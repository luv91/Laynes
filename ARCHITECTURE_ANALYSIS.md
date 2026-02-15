# Lanes Tariff Compliance Chatbot - Comprehensive Architectural Analysis

**Analysis Date:** February 10, 2026
**Codebase Path:** `/sessions/hopeful-ecstatic-darwin/mnt/lanes/`
**Status:** Production system with temporal tariff tracking and multi-program stacking

---

## Executive Summary

The Lanes system is a **data-driven, deterministic tariff stacking engine** that calculates U.S. import duties for products under Section 301, Section 232, and IEEPA tariff programs. The architecture prioritizes **source-of-truth database tables** over hardcoded logic, enabling non-technical users to update tariff rules from official government documents.

**Key Architectural Principles:**
- ✅ **Data-Driven:** All tariff logic lives in database tables, not code
- ✅ **Temporal Tracking:** Multiple rates per HTS code with effective date ranges
- ✅ **Deterministic Core:** No LLM in critical tariff calculation path
- ✅ **Audit Trail:** Full compliance record for every decision
- ✅ **Multi-Program Stacking:** Simultaneous Section 301, 232, IEEPA calculations
- ✅ **Entry Slicing:** Splits products into multiple ACE filing entries by material type

---

## 1. OVERALL ARCHITECTURE

### 1.1 Technology Stack

**Backend:**
- **Framework:** Flask 2.3+ with SQLAlchemy ORM
- **Database:** SQLite (development) / PostgreSQL (production)
- **Job Queue:** Celery + Redis
- **LangChain/LangGraph:** v0.3+ (agentic AI, tool calling)
- **Vector Search:** Pinecone (RAG document retrieval)
- **LLM:** OpenAI GPT-4 (embeddings & reasoning)

**Frontend:**
- **Client:** React.js (SPA in `/client/`)
- **Served:** Gunicorn on Railway platform

**Deployment:**
- **Platform:** Railway.app
- **Entry Point:** `wsgi.py` → `app.web:create_app()`
- **Worker:** Railway job for async processing (via `railway-worker.toml`)

### 1.2 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FRONTEND (React.js in /client/)                  │
│  tariff calculator form → /tariff/calculate POST                    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────┐
│                 FLASK WEB APP (app/web/__init__.py)                │
├─────────────────────────────────────────────────────────────────────┤
│  API Routes (app/web/views/tariff_views.py):                       │
│  • POST /tariff/calculate → StackingRAG.calculate_stacking()       │
│  • GET  /tariff/freshness → data_freshness_service.get_all()       │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────────┐
         │                         │                             │
         ▼                         ▼                             ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────┐
│ STACKING RAG GRAPH  │  │  TARIFF DATABASE    │  │  PINECONE RAG   │
│ (LangGraph)         │  │  (SQLAlchemy ORM)   │  │  (Vector Store) │
│                     │  │                     │  │                 │
│ stacking_rag.py     │  │ tariff_tables.py    │  │ pinecone.py     │
│ + 11 nodes:         │  │ section301.py       │  │                 │
│ 1. initialize       │  │                     │  │ Embedded Docs:  │
│ 2. check_materials  │  │ ~30 Models:         │  │ • FR Notices    │
│ 3. annex_ii_check   │  │ • TariffProgram     │  │ • CBP FAQs      │
│ 4. plan_slices      │  │ • Section301Rate    │  │ • Exclusions    │
│ 5. process_loop     │  │ • Section232Rate    │  │ • CSMs          │
│ 6. tool_edge        │  │ • IeepaRate         │  │                 │
│ 7. build_stacks     │  │ • Section301Excl... │  └─────────────────┘
│ 8. calculate        │  │ • SourceVersion     │
│ 9. generate_output  │  │ • CountryGroup      │
│ 10. final_edge      │  │ • ProgramRate       │
│ 11. end             │  │ • ProductHistory    │
└─────────────────────┘  └─────────────────────┘
         │                         │
         │                         │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │   TOOL LAYER            │
         │   (stacking_tools.py)   │
         │   ~2700 lines, 50 tools │
         │                         │
         │ Key Tools:              │
         │ • get_applicable_prog...│
         │ • check_program_inclus..│
         │ • check_program_exclus..│
         │ • check_material_compo..│
         │ • resolve_program_depe..│
         │ • get_program_output    │
         │ • calculate_duties      │
         │ • is_annex_ii_energy_...│
         │ • build_entry_stack     │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  DATA INGESTION LAYER   │
         │  (scripts/)             │
         │                         │
         │ • populate_tariff_      │
         │   tables.py (main)      │
         │ • parse_fr_301_pdfs.py  │
         │ • parse_cbp_232_lists.py│
         │ • populate_exclusion_   │
         │   claims.py             │
         │ • ingest_ieepa_annex_ii │
         └─────────────────────────┘
```

### 1.3 Key Files Overview

| File | Lines | Purpose |
|------|-------|---------|
| `app/chat/tools/stacking_tools.py` | 2,743 | Core tariff calculation engine (50 tool functions) |
| `app/web/db/models/tariff_tables.py` | 1,811 | SQLAlchemy models (~30 tables) |
| `app/chat/graphs/stacking_rag.py` | 1,300+ | LangGraph state machine for stacking workflow |
| `app/models/section301.py` | 736 | Section 301-specific models (SourceVersion, TariffMeasure, ExclusionClaim) |
| `app/web/views/tariff_views.py` | 1,000+ | Flask API endpoints for tariff calculation |
| `scripts/populate_tariff_tables.py` | 2,000+ | Data ingestion orchestrator |
| `data/current/` | 6 CSVs | Runtime data (rates, inclusions, exclusions) |

---

## 2. DATA FLOW: USER QUERY → TARIFF CALCULATION → RESPONSE

### 2.1 Request Flow

```
STEP 1: USER SUBMITS FORM
┌────────────────────────────────────────┐
│ /tariff/calculate POST                 │
│ {                                      │
│   hts_code: "8544.42.9090",           │
│   country: "China",                    │
│   product_value: 10000,                │
│   materials: {"copper": 500, ...},     │
│   product_description: "USB cables"    │
│ }                                      │
└────────────────────────┬───────────────┘
                         │
STEP 2: INITIALIZE STACKING RAG
┌────────────────────────────────────────┐
│ tariff_views.py:calculate_tariff()     │
│ Creates StackingRAG instance           │
│ session_id = uuid.uuid4()              │
└────────────────────────┬───────────────┘
                         │
STEP 3: INVOKE STACKING GRAPH
┌────────────────────────────────────────┐
│ StackingRAG.calculate_stacking()       │
│ graph.invoke({state}) with config      │
│ Thread: session_id for persistence     │
└────────────────────────┬───────────────┘
                         │
STEP 4: GRAPH NODE EXECUTION (11 nodes in sequence)
├── initialize_node()
│   └─► get_applicable_programs tool
│       (queries tariff_programs table by country/HTS)
│
├── check_materials_node()
│   └─► ensure_materials tool
│       (validates material composition, returns applicable materials)
│
├── check_annex_ii_node()
│   └─► check_annex_ii_exclusion tool
│       (checks IeepaAnnexIIExclusion table)
│
├── plan_slices_node()
│   └─► plan_entry_slices tool
│       (splits product into multiple ACE entries by material)
│
├── process_programs_loop_node()
│   ├─► For each program in filing_sequence order:
│   │
│   ├── process_program_node()
│   │   ├─► check_program_inclusion tool
│   │   │   (queries Section301Inclusion/Section301Rate)
│   │   │
│   │   ├─► check_program_exclusion tool
│   │   │   (matches product against Section301Exclusion table)
│   │   │
│   │   ├─► check_material_composition tool
│   │   │   (for Section 232: evaluates material thresholds)
│   │   │
│   │   ├─► resolve_program_dependencies tool
│   │   │   (e.g., for IEEPA: checks if 232 applies first)
│   │   │
│   │   └─► get_program_output tool
│   │       (returns Chapter 99 code + duty rate for program)
│   │
│   └─► Repeat for next program
│
├── build_entry_stacks_node()
│   ├─► resolve_reciprocal_variant tool
│   │   (determines which IEEPA Reciprocal code applies)
│   │
│   ├─► build_entry_stack tool
│   │   (for each entry slice, builds Chapter 99 stack in filing_sequence)
│   │
│   └─► Generates entries[] with filing_lines per entry
│
├── calculate_duties_node()
│   └─► calculate_duties tool
│       (computes total duty with material splits, unstacking, etc.)
│       Returns: total_duty{}, unstacking{}, breakdown[]
│
└── generate_output_node()
    └─► Formats final response for API

