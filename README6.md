# Lanes - Stacking Feature Implementation Plan (v2.0)

## Summary

Build a **Tariff Stacking Calculator** that takes an HTS code + Country of Origin and outputs the complete CBP filing sequence with calculated duties and full audit trail.

**Design Principle:** Rule templates as code, parameters as data. The orchestrator loop stays **tiny and generic**. All program-specific logic lives in **data (tables)**, not code.

**Status:** Phases 1-6.5 complete. Phase 6.5 implemented IEEPA Unstacking - Section 232 content is excluded from IEEPA Reciprocal base.

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
    """
    Generic function - doesn't know about copper/steel/aluminum.
    All specifics come from the DB row for that material.

    If CBP changes the rule in future, we update DB data, not this code.
    """
    if content_value is None or content_value <= 0:
        return False
    if content_value >= total_value:
        return False  # All material, no split needed

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

**Key insight:** The LLM is allowed to decide *tool flow and UX* (when to ask for more info, how to explain results). It is **not** allowed to decide law/math - that's deterministic from the DB.

---

## Current Tariff Rates (December 2025)

**IMPORTANT:** These are REAL rates from government sources. Tariffs change frequently - see `docs/tariff_sources.md` for update sources.

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

## Section 232 Content-Based Duty Rules (Dec 2025)

**Source:** CBP CSMS #65794272 (July 31, 2025) + Proclamations 10895/10896

### What Changed

The new Section 232 guidance fundamentally changes how material-based tariffs work:

| Aspect | Old Design | New Requirement |
|--------|-----------|-----------------|
| **Duty Basis** | Material percentage × rate | Material content **VALUE** × rate |
| **Filing Lines** | 1 line per material | 2 lines: non-material + material content |
| **Fallback** | None | If value unknown → charge on **FULL value** |
| **Copper Rate** | 25% | **50%** |
| **Quantity** | Product quantity | Material content line: kg of material |

### Line Splitting Requirement

For copper (and similar for steel/aluminum):

**Line 1 - Non-Copper Content:**
- Same HTS code, same country
- Entered value = `total_value - copper_value`
- Report full quantity
- Use disclaim code: `9903.78.02` (0% duty)
- Still subject to: Section 301, IEEPA, AD/CVD

**Line 2 - Copper Content:**
- Same HTS code, same country
- Entered value = `copper_value`
- Base HTS quantity = 0
- 9903 line reports kg of copper
- Use claim code: `9903.78.01` (50% duty on copper value)
- Still subject to: Section 301, IEEPA, AD/CVD

### Current US 232 Split Behavior

We set `split_policy = 'if_any_content'` in the database. This means:

> **We generate two lines whenever the product has some material content and some non-material content. There is no composition threshold; if `content_value > 0` and `content_value < total_value`, we split.**

The `split_threshold_pct` column exists for future rules / other jurisdictions that might require "only split if copper > X%", but **current US 232 rules don't use a threshold**.

### Why Is Line Splitting Needed?

**Two reasons:**

#### 1. Legal/Compliance Semantics

For content-based 232:
- The **material part** of the product is taxed at a 232 rate (e.g. 50% on copper content value)
- The **non-material part** is NOT subject to 232, but IS still subject to:
  - Normal MFN base duty
  - Section 301
  - IEEPA
  - AD/CVD, etc.

CBP's guidance (for steel and copper) basically says:
> When a product has both material and non-material content, the entry should show two lines to distinguish them.

If you only produce a single 232 line, you lose this representation:
- You can't separately account non-material vs material value
- You can't accurately trace how 232 was applied

#### 2. Engine / Math Clarity

Having two separate filing lines per material gives you:

**Clean math:**
- One line's 232 duty is always zero
- The other's is always `content_value × rate`

**Clean combination with other tariffs:**
- You can still apply 301, IEEPA, AD/CVD consistently to both lines

**Clean audit:**
- "Here's how we split $10,000 into $9,500 non-copper and $500 copper"
- "Here's where 50% 232 copper was applied"

### Generic Split Logic (Data-Driven)

