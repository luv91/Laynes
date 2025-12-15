# Tariff Stacker v6.0 - Architecture Design Document

## Executive Summary

This document captures the evolved design for the Tariff Stacker system, incorporating expert feedback on scalability, maintainability, and avoiding "manual drift" as new tariff programs are added.

**Key Design Principles:**
1. **Data-driven rules** - No hardcoded country lists, rate values, or program logic in Python
2. **Order-independent processing** - Suppression/interaction logic produces deterministic results
3. **Single source of truth** - Each concept (rates, scope, countries) lives in exactly one place
4. **Audit trail** - Every data change is traceable to a source document and ingestion run

---

## Current State (v5.x)

### Existing Tables (13)

| Table | Purpose | Status |
|-------|---------|--------|
| `tariff_programs` | Program definitions + stacking order | ✅ |
| `section_301_inclusions` | HTS codes subject to 301 | ✅ |
| `section_301_exclusions` | HTS codes excluded from 301 | ⚠️ Needs description matching |
| `section_232_materials` | Copper/Steel/Aluminum HTS lists | ⚠️ Rename to `program_scope_hts` |
| `program_codes` | 9903.xx ACE codes | ⚠️ Remove rate field |
| `duty_rules` | Calculation logic | ⚠️ Remove rate field |
| `product_history` | Date-based rate changes | ✅ |
| `ieepa_annex_ii_exclusions` | Annex II exempt HTS | ✅ |
| `source_documents` | FR citations | ✅ |
| `country_groups` | Group definitions | ✅ |
| `country_group_members` | Country → group mappings | ✅ |
| `program_rates` | Country-specific rates | ✅ Single source for all rates |
| `hts_base_rates` | MFN base rates | ✅ |

### Programs Implemented

| Program | Country Logic | Rate Source |
|---------|---------------|-------------|
| Section 301 | China only | `program_rates` |
| IEEPA Fentanyl | ⚠️ Hardcoded list | `program_rates` |
| IEEPA Reciprocal | Country groups | `program_rates` |
| Section 232 Copper | All countries | `program_rates` |
| Section 232 Steel | UK exception | `program_rates` |
| Section 232 Aluminum | UK exception | `program_rates` |

---

## v6.0 Design Changes

### Change 1: Data-Driven Country Applicability

**Problem:** Fentanyl countries are hardcoded as `["china", "cn", "hong kong", "hk"]`

**Solution:** Make program country scope data-driven

#### New Table: `program_country_scope`

```sql
CREATE TABLE program_country_scope (
    id SERIAL PRIMARY KEY,
    program_id VARCHAR(50) NOT NULL REFERENCES tariff_programs(program_id),
    country_group_id INTEGER REFERENCES country_groups(id),
    iso_alpha2 VARCHAR(2),  -- For single-country scope (NULL if using group)
    scope_type VARCHAR(20) DEFAULT 'include',  -- 'include' or 'exclude'
    effective_date DATE NOT NULL,
    expiration_date DATE,
    source_document_id INTEGER REFERENCES source_documents(id),

    CONSTRAINT chk_scope_target CHECK (
        (country_group_id IS NOT NULL AND iso_alpha2 IS NULL) OR
        (country_group_id IS NULL AND iso_alpha2 IS NOT NULL)
    )
);

CREATE INDEX idx_program_country_scope_program ON program_country_scope(program_id, effective_date);
```

#### Example Data

```sql
-- Fentanyl applies to Greater China group
INSERT INTO country_groups (group_code, group_name) VALUES ('FENTANYL_COUNTRIES', 'IEEPA Fentanyl Target Countries');
INSERT INTO country_group_members (country_group_id, country_name, iso_alpha2) VALUES
    ((SELECT id FROM country_groups WHERE group_code = 'FENTANYL_COUNTRIES'), 'China', 'CN'),
    ((SELECT id FROM country_groups WHERE group_code = 'FENTANYL_COUNTRIES'), 'Hong Kong', 'HK'),
    ((SELECT id FROM country_groups WHERE group_code = 'FENTANYL_COUNTRIES'), 'Macau', 'MO');

INSERT INTO program_country_scope (program_id, country_group_id, effective_date) VALUES
    ('ieepa_fentanyl', (SELECT id FROM country_groups WHERE group_code = 'FENTANYL_COUNTRIES'), '2025-02-04');
```