STEP 5: RETURN TO FRONTEND
┌────────────────────────────────────────┐
│ API Response:                          │
│ {                                      │
│   entries: [{                          │
│     entry_number: 1,                   │
│     stack: [{                          │
│       program: "Section 301",          │
│       action: "apply",                 │
│       code: "9903.88.01",              │
│       rate: 0.25,                      │
│       duty: 2500.00                    │
│     }, ...],                           │
│     total_duty: 2500.00                │
│   }, ...],                             │
│   total_duty: {                        │
│     total_amount: 2500.00,             │
│     effective_rate: 0.25,              │
│     breakdown: [...]                   │
│   },                                   │
│   potential_exclusions: [...]          │
│ }                                      │
└────────────────────────────────────────┘
```

### 2.2 Database Query Pattern

**Stacking Engine Query Sequence:**

```python
# 1. ENTRY POINT: What programs could apply?
program = TariffProgram.query.filter_by(
    country=normalize(country),
    effective_date <= import_date,
    expiration_date IS NULL OR expiration_date > import_date
).order_by(filing_sequence)
# Result: [section_301, ieepa_fentanyl, ieepa_reciprocal, section_232]

# 2. FOR EACH PROGRAM: Is HTS in inclusion list?
if program.inclusion_table == "section_301_inclusions":
    rate = Section301Rate.get_rate_as_of(hts_8digit, import_date)
    # Query: hts_8digit=X, effective_start <= date < effective_end
    # Precedence: active_datasets first, exclusions before impose codes

# 3. Is product excluded from this program?
exclusion = Section301Exclusion.query.filter_by(
    hts_8digit=X,
    effective_start <= import_date < effective_end
).first()
# Semantic match on exclusion_description vs product_description

# 4. FOR 232: Material composition check
materials = Section232Material.query.filter_by(hts_8digit=X).all()
# Get claim_code and disclaim_code for each material
# Check if material % meets threshold

# 5. RATE LOOKUP: Get duty rate
if rate_source == "temporal_table":
    rate = Section301Rate.duty_rate
elif rate_source == "country_specific":
    rate = ProgramRate.query.filter_by(
        program_id=P,
        country_group=country_group,
        effective_start <= date < effective_end
    ).first().duty_rate
    # EU special: 15% - MFN_base_rate (formula)
    # UK exception: 25% for 232 steel/aluminum

