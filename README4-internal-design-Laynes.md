# Lanes - Internal Design & End-to-End Flow

A deep-dive into how every component works internally.

---

## 1. High-Level Mental Model

Your system is essentially:

**Ingestion layer**
- PDFs → chunks → embeddings → Pinecone
- Metadata: `pdf_id`, `corpus="trade_compliance"`, `doc_type`, `page`, `text`

**Reasoning layer (LangGraph graphs)**
- `ConversationalRAG` (fast, 2 LLM calls)
- `AgenticRAG` (slower, multi-step with tools)

**State / memory**
- LangGraph SQLite checkpointer keyed by `conversation_id`
- Stores conversation state + message history

**Tools**
- `search_documents`
- `lookup_hts_code`
- `check_tariffs`
- `check_agency_requirements`

**Output schemas**
- `StructuredAnswer`
- `TradeComplianceOutput` (with HTS, agencies, docs, tariffs, risk_flags, citations)
- `AgentPlan`

**UI (Gradio)**
- Documents tab: upload + ingestion progress
- Chat tab: chat + mode selector + structured sidebar

---

## 2. End-to-End Data Flow (Standard vs Agentic)

### 2.1 Standard RAG Flow (ConversationalRAG)

**Good for:** "What is the HTS code for X?", "What is [concept]?"

**File:** `app/chat/graphs/conversational_rag.py`

#### Graph nodes:

##### `condense_question_node` (lines 145-181)

```python
LLM: ChatOpenAI(model="gpt-3.5-turbo", temperature=0)

Takes:
  - state["question"]           # latest user message
  - state["messages"]           # conversation history from checkpointer

Produces:
  - {"condensed_question": "..."}  # a standalone question (no pronouns, clear context)

Purpose:
  Handle follow-ups like "and what about if it's from China?"
  by turning it into a full question.

Internal logic:
  1. Filter messages to only HumanMessage/AIMessage (exclude SystemMessage)
  2. If ≤1 messages, return question as-is (no history to condense)
  3. Otherwise, invoke LLM with CONDENSE_SYSTEM_PROMPT:
     "Given a chat history and the latest user question which might reference
      context in the chat history, formulate a standalone question..."
```

##### `retrieve_documents_node` (lines 184-204)

```python
No LLM call - just Pinecone vector search

Takes:
  - state["condensed_question"] or state["question"]
  - state["scope_filter"]  # e.g., {"corpus": "trade_compliance"}
  - state["pdf_id"]        # for single-doc mode
  - state["mode"]          # "user_pdf" or "multi_doc"

Produces:
  - {"documents": [Document, Document, ...]}  # top-k chunks with metadata

Internal logic:
  1. Build filter based on mode:
     - multi_doc + scope_filter → use scope_filter
     - pdf_id set → {"pdf_id": pdf_id}
     - else → {} (no filter)
  2. Create Pinecone vector store connection
  3. Embed query with text-embedding-3-small (1536 dim)
  4. Search with k=5, apply filter
  5. Return Document objects with metadata:
     {pdf_id, doc_type, page, text, corpus, source_file}
```

##### `generate_answer_node` (lines 207-278)

```python
LLM: ChatOpenAI(model="gpt-4", temperature=0)

Takes:
  - state["condensed_question"] or state["question"]
  - state["documents"]      # retrieved chunks
  - state["output_format"]  # "text", "structured", or "trade_compliance"

Produces:
  - {"answer": "...", "structured_output": {...}, "citations": [...], "messages": [AIMessage]}

Internal logic:
  1. Format documents into context string with source markers:
     "[Source 1: Chapter_85_2025HTSRev32]\n8539.50.00 Light-emitting diode..."
  2. Extract citations from metadata:
     [{index: 1, pdf_id: "...", doc_type: "...", page: 42, snippet: "..."}]
  3. Choose prompt based on output_format:
     - "text" → ANSWER_SYSTEM_PROMPT (simple answer with inline [Source: X])
     - "structured" → STRUCTURED_ANSWER_PROMPT (JSON with confidence, follow-ups)
     - "trade_compliance" → TRADE_COMPLIANCE_PROMPT (JSON with HTS, agencies, docs)
  4. Invoke GPT-4 with prompt + context + question
  5. Parse JSON if structured/trade_compliance, handle parse errors gracefully
  6. Return answer + structured_output + citations + AIMessage for history
```