#### Code Change

```python
# BEFORE (hardcoded):
if country.lower() in ["china", "cn", "hong kong", "hk"]:
    # Apply fentanyl

# AFTER (data-driven):
def check_program_country_scope(program_id: str, country_iso2: str, check_date: date) -> bool:
    """Check if country is in scope for program."""
    scope = ProgramCountryScope.query.filter(
        ProgramCountryScope.program_id == program_id,
        ProgramCountryScope.effective_date <= check_date,
        db.or_(
            ProgramCountryScope.expiration_date.is_(None),
            ProgramCountryScope.expiration_date >= check_date
        )
    ).all()

    for s in scope:
        if s.iso_alpha2 == country_iso2:
            return s.scope_type == 'include'
        if s.country_group_id:
            member = CountryGroupMember.query.filter_by(
                country_group_id=s.country_group_id,
                iso_alpha2=country_iso2
            ).first()
            if member:
                return s.scope_type == 'include'

    return False
```

**Adding Macau becomes:** Insert row into `country_group_members`, not a code change.

---

### Change 2: Order-Independent Suppression Resolution

**Problem:** Checking suppression while iterating creates order-dependent bugs

**Solution:** 3-pass program resolution before building stacks

#### Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    REQUEST INPUT                                 │
│  (HTS, country_input, product_value, materials, description)    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 STEP 0: NORMALIZE INPUT                          │
│  country_input → { iso_alpha2, canonical_name }                 │
│  "Deutschland" → { "DE", "Germany" }                            │
│  "Macau" → { "MO", "Macau" }                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              PASS 1: APPLICABILITY CHECK                         │
│  For each active program:                                        │
│    ✓ Country scope check (data-driven)                          │
│    ✓ HTS scope check (program_scope_hts)                        │
│    ✓ Effective date check                                        │
│  Output: applicable_programs = [301, fentanyl, reciprocal, ...]  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              PASS 2: INTERACTION RESOLUTION                      │
│  Query program_suppressions for ALL applicable_programs          │
│  suppressed = get_all_suppressed(applicable_programs, date)      │
│  resolved_programs = applicable - suppressed                     │
│  Output: resolved_programs (ORDER-INDEPENDENT)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              PASS 3: VARIANT DETERMINATION                       │
│  For each resolved program:                                      │
│    - Check exclusions (301 exclusion → 301_excluded variant)     │
│    - Check exemptions (Annex II → reciprocal_exempt variant)     │
│    - Determine slice type (metal_content, us_content, full)      │
│  Output: program_variants with slice requirements                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 4: BUILD ENTRY SLICES                          │
│  Collect all required split dimensions from program_variants     │
│  Plan slices: copper_slice, steel_slice, ..., non_metal          │
│  (Future: us_content_slice, non_us_content, etc.)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 5: CALCULATE DUTIES                            │
│  For each slice:                                                 │
│    Get rate from program_rates (SINGLE SOURCE)                   │
│    Apply formula from duty_rules                                 │
│    Sum duties                                                    │
└─────────────────────────────────────────────────────────────────┘
```

#### Suppression Resolution Code

```python
def resolve_programs(applicable_programs: list, import_date: date) -> list:
    """
    Resolve program interactions to produce final program set.
    ORDER-INDEPENDENT: Same input always produces same output.
    """
    program_ids = [p["program_id"] for p in applicable_programs]

    # Get ALL suppressions in one query
    suppressions = ProgramSuppression.query.filter(
        ProgramSuppression.suppressor_program_id.in_(program_ids),
        ProgramSuppression.suppressed_program_id.in_(program_ids),
        ProgramSuppression.effective_date <= import_date,
        db.or_(
            ProgramSuppression.expiration_date.is_(None),
            ProgramSuppression.expiration_date >= import_date
        )
    ).all()

    # Build suppressed set
    suppressed_ids = {s.suppressed_program_id for s in suppressions}

    # Filter out suppressed programs
    resolved = [p for p in applicable_programs if p["program_id"] not in suppressed_ids]

    # Log suppressions for transparency
    suppression_log = [
        {
            "suppressed": s.suppressed_program_id,
            "by": s.suppressor_program_id,
            "reason": s.notes
        }
        for s in suppressions
    ]

    return resolved, suppression_log