# 6. DUTY CALCULATION
duty_amount = base_value * duty_rate
# base_value depends on DutyRule.base_on:
# - "product_value": full product $ amount
# - "content_value": material $ amount (232)
# - "remaining_value": product_value - 232_deductions (IEEPA reciprocal)
```

---

## 3. STACKING ENGINE DEEP DIVE

### 3.1 Core Calculation Pipeline (stacking_tools.py)

**File:** `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/chat/tools/stacking_tools.py` (2,743 lines)

**50 Tool Functions:**

#### Section Management Tools
- `get_applicable_programs()` (lines 1076-1146)
  - **Input:** country, hts_code, import_date
  - **Output:** JSON list of applicable programs in filing_sequence order
  - **Logic:** Queries TariffProgram table, normalizes country, filters by effective dates
  - **Key:** Entry point for all stacking operations

- `check_program_inclusion()` (lines 1147-1355)
  - **Input:** program_id, hts_code, technical_attributes (optional)
  - **Output:** JSON {"included": bool, "code": "9903.XX.XX", "rate": float, "source_doc": str}
  - **Logic:**
    - Temporal lookup: Section301Rate.get_rate_as_of() for time-series tracking
    - Datasets: Active (is_archived=False) preferred, fallback to archived
    - Role precedence: 'exclude' > 'impose'
    - Section 232 semiconductors: Evaluate technical attributes via Section232Predicate

- `check_program_exclusion()` (lines 1356-1457)
  - **Input:** program_id, hts_code, product_description, import_date
  - **Output:** JSON {"excluded": bool, "reason": str, "exclusion_id": int}
  - **Logic:** Queries Section301Exclusion table, semantic match on description
  - **Note:** LLM may be used here for semantic similarity (per phase design)

#### Material & Composition Tools
- `check_material_composition()` (lines 1497-1647)
  - **Input:** hts_code, materials (% or $), product_value
  - **Output:** JSON {"material_claims": {...}, "split_lines": [...], "fallback": bool}
  - **Logic:**
    - Queries Section232Material table (copper/steel/aluminum thresholds)
    - Evaluates if material % exceeds minimum for claim
    - Returns claim/disclaim codes from tariff_tables.py line 300+
    - Phase 6: Converts % to $ (content_value = material % × product_value)
    - Phase 6: If content_value unknown, fallback to full product_value

- `ensure_materials()` (lines 963-1075)
  - **Input:** hts_code, product_description, known_materials (optional)
  - **Output:** Normalized materials JSON
  - **Logic:**
    - Validates material input (% or $)
    - Ensures sum doesn't exceed 100% (if percentages)
    - Returns applicable materials list for UI

#### Dependency & Rate Tools
- `resolve_program_dependencies()` (lines 1648-1735)
  - **Input:** program_id, previous_results (JSON string)
  - **Output:** JSON {"skip": bool, "reason": str, "dependencies": [...]}
  - **Logic:** Checks TariffProgram.condition_handler for dependencies
    - E.g., IEEPA Reciprocal depends on Section 232 (checks condition_param)

- `get_program_output()` (lines 1736-1811)
  - **Input:** program_id, action (apply/claim/disclaim), variant, slice_type
  - **Output:** JSON {"code": "9903.XX.XX", "rate": float, "source_doc": str}
  - **Logic:** Queries ProgramCode table with (program_id, action, variant, slice_type)
  - **v7.0:** Supports disclaim_behavior from TariffProgram table

- `get_rate_for_program()` (lines 872-962)
  - **Input:** program_id, country, hts_code, import_date
  - **Output:** (rate: float, source: str)
  - **Logic:**
    - **v5.0 Country-Specific:**
      - Queries CountryGroup + CountryGroupMember for country mapping
      - Queries ProgramRate for country-group + hts_8digit
      - If formula (e.g., "15% - MFN"), calls get_mfn_base_rate()
    - **Section 301:** Uses Section301Rate (temporal lookup)
    - **232:** Uses Section232Rate with country_code filter
    - **IEEPA:** Uses get_ieepa_rate_temporal() with hardcoded fallback

#### Duty Calculation Core
- `calculate_duties()` (lines 1834-2200)
  - **Input:** filing_lines (JSON), product_value, materials (optional), country, hts_code, import_date
  - **Output:** JSON {"total_duty_amount": float, "effective_rate": float, "breakdown": [...], "unstacking": {...}}
  - **Logic:**
    - **Phase 6:** Content-value-based duties
      - For Section 232: duty = content_value × rate (not percentage of product)
      - Fallback: If content_value unknown, use full product_value
    - **Phase 6.5:** IEEPA Unstacking
      - Tracks remaining_value = product_value - sum(232_content_deductions)
      - IEEPA Reciprocal with base_on='remaining_value' uses reduced base
      - CBP rule: Content subject to 232 NOT subject to reciprocal IEEPA
    - **v5.0 Country-Specific Rates:**
      - Calls get_rate_for_program() for dynamic rates
      - EU 15% ceiling formula applied per line
    - **Calculation Types:** additive (compound duties), multiplicative (chain), floor/ceiling
    - **Breakdown:** Detailed audit trail per line

#### IEEPA & Annex II Tools
- `get_ieepa_rate_temporal()` (lines 89-157)
  - **Input:** program_type ('fentanyl'/'reciprocal'), country_code, as_of_date, variant
  - **Output:** JSON {"code": "9903.01.XX", "rate": float, "source": "temporal"|"hardcoded"}
  - **Logic:**
    - Tries IeepaRate table first (temporal lookup)
    - Falls back to IEEPA_CODES hardcoded constants (lines 52-82)
    - **v12.0 Corrections:**
      - Fentanyl: 9903.01.24 (NOT 9903.01.25)
      - Reciprocal: 9903.01.25 (standard), 9903.01.32 (Annex II exempt), 9903.01.33 (232-exempt), 9903.01.34 (US content exempt)

- `is_annex_ii_energy_exempt()` (lines 297-331)
  - **Input:** hts_code, import_date (optional)
  - **Output:** JSON {"exempt": bool, "reason": str, "exemption_code": "9903.01.32", "category": str}
  - **Logic:**
    - **v21.0:** Feature flag USE_DB_ENERGY_CHECK (default false)
    - If true: calls check_annex_ii_exclusion() with category filter
    - If false: uses _legacy_is_annex_ii_energy_exempt() (CSV + hardcoded)
    - **v12.0 Annex II Exemptions:** Energy products (propane, LPG, petroleum)
    - Data file: `data/annex_ii_exemptions.csv` (48 rows)

- `check_annex_ii_exclusion()` (lines 2513-2567)
  - **Input:** hts_code, import_date (optional)
  - **Output:** JSON {"excluded": bool, "reason": str, "category": str, "source_doc": str}
  - **Logic:** Queries IeepaAnnexIIExclusion table with temporal filter
  - **Purpose:** Determines IEEPA Reciprocal variant (standard / annex_ii_exempt / etc.)

#### Entry Slicing & Filing Tools
- `plan_entry_slices()` (lines 2345-2512)
  - **Input:** hts_code, product_value, materials, applicable_materials (from database)
  - **Output:** JSON {"slices": [{slice_type: "material", material: "copper", value: ...}, ...]}
  - **Logic:**
    - **v4.0:** Splits products with 232 metals into multiple ACE entries
    - Slice types: "non_material" (rest), "copper", "steel", "aluminum"
    - Value allocation: material_value (from materials dict) → slice value
    - Non-material slice: product_value - sum(material_values)
    - **Purpose:** Separate claim/disclaim codes per material type

- `build_entry_stack()` (lines 2677-2750)
  - **Input:** hts_code, slice_index, applicable_programs, program_results, ...
  - **Output:** JSON {"entry": {"entry_number": 1, "stack": [{program, action, code, rate, duty}, ...]}}
  - **Logic:**
    - Builds filing_lines in calculation_sequence order (NOT filing_sequence)
    - Applies disclaim_behavior rules (v7.0):
      - Copper (disclaim_behavior='required'): Must file disclaim code
      - Steel/Aluminum ('omit'): Omit entirely when not claimed
    - Supports variant selection (e.g., reciprocal_standard vs reciprocal_annex_ii_exempt)

#### Product History & Auditing
- `lookup_product_history()` (lines 2201-2280)
  - **Input:** hts_code, product_description
  - **Output:** JSON {"history": [{hts_code, classification, confidence, ...}], ...}
  - **Logic:** Queries ProductHistory table for similar products
  - **Purpose:** Learn from past classification decisions

- `save_product_decision()` (lines 2281-2344)
  - **Input:** hts_code, product_description, classification, decision_data (JSON)
  - **Output:** JSON {"saved": bool, "id": int}
  - **Logic:** Inserts into ProductHistory table with audit trail
  - **Purpose:** Build institutional knowledge

#### Support Tools
- `normalize_country()` (lines 449-524)
  - **Input:** country_input (string, country code, or variation)
  - **Output:** JSON {"country": "China", "code": "CN", "group": "CN", "normalized": bool}
  - **Logic:**
    - Queries CountryAlias table for variation mapping (Macau → MO, etc.)
    - Queries CountryGroup for group classification

- `get_country_group()` (lines 765-803)
  - **Input:** country, import_date (optional)
  - **Output:** str ("EU", "UK", "CN", "OTHER")
  - **Logic:** Queries CountryGroup + CountryGroupMember tables
  - **Purpose:** For formula-based rate calculations (EU 15% ceiling)

- `get_mfn_base_rate()` (lines 804-871)
  - **Input:** hts_code, import_date (optional)
  - **Output:** float (0.00 - 1.00)
  - **Logic:**
    - Queries HtsBaseRate table (MFN Column 1 rates)
    - Used in EU 15% formula: duty = max(0, 0.15 - MFN_base_rate)
    - Data file: `data/mfn_base_rates_8digit.csv` (15,263 rows)

- `evaluate_semiconductor_predicates()` (lines 647-764)
  - **Input:** hts_8digit, technical_attributes (dict)
  - **Output:** bool (true if 232 duty applies)
  - **Logic:**
    - Evaluates Section232Predicate rules (HS/MHz/memory/etc.)
    - Per CBP CSMS #67400472: 232 semiconductors need technical thresholds

### 3.2 Tariff Stacking Calculation: The 301/232/IEEPA Interaction

```
PRODUCT: USB-C Cable (HTS 8544.42.9090), China origin, $10,000 value
         Copper content: $500, Steel content: $2,000

┌─────────────────────────────────────────────────────────┐
│ STEP 1: APPLICABLE PROGRAMS (get_applicable_programs)  │
└──────────────────────┬──────────────────────────────────┘
                       │
   Returns in filing_sequence order:
   1. section_301 (filing_seq=1)
   2. ieepa_fentanyl (filing_seq=2)
   3. ieepa_reciprocal (filing_seq=4)
   4. section_232 (filing_seq=3, calc_seq=3)

┌─────────────────────────────────────────────────────────┐
│ STEP 2: PROGRAM INCLUSION CHECKS (check_program_incl...)│
└──────────────────────┬──────────────────────────────────┘
                       │
   section_301:
   ├─ HTS 8544.29.0000 in Section301Inclusion? NO
   └─ Result: NOT APPLICABLE

   ieepa_fentanyl:
   ├─ check_type='always' (applies to all China)
   └─ Result: APPLICABLE @ 10% → $1,000

   section_232:
   ├─ HTS 8544.42.9090 has copper & steel
   ├─ Section232Material records exist
   └─ Result: APPLICABLE if thresholds met

   ieepa_reciprocal:
   ├─ check_type='always' (applies to all China)
   └─ Result: APPLICABLE if not 232-exempt

┌─────────────────────────────────────────────────────────┐
│ STEP 3: MATERIAL COMPOSITION (check_material_composi...) │
└──────────────────────┬──────────────────────────────────┘
                       │
   For section_232:
   ├─ Copper: $500 / $10,000 = 5% (meets threshold) → CLAIM
   │  claim_code: 9903.81.30 (copper primary)
   │
   ├─ Steel: $2,000 / $10,000 = 20% (meets threshold) → CLAIM
   │  claim_code: 9903.81.31 (steel primary)
   │
   └─ Returns material_claims: {copper: claim, steel: claim}

┌─────────────────────────────────────────────────────────┐
│ STEP 4: DEPENDENCY RESOLUTION (resolve_dependencies)  │
└──────────────────────┬──────────────────────────────────┘
                       │
   ieepa_reciprocal:
   ├─ condition_handler='handle_dependency'
   ├─ condition_param='section_232'
   ├─ Check: section_232 applies? YES → SKIP RECIPROCAL (exempt)
   └─ variant: 'section_232_exempt' → code 9903.01.33