The decision to split is **not hardcoded for copper/steel/aluminum**. It's generic:

```python
def should_split_lines(total_value: float,
                       content_value: float,
                       split_policy: str,
                       split_threshold_pct: float = None) -> bool:
    """
    Generic function - doesn't know about copper/steel/aluminum.
    All specifics come from the DB row for that material.
    """
    # No material or all material → nothing to split
    if content_value is None or content_value <= 0:
        return False
    if content_value >= total_value:
        return False

    if split_policy == "never":
        return False
    elif split_policy == "if_any_content":
        # Current US 232 behaviour: split whenever there is some material and some non-material
        return True
    elif split_policy == "if_above_threshold":
        return (content_value / total_value) >= (split_threshold_pct or 0)

    return False
```

**To adapt to rule changes:**
- New composition threshold (e.g. "only split if > 10%"):
  - Change DB row: `split_policy = 'if_above_threshold'`, `split_threshold_pct = 0.10`
  - Same `should_split_lines` function keeps working
- Another country's content tax (e.g. EU "carbon content" duty):
  - Add new program in `tariff_programs`
  - Add material rows in a `material_tariffs` table
  - Reuse exactly the same `check_material_composition` + `should_split_lines` + `calculate_duties`

### Line Splitting Implementation

When `split_lines=True` for a material, we generate TWO filing lines:

```python
if material_result.split_lines:
    # Line A – non-material content
    filing_lines.append(FilingLine(
        sequence=...,
        program_id=program_id,
        program="Section 232 Copper",
        action="disclaim",
        chapter_99_code=material_result.disclaim_code,  # e.g. 9903.78.02
        line_value=material_result.non_content_value,   # e.g. $9,500
        line_quantity=full_product_quantity,
        material=material_result.material,
        split_type="non_material_content",
        duty_rate=0.0,
    ))

    # Line B – material content
    filing_lines.append(FilingLine(
        sequence=...,
        program_id=program_id,
        program="Section 232 Copper",
        action="claim",
        chapter_99_code=material_result.claim_code,     # e.g. 9903.78.01
        line_value=material_result.content_value,       # e.g. $500
        line_quantity=0,  # if CBP wants qty in 99 line instead
        material=material_result.material,
        material_quantity_kg=material_result.content_mass_kg,
        split_type="material_content",
        duty_rate=material_result.duty_rate,            # e.g. 0.50
    ))
else:
    # Single line (100% material or no split_policy)
    filing_lines.append(...)
```

### Fallback Rule (Critical!)

> "If the value of copper content cannot be determined, you must base 232 on the full entered value" - CBP CSMS #65794272

This is a **penalty case**. Our system:
1. Asks user for material content VALUE (not just percentage)
2. Warns: "If you cannot provide copper content value, 50% will be charged on entire product value"
3. Stores `fallback_base_on = 'full_value'` in duty_rules

### Example Calculation: USB-C Cable from China ($10,000)

**NOTE:** These are illustrative example numbers to show the calculation flow, not legally accurate rates for any specific product.

```
Materials: copper 5% ($500 value), steel 20% ($2,000 value), aluminum 72% ($7,200 value)

Section 301:        $10,000 × 25% = $2,500
IEEPA Fentanyl:     $10,000 × 10% = $1,000

232 Copper (split_policy = 'if_any_content'):
├── Line 1: Non-Copper Content → 9903.78.02 (0% on $9,500)
└── Line 2: Copper Content → 9903.78.01 (50% on $500) = $250

232 Aluminum (split_policy = 'if_any_content'):
├── Line 1: Non-Aluminum Content → 9903.85.09 (0% on $2,800)
└── Line 2: Aluminum Content → 9903.85.08 (25% on $7,200) = $1,800

IEEPA Reciprocal:   $300 × 10% = $30 (on remaining_value after 232!)
─────────────────────────────────────────────
TOTAL DUTY:         $5,580 (55.8% effective rate)
```

**Note:** IEEPA Reciprocal is calculated on `remaining_value` ($300), not `product_value` ($10,000). See Phase 6.5 section below.

---

## Phase 6.5: IEEPA Unstacking (Dec 2025)