```

---

### Change 3: Rename `section_232_materials` to `program_scope_hts`

**Problem:** Table name implies "materials" but will contain timber, furniture, vehicles

**Solution:** Generalize to `program_scope_hts` - one table for all HTS-based program scope

#### Updated Schema

```sql
-- Rename table
ALTER TABLE section_232_materials RENAME TO program_scope_hts;

-- Updated structure
CREATE TABLE program_scope_hts (
    id SERIAL PRIMARY KEY,
    program_id VARCHAR(50) NOT NULL,  -- "section_232_copper", "section_232_timber", etc.
    hts_code VARCHAR(20) NOT NULL,    -- Can be prefix (8544) or full (8544.42.9090)
    match_type VARCHAR(10) DEFAULT 'prefix',  -- 'prefix' or 'exact'
    effective_date DATE NOT NULL,
    expiration_date DATE,
    source_document_id INTEGER REFERENCES source_documents(id),
    notes TEXT,

    UNIQUE(program_id, hts_code, effective_date)
);

CREATE INDEX idx_program_scope_hts_lookup ON program_scope_hts(program_id, hts_code, effective_date);
```

#### Migration Path

```python
# Data migration: existing copper/steel/aluminum entries
# Before: material_type = "copper"
# After: program_id = "section_232_copper"

UPDATE program_scope_hts
SET program_id = CONCAT('section_232_', material_type)
WHERE program_id IS NULL;

ALTER TABLE program_scope_hts DROP COLUMN material_type;
```

---

### Change 4: Rate Consolidation - Single Source of Truth

**Problem:** Rates exist in multiple places (program_codes, duty_rules, program_rates)

**Solution:** Remove rate fields from all tables except `program_rates`

#### Table Responsibilities (After Consolidation)

| Table | Contains | Does NOT Contain |
|-------|----------|------------------|
| `tariff_programs` | program_id, name, stacking_order | ~~rate~~ |
| `program_codes` | program_id → Chapter 99 code mapping | ~~rate~~ |
| `duty_rules` | calculation formula, base_type | ~~rate_value~~ |
| `program_rates` | **ALL rates** (ad valorem, specific) | - |
| `hts_base_rates` | MFN/Col 1 base rates only | - |

#### Updated `program_rates` Schema

```sql
CREATE TABLE program_rates (
    id SERIAL PRIMARY KEY,
    program_id VARCHAR(50) NOT NULL,
    country_group_id INTEGER REFERENCES country_groups(id),  -- NULL = default
    rate DECIMAL(10, 6) NOT NULL,  -- e.g., 0.25 for 25%
    rate_type VARCHAR(20) DEFAULT 'ad_valorem',  -- 'ad_valorem', 'specific', 'formula'
    formula_code VARCHAR(50),  -- For complex calculations (e.g., 'EU_TOP_UP')
    effective_date DATE NOT NULL,
    expiration_date DATE,
    source_document_id INTEGER REFERENCES source_documents(id),
    notes TEXT,

    UNIQUE(program_id, country_group_id, effective_date)
);

CREATE INDEX idx_program_rates_lookup ON program_rates(program_id, effective_date);
```

#### Rate Lookup Function

```python
def get_rate_for_program(
    program_id: str,
    country_iso2: str,
    hts_code: str,
    import_date: date
) -> tuple[float, str]:
    """
    Get rate from program_rates (SINGLE SOURCE OF TRUTH).

    Returns: (rate, source_description)
    """
    # Get country group for this country
    country_group = get_country_group_for_country(country_iso2)

    # Try country-specific rate first
    rate_record = ProgramRate.query.filter(
        ProgramRate.program_id == program_id,
        ProgramRate.country_group_id == country_group.id if country_group else None,
        ProgramRate.effective_date <= import_date,
        db.or_(
            ProgramRate.expiration_date.is_(None),
            ProgramRate.expiration_date >= import_date
        )
    ).order_by(ProgramRate.effective_date.desc()).first()

    # Fallback to default rate (country_group_id = NULL)
    if not rate_record:
        rate_record = ProgramRate.query.filter(
            ProgramRate.program_id == program_id,
            ProgramRate.country_group_id.is_(None),
            ProgramRate.effective_date <= import_date
        ).order_by(ProgramRate.effective_date.desc()).first()

    if not rate_record:
        return 0.0, "No rate found"

    # Handle formula-based rates
    if rate_record.rate_type == 'formula' and rate_record.formula_code:
        return calculate_formula_rate(rate_record.formula_code, hts_code, import_date)

    source = f"{program_id} rate for {country_group.group_code if country_group else 'default'}"
    return float(rate_record.rate), source