┌─────────────────────────────────────────────────────────┐
│ STEP 5: PROGRAM OUTPUT (get_program_output)            │
└──────────────────────┬──────────────────────────────────┘
                       │
   Queries ProgramCode table:
   ├─ (section_301, apply) → no match
   ├─ (ieepa_fentanyl, apply) → 9903.01.24 @ 10%
   ├─ (section_232, copper, claim) → 9903.81.30 @ 50%
   ├─ (section_232, steel, claim) → 9903.81.31 @ 50%
   └─ (ieepa_reciprocal, section_232_exempt) → 9903.01.33 @ 0%

┌─────────────────────────────────────────────────────────┐
│ STEP 6: ENTRY SLICING (plan_entry_slices)             │
└──────────────────────┬──────────────────────────────────┘
                       │
   Splits into 3 slices:
   ├─ Slice 1 (copper):   $500   → 9903.81.30 @ 50%
   ├─ Slice 2 (steel):    $2,000 → 9903.81.31 @ 50%
   └─ Slice 3 (non-metal): $7,500 → no 232 (but 301 if applies)

┌─────────────────────────────────────────────────────────┐
│ STEP 7: BUILD ENTRY STACKS (build_entry_stack)        │
└──────────────────────┬──────────────────────────────────┘
                       │
   For each slice, in calculation_sequence order:

   Entry 1 (copper slice $500):
   ├─ filing_seq order:
   │  1. section_301 → NOT APPLICABLE
   │  2. ieepa_fentanyl → 9903.01.24 @ 10% = $50
   │  3. section_232 → 9903.81.30 @ 50% = $250
   │  4. ieepa_reciprocal → 9903.01.33 @ 0% (232-exempt)
   │
   │  calculation_seq order (for duty math):
   │  1. section_301 → 0
   │  2. ieepa_fentanyl → $50
   │  3. section_232 → $250
   │  4. ieepa_reciprocal → 0 (remaining_value reduced by 232)
   │
   └─ Stack: [{ieepa_fentanyl}, {section_232}, {ieepa_reciprocal}]

   Entry 2 (steel slice $2,000):
   ├─ Stack: [{ieepa_fentanyl}, {section_232}, {ieepa_reciprocal}]
   └─ Duties: $200 (10%) + $1,000 (50%) = $1,200

   Entry 3 (non-metal $7,500):
   ├─ Stack: [{ieepa_fentanyl}, {ieepa_reciprocal}]
   └─ Duties: $750 (10%) + $750 (10% reciprocal) = $1,500

┌─────────────────────────────────────────────────────────┐
│ STEP 8: DUTY CALCULATION (calculate_duties)           │
└──────────────────────┬──────────────────────────────────┘
                       │
   PHASE 6.5: IEEPA UNSTACKING

   1. Copper slice ($500):
      ├─ 232 duty: $500 × 50% = $250 (base_on='content_value')
      ├─ remaining_value = $10,000 - $500 = $9,500
      ├─ Fentanyl: $500 × 10% = $50 (base_on='product_value')
      └─ Reciprocal: $0 (variant='section_232_exempt')

   2. Steel slice ($2,000):
      ├─ 232 duty: $2,000 × 50% = $1,000
      ├─ remaining_value = $10,000 - $2,000 = $8,000
      ├─ Fentanyl: $2,000 × 10% = $200
      └─ Reciprocal: $0

   3. Non-metal slice ($7,500):
      ├─ remaining_value = $10,000 - $2,500 = $7,500
      ├─ Fentanyl: $7,500 × 10% = $750 (base_on='product_value')
      └─ Reciprocal: $7,500 × 10% = $750 (base_on='remaining_value')

   TOTAL DUTY:
   ├─ Section 301: $0
   ├─ Fentanyl: $50 + $200 + $750 = $1,000
   ├─ Section 232: $250 + $1,000 = $1,250
   ├─ Reciprocal: $750
   └─ TOTAL: $3,000 (effective rate: 30%)

   UNSTACKING BREAKDOWN:
   {
     "total_amount": 3000,
     "effective_rate": 0.30,
     "breakdown": [
       {"program": "ieepa_fentanyl", "amount": 1000},
       {"program": "section_232", "amount": 1250, "materials": {"copper": 250, "steel": 1000}},
       {"program": "ieepa_reciprocal", "amount": 750, "notes": "232-exempt for copper/steel"}
     ],
     "unstacking": {
       "232_content_value": 2500,
       "remaining_value": 7500,
       "reciprocal_applies_to": 7500
     }
   }
