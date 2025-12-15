# Lanes - Trade Compliance RAG System

## Complete System Design Documentation

---

## 1. Project Overview

**Lanes** is a Multi-Document Retrieval Augmented Generation (RAG) system specialized for trade compliance queries. It helps users answer questions about:

- HTS (Harmonized Tariff Schedule) codes and product classification
- Tariff rates and duty information
- Regulatory agency requirements (FDA, FCC, DOE, CBP)
- Import documentation and compliance procedures

### Key Features

| Feature | Description |
|---------|-------------|
| Multi-Document RAG | Search across multiple PDFs simultaneously |
| Two RAG Modes | Standard (fast) and Agentic (thorough with planning) |
| Conversation Memory | Maintains context across follow-up questions |
| Structured Output | JSON responses with HTS codes, agencies, documents |
| Smart Ingestion | Filters junk pages, auto-detects document types |
| Gradio UI | Drag-and-drop document upload with progress feedback |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           GRADIO UI                                      │
│  ┌─────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │   Documents Tab     │    │              Chat Tab                   │ │
│  │  - Upload PDFs      │    │  - Chat interface                       │ │
│  │  - Progress bar     │    │  - Mode selector (Standard/Agentic)     │ │
│  │  - Start Chatting   │    │  - Structured output sidebar            │ │
│  └─────────────────────┘    └─────────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CHAT MODULE (app/chat/)                          │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                      Entry Points (chat.py)                         ││
│  │  build_chat() ─────────────────► ConversationalRAG                  ││
│  │  build_agentic_chat() ─────────► AgenticRAG                         ││
│  │  build_trade_compliance_chat() ► ConversationalRAG (trade mode)     ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                   │                                      │
│           ┌───────────────────────┼───────────────────────┐             │
│           ▼                       ▼                       ▼             │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐       │
│  │ ConversationalRAG│   │   AgenticRAG    │   │   Prompts       │       │
│  │ (Standard Mode)  │   │ (Agentic Mode)  │   │                 │       │
│  │                  │   │                 │   │ - CONDENSE      │       │
│  │ Nodes:           │   │ Nodes:          │   │ - ANSWER        │       │
│  │ - condense       │   │ - plan          │   │ - PLANNER       │       │
│  │ - retrieve       │   │ - agent         │   │ - PLANNING      │       │
│  │ - generate       │   │ - tools         │   │ - TRADE_COMPLIANCE│     │
│  │                  │   │ - generate      │   │ - REFLECTION    │       │
│  └────────┬─────────┘   └────────┬────────┘   └─────────────────┘       │
│           │                      │                                       │
│           └──────────┬───────────┘                                       │
│                      ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                         TOOLS (trade_tools.py)                      ││
│  │  - search_documents()       - lookup_hts_code()                     ││
│  │  - check_tariffs()          - check_agency_requirements()           ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                      │                                                   │
│                      ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    VECTOR STORE (Pinecone)                          ││
│  │  - Index: "docs"                                                    ││
│  │  - Embedding: text-embedding-3-small (1536 dim)                     ││
│  │  - Metadata: pdf_id, corpus, doc_type, page, text                   ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    CHECKPOINTER (SQLite)                            ││
│  │  - File: instance/langgraph_checkpoints.db                          ││
│  │  - Stores: conversation state, message history                      ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Two RAG Modes

### 3.1 Standard RAG (ConversationalRAG)

**Best for**: Simple questions, fast responses (2-3 seconds)

**LLM Calls**: 2 per query

```
START
  │
  ▼
┌─────────────────────────┐
│ condense_question_node  │  ◄── GPT-3.5-turbo
│ Reformulate follow-ups  │      "What is it?" → "What is the HTS code for LED lamps?"
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ retrieve_documents_node │  ◄── Pinecone vector search
│ Fetch relevant chunks   │      k=5 chunks, filtered by corpus
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ generate_answer_node    │  ◄── GPT-4
│ Synthesize answer       │      Uses retrieved context + chat history
└───────────┬─────────────┘
            │
            ▼
           END
```

**Code**: `app/chat/graphs/conversational_rag.py`

### 3.2 Agentic RAG (AgenticRAG)

**Best for**: Complex multi-step queries (15-30 seconds)

