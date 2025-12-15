# Lanes - Stacking Feature Implementation (v3.0)

## Summary

Build a **Tariff Stacking Calculator** that takes an HTS code + Country of Origin and outputs the complete CBP filing sequence with calculated duties and full audit trail.

**Design Principle:** Rule templates as code, parameters as data. The orchestrator loop stays **tiny and generic**. All program-specific logic lives in **data (tables)**, not code.

**Status:** Phases 1-6.5 complete. IEEPA Unstacking implemented - Section 232 content is excluded from IEEPA Reciprocal base.

---

## Architecture Philosophy

### Three-Layer Separation

| Layer | What | When | LLM Role |
|-------|------|------|----------|
| **1. Truth Source** | CBP/law documents | Offline/ingestion | LLM parses docs → DB |
| **2. Rules DB** | Parameters as data, templates as code | Stored | None (just data) |
| **3. Runtime Engine** | Deterministic tool execution | Per-request | LLM = orchestrator only |

### Key Principle: Rule Templates as Code, Parameters as Data

**DON'T** encode every rule as code:
```python
# BAD - doesn't scale
if program == "232_copper" and year >= 2025:
    split_lines = True
    rate = 0.50
```

**DO** encode generic shapes in code, parameters in DB:
```python
# GOOD - scales to any program/country/material
def should_split_lines(total_value: float, content_value: float,
                       split_policy: str, split_threshold_pct: float) -> bool:
    if content_value is None or content_value <= 0:
        return False
    if content_value >= total_value:
        return False

    if split_policy == "never":
        return False
    elif split_policy == "if_any_content":
        return True
    elif split_policy == "if_above_threshold":
        return (content_value / total_value) >= (split_threshold_pct or 0)

    return False
```

### LLM Roles

| Context | LLM Does | LLM Does NOT |
|---------|----------|--------------|
| **Ingestion** | Parse CBP docs, extract structured rules, update DB | Decide law |
| **Runtime** | Choose tools, ask user questions, explain results | Override DB rules |

---

## Current Tariff Rates (December 2025)