def calculate_formula_rate(formula_code: str, hts_code: str, import_date: date) -> tuple[float, str]:
    """Handle formula-based rates like EU top-up."""

    if formula_code == 'EU_TOP_UP':
        # EU ceiling rule: max(0, 15% - MFN)
        mfn_rate = get_mfn_base_rate(hts_code)
        top_up = max(0, 0.15 - mfn_rate)
        return top_up, f"EU top-up: max(0, 15% - {mfn_rate*100:.1f}% MFN) = {top_up*100:.1f}%"

    # Add more formula handlers as needed
    return 0.0, f"Unknown formula: {formula_code}"
```

---

### Change 5: Enhanced 301 Exclusions (Semantic + Confirm)

**Problem:** Regex-only matching is fragile and risky

**Solution:** Hybrid approach with semantic matching and user confirmation

#### Updated Schema

```sql
CREATE TABLE section_301_exclusions (
    id SERIAL PRIMARY KEY,
    hts_code VARCHAR(20) NOT NULL,
    description_text TEXT NOT NULL,  -- Official exclusion description (always stored)
    match_type VARCHAR(30) NOT NULL,  -- 'hts_only' or 'hts_and_description_confirmed'
    description_keywords TEXT[],      -- Safe keyword matching (optional)
    effective_date DATE NOT NULL,
    expiration_date DATE,
    tranche VARCHAR(20),
    source_document_id INTEGER REFERENCES source_documents(id),

    INDEX idx_301_exclusions_hts (hts_code, effective_date)
);
```

#### Exclusion Check Flow

```python
def check_301_exclusion(
    hts_code: str,
    product_description: str = None,
    require_confirmation: bool = True
) -> dict:
    """
    Check 301 exclusion with semantic matching + confirmation.

    Returns:
        {
            "excluded": bool,
            "match_type": str,
            "exclusion_id": int,
            "confidence": float,  # For description matches
            "requires_confirmation": bool,
            "official_description": str
        }
    """
    exclusions = Section301Exclusion.query.filter(
        Section301Exclusion.hts_code == hts_code,
        Section301Exclusion.effective_date <= date.today(),
        db.or_(
            Section301Exclusion.expiration_date.is_(None),
            Section301Exclusion.expiration_date >= date.today()
        )
    ).all()

    for excl in exclusions:
        if excl.match_type == 'hts_only':
            # HTS match is sufficient
            return {
                "excluded": True,
                "match_type": "hts_only",
                "exclusion_id": excl.id,
                "requires_confirmation": False,
                "official_description": excl.description_text
            }

        elif excl.match_type == 'hts_and_description_confirmed':
            if not product_description:
                return {
                    "excluded": False,
                    "match_type": "hts_and_description_confirmed",
                    "requires_confirmation": True,
                    "official_description": excl.description_text,
                    "message": "Product description required to confirm exclusion"
                }

            # Semantic similarity check
            confidence = calculate_semantic_similarity(
                product_description,
                excl.description_text
            )

            # Keyword fallback
            if excl.description_keywords:
                keyword_match = any(
                    kw.lower() in product_description.lower()
                    for kw in excl.description_keywords
                )
                if keyword_match:
                    confidence = max(confidence, 0.7)

            if confidence >= 0.8 and not require_confirmation:
                return {
                    "excluded": True,
                    "match_type": "hts_and_description_confirmed",
                    "exclusion_id": excl.id,
                    "confidence": confidence,
                    "requires_confirmation": False
                }
            else:
                return {
                    "excluded": False,
                    "match_type": "hts_and_description_confirmed",
                    "confidence": confidence,
                    "requires_confirmation": True,
                    "official_description": excl.description_text,
                    "message": f"Potential exclusion match ({confidence*100:.0f}% confidence). Please confirm."
                }

    return {"excluded": False, "reason": "No matching exclusion found"}
