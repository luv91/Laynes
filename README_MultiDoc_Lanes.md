# Multi-Document RAG System: Design Document

---

## Part 1: Current System Design

### 1.1 What We Have Today

This is a **PDF Chat Application** - users upload a PDF and have a conversation about its contents.

```
┌─────────────────────────────────────────────────────────────────┐
│                     CURRENT ARCHITECTURE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  USER FLOW:                                                     │
│  1. User uploads a PDF                                          │
│  2. System chunks and embeds it                                 │
│  3. User asks questions about THAT PDF                          │
│  4. System retrieves relevant chunks and answers                │
│  5. Conversation continues with memory of previous Q&A          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 System Components (5 Layers)

#### A. Document Layer
- User uploads one PDF
- Celery background task processes it:
  - Split into chunks (500 chars, 100 overlap)
  - Add metadata: `pdf_id`, `page`, `text`
  - Compute embeddings (OpenAI)
  - Store in Pinecone

#### B. Retrieval Layer
- Pinecone retriever with filter: `{"pdf_id": <this_pdf>}`
- Used inside `ConversationalRetrievalChain`:
  - `CondenseQuestionChain` (rewrites follow-up questions)
  - `RetrievalQA` chain (retrieve + generate answer)

#### C. Memory Layer
- `SqlMessageHistory`: stores messages in SQLite by `conversation_id`
- `ConversationBufferMemory`: provides chat history to the chain
- Enables multi-turn conversations ("What about X?" → understands context)

#### D. Chat + Streaming Layer
- `/api/conversations/.../messages` endpoint
- `build_chat(chat_args)` function:
  - Selects LLM, retriever, memory based on Redis scores
  - Builds `StreamingConversationalRetrievalChain`
- Two LLM instances:
  - Non-streaming for `CondenseQuestionChain`
  - Streaming for final answer generation
- Custom `StreamingHandler` for token-by-token output

#### E. Infrastructure Layer
- Flask: API + auth + sessions
- Celery: background PDF processing
- Redis: component scores / feedback tracking
- Pinecone: vector store
- SQLite: User, PDF, Conversation, Message models
- Langfuse: observability / tracing

### 1.3 Key Constraint of Current Design

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   THE ENTIRE SYSTEM IS BUILT AROUND:                           │
│                                                                 │
│            1 conversation  ↔  1 pdf_id                         │
│                                                                 │
│   Every retrieval filters by: {"pdf_id": current_pdf_id}       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 How Conversation Memory Works

```
MESSAGE 1: "What is chapter 3 about?"
┌─────────────────────────────────────────────────────────────────┐
│ 1. memory.messages → [] (empty)                                 │
│ 2. No history, question goes straight to retriever              │
│ 3. Retriever finds chunks from pdf_id, LLM answers              │
│ 4. Both messages saved to DB                                    │
└─────────────────────────────────────────────────────────────────┘

MESSAGE 2: "What about the exceptions?"
┌─────────────────────────────────────────────────────────────────┐
│ 1. memory.messages → [Q1, A1]                                   │
│ 2. CondenseQuestionChain rewrites:                              │
│    "What about the exceptions?"                                 │
│    + context about chapter 3                                    │
│    → "What are the exceptions mentioned in chapter 3?"          │
│ 3. Retriever searches for rewritten question                    │
│ 4. LLM answers with proper context                              │
└─────────────────────────────────────────────────────────────────┘

MESSAGE 3: "Summarize those for me"
┌─────────────────────────────────────────────────────────────────┐
│ 1. memory.messages → [Q1, A1, Q2, A2]                          │
│ 2. CondenseQuestionChain rewrites:                              │
│    → "Summarize the exceptions in chapter 3"                    │
│ 3. Retriever + LLM answers                                      │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight**: The `CondenseQuestionChain` is what makes follow-up questions work.
It uses chat history to rewrite vague questions into standalone queries.

### 1.5 File Structure Reference

```
app/
├── chat/
│   ├── chains/
│   │   ├── retrieval.py      # StreamingConversationalRetrievalChain
│   │   ├── streamable.py     # Streaming mixin
│   │   └── traceable.py      # Langfuse tracing mixin
│   ├── embeddings/
│   │   └── openai.py         # OpenAIEmbeddings
│   ├── llms/
│   │   └── __init__.py       # LLM builders (gpt-4, gpt-3.5-turbo)
│   ├── memories/
│   │   ├── histories/
│   │   │   └── sql_history.py    # SqlMessageHistory
│   │   ├── sql_memory.py         # ConversationBufferMemory builder
│   │   └── window_memory.py      # Window memory variant
│   ├── vector_stores/
│   │   ├── pinecone.py       # Pinecone init + build_retriever
│   │   └── __init__.py       # retriever_map
│   ├── callbacks/
│   │   └── stream.py         # StreamingHandler
│   ├── chat.py               # build_chat() main function
│   ├── create_embeddings.py  # PDF → chunks → Pinecone
│   └── score.py              # Component scoring logic
├── web/
│   ├── views/
│   │   ├── auth_views.py
│   │   ├── pdf_views.py
│   │   └── conversation_views.py
│   ├── db/models/
│   │   ├── user.py
│   │   ├── pdf.py
│   │   ├── conversation.py
│   │   └── message.py
│   └── api.py
└── celery/
    └── worker.py
```