#### Lifecycle for a message:

```
Gradio
  → build_chat(chat_args)
    → ConversationalRAG(conversation_id, scope_filter, checkpointer)
      → graph.invoke(question, config={thread_id: conversation_id})
        → condense (GPT-3.5, ~500ms)
          → retrieve (Pinecone, ~200ms)
            → generate (GPT-4, ~2-3s)
              → {answer, citations, structured_output}
                → back to Gradio UI
```

**Total time:** ~3-4 seconds

---

### 2.2 Agentic RAG Flow (AgenticRAG)

**Good for:** "What tariffs apply if I import LED lamps from China? What documents do I need?"

Here you want planning + tool use + structured output.

**File:** `app/chat/graphs/agentic_rag.py`

#### Graph State (AgentState)

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]  # Full conversation
    question: str                    # Current user question
    plan: Optional[List[dict]]       # Execution plan from plan_node
    plan_reasoning: Optional[str]    # Why this plan
    current_step: int                # Index in plan (0-based)
    tool_outputs: List[str]          # Results from tool executions
    reflection: Optional[str]        # Agent's assessment
    final_answer: Optional[str]      # Generated answer
    iteration: int                   # Loop counter (max 5)
    scope_filter: Optional[dict]     # Pinecone filter
    output_format: str               # text/structured/trade_compliance
```

#### Graph nodes:

##### `plan_node` (lines 96-138)

```python
LLM: ChatOpenAI(model="gpt-4", temperature=0)
     (Could use gpt-3.5-turbo to save tokens)

Takes:
  - state["question"]
  - state["messages"]  # conversation history for context

Produces:
  - {"plan": [...], "plan_reasoning": "...", "current_step": 0}

Internal logic:
  1. Format chat history with _format_chat_history():
     "User: What is the HTS code for LED lamps?\nAssistant: LED lamps are..."
  2. Invoke LLM with PLANNING_PROMPT:
     - Lists available tools (search_documents, lookup_hts_code, etc.)
     - Asks for JSON output with steps
  3. Parse JSON response, fallback to single-step plan if parse fails
  4. Return plan structure:

{
  "schema_version": "1.0",
  "reasoning": "User wants to import LED lamps from China. Need HTS code, tariffs, and agency requirements.",
  "steps": [
    {"step_number": 1, "action": "lookup_hts_code", "description": "Find HTS code for LED lamps", "inputs": {"product_description": "LED lamps"}},
    {"step_number": 2, "action": "check_tariffs", "description": "Get tariff rates from China", "inputs": {"hts_code": "<from step 1>", "country_of_origin": "China"}},
    {"step_number": 3, "action": "check_agency_requirements", "description": "Find DOE and FCC requirements", "inputs": {"product_type": "LED lamps"}},
    {"step_number": 4, "action": "synthesize", "description": "Combine findings", "inputs": {}}
  ]
}
```

##### `agent_node` (lines 141-205)

```python
LLM: ChatOpenAI(model="gpt-4", temperature=0)
     With tools bound: llm.bind_tools(TRADE_TOOLS)

Takes:
  - state["question"]
  - state["messages"]
  - state["plan"] and state["current_step"]
  - state["tool_outputs"]  # previous tool results
  - state["iteration"]

Produces:
  - {"messages": [AIMessage with tool_calls], "iteration": n+1, "current_step": next}

Internal logic:
  1. Format conversation history
  2. Build system prompt with PLANNER_PROMPT:
     - Describes available tools
     - Shows previous tool results
     - Includes plan context: "CURRENT STEP: 2 - check_tariffs: Get tariff rates..."
  3. Invoke GPT-4 with tools bound
  4. LLM decides:
     - Call a tool → returns AIMessage with tool_calls
     - No tool needed → returns AIMessage with content only
  5. Advance current_step index
  6. Return updated messages and iteration count