```

---

## 4. DATA MODELS (tariff_tables.py)

### 4.1 Core Tables

**File:** `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/web/db/models/tariff_tables.py` (1,811 lines)

**~30 SQLAlchemy Models:**

#### Program Definition
1. **TariffProgram** (primary key: program_id, country)
   - Master table: What programs exist?
   - Columns: program_id, program_name, country, check_type, condition_handler, inclusion_table, exclusion_table, filing_sequence, calculation_sequence, effective_date, expiration_date, **disclaim_behavior** (v7.0)
   - **disclaim_behavior:** 'required' (copper), 'omit' (steel/aluminum), 'none' (others)
   - **Unique constraint:** (program_id, country)
   - **Row count:** 19

#### Temporal Rate Tables
2. **Section301Rate**
   - Temporal tariff rates with effective date ranges
   - Columns: hts_8digit, chapter_99_code, duty_rate, effective_start, effective_end, list_name, **role** ('impose'/'exclude'), **dataset_tag**, **is_archived**
   - **Unique constraint:** (hts_8digit, chapter_99_code, effective_start)
   - **Precedence:** Exclusions (role='exclude') > impose codes; Active datasets > archived
   - **Row count:** 10,811
   - **CSV file:** `data/current/section_301_rates.csv`
   - **Feature:** Dataset versioning + archival (v22.0)

3. **Section232Rate**
   - Temporal rates with country-specific exceptions
   - Columns: hts_8digit, material_type ('steel'/'aluminum'/'copper'), country_code, duty_rate, effective_start, effective_end, **article_type** ('primary'/'derivative')
   - **Row count:** 1,638
   - **CSV file:** `data/current/section_232_rates.csv`
   - **Example:** UK exception for steel = 25% (global = 50%)

4. **IeepaRate**
   - IEEPA program rates (fentanyl, reciprocal variants)
   - Columns: program_type, country_code, **variant** (standard, annex_ii_exempt, section_232_exempt, us_content_exempt), chapter_99_code, duty_rate, effective_start, effective_end
   - **Row count:** 46
   - **CSV file:** `data/current/ieepa_rates.csv`

#### Inclusion/Exclusion
5. **Section301Inclusion** (legacy)
   - Static inclusion list (replaced by Section301Rate for temporal tracking)
   - Columns: hts_8digit, list_name, chapter_99_code, duty_rate
   - **Unique constraint:** (hts_8digit, list_name)
   - **Row count:** 11,372
   - **CSV file:** `data/current/section_301_inclusions.csv`

6. **Section301Exclusion**
   - Product exclusions with semantic description
   - Columns: hts_8digit, product_description, exclusion_reason, effective_start, effective_end, source_doc
   - **Row count:** 179
   - **CSV file:** `data/current/exclusion_claims.csv`
   - **Query:** Semantic match on product_description vs user input

#### Material Handling
7. **Section232Material**
   - Material claims/disclaims per HTS code
   - Columns: hts_8digit, material_type ('copper'/'steel'/'aluminum'), **claim_code**, **disclaim_code**, min_percent_threshold, effective_start, effective_end
   - **Purpose:** Determines what Chapter 99 code to file (claim vs disclaim) per material
   - **Example:** HTS 9403.99.9045 (furniture), steel, claim_code=9903.81.91, disclaim_code=9903.81.96

8. **Section232Predicate** (v11.0)
   - Attribute-based rules for semiconductor 232 duties
   - Columns: hts_8digit, predicate_type ('attribute_threshold'), attribute_name (HS, MHz, memory), operator (>=, <=, ==), threshold_value, priority
   - **Purpose:** Per CBP CSMS #67400472, 232 semiconductors only apply if technical specs meet thresholds

#### Output Codes
9. **ProgramCode**
   - Output codes for each program/action
   - Columns: program_id, **action** ('apply'/'claim'/'disclaim'), **variant** (for IEEPA), **slice_type** (for 232 materials), chapter_99_code, duty_rate, effective_date, expiration_date
   - **Query:** Lookup by (program_id, action, variant, slice_type)
   - **Example:** (section_232, claim, copper, copper_slice) → 9903.81.30 @ 50%

10. **DutyRule**
    - Duty calculation rules per program
    - Columns: program_id, calculation_type ('additive'/'multiplicative'), **base_on** ('product_value'/'content_value'/'remaining_value'), **content_key** (material name), fallback_base_on, **base_effect** ('subtract_from_remaining' for 232)
    - **Example:** section_232, base_on='content_value', content_key='copper', base_effect='subtract_from_remaining'

#### Source Tracking (v10.0)
11. **SourceDocument**
    - Audit trail for all rules
    - Columns: document_type, document_id, document_url, published_date, content_hash, imported_date, change_detected_at
    - **Purpose:** Full compliance audit trail

12. **IngestionRun**
    - Records when data was ingested
    - Columns: run_id, script_name, started_at, completed_at, status, rows_loaded, csv_file, notes

#### Country Management (v6.0)
13. **CountryGroup**
    - Groupings: EU, UK, CN
    - Row count: 6
    - CSV file: `data/country_groups.csv`

14. **CountryGroupMember**
    - Map individual countries to groups
    - Row count: 50
    - CSV file: `data/country_group_members.csv`
    - **Example:** Germany → EU, England → UK, China → CN

15. **CountryAlias**
    - Normalize variations (Macau → MO, etc.)
    - Columns: alias_input, country_code, normalized_name

#### Rate Calculation Support
16. **ProgramRate**
    - Country-group-specific rates with formula support
    - Columns: program_id, country_group, chapter_99_code, duty_rate, **formula** (e.g., "15% - MFN"), effective_date, expiration_date
    - **Example:** (ieepa_reciprocal, EU, 9903.01.25) → formula="15% - MFN"

17. **HtsBaseRate**
    - MFN Column 1 rates for formulas
    - Columns: hts_8digit, mfn_rate, effective_date
    - **Row count:** 15,263
    - **CSV file:** `data/mfn_base_rates_8digit.csv`
    - **Purpose:** EU formula calculation

18. **ProgramCountryScope** (v6.0)
    - Data-driven country applicability per program
    - Columns: program_id, country, applies, effective_date, expiration_date, reason
    - **Purpose:** Replaces hardcoded country lists

19. **ProgramSuppression** (v6.0)
    - Program interaction rules (suppression, precedence)
    - Columns: suppressing_program_id, suppressed_program_id, reason, effective_date
    - **Example:** timber → timber_tariff suppresses ieepa_reciprocal

#### IEEPA & Annexes
20. **IeepaAnnexIIExclusion**
    - Annex II energy product exemptions
    - Columns: hts_8digit, product_description, category (energy/pharmaceutical/chemical), exemption_code, effective_start, effective_end, source_doc
    - **Row count:** 48 in legacy CSV (`data/annex_ii_exemptions.csv`)

#### Audit & Learning
21. **ProductHistory**
    - Historical product classifications
    - Columns: hts_code, product_description, classification_result, confidence, decision_data, created_by, created_at

22. **TariffCalculationLog** (v11.0)
    - Append-only audit log for all calculations
    - Columns: request_hash, hts_code, country, materials, import_date, program_results, total_duty, created_at
    - **Purpose:** Full audit trail for compliance

#### Section 301 Specific (section301.py)
23. **SourceVersion**
    - Audit backbone: tracks all sources with versioning (SCD Type 2)
    - Columns: source_type, document_id, content_hash, published_date, imported_at, **tier** (0/1/2)
    - **Purpose:** Full historical audit trail

24. **TariffMeasure**
    - Temporal tariff rates with versioning
    - Columns: hts_8digit, chapter_99_code, duty_rate, effective_start, effective_end, source_version_id, **is_current**, superseded_by_id

25. **ExclusionClaim**
    - Product exclusions with verification workflow
    - Columns: hts_8digit, product_description, exclusion_basis, evidence_summary, status (pending/approved/rejected), source_version_id, created_at

26. **HtsCodeHistory**
    - HTS code validity tracking for dual indexing
    - Columns: hts_8digit, hts_10digit, **validity_start**, **validity_end**, product_description

#### Search & Grounding
27. **GeminiSearchResult** (v14.0)
    - Cached search results from Gemini grounding API
    - Columns: query, search_results (JSON), confidence, created_at

28. **SearchAuditLog**
    - Search operation audit trail
    - Columns: query, result_count, confidence, created_at

29. **NeedsReviewQueue**
    - Cases requiring human review
    - Columns: hts_code, reason, status, assigned_to, created_at

30. **EvidenceQuote**
    - Exact quotes from evidence documents
    - Columns: quote_text, source_doc_id, page_number, confidence

### 4.2 Database Schema Diagram

```
TariffProgram (master)
├─ 1:N → Section301Rate (rates)
├─ 1:N → Section301Inclusion (legacy)
├─ 1:N → Section301Exclusion (exclusions)
├─ 1:N → Section232Rate (rates)
├─ 1:N → Section232Material (materials)
├─ 1:N → IeepaRate (rates)
├─ 1:N → ProgramCode (output codes)
├─ 1:N → DutyRule (rules)
├─ 1:N → ProgramRate (country-specific)
├─ 1:N → ProgramCountryScope (scope)
└─ 1:N → ProgramSuppression (interactions)

CountryGroup
└─ 1:N → CountryGroupMember (countries)
└─ 1:N → ProgramRate (rates by group)

HtsBaseRate
└─ Referenced by: ProgramRate (formula calculations)

SourceDocument (audit)
├─ Referenced by: Section301Rate
├─ Referenced by: Section301Exclusion
└─ Referenced by: SourceVersion

SourceVersion (SCD Type 2 audit backbone)
├─ 1:N → TariffMeasure
├─ 1:N → ExclusionClaim
└─ 1:N → HtsCodeHistory
```

---

## 5. RAG PIPELINE: PINECONE + EMBEDDINGS

### 5.1 Vector Store Architecture

**Files:**
- `app/chat/vector_stores/pinecone.py`
- `app/chat/vector_stores/tariff_search.py`
- `app/chat/embeddings/openai.py` (OpenAI text-embedding-3-small)

**Pinecone Configuration:**
- **API Key:** From `.env` (PINECONE_API_KEY)
- **Index Name:** `docs`
- **Region:** us-east-1
- **Embedding Model:** OpenAI text-embedding-3-small (1,536 dimensions)

**Vector Store Usage:**
- **Document Corpus:** Government documents (FR notices, CBP FAQs, CSMs)
- **Metadata:** pdf_id, chunk_index, source_type, page_number
- **Search Mode:** Multi-doc (scope_filter by corpus)

**Search Integration:**
```python
# In stacking_rag.py (agentic mode)
retriever = build_multi_doc_retriever(
    scope_filter={"corpus": "gov_trade"},
    k=5
)
documents = retriever.invoke(query)
```

**Known Limitations (based on code analysis):**
- **No real-time sync:** Documents ingested via manual scripts (ingest_test_docs.py)
- **No temporal filtering:** Vector search doesn't filter by publication date
- **Fallback:** If retriever fails, tools can still run without RAG context

---

## 6. LLM INTEGRATION: LANGGRAPH + LANGCHAIN

### 6.1 Graph Architecture

**File:** `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/chat/graphs/stacking_rag.py` (1,300+ lines)

**Framework:** LangGraph v0.2+ (state graph with checkpointing)

**Graph State (StackingState):**
```python
class StackingState(TypedDict):
    messages: Sequence[BaseMessage]              # Conversation history
    hts_code: str                                 # Input HTS
    country: str                                  # Origin country
    product_description: str                      # Product for exclusion match
    product_value: float                          # Declared value
    import_date: Optional[str]                    # YYYY-MM-DD
    materials: Optional[Dict[str, float]]         # Composition
    materials_needed: bool                        # Prompt for materials?
    applicable_materials: Optional[List[str]]     # From database
    programs: List[dict]                          # Applicable programs
    program_results: Dict[str, Any]               # Results per program
    filing_lines: List[dict]                      # Final output
    decisions: List[dict]                         # Audit trail
    total_duty: Optional[dict]                    # Calculated duty
    entries: List[dict]                           # ACE entry slices (v4.0)
    unstacking: Optional[dict]                    # IEEPA unstacking (v4.0)
    slices: List[dict]                            # Planned slices
    annex_ii_exempt: bool                         # Annex II status
    quantity: Optional[int]                       # Piece count (v7.1)
    quantity_uom: Optional[str]                   # Unit of measure (v7.1)
