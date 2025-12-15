# Lanes: Multi-Document RAG with LangGraph

A production-ready conversational AI system for multi-document retrieval with agentic capabilities, built on LangGraph.

---

## What We Built

Starting from a single-document PDF chat application, we evolved it into a full-featured **multi-document RAG system** with:

- **Multi-document retrieval** across document corpora
- **LangGraph-based architecture** replacing legacy LangChain chains
- **Persistent conversation memory** via SQLite checkpointer
- **Source citations** in every response
- **Structured JSON output** (3 formats)
- **Agentic RAG** with planning and tool use

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    LANES ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TWO MODES:                                                     │
│                                                                 │
│  1. CONVERSATIONAL RAG (Standard)                               │
│     User Question → Condense → Retrieve → Generate → Answer     │
│                                                                 │
│  2. AGENTIC RAG (Complex Queries)                               │
│     User Question → Plan → Tool Calls → Reflect → Generate      │
│                        ↑__________________|                     │
│                        (iterate if needed)                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Features

### 1. Multi-Document Retrieval

Retrieve across multiple documents using corpus-based filtering:

```python
# Single document mode (backward compatible)
scope_filter = {"pdf_id": "doc-123"}

# Multi-document mode
scope_filter = {"corpus": "trade_compliance"}
# or
scope_filter = {"doc_type": "hts_schedule"}
```

### 2. LangGraph StateGraph Architecture

Replaced legacy `ConversationalRetrievalChain` with modular LangGraph nodes:

```
┌─────────┐     ┌──────────┐     ┌──────────┐
│ Condense │ --> │ Retrieve │ --> │ Generate │
└─────────┘     └──────────┘     └──────────┘
```

### 3. Persistent Memory (SQLite Checkpointer)

Conversation history persists across sessions:

```python
# Stored in: instance/langgraph_checkpoints.db
# Thread-based isolation via conversation_id
```

### 4. Source Citations

Every response includes document sources:

```python
{
    "answer": "The HTS code is 8539.50.00 [Source: mock-hts-001]",
    "citations": [
        {
            "index": 1,
            "pdf_id": "mock-hts-001",
            "doc_type": "hts_schedule",
            "page": 1,
            "snippet": "8539.50.00 - Light-emitting diode (LED) lamps..."
        }
    ]
}
```

### 5. Structured Output Formats

Three output formats available:

| Format | Use Case | Fields |
|--------|----------|--------|
| `text` | General Q&A | `answer`, `citations` |
| `structured` | Detailed analysis | `answer`, `citations`, `confidence`, `follow_up_questions` |
| `trade_compliance` | Import/export queries | `answer`, `hts_codes`, `agencies`, `required_documents`, `tariff_info`, `risk_flags`, `citations` |

### 6. Agentic RAG with Tool Use

For complex queries, the agent can plan and use tools:

**Available Tools:**
- `search_documents` - General corpus search
- `lookup_hts_code` - HTS classification lookup
- `check_tariffs` - Tariff rates by HTS + country
- `check_agency_requirements` - Regulatory requirements

```
Query: "I want to import LED lamps from China. What do I need?"

Agent Plan:
1. lookup_hts_code("LED lamps") → 8539.50.00
2. check_tariffs("8539.50.00", "China") → 3.9% + 25% Section 301
3. check_agency_requirements("LED lamps") → DOE, FCC requirements
4. Generate comprehensive answer
```

---

## API Usage

### Standard RAG

```python
from app.chat import build_chat, ChatArgs
from app.chat.models import Metadata

metadata = Metadata(
    conversation_id="conv-001",
    user_id="user-001",
    pdf_id=None
)

chat_args = ChatArgs(
    conversation_id="conv-001",
    pdf_id=None,
    metadata=metadata,
    streaming=False,
    mode="multi_doc",
    scope_filter={"corpus": "trade_compliance"}
)

chat = build_chat(chat_args)
result = chat.invoke("What is the HTS code for LED lamps?")

print(result["answer"])
print(result["citations"])
```

### Structured Output