```

##### `tool_executor_node` (lines 208-253)

```python
No LLM call - executes tool functions

Takes:
  - state["messages"][-1]  # last message with tool_calls

Produces:
  - {"tool_outputs": [...], "messages": [ToolMessage, ToolMessage, ...]}

Internal logic:
  1. Check if last message has tool_calls attribute
  2. For each tool_call:
     - Extract tool_name and tool_args
     - Look up function in tool_map: {t.name: t for t in TRADE_TOOLS}
     - Invoke: tool_map[tool_name].invoke(tool_args)
     - Catch errors, format as error message
     - Create ToolMessage with result and tool_call_id
  3. Append results to state["tool_outputs"]
  4. Return ToolMessages for conversation history
```

##### `should_continue` (lines 256-279)

```python
Routing function - no LLM call

Takes:
  - state["messages"]
  - state["iteration"]

Returns:
  - "tools" if last message has tool_calls
  - "generate" otherwise (or if iteration >= 5)

Internal logic:
  1. Check iteration count (max 5 to prevent infinite loops)
  2. Check if last message has tool_calls attribute
  3. Route accordingly
```

##### `generate_answer_node` (lines 282-370)

```python
LLM: ChatOpenAI(model="gpt-4", temperature=0)

Takes:
  - state["question"]
  - state["messages"]
  - state["tool_outputs"]  # all accumulated tool results
  - state["output_format"]

Produces:
  - {"final_answer": "...", "messages": [AIMessage]}

Internal logic:
  1. Format chat history
  2. Combine all tool_outputs as context:
     "[search_documents]: [Result 1] Source: Chapter_85..."
     "[check_tariffs]: [Tariff]: HTS 8539.50.00 from China..."
  3. Choose prompt based on output_format:
     - "trade_compliance" → JSON with HTS codes, agencies, documents, tariffs
     - "structured" → JSON with citations, confidence, follow-ups
     - "text" → Natural language with inline citations
  4. Invoke GPT-4
  5. Parse JSON if structured, extract answer field
  6. Return final_answer + AIMessage for history
```

#### Graph edges:

```python
START → plan → agent → (conditional) → tools OR generate → END
                 ↑                         │
                 └─────────────────────────┘ (loop back after tools)
```

#### Lifecycle for a complex query:

```
Gradio
  → build_agentic_chat(chat_args)
    → AgenticRAG(conversation_id, scope_filter, checkpointer)
      → graph.invoke(question, config={thread_id: conversation_id})

        → plan_node (GPT-4, ~2s)
            Creates: {"steps": [lookup_hts, check_tariffs, check_agency, synthesize]}

        → agent_node (GPT-4 with tools, ~1.5s)
            Decides: Call lookup_hts_code("LED lamps")

        → tool_executor_node (~500ms)
            Executes: lookup_hts_code → Pinecone query → returns HTS info

        → agent_node (GPT-4, ~1.5s)  [loop back]
            Decides: Call check_tariffs("8539.50.00", "China")

        → tool_executor_node (~500ms)
            Executes: check_tariffs → Pinecone query → returns tariff info

        → agent_node (GPT-4, ~1.5s)  [loop back]
            Decides: Call check_agency_requirements("LED lamps")

        → tool_executor_node (~500ms)
            Executes: check_agency_requirements → returns DOE, FCC info

        → agent_node (GPT-4, ~1s)  [loop back]
            Decides: No more tools needed

        → generate_answer_node (GPT-4, ~3s)
            Synthesizes all tool outputs into final answer

        → {answer, citations, structured_output, tool_calls, plan}
          → back to Gradio UI
```

**Total time:** ~15-25 seconds (depends on tool call count)

---

## 3. Tool Internals

**File:** `app/chat/tools/trade_tools.py`

All tools are decorated with `@tool` from langchain_core.tools and share a common pattern:

### 3.1 `search_documents`

```python
@tool
def search_documents(query: str, doc_type: Optional[str] = None, max_results: int = 5) -> str:

Purpose: General search across all documents in corpus

Filter logic:
  search_filter = {"corpus": DEFAULT_CORPUS}  # "trade_compliance"
  if doc_type:
      search_filter["doc_type"] = doc_type

Pinecone call:
  retriever = vector_store.as_retriever(search_kwargs={"k": max_results, "filter": search_filter})
  docs = retriever.invoke(query)

Returns:
  "[Result 1] Source: Chapter_85_2025HTSRev32 (Type: hts_schedule, Page: 42)\n8539.50.00..."
  "\n\n---\n\n"
  "[Result 2] Source: Tariff_List_09.17.18 (Type: section301_tariff, Page: 15)\n..."
```

### 3.2 `lookup_hts_code`

```python
@tool
def lookup_hts_code(product_description: str) -> str:

Purpose: Find HTS classification for a product

Filter logic:
  search_filter = {"corpus": DEFAULT_CORPUS, "doc_type": "hts_schedule"}

Pinecone call:
  retriever with k=3
  query = f"HTS code classification for {product_description}"

Returns:
  "[Chapter_85_2025HTSRev32]: 8539.50.00 Light-emitting diode (LED) lamps..."
```

### 3.3 `check_tariffs`

```python
@tool
def check_tariffs(hts_code: str, country_of_origin: str) -> str:

Purpose: Get duty rates for HTS code from specific country

Filter logic:
  search_filter = {"corpus": DEFAULT_CORPUS}
  # Note: searches across all doc_types to find tariff info

Pinecone call:
  retriever with k=5
  query = f"tariff duty rate for HTS {hts_code} from {country_of_origin} section 301"

Returns:
  "[Tariff_List_09.17.18]: Products of China... 25% additional tariff..."
```

### 3.4 `check_agency_requirements`

```python
@tool
def check_agency_requirements(product_type: str, agencies: Optional[List[str]] = None) -> str:

Purpose: Find regulatory requirements for importing a product

Filter logic:
  search_filter = {"corpus": DEFAULT_CORPUS}
  # Searches for CBP, FDA, FCC, DOE requirements

Pinecone call:
  retriever with k=5
  query = f"regulatory requirements for importing {product_type} CBP customs"
  if agencies:
      query += f" agencies: {', '.join(agencies)}"

Returns:
  "[inporting_in_the_US]: LED lamps require DOE energy efficiency certification..."