```

---

### Change 6: Generalized Slice Planning

**Problem:** Current slicing is hardcoded for metals only

**Solution:** Data-driven "split dimensions" from duty_rules

#### Updated `duty_rules` Schema

```sql
CREATE TABLE duty_rules (
    id SERIAL PRIMARY KEY,
    program_id VARCHAR(50) NOT NULL,
    code_id INTEGER REFERENCES program_codes(id),
    base_type VARCHAR(30) NOT NULL,
    -- Values: 'full_value', 'content_value', 'remaining_value', 'non_content_value'
    content_key VARCHAR(30),  -- 'copper', 'steel', 'aluminum', 'us_content', etc.
    slice_type VARCHAR(30),   -- 'metal_slice', 'content_slice', 'remaining_slice'
    calculation_type VARCHAR(30) DEFAULT 'percentage',
    -- Values: 'percentage', 'formula', 'specific'
    notes TEXT
);
```

#### Slice Planning Function

```python
def plan_entry_slices(
    resolved_programs: list,
    product_value: float,
    materials: dict,  # {"copper": 3000, "steel": 1000, ...}
    content_values: dict = None  # {"us_content": 5000, ...} for future use
) -> list:
    """
    Plan entry slices based on required split dimensions from duty_rules.

    Returns list of slices with their applicable programs and values.
    """
    content_values = content_values or {}

    # Collect all required split dimensions
    required_splits = set()
    for program in resolved_programs:
        rules = DutyRule.query.filter_by(program_id=program["program_id"]).all()
        for rule in rules:
            if rule.content_key:
                required_splits.add(rule.content_key)

    slices = []
    remaining_value = product_value

    # Create content-based slices
    for content_key in required_splits:
        if content_key in materials:
            content_value = materials[content_key]
        elif content_key in content_values:
            content_value = content_values[content_key]
        else:
            continue

        if content_value > 0:
            slices.append({
                "slice_id": f"{content_key}_slice",
                "slice_type": "content_slice",
                "content_key": content_key,
                "value": content_value,
                "applicable_programs": get_programs_for_content(resolved_programs, content_key)
            })
            remaining_value -= content_value

    # Create remaining value slice
    if remaining_value > 0:
        slices.append({
            "slice_id": "remaining",
            "slice_type": "remaining_slice",
            "content_key": None,
            "value": remaining_value,
            "applicable_programs": get_programs_for_remaining(resolved_programs)
        })

    return slices