---

## Part 2: Problem Statement

### 2.1 Original Problem (Solved)
> "I have a PDF and want to ask questions about it"

The current system solves this well.

### 2.2 New Problem Statement
> "I have 4-5 documents and want to chat across ALL of them with memory"

**Example use case (Trade Compliance - future vision):**
- Document 1: HTS Schedule (tariff codes)
- Document 2: Section 301 Tariff Rules
- Document 3: FDA Regulations
- Document 4: DOT Requirements
- Document 5: CBP Guidance

**User wants to ask:**
- "What's the HTS code for LED bulbs?" → needs HTS Schedule
- "What tariffs apply if it's from China?" → needs HTS + Section 301
- "What agencies need to approve this?" → needs FDA + DOT docs
- "Tell me more about the FDA requirements" → needs FDA doc + conversation memory

### 2.3 The Gap

| Aspect | Current System | What We Need |
|--------|----------------|--------------|
| Documents | 1 (user uploads) | 4-5 (pre-loaded or selected) |
| Retrieval scope | Single `pdf_id` | Multiple docs / corpus |
| Chunk metadata | `pdf_id`, `page` | `pdf_id`, `corpus`, `doc_type`, etc. |
| Memory | Works | Keep as-is |
| Chat UI | Works | Keep as-is |
| Streaming | Works | Keep as-is |

**The gap is narrow**: We only need to generalize the retrieval scope.

---

## Part 3: Proposed Design

### 3.1 Core Concept: From "pdf_id" to "scope"

```
BEFORE:
┌─────────────────────────────────────────────────────────────────┐
│  Conversation has: pdf_id                                       │
│  Retriever filter: {"pdf_id": pdf_id}                          │
│  Result: chunks from ONE document                               │
└─────────────────────────────────────────────────────────────────┘

AFTER:
┌─────────────────────────────────────────────────────────────────┐
│  Conversation has: mode + scope_filter                          │
│  Retriever filter: {"corpus": "gov_trade"} or                  │
│                    {"pdf_id": {"$in": [doc1, doc2, doc3]}}     │
│  Result: chunks from MULTIPLE documents                         │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 What Changes

#### A. Document Layer (Minor Change)
- **Keep**: Same ingestion pipeline (chunk → embed → store)
- **Add**: Richer metadata per chunk:
  ```
  Current:  {pdf_id, page, text}
  New:      {pdf_id, page, text, corpus, doc_type, ...}
  ```
- **Add**: Concept of "system documents" (pre-loaded, not user-uploaded)

#### B. Retrieval Layer (Main Change)
- **Change**: Generalize filter from `pdf_id` to `scope_filter`
- **Add**: Mode concept on Conversation:
  - `mode = "user_pdf"` → filter by single pdf_id (existing behavior)
  - `mode = "multi_doc"` → filter by corpus or list of pdf_ids

#### C. Memory Layer (No Change)
- `SqlMessageHistory` works regardless of retrieval scope
- `ConversationBufferMemory` unchanged
- `CondenseQuestionChain` unchanged
- Multi-turn conversations work exactly the same

#### D. Chat + Streaming Layer (Minor Change)
- **Change**: `build_chat()` branches based on mode:
  - If `mode = "user_pdf"`: use `{"pdf_id": pdf_id}` filter
  - If `mode = "multi_doc"`: use `scope_filter` from conversation
- **Keep**: Streaming, two LLMs, all chat logic unchanged

#### E. Infrastructure Layer (No Change)
- Flask, Celery, Redis, Pinecone, SQLite, Langfuse all stay the same

### 3.3 New Data Model Fields

**Conversation Model (add fields):**
```
mode: string          # "user_pdf" | "multi_doc"
scope_filter: JSON    # e.g., {"corpus": "gov_trade"} or
                      #       {"pdf_id": {"$in": ["id1", "id2"]}}