```

---

## 4. State Management & Memory

### 4.1 LangGraph Checkpointer

**File:** `instance/langgraph_checkpoints.db` (SQLite)

```python
# In chat.py, checkpointer is initialized:
if os.getenv("USE_SQLITE_CHECKPOINTER", "true").lower() == "true":
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect("instance/langgraph_checkpoints.db", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
else:
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()
```

**What gets stored:**
- `thread_id` = conversation_id
- `messages` = full conversation history (HumanMessage, AIMessage, ToolMessage)
- `question`, `condensed_question`, `documents`, `answer`
- For agentic: `plan`, `current_step`, `tool_outputs`, `iteration`

**How follow-ups work:**
1. User asks: "What is the HTS code for LED lamps?"
2. System answers, state saved to SQLite with thread_id
3. User asks: "What about the tariffs?"
4. Graph reloads state for that thread_id
5. `condense_question_node` sees history, reformulates to:
   "What are the tariffs for LED lamps (HTS 8539.50.00)?"

### 4.2 ConversationState vs AgentState

```python
# Standard RAG
ConversationState:
  messages: List[BaseMessage]      # Conversation history
  question: str                    # Current question
  condensed_question: str          # Reformulated question
  documents: List[Document]        # Retrieved chunks
  answer: str                      # Final answer
  citations: List[dict]            # Source citations
  structured_output: Optional[dict]

# Agentic RAG
AgentState:
  messages: List[BaseMessage]      # Conversation history
  question: str                    # Current question
  plan: List[dict]                 # Execution steps
  plan_reasoning: str              # Why this plan
  current_step: int                # Current step index
  tool_outputs: List[str]          # Tool results
  iteration: int                   # Loop count
  final_answer: str                # Final answer
```

---

## 5. Output Schemas

**File:** `app/chat/output_schemas.py`

### 5.1 SourceCitation

```python
class SourceCitation(BaseModel):
    pdf_id: str           # "Chapter_85_2025HTSRev32"
    doc_type: Optional[str]  # "hts_schedule"
    page: Optional[int]   # 42
    snippet: str          # "8539.50.00 Light-emitting diode..."
```

### 5.2 StructuredAnswer

```python
class StructuredAnswer(BaseModel):
    schema_version: str = "1.0"
    answer: str                          # Main answer text
    citations: List[SourceCitation]      # Source references
    confidence: str = "medium"           # "high" | "medium" | "low"
    follow_up_questions: List[str] = []  # Suggested next questions
```

### 5.3 TradeComplianceOutput

```python
class TradeComplianceOutput(BaseModel):
    schema_version: str = "1.0"
    answer: str                                   # Main answer
    hts_codes: List[str] = []                    # ["8539.50.00"]
    agencies: List[str] = []                     # ["DOE", "FCC", "CBP"]
    required_documents: List[RequiredDocument]   # [{agency, document_name, description}]
    tariff_info: Optional[TariffInfo]            # {duty_rate, special_programs, country_specific}
    risk_flags: List[str] = []                   # Compliance warnings
    citations: List[SourceCitation] = []

class RequiredDocument(BaseModel):
    agency: str           # "DOE"
    document_name: str    # "Certificate of Compliance"
    description: str      # "Energy efficiency certification"

class TariffInfo(BaseModel):
    duty_rate: Optional[str]        # "3.9%"
    special_programs: List[str]     # ["Section 301"]
    country_specific: Optional[str] # "China: +25% additional tariff"
```

### 5.4 AgentPlan

```python
class AgentPlan(BaseModel):
    schema_version: str = "1.0"
    steps: List[PlanStep] = []
    reasoning: Optional[str]

class PlanStep(BaseModel):
    step_number: int      # 1
    action: str           # "lookup_hts_code"
    description: str      # "Find HTS code for LED lamps"
    inputs: dict = {}     # {"product_description": "LED lamps"}
```

---

## 6. Prompts in Detail

**File:** `app/chat/prompts/trade_compliance.py`

### 6.1 CONDENSE_SYSTEM_PROMPT

```
Used by: condense_question_node (Standard RAG)
Purpose: Reformulate follow-up questions

"Given a chat history and the latest user question which might reference
context in the chat history, formulate a standalone question which can be
understood without the chat history. Do NOT answer the question, just
reformulate it if needed and otherwise return it as is."
```

### 6.2 ANSWER_SYSTEM_PROMPT

```
Used by: generate_answer_node (Standard RAG, text mode)
Purpose: Generate answers with inline citations

"You are an assistant for question-answering tasks. Use the following pieces
of retrieved context to answer the question. If you don't know the answer,
just say that you don't know. Keep the answer concise but informative.

IMPORTANT: When citing information, reference the source document using
[Source: document_id] format.

Context:
{context}"
```

### 6.3 TRADE_COMPLIANCE_PROMPT

```
Used by: generate_answer_node (both modes, trade_compliance format)
Purpose: Structured trade compliance output

"You are a trade compliance expert assistant. Analyze the context and answer
the question about import/export compliance.

Context:
{context}

Respond with a JSON object containing:
- "schema_version": "1.0"
- "answer": Your main answer with inline citations [Source: doc_id]
- "hts_codes": Array of relevant HTS codes mentioned
- "agencies": Array of regulatory agencies (FDA, CBP, DOT, etc.)
- "required_documents": Array of {agency, document_name, description}
- "tariff_info": Object with {duty_rate, special_programs, country_specific}
- "risk_flags": Array of compliance warnings or risks
- "citations": Array of {pdf_id, doc_type, page, snippet}

Question: {question}"
```

### 6.4 PLANNER_PROMPT

```
Used by: agent_node (Agentic RAG)
Purpose: Guide agent's tool selection

"You are a trade compliance research assistant with access to tools.

Your task is to help users with questions about:
- HTS codes and product classification
- Tariff rates and trade programs
- Regulatory agency requirements (FDA, FCC, DOT, etc.)
- Import documentation requirements

Available tools:
1. search_documents: General search across all documents
2. lookup_hts_code: Find HTS classification for a product
3. check_tariffs: Get tariff rates for an HTS code from a country
4. check_agency_requirements: Find regulatory requirements for a product

Previous conversation context:
{chat_history}

Current user question: {question}

Previous tool results (if any):
{tool_results}

IMPORTANT: If the current question is a follow-up (like "what is it?", "tell me more"),
use the conversation context above to understand what the user is referring to."
```

### 6.5 PLANNING_PROMPT

```
Used by: plan_node (Agentic RAG)
Purpose: Generate explicit execution plan

"You are a trade compliance expert planning an analysis.

Given the conversation context and current question, create a step-by-step plan...

Previous Conversation:
{chat_history}

Current Question: {question}

IMPORTANT: If the current question is a follow-up, use the previous conversation
to understand what the user is referring to.

Output a JSON object with:
- "schema_version": "1.0"
- "reasoning": Brief explanation of your approach
- "steps": Array of step objects

Each step should have:
- "step_number": int (starting at 1)
- "action": tool name or "synthesize" for final step
- "description": what this step accomplishes
- "inputs": parameters for the tool (if applicable)

Respond ONLY with valid JSON."
```

---

## 7. Ingestion Pipeline

**File:** `app/chat/ingest.py`

### 7.1 `should_skip_page`

```python
def should_skip_page(text: str) -> bool:
    """Filter junk pages"""

    Skips:
    - len(text) < 100              # Too short
    - "table of contents" in text  # TOC pages
    - "this page intentionally"    # Blank page notices
    - text.startswith("index")     # Index pages at end
    - "chapter"/"section" only     # Header-only pages
```

### 7.2 `infer_doc_type`

```python
def infer_doc_type(filename: str) -> str:
    """Auto-detect document type from filename"""

    Mappings:
    - "chapter 85", "hts" → "hts_schedule"
    - "tariff", "301" → "section301_tariff"
    - "import", "cbp" → "cbp_guide"
    - "govpub" → "gov_publication"
    - "fda", "fcc", "doe" → "agency_regulation"
    - else → "general"
```

### 7.3 `ingest_pdf`

```python
def ingest_pdf(pdf_path, corpus, doc_type, chunk_size, chunk_overlap, progress_callback):
    """Main ingestion function"""

    Steps:
    1. Load PDF with PyPDFLoader
    2. Filter junk pages with should_skip_page()
    3. Chunk with RecursiveCharacterTextSplitter:
       - chunk_size=1200 (characters, ~300 tokens)
       - chunk_overlap=200
       - separators=["\n\n", "\n", ". ", " ", ""]
    4. Add metadata to each chunk:
       - corpus: "trade_compliance"
       - doc_type: "hts_schedule" (inferred or provided)
       - pdf_id: "Chapter_85_2025HTSRev32" (from filename)
       - source_file: "Chapter 85_2025HTSRev32.pdf"
       - page: original page number
    5. Upsert to Pinecone via vector_store.add_documents()
    6. Return stats: {filename, pdf_id, doc_type, pages, chunks, skipped}
```

---

## 8. Gradio UI Handlers

**File:** `scripts/gradio_app.py`

### 8.1 `handle_upload`

```python
def handle_upload(files, state, progress=gr.Progress()):
    """Handle PDF upload with progress bar"""

    Flow:
    1. Validate files (must be PDFs)
    2. For each PDF:
       a. Update progress bar: "Uploading 1/4: Chapter_85..."
       b. Call ingest_pdf() with progress_callback
       c. Update progress bar: "✓ Completed Chapter_85..."
    3. Update state["documents_loaded"] = True
    4. Return status + doc_list + state + show_start_button
```

### 8.2 `chat_handler`

```python
def chat_handler(message, history, mode, use_agentic, state):
    """Main chat handler"""

    Flow:
    1. Get conversation_id from state
    2. Create ChatArgs with scope_filter={"corpus": "trade_compliance"}
    3. Build appropriate chat:
       if mode == "trade_compliance":
           if use_agentic:
               chat = build_agentic_trade_chat(chat_args)
           else:
               chat = build_trade_compliance_chat(chat_args)
       else:
           if use_agentic:
               chat = build_agentic_chat(chat_args)
           else:
               chat = build_chat(chat_args)
    4. Invoke: result = chat.invoke(message)
    5. Extract: answer, citations, structured_output, tool_calls, plan
    6. Update history with user message + assistant response
    7. Render sidebar with structured output / citations
    8. Return updated history + sidebar + state
```

---

## 9. Component Mapping

| Component | File | Purpose |
|-----------|------|---------|
| Entry points | `app/chat/chat.py` | `build_chat()`, `build_agentic_chat()`, etc. |
| Standard RAG graph | `app/chat/graphs/conversational_rag.py` | condense → retrieve → generate |
| Agentic RAG graph | `app/chat/graphs/agentic_rag.py` | plan → agent → tools → generate |
| Tools | `app/chat/tools/trade_tools.py` | 4 Pinecone-backed search tools |
| Prompts | `app/chat/prompts/trade_compliance.py` | All prompt templates |
| Output schemas | `app/chat/output_schemas.py` | Pydantic models for JSON output |
| Vector store | `app/chat/vector_stores/pinecone.py` | Pinecone connection + retriever builder |
| Ingestion | `app/chat/ingest.py` | Smart PDF chunking + upload |
| Gradio UI | `scripts/gradio_app.py` | Documents tab + Chat tab |
| Checkpointer | `instance/langgraph_checkpoints.db` | SQLite conversation state |

---

## 10. LLM Call Summary

### Standard RAG (2 calls per query)

| Node | Model | Purpose | ~Time |
|------|-------|---------|-------|
| condense_question_node | gpt-3.5-turbo | Reformulate follow-ups | 500ms |
| generate_answer_node | gpt-4 | Generate answer | 2-3s |

### Agentic RAG (3-6 calls per query)

| Node | Model | Purpose | ~Time |
|------|-------|---------|-------|
| plan_node | gpt-4 | Create execution plan | 2s |
| agent_node (1st) | gpt-4 | Decide tool 1 | 1.5s |
| agent_node (2nd) | gpt-4 | Decide tool 2 | 1.5s |
| agent_node (3rd) | gpt-4 | Decide tool 3 | 1.5s |
| agent_node (final) | gpt-4 | No more tools | 1s |
| generate_answer_node | gpt-4 | Synthesize answer | 3s |

**Note:** Tool execution is Pinecone only (no LLM), ~500ms each.

---

## 11. Known Issues & Recommended Fixes

### Rate Limits (429 errors)

**Problem:** GPT-4 limit is 10K tokens/minute, agentic uses 5-6 calls.

**Fix:**
```python
# Add to all ChatOpenAI instances
llm = ChatOpenAI(
    model="gpt-4",
    temperature=0,
    max_retries=3,        # Auto-retry on 429
    request_timeout=60    # Don't hang forever
)

# In plan_node, use cheaper model
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, max_retries=3)
```

### Agentic Follow-ups

**Problem:** Agentic mode should use conversation history for follow-ups.

**Status:** Fixed - `plan_node` and `agent_node` now include `{chat_history}` from `_format_chat_history()`.

### Mock Data Leaking

**Problem:** Mock/test documents (corpus="test_corpus") appearing in results.

**Status:** Fixed - All tools now filter by `corpus="trade_compliance"`.

---

*This document describes the internal design of Lanes v1.0*