### The Problem We Discovered

Our Phase 6 implementation calculated IEEPA Reciprocal on the **full product value**:
```
IEEPA Reciprocal: $10,000 × 10% = $1,000  ← WRONG
```

But CBP guidance states:
> **"Content subject to Section 232 is NOT subject to Reciprocal IEEPA"**

The correct calculation requires **unstacking** - subtracting 232 content values first:
```
remaining_value = $10,000 - $3,000(Cu) - $1,000(Al) - $1,000(Steel) = $5,000
IEEPA Reciprocal: $5,000 × 10% = $500  ← CORRECT
```

### What Was Wrong (Before Phase 6.5)

```python
# duty_rules table - BEFORE
| program_id       | base_on        |
|------------------|----------------|
| ieepa_reciprocal | product_value  |  # Applied to FULL product value
```

### What We Fixed (After Phase 6.5)

```python
# duty_rules table - AFTER
| program_id            | base_on           | base_effect               |
|-----------------------|-------------------|---------------------------|
| section_232_copper    | content_value     | subtract_from_remaining   |
| section_232_steel     | content_value     | subtract_from_remaining   |
| section_232_aluminum  | content_value     | subtract_from_remaining   |
| ieepa_reciprocal      | remaining_value   | NULL                      |
```

### New Logic in calculate_duties()

```python
def calculate_duties(filing_lines, product_value, material_values):
    remaining_value = product_value  # Start with full value

    for program in programs:
        rule = get_duty_rule(program.program_id)

        if rule.base_on == 'content_value':
            # 232 metals - duty on content, subtract from remaining
            duty = content_value × rule.duty_rate
            if rule.base_effect == 'subtract_from_remaining':
                remaining_value -= content_value  # KEY CHANGE

        elif rule.base_on == 'remaining_value':
            # IEEPA Reciprocal - duty on what's left after 232 deductions
            duty = remaining_value × rule.duty_rate  # KEY CHANGE

        elif rule.base_on == 'product_value':
            # 301, IEEPA Fentanyl - duty on full value (unchanged)
            duty = product_value × rule.duty_rate
```

### Database Schema Changes

**duty_rules table** - Added column:
```sql
ALTER TABLE duty_rules ADD COLUMN base_effect VARCHAR;
-- Values: NULL, 'subtract_from_remaining'

-- 232 programs subtract their content from remaining value
UPDATE duty_rules SET base_effect = 'subtract_from_remaining'
WHERE program_id LIKE 'section_232_%';

-- IEEPA Reciprocal uses remaining value (after 232 subtractions)
UPDATE duty_rules SET base_on = 'remaining_value'
WHERE program_id = 'ieepa_reciprocal';
```

### Example: USB-C Cable with IEEPA Unstacking

**Product:** USB-C Cable from China, $10,000 total value

**Material composition (from research doc):**
- Copper: $3,000 (30%)
- Aluminum: $1,000 (10%)
- Steel: $1,000 (10%)
- Other: $5,000 (50%)

**Calculation with Unstacking:**
```
Section 301:        $10,000 × 25% = $2,500 (on product_value)
IEEPA Fentanyl:     $10,000 × 10% = $1,000 (on product_value)

232 Copper:         $3,000 × 50% = $1,500 (on content_value)
                    remaining_value -= $3,000 → $7,000

232 Aluminum:       $1,000 × 25% = $250 (on content_value)
                    remaining_value -= $1,000 → $6,000

232 Steel:          $1,000 × 50% = $500 (on content_value)
                    remaining_value -= $1,000 → $5,000

IEEPA Reciprocal:   $5,000 × 10% = $500 (on remaining_value!)
─────────────────────────────────────────────
TOTAL DUTY:         $6,250 (62.5% effective rate)
```

**WITHOUT unstacking (wrong):**
```
IEEPA Reciprocal:   $10,000 × 10% = $1,000 ← $500 OVERCHARGE!
TOTAL DUTY:         $6,750 (67.5% effective rate)
```

### Output Includes Unstacking Audit Trail