```

**11 Graph Nodes (in sequence):**

1. **initialize_node()** (line 110)
   - Calls: `get_applicable_programs`
   - Output: programs[], decisions[]

2. **check_materials_node()** (line 148)
   - Calls: `ensure_materials`
   - Output: materials_needed, applicable_materials, user_question

3. **check_annex_ii_node()** (line ~400)
   - Calls: `check_annex_ii_exclusion`
   - Output: annex_ii_exempt

4. **plan_slices_node()** (line ~450)
   - Calls: `plan_entry_slices`
   - Output: slices[]

5. **process_programs_loop_node()** (line ~600)
   - Loops over programs in filing_sequence
   - Calls per program:
     - `check_program_inclusion`
     - `check_program_exclusion`
     - `check_material_composition`
     - `resolve_program_dependencies`
     - `get_program_output`
   - Output: program_results{}

6. **tool_edge()** (line ~800)
   - Routes to appropriate tool based on LLM message
   - Processes tool_results back into messages

7. **build_entry_stacks_node()** (line ~527)
   - Calls: `resolve_reciprocal_variant`, `build_entry_stack`
   - Output: entries[], filing_lines[]

8. **calculate_duties_node()** (line ~800)
   - Calls: `calculate_duties`
   - Output: total_duty{}

9. **generate_output_node()** (line ~900)
   - Formats final response
   - Output: final_output

10. **final_edge()** (line ~1000)
    - Routes to END if done, or loops back

11. **end_node()** (implicit)
    - Returns complete state

**Graph Flow:**
```
START
  ↓
initialize_node
  ↓
check_materials_node ──→ (awaiting_user_input?) ──→ wait_for_user
  ↓                                                      ↓
  └─────────────────────────────────────────────────────┘
  ↓
check_annex_ii_node
  ↓
plan_slices_node
  ↓
process_programs_loop_node
  ├─► For each program:
  │   ├─ check_program_inclusion
  │   ├─ check_program_exclusion
  │   ├─ check_material_composition
  │   ├─ resolve_program_dependencies
  │   └─ get_program_output
  ↓
build_entry_stacks_node
  ├─ resolve_reciprocal_variant
  └─ build_entry_stack (per slice)
  ↓
calculate_duties_node
  ↓
generate_output_node
  ↓
END
```

**Checkpointing:**
- **Strategy:** MemorySaver (development) or LangGraph persistent checkpointer (production)
- **Purpose:** Resume conversations, audit trail
- **Configuration:** `{"thread_id": conversation_id}`

**Tool Calling:**
- **LLM:** ChatOpenAI (gpt-4-turbo)
- **Tool Map:** TOOL_MAP dict (50 STACKING_TOOLS)
- **Binding:** `llm.bind_tools([STACKING_TOOLS])`

### 6.2 Entry Point

**File:** `app/web/views/tariff_views.py` (lines 25-122)

**API Endpoint:** `POST /tariff/calculate`

```python
def calculate_tariff():
    # 1. Parse request
    hts_code = data.get("hts_code")
    country = data.get("country")
    materials = data.get("materials")  # May be None

    # 2. Continue with materials if session exists
    if session_id and session_id in _sessions:
        rag = _sessions[session_id]
        result = rag.continue_with_materials(materials or {})
    else:
        # 3. New calculation
        session_id = str(uuid.uuid4())
        rag = StackingRAG(conversation_id=session_id)

        result = rag.calculate_stacking(
            hts_code=hts_code,
            country=country,
            product_description=product_description,
            product_value=product_value,
            materials=materials
        )

        # 4. Check if materials needed
        if result.get("awaiting_user_input"):
            _sessions[session_id] = rag
            return {
                "session_id": session_id,
                "needs_materials": True,
                "applicable_materials": result["applicable_materials"]
            }

    # 5. Return results
    return {
        "entries": result["entries"],
        "total_duty": result["total_duty"],
        "potential_exclusions": ExclusionClaim.find_exclusion_candidates(...)
    }
```

---

## 7. DATA INGESTION PIPELINE

### 7.1 Main Ingestion Script

**File:** `scripts/populate_tariff_tables.py` (2,000+ lines)

**Purpose:** Initialize and update tariff database from CSV files

**Usage:**
```bash
# First deploy: reset and load from CSV
python scripts/populate_tariff_tables.py --reset

# Production: preserve runtime data
python scripts/populate_tariff_tables.py --seed-if-empty

# Manual update: reload specific table
python scripts/populate_tariff_tables.py --table section_301_rates
```

**v17.0 Update (Jan 2026):**
- **DB as Source of Truth:** Tables are source, not CSV
- **--seed-if-empty:** Only loads if table < 10K rows (preserves pipeline-discovered rates)
- **Railway Deploy:** Uses --seed-if-empty to preserve evidence packets
- **Critical Fix:** Section301Rate not deleted on < 10,000 rows

**Data Files Loaded:**

| CSV File | Rows | Purpose |
|----------|------|---------|
| `tariff_programs.csv` | 19 | TariffProgram table |
| `section_301_inclusions.csv` | 11,372 | Section301Inclusion table |
| `section_301_rates.csv` | 10,811 | Section301Rate table (temporal) |
| `section_232_rates.csv` | 1,638 | Section232Rate table |
| `ieepa_rates.csv` | 46 | IeepaRate table |
| `exclusion_claims.csv` | 179 | Section301Exclusion table |
| `annex_ii_exemptions.csv` | 48 | IeepaAnnexIIExclusion table |
| `mfn_base_rates_8digit.csv` | 15,263 | HtsBaseRate table |
| `country_groups.csv` | 6 | CountryGroup table |
| `country_group_members.csv` | 50 | CountryGroupMember table |

**CSV Headers & Format:**

**section_301_rates.csv:**
```
id,hts_8digit,hts_10digit,chapter_99_code,duty_rate,effective_start,effective_end,list_name,sector,product_group,description,source_doc,source_doc_id,supersedes_id,superseded_by_id,role,created_at,created_by
1,01012100,,9903.88.15,0.0750,2020-02-14,,list_4A,,,,FR-2019-08-20_2019-17865_List4A_4B_notice.pdf,,,,impose,2026-01-20T02:41:01.774836,
```

**section_301_inclusions.csv:**
```
hts_8digit,hts_10digit,chapter_99_code,duty_rate,list_name,effective_start,effective_end,source_doc
28452000,,9903.88.01,0.25,list_1,2018-07-06,,USITC Chapter 99 currentRelease
```

### 7.2 Data Ingestion Components

**Parse Scripts:**

1. **parse_fr_301_pdfs.py** (16,842 lines of logic)
   - Extracts HTS codes from Federal Register PDFs
   - Parses tables in PDF format
   - Validates HTS format (8 or 10 digits)
   - Output: CSV with HTS, chapter_99_code, duty_rate

2. **parse_cbp_232_lists.py** (16,190 lines)
   - Parses CBP Section 232 proclamation lists
   - Extracts material types (steel, aluminum, copper)
   - Builds Section232Rate records
   - Country exceptions (UK = 25%, global = 50%)

3. **populate_exclusion_claims.py** (16,842 lines)
   - Ingests Section 301 exclusion requests
   - Matches product descriptions to HTS codes
   - Creates Section301Exclusion records
   - Row count in data: 179

4. **ingest_ieepa_annex_ii.py** (10,203 lines)
   - Parses Annex II energy product list (EO 14257)
   - Creates IeepaAnnexIIExclusion records
   - Categories: energy, pharmaceutical, chemical

**Validation Scripts:**

- **validate_301_csv.py:** Validates HTS format, rate ranges, date ranges
- **reconcile_section_301.py:** Checks temporal coverage, detects gaps
- **reconcile_coverage.py:** Ensures all Section 301 lists covered

**Audit Trail:**

Each ingestion run creates **IngestionRun** record:
```python
IngestionRun(
    run_id=uuid.uuid4(),
    script_name="populate_tariff_tables.py",
    started_at=datetime.now(),
    completed_at=datetime.now(),
    status="success",
    rows_loaded=10811,
    csv_file="section_301_rates.csv",
    notes="Loaded temporal rates from 2020-02-14 to 2026-02-10"
)
```

---

## 8. WEB UI ARCHITECTURE

### 8.1 Frontend Structure

**Path:** `/sessions/hopeful-ecstatic-darwin/mnt/lanes/client/`

**Type:** React.js Single Page Application (SPA)

**Key Features:**
- Tariff calculator form (HTS, country, value, materials)
- Real-time validation
- Material input collection
- Results display with entry stacks
- Exclusion candidate suggestions
- Data freshness indicator

### 8.2 Backend API Views

**File:** `app/web/views/tariff_views.py` (1,000+ lines)

**Routes:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve calculator HTML |
| `/tariff/calculate` | POST | Calculate tariff stacking |
| `/tariff/freshness` | GET | Get data freshness for all sources |
| `/tariff/freshness/<program_id>` | GET | Get freshness for specific program |

**Session Management:**
- **_sessions dict:** In-memory store for awaiting_user_input cases
- **session_id:** UUID generated per calculation
- **Timeout:** Implicit (cleared on next POST)

### 8.3 Flask App Initialization

**File:** `app/web/__init__.py`

```python
def create_app():
    app = Flask(__name__)
    register_extensions(app)      # DB, migrations
    register_hooks(app)           # CORS, error handling
    register_blueprints(app)      # Routes
    return app
