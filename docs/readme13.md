# Section 232 Tariff Stacking System (v13.0)

**Date:** January 2026
**Status:** Production Ready
**Regulatory Alignment:** Federal Register 90 FR 40326, CSMS #65794272, #65936615, #65936570

---

## 1. Executive Summary

This document describes the Section 232 tariff stacking system as implemented for ACE (Automated Commercial Environment) filing. The system calculates and stacks multiple tariff programs for goods imported into the United States, with specific focus on:

- **Section 232 Steel/Aluminum/Copper** - Content-based duties on metal derivatives
- **Section 301** - China trade tariffs
- **IEEPA Fentanyl** - Emergency tariffs on fentanyl-related imports
- **IEEPA Reciprocal** - Reciprocal tariffs with country-specific rates

The system is aligned with **Phoebe's ACE filing examples** as ground truth for Chapter 99 code usage.

---

## 2. Current Tariff Rates (January 2026)

### 2.1 Section 232 Rates

Per **Presidential Proclamation 90 FR 10524 (June 4, 2025)**, Section 232 rates were **DOUBLED** for steel and aluminum:

| Metal | Default Rate | UK Exception | Effective Date |
|-------|-------------|--------------|----------------|
| **Copper** | 50% | 50% (no exception) | July 2025 |
| **Steel** | 50% | 25% | June 4, 2025 |
| **Aluminum** | 50% | 25% | June 4, 2025 |

### 2.2 Other Program Rates

| Program | Rate | Notes |
|---------|------|-------|
| Section 301 | 25% | China only, List-specific codes |
| IEEPA Fentanyl | 10% | Reduced from 20% (Nov 2025) |
| IEEPA Reciprocal | 10% (default) | EU: 15% - MFN formula |

---

## 3. HTS Scope Definition

### 3.1 Corrected Section 232 Scope (Final)

Based on regulatory alignment with Federal Register and CSMS guidance:

| HTS Code | Product | Cu | St | Al | Authority |
|----------|---------|----|----|----| ----------|
| 8544.42.2000 | Insulated copper wire (≤80V) | ✅ 50% | ❌ | ❌ | CSMS #65794272 |
| 8544.42.9090 | Insulated wire/cable (>80V) | ✅ 50% | ❌ | ✅ 50% | CSMS #65794272 + #65936615 |
| 9403.99.9045 | Furniture parts (metal) | ❌ | ✅ 50% | ✅ 50% | CSMS #65936570 + #65936615 |
| 8473.30.5100 | Computer parts | ❌ | ❌ | ✅ 50% | CSMS #65936615 |
| 8536.90.8585 | Electrical apparatus parts | ❌ | ❌ | ✅ 50% | CSMS #65936615 |

**Removed from scope:** 8539.50.0000 (LED lamps) - not in any 2025 derivative list

### 3.2 Regulatory Authority

| Document | Identifier | Effective Date | Purpose |
|----------|------------|----------------|---------|
| Presidential Proclamation | 90 FR 10524 | 2025-06-04 | Doubled 232 rates to 50% |
| Federal Register | 90 FR 40326 | 2025-08-19 | HTS inclusions process |
| CSMS | #65794272 | 2025-08-01 | Copper derivative guidance (Note 36) |
| CSMS | #65936615 | 2025-08-18 | Aluminum derivative guidance (Note 19k) |
| CSMS | #65936570 | 2025-08-18 | Steel derivative guidance (Note 16n) |

### 3.3 Chapter 99 Codes

| Metal | Claim Code | Disclaim Code | Disclaim Behavior |
|-------|------------|---------------|-------------------|
| Copper | 9903.78.01 | 9903.78.02 | **required** (always appears) |
| Steel | 9903.81.91 (derivative) | 9903.80.02 | **omit** (never appears) |
| Aluminum | 9903.85.08 | 9903.85.09 | **omit** (never appears) |

---

## 4. Stacking Architecture

### 4.1 Entry Slice Model (v4.0)

Products are split into **slices** based on material content. Each slice becomes a separate ACE filing line:

```
Product ($10,000)
├── non_metal slice ($6,000) - residual value
├── copper_slice ($3,000) - copper content value
└── aluminum_slice ($1,000) - aluminum content value
```

### 4.2 Program Application by Slice

| Program | non_metal | copper_slice | steel_slice | aluminum_slice |
|---------|-----------|--------------|-------------|----------------|
| Section 301 | apply | apply | apply | apply |
| IEEPA Fentanyl | apply | apply | apply | apply |
| IEEPA Reciprocal | **paid** | exempt | exempt | exempt |
| 232 Copper | disclaim | **claim** | disclaim | disclaim |
| 232 Steel | (omit) | (omit) | **claim** | (omit) |
| 232 Aluminum | (omit) | (omit) | (omit) | **claim** |

### 4.3 IEEPA Unstacking

Per CBP guidance: "Content subject to Section 232 is NOT subject to Reciprocal IEEPA"

```
remaining_value = product_value - copper_value - steel_value - aluminum_value
ieepa_reciprocal_duty = remaining_value × 10%
```

---

## 5. Phoebe's ACE Filing Examples (Ground Truth)

These examples from Phoebe's ACE filing training serve as the authoritative reference for Chapter 99 code usage:

### 5.1 Example Reference Table

| Example | HTS | Chapter 99 Codes Used | Confirms |
|---------|-----|----------------------|----------|
| Steel+Al 50/50 | 9403.99.9045 | 9903.81.91 + 9903.85.08 | Steel + Aluminum |
| Copper+Al 50/50 | 8544.42.9090 | 9903.78.01 + 9903.85.08 | Copper + Aluminum (NO steel!) |
| Disclaim Al | 8536.90.8585 | No 232 codes | Aluminum scope (omit behavior) |
| Copper full | 8544.42.2000 | 9903.78.01 only | Copper ONLY |
| Al claim | 8473.30.5100 | 9903.85.08 | Aluminum only |

### 5.2 Key Insights from Phoebe

1. **Steel uses derivative code 9903.81.91** (not 9903.80.01) for furniture parts
2. **8544.42.9090 does NOT have steel in scope** - only copper + aluminum
3. **Disclaim behavior is "omit"** for steel/aluminum - no code appears when not claiming
4. **Disclaim behavior is "required"** for copper - 9903.78.02 always appears in non-copper slices

---

## 6. Duty Calculation Examples

### 6.1 China 2-Metal Cable (8544.42.9090)

**Input:**
- HTS: 8544.42.9090
- Country: China
- Value: $10,000
- Materials: copper=$3,000, aluminum=$1,000

**Calculation:**
```
Section 301:      $10,000 × 25% = $2,500
IEEPA Fentanyl:   $10,000 × 10% = $1,000
232 Copper:       $3,000 × 50%  = $1,500
232 Aluminum:     $1,000 × 50%  = $500
IEEPA Reciprocal: $6,000 × 10%  = $600  (on remaining_value)
──────────────────────────────────────
Total Duty:                       $6,100 (61.0% effective rate)
```

### 6.2 Germany 2-Metal Cable (232 only)

**Input:**
- HTS: 8544.42.9090
- Country: Germany
- Value: $10,000
- Materials: copper=$3,000, aluminum=$1,000

**Calculation:**
```
232 Copper:   $3,000 × 50% = $1,500
232 Aluminum: $1,000 × 50% = $500
──────────────────────────────────
Total Duty:                 $2,000 (20.0% effective rate)
```

### 6.3 Steel + Aluminum Furniture Parts (9403.99.9045)

**Input:**
- HTS: 9403.99.9045
- Country: China
- Value: $10,000
- Materials: steel=$8,000, aluminum=$1,500

**Calculation:**
```
Section 301:      $10,000 × 25% = $2,500
IEEPA Fentanyl:   $10,000 × 10% = $1,000
232 Steel:        $8,000 × 50%  = $4,000
232 Aluminum:     $1,500 × 50%  = $750
IEEPA Reciprocal: $500 × 10%    = $50   (on remaining_value)
──────────────────────────────────────
Total Duty:                       $8,300 (83.0% effective rate)
```

---

## 7. Database Schema

### 7.1 section_232_materials