**LLM Calls**: 3-5 per query

```
START
  │
  ▼
┌─────────────────────────┐
│      plan_node          │  ◄── GPT-4 (can use GPT-3.5)
│ Create execution plan   │      "Step 1: lookup_hts_code, Step 2: check_tariffs..."
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│      agent_node         │  ◄── GPT-4 with tools bound
│ Execute current step    │      Decides which tool to call
└───────────┬─────────────┘
            │
    ┌───────┴───────┐
    │               │
    ▼               ▼
┌────────┐    ┌─────────────────────────┐
│ tools  │    │ generate_answer_node    │
│        │◄───┤ (if no more tool calls) │
└───┬────┘    └───────────┬─────────────┘
    │                     │
    │                     ▼
    │                    END
    │
    └──────► back to agent_node (loop)
```

**Code**: `app/chat/graphs/agentic_rag.py`

---

## 4. Component Details

### 4.1 Tools (Agentic Mode)

Located in `app/chat/tools/trade_tools.py`:

| Tool | Purpose | Filter |
|------|---------|--------|
| `search_documents(query, doc_type, max_results)` | General corpus search | corpus=trade_compliance |
| `lookup_hts_code(product_description)` | Find HTS classification | doc_type=hts_schedule |
| `check_tariffs(hts_code, country_of_origin)` | Get duty rates | corpus=trade_compliance |
| `check_agency_requirements(product_type, agencies)` | Regulatory requirements | corpus=trade_compliance |

All tools filter by `corpus="trade_compliance"` to exclude test/mock data.

### 4.2 Output Schemas

Located in `app/chat/output_schemas.py`:

```python
# Basic structured answer
StructuredAnswer:
  - schema_version: "1.0"
  - answer: str
  - citations: List[SourceCitation]
  - confidence: "high" | "medium" | "low"
  - follow_up_questions: List[str]

# Trade compliance output
TradeComplianceOutput:
  - schema_version: "1.0"
  - answer: str
  - hts_codes: List[str]          # e.g., ["8539.50.00"]
  - agencies: List[str]           # e.g., ["DOE", "FCC", "CBP"]
  - required_documents: List[RequiredDocument]
  - tariff_info: TariffInfo
  - risk_flags: List[str]
  - citations: List[SourceCitation]

# Agent planning
AgentPlan:
  - schema_version: "1.0"
  - reasoning: str
  - steps: List[PlanStep]
```

### 4.3 Prompts

Located in `app/chat/prompts/trade_compliance.py`:

| Prompt | Used By | Purpose |
|--------|---------|---------|
| `CONDENSE_SYSTEM_PROMPT` | Standard RAG | Reformulate follow-up questions |
| `ANSWER_SYSTEM_PROMPT` | Standard RAG | Generate answers with citations |
| `STRUCTURED_ANSWER_PROMPT` | Standard RAG | JSON output with confidence |
| `TRADE_COMPLIANCE_PROMPT` | Both modes | Trade-specific JSON output |
| `PLANNER_PROMPT` | Agentic | Guide agent tool selection |
| `PLANNING_PROMPT` | Agentic | Generate explicit execution plan |
| `REFLECTION_PROMPT` | Agentic | Evaluate if more info needed |

### 4.4 Vector Store (Pinecone)

Located in `app/chat/vector_stores/pinecone.py`:

```python
# Configuration
Index: "docs"
Dimension: 1536 (text-embedding-3-small)
Metric: cosine

# Metadata per chunk
{
  "pdf_id": "Chapter_85_2025HTSRev32",
  "corpus": "trade_compliance",
  "doc_type": "hts_schedule",
  "page": 42,
  "text": "8539.50.00 Light-emitting diode (LED) lamps...",
  "source_file": "Chapter 85_2025HTSRev32.pdf"
}

# Retrieval filtering
scope_filter = {"corpus": "trade_compliance"}
```

### 4.5 Checkpointer (SQLite)

Located at `instance/langgraph_checkpoints.db`:

- Stores conversation state between requests
- Enables follow-up questions to access chat history
- Thread ID = conversation_id from ChatArgs

---

## 5. Data Flow - Complete Request Lifecycle

### User asks: "What tariffs apply to LED lamps from China?"