| Program | Rate | Chapter 99 Code | Source |
|---------|------|-----------------|--------|
| Base Duty (HTS 8544.42.90.90) | 2.6% | - | [USITC HTS](https://hts.usitc.gov/) |
| Section 301 (List 3) | **25%** | 9903.88.03 | [USTR](https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions) |
| Section 232 Steel | **50%** | 9903.80.01 | [CBP](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs) |
| Section 232 Aluminum | **25%** | 9903.85.08 | [CBP](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs) |
| Section 232 Copper | **50%** | 9903.78.01 | [CBP CSMS #65794272](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ebf0e0) |
| IEEPA Fentanyl | **10%** | 9903.01.25 | [CBP IEEPA FAQ](https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ) |
| IEEPA Reciprocal (paid) | **10%** | 9903.01.33 | CBP IEEPA FAQ |
| IEEPA Reciprocal (disclaim) | 0% | 9903.01.25 | CBP IEEPA FAQ |

### Rate Changes in 2025

| Date | Change | Source |
|------|--------|--------|
| Mar 12, 2025 | Steel 232: 25% → 50%, Aluminum 232: 10% → 25% | Proclamations 10895/10896 |
| Jul 31, 2025 | Copper 232: 25% → **50%** | CBP CSMS #65794272 |
| Nov 10, 2025 | IEEPA Fentanyl: 20% → 10% (US-China deal) | White House EO |

---

## IEEPA Fentanyl vs IEEPA Reciprocal

Two distinct IEEPA programs with different behaviors:

| Program | base_on | base_effect | Behavior |
|---------|---------|-------------|----------|
| **IEEPA Fentanyl** | `product_value` | NULL | Always 10% on full value |
| **IEEPA Reciprocal** | `remaining_value` | NULL | 10% on value AFTER 232 deductions |

### Why the Difference?

**IEEPA Fentanyl** applies to the entire product regardless of material composition.

**IEEPA Reciprocal** follows the CBP rule:
> "Content subject to Section 232 is NOT subject to Reciprocal IEEPA"

This means 232 metal content must be subtracted from the IEEPA Reciprocal base.

### Engine Logic

```python
remaining_value = product_value

# For each 232 program (base_on='content_value' + base_effect='subtract_from_remaining'):
remaining_value -= content_value

# For IEEPA Reciprocal (base_on='remaining_value'):
duty = remaining_value * rate
```

---

## Canonical Example: USB-C Cable from China ($10,000)

**This example is used consistently throughout the documentation.**

> **Note:** For simplicity, we ignore MFN base duty (2.6%) in this example. We focus only on 301, 232, and IEEPA programs. In a real calculation, you'd add $260 to the total.

### Material Composition

| Material | Percentage | Value | Mass (kg) |
|----------|------------|-------|-----------|
| Copper | 30% | $3,000 | 40 |
| Steel | 10% | $1,000 | 10 |
| Aluminum | 10% | $1,000 | 10 |
| Other (plastic, etc.) | 50% | $5,000 | 20 |
| **Total** | 100% | $10,000 | 80 |

### Filing Lines (9 total with line splitting)

```
HTS 8544.42.9090 from China - $10,000 value

1. 9903.88.03 → Section 301 (apply, 25% on $10,000)           = $2,500
2. 9903.01.25 → IEEPA Fentanyl (apply, 10% on $10,000)        = $1,000
3. 9903.78.02 → 232 Non-Copper Content (disclaim, 0%)         = $0
4. 9903.78.01 → 232 Copper Content (claim, 50% on $3,000)     = $1,500
5. 9903.80.02 → 232 Non-Steel Content (disclaim, 0%)          = $0
6. 9903.80.01 → 232 Steel Content (claim, 50% on $1,000)      = $500
7. 9903.85.09 → 232 Non-Aluminum Content (disclaim, 0%)       = $0
8. 9903.85.08 → 232 Aluminum Content (claim, 25% on $1,000)   = $250
9. 9903.01.33 → IEEPA Reciprocal (paid, 10% on $5,000)        = $500
                                                        ─────────────
                                        TOTAL DUTY:           $6,250
                                        EFFECTIVE RATE:       62.5%
```

### IEEPA Unstacking Calculation

```
Initial product_value:          $10,000

After 232 Copper claim:         $10,000 - $3,000 = $7,000
After 232 Steel claim:          $7,000 - $1,000 = $6,000
After 232 Aluminum claim:       $6,000 - $1,000 = $5,000

remaining_value for IEEPA:      $5,000

IEEPA Reciprocal duty:          $5,000 × 10% = $500
```

**WITHOUT unstacking (incorrect):**
```
IEEPA Reciprocal:               $10,000 × 10% = $1,000  ← $500 OVERCHARGE!
```

---

## Section 232 Content-Based Duty Rules

**Source:** CBP CSMS #65794272 (July 31, 2025) + Proclamations 10895/10896

### What Changed in Dec 2025

| Aspect | Old Design | New Requirement |
|--------|-----------|-----------------|
| **Duty Basis** | Material percentage × rate | Material content **VALUE** × rate |
| **Filing Lines** | 1 line per material | 2 lines: non-material + material content |
| **Fallback** | None | If value unknown → charge on **FULL value** |
| **Copper Rate** | 25% | **50%** |

### Line Splitting Requirement

For each 232 material, generate TWO filing lines:

**Line A - Non-Material Content:**
- Entered value = `total_value - material_value`
- Use disclaim code (0% duty)
- Report full product quantity

**Line B - Material Content:**
- Entered value = `material_value`
- Use claim code (duty rate applies)
- Report kg of material for 9903 line

> **Important:** The non-material 232 "disclaim" lines are for CBP reporting only. Section 301 and IEEPA calculations use `product_value` / `remaining_value`, not the `line_value` from disclaim lines. The IEEPA unstacking only subtracts on `material_content` lines to prevent double-counting.

### Fallback Rule (Critical!)

> "If the value of copper content cannot be determined, you must base 232 on the full entered value" - CBP CSMS #65794272

This is a **penalty case**. If content value is unknown, duty is charged on the entire product value.

---

## Data Architecture

### tariff_programs (Master Table)

Defines what programs exist and when they apply.

```sql
CREATE TABLE tariff_programs (
    program_id          VARCHAR PRIMARY KEY,
    program_name        VARCHAR,
    country             VARCHAR,              -- "China", "ALL", etc.
    check_type          VARCHAR,              -- "hts_lookup", "always"
    condition_handler   VARCHAR,              -- "none", "handle_material_composition", "handle_dependency"
    condition_param     VARCHAR,              -- NULL, or "section_232" for dependencies
    inclusion_table     VARCHAR,
    exclusion_table     VARCHAR,
    filing_sequence     INT,                  -- Order in CBP filing
    source_document     VARCHAR,
    effective_date      DATE,
    expiration_date     DATE
);
```

**IMPORTANT: Filing Sequence Order**

For unstacking to work, 232 programs MUST run BEFORE IEEPA Reciprocal:

| program_id | country | filing_sequence |
|------------|---------|-----------------|
| section_301 | China | 1 |
| ieepa_fentanyl | China | 2 |
| section_232_copper | ALL | 3 |
| section_232_steel | ALL | 4 |
| section_232_aluminum | ALL | 5 |
| ieepa_reciprocal | China | 6 |

This ensures:
1. 301 and Fentanyl apply to full product_value
2. 232 programs deduct from remaining_value
3. IEEPA Reciprocal sees the reduced remaining_value

### section_232_materials

```sql
CREATE TABLE section_232_materials (
    hts_8digit          VARCHAR,
    material            VARCHAR,              -- "copper", "steel", "aluminum"
    claim_code          VARCHAR,              -- "9903.78.01"
    disclaim_code       VARCHAR,              -- "9903.78.02"
    duty_rate           DECIMAL,
    source_doc          VARCHAR,
    content_basis       VARCHAR DEFAULT 'value',
    quantity_unit       VARCHAR DEFAULT 'kg',
    split_policy        VARCHAR DEFAULT 'if_any_content',
    split_threshold_pct DECIMAL,
    PRIMARY KEY (hts_8digit, material)
);
```

**Example data:**

| hts_8digit | material | claim_code | disclaim_code | duty_rate | split_policy |
|------------|----------|------------|---------------|-----------|--------------|
| 85444290 | copper | 9903.78.01 | 9903.78.02 | 0.50 | if_any_content |
| 85444290 | steel | 9903.80.01 | 9903.80.02 | 0.50 | if_any_content |
| 85444290 | aluminum | 9903.85.08 | 9903.85.09 | 0.25 | if_any_content |

### duty_rules (With IEEPA Unstacking)

```sql
CREATE TABLE duty_rules (
    program_id          VARCHAR PRIMARY KEY,
    calculation_type    VARCHAR,              -- "additive", "compound", "on_portion"
    base_on             VARCHAR,              -- "product_value", "content_value", "remaining_value"
    compounds_with      VARCHAR,
    source_doc          VARCHAR,
    content_key         VARCHAR,              -- 'copper', 'steel', 'aluminum'
    fallback_base_on    VARCHAR,              -- 'full_value' if content value unknown
    base_effect         VARCHAR               -- 'subtract_from_remaining' for 232 programs
);
```

**Example data:**

| program_id | calculation_type | base_on | content_key | fallback_base_on | base_effect |
|------------|------------------|---------|-------------|------------------|-------------|
| section_301 | additive | product_value | NULL | NULL | NULL |
| ieepa_fentanyl | additive | product_value | NULL | NULL | NULL |
| section_232_copper | on_portion | content_value | copper | full_value | subtract_from_remaining |
| section_232_steel | on_portion | content_value | steel | full_value | subtract_from_remaining |
| section_232_aluminum | on_portion | content_value | aluminum | full_value | subtract_from_remaining |
| ieepa_reciprocal | additive | remaining_value | NULL | NULL | NULL |

**Key Design Points:**
- Section 232 programs: `base_effect = 'subtract_from_remaining'` reduces IEEPA base
- IEEPA Reciprocal: `base_on = 'remaining_value'` uses reduced base
- IEEPA Fentanyl: `base_on = 'product_value'` always uses full value

---

## Tool Call Sequence

```
Step 0: Input + import_date
    └── Collect HTS, country, description, value, import_date

Step 1: lookup_product_history()
    └── Pre-fill materials if high-confidence prior data

Step 2: get_applicable_programs(country, hts_code, import_date)
    └── Returns programs sorted by filing_sequence
    └── CRITICAL: 232 programs before ieepa_reciprocal

Step 3: FOR EACH program (sorted by filing_sequence):
    │
    ├── 3a. check_program_inclusion(program_id, hts_code)
    │       └── If not included → SKIP
    │
    ├── 3b. check_program_exclusion(program_id, hts_code, description)
    │       └── If excluded → SKIP
    │
    ├── 3c. Handle condition (based on condition_handler):
    │       └── "none" → action = "apply"
    │       └── "handle_material_composition":
    │           └── check_material_composition()
    │           └── Generate split lines if split_policy applies
    │       └── "handle_dependency":
    │           └── resolve_program_dependencies()
    │
    └── 3d. get_program_output(program_id, action)
            └── Append FilingLine(s) to state["filing_lines"]

Step 4: calculate_duties(filing_lines, product_value, material_values)
    └── Track remaining_value (starts at product_value)
    └── For 232 programs: remaining_value -= content_value
    └── For IEEPA Reciprocal: use remaining_value as base

Step 5: Output + save to product_history
```

---

## calculate_duties() Implementation

```python
def calculate_duties(filing_lines, product_value, material_values):
    remaining_value = product_value  # Initialize
    total_duty = 0.0
    content_deductions = {}
    processed_materials = set()  # Prevent double-subtraction for split lines

    for line in filing_lines:
        rule = get_duty_rule(line.program_id)

        if line.action in ['disclaim', 'skip']:
            duty = 0.0  # No duty on disclaim lines

        elif rule.base_on == 'product_value':
            # Section 301, IEEPA Fentanyl
            duty = product_value * line.duty_rate

        elif rule.base_on == 'content_value':
            # Section 232 programs (material_content lines only)
            content_value = material_values.get(rule.content_key)
            duty = content_value * line.duty_rate

            # Subtract from remaining for IEEPA unstacking
            # IMPORTANT: Only on material_content lines, not non_material_content!
            should_subtract = (
                rule.base_effect == 'subtract_from_remaining'
                and line.split_type in (None, 'material_content')
                and rule.content_key not in processed_materials
            )
            if should_subtract:
                remaining_value -= content_value
                content_deductions[rule.content_key] = content_value
                processed_materials.add(rule.content_key)

        elif rule.base_on == 'remaining_value':
            # IEEPA Reciprocal - use reduced base
            duty = remaining_value * line.duty_rate

        total_duty += duty

    return {
        "total_duty": total_duty,
        "unstacking": {
            "initial_value": product_value,
            "content_deductions": content_deductions,
            "remaining_value": remaining_value
        }
    }
```

**Key safeguards against double-subtraction:**
1. Only subtract on `material_content` lines (not `non_material_content` disclaim lines)
2. Track `processed_materials` to ensure each material is only subtracted once
3. Disclaim lines are handled early with `duty = 0` before any content_value logic

---

## Output Schema (v3.0)

```python
class StackingOutput(BaseModel):
    schema_version: str = "3.0"

    # Input
    hts_code: str
    country_of_origin: str
    product_description: str
    product_value: float
    materials: Dict[str, MaterialInfo]

    # Filing Lines
    filing_lines: List[FilingLine]

    # Calculations
    total_duty_percent: float
    total_duty_amount: float
    duty_breakdown: List[DutyBreakdown]

    # IEEPA Unstacking (Phase 6.5)
    unstacking: Optional[UnstackingInfo]

    # Audit Trail
    decisions: List[Decision]
    citations: List[SourceCitation]
    flags: List[str]  # e.g., ["fallback_applied_for_copper"]

class UnstackingInfo(BaseModel):
    initial_value: float
    content_deductions: Dict[str, float]  # {"copper": 3000, "steel": 1000, ...}
    remaining_value: float
    note: str
```

---

## Database Migration (Complete)

Run this migration to set up all Phase 6 and 6.5 features:

```sql
-- ============================================================================
-- Phase 6: Content-Based Duties
-- ============================================================================

-- section_232_materials: Add content-based duty columns
ALTER TABLE section_232_materials ADD COLUMN content_basis VARCHAR DEFAULT 'value';
ALTER TABLE section_232_materials ADD COLUMN quantity_unit VARCHAR DEFAULT 'kg';
ALTER TABLE section_232_materials ADD COLUMN split_policy VARCHAR DEFAULT 'if_any_content';
ALTER TABLE section_232_materials ADD COLUMN split_threshold_pct DECIMAL;

-- Update copper rate to 50%
UPDATE section_232_materials SET duty_rate = 0.50 WHERE material = 'copper';

-- duty_rules: Add content-based duty columns
ALTER TABLE duty_rules ADD COLUMN content_key VARCHAR;
ALTER TABLE duty_rules ADD COLUMN fallback_base_on VARCHAR;

-- Set 232 programs to use content_value
UPDATE duty_rules SET base_on = 'content_value', fallback_base_on = 'full_value'
WHERE program_id LIKE 'section_232_%';
UPDATE duty_rules SET content_key = 'copper' WHERE program_id = 'section_232_copper';
UPDATE duty_rules SET content_key = 'steel' WHERE program_id = 'section_232_steel';
UPDATE duty_rules SET content_key = 'aluminum' WHERE program_id = 'section_232_aluminum';

-- ============================================================================
-- Phase 6.5: IEEPA Unstacking
-- ============================================================================

-- duty_rules: Add unstacking column
ALTER TABLE duty_rules ADD COLUMN base_effect VARCHAR;

-- 232 programs subtract their content from remaining_value
UPDATE duty_rules SET base_effect = 'subtract_from_remaining'
WHERE program_id LIKE 'section_232_%';

-- IEEPA Reciprocal uses remaining_value (after 232 deductions)
UPDATE duty_rules SET base_on = 'remaining_value'
WHERE program_id = 'ieepa_reciprocal';

-- ============================================================================
-- Fix filing_sequence: 232 must run BEFORE ieepa_reciprocal
-- ============================================================================

UPDATE tariff_programs SET filing_sequence = 1 WHERE program_id = 'section_301';
UPDATE tariff_programs SET filing_sequence = 2 WHERE program_id = 'ieepa_fentanyl';
UPDATE tariff_programs SET filing_sequence = 3 WHERE program_id = 'section_232_copper';
UPDATE tariff_programs SET filing_sequence = 4 WHERE program_id = 'section_232_steel';
UPDATE tariff_programs SET filing_sequence = 5 WHERE program_id = 'section_232_aluminum';
UPDATE tariff_programs SET filing_sequence = 6 WHERE program_id = 'ieepa_reciprocal';
```

---

## Implementation Status

### Phase 1-5: COMPLETED
- Database schema and tables created
- Tables populated with sample data
- Core tools implemented
- Stacking graph working
- Basic tests passing

### Phase 6: Content-Based Duties - COMPLETED
- [x] Line splitting for 232 materials (2 lines per material)
- [x] Content-value-based duty calculation
- [x] Copper rate updated to 50%
- [x] `should_split_lines()` implemented
- [x] Fallback to full_value when content unknown

### Phase 6.5: IEEPA Unstacking - COMPLETED
- [x] Added `base_effect` column to duty_rules
- [x] 232 programs: `base_effect = 'subtract_from_remaining'`
- [x] IEEPA Reciprocal: `base_on = 'remaining_value'`
- [x] Updated filing_sequence (232 before reciprocal)
- [x] Added unstacking audit trail to output
- [x] Test cases updated with new expectations

### Phase 7: Government Document Sources - NEXT
- [ ] Add document watcher for new CBP notices
- [ ] Create parser for different document types
- [ ] Automate table updates from official sources

---

## Files Modified in Phase 6/6.5

| File | Changes |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Added `base_effect` column to DutyRule |
| `scripts/populate_tariff_tables.py` | Updated duty_rules with unstacking config, fixed filing_sequence |
| `app/chat/tools/stacking_tools.py` | Added `remaining_value` tracking in calculate_duties |
| `app/chat/graphs/stacking_rag.py` | Added unstacking display in output |
| `app/chat/output_schemas.py` | Added UnstackingInfo, MaterialInfo |
| `tests/test_stacking_automated.py` | Added Test Case 5 for IEEPA Unstacking |

---

## Key Design Decisions

### Deterministic vs LLM

| Component | Approach | Why |
|-----------|----------|-----|
| Program lookup | **Deterministic** | Query tariff_programs table |
| HTS inclusion | **Deterministic** | Exact 8-digit match |
| Exclusion match | **LLM** | Semantic description matching |
| Material composition | **User input** | Can't reliably infer |
| Filing order | **Deterministic** | filing_sequence column |
| Line splitting | **Deterministic** | split_policy column |
| Duty calculation | **Deterministic** | duty_rules table |
| IEEPA unstacking | **Deterministic** | remaining_value tracking |

### Why Tables Over PDFs?

| Querying PDFs (RAG) | Querying Tables |
|---------------------|-----------------|
| Slower (vector search + LLM) | Fast (SQL query) |
| Probabilistic results | Deterministic results |
| Hard to audit | Easy to audit (show row) |
| Can't guarantee exact match | Guaranteed exact match |

---

## Success Criteria

**Given:**
- HTS: `8544.42.9090` (USB-C cable)
- Country: `China`
- Materials: `{copper: $3,000, steel: $1,000, aluminum: $1,000}`
- Product value: `$10,000`

**Expected Output:**
- 9 filing lines (3 materials × 2 split lines + 301 + Fentanyl + Reciprocal)
- Total duty: `$6,250` (62.5% effective rate)
- IEEPA Reciprocal on `$5,000` remaining_value (not $10,000)
- Unstacking audit trail showing content deductions

**Time Savings:**
- Current: 45-60 minutes per complex entry
- Target: 5 minutes (including material value input)
