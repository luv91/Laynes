# Lanes - Stacking Feature Implementation Plan

## Summary

Build a **Tariff Stacking Calculator** that takes an HTS code + Country of Origin and outputs the complete CBP filing sequence with calculated duties and full audit trail.

**Design Principle:** The orchestrator loop stays **tiny and generic**. All program-specific logic lives in **data (tables)**, not code.

---

## Current Tariff Rates (December 2025)

**IMPORTANT:** These are REAL rates from government sources. Tariffs change frequently - see `docs/tariff_sources.md` for update sources.

| Program | Rate | Chapter 99 Code | Source |
|---------|------|-----------------|--------|
| Base Duty (HTS 8544.42.90.90) | 2.6% | - | [USITC HTS](https://hts.usitc.gov/) |
| Section 301 (List 3) | **25%** | 9903.88.03 | [USTR](https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions) |
| Section 232 Steel | **50%** | 9903.80.01 | [CBP](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs) |
| Section 232 Aluminum | **25%** | 9903.85.08 | [CBP](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs) |
| Section 232 Copper | **25%** | 9903.78.01 | CBP |
| IEEPA Fentanyl | **10%** | 9903.01.25 | [CBP IEEPA FAQ](https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ) |
| IEEPA Reciprocal (paid) | **10%** | 9903.01.33 | CBP IEEPA FAQ |
| IEEPA Reciprocal (disclaim) | 0% | 9903.01.25 | CBP IEEPA FAQ |

### Rate Changes in 2025

| Date | Change |
|------|--------|
| Mar 12, 2025 | Steel 232: 25% → 50%, Aluminum 232: 10% → 25% |
| Nov 10, 2025 | IEEPA Fentanyl: 20% → 10% (US-China deal) |

### Example Calculation: USB-C Cable from China ($10,000)

```
Materials: copper 5%, steel 20%, aluminum 72%

Section 301:        $10,000 × 25% = $2,500
IEEPA Fentanyl:     $10,000 × 10% = $1,000
232 Copper:         DISCLAIM (5% < 25% threshold)
232 Steel:          DISCLAIM (20% < 25% threshold)
232 Aluminum:       $10,000 × 72% × 25% = $1,800 (CLAIM)
IEEPA Reciprocal:   $10,000 × 10% = $1,000 (has 232 claims)
─────────────────────────────────────────────
TOTAL DUTY:         $6,300 (63.0% effective rate)
```

---

## 0. Agent State & Tool Call Sequence (The Core)

### State Definition
```python
state = {
    "hts_code": str,
    "country": str,
    "import_date": date,              # When goods are being imported
    "product_description": str,
    "product_value": float,
    "materials": Dict[str, float],    # {copper: 0.05, steel: 0.20, ...} or None
    "program_results": {},            # Per-program decisions
    "filing_lines": [],               # Final Chapter 99 codes
    "decisions": [],                  # Audit log
    "flags": [],                      # Uncertainties for review
}
```

### The Tool Call Sequence (This is the whole algorithm)
```
Step 0: Input + import_date
    └── Collect HTS, country, description, value, import_date

Step 1: lookup_product_history()
    └── Pre-fill materials if high-confidence prior data
    └── Get suggested questions

Step 2: get_applicable_programs(country, hts_code, import_date)
    └── Returns programs sorted by filing_sequence
    └── This is the ONLY place country→program mapping happens

Step 3: FOR EACH program (sorted by filing_sequence):
    │
    ├── 3a. check_program_inclusion(program_id, hts_code)
    │       └── If check_type == "hts_lookup": query inclusion_table
    │       └── If check_type == "always": skip, treat as included
    │       └── If not included → record decision, SKIP to next program
    │
    ├── 3b. check_program_exclusion(program_id, hts_code, description)
    │       └── If exclusion_table exists: query + semantic match
    │       └── If excluded → record decision, SKIP to next program
    │
    ├── 3c. Handle condition (based on condition_handler):
    │       └── "none" → action = "apply"
    │       └── "handle_material_composition":
    │           └── First: ensure_materials() if not yet known
    │           └── Then: check_material_composition()
    │       └── "handle_dependency":
    │           └── resolve_program_dependencies()
    │
    └── 3d. get_program_output(program_id, action)
            └── Append FilingLine to state["filing_lines"]
            └── Store result in state["program_results"][program_id]

Step 4: calculate_duties(filing_lines, product_value, materials)
    └── Use duty_rules table, not hardcoded math

Step 5: Supervisor QA
    └── Verify all programs got decisions
    └── Sanity-check math
    └── Flag uncertainties

Step 6: Output + save to product_history
```

**Key insight:** The loop in Step 3 is **identical for every program**. The only variation is what `condition_handler` returns - and that's data-driven.

---

## 1. The Stacking Problem

**What is it?**
Customs brokers must determine which tariff programs apply to a product, in what order, and at what rates. A single invoice line item can expand into 5-10 filing lines.

**Example Input:**
- HTS: `8544.42.9090` (USB-C cable)
- Country of Origin: China
- Composition: Copper 5%, Steel 20%, Aluminum (remaining), Zinc 3%

**Expected Output:**
```
8544.42.9090
├── 9903.88.03 → Section 301
├── 9903.01.24 → IEEPA Fentanyl
├── 9903.01.25 → Disclaim IEEPA Reciprocal (or 9903.01.33 if claiming)
├── 9903.78.02 → 232 Disclaim Copper (or 9903.78.01 if claiming)
└── 9903.85.08 → 232 Claim Aluminum
```

Plus: Duty calculation, plain English explanation, citations, and audit log.

---

## 2. Data-Driven Decision Tree

**Core Principle:** NO hardcoded logic. All rules come from tables populated from government documents.

### Generic Algorithm
```
1. LOOKUP: What tariff programs might apply?
   → Query: tariff_programs WHERE country = ? OR country = "ALL"
   → Returns: [{program_id, check_type, priority, ...}, ...]

2. FOR EACH program in applicable_programs (ordered by priority):
   → LOOKUP: program_rules WHERE program_id = ?
   → Get: {inclusion_table, exclusion_table, condition_type, ...}

   → CHECK INCLUSION:
     Query: {inclusion_table} WHERE hts_8digit = LEFT(input_hts, 8)
     IF not found → program does NOT apply, skip

   → CHECK EXCLUSION (if applicable):
     Query: {exclusion_table} WHERE hts_8digit = ? AND valid_until > TODAY
     IF found → semantic match description against product
     IF match → program does NOT apply, skip

   → CHECK CONDITIONS (based on condition_type):
     - "always" → applies, no further check
     - "material_composition" → ask user or lookup history
     - "depends_on" → check result of another program first

   → LOOKUP OUTPUT CODES:
     Query: program_codes WHERE program_id = ? AND action = ?
     Get: {chapter_99_code, duty_rate, applies_to, ...}

3. ARRANGE by filing_sequence from tariff_programs table
4. CALCULATE duties using rules from duty_calculation table
```

### Why Data-Driven?
| Hardcoded Approach | Data-Driven Approach |
|-------------------|---------------------|
| `IF country == "China"` | `WHERE country = input_country` |
| Code change when rules change | Table update when rules change |
| Developer needed for updates | Admin/batch job can update |
| Logic buried in code | Logic visible in tables |

---

## 3. Data Architecture (Fully Data-Driven)

### Master Table: tariff_programs
*Defines what programs exist and when they apply*
```sql
CREATE TABLE tariff_programs (
    program_id          VARCHAR PRIMARY KEY,  -- "section_301", "ieepa_fentanyl"
    program_name        VARCHAR,              -- "Section 301 China Tariffs"
    country             VARCHAR,              -- "China", "ALL", etc.
    check_type          VARCHAR,              -- "hts_lookup", "always"
    condition_handler   VARCHAR,              -- "none", "handle_material_composition", "handle_dependency"
    condition_param     VARCHAR,              -- NULL, or "section_232" for dependencies
    inclusion_table     VARCHAR,              -- "section_301_inclusions" or NULL
    exclusion_table     VARCHAR,              -- "section_301_exclusions" or NULL
    filing_sequence     INT,                  -- Order in CBP filing (1, 2, 3...)
    source_document     VARCHAR,              -- "USTR_301_Notice.pdf"
    effective_date      DATE,
    expiration_date     DATE                  -- NULL if still active
);
```

**Example rows:**
| program_id | country | check_type | condition_handler | condition_param | inclusion_table | filing_sequence |
|------------|---------|------------|-------------------|-----------------|-----------------|-----------------|
| section_301 | China | hts_lookup | none | NULL | section_301_inclusions | 1 |
| ieepa_fentanyl | China | always | none | NULL | NULL | 2 |
| ieepa_reciprocal | China | always | handle_dependency | section_232 | NULL | 3 |
| section_232_copper | ALL | hts_lookup | handle_material_composition | copper | section_232_materials | 4 |
| section_232_steel | ALL | hts_lookup | handle_material_composition | steel | section_232_materials | 5 |
| section_232_aluminum | ALL | hts_lookup | handle_material_composition | aluminum | section_232_materials | 6 |

**Why `condition_handler` instead of `condition_type`?**
- The orchestrator just calls `handlers[condition_handler](program, state)`
- Adding a new condition type = add a handler function + a row in the table
- The loop code NEVER changes

### Inclusion Tables (per program)

**section_301_inclusions** (populated from Lists 1-4 PDFs)
```sql
CREATE TABLE section_301_inclusions (
    hts_8digit      VARCHAR,
    list_name       VARCHAR,      -- "list_1", "list_2", "list_3", "list_4a"
    chapter_99_code VARCHAR,      -- "9903.88.03"
    duty_rate       DECIMAL,      -- 0.25
    source_doc      VARCHAR,
    source_page     INT,
    PRIMARY KEY (hts_8digit, list_name)
);
```

**section_232_materials** (populated from 232 proclamations)
```sql
CREATE TABLE section_232_materials (
    hts_8digit      VARCHAR,
    material        VARCHAR,      -- "copper", "steel", "aluminum"
    claim_code      VARCHAR,      -- "9903.78.01"
    disclaim_code   VARCHAR,      -- "9903.78.02"
    duty_rate       DECIMAL,      -- 0.25
    source_doc      VARCHAR,
    PRIMARY KEY (hts_8digit, material)
);
```

### Exclusion Tables

**section_301_exclusions** (populated from exclusion notices + extensions)
```sql
CREATE TABLE section_301_exclusions (
    id              SERIAL PRIMARY KEY,
    hts_8digit      VARCHAR,
    description     TEXT,         -- Full exclusion description for semantic match
    exclusion_doc   VARCHAR,      -- Source document
    original_expiry DATE,
    extended_to     DATE,         -- Latest extension date
    is_active       BOOLEAN,      -- Computed: extended_to > TODAY
    source_page     INT
);
```

### Program Codes (output mapping)

**program_codes**
```sql
CREATE TABLE program_codes (
    program_id      VARCHAR,
    action          VARCHAR,      -- "claim", "disclaim", "apply"
    chapter_99_code VARCHAR,
    duty_rate       DECIMAL,
    applies_to      VARCHAR,      -- "full", "partial"
    source_doc      VARCHAR,
    FOREIGN KEY (program_id) REFERENCES tariff_programs(program_id)
);
```

**Example rows:**
| program_id | action | chapter_99_code | duty_rate |
|------------|--------|-----------------|-----------|
| section_301 | apply | 9903.88.03 | 0.25 |
| section_232_copper | claim | 9903.78.01 | 0.25 |
| section_232_copper | disclaim | 9903.78.02 | 0 |
| ieepa_fentanyl | apply | 9903.01.24 | 0.XX |
| ieepa_reciprocal | paid | 9903.01.33 | 0.XX |
| ieepa_reciprocal | disclaim | 9903.01.25 | 0 |

### Duty Calculation Rules

**duty_rules**
```sql
CREATE TABLE duty_rules (
    program_id          VARCHAR,
    calculation_type    VARCHAR,  -- "additive", "compound", "on_portion"
    base_on             VARCHAR,  -- "product_value", "previous_duty", "material_percentage"
    compounds_with      VARCHAR,  -- NULL or another program_id
    source_doc          VARCHAR
);
```

### Product History (Learning)

**product_history**
```sql
CREATE TABLE product_history (
    id              SERIAL PRIMARY KEY,
    hts_code        VARCHAR,
    product_desc    TEXT,
    country         VARCHAR,
    components      JSONB,        -- {"copper": 0.05, "steel": 0.20, ...}
    decisions       JSONB,        -- Previous stacking decisions
    timestamp       TIMESTAMP,
    user_id         VARCHAR,
    user_confirmed  BOOLEAN
);
```

---

## 4. How Tables Get Populated

### From Government Documents (Batch Job)
```
PDFs/Notices → Parse → Validate → Insert/Update Tables

1. Section 301 Lists 1-4 → section_301_inclusions
2. Section 301 Exclusions → section_301_exclusions
3. Extension Notices → UPDATE section_301_exclusions.extended_to
4. Section 232 Proclamations → section_232_materials
5. IEEPA Notices → tariff_programs + program_codes
```

### Nightly Update Job
```python
def nightly_tariff_update():
    # 1. Check for new government notices (RSS, email, web scrape)
    new_docs = fetch_new_notices()

    # 2. Parse each document
    for doc in new_docs:
        doc_type = classify_document(doc)  # "301_extension", "232_addition", etc.
        parsed = parse_document(doc, doc_type)

    # 3. Update relevant tables
        if doc_type == "301_extension":
            update_exclusion_dates(parsed)
        elif doc_type == "301_new_list":
            insert_inclusions(parsed)
        # ... etc

    # 4. Validate changes
    run_consistency_checks()

    # 5. Log for audit
    log_update(doc, changes)
```

### Why This Design?
1. **No code changes** when tariff rules change
2. **Full audit trail** - every rule traces to a source document
3. **Easy to test** - can verify table contents against PDFs
4. **Extensible** - add new programs by adding rows, not code
5. **Temporal** - can query "what were the rules on date X?"

---

## 5. New Tools Required (Data-Driven)

### Tool 0: `ensure_materials(state) -> Dict[str, float]`
```python
def ensure_materials(state: dict) -> dict:
    """
    Ensure we have material composition BEFORE any program needs it.
    Called ONCE, not per-program.

    1. Check state["materials"] - if already complete, return it
    2. Check product_history for high-confidence prior data
    3. RAG over product spec sheets if available
    4. Ask user MINIMUM necessary questions:
       - "Does this product contain copper/steel/aluminum?"
       - "What percentage of each?"
    5. Update state["materials"] and return

    This avoids multiple programs each triggering separate composition questions.
    """
```

### Tool 1: `get_applicable_programs(country: str, hts_code: str, import_date: date) -> List[Program]`
```python
@tool
def get_applicable_programs(country: str, hts_code: str, import_date: date) -> str:
    """
    Query tariff_programs table to find what programs might apply.

    1. Query: SELECT * FROM tariff_programs
              WHERE (country = ? OR country = 'ALL')
              AND effective_date <= import_date
              AND (expiration_date IS NULL OR expiration_date > import_date)
              ORDER BY filing_sequence

    2. Return: [{program_id, check_type, condition_handler, inclusion_table, ...}]

    IMPORTANT: Takes import_date explicitly - never uses "today" internally.
    This enables: "What would have applied in 2022?" and easier testing.
    """
```

### Tool 2: `check_program_inclusion(program_id: str, hts_code: str) -> InclusionResult`
```python
@tool
def check_program_inclusion(program_id: str, hts_code: str) -> str:
    """
    Check if HTS is included in a specific program.

    1. Lookup program's inclusion_table from tariff_programs
    2. Query: SELECT * FROM {inclusion_table} WHERE hts_8digit = LEFT(?, 8)
    3. Return: {included: bool, details: {...}, source_doc, source_page}

    Generic - works for ANY program by looking up the right table.
    """
```

### Tool 3: `check_program_exclusion(program_id: str, hts_code: str, product_description: str, import_date: date) -> ExclusionResult`
```python
@tool
def check_program_exclusion(program_id: str, hts_code: str, product_description: str, import_date: date) -> str:
    """
    Check if product qualifies for an exclusion.

    1. Lookup program's exclusion_table from tariff_programs
    2. Query: SELECT * FROM {exclusion_table}
              WHERE hts_8digit = LEFT(?, 8)
              AND extended_to > import_date  -- Date-filtered!
    3. For each potential exclusion:
       - Semantic match product_description against exclusion.description
       - Use LLM for fuzzy matching
    4. Return: {excluded: bool, exclusion_id, match_confidence, source_doc}

    NOTE: This is the ONLY non-deterministic step in the core loop (LLM semantic match).
    """
```

### Tool 4: `check_material_composition(hts_code: str, materials: dict) -> MaterialResult`
```python
@tool
def check_material_composition(hts_code: str, materials: dict) -> str:
    """
    For programs with condition_type='material_composition'.

    1. Query: SELECT * FROM section_232_materials WHERE hts_8digit = LEFT(?, 8)
    2. For each material in table:
       - Check if material in user-provided materials dict
       - If yes: lookup claim_code, calculate portion
       - If no: lookup disclaim_code
    3. Return: [{material, applies, percentage, code, action, duty_rate}]
    """
```

### Tool 5: `resolve_program_dependencies(program_id: str, previous_results: dict) -> DependencyResult`
```python
@tool
def resolve_program_dependencies(program_id: str, previous_results: dict) -> str:
    """
    For programs with condition_type='depends_on:X'.

    1. Parse condition_type to get dependency (e.g., "section_232")
    2. Check previous_results for that program
    3. Determine which action/code based on dependency result
    4. Query program_codes for the right output

    Example: ieepa_reciprocal depends on section_232 claims
    - If any 232 claims exist → action = "paid"
    - Else → action = "disclaim"
    """
```

### Tool 6: `get_program_output(program_id: str, action: str) -> CodeResult`
```python
@tool
def get_program_output(program_id: str, action: str) -> str:
    """
    Lookup the output codes for a program decision.

    1. Query: SELECT * FROM program_codes
              WHERE program_id = ? AND action = ?
    2. Return: {chapter_99_code, duty_rate, applies_to, source_doc}
    """
```

### Tool 7: `calculate_duties(applicable_programs: List, product_value: float) -> DutyResult`
```python
@tool
def calculate_duties(applicable_programs: List, product_value: float) -> str:
    """
    Calculate total duties based on all applicable programs.

    1. For each program, lookup duty_rules
    2. Apply based on calculation_type:
       - "additive": Add duty_rate to running total
       - "compound": Apply on (value + previous_duty)
       - "on_portion": Apply only to material_percentage of value
    3. Return: {filing_lines, total_duty_percent, total_duty_amount, breakdown}
    """
```

### Tool 8: `lookup_product_history(hts_code: str, product_desc: str) -> HistoryResult`
```python
@tool
def lookup_product_history(hts_code: str, product_desc: str) -> str:
    """
    Check if we've handled similar products before.

    1. Query: SELECT * FROM product_history
              WHERE hts_code = ? ORDER BY timestamp DESC
    2. Semantic match on product_desc for similarity
    3. Return: {found, previous_compositions, previous_decisions, suggested_questions}

    Helps reduce user questions by using historical data.
    """
```

---

## 6. Agentic Workflow (Data-Driven)

```
┌───────────────────────────────────────────────────────────────────────────┐
│                      STACKING AGENT GRAPH                                  │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  INPUT: hts_code, country, product_description                            │
│    │                                                                      │
│    ▼                                                                      │
│  ┌─────────────────────────────────────────┐                              │
│  │ 1. LOOKUP PRODUCT HISTORY               │                              │
│  │    Tool: lookup_product_history()       │                              │
│  │    → Check if we know composition       │                              │
│  │    → Get suggested questions            │                              │
│  └──────────────────┬──────────────────────┘                              │
│                     │                                                     │
│                     ▼                                                     │
│  ┌─────────────────────────────────────────┐                              │
│  │ 2. GET APPLICABLE PROGRAMS              │ ◄── Data-driven!             │
│  │    Tool: get_applicable_programs()      │     Query tariff_programs    │
│  │    → Returns list of programs to check  │     table, not hardcoded     │
│  │    → Ordered by filing_sequence         │                              │
│  └──────────────────┬──────────────────────┘                              │
│                     │                                                     │
│                     ▼                                                     │
│  ┌─────────────────────────────────────────┐                              │
│  │ 3. FOR EACH PROGRAM (ordered):          │                              │
│  │                                         │                              │
│  │    ┌─────────────────────────────────┐  │                              │
│  │    │ 3a. CHECK INCLUSION             │  │                              │
│  │    │     Tool: check_program_inclusion│  │                              │
│  │    │     → Query program's table     │  │                              │
│  │    │     → If not included, SKIP     │  │                              │
│  │    └───────────────┬─────────────────┘  │                              │
│  │                    │                    │                              │
│  │                    ▼                    │                              │
│  │    ┌─────────────────────────────────┐  │                              │
│  │    │ 3b. CHECK EXCLUSION (if any)    │  │                              │
│  │    │     Tool: check_program_exclusion│  │                              │
│  │    │     → Semantic match description │  │                              │
│  │    │     → If excluded, SKIP         │  │                              │
│  │    └───────────────┬─────────────────┘  │                              │
│  │                    │                    │                              │
│  │                    ▼                    │                              │
│  │    ┌─────────────────────────────────┐  │                              │
│  │    │ 3c. CHECK CONDITIONS            │  │                              │
│  │    │     Based on condition_type:    │  │                              │
│  │    │     - "always" → applies        │  │                              │
│  │    │     - "material_composition"    │  │                              │
│  │    │       → ASK USER or use history │  │                              │
│  │    │       → Tool: check_material_   │  │                              │
│  │    │              composition()      │  │                              │
│  │    │     - "depends_on:X"            │  │                              │
│  │    │       → Tool: resolve_program_  │  │                              │
│  │    │              dependencies()     │  │                              │
│  │    └───────────────┬─────────────────┘  │                              │
│  │                    │                    │                              │
│  │                    ▼                    │                              │
│  │    ┌─────────────────────────────────┐  │                              │
│  │    │ 3d. GET OUTPUT CODE             │  │                              │
│  │    │     Tool: get_program_output()  │  │                              │
│  │    │     → chapter_99_code, duty_rate│  │                              │
│  │    └─────────────────────────────────┘  │                              │
│  │                                         │                              │
│  └──────────────────┬──────────────────────┘                              │
│                     │                                                     │
│                     ▼                                                     │
│  ┌─────────────────────────────────────────┐                              │
│  │ 4. CALCULATE DUTIES                     │ ◄── Deterministic            │
│  │    Tool: calculate_duties()             │     Uses duty_rules table    │
│  │    → Order by filing_sequence           │                              │
│  │    → Apply compound/additive rules      │                              │
│  │    → Calculate total                    │                              │
│  └──────────────────┬──────────────────────┘                              │
│                     │                                                     │
│                     ▼                                                     │
│  ┌─────────────────────────────────────────┐                              │
│  │ 5. SUPERVISOR QA                        │                              │
│  │    → Verify all programs checked        │                              │
│  │    → Verify math correct                │                              │
│  │    → Flag uncertainties                 │                              │
│  │    → Run consistency check              │                              │
│  └──────────────────┬──────────────────────┘                              │
│                     │                                                     │
│                     ▼                                                     │
│  ┌─────────────────────────────────────────┐                              │
│  │ 6. GENERATE OUTPUT                      │                              │
│  │    → Filing lines (ordered)             │                              │
│  │    → Plain English explanation          │                              │
│  │    → Decision audit trail               │                              │
│  │    → Source citations                   │                              │
│  │    → Save to product_history            │                              │
│  └──────────────────┬──────────────────────┘                              │
│                     │                                                     │
│                     ▼                                                     │
│                   END                                                     │
└───────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Loop vs Hardcoded Steps
The old design had hardcoded steps: "Step 1: 301", "Step 2: 232", "Step 3: IEEPA"...

The new design has a **generic loop**:
```python
programs = get_applicable_programs(country, hts)  # From database
for program in programs:
    check_inclusion(program)
    check_exclusion(program)
    check_conditions(program)
    get_output(program)
```

If government adds a new tariff program tomorrow, we just add rows to the database - NO CODE CHANGES.

---

## 7. Output Schema

```python
class StackingOutput(BaseModel):
    schema_version: str = "1.0"

    # Input
    hts_code: str
    country_of_origin: str
    product_description: str
    materials: Dict[str, float]  # {copper: 0.05, steel: 0.20, ...}

    # Filing Lines (the main output)
    filing_lines: List[FilingLine]

    # Calculations
    base_duty_rate: float
    total_duty_percent: float
    duty_breakdown: List[DutyBreakdown]

    # Audit Trail
    decisions: List[Decision]  # Each decision with reason + source
    user_inputs: List[UserInput]  # What user confirmed
    citations: List[SourceCitation]

    # QA
    confidence: str  # high/medium/low
    flags: List[str]  # Uncertainties for broker review

class FilingLine(BaseModel):
    sequence: int
    chapter_99_code: str
    program: str  # "Section 301", "IEEPA Fentanyl", etc.
    action: str  # "claim" or "disclaim"
    applies_to: str  # "full" or "partial (5%)"
    duty_rate: Optional[float]

class Decision(BaseModel):
    step: str
    decision: str
    reason: str
    source_doc: str
    source_page: Optional[int]
    source_snippet: str
```

---

## 8. Implementation Phases

### Phase 1: Database Schema & Tables
- [ ] Create database schema (SQLite or Postgres)
- [ ] Create `tariff_programs` master table
- [ ] Create `section_301_inclusions` table
- [ ] Create `section_301_exclusions` table
- [ ] Create `section_232_materials` table
- [ ] Create `program_codes` table
- [ ] Create `duty_rules` table
- [ ] Create `product_history` table

### Phase 2: Populate Tables from Documents
- [ ] Parse Section 301 Lists 1-4 PDFs → `section_301_inclusions`
- [ ] Parse Section 301 Exclusions PDF → `section_301_exclusions`
- [ ] Parse Section 232 proclamations → `section_232_materials`
- [ ] Populate `tariff_programs` with program metadata
- [ ] Populate `program_codes` with Chapter 99 codes
- [ ] Populate `duty_rules` with calculation logic

### Phase 3: Core Tools (Data-Driven)
- [ ] Implement `get_applicable_programs()` - query tariff_programs
- [ ] Implement `check_program_inclusion()` - generic inclusion checker
- [ ] Implement `check_program_exclusion()` - semantic match + validity
- [ ] Implement `check_material_composition()` - 232 material handler
- [ ] Implement `resolve_program_dependencies()` - conditional logic
- [ ] Implement `get_program_output()` - code lookup
- [ ] Implement `calculate_duties()` - duty calculation
- [ ] Implement `lookup_product_history()` - learning from history

### Phase 4: Stacking Graph
- [ ] Create StackingState TypedDict
- [ ] Implement program_loop_node (generic FOR EACH loop)
- [ ] Implement user_question_node (material composition)
- [ ] Implement supervisor_qa_node
- [ ] Implement generate_output_node
- [ ] Wire up graph with LangGraph edges

### Phase 5: Integration & Testing
- [ ] Test with USB-C cable example end-to-end
- [ ] Verify all decisions trace to source documents
- [ ] Add to Gradio UI as new mode
- [ ] Create audit trail display
- [ ] Broker review with real examples

### Phase 6: Batch Update Job (Future)
- [ ] Create document watcher for new notices
- [ ] Create parser for different document types
- [ ] Create table update logic
- [ ] Create validation/consistency checks

---

## 9. Key Design Decisions

### Deterministic vs LLM
| Component | Approach | Why |
|-----------|----------|-----|
| Program lookup | **Deterministic** (table query) | tariff_programs table |
| HTS inclusion check | **Deterministic** (table query) | Exact 8-digit match |
| Exclusion match | **LLM** (semantic) | Description requires fuzzy matching |
| Material composition | **User input** or history | Can't reliably infer |
| Filing order | **Deterministic** (filing_sequence column) | Stored in table |
| Dependency resolution | **Deterministic** (condition_type parsing) | Logic from table |
| Duty calculation | **Deterministic** (duty_rules table) | Must be exact |
| Output codes | **Deterministic** (program_codes table) | Direct lookup |
| Plain English | **LLM** | Natural language generation |

### Real-time vs Batch
| Task | Timing | Why |
|------|--------|-----|
| Parse government notices | **Nightly batch** | Infrequent changes |
| Update tables | **Nightly batch** | Extension notices, new lists |
| Query tariff_programs | **Real-time** | Fast table lookup |
| Query inclusion/exclusion | **Real-time** | Fast table lookup |
| Semantic exclusion match | **Real-time** | LLM call, but fast |
| Ask user questions | **Real-time** | Interactive |
| Calculate duties | **Real-time** | Immediate response |

### Why Tables Over PDFs?
| Querying PDFs (RAG) | Querying Tables |
|---------------------|-----------------|
| Slower (vector search + LLM) | Fast (SQL query) |
| Probabilistic results | Deterministic results |
| Hard to audit | Easy to audit (show row) |
| Can't guarantee exact match | Guaranteed exact match |
| Updates require re-indexing | Updates are simple INSERTs |

**RAG is only used for:**
1. Semantic matching of exclusion descriptions
2. Generating plain English explanations

---

## 10. Questions to Clarify with Broker (Wednesday)

1. What is the exact CBP filing order for tariffs?
2. Are there dependencies between tariffs (e.g., 301 affects IEEPA rate)?
3. How do partial material percentages affect compound tariffs?
4. What format does the final filing output need to be in?
5. Are there other tariff programs beyond 301, 232, IEEPA we need now?
6. How do exclusion descriptions get matched in practice?

---

## 11. Success Criteria

**MVP Success:**
- Given HTS `8544.42.9090` + Country `China` + Composition `{copper: 5%, steel: 20%, aluminum: 72%, zinc: 3%}`
- Output correct filing lines in correct order
- Calculate correct total duty
- Provide plain English explanation for each line
- Show sources/citations for each decision

**Time Savings:**
- Current: 45-60 minutes per complex entry
- Target: 5 minutes (including user confirmation)

---

## 12. Critical Files to Create/Modify

### New Files
```
app/
├── chat/
│   ├── tools/
│   │   └── stacking_tools.py       # 8 new data-driven tools
│   ├── graphs/
│   │   └── stacking_rag.py         # Stacking agent graph
│   ├── prompts/
│   │   └── stacking_prompts.py     # Prompts for exclusion matching, explanations
│   └── output_schemas.py           # Add StackingOutput, FilingLine, Decision
│
├── web/
│   └── db/
│       └── models/
│           └── tariff_tables.py    # SQLAlchemy models for tariff tables
│
scripts/
├── populate_tariff_tables.py       # One-time script to populate tables from PDFs
├── gradio_app.py                   # Add stacking mode to UI
│
instance/
└── tariff_data.db                  # SQLite database with tariff tables
```

### Modified Files
```
app/chat/__init__.py                # Export build_stacking_chat()
app/chat/chat.py                    # Add build_stacking_chat() entry point
scripts/gradio_app.py               # Add Stacking tab/mode
```

### Government Documents Needed
```
docs/
├── section_301/
│   ├── list_1_34B.pdf
│   ├── list_2_16B.pdf
│   ├── list_3_200B.pdf
│   ├── list_4a_120B.pdf
│   └── exclusions_frn.pdf
├── section_232/
│   ├── steel_proclamation.pdf
│   ├── aluminum_proclamation.pdf
│   └── copper_proclamation.pdf
└── ieepa/
    └── fentanyl_notice.pdf
```

---

## 13. Complete USB-C Cable Walkthrough

**This is exactly how the algorithm runs for our test case.**

### Input
```python
state = {
    "hts_code": "8544.42.9090",
    "country": "China",
    "import_date": "2024-12-07",
    "product_description": "USB-C cable, insulated electrical conductor",
    "product_value": 1000.00,
    "materials": None,  # Unknown at start
}
```

### Step 1: lookup_product_history("8544.42.9090", "USB-C cable")
```
→ Found prior USB-C imports
→ Suggests: copper, steel, aluminum likely
→ state["materials"] still None (will ask user)
```

### Step 2: get_applicable_programs("China", "8544.42.9090", "2024-12-07")
```
Returns (sorted by filing_sequence):
[
  {program_id: "section_301", check_type: "hts_lookup", condition_handler: "none", ...},
  {program_id: "ieepa_fentanyl", check_type: "always", condition_handler: "none", ...},
  {program_id: "ieepa_reciprocal", check_type: "always", condition_handler: "handle_dependency", condition_param: "section_232", ...},
  {program_id: "section_232_copper", check_type: "hts_lookup", condition_handler: "handle_material_composition", condition_param: "copper", ...},
  {program_id: "section_232_steel", check_type: "hts_lookup", condition_handler: "handle_material_composition", condition_param: "steel", ...},
  {program_id: "section_232_aluminum", check_type: "hts_lookup", condition_handler: "handle_material_composition", condition_param: "aluminum", ...},
]
```

### Step 3: Loop through each program

#### Program 1: section_301
```
3a. check_program_inclusion("section_301", "8544.42.9090")
    → Query section_301_inclusions WHERE hts_8digit = "8544.42"
    → FOUND in list_3
    → Decision: "Included - HTS 8544.42 is in Section 301 List 3"

3b. check_program_exclusion("section_301", "8544.42.9090", "USB-C cable", "2024-12-07")
    → Query section_301_exclusions WHERE hts_8digit = "8544.42" AND extended_to > "2024-12-07"
    → No matching exclusions for USB-C cables
    → Decision: "No exclusion applies"

3c. condition_handler = "none"
    → action = "apply"

3d. get_program_output("section_301", "apply")
    → chapter_99_code: "9903.88.03", duty_rate: 0.25
    → Append FilingLine(sequence=1, code="9903.88.03", program="Section 301", action="apply", duty=25%)
```

#### Program 2: ieepa_fentanyl
```
3a. check_type = "always"
    → Skip inclusion check, treat as included
    → Decision: "Always applies to China imports"

3b. No exclusion_table
    → Skip

3c. condition_handler = "none"
    → action = "apply"

3d. get_program_output("ieepa_fentanyl", "apply")
    → chapter_99_code: "9903.01.24", duty_rate: X%
    → Append FilingLine(sequence=2, code="9903.01.24", program="IEEPA Fentanyl", action="apply")
```

#### Program 3: ieepa_reciprocal
```
3a. check_type = "always"
    → Skip inclusion check

3b. No exclusion_table
    → Skip

3c. condition_handler = "handle_dependency", condition_param = "section_232"
    → Call resolve_program_dependencies("ieepa_reciprocal", state["program_results"])
    → Check if any section_232_* has claims
    → We haven't processed 232 yet, so DEFER this program
    → (Or: process after 232 programs)
```

#### Program 4: section_232_copper
```
3a. check_program_inclusion("section_232_copper", "8544.42.9090")
    → Query section_232_materials WHERE hts_8digit = "8544.42" AND material = "copper"
    → FOUND
    → Decision: "HTS 8544.42 is subject to 232 copper tariff"

3b. No exclusion_table for 232
    → Skip

3c. condition_handler = "handle_material_composition", condition_param = "copper"
    → First: ensure_materials(state)
       → state["materials"] is None, so ASK USER:
         "Does this product contain copper? What percentage?"
       → User answers: copper=5%, steel=20%, aluminum=72%, zinc=3%
       → Update state["materials"] = {copper: 0.05, steel: 0.20, aluminum: 0.72, zinc: 0.03}
    → Then: check_material_composition("8544.42.9090", {copper: 0.05})
       → Copper present at 5%
       → action = "claim", applies_to = "partial (5%)"

3d. get_program_output("section_232_copper", "claim")
    → chapter_99_code: "9903.78.01", duty_rate: 0.25
    → Append FilingLine(sequence=4, code="9903.78.01", program="232 Copper", action="claim", applies_to="5%")
```

#### Program 5: section_232_steel
```
3a. check_program_inclusion → FOUND

3c. condition_handler = "handle_material_composition"
    → Materials already known from step 4
    → steel = 20%
    → action = "claim", applies_to = "partial (20%)"

3d. get_program_output("section_232_steel", "claim")
    → chapter_99_code: "9903.83.01"
    → Append FilingLine(sequence=5, code="9903.83.01", program="232 Steel", action="claim", applies_to="20%")
```

#### Program 6: section_232_aluminum
```
3a. check_program_inclusion → FOUND

3c. condition_handler = "handle_material_composition"
    → aluminum = 72%
    → action = "claim", applies_to = "partial (72%)"

3d. get_program_output("section_232_aluminum", "claim")
    → chapter_99_code: "9903.85.08"
    → Append FilingLine(sequence=6, code="9903.85.08", program="232 Aluminum", action="claim", applies_to="72%")
```

#### Back to Program 3: ieepa_reciprocal (deferred)
```
3c. condition_handler = "handle_dependency"
    → resolve_program_dependencies("ieepa_reciprocal", state["program_results"])
    → Checks: section_232_copper=claim, section_232_steel=claim, section_232_aluminum=claim
    → At least one 232 claim exists
    → action = "paid"

3d. get_program_output("ieepa_reciprocal", "paid")
    → chapter_99_code: "9903.01.33"
    → Append FilingLine(sequence=3, code="9903.01.33", program="IEEPA Reciprocal", action="paid")
```

### Step 4: calculate_duties(filing_lines, 1000.00, materials)
```
Query duty_rules for each program, apply calculations:

1. Base MFN duty on HTS 8544.42.9090: 3.9%
2. Section 301 (25%): additive on full value
3. IEEPA Fentanyl (X%): additive on full value
4. IEEPA Reciprocal: depends on 232 claims (already factored)
5. 232 Copper (25%): on_portion, 5% of value
6. 232 Steel (25%): on_portion, 20% of value
7. 232 Aluminum (10%): on_portion, 72% of value

Total calculation...
```

### Step 5: Supervisor QA
```
✓ All 6 programs processed
✓ All have decisions with sources
✓ Math checks out
✓ No flags
```

### Step 6: Final Output
```python
StackingOutput(
    hts_code="8544.42.9090",
    country_of_origin="China",
    materials={copper: 0.05, steel: 0.20, aluminum: 0.72, zinc: 0.03},

    filing_lines=[
        FilingLine(sequence=1, code="9903.88.03", program="Section 301", action="apply", applies_to="full", duty_rate=0.25),
        FilingLine(sequence=2, code="9903.01.24", program="IEEPA Fentanyl", action="apply", applies_to="full"),
        FilingLine(sequence=3, code="9903.01.33", program="IEEPA Reciprocal", action="paid", applies_to="full"),
        FilingLine(sequence=4, code="9903.78.01", program="232 Copper", action="claim", applies_to="partial (5%)", duty_rate=0.25),
        FilingLine(sequence=5, code="9903.83.01", program="232 Steel", action="claim", applies_to="partial (20%)", duty_rate=0.25),
        FilingLine(sequence=6, code="9903.85.08", program="232 Aluminum", action="claim", applies_to="partial (72%)", duty_rate=0.10),
    ],

    decisions=[
        Decision(step="section_301", decision="apply", reason="HTS 8544.42 in List 3", source_doc="200B_List.pdf", source_page=47),
        Decision(step="section_301_exclusion", decision="not excluded", reason="No matching exclusion for USB-C cables"),
        Decision(step="ieepa_fentanyl", decision="apply", reason="Country=China, always applies"),
        Decision(step="section_232_copper", decision="claim 5%", reason="User confirmed copper content", source_doc="user_input"),
        # ... etc
    ],

    total_duty_percent=XX.X,
    confidence="high",
    flags=[]
)
```

### What the Broker Sees
```
PRIMARY: 8544.42.9090

FILING SEQUENCE:
1. 9903.88.03 → Section 301 (25% on full value)
2. 9903.01.24 → IEEPA Fentanyl
3. 9903.01.33 → IEEPA Reciprocal (Paid - because claiming 232)
4. 9903.78.01 → 232 Copper (Claim - 5% of value)
5. 9903.83.01 → 232 Steel (Claim - 20% of value)
6. 9903.85.08 → 232 Aluminum (Claim - 72% of value)

TOTAL DUTY: XX.X%

WHY EACH APPLIES:
- Section 301: HTS 8544.42 is in List 3 (source: 200B Trade Action, page 47)
- No exclusion found for "USB-C cable" description
- IEEPA Fentanyl: Always applies to China imports
- IEEPA Reciprocal: Paid because claiming 232 materials
- 232 Copper: User confirmed 5% copper content
- 232 Steel: User confirmed 20% steel content
- 232 Aluminum: User confirmed 72% aluminum content
```

**This is exactly what your broker does manually in 45-60 minutes. We do it in 5 minutes with full audit trail.**