```

**Blueprints:**
- `auth_views`: Login/logout
- `tariff_views`: Calculator API
- `admin_views`: Data management
- `conversation_views`: Chat history
- `pdf_views`: Document upload
- `client_views`: React.js SPA

**Configuration:**
- **Database:** SQLite (dev), PostgreSQL (prod)
- **CORS:** Enabled
- **Session:** Permanent, SECRET_KEY from .env
- **Celery:** Optional Redis job queue

---

## 9. CONFIGURATION & ENVIRONMENT

### 9.1 Environment Variables (.env)

```
SECRET_KEY=123
SQLALCHEMY_DATABASE_URI=sqlite:///sqlite.db

# OpenAI API
OPENAI_API_KEY=sk-proj-...

# Pinecone Vector Store
PINECONE_API_KEY=pcsk_2pX5e7_...
PINECONE_ENV_NAME=us-east-1
PINECONE_INDEX_NAME=docs

# Langfuse Tracing
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# Gemini API (HTS scope verification)
GEMINI_API_KEY=AIzaSyC8ZYwnVbVvQwfcNSEU7cj...

# Gmail IMAP (CSMS Watcher)
GMAIL_CSMS_EMAIL=luvverma2011@gmail.com
GMAIL_CSMS_APP_PASSWORD=ejmrpdptmdmofvar

# PostgreSQL (Railway production)
DATABASE_URL_REMOTE=postgresql://postgres:...@metro.proxy.rlwy.net:51109/railway
AUTO_SYNC_ENABLED=true

# Redis (Celery job queue)
REDIS_URI=redis://localhost:6379
```

### 9.2 Deployment Configuration

**File:** `railway.toml`
```toml
[deploy]
startCommand = "python scripts/populate_tariff_tables.py && gunicorn wsgi:app --bind 0.0.0.0:$PORT"
```

**Deployment Flow:**
1. Railway pulls code
2. Install dependencies (requirements.txt)
3. Run `populate_tariff_tables.py --seed-if-empty` (preserves data)
4. Start Gunicorn server
5. Flask app serves static React.js + API

**Workers:**
- **railway-worker.toml:** Async job processing via Celery
- **Procfile:** Legacy format (fallback)

---

## 10. KNOWN LIMITATIONS & GAPS

### 10.1 Architecture Limitations

| Issue | Impact | Workaround |
|-------|--------|-----------|
| **In-memory sessions** | Sessions lost on server restart | Use database session store in production |
| **No temporal filter in RAG** | Vector search doesn't filter by publication date | Manual document curation in Pinecone |
| **Hardcoded IEEPA codes** | IEEPA_CODES dict (lines 52-82) not in database | Migration needed to temporal table (v13.0 started this) |
| **No HTS6/4/2 fallback** | Section 301 strictly HTS8/10 only | Users must provide full HTS for accuracy |
| **Semantic exclusion matching** | Product description match may fail for variations | LLM-based semantic search as fallback |
| **CSV-driven data** | Must edit CSV → upload → script to update | Could add UI for admin data entry |

### 10.2 Data Quality Issues

| Issue | Evidence | Risk |
|-------|----------|------|
| **Rate currency** | Last updated 2026-02-07 | Rates may be outdated; reliance on manual ingestion |
| **Coverage gaps** | Section 301 lists may not include all HTS codes | False negatives if HTS not in database |
| **Country alias completeness** | CountryAlias table has 50 entries | New country variations may not map correctly |
| **Exclusion description quality** | Section301Exclusion relies on semantic match | Exclusions may not apply if product description mismatches |

### 10.3 Known Bugs/Edge Cases

| Bug | Location | Impact |
|-----|----------|--------|
| **Material value validation** | stacking_rag.py:1167-1174 | Fails if sum(material_values) > product_value |
| **Null import_date handling** | stacking_tools.py:1076+ | Defaults to today() - may be unexpected for historical queries |
| **Annex II legacy CSV** | stacking_tools.py:175-227 | Still uses CSV if USE_DB_ENERGY_CHECK=false |
| **No variant fallback** | get_program_output() | May crash if variant not in ProgramCode table |

### 10.4 Feature Gaps

| Gap | Requested | Effort |
|-----|-----------|--------|
| **Batch calculations** | Multiple HTS codes in one request | Medium (loop + aggregation) |
| **Rate history** | Compare rates over time for same HTS | Low (temporal queries exist) |
| **Exclusion workflow** | Manage exclusion requests → approval | High (add UI + workflow states) |
| **Material library** | Pre-defined material compositions | Low (UI dropdown + cache) |
| **Scenario modeling** | "What if" rate changes | Medium (cache + replay) |

---

## 11. DEPLOYMENT & OPERATIONAL NOTES

### 11.1 Runtime Requirements

**Production Stack:**
- **OS:** Linux (Railway runs on Ubuntu)
- **Python:** 3.9+ (via runtime.txt)
- **Database:** PostgreSQL 12+ (Railway managed)
- **Cache:** Redis (Railway managed)
- **Storage:** Object storage (S3 compatible)

**Dependencies:**
- Flask 2.3+
- SQLAlchemy 3.0+
- LangChain 0.3+
- LangGraph 0.2+
- Celery 5.3+
- Pinecone 5.0+

**Memory:** ~512MB baseline; ~2GB for full data load

### 11.2 Scaling Considerations

**Bottlenecks:**
1. **Database queries:** 50 tools × ~5 queries each = 250 DB hits per calculation
   - Mitigate: Add SQLAlchemy query caching, materialized views
2. **LangGraph checkpointing:** Disk I/O for each node
   - Mitigate: Use in-memory checkpointer for development, persistent for prod
3. **Vector search latency:** Pinecone network calls
   - Mitigate: Cache embeddings, batch searches

**Recommendations:**
- Add database connection pooling (PgBouncer)
- Cache tariff_programs query (changes rarely)
- Pre-load common HTS codes into memory
- Monitor tool execution time (add tracing)

---

## 12. ARCHITECTURE SUMMARY

### 12.1 Component Interaction

```
┌──────────────────────────────────────────────────────────────┐
│                      USER FRONTEND                           │
│ (React calculator form in /client/build/)                   │
└────────────────┬─────────────────────────────────────────────┘
                 │ POST /tariff/calculate (JSON)
                 ▼