```sql
CREATE TABLE section_232_materials (
    id UUID PRIMARY KEY,
    hts_8digit VARCHAR(10) NOT NULL,
    material VARCHAR(20) NOT NULL,  -- 'copper', 'steel', 'aluminum'
    claim_code VARCHAR(12) NOT NULL,
    disclaim_code VARCHAR(12),
    duty_rate DECIMAL(5,4) NOT NULL,
    threshold_percent DECIMAL(5,4),
    source_doc VARCHAR(255),
    content_basis VARCHAR(20) DEFAULT 'value',
    quantity_unit VARCHAR(10) DEFAULT 'kg',
    split_policy VARCHAR(30) DEFAULT 'if_any_content',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 Current Data

```sql
SELECT hts_8digit, material, claim_code, duty_rate
FROM section_232_materials
ORDER BY hts_8digit, material;
```

| hts_8digit | material | claim_code | duty_rate |
|------------|----------|------------|-----------|
| 84733051 | aluminum | 9903.85.08 | 0.50 |
| 85369085 | aluminum | 9903.85.08 | 0.50 |
| 85444220 | copper | 9903.78.01 | 0.50 |
| 85444290 | aluminum | 9903.85.08 | 0.50 |
| 85444290 | copper | 9903.78.01 | 0.50 |
| 94039990 | aluminum | 9903.85.08 | 0.50 |
| 94039990 | steel | 9903.81.91 | 0.50 |

---

## 8. System Components

### 8.1 Core Files

| File | Purpose |
|------|---------|
| `app/chat/graphs/stacking_rag.py` | Main stacking calculation engine |
| `app/web/db/models/tariff_tables.py` | SQLAlchemy models for tariff data |
| `scripts/populate_tariff_tables.py` | Database population script |
| `scripts/migrate_v9_search_tables.py` | Search cache table management |

### 8.2 Test Files

| File | Purpose |
|------|---------|
| `tests/test_stacking_v7_phoebe.py` | Phoebe-aligned test cases (7 tests) |
| `tests/test_stacking_automated.py` | Comprehensive automated tests (12 tests) |

---

## 9. Implementation History

### 9.1 Version Timeline

| Version | Date | Changes |
|---------|------|---------|
| v4.0 | Dec 2025 | Entry slice model, Annex II exclusions |
| v5.0 | Dec 2025 | Country groups, program rates, HTS base rates |
| v6.0 | Dec 2025 | Content-value-based duties, copper 50% |
| v6.5 | Dec 2025 | IEEPA unstacking (CBP compliance) |
| v7.0 | Dec 2025 | Phoebe alignment, disclaim_behavior |
| v9.0 | Dec 2025 | Search persistence, Gemini caching |
| v9.2 | Jan 2026 | Evidence-first citations |
| v9.3 | Jan 2026 | Vector indexing for evidence quotes |
| **v13.0** | Jan 2026 | Regulatory alignment (50% rates, HTS scope) |

### 9.2 v13.0 Changes Summary

1. **Aluminum rate updated to 50%** per Presidential Proclamation 90 FR 10524
2. **HTS scope corrected** per Federal Register 90 FR 40326 and CSMS guidance:
   - 8544.42.2000: Copper only (removed aluminum)
   - 8544.42.9090: Copper + Aluminum (removed steel)
   - 8536.90.8585: Added as aluminum derivative
   - 8539.50.0000: Removed (out of scope)
3. **Test cases updated** to reflect corrected scope and rates

---

## 10. Maintenance Procedures

### 10.1 Updating Tariff Data

```bash
# Reset and repopulate database
pipenv run python scripts/migrate_v9_search_tables.py --reset
pipenv run python scripts/populate_tariff_tables.py --reset

# Verify data
pipenv run python -c "
from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import Section232Material

app = create_app()
with app.app_context():
    for m in db.session.query(Section232Material).all():
        print(f'{m.hts_8digit}: {m.material} @ {m.duty_rate:.0%}')
"
```

### 10.2 Running Tests

```bash
# Phoebe-aligned tests
pipenv run python tests/test_stacking_v7_phoebe.py -v

# Automated stacking tests
pipenv run python tests/test_stacking_automated.py -v
```

### 10.3 Seeding Gemini Cache

```bash
# Seed all supported HTS codes
pipenv run python scripts/seed_gemini_search.py