```
1. GRADIO UI
   └─► User types question, clicks Send

2. CHAT HANDLER (gradio_app.py)
   └─► Creates ChatArgs with conversation_id
   └─► Calls build_agentic_chat(chat_args)

3. AGENTIC RAG WRAPPER (chat.py)
   └─► Initializes AgenticRAG with SQLite checkpointer
   └─► Calls graph.invoke(question)

4. PLAN NODE (agentic_rag.py)
   └─► GPT-4 creates plan:
       Step 1: lookup_hts_code("LED lamps")
       Step 2: check_tariffs("8539.50", "China")
       Step 3: synthesize

5. AGENT NODE (agentic_rag.py)
   └─► GPT-4 with tools bound
   └─► Calls lookup_hts_code tool

6. TOOL EXECUTOR (agentic_rag.py)
   └─► Executes lookup_hts_code
   └─► Queries Pinecone: filter={corpus: trade_compliance, doc_type: hts_schedule}
   └─► Returns HTS 8539.50.00 info

7. AGENT NODE (loop back)
   └─► Calls check_tariffs tool

8. TOOL EXECUTOR
   └─► Queries Pinecone for tariff info
   └─► Returns Section 301 tariff data

9. GENERATE NODE (agentic_rag.py)
   └─► GPT-4 synthesizes final answer
   └─► Returns TradeComplianceOutput JSON

10. GRADIO UI
    └─► Displays answer in chat
    └─► Renders structured output in sidebar
```

---

## 6. File Structure

```
lanes/
├── app/
│   └── chat/
│       ├── __init__.py              # Public API exports
│       ├── chat.py                  # Entry points (build_chat, build_agentic_chat)
│       ├── models/__init__.py       # ChatArgs, Metadata models
│       ├── graphs/
│       │   ├── __init__.py
│       │   ├── conversational_rag.py  # Standard RAG graph
│       │   └── agentic_rag.py         # Agentic RAG graph
│       ├── prompts/
│       │   ├── __init__.py
│       │   └── trade_compliance.py    # All prompt templates
│       ├── tools/
│       │   ├── __init__.py
│       │   └── trade_tools.py         # 4 trade compliance tools
│       ├── output_schemas.py          # Pydantic models for responses
│       ├── vector_stores/
│       │   ├── __init__.py
│       │   └── pinecone.py            # Pinecone integration
│       ├── embeddings/
│       │   ├── __init__.py
│       │   └── openai.py              # OpenAI embeddings
│       ├── llms/
│       │   ├── __init__.py
│       │   └── chatopenai.py          # LLM factory
│       ├── ingest.py                  # Smart PDF ingestion
│       └── create_embeddings.py       # Legacy embedding creation
│
├── scripts/
│   ├── gradio_app.py                  # Main Gradio UI
│   ├── test_conversation_memory.py    # Memory tests
│   └── ingest_test_docs.py            # Test data ingestion
│
├── instance/
│   └── langgraph_checkpoints.db       # SQLite conversation store
│
├── .env                               # Environment variables
├── Pipfile                            # Dependencies
└── README4.md                         # This file
```

---

## 7. Gradio UI

### Documents Tab

```
┌─────────────────────────────────────────────────────────────────┐
│  Upload Trade Documents                                          │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Drag and drop PDF files here, or click to browse        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  [Upload & Process]  [Use Existing Documents]                   │
│                                                                  │
│  Status: Processing 2 of 4 files...                             │
│  ████████████████░░░░░░░░ 50%                                   │
│                                                                  │
│  Loaded Documents:                                               │
│  - Chapter_85_2025HTSRev32 (hts_schedule) - 1200 chunks         │
│  - Tariff_List_09.17.18 (section301_tariff) - 450 chunks        │
│                                                                  │
│  [Start Chatting]  ◄── Appears after upload                     │
└─────────────────────────────────────────────────────────────────┘
```

### Chat Tab