When unstacking is applied, the output includes:
```json
{
  "unstacking": {
    "initial_value": 10000.0,
    "content_deductions": {
      "copper": 3000.0,
      "steel": 1000.0,
      "aluminum": 1000.0
    },
    "remaining_value": 5000.0,
    "note": "IEEPA Reciprocal calculated on remaining_value after 232 content deductions"
  }
}
```

### Why This Matters

For products with high metal content, the savings can be significant:
- USB-C cable with 50% metal content: ~$500 savings per $10,000
- Industrial machinery with 80% metal: ~$800 savings per $10,000
- Total savings across a company's imports can be substantial

---

## Data Architecture

### Master Table: tariff_programs
*Defines what programs exist and when they apply*
```sql
CREATE TABLE tariff_programs (
    program_id          VARCHAR PRIMARY KEY,
    program_name        VARCHAR,
    country             VARCHAR,              -- "China", "ALL", etc.
    check_type          VARCHAR,              -- "hts_lookup", "always"
    condition_handler   VARCHAR,              -- "none", "handle_material_composition", "handle_dependency"
    condition_param     VARCHAR,              -- NULL, or "section_232" for dependencies
    inclusion_table     VARCHAR,              -- "section_301_inclusions" or NULL
    exclusion_table     VARCHAR,              -- "section_301_exclusions" or NULL
    filing_sequence     INT,                  -- Order in CBP filing (1, 2, 3...)
    source_document     VARCHAR,
    effective_date      DATE,
    expiration_date     DATE,
    -- Content-based duties
    line_split_mode     VARCHAR               -- 'none', 'by_material_value'
);
```

### section_232_materials (Updated for Content-Based Duties)
```sql
CREATE TABLE section_232_materials (
    hts_8digit          VARCHAR,
    material            VARCHAR,              -- "copper", "steel", "aluminum"
    claim_code          VARCHAR,              -- "9903.78.01"
    disclaim_code       VARCHAR,              -- "9903.78.02"
    duty_rate           DECIMAL,              -- 0.50 for copper, 0.50 for steel, 0.25 for aluminum
    source_doc          VARCHAR,
    -- Content-based duty columns
    content_basis       VARCHAR,              -- 'value' (duty on $ value), 'mass', 'percent'
    quantity_unit       VARCHAR,              -- 'kg' for material content reporting
    -- Flexible split policy (data-driven, not hardcoded)
    split_policy        VARCHAR,              -- 'never', 'if_any_content', 'if_above_threshold'
    split_threshold_pct DECIMAL,              -- NULL for 'if_any_content', numeric for threshold
    PRIMARY KEY (hts_8digit, material)
);
```

**Example data (Dec 2025):**

| hts_8digit | material | claim_code | disclaim_code | duty_rate | content_basis | split_policy | split_threshold_pct |
|------------|----------|------------|---------------|-----------|---------------|--------------|---------------------|
| 85444290 | copper | 9903.78.01 | 9903.78.02 | **0.50** | value | if_any_content | NULL |
| 85444290 | steel | 9903.80.01 | 9903.80.02 | **0.50** | value | if_any_content | NULL |
| 85444290 | aluminum | 9903.85.08 | 9903.85.09 | 0.25 | value | if_any_content | NULL |

**Why `split_policy` column?** If CBP changes the rule tomorrow to "only split if copper > 10%", we update data, not code:
```sql
UPDATE section_232_materials
SET split_policy = 'if_above_threshold', split_threshold_pct = 0.10
WHERE material = 'copper';
```

### duty_rules (Updated for Phase 6.5 - IEEPA Unstacking)
```sql
CREATE TABLE duty_rules (
    program_id          VARCHAR,
    calculation_type    VARCHAR,              -- "additive", "compound", "on_portion"
    base_on             VARCHAR,              -- "product_value", "content_value", "remaining_value"
    compounds_with      VARCHAR,
    source_doc          VARCHAR,
    -- Content-based duty columns
    content_key         VARCHAR,              -- 'copper', 'steel', 'aluminum' (which material)
    fallback_base_on    VARCHAR,              -- 'full_value' if content value unknown
    -- Phase 6.5: IEEPA Unstacking columns
    base_effect         VARCHAR               -- 'subtract_from_remaining' for 232 programs
);
```