# Force refresh specific HTS
pipenv run python scripts/seed_gemini_search.py --hts 8544.42.90 --force
```

---

## 11. Appendix: Full Rate Schedule

### 11.1 Section 232 by Country

| Country | Copper | Steel | Aluminum |
|---------|--------|-------|----------|
| Default | 50% | 50% | 50% |
| UK | 50% | 25% | 25% |
| Canada (USMCA) | 50%* | Quota | Quota |
| Mexico (USMCA) | 50%* | Quota | Quota |

*Copper has no country exceptions

### 11.2 Section 301 List Codes

| List | Code | Rate | Example HTS |
|------|------|------|-------------|
| List 1 | 9903.88.01 | 25% | 8536.90.8585 |
| List 2 | 9903.88.02 | 25% | 8471.30.01 |
| List 3 | 9903.88.03 | 25% | 8544.42.9090 |
| List 4A | 9903.88.15 | 7.5% | 9013.80.00 |
| Other | 9903.88.69 | 25% | 8473.30.5100 |

### 11.3 IEEPA Reciprocal Codes

| Variant | Code | Rate | Applies To |
|---------|------|------|------------|
| Taxable | 9903.01.25 | 10% | non_metal slice |
| Annex II Exempt | 9903.01.32 | 0% | Pharma, minerals |
| Metal Exempt | 9903.01.33 | 0% | Metal slices |
| US Content Exempt | 9903.01.34 | 0% | US-origin content |

---

## 12. Document References

1. **Federal Register 90 FR 10524** - Presidential Proclamation doubling 232 rates
   - URL: https://www.federalregister.gov/documents/2025/06/09/2025-10524/adjusting-imports-of-aluminum-and-steel-into-the-united-states

2. **Federal Register 90 FR 40326** - Section 232 Inclusions Process
   - URL: https://www.federalregister.gov/documents/2025/08/19/2025-15819/adoption-and-procedures-of-the-section-232-steel-and-aluminum-tariff-inclusions-process

3. **CSMS #65794272** - Copper Derivative Guidance
   - URL: https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ebf0e0

4. **CSMS #65936615** - Aluminum Derivative Guidance
   - URL: https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ee1ce7

5. **CSMS #65936570** - Steel Derivative Guidance
   - URL: https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ee1cba

---

## 13. System Architecture Overview

### 13.1 Complete Stack Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (SvelteKit)                          │
│   /chat  /documents  /scores  /auth                                    │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ HTTP/Streaming
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          FLASK API LAYER                                │
│   /api/conversations  /api/tariffs  /api/pdfs  /api/auth               │
└────────────┬────────────────────────────────────┬───────────────────────┘
             │                                    │
             ▼                                    ▼
┌────────────────────────────┐      ┌────────────────────────────────────┐
│     CHAT/RAG ENGINE        │      │      TARIFF STACKING ENGINE        │
│  (LangGraph + LangChain)   │      │   (Data-Driven Calculations)       │
│                            │      │                                    │
│  - ConversationalRAG       │      │  - Applicable Programs             │
│  - AgenticRAG              │      │  - Material Composition            │
│  - StackingRAG             │      │  - Duty Calculation                │
│                            │      │  - ACE Entry Slicing               │
└────────────┬───────────────┘      └───────────────┬────────────────────┘
             │                                      │
             ▼                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATABASE LAYER (SQLAlchemy)                     │
│                                                                         │
│  Core Tables:              Tariff Tables:           Search Cache:       │
│  - User                    - TariffProgram          - GeminiSearchResult│
│  - Conversation            - Section301Inclusion    - GroundingSource   │
│  - Message                 - Section232Material     - EvidenceQuote     │
│  - Pdf/Corpus              - ProgramCode/Rate       - SearchAuditLog    │
└─────────────────────────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL SERVICES                                  │
│                                                                         │
│  OpenAI (GPT-4)     Pinecone (Vectors)     Gemini (Search)             │
│  - Chat completion   - Document search      - HTS verification         │
│  - Embeddings        - Tariff cache         - Google grounding         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Directory Structure

```
lanes/
├── app/                          # Main Flask application
│   ├── web/                      # Flask web server & API
│   │   ├── views/                # API endpoints (blueprints)
│   │   ├── db/models/            # SQLAlchemy models
│   │   └── config/               # Configuration
│   ├── chat/                     # Chat/RAG logic (LangGraph)
│   │   ├── graphs/               # LangGraph workflows
│   │   ├── tools/                # Stacking & trade tools
│   │   ├── vector_stores/        # Pinecone integration
│   │   └── prompts/              # LLM prompts
│   └── celery/                   # Background task queue
├── client/                       # SvelteKit frontend (TypeScript)
├── mcp_servers/                  # MCP servers for Claude integration
├── scripts/                      # Database population & testing
├── tests/                        # Test suite
└── docs/                         # Documentation
```

### 13.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | SvelteKit + Vite + Tailwind | UI, routing, API calls |
| API | Flask + SQLAlchemy 2.0 | REST endpoints, ORM |
| RAG Engine | LangGraph + LangChain | Conversation workflows |
| Vector DB | Pinecone | Semantic document search |
| LLM | OpenAI GPT-4 | Answer generation |
| Search | Google Gemini | HTS verification with grounding |
| Database | PostgreSQL/SQLite | Persistent storage |
| Cache | Redis (optional) | Celery broker |

---

## 14. 3-Tier Search Cache Design

### 14.1 Architecture Overview

The system uses a 3-tier caching architecture to minimize expensive Gemini API calls:

```
┌─────────────────────────────────────────────────────────────────┐
│                    SEARCH QUERY                                  │
│            verify_hts_scope("8544.42.9090", "copper")           │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: PostgreSQL (Exact Match)                              │
│  Table: gemini_search_results                                   │
│  Key: (hts_code, query_type, material)                         │
│  TTL: 30 days                                                   │
│                                                                 │
│  ✓ HIT → Return cached result                                  │
│  ✗ MISS → Continue to Layer 2                                  │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: Pinecone (Semantic Match)                             │
│  Index: lanes-tariff-search                                     │
│  Model: text-embedding-3-small (1536 dims)                     │
│  Threshold: 0.85 similarity                                     │
│                                                                 │
│  ✓ HIT (score > 0.85) → Return similar result                  │
│  ✗ MISS → Continue to Layer 3                                  │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3: Gemini API (Live Search)                              │
│  Model: gemini-2.5-flash (test) / gemini-3-pro (production)    │
│  Grounding: Google Search (cbp.gov, federalregister.gov)       │
│                                                                 │
│  → Call Gemini with structured prompt                          │
│  → Extract grounding URLs                                       │
│  → Parse JSON response                                          │
│  → Validate schema + business rules                            │
│  → Persist to Layer 1 + Index in Layer 2                       │
└─────────────────────────────────────────────────────────────────┘
```

### 14.2 Cache Tables

| Table | Purpose | TTL |
|-------|---------|-----|
| `gemini_search_results` | Full Gemini responses | 30 days |
| `grounding_sources` | URLs Gemini cited | Linked to search |
| `evidence_quotes` | Verbatim citations | Linked to search |
| `search_audit_log` | Cost tracking, hit/miss | Permanent |

### 14.3 Key Files

| File | Purpose |
|------|---------|
| `mcp_servers/search_cache.py` | 3-tier cache orchestration |
| `app/chat/vector_stores/tariff_search.py` | Pinecone indexing |
| `app/web/db/models/tariff_tables.py` | Cache table models |

---

## 15. MCP Server Layer

### 15.1 MCP Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE / MCP CLIENT                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │ stdio transport
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  MCP SERVERS (mcp_servers/)                      │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ hts_verifier.py                                          │   │
│  │ Tool: verify_hts_scope(hts_code, material, ...)         │   │
│  │ Tool: verify_section_301(hts_code, ...)                 │   │
│  │ Tool: test_gemini_connection()                          │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             │                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ search_cache.py                                          │   │
│  │ - check_postgres_cache()                                │   │
│  │ - check_pinecone_cache()                                │   │
│  │ - persist_search_result()                               │   │
│  │ - persist_evidence_quotes()                             │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             │                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ schemas.py                                               │   │
│  │ - Section232ResultV2 (Pydantic strict mode)             │   │
│  │ - Citation model (verbatim quotes)                      │   │
│  │ - validate_citations_have_proof()                       │   │
│  │ - validate_citations_contain_hts()                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 15.2 MCP Tools

| Tool | Purpose | Parameters |
|------|---------|------------|
| `verify_hts_scope` | Check Section 232 scope | hts_code, material, use_production_model |
| `verify_section_301` | Check Section 301 list | hts_code, use_production_model |
| `test_gemini_connection` | API health check | None |

### 15.3 v9.2 Evidence-First Schema

```json
{
  "hts_code": "8544.42.9090",
  "query_type": "section_232",
  "results": {
    "copper": {
      "in_scope": true,
      "claim_code": "9903.78.01",
      "citations": [
        {
          "source_url": "https://content.govdelivery.com/...",
          "source_document": "CSMS #65794272",
          "quoted_text": "8544.42.90 - Insulated copper wire..."
        }
      ]
    },
    "steel": {"in_scope": false, "citations": []},
    "aluminum": {"in_scope": true, "claim_code": "9903.85.08", "citations": [...]}
  }
}
```

---

## 16. Stacking Engine Design

### 16.1 Complete Flow

```
INPUT: {hts_code, country, product_value, materials}
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. NORMALIZE COUNTRY                                           │
│     CountryAlias lookup → ISO Alpha-2 code                     │
│     "China" → "CN", "PRC" → "CN", "Macau" → "MO"              │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. GET APPLICABLE PROGRAMS                                     │
│     Query TariffProgram WHERE country matches                  │
│     Check ProgramCountryScope for data-driven rules            │
│     Order by filing_sequence                                    │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. FOR EACH PROGRAM (in filing_sequence order):               │
│                                                                 │
│     ├─ check_program_inclusion(program_id, hts)                │
│     │   → Query Section301Inclusion, Section232Material        │
│     │                                                           │
│     ├─ check_program_exclusion(program_id, hts, desc)          │
│     │   → Query Section301Exclusion, IeepaAnnexIIExclusion     │
│     │                                                           │
│     ├─ check_material_composition(hts, material)               │
│     │   → Query Section232Material for Cu/St/Al                │
│     │                                                           │
│     ├─ resolve_program_dependencies()                          │
│     │   → Check ProgramSuppression rules                       │
│     │                                                           │
│     └─ get_program_output(program_id, action, variant, slice)  │
│         → Query ProgramCode for Chapter 99 code                │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. PLAN ENTRY SLICES (v4.0)                                   │
│                                                                 │
│     Product ($10,000)                                          │
│     ├── non_metal slice ($6,000) - residual                   │
│     ├── copper_slice ($3,000) - copper content                │
│     └── aluminum_slice ($1,000) - aluminum content            │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. CALCULATE DUTIES                                            │
│                                                                 │
│     For each slice:                                            │
│     - Apply program rates (from ProgramRate or ProgramCode)    │
│     - Handle compound vs additive                              │
│     - Apply IEEPA unstacking (v6.5)                           │
│       remaining_value = product - copper - steel - aluminum    │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. GENERATE FILING LINES                                       │
│                                                                 │
│     For each slice × applicable programs:                      │
│     - Chapter 99 code (claim or disclaim)                      │
│     - Value basis                                              │
│     - Duty amount                                              │
│                                                                 │
│     disclaim_behavior:                                         │
│     - copper: 'required' → always file 9903.78.02             │
│     - steel:  'omit' → never file disclaim code               │
│     - aluminum: 'omit' → never file disclaim code             │
└─────────────────────────────────────────────────────────────────┘

OUTPUT: {programs, entries, filing_lines, duties, audit_trail}
```

### 16.2 Key Stacking Files

| File | Purpose |
|------|---------|
| `app/chat/graphs/stacking_rag.py` | LangGraph stacking workflow |
| `app/chat/tools/stacking_tools.py` | Calculation functions |
| `app/web/db/models/tariff_tables.py` | All tariff table models |

---

## 17. Complete Database Schema

### 17.1 Core Tariff Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| **TariffProgram** | Defines programs | program_id, country, disclaim_behavior, filing_sequence |
| **Section301Inclusion** | 301 HTS scope | hts_8digit, list_name, chapter_99_code, duty_rate |
| **Section301Exclusion** | 301 exclusions | description, exclusion_doc, expiry_date |
| **Section232Material** | 232 material scope | hts_8digit, material, claim_code, duty_rate |
| **ProgramCode** | Output codes | program_id, action, variant, slice_type, chapter_99_code |
| **DutyRule** | Calculation rules | program_id, calculation_type, base_on, content_key |
| **ProgramRate** | Country-specific rates | program_id, group_id, rate, rate_formula |
| **CountryAlias** | Country normalization | alias_raw, iso_alpha2, canonical_name |
| **CountryGroup** | Country groupings | group_id, description, effective_date |
| **ProgramCountryScope** | Data-driven scope | program_id, country_group_id, scope_type |
| **ProgramSuppression** | Program conflicts | suppressor_id, suppressed_id, suppression_type |
| **IeepaAnnexIIExclusion** | Annex II exemptions | hts_prefix, description |
| **HtsBaseRate** | MFN Column 1 rates | hts_code, column1_rate |
| **SourceDocument** | Audit trail | doc_type, doc_identifier, url, effective_date |

### 17.2 Search Cache Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| **GeminiSearchResult** | Cached responses | hts_code, query_type, material, result_json, expires_at |
| **GroundingSource** | Source URLs | search_result_id, url, domain, reliability_score |
| **EvidenceQuote** | Verbatim citations | search_result_id, quoted_text, in_scope, claim_code |
| **SearchAuditLog** | Cost tracking | hts_code, cache_hit, response_time_ms, estimated_cost |

### 17.3 Entity Relationships

```
TariffProgram (1) ──── (N) Section301Inclusion
             │
             ├──── (N) Section232Material
             │
             ├──── (N) ProgramCode
             │
             ├──── (N) DutyRule
             │
             └──── (N) ProgramRate ──── (1) CountryGroup ──── (N) CountryGroupMember