```python
chat = build_chat(chat_args, output_format="structured")
result = chat.invoke("What is the duty rate for LED lamps?")

print(result["structured_output"]["confidence"])  # "high"
print(result["structured_output"]["follow_up_questions"])
```

### Trade Compliance Output

```python
from app.chat import build_trade_compliance_chat

chat = build_trade_compliance_chat(chat_args)
result = chat.invoke("I want to import LED lamps from China")

so = result["structured_output"]
print(so["hts_codes"])          # ["8539.50.00"]
print(so["agencies"])           # ["DOE", "FCC"]
print(so["required_documents"]) # [{agency, document_name, description}, ...]
print(so["tariff_info"])        # {duty_rate, special_programs, country_specific}
print(so["risk_flags"])         # ["Additional 25% tariff under Section 301"]
```

### Agentic RAG

```python
from app.chat import build_agentic_chat

chat = build_agentic_chat(chat_args)
result = chat.invoke("What tariffs would I pay on LED lamps from China?")

print(result["answer"])
print(result["tool_calls"])  # Shows which tools were used
```

---

## File Structure

```
app/
├── chat/
│   ├── graphs/
│   │   ├── __init__.py
│   │   ├── conversational_rag.py   # Standard RAG graph
│   │   └── agentic_rag.py          # Agentic RAG with tools
│   ├── chat.py                     # Main builders
│   ├── models/
│   │   └── __init__.py             # ChatArgs, Metadata
│   └── ...
├── web/
│   ├── views/
│   │   └── conversation_views.py   # API endpoints
│   └── db/models/
│       ├── conversation.py         # mode, scope_filter fields
│       └── pdf.py                  # corpus, doc_type fields
└── ...

scripts/
├── test_multi_doc_chat.py          # Standard RAG tests
├── test_agentic_chat.py            # Agentic RAG tests
└── ingest_test_docs.py             # Test document ingestion
```

---

## Test Results

### Multi-Doc Chat Tests (6/6 Passing)

```
✓ Basic Retrieval: Retrieved from 3 sources
✓ Conversational Memory: Context maintained across questions
✓ Source Citations: Citations included in responses
✓ Structured Output: JSON with confidence and follow-ups
✓ Trade Compliance Output: HTS codes, agencies, documents
✓ SQLite Persistence: Memory persists across sessions
```

### Agentic Chat Tests (5/5 Passing)

```
✓ Basic Tool Use: Agent used lookup_hts_code tool
✓ Multi-Step Reasoning: Agent chained multiple tools
✓ Comprehensive Trade Query: All info gathered (HTS, tariffs, agencies)
✓ Streaming: Chunks received correctly
✓ Tool-Specific Queries: All 4 tools executed successfully
```

---

## Dependencies

Key packages in `Pipfile`:

```
langchain = ">=0.3.0"
langchain-core = ">=0.3.0"
langchain-openai = ">=0.2.0"
langgraph = ">=0.2.0"
langgraph-checkpoint = ">=2.0.0"
langgraph-checkpoint-sqlite = "*"
pinecone = ">=5.0.0"
```

---

## Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX_NAME=docs

# Optional
USE_SQLITE_CHECKPOINTER=true
CHECKPOINTER_DB_PATH=instance/langgraph_checkpoints.db
```

---

## Running Tests

```bash
cd lanes
pipenv shell

# Standard RAG tests
python scripts/test_multi_doc_chat.py

# Agentic RAG tests
python scripts/test_agentic_chat.py
```

---

## Evolution Summary

| Before | After |
|--------|-------|
| Single PDF per conversation | Multi-document corpus |
| LangChain ConversationalRetrievalChain | LangGraph StateGraph |
| In-memory conversation state | SQLite persistent checkpointer |
| Text-only output | Structured JSON + citations |
| Retrieve → Answer | Plan → Tools → Reflect → Answer |

---

## What's Next

Potential future enhancements:

1. **Web UI for multi-doc mode** - Document corpus selector
2. **Scheduled re-ingestion** - Keep documents up to date
3. **More tools** - Calculators, external APIs, database lookups
4. **Evaluation framework** - Automated quality testing
5. **Production deployment** - Docker, async workers, monitoring