**Example data (Phase 6.5):**

| program_id | calculation_type | base_on | content_key | fallback_base_on | base_effect |
|------------|------------------|---------|-------------|------------------|-------------|
| section_301 | additive | product_value | NULL | NULL | NULL |
| ieepa_fentanyl | additive | product_value | NULL | NULL | NULL |
| section_232_copper | on_portion | content_value | copper | full_value | **subtract_from_remaining** |
| section_232_steel | on_portion | content_value | steel | full_value | **subtract_from_remaining** |
| section_232_aluminum | on_portion | content_value | aluminum | full_value | **subtract_from_remaining** |
| ieepa_reciprocal | additive | **remaining_value** | NULL | NULL | NULL |

**Key Changes:**
- Phase 6: Section 232 uses `content_value` (material's dollar value) instead of `material_percentage`
- Phase 6.5: Section 232 programs have `base_effect = 'subtract_from_remaining'` to reduce IEEPA base
- Phase 6.5: IEEPA Reciprocal uses `remaining_value` (after 232 deductions) instead of `product_value`

### product_history (Updated for Values)
```sql
CREATE TABLE product_history (
    id              SERIAL PRIMARY KEY,
    hts_code        VARCHAR,
    product_desc    TEXT,
    country         VARCHAR,
    components      JSONB,                    -- Updated format (see below)
    decisions       JSONB,
    timestamp       TIMESTAMP,
    user_id         VARCHAR,
    user_confirmed  BOOLEAN
);
```

**New Material Format in `components` JSON:**
```json
{
  "copper": {
    "percentage": 0.05,
    "value": 500.00,
    "mass_kg": 2.5,
    "value_source": "user_provided"
  },
  "steel": {
    "percentage": 0.20,
    "value": 2000.00,
    "mass_kg": 10.0,
    "value_source": "user_provided"
  },
  "aluminum": {
    "percentage": 0.72,
    "value": 7200.00,
    "mass_kg": null,
    "value_source": "estimated_from_percentage"
  }
}
```

**Why this change:** CBP now requires material content VALUE for 232 duties. We store both percentage and value so we can:
1. Use value if user provides it
2. Estimate from percentage if value unknown
3. Apply fallback (full value) as penalty if neither available

---

## Tool Call Sequence (The Core Algorithm)

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
    │           └── NEW: Generate split lines if split_policy applies
    │       └── "handle_dependency":
    │           └── resolve_program_dependencies()
    │
    └── 3d. get_program_output(program_id, action)
            └── Append FilingLine(s) to state["filing_lines"]
            └── Store result in state["program_results"][program_id]

Step 4: calculate_duties(filing_lines, product_value, material_values)
    └── Use duty_rules table with content_value basis
    └── Apply fallback_base_on if content value unknown

Step 5: Supervisor QA
    └── Verify all programs got decisions
    └── Sanity-check math
    └── Flag uncertainties (e.g., "fallback_applied_for_copper")

Step 6: Output + save to product_history
```

**Key insight:** The loop in Step 3 is **identical for every program**. The only variation is what `condition_handler` returns - and that's data-driven.

---

## Updated Tools for Content-Based Duties

### check_material_composition (Updated)
```python
@tool
def check_material_composition(hts_code: str, materials: dict, total_value: float) -> str:
    """
    For programs with condition_type='material_composition'.

    Input materials format (NEW):
      {
        "copper": {"percentage": 0.05, "value": 500.00},  // value preferred
        "steel":  {"percentage": 0.2},  // percentage only - will estimate value
        ...
      }

    1. Query: SELECT * FROM section_232_materials WHERE hts_8digit = LEFT(?, 8)
    2. For each material in table:
       - Get user-provided value OR estimate from percentage × total_value
       - If neither available: flag for fallback (full_value)
       - Calculate: material_value, non_material_value = total_value - material_value
       - Check split_policy to determine if we generate 2 lines
    3. Return: {
         material: str,
         applies: bool,
         percentage: float,
         content_value: float,       # Dollar value of material
         non_content_value: float,   # Remaining value
         content_mass_kg: float,     # kg of material (for CBP reporting)
         claim_code: str,
         disclaim_code: str,
         action: str,
         duty_rate: float,
         split_lines: bool,          # Whether to generate 2 lines
         value_source: str           # "user_provided", "estimated", "fallback"
       }
    """
```

### calculate_duties (Updated)
```python
@tool
def calculate_duties(filing_lines: List, product_value: float, material_values: dict) -> str:
    """
    Calculate total duties based on all applicable programs.

    1. For each program, lookup duty_rules
    2. Apply based on calculation_type:
       - "additive": duty_rate × product_value
       - "on_portion" with base_on="content_value":
           a. Get material_value from material_values dict
           b. If material_value is None AND fallback_base_on = 'full_value':
              → Use product_value as base (penalty case)
              → Flag as "fallback_applied"
           c. Calculate: duty = material_value × duty_rate

    3. Generate filing lines (line splitting logic):
       IF split_policy != 'never' AND should_split_lines():
         - Line A (non-material content):
             value = product_value - material_value
             chapter_99_code = disclaim_code
             duty = 0
             quantity = full product quantity
         - Line B (material content):
             value = material_value
             chapter_99_code = claim_code
             duty = material_value × duty_rate
             quantity = 0 (base HTS), material_mass_kg (for 9903 line)

    4. Return: {
         filing_lines: List[FilingLine],
         total_duty_percent: float,
         total_duty_amount: float,
         breakdown: List[DutyBreakdown],
         flags: List[str]
       }
    """
```

---

## Output Schema (v2.0)

```python
class MaterialInfo(BaseModel):
    """Material composition with both percentage and value"""
    percentage: float           # 0.05 = 5%
    value: Optional[float]      # Dollar value of material content
    mass_kg: Optional[float]    # Mass in kg (for CBP reporting)
    value_source: str           # "user_provided", "estimated", "fallback"

class FilingLine(BaseModel):
    sequence: int
    chapter_99_code: str
    program: str
    program_id: str
    action: str                 # "apply", "claim", "disclaim", "paid"
    duty_rate: Optional[float]
    # Content-based duty fields
    line_value: float           # Value for THIS specific line
    line_quantity: float        # Product quantity (0 for material content lines)
    material: Optional[str]
    material_quantity_kg: Optional[float]
    split_type: Optional[str]   # "non_material_content" or "material_content"
    applies_to: str             # "full" or "partial"

class DutyBreakdown(BaseModel):
    program_id: str
    chapter_99_code: str
    action: str
    duty_rate: float
    base_value: float           # What value was duty calculated on
    duty_amount: float
    calculation: str            # e.g., "content_value × rate"
    material: Optional[str]
    value_source: Optional[str] # "user_provided", "estimated", "fallback"

class StackingOutput(BaseModel):
    schema_version: str = "2.0"

    # Input
    hts_code: str
    country_of_origin: str
    product_description: str
    materials: Dict[str, MaterialInfo]

    # Filing Lines (may include split lines)
    filing_lines: List[FilingLine]

    # Calculations
    base_duty_rate: float
    total_duty_percent: float
    total_duty_amount: float
    duty_breakdown: List[DutyBreakdown]

    # Audit Trail
    decisions: List[Decision]
    user_inputs: List[UserInput]
    citations: List[SourceCitation]

    # QA
    confidence: str
    flags: List[str]            # e.g., ["fallback_applied_for_copper"]
```

---

## Implementation Phases

### Phase 1-5: COMPLETED ✅
- Database schema and tables created
- Tables populated with sample data
- Core tools implemented
- Stacking graph working
- Basic tests passing

### Phase 6: Content-Based Duty Updates - COMPLETED ✅

#### 6.1 Schema Updates
- [x] Add `line_split_mode` column to `tariff_programs` table
- [x] Add `content_basis`, `split_policy`, `split_threshold_pct`, `quantity_unit` to `section_232_materials`
- [x] Add `content_key`, `fallback_base_on` columns to `duty_rules`
- [x] Update copper rate from 0.25 to 0.50

#### 6.2 Tool Updates
- [x] Update `check_material_composition()` to accept values, not just percentages
- [x] Add content_value calculation logic (value preferred, percentage as fallback)
- [x] Add fallback_to_full_value logic when content value unknown
- [x] Update `calculate_duties()` for content-value basis
- [x] Implement line splitting logic using `should_split_lines()`

#### 6.3 Output Schema Updates
- [x] Add `MaterialInfo` with value, mass_kg, value_source
- [x] Update `FilingLine` with line_value, line_quantity, material_quantity_kg, split_type
- [x] Update `DutyBreakdown` with base_value, value_source

#### 6.4 User Question Updates
- [x] Ask for material content VALUE (not just percentage)
- [x] Add warning about fallback penalty if value unknown
- [x] Store value_source in product_history

#### 6.5 Testing
- [x] Update test cases for content-value-based calculations
- [x] Add test for line splitting
- [x] Add test for fallback (full_value) scenario
- [x] Verify filing line output matches CBP expected format

### Phase 6.5: IEEPA Unstacking - COMPLETED ✅ (Dec 2025)

**Discovery:** Research document revealed IEEPA Reciprocal should NOT apply to 232 content.

#### Changes Made:
- [x] Add `base_effect` column to `DutyRule` model (`tariff_tables.py`)
- [x] Update `populate_tariff_tables.py` with 232 `base_effect = 'subtract_from_remaining'`
- [x] Update `populate_tariff_tables.py` with IEEPA Reciprocal `base_on = 'remaining_value'`
- [x] Update `calculate_duties()` in `stacking_tools.py` with `remaining_value` tracking
- [x] Add unstacking audit trail to output (`content_deductions`, `remaining_value`)
- [x] Update `stacking_rag.py` output to display unstacking info
- [x] Add Test Case 5: IEEPA Unstacking with research doc example values
- [x] Update existing test expectations for new IEEPA calculations
- [x] Document unstacking in README6.md

#### Key Files Modified:
| File | Changes |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Added `base_effect` column |
| `scripts/populate_tariff_tables.py` | Updated duty_rules with unstacking config |
| `app/chat/tools/stacking_tools.py` | Added `remaining_value` tracking |
| `app/chat/graphs/stacking_rag.py` | Added unstacking display in output |
| `tests/test_stacking_automated.py` | Added Test Case 5, updated expectations |
| `README6.md` | Added Phase 6.5 documentation |

### Phase 7: Government Document Sources (NEXT)
- [ ] Add new source URLs to `docs/tariff_sources.md`
- [ ] Create document watcher for new notices
- [ ] Create parser for different document types

---

## Files to Modify for Phase 6

| File | Changes Required |
|------|------------------|
| `scripts/populate_tariff_tables.py` | Add new columns, update copper rate to 0.50 |
| `app/web/db/models/tariff_tables.py` | Add new SQLAlchemy columns |
| `app/chat/tools/stacking_tools.py` | Update check_material_composition, calculate_duties |
| `app/chat/output_schemas.py` | Add MaterialInfo, update FilingLine, DutyBreakdown |
| `app/chat/graphs/stacking_rag.py` | Update material question flow for values |
| `tests/test_stacking_automated.py` | Add content-value and line-splitting tests |
| `docs/tariff_sources.md` | Add new government document URLs |

### Database Migration

```sql
-- tariff_programs
ALTER TABLE tariff_programs ADD COLUMN line_split_mode VARCHAR DEFAULT 'none';
UPDATE tariff_programs SET line_split_mode = 'by_material_value'
WHERE program_id LIKE 'section_232_%';

-- section_232_materials
ALTER TABLE section_232_materials ADD COLUMN content_basis VARCHAR DEFAULT 'value';
ALTER TABLE section_232_materials ADD COLUMN quantity_unit VARCHAR DEFAULT 'kg';
ALTER TABLE section_232_materials ADD COLUMN split_policy VARCHAR DEFAULT 'if_any_content';
ALTER TABLE section_232_materials ADD COLUMN split_threshold_pct DECIMAL;
UPDATE section_232_materials SET duty_rate = 0.50 WHERE material = 'copper';

-- duty_rules
ALTER TABLE duty_rules ADD COLUMN content_key VARCHAR;
ALTER TABLE duty_rules ADD COLUMN fallback_base_on VARCHAR;
UPDATE duty_rules SET base_on = 'content_value', fallback_base_on = 'full_value'
WHERE program_id LIKE 'section_232_%';
UPDATE duty_rules SET content_key = 'copper' WHERE program_id = 'section_232_copper';
UPDATE duty_rules SET content_key = 'steel' WHERE program_id = 'section_232_steel';
UPDATE duty_rules SET content_key = 'aluminum' WHERE program_id = 'section_232_aluminum';
```

---

## Government Document Sources (Dec 2025)

See `docs/tariff_sources.md` for full documentation.

**Section 232 Steel:**
- https://www.federalregister.gov/documents/2025/03/05/2025-03598/... (March 5, 2025)
- https://www.federalregister.gov/documents/2025/08/19/2025-15819/... (August 19, 2025)

**Section 232 Aluminum:**
- https://www.federalregister.gov/documents/2025/03/05/2025-03596/... (March 5, 2025)
- https://www.federalregister.gov/documents/2025/04/04/2025-05884/... (April 4, 2025)
- https://www.federalregister.gov/documents/2025/08/19/2025-15819/... (August 19, 2025)

**Section 232 Copper:**
- https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ebf0e0 (CSMS July 31, 2025)
- https://www.federalregister.gov/documents/2025/08/05/2025-14893/... (July 30, 2025)

---

## Key Design Decisions

### Deterministic vs LLM
| Component | Approach | Why |
|-----------|----------|-----|
| Program lookup | **Deterministic** (table query) | tariff_programs table |
| HTS inclusion check | **Deterministic** (table query) | Exact 8-digit match |
| Exclusion match | **LLM** (semantic) | Description requires fuzzy matching |
| Material composition | **User input** or history | Can't reliably infer |
| Filing order | **Deterministic** (filing_sequence column) | Stored in table |
| Line splitting | **Deterministic** (split_policy column) | Data-driven |
| Duty calculation | **Deterministic** (duty_rules table) | Must be exact |
| Output codes | **Deterministic** (program_codes table) | Direct lookup |
| Plain English | **LLM** | Natural language generation |

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

## Future: Rules Versioning for Audit

For compliance, we need to know which law version was used for any calculation:

```sql
ALTER TABLE tariff_programs ADD COLUMN ruleset_version VARCHAR;
ALTER TABLE section_232_materials ADD COLUMN ruleset_version VARCHAR;
ALTER TABLE product_history ADD COLUMN ruleset_version_used VARCHAR;
```

**Example audit trail:**
```json
{
  "calculation_id": "calc-2025-12-07-001",
  "ruleset_version": "v2025.12.07",
  "hts_code": "8544.42.9090",
  "decisions": [
    {"program": "section_232_copper", "rule_version": "v2025.12.07", "action": "split", ...}
  ]
}
```

This allows:
- Retrospective audits: "What rules applied on date X?"
- Reconciliation: "Why did duty differ between two calculations?"
- Compliance: "We used ruleset v2025.12.07 which reflected CBP guidance as of Dec 7, 2025"

---

## Success Criteria

**MVP Success (Content-Based Duties):**
- Given:
  - HTS `8544.42.9090` (USB-C cable)
  - Country `China`
  - Materials: `{copper: {pct: 5%, value: $500}, steel: {pct: 20%, value: $2000}, aluminum: {pct: 72%, value: $7200}}`
  - Product value: $10,000
- Output:
  - Correct filing lines with line splitting for 232 materials
  - Duty calculated on content VALUE (not percentage)
  - Fallback warning if value unknown
  - Plain English explanation for each line
  - Sources/citations for each decision

**Time Savings:**
- Current: 45-60 minutes per complex entry
- Target: 5 minutes (including material value input)