GeminiSearchResult (1) ──── (N) GroundingSource
                   │
                   ├──── (N) EvidenceQuote
                   │
                   └──── (N) SearchAuditLog
```

---

## 18. Known Limitations & Why Search Can Fail

### 18.1 The Problem

The current search architecture has a fundamental gap:

```
Gemini says "in scope" → Store in cache → Use for 30 days
                        ↑
                        NO VERIFICATION STEP
```

### 18.2 Root Causes of Search Errors

| Cause | Description | Example |
|-------|-------------|---------|
| **No Source Verification** | URLs cited but never fetched | Gemini claims HTS is on list, but nobody checks |
| **LLM Conflation** | Chapter 85 ≠ 8544.42.9090 | Sees "Chapter 85 in steel scope", wrongly includes specific HTS |
| **Hallucinated Citations** | Quotes that don't exist | Gemini invents a quote not in the source |
| **Stale Sources** | 2018 list vs 2025 list | Google returns old list, Gemini cites it |
| **Single Source Trust** | No corroboration | One source is enough to store as truth |

### 18.3 Current Validation Gaps

```python
# schemas.py - This is a WARNING, should be ERROR
def validate_citations_contain_hts(result):
    warnings.append(...)  # ← Should block storage, not just warn
```

### 18.4 Recommended Fixes

| Fix | Priority | Implementation |
|-----|----------|----------------|
| **Fetch source URLs** | HIGH | Actually download and verify HTS appears in content |
| **Make HTS check an error** | HIGH | Block storage if quoted_text doesn't contain HTS |
| **Short TTL for unverified** | MEDIUM | 1 day for unverified, 30 days for verified |
| **Multi-source corroboration** | MEDIUM | Require 2+ independent sources |
| **Conflict detection** | LOW | Alert if Gemini result differs from curated DB |

### 18.5 Current Workaround

The system uses **curated ground truth** (Phoebe's ACE examples + CSMS bulletins) instead of trusting Gemini search for production data. The `section_232_materials` table is manually populated and verified against official sources.

```bash
# Correct approach: Use curated data
pipenv run python scripts/populate_tariff_tables.py

