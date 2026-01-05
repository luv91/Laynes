# v10.0 Legal-Grade Tariff Data System

## Complete Design Specification & Implementation Guide

**Version:** 10.0 (Legal-Grade RAG System)
**Date:** January 2026
**Status:** Implemented

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Problem: Before v10.0](#2-the-problem-before-v100)
3. [The Solution: After v10.0](#3-the-solution-after-v100)
4. [Architecture Overview](#4-architecture-overview)
5. [Database Design](#5-database-design)
6. [Component Deep Dive](#6-component-deep-dive)
7. [Search System Design](#7-search-system-design)
8. [Gemini Integration](#8-gemini-integration)
9. [Implementation Phases](#9-implementation-phases)
10. [Testing](#10-testing)
11. [API Reference](#11-api-reference)
12. [Operational Guide](#12-operational-guide)

---

## 1. Executive Summary

### Core Principle

> **LLMs may interpret, but they must PROVE every claim by pointing to exact text spans inside Tier-A documents we have stored.**

The v10.0 system transforms how tariff scope determinations are made:
- **Before:** LLM (Gemini) searches the web, returns conclusions, system caches as truth
- **After:** LLM reads from our verified corpus, citations verified mechanically, proof stored with assertions

### Key Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Test Coverage | 100 tests | 112 tests passing |
| Cache Hit Rate | >70% | Tracked via verified_assertions |
| Verification Rate | 100% | All assertions have proof chains |

---

## 2. The Problem: Before v10.0

### Previous Architecture (Broken)

```
User question
      │
      ▼
Gemini Web Search (open internet)
      │  - finds official + unofficial + outdated + summaries
      │  - reads URLs itself
      │  - returns a conclusion ("in_scope", "claim_code")
      ▼
System caches Gemini's conclusion in Pinecone/Postgres
      ▼
System treats it as truth for TTL period
```

### Failure Modes

1. **Source Mixing:** Gemini combines official (CBP) and unofficial (law firm blogs) sources
2. **Confident Hallucination:** Returns wrong claim codes with high confidence
3. **Stale Information:** Cached conclusions outlive regulatory changes
4. **No Proof Chain:** Cannot answer "show me where this is written"
5. **Gap Blindness:** Cannot prove something is NOT in a list

### Example Failure

```
User: "Is HTS 8544.42.9090 in scope for Section 232 steel?"

Gemini (before): "Yes, in scope. Claim code 9903.78.01"
Reality: HTS 8544 falls in a gap between covered headings
Result: Wrong advice cached for weeks, potential CBP penalty
```

---

## 3. The Solution: After v10.0

### New Architecture (Legal-Grade)

```
User question
      │
      ▼
┌─────────────────────────────────────────────────┐
│  LAYER 1: Verified Assertions (Postgres)        │
│  - Check for existing verified fact + proof     │
│  ✓ HIT → return immediately (authoritative)    │
│  ✗ MISS → continue to Layer 2                   │
└─────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────┐
│  LAYER 2: RAG Over Official Corpus              │
│  - Retrieve chunks from Pinecone (tier='A')    │
│  - Reader LLM answers from chunks only          │
│  - Validator LLM verifies citations             │
│  - Write Gate checks proof mechanically         │
│  ✓ PASS → store verified_assertion             │
│  ✗ FAIL → queue for human review               │
└─────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────┐
│  LAYER 3: Discovery Mode (if no corpus match)   │
│  - Gemini finds official URLs (not conclusions) │
│  - Connector fetches and stores document        │
│  - Re-run Layer 2 with new evidence             │
└─────────────────────────────────────────────────┘
```

### Key Differences

| Aspect | Before | After |
|--------|--------|-------|
| Source | Open internet | Our verified corpus |
| Trust | LLM conclusion | Mechanical proof chain |
| Caching | TTL-based | Permanent with versioning |
| Auditing | None | Full provenance trail |
| Gemini Role | Answerer | Document finder only |

---

## 4. Architecture Overview

### System Components

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACE                                  │
│                    (Chat / MCP Tools / API)                              │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         RAG ORCHESTRATOR                                  │
│                     (app/rag/orchestrator.py)                            │
│                                                                          │
│  Coordinates:                                                            │
│  • Verified cache lookup                                                 │
│  • Chunk retrieval                                                       │
│  • Reader LLM → Validator LLM → Write Gate                              │
│  • Assertion storage or review queue                                    │
└────────┬──────────────┬──────────────┬──────────────┬───────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  VERIFIED   │ │   READER    │ │  VALIDATOR  │ │   WRITE     │
│  ASSERTIONS │ │    LLM      │ │     LLM     │ │    GATE     │
│  (Postgres) │ │  (OpenAI)   │ │  (OpenAI)   │ │ (Postgres)  │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
         │              │              │              │
         └──────────────┴──────────────┴──────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        DOCUMENT CORPUS                                    │
│                                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                      │
│  │  DOCUMENTS  │  │   CHUNKS    │  │  PINECONE   │                      │
│  │  (Postgres) │  │  (Postgres) │  │  (Vectors)  │                      │
│  └─────────────┘  └─────────────┘  └─────────────┘                      │
│                                                                          │
│  Populated by:                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                      │
│  │    CSMS     │  │  GOVINFO    │  │   USITC     │                      │
│  │ CONNECTOR   │  │ CONNECTOR   │  │ CONNECTOR   │                      │
│  └─────────────┘  └─────────────┘  └─────────────┘                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Query Arrives:** User asks about HTS scope
2. **Cache Check:** Look for existing verified_assertion
3. **Chunk Retrieval:** If miss, retrieve from Pinecone (tier='A' only)
4. **Reader LLM:** Answers from chunks, cites exact quotes
5. **Validator LLM:** Verifies citations against chunk text
6. **Write Gate:** Mechanical checks (doc exists, quote exists, tier A)
7. **Storage:** If all pass → verified_assertion; else → needs_review_queue

---

## 5. Database Design

### New Tables (v10.0)

```sql
-- Official documents from trusted connectors
CREATE TABLE documents (
    id VARCHAR(36) PRIMARY KEY,
    source VARCHAR(20) NOT NULL,          -- 'CSMS', 'FEDERAL_REGISTER', 'USITC'
    tier CHAR(1) NOT NULL DEFAULT 'A',    -- 'A', 'B', 'C'
    connector_name VARCHAR(50) NOT NULL,
    canonical_id VARCHAR(100),             -- CSMS#65794272
    url_canonical TEXT NOT NULL,
    title TEXT,
    published_at TIMESTAMP,
    effective_start DATE,
    effective_end DATE,
    sha256_raw VARCHAR(64) NOT NULL,
    raw_content TEXT,
    extracted_text TEXT,
    fetch_log JSONB,
    hts_codes_mentioned JSONB,
    programs_mentioned JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Chunked text for RAG retrieval
CREATE TABLE document_chunks (
    id VARCHAR(36) PRIMARY KEY,
    document_id VARCHAR(36) REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    char_start INT,
    char_end INT,
    text_hash VARCHAR(64),
    embedding_id VARCHAR(64),              -- Pinecone vector ID
    chunk_metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (document_id, chunk_index)
);

-- Verified facts with proof chains
CREATE TABLE verified_assertions (
    id VARCHAR(36) PRIMARY KEY,
    program_id VARCHAR(30) NOT NULL,       -- 'section_232_steel'
    hts_code_norm VARCHAR(10) NOT NULL,    -- '85444290' (digits only)
    hts_digits INT NOT NULL DEFAULT 8,
    material VARCHAR(20),                  -- 'steel', 'copper', 'aluminum'
    assertion_type VARCHAR(30) NOT NULL,   -- 'IN_SCOPE', 'OUT_OF_SCOPE'
    claim_code VARCHAR(12),                -- '9903.78.01'
    disclaim_code VARCHAR(12),
    duty_rate DECIMAL(5,4),
    effective_start DATE NOT NULL,
    effective_end DATE,                    -- NULL = current
    document_id VARCHAR(36) REFERENCES documents(id),
    chunk_id VARCHAR(36) REFERENCES document_chunks(id),
    evidence_quote TEXT NOT NULL,
    evidence_quote_hash VARCHAR(64) NOT NULL,
    reader_output JSONB,
    validator_output JSONB,
    verified_at TIMESTAMP DEFAULT NOW(),
    verified_by VARCHAR(50) DEFAULT 'write_gate',
    UNIQUE (program_id, hts_code_norm, material, assertion_type, effective_start)
);

-- Failed verifications awaiting human review
CREATE TABLE needs_review_queue (
    id VARCHAR(36) PRIMARY KEY,
    hts_code VARCHAR(12) NOT NULL,
    query_type VARCHAR(30) NOT NULL,
    material VARCHAR(20),
    reader_output JSONB,
    validator_output JSONB,
    block_reason TEXT NOT NULL,
    block_details JSONB,
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'approved', 'rejected'
    priority INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP,
    resolution_notes TEXT
);
```

### Source Tiers

| Tier | Sources | Write Permission |
|------|---------|-----------------|
| **A** | Federal Register, CBP CSMS, USITC | Can populate verified_assertion |
| **B** | USTR press, White House | Signals only (trigger discovery) |
| **C** | Law firms, blogs | Discovery hints only |

### Indexes

```sql
-- Fast assertion lookups
CREATE INDEX idx_assertion_hts ON verified_assertions(hts_code_norm, program_id);
CREATE INDEX idx_assertion_effective ON verified_assertions(effective_start, effective_end);

-- Document searches
CREATE INDEX idx_document_source_tier ON documents(source, tier);
CREATE INDEX idx_document_hts_mentions ON documents USING GIN(hts_codes_mentioned);

-- Chunk embedding lookup
CREATE INDEX idx_chunk_embedding ON document_chunks(embedding_id);
```

---

## 6. Component Deep Dive

### 6.1 Trusted Connectors

Each connector validates domain, computes hash, logs fetch metadata.

**File:** `app/ingestion/connectors/`

```python
# CSMS Connector (Tier A)
class CSMSConnector(BaseConnector):
    TRUSTED_DOMAINS = {'content.govdelivery.com', 'www.cbp.gov', 'cbp.gov'}
    SOURCE_TYPE = "CSMS"
    TIER = "A"

# GovInfo Connector (Tier A)
class GovInfoConnector(BaseConnector):
    TRUSTED_DOMAINS = {'www.federalregister.gov', 'api.govinfo.gov'}
    SOURCE_TYPE = "FEDERAL_REGISTER"
    TIER = "A"

# USITC Connector (Tier A)
class USITCConnector(BaseConnector):
    TRUSTED_DOMAINS = {'hts.usitc.gov', 'www.usitc.gov'}
    SOURCE_TYPE = "USITC"
    TIER = "A"
```

**Security:** Untrusted domains raise `UntrustedSourceError`.

### 6.2 Document Chunker

Splits documents for RAG retrieval.

**File:** `app/ingestion/chunker.py`

```python
class DocumentChunker:
    def __init__(
        self,
        min_chunk_size: int = 200,   # Avoid tiny chunks
        max_chunk_size: int = 1200,  # Fit in context
        overlap: int = 50,           # Context continuity
        strategy: str = "paragraph"  # or "sentence", "fixed"
    ):

    def chunk_text(self, text: str, document_id: str) -> List[Chunk]:
        # Returns chunks with position tracking
```

### 6.3 Reader LLM

Answers from chunks only, returns structured output.

**File:** `app/rag/reader_llm.py`

```python
class ReaderLLM:
    SYSTEM_PROMPT = """You are a tariff scope analyst.
    CRITICAL RULES:
    1. ONLY use the provided document chunks to answer
    2. For every claim, provide an EXACT verbatim quote
    3. Include document_id and chunk_id for each citation
    """

    def read(self, hts_code, program_id, material, chunks) -> ReaderOutput:
        # Returns structured answer with citations
```

**Output Schema:**
```json
{
  "answer": {
    "in_scope": true,
    "program": "section_232_steel",
    "hts_code": "8544.42.9090",
    "claim_codes": ["9903.78.01"],
    "confidence": "high"
  },
  "citations": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "quote": "verbatim text",
      "why_this_supports": "explanation"
    }
  ]
}
```

### 6.4 Validator LLM

Independently verifies Reader's claims.

**File:** `app/rag/validator_llm.py`

```python
class ValidatorLLM:
    SYSTEM_PROMPT = """You are a fact-checker.
    Verify each citation quote is an EXACT substring of the chunk text.
    """

    def validate(self, reader_output, chunks) -> ValidatorOutput:
        # LLM verification

    def quick_validate(self, reader_output, chunks) -> ValidatorOutput:
        # Mechanical checks only (faster)
```

**Output Schema:**
```json
{
  "verified": true,
  "failures": [],
  "confidence": "high"
}
```

### 6.5 Write Gate

Mechanical proof checks before writing to verified_assertion.

**File:** `app/rag/write_gate.py`

```python
class WriteGate:
    def check(self, reader_output, validator_output) -> WriteGateResult:
        # Checks:
        # 1. Document exists in database
        # 2. Chunk exists in database
        # 3. Document tier is 'A'
        # 4. Quote is exact substring of chunk text
        # 5. Validator returned verified=true
        # 6. (Optional) Multiple sources
```

| Check | What It Validates |
|-------|-------------------|
| document_exists | document_id exists in documents table |
| chunk_exists | chunk_id exists in document_chunks table |
| tier_a_only | document.tier == 'A' |
| quote_exists | quote is exact substring of chunk.text |
| validator_passed | verified == true from Validator LLM |
| multiple_sources | At least 2 citations (warning only) |

### 6.6 RAG Orchestrator

Coordinates the full pipeline.

**File:** `app/rag/orchestrator.py`

```python
class RAGOrchestrator:
    def verify_scope(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str] = None,
        force_rag: bool = False
    ) -> RAGResult:
        # 1. Check verified_assertion cache
        # 2. Retrieve chunks from Pinecone
        # 3. Reader LLM
        # 4. Validator LLM
        # 5. Write Gate
        # 6. Store or queue for review
```

---

## 7. Search System Design

### Multi-Layer Search Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  QUERY: "Is HTS 8544.42.9090 in scope for Section 232 steel?"          │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: VERIFIED ASSERTION LOOKUP (fastest, most authoritative)       │
│                                                                         │
│  SELECT * FROM verified_assertions                                      │
│  WHERE hts_code_norm = '85444290'                                      │
│    AND program_id = 'section_232_steel'                                │
│    AND effective_end IS NULL  -- current only                          │
│                                                                         │
│  ✓ FOUND → Return immediately with evidence quote                      │
│  ✗ NOT FOUND → Continue to Layer 2                                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: RAG OVER OFFICIAL CORPUS                                      │
│                                                                         │
│  Step A: Pinecone Vector Search                                         │
│  - Filter: tier='A'                                                    │
│  - Query: semantic embedding of question                               │
│  - Returns: top K chunks with doc_id, chunk_id, text                   │
│                                                                         │
│  Step B: Reader LLM                                                     │
│  - Input: question + retrieved chunks                                  │
│  - Output: answer + citations with exact quotes                        │
│                                                                         │
│  Step C: Validator LLM                                                  │
│  - Input: Reader output + original chunks                              │
│  - Output: verified true/false + any failures                          │
│                                                                         │
│  Step D: Write Gate                                                     │
│  - Mechanical checks: doc exists, chunk exists, tier A, quote exists   │
│                                                                         │
│  ✓ ALL PASS → Store verified_assertion, return authoritative          │
│  ✗ ANY FAIL → Queue for review, return "unverified"                   │
│  ✗ NO CHUNKS → Continue to Layer 3                                    │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: DISCOVERY MODE (Gemini-assisted)                             │
│                                                                         │
│  Gemini searches web for official sources:                             │
│  - Returns URLs/identifiers ONLY (no conclusions trusted)              │
│  - Filtered to official domains                                        │
│                                                                         │
│  If official URL found:                                                │
│  1. Trusted connector fetches document                                 │
│  2. Store in documents table                                           │
│  3. Chunk and embed                                                    │
│  4. Re-run Layer 2 with new evidence                                  │
│                                                                         │
│  ✗ NO TIER-A PROOF → Return "unknown" + log to needs_review           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Prefix Matching for 10-digit Queries

```sql
-- When user queries 8544.42.9090 (10-digit)
-- Check for 8-digit parent (85444290)

SELECT * FROM verified_assertions
WHERE '8544429090' LIKE hts_code_norm || '%'  -- 10-digit starts with 8-digit
  AND program_id = 'section_232_steel'
  AND effective_end IS NULL;
```

---

## 8. Gemini Integration

### Before: Gemini as Oracle

```python
# BEFORE (dangerous)
gemini_response = gemini_search(
    query=f"Is HTS {hts_code} in scope for {program}?"
)
# Gemini returns: {"in_scope": true, "claim_code": "9903.78.01"}
cache.set(hts_code, gemini_response)  # WRONG: caching LLM opinion
```

### After: Gemini as Document Finder

```python
# AFTER (correct)
def discover_official_sources(hts_code, program_id, material):
    """Gemini finds URLs, NOT conclusions."""
    prompt = f"""
    Find OFFICIAL government sources about HTS {hts_code} and {program_id}.
    Return URLs from: Federal Register, CBP.gov, USITC
    DO NOT provide scope conclusions.
    """

    gemini_response = gemini_search(prompt)

    # Extract only official URLs (no conclusions)
    for source in gemini_response.get("official_sources", []):
        url = source.get("url")
        if is_official_domain(url):
            # Fetch via trusted connector
            connector = get_connector_for_url(url)
            result = connector.fetch(url)

            # Store document
            store_document(result)

            # Chunk and embed
            chunks = chunker.chunk_document(result)
            store_chunks(chunks)
            embed_chunks(chunks)

    # Now run RAG pipeline with new corpus
    return orchestrator.verify_scope(hts_code, program_id, material)
```

### MCP Tool Integration

**File:** `mcp_servers/hts_verifier.py`

```python
@mcp.tool()
def discover_official_sources(
    hts_code: str,
    program_id: str,
    material: Optional[str] = None
) -> dict:
    """
    Uses Gemini to find official government sources.
    Returns URLs only, NOT conclusions.
    """

@mcp.tool()
def verify_with_rag(
    hts_code: str,
    program_id: str,
    material: Optional[str] = None,
    force_rag: bool = False
) -> dict:
    """
    Full RAG verification pipeline.
    Uses verified_assertion cache first, then RAG.
    """
```

---

## 9. Implementation Phases

### Phase 1: Stop Caching Gemini Conclusions [COMPLETED]

**Goal:** Immediately stop poisoning the database.

**Changes:**
- Added `needs_review_queue` table
- Modified search cache to not store LLM conclusions as truth
- Return "unknown (no verified proof)" instead of caching guesses

**Files:**
- `app/web/db/models/tariff_tables.py` - NeedsReviewQueue model

### Phase 2: Document Store + Chunking [COMPLETED]

**Goal:** Build the official document corpus.

**Deliverables:**
- `documents` table
- `document_chunks` table
- Trusted connectors (CSMS, GovInfo, USITC)
- Document chunker

**Files:**
- `app/web/db/models/document.py`
- `app/ingestion/connectors/base.py`
- `app/ingestion/connectors/csms.py`
- `app/ingestion/connectors/govinfo.py`
- `app/ingestion/connectors/usitc.py`
- `app/ingestion/chunker.py`

### Phase 3: Reader + Validator + Write Gate [COMPLETED]

**Goal:** Answer from corpus with proof.

**Deliverables:**
- Reader LLM with strict JSON output
- Validator LLM with citation verification
- Write Gate with mechanical checks

**Files:**
- `app/rag/reader_llm.py`
- `app/rag/validator_llm.py`
- `app/rag/write_gate.py`
- `app/rag/orchestrator.py`

### Phase 4: Verified Assertions Store [COMPLETED]

**Goal:** Durable truth table with versioning.

**Deliverables:**
- `verified_assertions` table
- Effective date versioning
- Proof chain storage

**Files:**
- `app/web/db/models/document.py` (VerifiedAssertion model)

### Phase 5: Discovery Mode [COMPLETED]

**Goal:** Auto-populate corpus when needed.

**Deliverables:**
- Gemini discovery (URLs only)
- Connector fetch → store → chunk → embed
- Re-run RAG with new evidence

**Files:**
- `mcp_servers/hts_verifier.py`

---

## 10. Testing

### Test Structure

```
tests/test_rag/
├── __init__.py
├── conftest.py              # RAG-specific fixtures
├── test_document_models.py  # Document, Chunk, Assertion models
├── test_connectors.py       # CSMS, GovInfo, USITC connectors
├── test_chunker.py          # Document chunking
├── test_reader_llm.py       # Reader LLM
├── test_validator_llm.py    # Validator LLM
├── test_write_gate.py       # Write Gate checks
├── test_orchestrator.py     # RAG Orchestrator
└── test_integration.py      # End-to-end tests
```

### Running Tests

```bash
# Run all RAG tests
pipenv run pytest tests/test_rag/ -v

# Run specific test file
pipenv run pytest tests/test_rag/test_write_gate.py -v

# Run with coverage
pipenv run pytest tests/test_rag/ --cov=app/rag --cov-report=html
```

### Current Status

```
112 tests passed, 2 warnings
```

---

## 11. API Reference

### RAG Orchestrator

```python
from app.rag.orchestrator import RAGOrchestrator

orchestrator = RAGOrchestrator(db_session)
result = orchestrator.verify_scope(
    hts_code="8544.42.9090",
    program_id="section_232_steel",
    material="steel",
    force_rag=False  # Skip cache if True
)

# Result
{
    "success": True,
    "source": "verified_cache" | "rag_verified" | "rag_pending" | "discovery_needed",
    "is_verified": True,
    "in_scope": True,
    "claim_codes": ["9903.78.01"],
    "confidence": "high",
    "evidence_quote": "HTS 8544.42.9090 is subject to...",
    "document_id": "uuid",
    "verified_assertion_id": "uuid"
}
```

### Document Ingestion

```python
from app.ingestion.connectors.csms import CSMSConnector
from app.ingestion.chunker import DocumentChunker

# Fetch document
connector = CSMSConnector()
result = connector.fetch("https://content.govdelivery.com/...")

# Chunk document
chunker = DocumentChunker()
chunks = chunker.chunk_document(result)

# Store in database
doc = Document(
    id=result.document_id,
    source=result.source,
    tier=result.tier,
    ...
)
db.session.add(doc)
for chunk in chunks:
    db_chunk = DocumentChunk(...)
    db.session.add(db_chunk)
db.session.commit()
```

### Write Gate

```python
from app.rag.write_gate import WriteGate

gate = WriteGate(db_session)
result = gate.check(reader_output, validator_output)

if result.passed:
    # Store verified assertion
else:
    # Queue for review
    print(result.errors)
```

---

## 12. Operational Guide

### Migration

```bash
# Create all v10.0 tables
pipenv run python scripts/migrate_v10_full.py

# Reset tables (development only)
pipenv run python scripts/migrate_v10_full.py --reset

# Show statistics
pipenv run python scripts/migrate_v10_full.py --stats
```

### Monitoring

Key metrics to track:
- **L1 Hit Rate:** verified_assertion cache hits
- **L2 Hit Rate:** RAG pipeline success rate
- **Discovery Rate:** How often Layer 3 is needed
- **Validation Failure Rate:** Write Gate rejections
- **Review Queue Size:** needs_review_queue pending count

### Troubleshooting

**Issue:** RAG returns "no_chunks_found"
- **Cause:** Corpus lacks relevant documents
- **Fix:** Run discovery mode or manually ingest documents

**Issue:** Write Gate fails "quote not found"
- **Cause:** Reader LLM cited a paraphrased quote
- **Fix:** Check Reader LLM prompt; quote must be verbatim

**Issue:** Validator returns "verified: false"
- **Cause:** Citation doesn't support the claim
- **Fix:** Review Reader output; may need human review

---

## Summary

### What v10.0 Achieves

| Property | How It's Achieved |
|----------|-------------------|
| **Proof-carrying** | Every assertion links to stored evidence quote |
| **Auditable** | Full provenance: connector → document → chunk → citation |
| **Versioned** | effective_start/effective_end on assertions |
| **No regex/rules** | LLMs interpret; Write Gate verifies mechanically |
| **Legally defensible** | Can answer "show me where this is written" |

### The Three LLM Roles

| LLM | Job | Trusted? |
|-----|-----|----------|
| **Reader** | Answer from chunks, cite exact quotes | Interpretation trusted, citations verified |
| **Validator** | Confirm citations are supported | Reduces correlated mistakes |
| **Discovery (Gemini)** | Find official URLs | URLs trusted, conclusions NOT trusted |

### One-Line Summary

> **RAG retrieves from our official corpus → Reader answers with citations → Validator confirms → Write Gate checks proof → Store verified assertion.**

---

*Last Updated: January 2026*
