# Lanes - Production Readiness Update

## Overview

Lanes is a multi-document RAG (Retrieval Augmented Generation) system for trade compliance queries. This document covers the production readiness work completed in Phase 1.

## What's Been Built

### Core Features (Previous Work)

1. **Multi-Document RAG** - Query across multiple documents with a single conversation
2. **Agentic RAG** - LangGraph-based agent with tool use for complex queries
3. **Structured Output** - Pydantic-validated responses for trade compliance
4. **Source Citations** - Inline references with document attribution
5. **Conversation Memory** - Multi-turn conversations with context preservation

### Production Readiness (Phase 1)

#### 1. Standardized API Response

All `/api/conversations/{id}/messages` responses now return a consistent envelope:

```json
{
  "success": true,
  "error": null,
  "message_id": "uuid-string",
  "role": "assistant",
  "mode": "multi_doc",
  "output_format": "text|structured|trade_compliance",
  "answer": "The HTS code for LED lamps is 8539.50.00...",
  "citations": [
    {
      "index": 1,
      "pdf_id": "hts-schedule-001",
      "doc_type": "hts_schedule",
      "page": 1542,
      "snippet": "8539.50.00 - Light-emitting diode (LED) lamps..."
    }
  ],
  "structured_output": {
    "hts_codes": ["8539.50.00"],
    "agencies": ["DOE", "FCC"],
    "required_documents": [...],
    "tariff_info": {...},
    "risk_flags": [...]
  },
  "tool_calls": [],
  "condensed_question": "What is the HTS code for LED lamps?"
}
```

**Request Parameters:**
- `input` (required): The user's question
- `output_format`: `text` | `structured` | `trade_compliance`
- `use_agent`: `true` to enable agentic mode with tools

**Error Response:**
```json
{
  "success": false,
  "error": {
    "code": "MISSING_INPUT|CHAT_NOT_AVAILABLE|INTERNAL_ERROR",
    "message": "Human-readable error description"
  }
}
```

#### 2. Corpus Model

New model for managing versioned document collections:

```python
from app.web.db.models import Corpus

# Create a corpus
corpus = Corpus.create(
    name="trade_compliance_v2",
    description="HTS schedules, tariff notices, agency regulations",
    is_active=True,
    version="v2.0"
)

# Query active corpora
active = Corpus.get_active()

# Find by name
corpus = Corpus.get_by_name("trade_compliance_v2")

# Deactivate old version
corpus.is_active = False
corpus.save()
```

**Schema:**
| Field | Type | Description |
|-------|------|-------------|
| id | Integer | Primary key |
| name | String(80) | Unique corpus name |
| description | Text | Optional description |
| is_active | Boolean | Whether corpus is queryable |
| version | String(20) | Version identifier |
| created_at | DateTime | Creation timestamp |

#### 3. Logging & Tracing

Structured logging for graph execution with `app/chat/logging_utils.py`:

```python
from app.chat.logging_utils import GraphLogger, timed_node, log_graph_event

# Context manager for full run tracing
with GraphLogger(run_id, conversation_id, user_id) as logger:
    logger.log_condense(original_question, condensed_question)
    logger.log_retrieve(query, documents, duration_ms=45.2)
    logger.log_generate(answer, citations)
    logger.log_tool("lookup_hts", {"product": "LED"}, result, duration_ms=120.5)

# Decorator for node timing
@timed_node("retrieve")
def retrieve_documents_node(state, config):
    # Node logic here
    pass

# Simple event logging
log_graph_event("custom_event", {
    "run_id": "...",
    "conversation_id": "...",
    "custom_field": "value"
})
```

**Log Output (JSON):**
```json
{
  "timestamp": "2024-01-15T10:30:45.123456",
  "event_type": "node_execution",
  "node": "retrieve",
  "run_id": "abc-123",
  "conversation_id": "conv-456",
  "duration_ms": 45.2,
  "inputs": {"query": "HTS code for LED..."},
  "outputs": {"num_docs": 5}
}
```

#### 4. Test Suite

Comprehensive test coverage with mocked external services:

```
tests/
├── conftest.py           # Pytest fixtures
├── test_api_response.py  # API envelope tests (14 tests)
├── test_corpus_model.py  # Corpus CRUD tests (15 tests)
├── test_integration.py   # End-to-end flow tests (14 tests)
├── test_trade_eval.py    # Eval harness tests (18 tests)
├── trade_scenarios.py    # Trade compliance scenarios
└── test_multi_doc.py     # Multi-doc feature tests (18 tests)
```

**Running Tests:**
```bash
# Run all tests
pipenv run python -m pytest tests/ -v

# Run specific test file
pipenv run python -m pytest tests/test_api_response.py -v

# Run with coverage
pipenv run python -m pytest tests/ --cov=app
```

**Test Results:** 77 passed, 2 skipped

#### 5. Trade Compliance Eval Harness

Predefined scenarios for validating trade compliance responses:

```python
from tests.trade_scenarios import (
    LED_LAMPS_FROM_CHINA,
    LED_LAMPS_TARIFF,
    CORE_SCENARIOS,
    TradeScenario
)

# Scenario structure
@dataclass
class TradeScenario:
    name: str                        # "LED_lamps_from_China"
    query: str                       # User's question
    expected_hts_codes: List[str]    # ["8539.50"]
    expected_agencies_subset: List[str]  # ["DOE", "FCC"]
    expected_tariff_keywords: List[str]  # ["Section 301", "25%"]
    expected_doc_types: List[str]    # ["hts_schedule", "tariff_notice"]
    description: str                 # Human-readable description
```

**Available Scenarios:**
| Scenario | Query | Expected |
|----------|-------|----------|
| LED_lamps_basic | "What is the HTS code for LED lamps?" | HTS: 8539.50 |
| LED_lamps_from_China | "I want to import LED lamps from China..." | HTS + DOE/FCC + Section 301 |
| LED_lamps_tariff | "What tariffs apply to LED lamps from China?" | 3.9% + Section 301 |
| LED_lamps_agencies | "What agencies regulate LED lamps?" | DOE, FCC |
| LED_lamps_documents | "What documents do I need..." | DOE/FCC certs |

## Project Structure

```
lanes/
├── app/
│   ├── chat/
│   │   ├── graphs/
│   │   │   ├── conversational_rag.py  # Standard RAG graph
│   │   │   └── agentic_rag.py         # Agentic RAG with tools
│   │   ├── tools/
│   │   │   └── trade_tools.py         # HTS lookup, tariff check
│   │   ├── prompts/
│   │   │   └── trade_compliance.py    # System prompts
│   │   ├── output_schemas.py          # Pydantic models
│   │   ├── logging_utils.py           # Graph tracing (NEW)
│   │   └── chat.py                    # Chat builders
│   └── web/
│       ├── db/models/
│       │   ├── corpus.py              # Corpus model (NEW)
│       │   ├── conversation.py        # Updated with corpus_name
│       │   └── ...
│       └── views/
│           └── conversation_views.py  # Standardized response (UPDATED)
├── tests/
│   ├── conftest.py                    # Fixtures (NEW)
│   ├── test_api_response.py           # API tests (NEW)
│   ├── test_corpus_model.py           # Corpus tests (NEW)
│   ├── test_integration.py            # Integration tests (NEW)
│   ├── test_trade_eval.py             # Eval harness (NEW)
│   └── trade_scenarios.py             # Scenarios (NEW)
└── README3.md                         # This file
```

## API Reference

### Create Conversation

```http
POST /api/conversations/
Content-Type: application/json

{
  "mode": "multi_doc",
  "scope_filter": {"corpus": "trade_compliance_v2"}
}
```

### Send Message

```http
POST /api/conversations/{conversation_id}/messages
Content-Type: application/json

{
  "input": "What is the HTS code for LED lamps from China?",
  "output_format": "trade_compliance",
  "use_agent": false
}
```

### List Conversations

```http
GET /api/conversations/?mode=multi_doc
```

## Configuration

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=lanes-index

# Optional
SQLALCHEMY_DATABASE_URI=sqlite:///lanes.db
USE_SQLITE_CHECKPOINTER=true
LANGFUSE_PUBLIC_KEY=...  # For observability
```

## Usage Examples

### Basic Query

```python
import requests

# Create conversation
resp = requests.post("http://localhost:5000/api/conversations/", json={
    "mode": "multi_doc",
    "scope_filter": {"corpus": "trade_compliance"}
})
conv_id = resp.json()["id"]

# Send message
resp = requests.post(f"http://localhost:5000/api/conversations/{conv_id}/messages", json={
    "input": "What is the HTS code for LED lamps?"
})
print(resp.json()["answer"])
```

### Trade Compliance Query

```python
resp = requests.post(f"http://localhost:5000/api/conversations/{conv_id}/messages", json={
    "input": "I want to import LED lamps from China. What do I need?",
    "output_format": "trade_compliance"
})

data = resp.json()
print(f"HTS Codes: {data['structured_output']['hts_codes']}")
print(f"Agencies: {data['structured_output']['agencies']}")
print(f"Tariffs: {data['structured_output']['tariff_info']}")
```

### Agentic Mode

```python
resp = requests.post(f"http://localhost:5000/api/conversations/{conv_id}/messages", json={
    "input": "Find the HTS code for LED lamps and check tariffs from China",
    "use_agent": True
})

data = resp.json()
print(f"Tool Calls: {data['tool_calls']}")
print(f"Answer: {data['answer']}")
```

## Next Steps (Phase 2 & 3)

- **Gradio UI** - Web interface using Gradio for rapid prototyping
- **Graph Instrumentation** - Apply logging decorators to all graph nodes
- **Performance Monitoring** - Dashboard for query latency and success rates

## Development

```bash
# Install dependencies
pipenv install --dev

# Run tests
pipenv run python -m pytest tests/ -v

# Start server
pipenv run flask run

# Run with debug
FLASK_DEBUG=1 pipenv run flask run
```