# Not recommended: Trust Gemini search without verification
pipenv run python scripts/seed_gemini_search.py
```

---

*Last Updated: January 2026*

# =============> 
New

Legal-Grade Tariff Data System: Complete Design Specification

 Date: January 2026
 Version: 4.0 (Final - Pure RAG + LLM Validation)
 Status: Ready to Implement

 ---
 0. The Core Principle

 LLMs may interpret, but they must PROVE every claim by pointing to exact text spans inside Tier-A documents we have stored.

 This replaces regex/rules. The "proof" is what makes it legal-grade.

 ---
 0.1 What's Happening Now (Broken)

 User question
       │
       ▼
 Gemini Web Search (open internet)
       │  - finds official + unofficial + outdated + summaries
       │  - reads URLs itself
       │  - returns a conclusion ("in_scope", "claim_code")
       ▼
 You cache Gemini's conclusion in Pinecone/Postgres
       ▼
 System treats it as truth for TTL period

 Failure mode: "source mixing + confident conclusion + caching" → long-lived wrong facts.

 ---
 0.2 What Will Happen (Proposed)

 User question
       │
       ▼
 Layer 1: Verified Assertions (Postgres)
       │  - if we already have a verified fact + proof, return it
       │
       ├─ HIT → return (authoritative)
       │
       └─ MISS
            │
            ▼
 Layer 2: RAG Retrieval over OUR Official Corpus (Pinecone)
       │  - only Tier-A documents we ingested and hashed
       │  - retrieve top chunks relevant to the HTS + program
       ▼
 Reader LLM (answers using only retrieved chunks)
       ▼
 Validator LLM (independently checks the answer against chunks)
       ▼
 Write Gate (mechanical proof checks: quotes exist, doc IDs exist)
       ▼
 Store Verified Assertion (with proof pointers)
       ▼
 Return answer (now authoritative)

 And only if Layer 2 can't find anything:

 Layer 3: Discovery Mode (Gemini Web Search)
       │  - Gemini returns *official URLs/IDs only* (no conclusions trusted)
       ▼
 Your Connector fetches the official doc
       ▼
 Store doc + chunk + index into corpus
       ▼
 Then run Layer 2 (Reader + Validator) again

 Key difference:
 - Current: cache LLM interpretation
 - Proposed: cache official documents + verified assertions with evidence

 ---
 1. Complete Runtime Flow (Detailed)

 User Query: "Is HTS 8544.42.9090 in scope for Section 232 steel?"
   │
   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 0: NORMALIZE HTS                                                 │
 │                                                                         │
 │  - Validate shape (8 or 10 digits)                                     │
 │  - Normalize formatting                                                 │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 1: VERIFIED ASSERTIONS (PostgreSQL)                              │
 │                                                                         │
 │  SELECT * FROM verified_assertion                                       │
 │  WHERE hts_code_norm = '85444290'                                      │
 │    AND program_id = 'section_232'                                       │
 │    AND effective_end IS NULL                                            │
 │                                                                         │
 │  ✓ FOUND → Return with evidence_quote + document link (authoritative)  │
 │  ✗ NOT FOUND → Continue to Layer 2                                     │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 2: RAG OVER OFFICIAL CORPUS                                      │
 │                                                                         │
 │  STEP A: Hybrid Retrieval (Pinecone + optional lexical)                │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  Vector search: filter tier='A'                                  │   │
 │  │  Query: "8544.42.9090 Section 232 steel scope"                  │   │
 │  │  + Optional lexical search for HTS string in chunk_text         │   │
 │  │  → Returns top K chunks with doc_id, chunk_id                   │   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 │                                                                         │
 │  STEP B: READER LLM                                                    │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  Input: User question + retrieved chunks                        │   │
 │  │  Instruction: Answer ONLY from these chunks, cite exact quotes  │   │
 │  │                                                                  │   │
 │  │  Output:                                                         │   │
 │  │  {                                                               │   │
 │  │    "answer": {"in_scope": false, "program": "section_232_steel"}│   │
 │  │    "citations": [                                                │   │
 │  │      {                                                           │   │
 │  │        "document_id": "...",                                    │   │
 │  │        "chunk_id": "...",                                       │   │
 │  │        "quote": "8501.10.20 through 8504.40.95",               │   │
 │  │        "why_this_supports": "Steel list ends at 8504, 8544 is  │   │
 │  │                              after the gap"                     │   │
 │  │      }                                                           │   │
 │  │    ]                                                             │   │
 │  │  }                                                               │   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 │                                                                         │
 │  STEP C: VALIDATOR LLM                                                 │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  Input: Same chunks + Reader's output                           │   │
 │  │  Instruction: Confirm every claim is supported by cited quotes  │   │
 │  │                                                                  │   │
 │  │  Output:                                                         │   │
 │  │  {                                                               │   │
 │  │    "verified": true,                                            │   │
 │  │    "failures": [],                                              │   │
 │  │    "confidence": "high"                                         │   │
 │  │  }                                                               │   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 │                                                                         │
 │  STEP D: WRITE GATE (Mechanical Checks)                                │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  1. cited document_id exists in document table                  │   │
 │  │  2. cited chunk_id exists in document_chunk table               │   │
 │  │  3. document.tier == 'A'                                        │   │
 │  │  4. quote is exact substring of document_chunk.text             │   │
 │  │  5. Validator returned verified=true                            │   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 │                                                                         │
 │  ✓ ALL PASS → Store verified_assertion + Return authoritative         │
 │  ✗ ANY FAIL → needs_review_queue + Return "unverified"                │
 │  ✗ NO CHUNKS FOUND → Continue to Layer 3                              │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 3: DISCOVERY MODE (Gemini Web Search)                           │
 │                                                                         │
 │  ⚠️ GEMINI RETURNS URLs ONLY - NO CONCLUSIONS TRUSTED                 │
 │                                                                         │
 │  Gemini output:                                                         │
 │  {                                                                      │
 │    "official_sources": [                                                │
 │      {                                                                  │
 │        "source_type": "CSMS",                                          │
 │        "official_url": "https://content.govdelivery.com/...",          │
 │        "why_relevant": "Contains steel derivative list"               │
 │      }                                                                  │
 │    ]                                                                    │
 │  }                                                                      │
 │                                                                         │
 │  Pipeline:                                                              │
 │  1. Connector fetches URL (validates domain)                          │
 │  2. Store Document with SHA-256 hash                                   │
 │  3. Chunk document + embed + index in Pinecone                        │
 │  4. Re-run Layer 2 (Reader → Validator → Write Gate)                  │
 │                                                                         │
 │  ✓ VALIDATED → Return authoritative                                    │
 │  ✗ NO TIER-A PROOF FOUND → Return "unknown" + log needs_review        │
 └─────────────────────────────────────────────────────────────────────────┘

 ---
 2. The Three LLM Roles

 2.1 Reader LLM

 Purpose: Answer user questions using ONLY retrieved chunks from our corpus.

 Input:
 - User question
 - Retrieved chunks (with doc_id, chunk_id)
 - Strict instruction: answer only from these chunks, cite exact quotes

 Output Schema:
 {
   "answer": {
     "in_scope": true | false | null,
     "program": "section_232_copper",
     "hts": "8544.42.9090",
     "claim_codes": ["9903.78.01"],
     "confidence": "high" | "medium" | "low"
   },
   "citations": [
     {
       "document_id": "uuid",
       "chunk_id": "uuid",
       "quote": "verbatim text from chunk",
       "why_this_supports": "explanation"
     }
   ],
   "missing_info": [],
   "contradictions": []
 }

 2.2 Validator LLM

 Purpose: Independently verify that the Reader's claims are supported by the cited quotes.

 Input:
 - Same chunks as Reader
 - Reader's JSON output

 Output Schema:
 {
   "verified": true | false,
   "failures": [
     {"citation_index": 0, "reason": "quote does not support claim"}
   ],
   "required_fixes": [],
   "confidence": "high" | "medium" | "low"
 }

 Best practice: Use a different model (or at least different prompt/temperature) than Reader to reduce correlated mistakes.

 2.3 Discovery LLM (Gemini with Web Search)

 Purpose: Find official URLs when our corpus lacks relevant documents.

 Constraint: Returns URLs/identifiers ONLY, no conclusions.

 Output Schema:
 {
   "official_sources": [
     {
       "source_type": "CSMS" | "FR" | "USITC",
       "official_url": "https://...",
       "why_relevant": "description",
       "expected_to_contain": ["8544.42.90", "9903.78.01"]
     }
   ]
 }

 ---
 3. Write Gate (Mechanical Proof Checks)

 Even without regex/rules, we need a small deterministic gate:

 | Check                          | What It Validates                               |
 |--------------------------------|-------------------------------------------------|
 | 1. Document exists             | document_id exists in document table            |
 | 2. Chunk exists                | chunk_id exists in document_chunk table         |
 | 3. Tier A only                 | document.tier == 'A'                            |
 | 4. Quote exists                | quote is exact substring of document_chunk.text |
 | 5. Validator passed            | verified == true from Validator LLM             |
 | 6. (Optional) Multiple sources | At least 2 citations for high-confidence claims |

 If ALL pass: Write verified_assertion + evidence_quote pointers

 If ANY fail: Write to needs_review_queue, return "unknown / needs review"

 ---
 4. Data Model

 4.1 Document Store (Postgres)

 -- Official documents we fetched
 CREATE TABLE document (
     id UUID PRIMARY KEY,
     source VARCHAR(20) NOT NULL,        -- 'CSMS', 'FEDERAL_REGISTER', 'USITC'
     tier CHAR(1) NOT NULL DEFAULT 'A',
     connector_name VARCHAR(50) NOT NULL,
     canonical_id VARCHAR(100),           -- CSMS#65794272, FR citation
     url_canonical TEXT NOT NULL,
     title TEXT,
     published_at TIMESTAMP,
     effective_start DATE,
     sha256_raw VARCHAR(64) NOT NULL,
     raw_content TEXT,
     extracted_text TEXT,
     fetch_log JSONB,
     created_at TIMESTAMP DEFAULT NOW()
 );

 -- Chunked text for RAG
 CREATE TABLE document_chunk (
     id UUID PRIMARY KEY,
     document_id UUID REFERENCES document(id),
     chunk_index INT NOT NULL,
     text TEXT NOT NULL,
     embedding_id VARCHAR(64),            -- Pinecone vector ID
     metadata JSONB,                      -- page, section, etc.
     UNIQUE (document_id, chunk_index)
 );

 -- Verbatim evidence quotes
 CREATE TABLE evidence_quote (
     id UUID PRIMARY KEY,
     document_id UUID REFERENCES document(id),
     chunk_id UUID REFERENCES document_chunk(id),
     quote_text TEXT NOT NULL,
     quote_sha256 VARCHAR(64) NOT NULL,
     created_at TIMESTAMP DEFAULT NOW()
 );

 4.2 Truth Store (Postgres)

 -- Verified facts with proof
 CREATE TABLE verified_assertion (
     id UUID PRIMARY KEY,
     program_id VARCHAR(30) NOT NULL,
     hts_code_norm VARCHAR(10) NOT NULL,
     material VARCHAR(20),
     assertion_type VARCHAR(30) NOT NULL,  -- IN_SCOPE, OUT_OF_SCOPE
     claim_code VARCHAR(12),
     disclaim_code VARCHAR(12),
     effective_start DATE NOT NULL,
     effective_end DATE,                   -- NULL = current
     document_id UUID REFERENCES document(id),
     evidence_quote_id UUID REFERENCES evidence_quote(id),
     reader_output JSONB,                  -- Full Reader LLM response
     validator_output JSONB,               -- Full Validator LLM response
     created_at TIMESTAMP DEFAULT NOW(),
     UNIQUE (program_id, hts_code_norm, material, assertion_type, effective_start)
 );

 -- Blocked writes awaiting human review
 CREATE TABLE needs_review_queue (
     id UUID PRIMARY KEY,
     hts_code VARCHAR(12) NOT NULL,
     query_type VARCHAR(30) NOT NULL,
     reader_output JSONB,
     validator_output JSONB,
     block_reason TEXT NOT NULL,
     status VARCHAR(20) DEFAULT 'pending',
     created_at TIMESTAMP DEFAULT NOW(),
     reviewed_at TIMESTAMP,
     resolution_notes TEXT
 );

 4.3 Pinecone Index

 Only Tier-A document chunks. Metadata:
 - tier: 'A'
 - source: 'CSMS' | 'FEDERAL_REGISTER' | 'USITC'
 - document_id: UUID
 - chunk_id: UUID
 - published_at: timestamp
 - effective_start: date
 - program_hint: 'section_232' | 'section_301' | 'ieepa' (optional)

 ---
 5. Source Tiers

 | Tier | Sources                           | Write Permission                    |
 |------|-----------------------------------|-------------------------------------|
 | A    | Federal Register, CBP CSMS, USITC | ✅ Can populate verified_assertion   |
 | B    | USTR press, White House           | ⚠️ Signals only (trigger discovery) |
 | C    | Law firms, blogs                  | ❌ Discovery hints only              |

 ---
 3. Trusted Connectors (Not "Allowed Domains")

 3.1 What Is a Trusted Connector?

 A connector is a specific code path that:
 1. Fetches from a known official endpoint
 2. Stores raw content + hash
 3. Records fetch metadata (timestamp, headers, status)
 4. Tags document with connector_name for provenance

 # Example: CSMS Connector
 class CSMSConnector:
     TRUSTED_DOMAINS = ["content.govdelivery.com", "www.cbp.gov"]
     SOURCE_TYPE = "CSMS"
     TIER = "A"

     def fetch(self, bulletin_url: str) -> Document:
         # Validate domain
         if not self._is_trusted_domain(bulletin_url):
             raise UntrustedSourceError(f"Domain not in CSMS allowlist")

         # Fetch with full logging
         response = self._fetch_with_audit(bulletin_url)

         # Create document with provenance
         return Document(
             source=self.SOURCE_TYPE,
             tier=self.TIER,
             connector_name="csms_connector",
             url_canonical=bulletin_url,
             sha256_raw=hash_content(response.content),
             raw_content=response.content,
             fetch_log={
                 "retrieved_at": datetime.utcnow(),
                 "status_code": response.status_code,
                 "headers": dict(response.headers)
             }
         )

 3.2 The Four Trusted Connectors

 | Connector         | Source           | Tier | Endpoint                                  |
 |-------------------|------------------|------|-------------------------------------------|
 | govinfo_connector | Federal Register | A    | api.govinfo.gov                           |
 | csms_connector    | CBP CSMS         | A    | content.govdelivery.com/accounts/USDHSCBP |
 | usitc_connector   | HTS Schedule     | A    | hts.usitc.gov/reststop                    |
 | ustr_connector    | USTR Press       | B    | ustr.gov/about-us/policy-offices          |

 Under the hood: Each connector has domain allowlists, but architecturally you talk about connectors, not domains.

 ---
 4. The Search System Design

 4.1 Philosophy: Build a Better Corpus, Not Better Internet Search

 DON'T: "Search the internet better"
 DO:    "Build an official corpus + retrieval workflow"

 4.2 Complete Search Architecture

 ┌─────────────────────────────────────────────────────────────────────────┐
 │                         QUERY: "Is HTS X in scope for Program Y?"       │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 1: VERIFIED ASSERTION LOOKUP (fastest, most authoritative)       │
 │                                                                         │
 │  SELECT * FROM verified_assertion                                       │
 │  WHERE hts_code_norm = normalize(X)                                     │
 │    AND program_id = Y                                                   │
 │    AND effective_end IS NULL  -- current                                │
 │                                                                         │
 │  ✓ FOUND → Return with evidence quote                                  │
 │  ✗ NOT FOUND → Continue to Layer 2                                     │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 2: PREFIX MATCH (for 10-digit queries against 8-digit lists)    │
 │                                                                         │
 │  SELECT * FROM verified_assertion                                       │
 │  WHERE X LIKE hts_code_norm || '%'                                     │
 │    AND program_id = Y                                                   │
 │    AND effective_end IS NULL                                            │
 │                                                                         │
 │  ✓ FOUND → Return with evidence quote                                  │
 │  ✗ NOT FOUND → Continue to Layer 3                                     │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 3: OFFICIAL DOCUMENT CORPUS SEARCH                               │
 │                                                                         │
 │  Search stored Tier A documents only:                                   │
 │  - Hybrid: BM25 (keyword) + Pinecone (semantic)                        │
 │  - Filters: tier='A', doc_type IN (program-relevant types)             │
 │                                                                         │
 │  Returns: document chunks with location metadata                        │
 │                                                                         │
 │  ✓ FOUND relevant chunks → Send to Extractor + Validator               │
 │  ✗ NOT FOUND → Continue to Layer 4                                     │
 └─────────────────────────────────┬───────────────────────────────────────┘
                                   ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  LAYER 4: DISCOVERY MODE (LLM-assisted, but NOT write-allowed)         │
 │                                                                         │
 │  LLM can:                                                               │
 │  - Search for Tier B signals that point to Tier A docs                 │
 │  - Propose candidate official sources                                   │
 │  - Return URLs/identifiers, NOT conclusions                            │
 │                                                                         │
 │  System then:                                                           │
 │  - Pulls via trusted connector                                          │
 │  - Runs through Extractor + Validator                                   │
 │  - If validated → commits to VerifiedAssertion                         │
 │                                                                         │
 │  ⚠️ LLM CANNOT directly answer scope questions in write path           │
 └─────────────────────────────────────────────────────────────────────────┘

 4.3 Numerical Gap Validation (The "8504 → 8601 Jump")

 For lists where absence matters (your exact pain point):

 def validate_numerical_gap(hts_code: str, annex_section: str, document: Document) -> GapProof:
     """
     Verify HTS is NOT in a list by proving the gap exists.

     Example: Steel list in Note 16(n) covers 8501-8504, then jumps to 8601.
     HTS 8544 is NOT in scope because it falls in the gap.
     """
     # 1. Extract all HTS tokens and ranges from the annex section
     hts_tokens = extract_hts_from_text(annex_section)

     # 2. Normalize to numeric intervals
     intervals = normalize_to_intervals(hts_tokens)
     # e.g., [(85011020, 85049642), (86010000, 86091900)]

     # 3. Check if HTS falls in any interval
     hts_numeric = int(hts_code.replace(".", ""))

     for start, end in intervals:
         if start <= hts_numeric <= end:
             return GapProof(
                 in_scope=True,
                 reason=f"HTS {hts_code} covered by interval {start}-{end}"
             )

     # 4. Find the gap it falls into
     for i in range(len(intervals) - 1):
         gap_start = intervals[i][1] + 1
         gap_end = intervals[i + 1][0] - 1

         if gap_start <= hts_numeric <= gap_end:
             return GapProof(
                 in_scope=False,
                 reason=f"HTS {hts_code} falls in gap between {intervals[i][1]} and {intervals[i+1][0]}",
                 gap_proof={
                     "list_ends_at": intervals[i][1],
                     "list_resumes_at": intervals[i + 1][0],
                     "hts_in_gap": hts_numeric
                 }
             )

     return GapProof(
         in_scope=False,
         reason=f"HTS {hts_code} not found in any interval"
     )

 ---
 5. The Ingestion Pipeline

 5.1 Service Architecture

 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    SOURCE TRIGGERS                                       │
 │  - Email (GovDelivery → CSMS bulletins)                                 │
 │  - RSS (USTR press releases)                                            │
 │  - Scheduled (GovInfo daily pull, USITC weekly sync)                    │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    TRUSTED CONNECTORS                                    │
 │  govinfo_connector | csms_connector | usitc_connector | ustr_connector  │
 │                                                                         │
 │  Each connector:                                                        │
 │  - Validates source domain                                              │
 │  - Fetches with full audit logging                                      │
 │  - Computes content hash                                                │
 │  - Tags with connector_name + tier                                      │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    DOCUMENT STORE                                        │
 │                                                                         │
 │  document:                                                              │
 │  - id, source, tier, connector_name                                     │
 │  - canonical_id (CSMS#65794272, GovInfo package ID)                    │
 │  - url_canonical, sha256_raw                                            │
 │  - raw_content, extracted_text                                          │
 │  - published_at, effective_start                                        │
 │  - fetch_log (headers, retrieved_at, status)                           │
 │                                                                         │
 │  document_chunk:                                                        │
 │  - document_id, chunk_index, text                                       │
 │  - embedding_id (Pinecone), location_meta (page, section, offsets)     │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    EXTRACTOR (Rules + LLM Assist)                       │
 │                                                                         │
 │  Rule-based extraction:                                                 │
 │  - HTS code patterns (regex)                                            │
 │  - Chapter 99 code patterns                                             │
 │  - Effective date patterns                                              │
 │                                                                         │
 │  LLM-assisted extraction:                                               │
 │  - Table parsing from PDFs                                              │
 │  - Range interpretation ("through", "including")                        │
 │  - Context disambiguation                                               │
 │                                                                         │
 │  Output: CandidateAssertion[] with evidence_candidates[]                │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    WRITE GATE / VALIDATOR                               │
 │                                                                         │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  DETERMINISTIC CHECKS (must-pass)                                │   │
 │  │                                                                  │   │
 │  │  1. Source provenance                                            │   │
 │  │     document.tier == 'A'                                         │   │
 │  │     document.connector_name IN TRUSTED_CONNECTORS                │   │
 │  │                                                                  │   │
 │  │  2. Document integrity                                           │   │
 │  │     sha256_raw EXISTS                                            │   │
 │  │     extracted_text EXISTS                                        │   │
 │  │                                                                  │   │
 │  │  3. Evidence integrity                                           │   │
 │  │     evidence_quote EXISTS VERBATIM in extracted_text             │   │
 │  │     quote_sha256 MATCHES stored                                  │   │
 │  │                                                                  │   │
 │  │  4. HTS proof                                                    │   │
 │  │     normalized HTS APPEARS in quote                              │   │
 │  │     (accept: dotted, undotted, 8-digit, 10-digit variants)      │   │
 │  │                                                                  │   │
 │  │  5. Claim/disclaim proof                                         │   │
 │  │     if claim_code required → MUST appear in same doc or annex   │   │
 │  │                                                                  │   │
 │  │  6. Effective date resolved                                      │   │
 │  │     explicit in doc, OR derived from "effective upon publication"│   │
 │  │                                                                  │   │
 │  │  7. Conflict resolution                                          │   │
 │  │     if newer effective_start exists → close old assertion        │   │
 │  │     do NOT overwrite history                                     │   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 │                              │                                          │
 │                              ▼                                          │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  LLM SEMANTIC VERIFICATION (recommended, not required)           │   │
 │  │                                                                  │   │
 │  │  LLM receives:                                                   │   │
 │  │  - candidate assertion                                           │   │
 │  │  - evidence quote                                                │   │
 │  │  - minimal surrounding context                                   │   │
 │  │                                                                  │   │
 │  │  LLM returns:                                                    │   │
 │  │  - supported: true/false                                         │   │
 │  │  - support_reason: string                                        │   │
 │  │  - missing_requirements: []                                      │   │
 │  │  - ambiguity_flags: []                                           │   │
 │  │                                                                  │   │
 │  │  Rules:                                                          │   │
 │  │  - If LLM says "supported" but deterministic fails → BLOCKED    │   │
 │  │  - If deterministic passes but LLM flags ambiguity → needs_review│   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 │                              │                                          │
 │                              ▼                                          │
 │  ┌─────────────────────────────────────────────────────────────────┐   │
 │  │  OUTPUT                                                          │   │
 │  │                                                                  │   │
 │  │  ALL CHECKS PASS → Write to verified_assertion                  │   │
 │  │  ANY CHECK FAILS → Write to needs_review queue                  │   │
 │  └─────────────────────────────────────────────────────────────────┘   │
 └─────────────────────────────────────────────────────────────────────────┘

 ---
 6. Data Model

 6.1 Document Tables

 -- Official document store (Tier A only for write path)
 CREATE TABLE document (
     id UUID PRIMARY KEY,
     source VARCHAR(20) NOT NULL,      -- 'CSMS', 'GOVINFO_FR', 'USITC', 'USTR_SIGNAL'
     tier CHAR(1) NOT NULL,            -- 'A', 'B', 'C'
     connector_name VARCHAR(50) NOT NULL, -- 'csms_connector', 'govinfo_connector'
     canonical_id VARCHAR(100),        -- CSMS#65794272, GovInfo package ID
     url_canonical TEXT NOT NULL,
     title TEXT,
     published_at TIMESTAMP,
     effective_start DATE,             -- When regulation takes effect
     sha256_raw VARCHAR(64) NOT NULL,
     raw_content TEXT,                 -- Or pointer to blob storage
     extracted_text TEXT,
     fetch_log JSONB,                  -- {retrieved_at, status_code, headers}
     created_at TIMESTAMP DEFAULT NOW()
 );

 -- Document chunks for vector search
 CREATE TABLE document_chunk (
     id UUID PRIMARY KEY,
     document_id UUID REFERENCES document(id),
     chunk_index INT NOT NULL,
     text TEXT NOT NULL,
     embedding_id VARCHAR(64),         -- Pinecone vector ID
     location_meta JSONB,              -- {page, section, char_start, char_end}
     UNIQUE (document_id, chunk_index)
 );

 6.2 Assertion Tables

 -- Staging table for extraction output
 CREATE TABLE candidate_assertion (
     id UUID PRIMARY KEY,
     program_id VARCHAR(30) NOT NULL,
     hts_code_norm VARCHAR(10) NOT NULL,  -- Digits only: 85444290
     hts_digits INT NOT NULL,              -- 8 or 10
     material VARCHAR(20),
     assertion_type VARCHAR(30) NOT NULL,  -- IN_SCOPE, OUT_OF_SCOPE, RATE_CHANGE
     claim_code VARCHAR(12),
     disclaim_code VARCHAR(12),
     effective_start DATE,
     evidence_candidates JSONB,            -- [{doc_id, chunk_id, snippet, offsets}]
     status VARCHAR(20) DEFAULT 'pending', -- pending, validated, rejected
     created_at TIMESTAMP DEFAULT NOW()
 );

 -- Truth store (only validated assertions)
 CREATE TABLE verified_assertion (
     id UUID PRIMARY KEY,
     program_id VARCHAR(30) NOT NULL,
     hts_code_norm VARCHAR(10) NOT NULL,
     hts_digits INT NOT NULL,
     material VARCHAR(20),
     assertion_type VARCHAR(30) NOT NULL,
     claim_code VARCHAR(12),
     disclaim_code VARCHAR(12),
     effective_start DATE NOT NULL,
     effective_end DATE,                   -- NULL = current
     document_id UUID REFERENCES document(id),
     evidence_quote_id UUID REFERENCES evidence_quote(id),
     validation_hash VARCHAR(64),          -- Hash of normalized evidence + key fields
     review_status VARCHAR(20) DEFAULT 'verified', -- verified, needs_review
     created_at TIMESTAMP DEFAULT NOW(),
     UNIQUE (program_id, hts_code_norm, material, assertion_type, effective_start)
 );

 -- Evidence is stored, verifiable excerpts (NOT "LLM citations")
 CREATE TABLE evidence_quote (
     id UUID PRIMARY KEY,
     document_id UUID REFERENCES document(id),
     chunk_id UUID REFERENCES document_chunk(id),
     quote_text TEXT NOT NULL,             -- Verbatim excerpt
     char_start INT,
     char_end INT,
     quote_sha256 VARCHAR(64) NOT NULL,
     notes TEXT,                           -- What this proves
     created_at TIMESTAMP DEFAULT NOW()
 );

 6.3 Compiled Tables (Fast Query)

 -- Derived from verified_assertion WHERE effective_end IS NULL
 -- Rebuilt on assertion changes

 CREATE TABLE section_232_material_current (
     hts_8digit VARCHAR(10) PRIMARY KEY,
     material VARCHAR(20) NOT NULL,
     claim_code VARCHAR(12) NOT NULL,
     disclaim_code VARCHAR(12),
     duty_rate DECIMAL(5,4) NOT NULL,
     verified_assertion_id UUID REFERENCES verified_assertion(id)
 );

 CREATE TABLE section_301_inclusion_current (
     hts_8digit VARCHAR(10) PRIMARY KEY,
     list_name VARCHAR(20) NOT NULL,
     chapter_99_code VARCHAR(12) NOT NULL,
     duty_rate DECIMAL(5,4) NOT NULL,
     verified_assertion_id UUID REFERENCES verified_assertion(id)
 );

 ---
 7. Prompt Rules (Policy Hints, Not Enforcement)

 7.1 Extraction Prompts (Write Path)

 SYSTEM: You are extracting structured data from an official government document.

 RULES:
 1. Use ONLY the provided document text. Do not use outside knowledge.
 2. Return JSON only. No commentary.
 3. Every assertion MUST include an evidence_span that contains the HTS string.
 4. If you cannot find explicit proof in the text, return supported=false.
 5. For ranges ("8501 through 8504"), enumerate all covered prefixes.
 6. Flag any ambiguity (truncated lists, unclear ranges) in ambiguity_flags[].

 OUTPUT FORMAT:
 {
   "assertions": [...],
   "evidence_spans": [...],
   "ambiguity_flags": [...]
 }

 7.2 Semantic Verification Prompts

 SYSTEM: You are verifying whether an evidence quote supports a scope assertion.

 INPUT:
 - assertion: {program_id, hts_code, material, in_scope, claim_code}
 - evidence_quote: "..."
 - context: (surrounding text)

 TASK:
 1. Does the evidence quote explicitly support the assertion?
 2. Does the HTS code (or a covering range) appear in the quote?
 3. Does the claim/disclaim code appear?
 4. Are there any ambiguities or missing requirements?

 OUTPUT:
 {
   "supported": true/false,
   "support_reason": "...",
   "missing_requirements": [],
   "ambiguity_flags": []
 }

 7.3 Discovery Prompts (Finding Tier A Sources)

 SYSTEM: You are helping locate official government sources for tariff information.

 RULES:
 1. You may use secondary sources ONLY to locate official Tier A documents.
 2. Return official URLs and document identifiers, NOT scope conclusions.
 3. Tier A sources: Federal Register, CBP CSMS, USITC HTS
 4. Do NOT return conclusions about scope. Only return source pointers.

 OUTPUT:
 {
   "official_sources_found": [
     {"type": "CSMS", "identifier": "#65794272", "url": "..."},
     {"type": "FR", "citation": "90 FR 40326", "url": "..."}
   ],
   "search_notes": "..."
 }

 ---
 8. CBP CSMS Ingestion (Email → Connector → Validation)

 8.1 Pattern: Email Triggers Ingestion, Not Truth

 ┌─────────────────────────────────────────────────────────────────────────┐
 │  1. EMAIL ARRIVES (GovDelivery/CBP sender)                              │
 │     - Poll Gmail/IMAP every 5 minutes                                   │
 │     - Match allowlisted sender patterns                                 │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  2. EXTRACT BULLETIN URL                                                │
 │     - Parse email body for content.govdelivery.com/accounts/USDHSCBP/  │
 │     - Deduplicate by URL hash                                          │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  3. FETCH VIA CSMS CONNECTOR                                            │
 │     - Validate domain in allowlist                                      │
 │     - Fetch HTML with audit logging                                     │
 │     - Compute sha256                                                    │
 │     - Store as Document (tier='A', connector='csms_connector')         │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  4. PARSE CSMS BULLETIN                                                 │
 │     - Extract CSMS number from title                                    │
 │     - Extract effective date statements                                 │
 │     - Extract Chapter 99 headings (9903.xx.xx patterns)                │
 │     - Extract HTS lists (8- or 10-digit patterns)                      │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  5. CREATE CANDIDATE ASSERTIONS                                         │
 │     - For each HTS + claim_code pair found                             │
 │     - Link to evidence spans in document                               │
 └─────────────────────────────┬───────────────────────────────────────────┘
                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │  6. VALIDATE AND COMMIT                                                 │
 │     - Run through Write Gate                                           │
 │     - Deterministic checks + LLM semantic verification                 │
 │     - Commit verified_assertion or queue needs_review                  │
 └─────────────────────────────────────────────────────────────────────────┘

 8.2 Redundancy (Important)

 Email can miss things. Add a daily job:
 - Pull latest CSMS bulletins from official archive (if available)
 - Reconcile against what email triggered
 - Flag any missed bulletins

 ---
 6. Implementation Phases (No Gmail, Pure RAG)

 Phase 1: Stop Caching Gemini Conclusions

 Goal: Immediately stop poisoning the database with LLM guesses.

 Changes:
 1. Remove/disable "cache Gemini response as truth"
 2. Return "unknown (no official proof yet)" instead of caching guesses
 3. Add needs_review_queue table

 Files:
 - mcp_servers/search_cache.py - disable caching LLM conclusions
 - app/web/db/models/tariff.py - add needs_review_queue model

 Result: System can still answer, but won't corrupt truth tables.

 ---
 Phase 2: Document Store + Chunking + Corpus Index

 Goal: Build the official document corpus.

 Deliverables:
 1. document / document_chunk / evidence_quote tables
 2. Chunking pipeline (400-1200 chars per chunk)
 3. Pinecone index with Tier-A chunk embeddings (filter: tier='A')
 4. Hybrid retrieval function (vector + optional lexical)

 New files:
 - app/ingestion/__init__.py
 - app/ingestion/connectors/base.py
 - app/ingestion/connectors/csms_connector.py
 - app/ingestion/connectors/govinfo_connector.py
 - app/ingestion/connectors/usitc_connector.py
 - app/web/db/models/document.py
 - scripts/migrate_document_tables.py

 Result: Can retrieve chunks from official docs, even before verified assertions.

 ---
 Phase 3: Reader LLM + Validator LLM Pipeline

 Goal: Answer from corpus only, with proof.

 Deliverables:
 1. Reader LLM prompt + strict JSON schema
 2. Validator LLM prompt + strict JSON schema
 3. Minimal Write Gate (quote exists in chunk, doc tier A, validator passed)

 New files:
 - app/rag/reader_llm.py
 - app/rag/validator_llm.py
 - app/rag/write_gate.py
 - app/rag/orchestrator.py

 Result: Chat system gives "legal-ish" answers with quotes from official docs.

 ---
 Phase 4: Verified Assertions Store + Versioning

 Goal: Convert repeated Q&A into a durable truth table.

 Deliverables:
 1. verified_assertion table with effective_start/effective_end
 2. "Upsert with versioning" logic
 3. Link to evidence quotes
 4. Layer 1 lookup (fast path for known answers)

 New files:
 - app/web/db/models/verified_assertion.py
 - app/rag/assertion_store.py

 Result: Most queries become fast L1 hits.

 ---
 Phase 5: Discovery Mode Integration

 Goal: When corpus lacks proof, automatically find and ingest official docs.

 Deliverables:
 1. Gemini discovery prompt (returns URLs only, no conclusions)
 2. Connector fetch → store → chunk → index
 3. Re-run RAG (Reader → Validator → Write Gate → Store)

 Modify:
 - mcp_servers/hts_verifier.py - add discovery orchestration

 Result: System can bootstrap itself when it lacks documents.

 ---
 Phase 6: Scheduled Ingestion (Optional)

 Goal: Keep corpus warm so discovery runs less often.

 Deliverables:
 1. Daily job to pull new GovInfo Federal Register packages
 2. Weekly CSMS bulletin sync (poll public archive)
 3. Store → chunk → index → flag for review

 New files:
 - scripts/scheduled_ingestion.py

 Result: Most queries answered at Layer 2 without web discovery.

 ---
 Phase 7: Observability + QA

 Goal: Prevent regressions, measure quality.

 Deliverables:
 1. Metrics: L1 hit rate, L2 hit rate, discovery rate, validator failure rate
 2. Logging: doc fetches, doc hashes, citations used
 3. Test harness for Reader/Validator output schemas

 New files:
 - tests/test_rag_pipeline.py
 - scripts/metrics_dashboard.py

 ---
 7. Summary

 What This Design Achieves

 | Property           | How It's Achieved                                                              |
 |--------------------|--------------------------------------------------------------------------------|
 | Proof-carrying     | Every assertion links to stored evidence quote from stored Tier A doc          |
 | Auditable          | Full provenance: connector → document → chunk → Reader → Validator → assertion |
 | Versioned          | effective_start/effective_end on assertions, history preserved                 |
 | No regex/rules     | LLMs interpret; Write Gate just checks quote exists in stored doc              |
 | Legally defensible | Can answer "show me the legal basis" for any scope fact                        |

 The Three LLM Roles

 | LLM       | Job                                             | Trusted?                                   |
 |-----------|-------------------------------------------------|--------------------------------------------|
 | Reader    | Answer from retrieved chunks, cite exact quotes | Interpretation trusted, citations verified |
 | Validator | Confirm Reader's claims are supported by quotes | Reduces correlated mistakes                |
 | Discovery | Find official URLs when corpus lacks docs       | URLs trusted, conclusions NOT trusted      |

 The One-Line Summary

 RAG retrieves from our official corpus → Reader answers with citations → Validator confirms → Write Gate checks quote exists → Store verified assertion with 
 proof.

 Pros of This Approach

 - No manual parsing logic (pure LLM interpretation)
 - Gemini remains useful (discovery + reading)
 - Clean separation: corpus is official; answers must cite official text
 - Validation redundancy catches "confident but wrong" outputs

 Cons to Expect

 | Issue                                   | Mitigation                                              |
 |-----------------------------------------|---------------------------------------------------------|
 | LLM costs increase (Reader + Validator) | Cache verified assertions; most queries hit L1          |
 | LLMs can hallucinate citations          | Write Gate checks quote exists verbatim in stored chunk |
 | Absence proofs are hard ("not listed")  | Reader must cite list boundaries; Validator confirms    |
 | Embeddings miss HTS codes               | Hybrid retrieval (vector + lexical)                     |

 ---
 8. Ready to Implement

 This design is complete. The pure RAG approach with Reader LLM + Validator LLM + Write Gate.

 Quick Start: Phase 1

 Goal: Stop caching Gemini conclusions immediately.

 Files to modify:
 1. mcp_servers/search_cache.py - Disable caching LLM responses as truth
 2. app/web/db/models/tariff.py - Add needs_review_queue model
 3. Return "unknown (no verified proof)" instead of caching guesses

 Next: Phase 2

 Build the official document corpus:
 - document / document_chunk tables
 - Connectors for CSMS / GovInfo / USITC
 - Chunk and embed in Pinecone with tier='A' filter

 Then: Phase 3

 Build the RAG pipeline:
 - app/rag/reader_llm.py
 - app/rag/validator_llm.py
 - app/rag/write_gate.py
 - app/rag/orchestrator.py

 ---
 Last Updated: January 2026