```
┌────────────────────────────────────────┬────────────────────────┐
│              Chat                       │  Summary & Sources     │
│                                         │                        │
│  User: What tariffs apply to LED        │  ### Execution Plan    │
│        lamps from China?                │  1. lookup_hts_code    │
│                                         │  2. check_tariffs      │
│  Assistant: LED lamps from China        │  3. synthesize         │
│  are classified under HTS 8539.50.00.   │                        │
│  The base duty rate is 3.9%, plus       │  ### HTS Codes         │
│  Section 301 tariff of 25%...           │  `8539.50.00`          │
│                                         │                        │
│  [Your Question                    ]    │  ### Tariff Info       │
│  [Send]                                 │  - Duty: 3.9%          │
│                                         │  - Section 301: +25%   │
│  Output Mode: ○ trade_compliance        │                        │
│              ○ standard_rag             │  ### Sources           │
│  ☑ Use Agentic Reasoning               │  [1] Chapter_85 p.42   │
└────────────────────────────────────────┴────────────────────────┘
```

---

## 8. Configuration

### Environment Variables (.env)

```bash
# Required
OPENAI_API_KEY=sk-proj-...
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=docs

# Optional
PINECONE_ENV_NAME=us-east-1
USE_SQLITE_CHECKPOINTER=true
LANGFUSE_PUBLIC_KEY=...        # For tracing
LANGFUSE_SECRET_KEY=...
```

### Model Configuration

| Component | Model | Temperature |
|-----------|-------|-------------|
| Planning (agentic) | gpt-4 | 0 |
| Agent (agentic) | gpt-4 | 0 |
| Answer generation | gpt-4 | 0 |
| Question condensing | gpt-3.5-turbo | 0 |
| Embeddings | text-embedding-3-small | - |

### Chunking Configuration

```python
# app/chat/ingest.py
chunk_size = 1200      # characters (~300 tokens)
chunk_overlap = 200    # characters
```

---

## 9. Known Limitations & Future Improvements

### Current Limitations

| Issue | Impact | Workaround |
|-------|--------|------------|
| GPT-4 rate limits (10K TPM) | 429 errors on rapid queries | Add max_retries=3, use gpt-3.5 for planning |
| Agentic mode is slow | 15-30 seconds per query | Use Standard mode for simple questions |
| No streaming in agentic mode | User waits for complete response | Planned improvement |
| Single corpus filter | Can't query across different corpora | Use pdf_id filter for specific docs |

### Recommended Improvements

1. **Rate Limit Handling**
   ```python
   # Add to all ChatOpenAI instances
   ChatOpenAI(model="gpt-4", max_retries=3, request_timeout=60)
   ```

2. **Switch Planning to GPT-3.5**
   ```python
   # In plan_node()
   llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
   ```

3. **Add Request Queuing**
   - Implement token budgeting per conversation
   - Queue requests when approaching rate limits

---

## 10. Quick Start

### 1. Install Dependencies

```bash
cd lanes
pipenv install
pipenv shell
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run the App

```bash
python scripts/gradio_app.py
```

### 4. Upload Documents

1. Open http://localhost:7860
2. Go to Documents tab
3. Drag and drop PDF files
4. Click "Upload & Process"
5. Click "Start Chatting"

### 5. Ask Questions

- "What is the HTS code for LED lamps?"
- "What tariffs apply to electronics from China?"
- "What documents do I need to import food products?"

---

## 11. API Reference

### Build Functions

```python
from app.chat import build_chat, build_agentic_chat, ChatArgs

# Standard RAG
chat = build_chat(chat_args, output_format="text")
result = chat.invoke("What is the HTS code for LED lamps?")

# Agentic RAG
chat = build_agentic_chat(chat_args, output_format="trade_compliance")
result = chat.invoke("What are all the requirements for importing LED lamps from China?")

# Result structure
{
    "answer": "LED lamps are classified under HTS 8539.50.00...",
    "citations": [...],
    "structured_output": {...},  # For trade_compliance mode
    "tool_calls": [...],         # For agentic mode
    "plan": [...]                # For agentic mode
}
```

### ChatArgs

```python
from app.chat.models import ChatArgs, Metadata

chat_args = ChatArgs(
    conversation_id="unique-id",
    pdf_id=None,                              # Not used in multi-doc mode
    metadata=Metadata(...),
    streaming=False,
    mode="multi_doc",
    scope_filter={"corpus": "trade_compliance"}
)
```

---

*Generated for Lanes Trade Compliance RAG System v1.0*