```

**Pdf Model (add fields):**
```
is_system: boolean    # True for pre-loaded docs, False for user uploads
corpus: string        # e.g., "gov_trade", "user_docs", null
doc_type: string      # e.g., "hts_schedule", "regulation"
```

**Chunk Metadata (in Pinecone):**
```
Current:  {pdf_id, page, text}
New:      {pdf_id, page, text, corpus, doc_type, ...}
```

### 3.4 System Flow (Multi-Doc Mode)

```
┌─────────────────────────────────────────────────────────────────┐
│                    MULTI-DOC CONVERSATION FLOW                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. CREATE CONVERSATION                                         │
│     POST /api/conversations                                     │
│     {                                                           │
│       "mode": "multi_doc",                                      │
│       "scope_filter": {"corpus": "gov_trade"}                  │
│       // OR: {"pdf_id": {"$in": ["doc1", "doc2", "doc3"]}}     │
│     }                                                           │
│                                                                 │
│  2. SEND MESSAGE                                                │
│     POST /api/conversations/{id}/messages                       │
│     {"content": "What is HTS code 8539?"}                      │
│                                                                 │
│  3. BUILD CHAT                                                  │
│     build_chat(chat_args):                                      │
│       - Check mode = "multi_doc"                                │
│       - Build retriever with scope_filter (not pdf_id)         │
│       - Load memory (same as before)                            │
│       - Return StreamingConversationalRetrievalChain            │
│                                                                 │
│  4. PROCESS MESSAGE                                             │
│     a. CondenseQuestionChain (if follow-up)                    │
│     b. Retriever searches across ALL docs in scope             │
│     c. LLM synthesizes answer from multi-doc chunks            │
│     d. Stream response                                          │
│     e. Save to memory                                           │
│                                                                 │
│  5. FOLLOW-UP MESSAGE                                           │
│     {"content": "What about LEDs specifically?"}               │
│     - Memory provides history                                   │
│     - CondenseQuestionChain rewrites to standalone              │
│     - Retriever searches across same scope                      │
│     - Works exactly like single-doc mode                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 Backward Compatibility

The existing single-doc behavior is preserved:
- `mode = "user_pdf"` (default) works exactly as before
- No changes to existing conversations or API contracts
- Just adding new capability alongside existing one

---

## Part 4: Testing Strategy

### 4.1 What to Test

#### Test 1: Multi-Doc Retrieval
**Goal**: Verify retriever returns chunks from multiple documents

**Setup**:
- Ingest 3 test documents into Pinecone with different `pdf_id` values
- Tag all with same `corpus = "test_corpus"`

**Test**:
- Create retriever with filter `{"corpus": "test_corpus"}`
- Query: "Find information about X"
- Verify: Results include chunks from all 3 documents (check `pdf_id` in metadata)

**Success criteria**: Retrieved chunks have different `pdf_id` values

---

#### Test 2: Memory Works Across Multi-Doc
**Goal**: Verify conversation memory works when retrieving from multiple docs

**Setup**:
- Create conversation with `mode = "multi_doc"`
- 3 documents in scope

**Test sequence**:
1. Message 1: "What does document A say about topic X?"
   - Verify: Answer cites document A
2. Message 2: "What about document B?"
   - Verify: System understands "what about" refers to topic X
   - Verify: Answer cites document B
3. Message 3: "Compare them"
   - Verify: System understands "them" = doc A and doc B on topic X
   - Verify: Answer references both documents

**Success criteria**: Follow-up questions work correctly with multi-doc context

---

#### Test 3: Scope Isolation
**Goal**: Verify conversations only retrieve from their specified scope

**Setup**:
- Corpus A: 2 documents about "apples"
- Corpus B: 2 documents about "oranges"
- Conversation 1: scope = corpus A
- Conversation 2: scope = corpus B

**Test**:
- Conversation 1: "Tell me about fruit" → should only mention apples
- Conversation 2: "Tell me about fruit" → should only mention oranges

**Success criteria**: Each conversation stays within its scope

---

#### Test 4: Mode Switching (Backward Compatibility)
**Goal**: Verify old single-doc mode still works

**Setup**:
- Upload a user PDF (existing flow)
- Create conversation with `mode = "user_pdf"` (or default)

**Test**:
- Ask questions about the PDF
- Verify: Works exactly as before
- Verify: Only retrieves from that specific pdf_id

**Success criteria**: No regression in existing functionality

---

#### Test 5: Source Attribution
**Goal**: Verify we can tell which document each chunk came from

**Setup**:
- 3 documents in scope
- Each has distinct content

**Test**:
- Ask question that requires info from multiple docs
- Check retrieved chunks

**Verify**:
- Each chunk has `pdf_id` in metadata
- Can map `pdf_id` back to document name
- Answer can cite "According to Document A..." and "Document B states..."

**Success criteria**: Clear attribution to source documents

---

### 4.2 Testing Approach

