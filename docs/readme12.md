# Lanes Tariff System - Complete Architecture Documentation

**Version:** v9.3 (Evidence-First Citations + Vector Indexing)
**Date:** January 2026
**Status:** Production Ready

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [MCP Server Architecture](#2-mcp-server-architecture)
3. [3-Tier Cache Architecture](#3-3-tier-cache-architecture)
4. [Database Schema](#4-database-schema)
5. [Vector Search System (v9.3)](#5-vector-search-system-v93)
6. [Data Flow & Integration](#6-data-flow--integration)
7. [Tariff Calculation Logic](#7-tariff-calculation-logic)
8. [Directory Structure](#8-directory-structure)
9. [Configuration Reference](#9-configuration-reference)

---

## 1. System Overview

Lanes is an AI-powered tariff verification and calculation system that:

- **Verifies HTS code scope** for Section 232 (Steel/Copper/Aluminum) and Section 301 tariffs
- **Calculates stacked duties** including IEEPA Fentanyl and IEEPA Reciprocal
- **Caches results** using a 3-tier architecture (PostgreSQL → Pinecone → Gemini)
- **Provides evidence-first citations** with verbatim quotes from official sources

### Key Features

| Feature | Description |
|---------|-------------|
| **Evidence-First (v9.2)** | Gemini returns citations with verbatim quotes from CBP/CSMS sources |
| **Vector Caching (v9.3)** | Evidence quotes indexed in Pinecone for semantic search |
| **Data-Driven Logic** | No hardcoded country/HTS rules - everything in database |
| **Multi-Model Support** | Flash (free tier) vs Pro (thinking mode) |
| **Audit Trail** | Every search logged with cost tracking |

---

## 2. MCP Server Architecture

### Location: `/mcp_servers/`

The system uses the **Model Context Protocol (MCP)** via FastMCP to expose AI-powered tools.

### 2.1 HTS Verifier Server (`hts_verifier.py`)

The main MCP server providing tariff verification tools.

```
┌──────────────────────────────────────────────────────────────┐
│                    HTS Verifier MCP Server                   │
│                     (FastMCP Framework)                       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Tool 1: verify_hts_scope()                                  │
│  ├── Purpose: Section 232 material scope verification        │
│  ├── Parameters:                                             │
│  │   ├── hts_code: "8544.42.9090"                           │
│  │   ├── material: "all" | "copper" | "steel" | "aluminum"  │
│  │   ├── use_production_model: bool (Flash vs Pro)          │
│  │   ├── force_search: bool (bypass cache)                  │
│  │   └── use_v2_schema: bool (evidence-first)               │
│  └── Returns: scope data with citations[]                   │
│                                                              │
│  Tool 2: verify_section_301()                                │
│  ├── Purpose: Section 301 list assignment                   │
│  ├── Parameters: hts_code, use_production_model, force_search│
│  └── Returns: list_name, chapter_99_code, duty_rate         │
│                                                              │
│  Tool 3: test_gemini_connection()                            │
│  └── Purpose: API connectivity test                          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Configuration (`config.py`)

```python
MODELS = {
    "test": "gemini-2.5-flash",           # Free tier, fast
    "production": "gemini-3-pro-preview"  # Paid, with thinking mode
}

THINKING_BUDGET = {
    "low": 1024,
    "medium": 8192,
    "high": 16384  # For complex verification
}

CACHE_TTL_DAYS = 30
MAX_FORCE_SEARCHES_PER_HOUR = 10
```

### 2.3 Schema Validation (`schemas.py`)

#### Legacy Schema (v9.1)

```python
class MetalScope(BaseModel):
    in_scope: Optional[bool]
    claim_code: Optional[str]
    disclaim_code: Optional[str]
    source: Optional[str]

class Section232Result(BaseModel):
    hts_code: str
    copper: MetalScope
    steel: MetalScope
    aluminum: MetalScope
    notes: Optional[str]
```

#### Evidence-First Schema (v9.2)

```python
class Citation(BaseModel):
    source_url: str
    source_title: Optional[str]
    source_document: Optional[str]  # "CSMS #65936570"
    effective_date: Optional[str]   # "2025-08-18"
    location_hint: Optional[str]    # "Table row: 8544.42.90"
    evidence_type: Optional[str]    # "table|paragraph|bullet"
    quoted_text: Optional[str]      # Verbatim, max 400 chars

class MetalScopeV2(BaseModel):
    in_scope: Optional[bool]  # true/false/null
    claim_code: Optional[str]
    disclaim_code: Optional[str]
    citations: List[Citation]

class Section232ResultV2(BaseModel):
    hts_code: str
    query_type: str = "section_232"
    results: Dict[str, MetalScopeV2]  # {"copper": {...}, "steel": {...}}
    notes: Optional[str]
```

#### Business Validation Rules

```python
def validate_citations_have_proof(result: Section232ResultV2) -> List[str]:
    """
    If in_scope=true, must have:
    - claim_code present
    - At least one citation with source_url + quoted_text
    - quoted_text should contain the HTS code
    """
```

---

## 3. 3-Tier Cache Architecture

### Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          3-TIER CACHE ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────┘

User Query: "Is HTS 8544.42.9090 in scope for Section 232?"
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    LAYER 1: PostgreSQL (Exact Match)                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ SELECT * FROM gemini_search_results                                  │  │
│  │ WHERE hts_code = '8544.42.9090'                                     │  │
│  │   AND query_type = 'section_232'                                    │  │
│  │   AND (expires_at IS NULL OR expires_at > NOW())                    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                              │ HIT → Return cached result                  │
│                              │ MISS ↓                                      │
└──────────────────────────────┼─────────────────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                   LAYER 2: Pinecone (Semantic Search)                      │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Query: "Section 232 copper steel aluminum for HTS 8544.42.9090"     │  │
│  │ Vector similarity search with filters:                              │  │
│  │   - chunk_type = "evidence_quote"                                   │  │
│  │   - hts_code = "8544.42.9090"                                       │  │
│  │ Threshold: similarity >= 0.85                                       │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                              │ HIT → Return semantic match                 │
│                              │ MISS ↓                                      │
└──────────────────────────────┼─────────────────────────────────────────────┘
                               ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    LAYER 3: Gemini (Live Search)                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Call verify_hts_scope() with Google Search grounding                │  │
│  │ Searches: CBP CSMS, Federal Register, USTR sources                  │  │
│  │ Returns: Structured JSON with citations[]                           │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ PERSIST RESULTS:                                                    │  │
│  │ 1. gemini_search_results (PostgreSQL)                               │  │
│  │ 2. grounding_sources (PostgreSQL)                                   │  │
│  │ 3. evidence_quotes (PostgreSQL)                                     │  │
│  │ 4. Vector chunks (Pinecone)                                         │  │
│  │ 5. Evidence quote vectors (Pinecone v9.3)                           │  │
│  │ 6. search_audit_log (PostgreSQL)                                    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

### Cache Service (`search_cache.py`)

```python
# Key functions:

def check_cache_before_gemini(session, hts_code, query_type, material, force_search):
    """Multi-tier cache lookup. Returns {"hit": True/False, "source": "postgres"|"pinecone"}"""

def persist_search_result(session, hts_code, query_type, material, result_json, ...):
    """Save to PostgreSQL + Pinecone after successful Gemini search"""

def persist_evidence_quotes(session, search_result_id, hts_code, query_type, result_json, grounding_urls):
    """Extract citations[] and create EvidenceQuote records (v9.2)"""

def log_search_request(session, hts_code, query_type, cache_hit, response_time_ms, model_used, ...):
    """Audit trail with cost tracking"""
```

---

## 4. Database Schema

### Location: `/app/web/db/models/tariff_tables.py`

The system uses **21 database tables** organized into functional groups:

### 4.1 Program Configuration Layer

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        PROGRAM CONFIGURATION                                │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  TariffProgram                    Section301Inclusion                      │
│  ├── program_id (PK)              ├── id (PK)                              │
│  ├── country                      ├── hts_8digit                           │
│  ├── check_type                   ├── list_name (list_1-4a)                │
│  ├── condition_handler            ├── chapter_99_code                      │
│  ├── inclusion_table              └── duty_rate                            │
│  ├── exclusion_table                                                       │
│  ├── filing_sequence              Section301Exclusion                      │
│  ├── calculation_sequence         ├── id (PK)                              │
│  └── disclaim_behavior            ├── hts_8digit                           │
│      ("required"|"omit"|"none")   ├── description                          │
│                                   └── extended_to                          │
│  Section232Material                                                        │
│  ├── id (PK)                                                               │
│  ├── hts_8digit                                                            │
│  ├── material (copper|steel|aluminum)                                      │
│  ├── claim_code                                                            │
│  ├── disclaim_code                                                         │
│  ├── duty_rate                                                             │
│  ├── content_basis (value|mass|percent)                                    │
│  └── split_policy (never|if_any_content|if_above_threshold)                │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Output Code Layer

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           OUTPUT CODES                                      │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ProgramCode                      DutyRule                                 │
│  ├── program_id (FK)              ├── program_id (FK)                      │
│  ├── action (claim|disclaim|...)  ├── variant                              │
│  ├── variant                      ├── calculation_type                     │
│  ├── slice_type                   ├── base_on                              │
│  └── chapter_99_code              ├── base_effect                          │
│                                   └── content_key                          │
│  Actions:                                                                  │
│  - claim: Product is subject                                               │
│  - disclaim: Product is NOT subject (copper only)                          │
│  - apply: Apply this duty                                                  │
│  - paid: Duty has been paid                                                │
│  - exempt: Exemption applies                                               │
│                                                                            │
│  Slice Types:                                                              │
│  - all: Applies to entire entry                                            │
│  - non_metal: Residual value after metals                                  │
│  - copper_slice / steel_slice / aluminum_slice: Metal content              │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Country Grouping Layer

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          COUNTRY GROUPING                                   │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  CountryAlias                     CountryGroup                             │
│  ├── alias (PK)                   ├── group_id (PK)                        │
│  └── iso_alpha2                   ├── description                          │
│                                   ├── effective_date                       │
│  Maps: "Macau" → "MO"             └── expiration_date                      │
│        "China" → "CN"                                                      │
│        "Hong Kong" → "HK"         CountryGroupMember                       │
│                                   ├── id (PK)                              │
│  ProgramCountryScope              ├── country_code                         │
│  ├── id (PK)                      └── group_id (FK)                        │
│  ├── program_id (FK)                                                       │
│  ├── country_group_id (FK)        ProgramRate                              │
│  ├── iso_alpha2                   ├── program_id (FK)                      │
│  └── scope_type (include|exclude) ├── group_id (FK)                        │
│                                   ├── effective_date                       │
│                                   ├── rate_type (fixed|formula)            │
│                                   └── rate_formula                         │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Search & Caching Layer (v9.x)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       SEARCH & CACHING (v9.0-v9.3)                          │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  GeminiSearchResult              GroundingSource                           │
│  ├── id (PK, UUID)               ├── id (PK, UUID)                         │
│  ├── hts_code                    ├── search_result_id (FK) ──────┐         │
│  ├── query_type                  ├── url                         │         │
│  ├── material                    ├── domain                      │         │
│  ├── result_json                 ├── source_type                 │         │
│  ├── raw_response                └── reliability_score           │         │
│  ├── model_used                                                  │         │
│  ├── thinking_budget             SearchAuditLog                  │         │
│  ├── searched_at                 ├── id (PK, UUID)               │         │
│  ├── expires_at                  ├── hts_code                    │         │
│  ├── is_verified                 ├── query_type                  │         │
│  └── was_force_search            ├── cache_hit                   │         │
│         │                        ├── cache_source                │         │
│         │                        ├── response_time_ms            │         │
│         ▼                        ├── model_used                  │         │
│  EvidenceQuote (v9.2)            ├── input_tokens                │         │
│  ├── id (PK, UUID)               ├── output_tokens               │         │
│  ├── search_result_id (FK) ◄─────┴── estimated_cost_usd          │         │
│  ├── program_id                                                  │         │
│  ├── material                                                    │         │
│  ├── hts_code                                                    │         │
│  ├── in_scope (true/false/null)                                  │         │
│  ├── claim_code                                                  │         │
│  ├── disclaim_code                                               │         │
│  ├── quoted_text                                                 │         │
│  ├── quote_hash (SHA256)                                         │         │
│  ├── quote_verified                                              │         │
│  └── url_in_grounding_metadata                                   │         │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.5 Audit & History Layer

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          AUDIT & HISTORY                                    │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  SourceDocument                   IngestionRun                             │
│  ├── id (PK, UUID)                ├── id (PK, UUID)                        │
│  ├── doc_type (CSMS|FR_notice|EO) ├── run_type                             │
│  ├── doc_identifier               ├── started_at                           │
│  ├── effective_date               ├── completed_at                         │
│  ├── content_hash (SHA256)        ├── records_added                        │
│  └── content_text                 ├── records_updated                      │
│                                   ├── operator                             │
│  ProductHistory                   └── status (success|partial|failed)      │
│  ├── id (PK, UUID)                                                         │
│  ├── hts_code                                                              │
│  ├── product_desc                                                          │
│  ├── components (JSON)                                                     │
│  ├── decisions (JSON)                                                      │
│  └── user_confirmed                                                        │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.6 Exemptions

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            EXEMPTIONS                                       │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  IeepaAnnexIIExclusion                                                     │
│  ├── id (PK)                                                               │
│  ├── hts_code (4-digit prefix)                                             │
│  ├── category (pharmaceutical|chemical|critical_mineral|semiconductor)     │
│  └── effective_date                                                        │
│                                                                            │
│  Lookup: PREFIX MATCH on hts_code                                          │
│  Example: "2934" matches "2934.99.9050"                                    │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Vector Search System (v9.3)

### Location: `/app/chat/vector_stores/tariff_search.py`

### 5.1 Configuration

```python
PINECONE_INDEX_NAME = "lanes-tariff-search"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
CHUNK_SIZE = 500   # Max tokens per chunk
CHUNK_OVERLAP = 50 # Token overlap
SIMILARITY_THRESHOLD = 0.85  # Minimum for cache hit
```

### 5.2 TariffVectorSearch Class

```python
class TariffVectorSearch:
    """Vector search for tariff documents and Gemini search results."""

    def __init__(self):
        self.pc = PineconeClient(api_key=PINECONE_API_KEY)
        self.openai = OpenAI(api_key=OPENAI_API_KEY)
        self.index = self.pc.Index(PINECONE_INDEX_NAME)

    def search_similar(
        self,
        query: str,
        hts_code: Optional[str] = None,
        query_type: Optional[str] = None,
        chunk_type: Optional[str] = None,  # "evidence_quote" | "gemini_response"
        material: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict]:
        """Semantic search with metadata filtering."""

    def index_search_result(
        self,
        search_result_id: str,
        hts_code: str,
        query_type: str,
        material: Optional[str],
        raw_response: str,
        model_used: str,
        grounding_sources: Optional[List[Dict]]
    ) -> int:
        """Index Gemini response chunks."""

    def index_evidence_quotes(
        self,
        search_result_id: str,
        hts_code: str,
        query_type: str,
        result_json: Dict,
        grounding_urls: List[str]
    ) -> int:
        """Index evidence quotes as high-signal chunks (v9.3)."""
```

### 5.3 Vector Metadata Schema

```json
{
  "chunk_type": "evidence_quote",
  "search_result_id": "uuid",
  "hts_code": "8544.42.9090",
  "query_type": "section_232",
  "material": "copper",
  "in_scope": true,
  "claim_code": "9903.78.01",
  "disclaim_code": "9903.78.02",
  "source_url": "https://cbp.gov/...",
  "source_domain": "cbp.gov",
  "reliability_score": 1.0,
  "url_in_grounding_metadata": true,
  "quote_verified": false,
  "chunk_text": "8544.42.90 - Insulated copper wire...",
  "indexed_at": "2026-01-03T05:00:00Z"
}
```

### 5.4 Source Reliability Scoring

```python
RELIABILITY_SCORES = {
    "official_cbp": 1.0,      # cbp.gov
    "federal_register": 1.0,  # federalregister.gov
    "ustr": 0.95,             # ustr.gov
    "usitc": 0.95,            # usitc.gov
    "csms": 0.90,             # CSMS messages
    "other": 0.50             # Unknown sources
}
```

---

## 6. Data Flow & Integration

### 6.1 Complete Request Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        COMPLETE REQUEST FLOW                              │
└──────────────────────────────────────────────────────────────────────────┘

User Request: "Calculate tariffs for USB-C cable from China"
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Step 1: STACKING TOOLS (app/chat/tools/stacking_tools.py)                │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ calculate_stacking(                                                  │ │
│ │   hts_code="8544.42.9090",                                          │ │
│ │   country="China",                                                   │ │
│ │   product_value=10000.00,                                           │ │
│ │   materials={"copper": 3000, "steel": 1000, "aluminum": 1000}       │ │
│ │ )                                                                    │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Step 2: PROGRAM LOOKUP                                                    │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ For each applicable program:                                         │ │
│ │ - Section 301 (China only) → check Section301Inclusion               │ │
│ │ - Section 232 (all countries) → check Section232Material             │ │
│ │ - IEEPA Fentanyl (China only) → always applies                       │ │
│ │ - IEEPA Reciprocal (China only) → on remaining_value                 │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Step 3: SCOPE VERIFICATION (Optional)                                     │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ If scope uncertain → Call MCP verify_hts_scope()                     │ │
│ │ → 3-tier cache check                                                 │ │
│ │ → Gemini with Google Search grounding (if miss)                      │ │
│ │ → Return in_scope, claim_code, citations[]                           │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Step 4: ENTRY SLICING (v4.0)                                              │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ Create entry slices based on materials:                              │ │
│ │ - non_metal slice: $5,000 (residual)                                 │ │
│ │ - copper_slice: $3,000                                               │ │
│ │ - steel_slice: $1,000                                                │ │
│ │ - aluminum_slice: $1,000                                             │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Step 5: DUTY CALCULATION                                                  │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ For each program × slice:                                            │ │
│ │ - Get DutyRule (calculation_type, base_on, rate)                     │ │
│ │ - Apply disclaim_behavior (required/omit)                            │ │
│ │ - Calculate duty amount                                              │ │
│ │ - Track remaining_value for IEEPA unstacking                         │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Step 6: RESULT ASSEMBLY                                                   │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ Return:                                                              │ │
│ │ {                                                                    │ │
│ │   "entries": [                                                       │ │
│ │     {"slice_type": "non_metal", "value": 5000, "stack": [...]},      │ │
│ │     {"slice_type": "copper_slice", "value": 3000, "stack": [...]},   │ │
│ │     ...                                                              │ │
│ │   ],                                                                 │ │
│ │   "total_duty": {"amount": 6250.00, "effective_rate": 0.625},        │ │
│ │   "decision_audit": [...]                                            │ │
│ │ }                                                                    │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Tariff Calculation Logic

### 7.1 Applicable Programs by Country

| Program | China | Hong Kong | Macau | Germany | UK | Others |
|---------|-------|-----------|-------|---------|-----|--------|
| Section 301 | Yes (List 1-4) | No | No | No | No | No |
| IEEPA Fentanyl | Yes (10%) | Yes | Yes | No | No | No |
| IEEPA Reciprocal | Yes (10%) | No | No | No | No | No |
| Section 232 Copper | Yes (50%) | Yes | Yes | Yes | Yes | Yes |
| Section 232 Steel | Yes (50%) | Yes | Yes | Yes | Yes | Yes |
| Section 232 Aluminum | Yes (25%) | Yes | Yes | Yes | Yes | Yes |

### 7.2 Tariff Rates Reference

| Program | Rate | Notes |
|---------|------|-------|
| Section 301 List 1-3 | 25% | China products |
| Section 301 List 4A | 7.5% | China products |
| IEEPA Fentanyl | 10% | China, HK, Macau |
| IEEPA Reciprocal | 10% | On remaining_value after 232 |
| Section 232 Copper | 50% | On copper content value |
| Section 232 Steel | 50% | On steel content value |
| Section 232 Aluminum | 25% | On aluminum content value |

### 7.3 Disclaim Behavior (v7.0 Phoebe)

| Material | disclaim_behavior | Effect |
|----------|------------------|--------|
| Copper | `required` | Disclaim (9903.78.02) appears in ALL non-copper slices |
| Steel | `omit` | No disclaim line ever appears |
| Aluminum | `omit` | No disclaim line ever appears |

### 7.4 IEEPA Unstacking (Phase 6.5)

```
Product Value: $10,000
  - Copper content: $3,000
  - Steel content: $1,000
  - Aluminum content: $1,000
  - Remaining value: $5,000

IEEPA Reciprocal applies to:
  remaining_value = $10,000 - $3,000 - $1,000 - $1,000 = $5,000

Duty = $5,000 × 10% = $500 (NOT $10,000 × 10% = $1,000)
```

### 7.5 Key Chapter 99 Codes

| Code | Program | Action |
|------|---------|--------|
| 9903.78.01 | Section 232 Copper | Claim |
| 9903.78.02 | Section 232 Copper | Disclaim |
| 9903.80.01-03 | Section 232 Steel | Claim |
| 9903.81.91 | Section 232 Steel (Derivative) | Claim |
| 9903.85.01-08 | Section 232 Aluminum | Claim |
| 9903.88.01 | Section 301 List 1 | Apply |
| 9903.88.02 | Section 301 List 2 | Apply |
| 9903.88.03 | Section 301 List 3 | Apply |
| 9903.88.15 | Section 301 List 4A | Apply |
| 9903.01.25 | IEEPA Reciprocal | Paid |
| 9903.01.32 | IEEPA Annex II | Exempt |

---

## 8. Directory Structure

```
lanes/
├── mcp_servers/                    # MCP Server Layer
│   ├── __init__.py
│   ├── config.py                   # Gemini API config, model selection
│   ├── hts_verifier.py             # Main MCP server (FastMCP)
│   ├── schemas.py                  # Pydantic validation (v9.1 + v9.2)
│   └── search_cache.py             # 3-tier cache orchestration
│
├── app/
│   ├── web/                        # Web/API Layer
│   │   ├── db/
│   │   │   ├── __init__.py         # SQLAlchemy setup
│   │   │   └── models/
│   │   │       └── tariff_tables.py  # 21 database models
│   │   ├── api.py                  # Flask app
│   │   └── views/                  # Route handlers
│   │
│   └── chat/                       # Chat/LLM Layer
│       ├── tools/
│       │   ├── trade_tools.py      # HTS lookup, document search
│       │   └── stacking_tools.py   # Tariff calculation
│       ├── graphs/
│       │   └── stacking_rag.py     # LangGraph implementation
│       └── vector_stores/
│           └── tariff_search.py    # Pinecone integration (v9.3)
│
├── scripts/
│   ├── populate_tariff_tables.py   # Seed tariff tables
│   ├── migrate_v9_search_tables.py # v9.0 migration
│   └── seed_gemini_search.py       # Seed Gemini cache
│
├── tests/
│   ├── test_stacking_v7_phoebe.py  # v7.0 Phoebe tests
│   ├── test_stacking_automated.py  # Phase 6/6.5 tests
│   ├── test_stacking_v7_stability.py
│   ├── test_v9_search_persistence.py
│   ├── test_vector_indexing.py
│   └── test_mcp_parsing.py
│
└── docs/
    ├── readme11.md                 # Previous documentation
    ├── readme12.md                 # This file
    └── readme12-tests.md           # Test documentation
```

---

## 9. Configuration Reference

### 9.1 Environment Variables

```bash
# Gemini API
GEMINI_API_KEY=your_gemini_key

# OpenAI (for embeddings)
OPENAI_API_KEY=your_openai_key

# Pinecone
PINECONE_API_KEY=your_pinecone_key
PINECONE_TARIFF_INDEX=lanes-tariff-search

# Database
DATABASE_URL=postgresql://user:pass@host:5432/lanes
```

### 9.2 Model Selection

```python
# In mcp_servers/config.py

MODELS = {
    "test": "gemini-2.5-flash",           # Free, fast (development)
    "production": "gemini-3-pro-preview"  # Paid, thinking mode
}

# Usage:
verify_hts_scope(hts_code, use_production_model=True)  # Uses Pro
verify_hts_scope(hts_code, use_production_model=False) # Uses Flash (default)
```

### 9.3 Cache Configuration

```python
CACHE_TTL_DAYS = 30                    # Results expire after 30 days
PINECONE_SIMILARITY_THRESHOLD = 0.85   # Minimum for semantic cache hit
MAX_FORCE_SEARCHES_PER_HOUR = 10       # Rate limiting
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v9.0 | Jan 2026 | Search Persistence + 3-tier cache |
| v9.2 | Jan 2026 | Evidence-First Citations with quoted_text |
| v9.3 | Jan 2026 | Evidence Quote Vector Indexing in Pinecone |
| v7.0 | Dec 2025 | Phoebe ACE filing model (disclaim_behavior) |
| v6.5 | Dec 2025 | IEEPA Unstacking (remaining_value) |
| v6.0 | Nov 2025 | Content-value-based duties |
| v4.0 | Oct 2025 | Entry slicing (multi-slice output) |

---

*Generated: January 2026*