┌──────────────────────────────────────────────────────────────┐
│            FLASK WEB LAYER (tariff_views.py)                │
│ • Validates input                                           │
│ • Creates StackingRAG instance                              │
│ • Handles session management                                │
└────────────────┬─────────────────────────────────────────────┘
                 │
    ┌────────────┴─────────────┐
    │                          │
    ▼                          ▼
┌──────────────────┐  ┌──────────────────────────┐
│  STACKING GRAPH  │  │  TARIFF DATABASE         │
│  (LangGraph)     │  │  (SQLAlchemy + SQL)      │
│ 11 nodes         │  │ ~30 tables               │
│ 50 tools         │  │ Temporal tracking        │
│ Tool calling     │  │ Audit trail              │
└────────┬─────────┘  └──────┬───────────────────┘
         │                   │
         └───────┬───────────┘
                 │
         ┌───────▼──────────┐
         │  TOOL LAYER      │
         │ (stacking_tools) │
         │ • Deterministic  │
         │ • Data-driven    │
         │ • 2,700 lines    │
         └───────┬──────────┘
                 │
    ┌────────────┴───────────────────┐
    │                                │
    ▼                                ▼
┌──────────────────┐      ┌──────────────────────┐
│  PINECONE RAG    │      │  DATA INGESTION      │
│  (Vector Search) │      │  (Python scripts)    │
│ • Document       │      │ • Populate CSVs      │
│   retrieval      │      │ • Parse PDFs         │
│ • Semantic       │      │ • Validate data      │
│   search         │      │ • Audit trail        │
└──────────────────┘      └──────────────────────┘
```

### 12.2 Key Design Principles

1. **Data-Driven Core**
   - All tariff logic in tables, not code
   - Non-technical users update rates via CSV
   - No hardcoded country lists or HTS checks

2. **Temporal Tracking**
   - Effective date ranges for all rates
   - Historical queries supported (as_of_date)
   - Supersession tracking (what rate was replaced?)

3. **Deterministic Calculation**
   - No LLM in critical path (tariff math)
   - LLM used only for semantic exclusion matching
   - Full audit trail for compliance defense

4. **Multi-Program Stacking**
   - Processes Section 301 + 232 + IEEPA simultaneously
   - Respects filing order (ACE compliance)
   - Separate calculation order for duty math (232 before IEEPA)

5. **Entry Slicing**
   - Products split by material type
   - Separate claim/disclaim codes per slice
   - CBP Phoebe-aligned filing structure

6. **Audit Everything**
   - Every decision logged with source citation
   - SourceVersion table for compliance audit trail
   - TariffCalculationLog for append-only audit

---

## 13. KEY FILES REFERENCE

### Code Organization

```
/sessions/hopeful-ecstatic-darwin/mnt/lanes/
├── app/
│   ├── chat/
│   │   ├── tools/
│   │   │   └── stacking_tools.py          [2,743 lines] ⭐ Core engine
│   │   ├── graphs/
│   │   │   └── stacking_rag.py            [1,300+ lines] LangGraph state machine
│   │   ├── vector_stores/
│   │   │   └── pinecone.py                Pinecone RAG
│   │   └── embeddings/
│   │       └── openai.py                  OpenAI embeddings
│   ├── web/
│   │   ├── db/
│   │   │   └── models/
│   │   │       ├── tariff_tables.py       [1,811 lines] ⭐ Data models
│   │   │       └── base.py
│   │   ├── views/
│   │   │   └── tariff_views.py            [1,000+ lines] API endpoints
│   │   ├── __init__.py                    Flask app factory
│   │   └── config/__init__.py             Configuration
│   ├── models/
│   │   ├── section301.py                  [736 lines] Section 301 models
│   │   ├── evidence.py
│   │   └── regulatory_run.py
│   └── services/
│       └── freshness.py                   Data freshness service
├── scripts/
│   ├── populate_tariff_tables.py          [2,000+ lines] ⭐ Data ingestion
│   ├── parse_fr_301_pdfs.py               [16,842 lines] FR PDF parser
│   ├── parse_cbp_232_lists.py             [16,190 lines] CBP 232 parser
│   ├── populate_exclusion_claims.py       [16,842 lines] Exclusion ingestion
│   ├── ingest_ieepa_annex_ii.py           [10,203 lines] Annex II ingestion
│   └── validate_301_csv.py                CSV validation
├── data/
│   ├── tariff_programs.csv                [19 rows] Program definitions
│   ├── section_301_rates_temporal.csv     [10,785 rows] Temporal rates
│   ├── mfn_base_rates_8digit.csv          [15,263 rows] MFN rates
│   ├── country_groups.csv                 [6 rows] Country groupings
│   └── current/
│       ├── section_301_rates.csv          [10,811 rows] Current rates
│       ├── section_301_inclusions.csv     [11,372 rows] Inclusions
│       ├── section_232_rates.csv          [1,638 rows] 232 rates
│       ├── ieepa_rates.csv                [46 rows] IEEPA rates
│       ├── exclusion_claims.csv           [179 rows] Exclusions
│       └── manifest.json                  Data manifest
├── wsgi.py                                WSGI entry point
├── railway.toml                           Railway deployment config
├── Procfile                               Process definition
├── requirements.txt                       Python dependencies
└── README.md
```

### Critical Code References

| Component | File | Lines | Key Functions |
|-----------|------|-------|---|
| Stacking Engine | `stacking_tools.py` | 2,743 | get_applicable_programs(), check_program_inclusion(), calculate_duties() |
| Data Models | `tariff_tables.py` | 1,811 | 30 SQLAlchemy models (TariffProgram, Section301Rate, etc.) |
| Graph State Machine | `stacking_rag.py` | 1,300+ | StackingRAG class, 11 graph nodes |
| Data Ingestion | `populate_tariff_tables.py` | 2,000+ | Main orchestrator for CSV loading |
| API Layer | `tariff_views.py` | 1,000+ | POST /tariff/calculate endpoint |
| Section 301 Models | `section301.py` | 736 | SourceVersion, TariffMeasure, ExclusionClaim |

---

## 14. SUMMARY: WHAT THIS SYSTEM DOES

**The Lanes Chatbot is a production tariff stacking engine that:**

1. **Accepts tariff queries:** HTS code, country of origin, product value, material composition
2. **Queries temporal databases:** Finds applicable Section 301, 232, IEEPA programs with effective dates
3. **Evaluates eligibility:** Checks HTS inclusion, product exclusions, material thresholds
4. **Calculates duties:** Applies country-specific rates, formula support (EU 15% ceiling), content-value splits
5. **Implements IEEPA unstacking:** Subtracts 232-subject material from reciprocal tariff base
6. **Splits ACE entries:** Creates multiple filing lines by material type (copper/steel/aluminum)
7. **Returns audit trail:** Full source citations and decision rationale for CBP compliance

**Key Differentiators:**
- ✅ **Data-driven, not hardcoded:** Rates in database, not code
- ✅ **Temporal tracking:** Time-series rates with effective date ranges
- ✅ **Deterministic core:** No AI in critical calculation path
- ✅ **Phoebe-aligned:** Supports Customs-friendly entry structures
- ✅ **Fully auditable:** Every decision logged with source document reference

**Architecture: Single agent + 50 deterministic tools querying temporal databases → LangGraph graph orchestrates flow → Flask API serves web UI**