```

---

## Updated Table Count

| Category | v5.x | v6.0 | Change |
|----------|------|------|--------|
| Core tariff tables | 13 | 15 | +2 new tables |
| New: `program_country_scope` | - | 1 | Country applicability |
| New: `program_suppressions` | - | 1 | Interaction rules |
| New: `country_aliases` | - | 1 | Input normalization |
| New: `ingestion_runs` | - | 1 | Audit trail |
| Renamed: `program_scope_hts` | - | (rename) | Was section_232_materials |
| **Total** | 13 | 17 | +4 |

Still well within TARIC/TaMaTo range of 15-20 tables.

---

## Updated Schema Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INPUT NORMALIZATION                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  country_aliases                                                             │
│    alias_raw, alias_norm (unique), iso_alpha2, canonical_name               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PROGRAM DEFINITIONS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  tariff_programs                                                             │
│    program_id (PK), name, description, stacking_order, is_active            │
│                                                                              │
│  program_country_scope (NEW)                                                 │
│    program_id → country_group_id OR iso_alpha2, scope_type, dates           │
│                                                                              │
│  program_scope_hts (renamed from section_232_materials)                      │
│    program_id, hts_code, match_type, dates                                  │
│                                                                              │
│  program_suppressions (NEW)                                                  │
│    suppressor_program_id, suppressed_program_id, dates                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RATES (SINGLE SOURCE)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  program_rates (ONLY place rates live)                                       │
│    program_id, country_group_id, rate, rate_type, formula_code, dates       │
│                                                                              │
│  hts_base_rates (MFN only)                                                   │
│    hts_code, rate, rate_type, dates                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CALCULATION RULES                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  duty_rules (NO rates here)                                                  │
│    program_id, base_type, content_key, slice_type, calculation_type         │
│                                                                              │
│  program_codes (NO rates here)                                               │
│    program_id, chapter_99_code, variant, action_code                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXCLUSIONS & EXEMPTIONS                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  section_301_inclusions                                                      │
│    hts_code, tranche, dates                                                 │
│                                                                              │
│  section_301_exclusions (enhanced)                                           │
│    hts_code, description_text, match_type, description_keywords, dates      │
│                                                                              │
│  ieepa_annex_ii_exclusions                                                   │
│    hts_code, dates                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REFERENCE & AUDIT                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  country_groups + country_group_members                                      │
│    group_code, group_name → country_name, iso_alpha2                        │
│                                                                              │
│  source_documents                                                            │
│    document_type, reference_number, url, effective_date                     │
│                                                                              │
│  ingestion_runs (NEW)                                                        │
│    source_document_id, timestamp, operator, table_affected, counts, status  │
│                                                                              │
│  product_history                                                             │
│    (date-based rate change tracking)                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Test Cases

### Existing Test Cases (v5.x)

| ID | Description | HTS | Country | Expected |
|----|-------------|-----|---------|----------|
| TC1 | USB-C cable, China, full stack | 8544.42.9090 | China | 301 + Fentanyl + 232s + Reciprocal |
| TC2 | USB-C cable, Germany (EU ceiling) | 8544.42.9090 | Germany | 232s + Reciprocal (12.4% top-up) |
| TC3 | USB-C cable, UK (232 exception) | 8544.42.9090 | UK | 232s (25%) + Reciprocal (10%) |
| TC4 | Plasmid, UK (Annex II exempt) | 2934.99.9050 | UK | $0 (fully exempt) |
| TC5 | Plastic container (no 232) | 3923.90.0080 | China | 301 + Fentanyl + Reciprocal only |

### New Test Cases (v6.0)

| ID | Description | HTS | Country | Expected | Tests |
|----|-------------|-----|---------|----------|-------|
| TC6 | USB-C cable, Macau (data-driven) | 8544.42.9090 | Macau | Fentanyl + Reciprocal | Country alias + scope table |
| TC7 | USB-C cable, "MO" (alias) | 8544.42.9090 | MO | Same as TC6 | Country normalization |
| TC8 | USB-C cable, "Macao" (alias) | 8544.42.9090 | Macao | Same as TC6 | Country alias variants |
| TC9 | Timber product, Canada | 44xx.xx.xxxx | CA | 232 Timber (25%) | New 232 program |
| TC10 | Timber product, Vietnam | 44xx.xx.xxxx | VN | 232 Timber, NO Reciprocal | Suppression rule |
| TC11 | Heavy vehicle, Mexico | 8704.xx.xxxx | MX | 232 Vehicles, NO Reciprocal | Suppression rule |
| TC12 | 301 exclusion (HTS only) | [excluded HTS] | China | No 301 duty | Exclusion match_type |
| TC13 | 301 exclusion (HTS+desc) | [excluded HTS] | China | Requires confirmation | Description matching |
| TC14 | Same input, different order | 8544.42.9090 | China | Identical output | Order independence |
| TC15 | Date regression (2025-01-01) | 8544.42.9090 | China | Pre-Fentanyl rates | Effective dating |

### Order Independence Test

```python
def test_suppression_order_independence():
    """Suppression results must be identical regardless of program order."""
    programs_order_a = ["ieepa_reciprocal", "section_232_timber"]
    programs_order_b = ["section_232_timber", "ieepa_reciprocal"]

    result_a, _ = resolve_programs(programs_order_a, date(2025, 6, 1))
    result_b, _ = resolve_programs(programs_order_b, date(2025, 6, 1))

    # Results must be identical
    assert set(p["program_id"] for p in result_a) == set(p["program_id"] for p in result_b)
    # Reciprocal should be suppressed in both
    assert "ieepa_reciprocal" not in [p["program_id"] for p in result_a]
    assert "ieepa_reciprocal" not in [p["program_id"] for p in result_b]
```

### Date-Effective Regression Test

```python
def test_date_effective_rates():
    """Same product, different dates = different applicable programs."""
    hts = "8544.42.9090"
    country = "CN"

    # Before IEEPA Fentanyl (Feb 4, 2025)
    result_jan = calculate_duties(hts, country, date(2025, 1, 15))
    assert "ieepa_fentanyl" not in result_jan["programs"]

    # After IEEPA Fentanyl
    result_mar = calculate_duties(hts, country, date(2025, 3, 15))
    assert "ieepa_fentanyl" in result_mar["programs"]