```
UNIT TESTS:
├── Test retriever filter construction
│   - Given mode="multi_doc", scope={"corpus": "X"}
│   - Verify filter built correctly
│
├── Test metadata enrichment during ingestion
│   - Given PDF with corpus="X", doc_type="Y"
│   - Verify chunks have correct metadata in Pinecone
│
└── Test conversation model
    - Verify mode and scope_filter fields save/load correctly

INTEGRATION TESTS:
├── End-to-end multi-doc conversation
│   - Ingest 3 docs → Create conversation → Send messages → Verify responses
│
├── Memory persistence across requests
│   - Send message → Restart server → Send follow-up → Verify context maintained
│
└── Concurrent conversations with different scopes
    - Two users, two scopes → Verify isolation

MANUAL TESTING:
├── Chat UI works with multi-doc mode
├── Streaming works correctly
├── Error handling when scope has no matching docs
└── Performance with larger document sets
```

---

## Part 5: Summary

### What We Have
- Single-document RAG with chat memory
- Retrieval scoped to one `pdf_id`
- Full conversation flow with streaming

### What We Want
- Multi-document RAG with same chat memory
- Retrieval scoped to corpus or list of documents
- Same conversation flow, just broader retrieval

### The Change is Small

| Component | Change Required |
|-----------|-----------------|
| Document ingestion | Add richer metadata (corpus, doc_type, etc.) |
| Retrieval filter | Generalize from `pdf_id` to `scope_filter` |
| Conversation model | Add `mode` and `scope_filter` fields |
| build_chat() | Branch based on mode |
| Memory | No change |
| Streaming | No change |
| Chat UI | No change |
| Infrastructure | No change |

### Key Insight

> The system already knows how to do multi-turn conversations with memory.
> We just need to widen the retrieval aperture from "one document" to "multiple documents".
> Everything else stays the same.

---

## Part 6: Implementation Steps

### Step 1: Fork the Project
Create a new folder `lanes` as a copy of `pdf`:
```
/Users/luv/Documents/GitHub/AI_enabled_chatbot/lanes/
```

### Step 2: Modify Database Models

**File: `app/web/db/models/conversation.py`**
- Add `mode` field (string: "user_pdf" | "multi_doc")
- Add `scope_filter` field (JSON)

**File: `app/web/db/models/pdf.py`**
- Add `is_system` field (boolean)
- Add `corpus` field (string)
- Add `doc_type` field (string)

### Step 3: Modify Document Ingestion

**File: `app/chat/create_embeddings.py`**
- Add `corpus` and `doc_type` to chunk metadata
- Modify `create_embeddings_for_pdf()` to accept additional metadata params

### Step 4: Modify Retriever

**File: `app/chat/vector_stores/pinecone.py`**
- Modify `build_retriever()` to accept `scope_filter` instead of just `pdf_id`
- Support both old and new filter formats

**File: `app/chat/vector_stores/__init__.py`**
- Update `retriever_map` to use new retriever signature

### Step 5: Modify Chat Builder

**File: `app/chat/chat.py`**
- Modify `build_chat()` to check `mode` from chat_args
- If `mode = "user_pdf"`: use existing `pdf_id` filter
- If `mode = "multi_doc"`: use `scope_filter` from conversation

**File: `app/chat/models/__init__.py`**
- Add `mode` and `scope_filter` to `ChatArgs`

### Step 6: Modify API Endpoints

**File: `app/web/views/conversation_views.py`**
- Accept `mode` and `scope_filter` when creating conversation
- Pass these to ChatArgs

### Step 7: Test with Sample Docs
- Ingest 3-4 test PDFs with same `corpus` tag
- Create multi_doc conversation
- Verify retrieval across all docs
- Verify memory works for follow-ups

---

## Files to Modify (Summary)

| File | Change |
|------|--------|
| `app/web/db/models/conversation.py` | Add mode, scope_filter fields |
| `app/web/db/models/pdf.py` | Add is_system, corpus, doc_type fields |
| `app/chat/create_embeddings.py` | Add corpus/doc_type to metadata |
| `app/chat/vector_stores/pinecone.py` | Generalize filter logic |
| `app/chat/vector_stores/__init__.py` | Update retriever_map |
| `app/chat/chat.py` | Branch on mode |
| `app/chat/models/__init__.py` | Add mode, scope_filter to ChatArgs |
| `app/web/views/conversation_views.py` | Accept new params |

---

## Part 7: Future Extensions (Not in Scope Now)

Once multi-doc RAG works, future enhancements could include:

1. **Agentic behavior**: Planning + tool use instead of just retrieve → answer
2. **Structured output**: JSON responses for classification/compliance use cases
3. **Knowledge base updates**: Scheduled re-ingestion of changing documents
4. **Source citations**: Inline references to which document said what

These are mentioned for context but are **not part of this design**.