```

### Snapshot (Golden) Test

```python
def test_golden_output_tc1():
    """Snapshot test for TC1 - USB-C cable from China."""
    result = calculate_full_tariff(
        hts_code="8544.42.9090",
        country="China",
        product_value=10000,
        materials={"copper": 3000, "steel": 1000, "aluminum": 1000}
    )

    # Compare to golden snapshot (minus volatile fields)
    expected = load_golden_snapshot("tc1_usb_cable_china.json")

    assert result["total_duty"]["total_duty_amount"] == expected["total_duty"]["total_duty_amount"]
    assert result["effective_rate"] == expected["effective_rate"]
    assert len(result["entries"]) == len(expected["entries"])
```

---

## Migration Plan

### Phase 1: Schema Changes (Use Alembic)

```python
# migrations/versions/001_v6_schema_updates.py

def upgrade():
    # 1. Create country_aliases
    op.create_table('country_aliases', ...)

    # 2. Create program_country_scope
    op.create_table('program_country_scope', ...)

    # 3. Create program_suppressions
    op.create_table('program_suppressions', ...)

    # 4. Rename section_232_materials → program_scope_hts
    op.rename_table('section_232_materials', 'program_scope_hts')

    # 5. Add columns to section_301_exclusions
    op.add_column('section_301_exclusions',
        sa.Column('description_text', sa.Text))
    op.add_column('section_301_exclusions',
        sa.Column('match_type', sa.String(30), default='hts_only'))

    # 6. Create ingestion_runs
    op.create_table('ingestion_runs', ...)

    # 7. Remove rate columns from program_codes (if exists)
    # 8. Remove rate columns from duty_rules (if exists)

def downgrade():
    # Reverse all changes
    ...
```

### Phase 2: Data Migration

```python
# scripts/migrate_v6_data.py

def migrate():
    # 1. Populate country_aliases with common variants
    # 2. Create FENTANYL_COUNTRIES group and populate
    # 3. Create program_country_scope entries from hardcoded logic
    # 4. Update program_scope_hts with program_id values
    # 5. Create suppression rules for timber/vehicles
    # 6. Consolidate any duplicate rates into program_rates
```

### Phase 3: Code Updates

1. Update `stacking_tools.py`:
   - Add `normalize_country()` function
   - Replace hardcoded country lists with `check_program_country_scope()`
   - Add `resolve_programs()` for 3-pass flow

2. Update `stacking_rag.py`:
   - Implement 3-pass program resolution
   - Update `build_entry_stacks_node` to use resolved programs
   - Add suppression logging

3. Update seed scripts:
   - Remove `db.create_all()` calls
   - Add `log_ingestion()` calls

---

## Data Freshness Display

### API Response Enhancement

```python
# Add to tariff calculation response
{
    "result": { ... },
    "metadata": {
        "data_freshness": {
            "section_301": "2025-06-10",
            "ieepa_fentanyl": "2025-02-04",
            "ieepa_reciprocal": "2025-04-09",
            "section_232": "2025-03-12"
        },
        "last_ingestion": "2025-06-12T14:30:00Z",
        "source_documents_count": 47
    }
}
```

### UI Display

```
┌─────────────────────────────────────────┐
│ Data verified through: June 12, 2025   │
│ Sources: 47 official documents         │
│ [Verify with official sources]         │
└─────────────────────────────────────────┘
```

---

## Summary of Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Data-driven country scope** | Adding Macau (or removing a country) is a data change, not code |
| **Order-independent suppression** | Deterministic, testable, no iteration-order bugs |
| **Single rate source** | Eliminates "why is UI showing 25% but math used 50%" bugs |
| **Semantic + confirm for 301** | Matches broker workflow; avoids regex fragility |
| **Generalized slice dimensions** | Ready for us_content, non_us_content without rewrite |
| **Alembic migrations** | Production-ready schema management |
| **Ingestion tracking** | Answers "when was this updated?" and enables audit |

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Add 4 new tables, update 3 existing |
| `app/chat/tools/stacking_tools.py` | Add normalize_country, check_program_country_scope, resolve_programs |
| `app/chat/graphs/stacking_rag.py` | Implement 3-pass flow |
| `scripts/populate_tariff_tables.py` | Update for new schema, add log_ingestion |
| `migrations/versions/001_*.py` | Alembic migration (new) |
| `tests/test_v6_enhancements.py` | New test file with TC6-TC15 |