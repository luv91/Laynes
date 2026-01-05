# README11.md - Tariff Stacking v7.0: Phoebe-Aligned ACE Filing Model

**Date:** January 2026
**Version:** 7.0
**Status:** Implementation Ready
**Author:** Luv + Claude Code

---

## Executive Summary

This document describes the architectural changes needed to align the tariff stacking system with real-world ACE filing requirements as demonstrated by Phoebe's examples from the freight/logistics industry. The core change is shifting from a **"metal-centric slice model"** to a **"claim/disclaim decision model per applicable program"**.

### Key Design Principles (v7.0)

1. **Slice naming**: Use `residual` not "disclaim" for non-metal slices (disclaim implies a filed code exists)
2. **Program-level behavior**: Store `disclaim_behavior` on the PROGRAM, not per-HTS row
3. **301 code source**: Chapter 99 code comes from `section_301_inclusions`, not `program_codes`
4. **HTS-specific 232 codes**: Claim codes vary by HTS (e.g., steel can be 9903.80.01 OR 9903.81.91)

---

## Table of Contents

1. [Current Design](#1-current-design)
2. [What Needs to Change](#2-what-needs-to-change)
3. [Refined Schema Design](#3-refined-schema-design)
4. [New Test Cases (v7.0)](#4-new-test-cases-v70)
5. [Implementation Plan](#5-implementation-plan)
6. [Files to Modify](#6-files-to-modify)
7. [Phoebe Meeting Notes](#7-phoebe-meeting-notes)
8. [Summary of Changes](#8-summary-of-changes)
9. [Verification Checklist](#9-verification-checklist)
10. [Appendix: Phoebe Example Data](#10-appendix-phoebe-example-data-raw)
11. [Steel Scope Clarification](#11-steel-scope-clarification-january-2026)
12. [v7.0 Implementation Status](#12-v70-implementation-status)
13. [Current Search/Lookup Architecture](#13-current-searchlookup-architecture)
14. [Gemini MCP Search Integration Design (v8.0)](#14-gemini-mcp-search-integration-design-v80)
15. [Search Persistence & Vector Caching (v9.0 Implementation)](#15-search-persistence--vector-caching-v90-implementation)
16. [Gemini Parsing & Validation Architecture (v9.1)](#16-gemini-parsing--validation-architecture-v91)

---

## 1. Current Design

### 1.1 Current Slice Model (v4.0-v6.5)

The current system creates slices based on **metal presence**:

```
Input: HTS 8544.42.9090, China, $10,000
Materials: Copper=$500, Steel=$2,000, Aluminum=$7,200, Other=$300

Current Output (4 slices):
+------------------+----------+--------------------------------------+
| Slice            | Value    | Programs Applied                     |
+------------------+----------+--------------------------------------+
| non_metal        | $300     | 301, Fentanyl, Reciprocal(PAID)      |
| copper_slice     | $500     | 301, Fentanyl, 232-Cu, Recip(EXEMPT) |
| steel_slice      | $2,000   | 301, Fentanyl, 232-St, Recip(EXEMPT) |
| aluminum_slice   | $7,200   | 301, Fentanyl, 232-Al, Recip(EXEMPT) |
+------------------+----------+--------------------------------------+
```

### 1.2 Current Chapter 99 Code Generation (WRONG)

**Current stack per slice (non_metal example):**
```
9903.88.03      (Section 301)
9903.01.24      (IEEPA Fentanyl)
9903.01.25      (IEEPA Reciprocal - PAID)
9903.78.02      (Copper DISCLAIM) <-- Currently shown
9903.80.02      (Steel DISCLAIM)  <-- WRONG: Should be omitted
9903.85.09      (Aluminum DISCLAIM) <-- WRONG: Should be omitted
8544.42.9090    (Base HTS)
```

### 1.3 Three Concrete Mismatches

1. **Steel/Aluminum "0% DISCLAIM" lines appear** but Phoebe expects them omitted entirely
2. **Copper disclaim appears only sometimes** but should appear in ALL other slices when copper is applicable
3. **99-code selection is constant** (e.g., steel always 9903.80.01) but Phoebe shows steel can be 9903.81.91

---

## 2. What Needs to Change

### 2.1 Core Architecture Shift

**From:** "slice = metal presence"
**To:** "slice = claim decision + required cross-disclaims (copper) + omit behavior (steel/aluminum)"

**Internal Engine Must Think:**
1. **Applicability** - HTS says this program could apply
2. **Decision per slice** - claimed vs not claimed
3. **Filing behavior per program** - insert disclaim vs omit

### 2.2 Disclaim Behavior Per Metal

| Metal | Has Explicit Disclaim Code? | Behavior |
|-------|----------------------------|----------|
| **Copper** | YES (9903.78.02) | `required` - Must include disclaim code in OTHER slices |
| **Steel** | NO | `omit` - Omit entirely if not claimed |
| **Aluminum** | NO | `omit` - Omit entirely if not claimed |

### 2.3 Slice Naming Convention

**IMPORTANT:** Rename `non_metal` -> `residual` (or keep `non_metal`, but avoid "disclaim" label)

**Reason:** "disclaim" implies a filed disclaim code exists (true only for copper). In the residual slice, steel/aluminum are simply *omitted*.

### 2.4 Cross-Slice Copper Disclaim Insertion

**Critical Rule:** When copper is applicable to an HTS but NOT claimed in a particular slice, the copper disclaim code (9903.78.02) MUST appear in that slice.

**Example - Aluminum slice when copper is also applicable:**
```
Aluminum claim slice ($1,000):
  9903.88.03      (Section 301)
  9903.01.24      (IEEPA Fentanyl)
  9903.01.25      (IEEPA Reciprocal)
  9903.78.02      (Copper DISCLAIM) <-- MUST BE HERE
  9903.85.08      (Aluminum CLAIM)
  8544.42.9090    (Base HTS)
```

### 2.5 HTS-Dependent Chapter 99 Codes

**Current Problem:** We assume constant codes (Steel = 9903.80.01)

**Reality from Phoebe's examples:**
- Steel can be 9903.80.01 OR 9903.81.91 (depends on HTS - primary vs derivative)
- Section 301 can be 9903.88.01, 9903.88.03, or 9903.88.69

**Required:** Lookup claim_code from `section_232_materials` table per HTS.

### 2.6 Quantity Duplication Policy

All slices repeat the SAME piece count (quantity duplicated, value split).

```
Line Item: 18 pieces, $3,348 total

Slice 1 (residual): 18 pcs, $280.23
Slice 2 (steel claim): 18 pcs, $3,046.68
Slice 3 (aluminum claim): 18 pcs, $21.09
```

---

## 3. Refined Schema Design

### 3.1 Program-Level Disclaim Behavior (Recommended)

**Instead of adding `requires_disclaim_in_other_slices` to each HTS row**, store behavior on the program itself:

```python
# Add to tariff_programs table
class TariffProgram(db.Model):
    # ... existing columns ...
    disclaim_behavior = Column(String(16), default='none')
    # Values: 'required', 'omit', 'none'
```

**Values:**
- `required` - Copper (must file disclaim code in other slices)
- `omit` - Steel/Aluminum (omit entirely when not claimed)
- `none` - Non-232 programs (no disclaim concept)

**Benefit:** Single source of truth, not duplicated across thousands of HTS rows.

### 3.2 Section 301 Code Source

**Critical:** `chapter99_code` comes from `section_301_inclusions`, NOT `program_codes`:

```python
def check_301_inclusion(hts_code):
    row = Section301Inclusion.query.filter_by(hts_8digit=hts_code[:8]).first()
    if row:
        return {
            "applies": True,
            "chapter99_code": row.chapter_99_code,  # 9903.88.01, .03, .69, etc.
            "list_name": row.list_name,
            "duty_rate": row.duty_rate
        }
    return {"applies": False}
```

**Do NOT:** Look up program_id + then query program_codes for 301.

### 3.3 Section 232 Materials Table (Keep Existing)

```python
class Section232Material(db.Model):
    hts_8digit = Column(String(10))
    material = Column(String(32))  # 'copper', 'steel', 'aluminum'
    claim_code = Column(String(16))  # HTS-specific (e.g., 9903.81.91)
    disclaim_code = Column(String(16))  # Only meaningful for copper
    duty_rate = Column(Numeric(5,4))
```

**Note:** `disclaim_code` for steel/aluminum can remain but will be ignored due to program-level `disclaim_behavior='omit'`.

### 3.4 Scope Resolver Output Structure

```python
def resolve_scope(hts_code, country):
    return {
        "section_301": {
            "applies": True,
            "chapter99_code": "9903.88.03",  # From inclusion row
            "list_name": "list_3"
        },
        "section_232_copper": {
            "applies": True,
            "claim_code": "9903.78.01",
            "disclaim_code": "9903.78.02",
            "disclaim_behavior": "required"  # From program
        },
        "section_232_steel": {
            "applies": True,
            "claim_code": "9903.81.91",  # HTS-specific!
            "disclaim_behavior": "omit"  # From program
        },
        "section_232_aluminum": {
            "applies": True,
            "claim_code": "9903.85.08",
            "disclaim_behavior": "omit"  # From program
        }
    }
```

---

## 4. New Test Cases (v7.0)

### 4.1 Test Case Strategy

**Legacy Tests:** Keep as snapshots/xfails, don't delete
**v7.0 Tests:** All include `effective_date="2026-01-01"`
**Assertions:** Stack structure first, then duty math

### 4.2 Phoebe Example Test Cases

#### TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)
**Source:** Phoebe Example 1 | **Timestamp:** 2026-01-01

```yaml
Input:
  hts_code: "9403.99.9045"
  country: "CN"
  product_value: 123.12
  quantity: 6
  effective_date: "2026-01-01"
  materials:
    steel: { value: 61.56 }
    aluminum: { value: 61.56 }

Expected:
  slices: 2

  slice_1:
    slice_type: "steel_claim"
    value: 61.56
    quantity: 6
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.81.91", "9403.99.9045"]

  slice_2:
    slice_type: "aluminum_claim"
    value: 61.56
    quantity: 6
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.85.08", "9403.99.9045"]

Notes:
  - No copper codes (copper not applicable to this HTS)
  - No steel disclaim in aluminum slice (steel omitted)
  - No aluminum disclaim in steel slice (aluminum omitted)
```

#### TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)
**Source:** Phoebe Example 2 | **Timestamp:** 2026-01-01

```yaml
Input:
  hts_code: "8544.42.9090"
  country: "CN"
  product_value: 36.00
  quantity: 3
  effective_date: "2026-01-01"
  materials:
    copper: { value: 18.00 }
    aluminum: { value: 18.00 }

Expected:
  slices: 2

  slice_1:
    slice_type: "aluminum_claim"
    value: 18.00
    quantity: 3
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.78.02", "9903.85.08", "8544.42.9090"]
    # Note: 9903.78.02 is COPPER DISCLAIM - required because copper is applicable

  slice_2:
    slice_type: "copper_claim"
    value: 18.00
    quantity: 3
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.78.01", "8544.42.9090"]
    # Note: No aluminum code (aluminum omitted when not claimed)

Key_Insight: Copper disclaim appears in aluminum slice because copper IS applicable but NOT claimed there
```

#### TC-v7.0-003: No 232 Claimed (Residual Only)
**Source:** Phoebe Example 3 | **Timestamp:** 2026-01-01

```yaml
Input:
  hts_code: "8536.90.8585"
  country: "CN"
  product_value: 174.00
  quantity: 3
  effective_date: "2026-01-01"
  materials: {}

Expected:
  slices: 1

  slice_1:
    slice_type: "residual"  # Not "disclaim"!
    value: 174.00
    quantity: 3
    stack: ["9903.88.01", "9903.01.24", "9903.01.25", "8536.90.8585"]

Notes:
  - No 232 codes at all (omitted, not disclaimed)
  - Uses 9903.01.25 (paid) not 9903.01.33 (exempt)
  - Uses 9903.88.01 (List 1) not 9903.88.03 (List 3)
```

#### TC-v7.0-004: Copper Full Claim
**Source:** Phoebe Example 4 | **Timestamp:** 2026-01-01

```yaml
Input:
  hts_code: "8544.42.2000"
  country: "CN"
  product_value: 66.00
  quantity: 6
  effective_date: "2026-01-01"
  materials:
    copper: { value: 66.00 }

Expected:
  slices: 1

  slice_1:
    slice_type: "copper_claim"
    value: 66.00
    quantity: 6
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.78.01", "8544.42.2000"]
```

#### TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)
**Source:** Phoebe Example 5 | **Timestamp:** 2026-01-01

```yaml
Input:
  hts_code: "9403.99.9045"
  country: "CN"
  product_value: 3348.00
  quantity: 18
  effective_date: "2026-01-01"
  materials:
    steel: { value: 3046.68 }
    aluminum: { value: 21.09 }

Expected:
  slices: 3

  slice_1:
    slice_type: "residual"
    value: 280.23
    quantity: 18
    stack: ["9903.88.03", "9903.01.24", "9903.01.25", "9403.99.9045"]
    # NO steel disclaim, NO aluminum disclaim

  slice_2:
    slice_type: "steel_claim"
    value: 3046.68
    quantity: 18
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.81.91", "9403.99.9045"]

  slice_3:
    slice_type: "aluminum_claim"
    value: 21.09
    quantity: 18
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.85.08", "9403.99.9045"]
```

#### TC-v7.0-006: Annex II Exemption
**Source:** Phoebe Example 6 | **Timestamp:** 2026-01-01

```yaml
Input:
  hts_code: "8473.30.5100"
  country: "CN"
  product_value: 842.40
  quantity: 27
  effective_date: "2026-01-01"
  materials:
    aluminum: { value: 126.36 }

Expected:
  slices: 2

  slice_1:
    slice_type: "residual"
    value: 716.04
    quantity: 27
    stack: ["9903.88.69", "9903.01.24", "9903.01.32", "8473.30.5100"]
    # 9903.01.32 = Annex II exempt (takes precedence over metal_exempt)
    # 9903.88.69 = Different 301 list

  slice_2:
    slice_type: "aluminum_claim"
    value: 126.36
    quantity: 27
    stack: ["9903.88.69", "9903.01.24", "9903.01.32", "9903.85.08", "8473.30.5100"]
    # Still Annex II (9903.01.32), not metal_exempt (9903.01.33)
```

### 4.3 Edge Case Test Cases

#### TC-v7.0-007: Copper Applicable But Not Claimed (SYNTHETIC)
**Note:** Uses synthetic HTS scope seeding to ensure copper+aluminum applicable

```yaml
Input:
  hts_code: "TEST.COPPER.ALUMINUM"  # Synthetic HTS
  country: "CN"
  product_value: 10000.00
  quantity: 10
  effective_date: "2026-01-01"
  materials:
    aluminum: { value: 5000.00 }
    # Copper: $0 but HTS flags for it

Scope_Seed:  # Test seeds this applicability
  copper: { applies: true }
  aluminum: { applies: true }

Expected:
  slices: 2

  slice_1:
    slice_type: "residual"
    value: 5000.00
    stack_must_contain: ["9903.78.02"]  # Copper disclaim REQUIRED

  slice_2:
    slice_type: "aluminum_claim"
    value: 5000.00
    stack_must_contain: ["9903.78.02", "9903.85.08"]  # Both copper disclaim AND aluminum claim
```

#### TC-v7.0-008: No Steel/Aluminum Disclaim Codes
```yaml
Purpose: Verify steel/aluminum disclaim codes NEVER appear

Input:
  hts_code: "8544.42.9090"
  country: "CN"
  product_value: 1000.00
  quantity: 5
  materials:
    copper: { value: 1000.00 }

Expected:
  slice_1:
    stack: ["9903.88.03", "9903.01.24", "9903.01.33", "9903.78.01", "8544.42.9090"]
    must_not_contain:
      - "9903.80.02"  # Steel disclaim
      - "9903.85.09"  # Aluminum disclaim
```

#### TC-v7.0-009: Quantity Duplication
```yaml
Input:
  hts_code: "8544.42.9090"
  country: "CN"
  product_value: 10000.00
  quantity: 100
  materials:
    copper: { value: 3000.00 }
    steel: { value: 2000.00 }
    aluminum: { value: 1000.00 }

Expected:
  slices: 4
  all_slices_have_quantity: 100  # NOT split
  sum_of_values: 10000.00  # IS split
```

### 4.4 Stability Test Cases

#### TC-v7.0-010: Rounding / Penny Drift
```yaml
Input:
  product_value: 100.00
  materials:
    copper: { value: 33.33 }
    aluminum: { value: 33.33 }
    steel: { value: 33.33 }

Expected:
  sum_of_slice_values: 100.00  # Exactly, no drift
  residual_absorbs_rounding: true  # If 0.01 remainder
```

#### TC-v7.0-011: Invalid Allocation (Sum > Total)
```yaml
Input:
  product_value: 100.00
  materials:
    copper: { value: 60.00 }
    aluminum: { value: 60.00 }  # Sum = 120 > 100

Expected:
  error: "Material values exceed product value"
  no_partial_output: true
```

#### TC-v7.0-012: Claimed Metal Not Applicable
```yaml
Input:
  hts_code: "9403.99.9045"  # Flags for steel+aluminum, NOT copper
  materials:
    copper: { value: 500.00 }  # User claims copper

Expected:
  behavior: "warn_and_ignore"  # or "error" - define policy
  copper_not_in_output: true
```

#### TC-v7.0-013: Copper Applicable, No Copper Slice Exists
```yaml
Input:
  hts_code: "8544.42.9090"  # Flags for copper+aluminum
  materials:
    aluminum: { value: 5000.00 }
    # No copper claimed, but copper IS applicable

Expected:
  residual_slice:
    must_contain: ["9903.78.02"]  # Copper disclaim once
  aluminum_slice:
    must_contain: ["9903.78.02"]  # Copper disclaim once
  no_duplicate_copper_disclaim: true  # Exactly once per slice
```

#### TC-v7.0-014: No Duplicate Copper Disclaim Insertion
```yaml
Purpose: Copper disclaim appears exactly ONCE per slice, not twice

Input:
  hts_code: "8544.42.9090"
  materials:
    aluminum: { value: 1000.00 }

Expected:
  aluminum_slice:
    copper_disclaim_count: 1  # Not 2 or 0
```

### 4.5 Legacy Test Strategy

```python
# Option 1: Mark as legacy snapshots (recommended)
@pytest.mark.legacy_snapshot
def test_usbc_cable_v4():
    """Pre-v7 output - kept for reference"""
    pass

# Option 2: Mark as expected failures
@pytest.mark.xfail(reason="Known mismatch: pre-v7 included steel/alum disclaim")
def test_high_steel_content_v4():
    pass
```

**Location:** `tests/legacy_snapshots/` (separate from v7 tests)

---

## 5. Implementation Plan

### Phase 1: Database Schema Updates

**1.1 Add `disclaim_behavior` to TariffProgram:**
```python
class TariffProgram(db.Model):
    disclaim_behavior = Column(String(16), default='none')
    # 'required' = copper, 'omit' = steel/aluminum, 'none' = other
```

**1.2 Update populate script:**
```python
# section_232_copper: disclaim_behavior = 'required'
# section_232_steel: disclaim_behavior = 'omit'
# section_232_aluminum: disclaim_behavior = 'omit'
```

**1.3 Add Phoebe HTS codes with correct claim_codes:**
```python
# 9403.99.9045 + steel -> claim_code = "9903.81.91" (derivative)
# 8544.42.9090 + steel -> claim_code = "9903.80.01" (primary)
# 8536.90.8585 -> list_1 -> chapter_99_code = "9903.88.01"
# 8473.30.5100 -> other_list -> chapter_99_code = "9903.88.69"
```

### Phase 2: Stacking Tools Updates

**2.1 Update scope resolver to return codes:**
```python
def resolve_program_scope(hts_code, country):
    # Returns chapter99_code from inclusion row, not program_codes
    # Returns claim_code from section_232_materials
    # Returns disclaim_behavior from tariff_programs
```

**2.2 Update stack builder:**
```python
def build_entry_stack(slice, scope):
    for program in ['section_232_copper', 'section_232_steel', 'section_232_aluminum']:
        info = scope[program]
        if not info['applies']:
            continue

        if slice.claims(program):
            stack.append(info['claim_code'])
        elif info['disclaim_behavior'] == 'required':
            stack.append(info['disclaim_code'])  # Copper only
        # 'omit' -> do nothing
```

**2.3 Update slice planner for quantity:**
```python
def plan_entry_slices(product_value, materials, quantity):
    for slice in slices:
        slice['quantity'] = quantity  # Duplicate, don't split
```

### Phase 3: Test Implementation

**3.1 Create test files:**
```
tests/test_stacking_v7_phoebe.py      # Phoebe examples
tests/test_stacking_v7_stability.py   # Edge cases
tests/legacy_snapshots/               # Old tests as reference
```

**3.2 Use fixtures with effective_date:**
```python
@pytest.fixture
def phoebe_example_1():
    return {
        "input": {..., "effective_date": "2026-01-01"},
        "expected": {...}
    }
```

---

## 6. Files to Modify

| File | Changes |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Add `disclaim_behavior` to TariffProgram |
| `app/chat/tools/stacking_tools.py` | Update scope resolver, stack builder, slice planner |
| `scripts/populate_tariff_tables.py` | Add Phoebe HTS codes, set disclaim_behavior values |
| `tests/test_stacking_v7_phoebe.py` | NEW: All Phoebe test cases |
| `tests/test_stacking_v7_stability.py` | NEW: Edge case tests |
| `tests/legacy_snapshots/` | Move old tests here |
| `docs/readme11.md` | This document |
| `docs/test-cases.md` | Add v7.0 section |

---

## 7. Phoebe Meeting Notes

### Key Insights from December 2025 Meeting

1. **Dollar Amount > Percentage**: Importers must provide dollar breakout to brokers, not percentages
2. **Only Show Applicable Metals**: Don't show steel if HTS doesn't flag for it
3. **CSMS Messages**: Source of truth for 232 applicability - changes frequently
4. **Copper is Special**: Has explicit claim/disclaim codes; steel/aluminum don't
5. **Quantity Duplicated**: All slices have same piece count, value is split
6. **301 Exclusions**: Some may use 9903.88.69 instead of 9903.88.03

### Phoebe's Filing Order

```
1. Section 301 code (9903.88.xx)
2. IEEPA Fentanyl (9903.01.24)
3. IEEPA Reciprocal (variant: 9903.01.25 vs 9903.01.33 vs 9903.01.32)
4. Section 232 metal codes (claim and/or disclaim)
5. Base HTS
```

### Reciprocal Variant Priority

```
1. annex_ii_exempt -> 9903.01.32
2. us_content_exempt -> 9903.01.34
3. metal_exempt -> 9903.01.33
4. taxable -> 9903.01.25
```

---

## 8. Summary of Changes

| Component | Current | v7.0 Required | Impact |
|-----------|---------|---------------|--------|
| Steel/Aluminum disclaim | Shows codes | **Omit entirely** | Breaking |
| Copper disclaim | Sometimes present | **Always in other slices** | Breaking |
| Disclaim behavior location | Per-HTS row | **Per-program** | Schema |
| Steel claim code | 9903.80.01 | **HTS-specific** | Breaking |
| 301 code source | program_codes | **section_301_inclusions** | Code path |
| Slice naming | "non_metal" | **"residual"** | Cosmetic |
| Quantity | Not tracked | **Duplicate per slice** | New feature |

---

## 9. Verification Checklist

- [ ] Steel disclaim (9903.80.02) NEVER appears in output
- [ ] Aluminum disclaim (9903.85.09) NEVER appears in output
- [ ] Copper disclaim (9903.78.02) appears in EVERY non-copper slice when copper applicable
- [ ] Copper disclaim appears exactly ONCE per slice (no duplicates)
- [ ] Steel claim code is HTS-specific (9903.81.91 for derivatives)
- [ ] 301 code comes from section_301_inclusions, not program_codes
- [ ] Quantity is duplicated across all slices
- [ ] Values sum to product_value exactly (no penny drift)
- [ ] Invalid allocations produce clear errors
- [ ] All v7 tests pass with effective_date="2026-01-01"

---

## 10. Appendix: Phoebe Example Data (Raw)

### Example 1: Steel + Aluminum (50/50)
```
Qty=6, Value=$61.56 each, Country=CN, HTS=9403.99.9045
Stack: 9903.88.03, 9903.01.24, 9903.01.33, 9903.81.91, 9403.99.9045
       9903.88.03, 9903.01.24, 9903.01.33, 9903.85.08, 9403.99.9045
```

### Example 2: Copper + Aluminum (50/50)
```
Qty=3, Value=$18 each, Country=CN, HTS=8544.42.9090
Stack: 9903.88.03, 9903.01.24, 9903.01.33, 9903.78.02, 9903.85.08, 8544.42.9090
       9903.88.03, 9903.01.24, 9903.01.33, 9903.78.01, 8544.42.9090
```

### Example 3: Disclaim Aluminum
```
Qty=3, Value=$174, Country=CN, HTS=8536.90.8585
Stack: 9903.88.01, 9903.01.24, 9903.01.25, 8536.90.8585
```

### Example 4: Copper Full Claim
```
Qty=6, Value=$66, Country=CN, HTS=8544.42.2000
Stack: 9903.88.03, 9903.01.24, 9903.01.33, 9903.78.01, 8544.42.2000
```

### Example 5: Steel + Aluminum Claim/Disclaim
```
Line-item total: $3348, Qty=18, HTS=9403.99.9045
Slice 1: $280.23  -> 9903.88.03, 9903.01.24, 9903.01.25, 9403.99.9045
Slice 2: $3046.68 -> 9903.88.03, 9903.01.24, 9903.01.33, 9903.81.91, 9403.99.9045
Slice 3: $21.09   -> 9903.88.03, 9903.01.24, 9903.01.33, 9903.85.08, 9403.99.9045
```

### Example 6: Aluminum Claim/Disclaim with Annex II
```
Line-item total: $842.40, Qty=27, HTS=8473.30.5100
Slice 1: $716.04 -> 9903.88.69, 9903.01.24, 9903.01.32, 8473.30.5100
Slice 2: $126.36 -> 9903.88.69, 9903.01.24, 9903.01.32, 9903.85.08, 8473.30.5100
```

---

## 11. Steel Scope Clarification (January 2026)

### 11.1 Original Confusion

Phoebe stated: **"8544.42.9090 flags for copper and aluminum, NOT steel"**

This was initially interpreted as: Steel is not applicable to this HTS code.

### 11.2 Corrected Understanding

**VERIFIED:** Steel IS in scope for HTS 8544.42.90 per the official CBP steel HTS list (effective August 18, 2025).

**Key Nuance - "In Scope" vs "Has Content":**

| Concept | Meaning |
|---------|---------|
| **"HTS in scope for steel"** | Steel Section 232 rules are **potentially applicable** |
| **≠** | Every product under this HTS has steel content |

**What this means:**
- CBP expects the filer to treat steel content rules as possibly applicable for that classification
- If the product truly has $0 steel, you should NOT create a steel-claim slice
- But the system should recognize steel as "potentially applicable" to this HTS

### 11.3 Official Sources

- [CSMS #65936570](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ee1cba) - Section 232 Additional Steel Derivative Tariff Inclusion Products (Aug 15, 2025)
- [CBP Steel HTS List (Aug 2025)](https://www.awpa.org/wp-content/uploads/2025/08/Updated-steelHTSlist-081525.pdf) - Official list includes 8544.42.90
- [Federal Register 90 FR 11249, 90 FR 24199, 90 FR 25208](https://www.federalregister.gov/documents/2025/08/19/2025-15819/adoption-and-procedures-of-the-section-232-steel-and-aluminum-tariff-inclusions-process) - Legal basis for derivative additions

### 11.4 Correct System Behavior

The current implementation is **CORRECT**:

1. ✅ `section_232_materials` table has steel for 8544.42.90 (steel IS in scope)
2. ✅ When user enters $0 steel → no steel slice created
3. ✅ When user enters steel value > $0 → steel slice created

**Phoebe's guidance** was about a **specific USB-C cable product** that had no steel content - not that steel is never applicable to the HTS classification.

### 11.5 Correct Scope for Phoebe Examples

| HTS | Copper | Steel | Aluminum | Notes |
|-----|--------|-------|----------|-------|
| 8544.42.9090 | ✅ | ✅ | ✅ | All 3 metals in scope (Aug 2025 list). Phoebe's example had $0 steel content. |
| 9403.99.9045 | ❌ | ✅ | ✅ | Furniture - steel + aluminum |
| 8536.90.8585 | ❌ | ❌ | ❌ | Electrical parts - no 232 metals applicable |
| 8473.30.5100 | ❌ | ❌ | ✅ | Computer parts - aluminum only |

### 11.6 Technical Note: Steel Derivatives in Chapter 85

As of August 18, 2025, Commerce/BIS added 428 HTS codes to the Section 232 derivative list. Chapter 85 codes (electrical machinery) were included based on petitions demonstrating that:

1. USB-C cables and similar products may contain **steel for structural reinforcement** (messenger wires)
2. **Shielding** may use braided steel wire or foil
3. **Connector housings** may contain steel components

This doesn't mean every USB-C cable has steel - it means CBP expects filers to evaluate and declare steel content if present.

---

## 12. v7.0 Implementation Status

### Completion Checklist

| Item | Status |
|------|--------|
| `disclaim_behavior` added to TariffProgram | ✅ Complete |
| Populate script updated with Phoebe HTS codes | ✅ Complete |
| Scope resolver returns codes from correct tables | ✅ Complete |
| Stack builder implements disclaim_behavior logic | ✅ Complete |
| Quantity handling (duplicate per slice) | ✅ Complete |
| Invalid allocation validation | ✅ Complete |
| Front-end validation (percentages ≤ 100%) | ✅ Complete |
| v7.0 Phoebe tests | ✅ 7/7 passing |
| v7.0 Stability tests | ✅ 7/7 passing |
| Steel scope clarification | ✅ Verified - no changes needed |
| Phoebe validation on examples | ⬜ Pending |

### Test Results (January 2026)

```
v7.0 Phoebe-Aligned ACE Filing - Test Suite
============================================================
[PASS] TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)
[PASS] TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)
[PASS] TC-v7.0-003: No 232 Claimed (Residual Only)
[PASS] TC-v7.0-004: Copper Full Claim
[PASS] TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)
[PASS] TC-v7.0-006: Annex II Exemption
[PASS] TC-v7.0-008: No Steel/Aluminum Disclaim Codes
============================================================
Results: 7 passed, 0 failed, 7 total

v7.0 Stability Test Suite - Edge Cases
============================================================
[PASS] TC-v7.0-009: Quantity Duplication
[PASS] TC-v7.0-010: Rounding / Penny Drift
[PASS] TC-v7.0-011: Invalid Allocation (Sum > Total)
[PASS] TC-v7.0-013: Copper Applicable, No Copper Slice Exists
[PASS] TC-v7.0-014: No Duplicate Copper Disclaim Insertion
[PASS] TC-v7.0-015: Slice Value Sum Validation
[PASS] TC-v7.0-016: Zero Metal Value Handling
============================================================
Results: 7 passed, 0 failed, 7 total
```

---

## 13. Current Search/Lookup Architecture

### 13.1 Overview: 100% Data-Driven, No External API Calls

The tariff stacking system is **entirely data-driven** with **no external API calls during runtime**. All tariff logic comes from database tables that are populated from government documents.

```
┌─────────────────────────────────────────────────────────────────┐
│                     CURRENT ARCHITECTURE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐     ONE-TIME POPULATION                       │
│  │  CBP PDFs   │─────────────────────────┐                     │
│  │  CSMS Docs  │                         │                     │
│  │  USTR Lists │                         ▼                     │
│  │  Fed Reg    │              ┌──────────────────┐             │
│  └─────────────┘              │   PostgreSQL DB   │             │
│                               │  ┌──────────────┐ │             │
│                               │  │tariff_programs│ │             │
│                               │  │section_301_  │ │             │
│                               │  │  inclusions  │ │             │
│                               │  │section_232_  │ │             │
│                               │  │  materials   │ │             │
│                               │  │program_codes │ │             │
│                               │  │annex_ii_excl │ │             │
│                               │  └──────────────┘ │             │
│                               └────────┬─────────┘             │
│                                        │                        │
│  ┌─────────────┐      RUNTIME QUERIES  │                        │
│  │ User Input  │                       │                        │
│  │ HTS: 8544.. │──────────────────────▶│                        │
│  │ Country: CN │       SQL Lookups     │                        │
│  │ Value: $10k │◀──────────────────────│                        │
│  └─────────────┘       Results         │                        │
│                                                                 │
│  ❌ NO WEB SEARCH    ❌ NO GEMINI    ❌ NO EXTERNAL APIs        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 13.2 Data Sources (Populated Once)

| Table | Source Document | Update Frequency |
|-------|-----------------|------------------|
| `section_301_inclusions` | USTR List 1-4 PDFs | When USTR updates lists |
| `section_232_materials` | CBP CSMS bulletins (#65936570, etc.) | When BIS adds HTS codes |
| `ieepa_annex_ii_exclusions` | Executive Order Annex II | When White House updates |
| `hts_base_rates` | USITC HTS Column 1 rates | Rarely changes |
| `program_rates` | Presidential Proclamations | Per-country rate changes |

**Population Script:** `scripts/populate_tariff_tables.py`

```bash
# Run to refresh all tariff data
pipenv run python scripts/populate_tariff_tables.py
```

### 13.3 How Scope Determination Works

When a user enters an HTS code, the system queries the database to determine which programs apply:

#### Step 1: Query Applicable Programs
```python
# File: app/chat/tools/stacking_tools.py (lines 571-630)
def get_applicable_programs(country, hts_code, import_date):
    """Query which tariff programs apply to this country/date."""
    return TariffProgram.query.filter(
        or_(TariffProgram.country == country, TariffProgram.country == 'ALL'),
        TariffProgram.effective_date <= import_date,
        or_(TariffProgram.expiration_date == None,
            TariffProgram.expiration_date > import_date)
    ).order_by(TariffProgram.filing_sequence).all()
```

**Result for China:** Returns 6 programs: `section_301`, `ieepa_fentanyl`, `ieepa_reciprocal`, `section_232_copper`, `section_232_steel`, `section_232_aluminum`

#### Step 2: Check Inclusion Tables (Per Program)
```python
# File: app/chat/tools/stacking_tools.py (lines 637-716)
def check_program_inclusion(program_id, hts_code):
    """Check if HTS is in program's inclusion table."""

    if program.check_type == "always":
        return {"included": True}  # IEEPA Fentanyl always applies to China

    if program_id == "section_301":
        # Query Section 301 inclusions
        row = Section301Inclusion.query.filter_by(
            hts_8digit=hts_code[:8]  # "85444290"
        ).first()
        if row:
            return {
                "included": True,
                "chapter_99_code": row.chapter_99_code,  # "9903.88.03"
                "duty_rate": row.duty_rate,              # 0.25
                "list_name": row.list_name               # "list_3"
            }

    if program_id.startswith("section_232"):
        material = program_id.replace("section_232_", "")  # "copper"
        row = Section232Material.query.filter_by(
            hts_8digit=hts_code[:8],
            material=material
        ).first()
        if row:
            return {
                "included": True,
                "claim_code": row.claim_code,      # "9903.78.01"
                "disclaim_code": row.disclaim_code, # "9903.78.02"
                "duty_rate": row.duty_rate          # 0.50
            }
```

#### Step 3: Check Exclusions (Prefix Matching)
```python
# File: app/chat/tools/stacking_tools.py (lines 1723-1775)
def check_annex_ii_exclusion(hts_code):
    """Check Annex II with PREFIX MATCHING (4, 6, 8, 10 digit)."""

    prefixes = [
        hts_code,           # "8544.42.9090" (10-digit)
        hts_code[:8],       # "8544.42.90" (8-digit)
        hts_code[:6],       # "8544.42" (6-digit)
        hts_code[:4]        # "8544" (4-digit)
    ]

    for prefix in prefixes:
        row = IeepaAnnexIIExclusion.query.filter_by(
            hts_code=prefix.replace(".", "")
        ).first()
        if row:
            return {"excluded": True, "category": row.category}

    return {"excluded": False}
```

### 13.4 Complete Example: USB-C Cable from China

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.00
materials = {"copper": 3000.00, "steel": 1000.00, "aluminum": 1000.00}
```

**Step-by-Step Database Queries:**

```
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: get_applicable_programs("China", "8544.42.9090")                   │
├────────────────────────────────────────────────────────────────────────────┤
│ Query: SELECT * FROM tariff_programs                                       │
│        WHERE (country = 'China' OR country = 'ALL')                        │
│        ORDER BY filing_sequence                                            │
│                                                                            │
│ Result:                                                                    │
│   1. section_301       (China, check_type="hts_lookup")                    │
│   2. ieepa_fentanyl    (China, check_type="always")                        │
│   3. ieepa_reciprocal  (China, check_type="always", has dependency)        │
│   4. section_232_copper (ALL, check_type="hts_lookup")                     │
│   5. section_232_steel  (ALL, check_type="hts_lookup")                     │
│   6. section_232_aluminum (ALL, check_type="hts_lookup")                   │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: check_program_inclusion("section_301", "8544.42.9090")             │
├────────────────────────────────────────────────────────────────────────────┤
│ Query: SELECT * FROM section_301_inclusions                                │
│        WHERE hts_8digit = '85444290'                                       │
│                                                                            │
│ Result: ✅ FOUND                                                           │
│   list_name = "list_3"                                                     │
│   chapter_99_code = "9903.88.03"                                           │
│   duty_rate = 0.25 (25%)                                                   │
│                                                                            │
│ Decision: Section 301 APPLIES with 9903.88.03                              │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: check_program_inclusion("section_232_copper", "8544.42.9090")      │
├────────────────────────────────────────────────────────────────────────────┤
│ Query: SELECT * FROM section_232_materials                                 │
│        WHERE hts_8digit = '85444290' AND material = 'copper'               │
│                                                                            │
│ Result: ✅ FOUND                                                           │
│   claim_code = "9903.78.01"                                                │
│   disclaim_code = "9903.78.02"                                             │
│   duty_rate = 0.50 (50%)                                                   │
│                                                                            │
│ Decision: Copper IS IN SCOPE for this HTS                                  │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: check_program_inclusion("section_232_steel", "8544.42.9090")       │
├────────────────────────────────────────────────────────────────────────────┤
│ Query: SELECT * FROM section_232_materials                                 │
│        WHERE hts_8digit = '85444290' AND material = 'steel'                │
│                                                                            │
│ Result: ✅ FOUND (added Aug 2025 per CSMS #65936570)                       │
│   claim_code = "9903.80.01"                                                │
│   disclaim_code = "9903.80.02"                                             │
│   duty_rate = 0.50 (50%)                                                   │
│                                                                            │
│ Decision: Steel IS IN SCOPE for this HTS                                   │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: check_annex_ii_exclusion("8544.42.9090")                           │
├────────────────────────────────────────────────────────────────────────────┤
│ Query: SELECT * FROM ieepa_annex_ii_exclusions                             │
│        WHERE hts_code IN ('8544429090', '85444290', '854442', '8544')      │
│                                                                            │
│ Result: ❌ NOT FOUND                                                       │
│                                                                            │
│ Decision: NOT exempt from IEEPA Reciprocal                                 │
│           → Use 9903.01.25 (taxable) for non-metal slices                  │
│           → Use 9903.01.33 (metal_exempt) for metal slices                 │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: plan_entry_slices() - Determine ACE filing structure               │
├────────────────────────────────────────────────────────────────────────────┤
│ User provided:                                                             │
│   copper = $3,000                                                          │
│   steel = $1,000                                                           │
│   aluminum = $1,000                                                        │
│   residual = $10,000 - $3,000 - $1,000 - $1,000 = $5,000                   │
│                                                                            │
│ Result: 4 slices planned                                                   │
│   1. non_metal (residual): $5,000                                          │
│   2. copper_slice: $3,000                                                  │
│   3. steel_slice: $1,000                                                   │
│   4. aluminum_slice: $1,000                                                │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: build_entry_stacks() - Build Chapter 99 stack per slice            │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│ copper_slice ($3,000):                                                     │
│   Query program_codes for each program:                                    │
│     section_301 → 9903.88.03 (25%)                                         │
│     ieepa_fentanyl → 9903.01.24 (10%)                                      │
│     ieepa_reciprocal → 9903.01.33 (0%, metal_exempt)                       │
│     section_232_copper → 9903.78.01 (50%, CLAIM)                           │
│     section_232_steel → OMIT (disclaim_behavior='omit')                    │
│     section_232_aluminum → OMIT (disclaim_behavior='omit')                 │
│                                                                            │
│   Stack: [9903.88.03, 9903.01.24, 9903.01.33, 9903.78.01, 8544.42.9090]    │
│                                                                            │
│ non_metal slice ($5,000):                                                  │
│   Stack: [9903.88.03, 9903.01.24, 9903.01.25, 9903.78.02, 8544.42.9090]    │
│          (Note: 9903.78.02 = copper DISCLAIM, required in other slices)    │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 13.5 Key Files in the Lookup Flow

| File | Purpose | Key Functions |
|------|---------|---------------|
| `scripts/populate_tariff_tables.py` | One-time data population | `populate_section_301_inclusions()`, `populate_section_232_materials()` |
| `app/web/db/models/tariff_tables.py` | Database models | `TariffProgram`, `Section301Inclusion`, `Section232Material` |
| `app/chat/tools/stacking_tools.py` | Runtime query tools | `get_applicable_programs()`, `check_program_inclusion()`, `check_annex_ii_exclusion()` |
| `app/chat/graphs/stacking_rag.py` | LangGraph workflow | `initialize_node()`, `build_entry_stacks_node()` |

### 13.6 Limitations of Current Approach

| Limitation | Impact | Potential Solution |
|------------|--------|-------------------|
| **Static data** | Requires manual updates when CBP/BIS changes lists | Auto-fetch from CBP RSS/API |
| **No real-time verification** | Can't confirm if our data matches current CBP | MCP server to query CBP |
| **Manual PDF parsing** | New HTS codes require script updates | AI-powered PDF extraction |
| **No product classification** | User must know HTS code upfront | Gemini-powered HTS lookup |

### 13.7 Future Enhancement: AI-Powered Scope Verification

A potential MCP server could provide real-time verification:

```
┌─────────────────────────────────────────────────────────────────┐
│                  PROPOSED: MCP SEARCH LAYER                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐                     ┌──────────────────┐       │
│  │ User Input  │                     │  MCP Server      │       │
│  │ HTS: 8544.. │──────┬─────────────▶│  (hts-lookup)    │       │
│  └─────────────┘      │              │                  │       │
│                       │              │  1. Query DB     │       │
│                       │              │  2. If not found:│       │
│  ┌─────────────┐      │              │     → WebSearch  │       │
│  │ PostgreSQL  │◀─────┤              │     → Gemini API │       │
│  │   (cache)   │      │              │  3. Cache result │       │
│  └─────────────┘      │              │  4. Return scope │       │
│                       │              └──────────────────┘       │
│                       │                       │                 │
│                       │              ┌────────▼────────┐        │
│                       │              │ External Sources│        │
│                       │              │ • CBP CSMS RSS  │        │
│                       │              │ • HTS.usitc.gov │        │
│                       │              │ • Gemini Search │        │
│                       │              └─────────────────┘        │
│                       │                                         │
│                       ▼                                         │
│              ┌─────────────────┐                                │
│              │ Stacking Engine │                                │
│              │ (unchanged)     │                                │
│              └─────────────────┘                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Benefits:**
1. Real-time verification against CBP sources
2. Auto-discover new HTS codes added to 232 lists
3. AI-powered product → HTS classification
4. Cache results in database for performance

---

## 14. Gemini MCP Search Integration Design (v8.0)

**Date:** January 2026
**Status:** Design Document
**Version:** v8.0 - AI-Powered Search Layer

### 14.1 Executive Summary

Integrate Google Gemini 3 Pro with MCP (Model Context Protocol) to provide AI-powered real-time verification of HTS code scope. The system will:

1. **Check local database first** (existing behavior)
2. **If not found OR stale**, call Gemini via MCP for live search
3. **Cache results** with provenance metadata (model, timestamp, sources)
4. **Never re-search** once data is populated and verified

### 14.2 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    v8.0 GEMINI MCP SEARCH ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐                                                            │
│  │ User Input  │                                                            │
│  │ HTS: 8544.. │                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    STACKING ENGINE                            │          │
│  │  1. Query local DB for scope                                  │          │
│  │  2. Check: is_verified=True AND search_updated_at < 30 days? │          │
│  └──────────────────────┬───────────────────────────────────────┘          │
│                         │                                                   │
│         ┌───────────────┴───────────────┐                                  │
│         │                               │                                  │
│         ▼                               ▼                                  │
│  ┌─────────────┐                ┌─────────────────────┐                    │
│  │ DB HIT ✅   │                │ DB MISS or STALE ❓  │                    │
│  │ Use cached  │                │ Call MCP Server     │                    │
│  │ result      │                └──────────┬──────────┘                    │
│  └─────────────┘                           │                               │
│                                            ▼                               │
│                              ┌─────────────────────────┐                   │
│                              │   HTS-VERIFIER MCP      │                   │
│                              │   (FastMCP + Gemini)    │                   │
│                              │                         │                   │
│                              │  ┌─────────────────┐    │                   │
│                              │  │ gemini-2.0-flash│    │ ← Testing        │
│                              │  │ (free tier)     │    │                   │
│                              │  └────────┬────────┘    │                   │
│                              │           │             │                   │
│                              │  ┌────────▼────────┐    │                   │
│                              │  │ gemini-3-pro    │    │ ← Production     │
│                              │  │ thinking="high" │    │                   │
│                              │  │ + google_search │    │                   │
│                              │  └────────┬────────┘    │                   │
│                              └───────────┼─────────────┘                   │
│                                          │                                  │
│                              ┌───────────▼───────────┐                     │
│                              │  Google Search API    │                     │
│                              │  (grounding sources)  │                     │
│                              └───────────┬───────────┘                     │
│                                          │                                  │
│                              ┌───────────▼───────────┐                     │
│                              │  Return + Cache       │                     │
│                              │  • scope result       │                     │
│                              │  • source URLs        │                     │
│                              │  • model used         │                     │
│                              │  • timestamp          │                     │
│                              └───────────────────────┘                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 14.3 Database Schema Changes

#### New Provenance Columns for `section_232_materials`

```sql
ALTER TABLE section_232_materials ADD COLUMN search_model VARCHAR(64);
ALTER TABLE section_232_materials ADD COLUMN search_updated_at TIMESTAMP;
ALTER TABLE section_232_materials ADD COLUMN search_source VARCHAR(32);
ALTER TABLE section_232_materials ADD COLUMN grounding_urls JSONB;
ALTER TABLE section_232_materials ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE section_232_materials ADD COLUMN verification_notes TEXT;
```

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `search_model` | VARCHAR(64) | Which AI model was used | `"gemini-3-pro-preview"`, `"manual"` |
| `search_updated_at` | TIMESTAMP | When scope was last verified | `2026-01-02 14:30:00` |
| `search_source` | VARCHAR(32) | How data was obtained | `"gemini_mcp"`, `"manual"`, `"csms_bulletin"` |
| `grounding_urls` | JSONB | Source URLs from search | `["https://cbp.gov/...", "https://..."]` |
| `is_verified` | BOOLEAN | Human-verified flag | `true` = don't re-search |
| `verification_notes` | TEXT | Human notes | `"Confirmed per CSMS #65936570"` |

**Same columns to be added to:**
- `section_301_inclusions`
- `ieepa_annex_ii_exclusions`

### 14.4 Two-Tier Model Strategy

| Tier | Model | Cost | Use Case |
|------|-------|------|----------|
| **Test** | `gemini-2.5-flash` | Free tier available | Development, CI/CD, bulk verification |
| **Production** | `gemini-3-pro-preview` | Paid | Real-time user queries, high-confidence verification |

**Key Configuration:**
- **Thinking Mode:** `high` (budget: 16384 tokens) for production model
- **Google Search Grounding:** Enabled for both tiers
- **Cache TTL:** 30 days (re-verify after 30 days if not manually verified)

### 14.5 MCP Server Implementation

#### File Structure

```
lanes/
├── mcp_servers/              # Named to avoid conflict with pip 'mcp' package
│   ├── __init__.py
│   ├── hts_verifier.py       # Main MCP server (FastMCP)
│   ├── config.py             # API keys, model selection
│   └── test_gemini.py        # Test script
```

#### Core MCP Tool: `verify_hts_scope`

```python
from mcp.server.fastmcp import FastMCP
from google import genai
from google.genai import types

mcp = FastMCP("hts-verifier")

@mcp.tool()
def verify_hts_scope(
    hts_code: str,
    material: str = "all",
    use_production_model: bool = False,
    force_search: bool = False
) -> dict:
    """
    Verify Section 232 material scope for an HTS code using Gemini search.

    Args:
        hts_code: The HTS code to verify (e.g., "8544.42.9090")
        material: Specific material ("copper", "steel", "aluminum", "all")
        use_production_model: If True, use Gemini 3 Pro; else use Flash (free)
        force_search: If True, bypass cache and force fresh Gemini search
                      (even if is_verified=True or recently updated)

    Returns:
        dict with scope info, sources, and metadata (includes force_search flag)
    """
    model_id = "gemini-3-pro-preview" if use_production_model else "gemini-2.0-flash-exp"

    # Configure with Google Search grounding + thinking mode
    search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[search_tool],
        thinking_config=types.ThinkingConfig(thinking_budget=10000)
            if "gemini-3" in model_id else None
    )

    # Verification prompt
    prompt = f"""
    You are a U.S. Customs and Border Protection (CBP) tariff expert.

    Task: Determine if HTS code {hts_code} is subject to Section 232 tariffs
    for {material if material != 'all' else 'copper, steel, and/or aluminum'}.

    Search for:
    1. Official CBP CSMS bulletins mentioning this HTS code
    2. The "LIST OF STEEL HTS SUBJECT TO SECTION 232" (effective Aug 18, 2025)
    3. The aluminum and copper derivative lists
    4. Federal Register notices about Section 232 inclusions

    Return JSON:
    {{
        "hts_code": "{hts_code}",
        "copper": {{"in_scope": bool, "claim_code": "...", "source": "..."}},
        "steel": {{"in_scope": bool, "claim_code": "...", "source": "..."}},
        "aluminum": {{"in_scope": bool, "claim_code": "...", "source": "..."}}
    }}
    """

    response = client.models.generate_content(
        model=model_id, contents=prompt, config=config
    )

    # Extract grounding URLs from response metadata
    grounding_urls = extract_grounding_urls(response)

    return {
        "scope": parse_json_response(response.text),
        "metadata": {
            "model": model_id,
            "timestamp": datetime.utcnow().isoformat(),
            "grounding_urls": grounding_urls,
            "force_search": force_search  # Track if this was a forced refresh
        }
    }
```

### 14.6 Integration with Stacking Tools

```python
# app/chat/tools/stacking_tools.py

def check_program_inclusion_with_mcp(
    program_id: str,
    hts_code: str,
    force_search: bool = False  # NEW: Force bypass of all caching
) -> dict:
    """
    Check program inclusion with MCP fallback for missing/stale data.

    Args:
        program_id: The tariff program to check (e.g., "section_232_steel")
        hts_code: The HTS code to verify
        force_search: If True, skip ALL cache checks and go directly to Gemini
                      Use when: regulations changed, suspect stale data, manual verify
    """

    # FORCE SEARCH: Skip all cache logic, go directly to MCP
    if force_search:
        mcp_result = call_hts_verifier_mcp(hts_code, program_id, force_search=True)
        if mcp_result.get("scope"):
            update_inclusion_from_mcp(program_id, hts_code, mcp_result)
        return mcp_result

    # Step 1: Check local database first (normal flow)
    db_result = check_program_inclusion(program_id, hts_code)

    if db_result.get("included"):
        row = get_inclusion_row(program_id, hts_code)
        if row:
            # If verified, use cached result (don't re-search unless forced)
            if getattr(row, 'is_verified', False):
                return db_result

            # If recent (< 30 days), use cached
            search_updated_at = getattr(row, 'search_updated_at', None)
            if search_updated_at:
                age_days = (datetime.utcnow() - search_updated_at).days
                if age_days < 30:
                    return db_result

    # Step 2: Not found or stale - call MCP
    mcp_result = call_hts_verifier_mcp(hts_code, program_id)

    # Step 3: Cache result in database
    if mcp_result.get("scope"):
        update_inclusion_from_mcp(program_id, hts_code, mcp_result)

    return mcp_result
```

### 14.7 Claude Code MCP Configuration

```bash
# Add the HTS Verifier MCP server to Claude Code
claude mcp add --transport stdio hts-verifier \
  --env GEMINI_API_KEY=$GEMINI_API_KEY \
  -- python -m mcp_servers.hts_verifier
```

**Usage Examples:**

**Normal Query (uses cache if available):**
```
User: Is HTS 7326.90.8688 subject to Section 232 steel duties?

Claude: Let me verify this using the HTS Verifier...
[Calls mcp__hts-verifier__verify_hts_scope("7326.90.8688", "steel")]

Result: Yes, HTS 7326.90.8688 is in scope for Section 232 steel duties.
- Claim code: 9903.80.01
- Source: CBP CSMS #65936570 (Aug 15, 2025)
- Verified by: gemini-3-pro-preview
- Cache status: Used cached result (verified 2 days ago)
```

**Force Search (bypass cache, get fresh data):**
```
User: Force refresh the scope for HTS 8544.42.9090 - I think regulations changed

Claude: I'll force a fresh search, bypassing the cache...
[Calls mcp__hts-verifier__verify_hts_scope("8544.42.9090", "all", force_search=True)]

Result: Fresh verification complete for HTS 8544.42.9090:
- Copper: IN SCOPE (9903.78.01)
- Steel: IN SCOPE (9903.80.01)
- Aluminum: IN SCOPE (9903.85.01)
- Source: CBP Steel List (Aug 18, 2025), Copper Derivatives List
- Verified by: gemini-3-pro-preview (FORCED REFRESH)
- Previous cache invalidated and updated
```

### 14.8 Implementation Phases

| Phase | Description | Days |
|-------|-------------|------|
| **Phase 1** | Database schema changes (new provenance columns) | 1 |
| **Phase 2** | MCP Server implementation (FastMCP + Gemini) | 2-3 |
| **Phase 3** | Integration with stacking_tools.py | 1 |
| **Phase 4** | Testing & documentation | 1 |

### 14.9 Files Created/Modified

| File | Status | Description |
|------|--------|-------------|
| `mcp_servers/hts_verifier.py` | CREATED | FastMCP server with Gemini integration |
| `mcp_servers/config.py` | CREATED | Configuration for models, API keys |
| `mcp_servers/__init__.py` | CREATED | Package init |
| `mcp_servers/test_gemini.py` | CREATED | Test script for Gemini API |
| `.env` | MODIFIED | Added GEMINI_API_KEY |
| `Pipfile` | MODIFIED | Added `google-genai`, `mcp` packages |
| `app/web/db/models/tariff_tables.py` | TODO | Add search metadata columns |
| `app/chat/tools/stacking_tools.py` | TODO | Add MCP fallback logic |

### 14.10 Cost Considerations

| Model | Pricing | When to Use |
|-------|---------|-------------|
| `gemini-2.5-flash` | Free tier (rate limited) | Development, bulk verification |
| `gemini-3-pro-preview` | Paid (requires billing) | User-facing queries, high-confidence |
| Google Search Grounding | Included | All searches |

**Recommendation:** Use Flash for development/testing, Pro for production user-triggered verification.

**Note:** Free tier has rate limits (requests per minute/day). Enable billing for production use.

### 14.11 Security Notes

1. **API Key Storage:** Use environment variables, never commit keys
2. **Rate Limiting:** Implement rate limiting to avoid API quota issues
3. **Caching:** Always cache results to minimize API calls
4. **Verification Flag:** Human-verified data (`is_verified=True`) won't re-search automatically (but `force_search=True` can override)

### 14.12 Force Search: When and How to Use

The `force_search` parameter bypasses ALL caching logic and forces a fresh Gemini search, even for verified data.

#### When to Use Force Search

| Scenario | Why Force Search? |
|----------|-------------------|
| **Regulation Change** | CBP issued new CSMS bulletin, lists updated |
| **Suspected Stale Data** | You believe cached data is incorrect |
| **Manual Verification** | User wants to double-check against live sources |
| **New HTS Added to List** | A previously excluded HTS is now included |
| **Audit/Compliance** | Need documented fresh verification with timestamp |
| **After System Downtime** | Re-verify data after extended offline period |

#### Force Search Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    FORCE SEARCH FLOW                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐                                             │
│  │ force_search=   │                                             │
│  │     True        │                                             │
│  └────────┬────────┘                                             │
│           │                                                      │
│           │ SKIP ALL CACHE CHECKS                                │
│           │ • Skip is_verified check                             │
│           │ • Skip search_updated_at check                       │
│           │ • Skip 30-day TTL check                              │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐     ┌─────────────────┐                     │
│  │ Call Gemini MCP │────▶│ Fresh Search    │                     │
│  │ Directly        │     │ via Google API  │                     │
│  └─────────────────┘     └────────┬────────┘                     │
│                                   │                              │
│                                   ▼                              │
│                          ┌─────────────────┐                     │
│                          │ UPDATE Cache    │                     │
│                          │ • New timestamp │                     │
│                          │ • New sources   │                     │
│                          │ • Model used    │                     │
│                          │ • force=True    │                     │
│                          └─────────────────┘                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### API Examples

```python
# Normal lookup (uses cache)
result = check_program_inclusion_with_mcp("section_232_steel", "8544.42.9090")

# Force fresh search (bypasses ALL caching)
result = check_program_inclusion_with_mcp(
    "section_232_steel",
    "8544.42.9090",
    force_search=True  # <-- Bypass cache, hit Gemini
)

# MCP tool call with force search
mcp__hts-verifier__verify_hts_scope(
    hts_code="8544.42.9090",
    material="all",
    use_production_model=True,
    force_search=True
)
```

#### Best Practices

1. **Don't overuse:** Force search costs API calls - use only when needed
2. **Log force searches:** Track who triggered and why (audit trail)
3. **Rate limit:** Max 10 force searches per hour per user
4. **Notify on changes:** If force search returns different result than cache, alert user

---

## 15. Search Persistence & Vector Caching (v9.0 Implementation)

**Date:** January 2026
**Status:** Implemented

This section documents the fully implemented v9.0 Search Persistence & Vector Caching architecture that persists Gemini search results to avoid redundant expensive API calls.

### 15.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                v9.0 SEARCH PERSISTENCE & VECTOR CACHING                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐                                                            │
│  │ User Query  │                                                            │
│  │ HTS: 8544.. │                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │              LAYER 1: PostgreSQL Structured Cache             │          │
│  │  Query: SELECT * FROM gemini_search_results WHERE hts=?      │          │
│  └──────────────────────┬───────────────────────────────────────┘          │
│                         │                                                   │
│         ┌───────────────┴───────────────┐                                  │
│         │                               │                                  │
│         ▼                               ▼                                  │
│  ┌─────────────┐                ┌─────────────────────┐                    │
│  │ DB HIT ✅   │                │ DB MISS             │                    │
│  │ Return      │                │ Check Pinecone      │                    │
│  │ cached JSON │                └──────────┬──────────┘                    │
│  └─────────────┘                           │                               │
│                                            ▼                               │
│                              ┌─────────────────────────┐                   │
│                              │ LAYER 2: Pinecone       │                   │
│                              │ Semantic Vector Search  │                   │
│                              │ Threshold: 0.85         │                   │
│                              └──────────┬──────────────┘                   │
│                                         │                                  │
│         ┌───────────────────────────────┴───────────────┐                  │
│         │                                               │                  │
│         ▼                                               ▼                  │
│  ┌─────────────────┐                           ┌─────────────────┐         │
│  │ VECTOR HIT ✅   │                           │ VECTOR MISS     │         │
│  │ Return cached   │                           │ Call Gemini     │         │
│  │ chunks          │                           └────────┬────────┘         │
│  └─────────────────┘                                    │                  │
│                                                         ▼                  │
│                                         ┌───────────────────────────┐      │
│                                         │ LAYER 3: Gemini Search    │      │
│                                         │ gemini-3-pro + thinking   │      │
│                                         │ + Google Search grounding │      │
│                                         └───────────┬───────────────┘      │
│                                                     │                      │
│                                                     ▼                      │
│                                         ┌───────────────────────────┐      │
│                                         │ PERSIST RESULTS           │      │
│                                         │ 1. PostgreSQL tables      │      │
│                                         │ 2. Pinecone vectors       │      │
│                                         │ 3. Audit log entry        │      │
│                                         └───────────────────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 15.2 New Database Tables

Three new tables store search results and metadata:

#### 15.2.1 `gemini_search_results`

Caches the structured JSON output from each Gemini search.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `hts_code` | VARCHAR(20) | HTS code searched |
| `query_type` | VARCHAR(32) | 'section_232', 'section_301', etc. |
| `material` | VARCHAR(16) | 'copper', 'steel', 'aluminum', 'all' |
| `result_json` | JSONB | Parsed Gemini response |
| `raw_response` | TEXT | Original response text |
| `model_used` | VARCHAR(64) | 'gemini-2.5-flash' or 'gemini-3-pro-preview' |
| `thinking_budget` | INTEGER | Thinking mode budget (null if not used) |
| `searched_at` | TIMESTAMP | When search was performed |
| `expires_at` | TIMESTAMP | Cache expiration (30 days default) |
| `is_verified` | BOOLEAN | Human-verified flag (never expires) |
| `was_force_search` | BOOLEAN | True if force_search was used |

**Unique Constraint:** `(hts_code, query_type, material)`

#### 15.2.2 `grounding_sources`

Tracks every URL Gemini used for grounding.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `search_result_id` | UUID | FK to gemini_search_results |
| `url` | TEXT | Source URL |
| `domain` | VARCHAR(255) | Extracted domain (cbp.gov, etc.) |
| `source_type` | VARCHAR(32) | 'official_cbp', 'federal_register', 'other' |
| `reliability_score` | DECIMAL(3,2) | 0.00 to 1.00 |
| `fetched_content` | TEXT | Optional cached page content |
| `content_hash` | VARCHAR(64) | SHA-256 for change detection |

#### 15.2.3 `search_audit_log`

Analytics and debugging for all search requests.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `hts_code` | VARCHAR(20) | HTS code queried |
| `query_type` | VARCHAR(32) | Type of query |
| `cache_hit` | BOOLEAN | Was cache used? |
| `cache_source` | VARCHAR(20) | 'postgres', 'pinecone', 'gemini' |
| `force_search` | BOOLEAN | Was force_search used? |
| `response_time_ms` | INTEGER | Response latency |
| `model_used` | VARCHAR(64) | Model if Gemini was called |
| `success` | BOOLEAN | Did the search succeed? |
| `input_tokens` | INTEGER | Token usage |
| `output_tokens` | INTEGER | Token usage |
| `estimated_cost_usd` | DECIMAL(10,6) | Estimated API cost |

### 15.3 Files Implemented

| File | Purpose |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Added 3 new SQLAlchemy models |
| `app/chat/vector_stores/tariff_search.py` | TariffVectorSearch class for Pinecone |
| `mcp_servers/search_cache.py` | 3-tier cache check and persistence logic |
| `mcp_servers/hts_verifier.py` | Updated with raw_response, query_type |
| `scripts/migrate_v9_search_tables.py` | Database migration script |

### 15.4 TariffVectorSearch Class

The `TariffVectorSearch` class in `app/chat/vector_stores/tariff_search.py` provides:

```python
class TariffVectorSearch:
    def chunk_and_embed(self, text: str, metadata: dict) -> List[Dict]:
        """Chunk text and create OpenAI embeddings for Pinecone."""

    def search_similar(self, query: str, hts_code: str = None, top_k: int = 5) -> List[Dict]:
        """Semantic search with optional HTS filter. Returns matches with scores."""

    def index_search_result(self, search_result_id: str, hts_code: str, ...) -> int:
        """Index Gemini response and grounding sources in Pinecone."""

    def delete_by_search_result(self, search_result_id: str) -> bool:
        """Delete vectors when force_search replaces cached result."""
```

**Configuration:**
- Index: `lanes-tariff-search`
- Embedding model: `text-embedding-3-small`
- Dimension: 1536
- Similarity threshold: 0.85

### 15.5 Cache Check Flow

The `verify_with_caching()` function in `mcp_servers/search_cache.py`:

```python
def verify_with_caching(
    session: Session,
    hts_code: str,
    query_type: str,
    material: Optional[str] = None,
    force_search: bool = False,
    gemini_callable=None,
    requested_by: Optional[str] = None
) -> Dict:
    """
    Main entry point with full 3-tier caching logic.

    1. Check PostgreSQL cache (unless force_search)
    2. Check Pinecone cache (unless force_search)
    3. Call Gemini if no cache hit
    4. Persist results to both caches
    5. Log to audit trail
    """
```

### 15.6 Source Reliability Scoring

Grounding sources are automatically scored by domain:

| Domain | Source Type | Reliability Score |
|--------|-------------|-------------------|
| `cbp.gov` | official_cbp | 1.00 |
| `federalregister.gov` | federal_register | 1.00 |
| `ustr.gov` | ustr | 0.95 |
| `usitc.gov` | usitc | 0.95 |
| Other | other | 0.50 |

### 15.7 Cost Tracking

The audit log estimates API costs based on token usage:

| Model | Input Cost/1K | Output Cost/1K |
|-------|---------------|----------------|
| `gemini-3-pro-preview` | $0.0375 | $0.15 |
| `gemini-2.5-flash` | $0.00015 | $0.0006 |

### 15.8 Usage Examples

#### Run Migration
```bash
# Create the new tables
pipenv run python scripts/migrate_v9_search_tables.py

# Reset tables (WARNING: deletes cached data)
pipenv run python scripts/migrate_v9_search_tables.py --reset

# View statistics
pipenv run python scripts/migrate_v9_search_tables.py --stats
```

#### MCP Server Output Format
```python
# verify_hts_scope now includes raw_response for caching
{
    "success": True,
    "scope": {
        "hts_code": "8544.42.9090",
        "copper": {"in_scope": True, "claim_code": "9903.78.01"},
        "steel": {"in_scope": True, "claim_code": "9903.80.01"},
        "aluminum": {"in_scope": True, "claim_code": "9903.85.01"}
    },
    "raw_response": "Full Gemini response text...",  # NEW in v9.0
    "metadata": {
        "model": "gemini-3-pro-preview",
        "timestamp": "2026-01-02T15:30:00",
        "grounding_urls": ["https://cbp.gov/...", "https://..."],
        "force_search": False,
        "material_queried": "all",
        "thinking_budget": 16384,  # NEW in v9.0
        "query_type": "section_232"  # NEW in v9.0
    }
}
```

### 15.9 Testing

The v9.0 implementation includes:

1. **Migration test:** `scripts/migrate_v9_search_tables.py` runs successfully
2. **Gemini MCP tests:** `mcp_servers/test_gemini.py` - 3/3 passing
3. **Model unit tests:** See `tests/test_v9_search_persistence.py`
4. **Integration tests:** See `tests/test_v9_cache_integration.py`

### 15.10 Cache Invalidation Rules

| Condition | Action |
|-----------|--------|
| `is_verified = True` | Never expires, never re-searches |
| `expires_at < now()` | Cache miss, triggers new search |
| `force_search = True` | Bypass all caches, update cache after |
| 30 days since search | Auto-expire (unless verified) |

### 15.11 Monitoring Dashboard Queries

```sql
-- Cache hit rate
SELECT
    COUNT(*) FILTER (WHERE cache_hit = true) * 100.0 / COUNT(*) as hit_rate_pct
FROM search_audit_log
WHERE requested_at > NOW() - INTERVAL '7 days';

-- Top 10 most expensive searches
SELECT hts_code, query_type, SUM(estimated_cost_usd) as total_cost
FROM search_audit_log
WHERE cache_hit = false
GROUP BY hts_code, query_type
ORDER BY total_cost DESC
LIMIT 10;

-- Grounding source reliability breakdown
SELECT source_type, COUNT(*), AVG(reliability_score)
FROM grounding_sources
GROUP BY source_type;
```

---

## 16. Gemini Parsing & Validation Architecture (v9.1)

**Date:** January 2026
**Status:** Implemented
**Version:** v9.1 - Complete Parsing, Validation & Testing

This section documents how Gemini search outputs are parsed, validated, and stored. It answers: "How does the system convert Gemini's text response into structured database records?"

### 16.1 Overview: No LLM Call for Parsing

**Key Insight:** The parsing is **simple string extraction**, NOT an LLM call. We trust Gemini to return JSON (as instructed in the prompt), extract it, and optionally validate against a Pydantic schema.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COMPLETE GEMINI PARSING FLOW                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      STEP 1: GEMINI API CALL                         │    │
│  │                                                                      │    │
│  │  client.models.generate_content(                                     │    │
│  │      model="gemini-3-pro-preview",                                   │    │
│  │      contents=prompt,           ← Contains JSON format instructions  │    │
│  │      config=GenerateContentConfig(                                   │    │
│  │          tools=[google_search], ← Google Search grounding enabled    │    │
│  │          thinking_config=...    ← High thinking mode for production  │    │
│  │      )                                                               │    │
│  │  )                                                                   │    │
│  └──────────────────────────────────┬──────────────────────────────────┘    │
│                                     │                                        │
│                                     ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      GEMINI API RESPONSE                             │    │
│  │                                                                      │    │
│  │  response.text = "Based on my search of CBP sources, here is...     │    │
│  │                                                                      │    │
│  │  {                                                                   │    │
│  │    \"hts_code\": \"8544.42.9090\",                                  │    │
│  │    \"copper\": {\"in_scope\": true, \"claim_code\": \"9903.78.01\"},│    │
│  │    \"steel\": {\"in_scope\": true, \"claim_code\": \"9903.80.01\"}, │    │
│  │    \"aluminum\": {\"in_scope\": true, ...}                          │    │
│  │  }                                                                   │    │
│  │                                                                      │    │
│  │  This is based on CSMS #65936570..."                                │    │
│  │                                                                      │    │
│  │  response.candidates[0].grounding_metadata.grounding_chunks = [     │    │
│  │    {web: {uri: "https://cbp.gov/..."}},                             │    │
│  │    {web: {uri: "https://federalregister.gov/..."}}                  │    │
│  │  ]                                                                   │    │
│  └──────────────────────────────────┬──────────────────────────────────┘    │
│                                     │                                        │
│         ┌───────────────────────────┴───────────────────────────┐           │
│         │                                                       │           │
│         ▼                                                       ▼           │
│  ┌─────────────────────────┐                   ┌─────────────────────────┐  │
│  │  STEP 2a: PARSE JSON    │                   │  STEP 2b: EXTRACT URLs  │  │
│  │                         │                   │                         │  │
│  │  parse_json_response()  │                   │  extract_grounding_urls()│  │
│  │  • find('{')            │                   │  • candidates[0]        │  │
│  │  • rfind('}')           │                   │  • grounding_metadata   │  │
│  │  • json.loads()         │                   │  • grounding_chunks     │  │
│  │  • NO LLM CALL!         │                   │  • .web.uri             │  │
│  └────────────┬────────────┘                   └────────────┬────────────┘  │
│               │                                              │               │
│               ▼                                              ▼               │
│        scope_data (dict)                           grounding_urls (list)    │
│               │                                              │               │
│               │                                              │               │
│               ▼                                              │               │
│  ┌─────────────────────────┐                                 │               │
│  │  STEP 3: VALIDATE       │                                 │               │
│  │                         │                                 │               │
│  │  validate_section_232() │                                 │               │
│  │  • Pydantic strict mode │                                 │               │
│  │  • Catches type errors  │                                 │               │
│  │  • Returns is_valid     │                                 │               │
│  └────────────┬────────────┘                                 │               │
│               │                                              │               │
│               └──────────────────┬───────────────────────────┘               │
│                                  │                                           │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                   STEP 4: MCP TOOL RETURN VALUE                      │    │
│  │                                                                      │    │
│  │  {                                                                   │    │
│  │    "success": True,                                                  │    │
│  │    "scope": {                      ← Parsed JSON (may be unvalidated)│    │
│  │      "hts_code": "8544.42.9090",                                    │    │
│  │      "copper": {"in_scope": true, "claim_code": "9903.78.01"},      │    │
│  │      "steel": {"in_scope": true, "claim_code": "9903.80.01"},       │    │
│  │      ...                                                             │    │
│  │    },                                                                │    │
│  │    "raw_response": "Full Gemini response text...",  ← For debugging │    │
│  │    "metadata": {                                                     │    │
│  │      "model": "gemini-3-pro-preview",                               │    │
│  │      "timestamp": "2026-01-02T15:30:00",                            │    │
│  │      "grounding_urls": ["https://cbp.gov/..."],                     │    │
│  │      "thinking_budget": 16384,                                      │    │
│  │      "query_type": "section_232"                                    │    │
│  │    },                                                                │    │
│  │    "validation": {                  ← NEW in v9.1                    │    │
│  │      "is_valid": true,              ← Schema validation passed       │    │
│  │      "error": null                  ← Error message if failed        │    │
│  │    }                                                                 │    │
│  │  }                                                                   │    │
│  └──────────────────────────────────┬──────────────────────────────────┘    │
│                                     │                                        │
│                                     ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                   STEP 5: PERSIST TO DATABASE                        │    │
│  │                                                                      │    │
│  │  persist_search_result() in mcp_servers/search_cache.py             │    │
│  │                                                                      │    │
│  │  1. Create GeminiSearchResult record:                                │    │
│  │     - result_json = scope_data (JSONB column)                       │    │
│  │     - raw_response = original text                                  │    │
│  │     - model_used, searched_at, expires_at                           │    │
│  │                                                                      │    │
│  │  2. For each URL in grounding_urls:                                 │    │
│  │     - extract_domain(url) → domain                                  │    │
│  │     - classify_source_type(domain) → source_type                    │    │
│  │     - get_reliability_score(source_type) → score (0.0 - 1.0)        │    │
│  │     - Create GroundingSource record                                 │    │
│  │                                                                      │    │
│  │  3. Log to SearchAuditLog (response time, tokens, cost)             │    │
│  │                                                                      │    │
│  │  4. Index in Pinecone (chunk, embed, upsert)                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 16.2 How We Tell Gemini to Output JSON

The prompt in `mcp_servers/hts_verifier.py` (lines 131-177) explicitly requests JSON:

```python
prompt = f"""You are a U.S. Customs and Border Protection (CBP) tariff expert...

TASK: Determine if HTS code {hts_code} is subject to Section 232 tariffs...

Return your answer as JSON:
{{
    "hts_code": "{hts_code}",
    "copper": {{
        "in_scope": true/false,
        "claim_code": "9903.78.01 or null",
        "disclaim_code": "9903.78.02",
        "source": "Document name and date"
    }},
    "steel": {{...}},
    "aluminum": {{...}},
    "notes": "Any additional context"
}}

Only return "in_scope": true if you find EXPLICIT evidence in official sources.
"""
```

**Important:** This is a **prompt-based request**. We are NOT using Gemini's structured output feature (`response_mime_type="application/json"`). The model returns free-form text that should contain JSON.

### 16.3 The Parsing Function: `parse_json_response()`

**File:** `mcp_servers/hts_verifier.py`, lines 66-76

```python
def parse_json_response(text: str) -> dict:
    """Extract JSON from Gemini response text."""
    try:
        # Find JSON in response
        json_start = text.find('{')      # Find first opening brace
        json_end = text.rfind('}') + 1   # Find last closing brace
        if json_start >= 0 and json_end > json_start:
            return json.loads(text[json_start:json_end])
    except json.JSONDecodeError:
        pass
    return {"raw_response": text}  # Fallback if parsing fails
```

**Key Characteristics:**
- Simple string manipulation, **NOT an LLM call**
- Finds the first `{` and last `}` in response text
- Uses standard `json.loads()` to parse
- **NO schema validation** at this stage
- Graceful degradation: returns `{"raw_response": text}` on failure

### 16.4 The Grounding URL Extractor: `extract_grounding_urls()`

**File:** `mcp_servers/hts_verifier.py`, lines 48-63

```python
def extract_grounding_urls(response) -> list:
    """Extract grounding source URLs from Gemini response metadata."""
    grounding_urls = []
    try:
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata
                if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                    for chunk in metadata.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web:
                            if hasattr(chunk.web, 'uri'):
                                grounding_urls.append(chunk.web.uri)
    except Exception:
        pass  # Silently handle missing metadata
    return grounding_urls
```

**Key Characteristics:**
- Defensive extraction with `hasattr()` checks at every level
- Navigates: `response.candidates[0].grounding_metadata.grounding_chunks[].web.uri`
- Returns empty list on any error (silent failure)

### 16.5 Schema Validation with Pydantic

**File:** `mcp_servers/schemas.py`

The v9.1 update adds Pydantic validation with **strict mode** to catch type mismatches:

```python
from pydantic import BaseModel, ConfigDict
from typing import Optional

class MetalScope(BaseModel):
    """Schema for individual metal scope result.

    Uses strict mode to prevent string->bool coercion.
    E.g., "yes" should NOT become True.
    """
    model_config = ConfigDict(strict=True)

    in_scope: bool                      # MUST be boolean, not "yes" or "true"
    claim_code: Optional[str] = None
    disclaim_code: Optional[str] = None
    source: Optional[str] = None


class Section232Result(BaseModel):
    """Schema for Section 232 verification result."""
    model_config = ConfigDict(strict=True)

    hts_code: str
    copper: MetalScope
    steel: MetalScope
    aluminum: MetalScope
    notes: Optional[str] = None


def validate_section_232(parsed_json: dict) -> tuple[bool, Optional[Section232Result], Optional[str]]:
    """
    Validate parsed JSON against Section 232 schema.

    Returns:
        (is_valid, validated_result, error_message)
    """
    if "raw_response" in parsed_json and len(parsed_json) == 1:
        return False, None, "JSON parsing failed - raw response returned"

    try:
        result = Section232Result(**parsed_json)
        return True, result, None
    except Exception as e:
        return False, None, str(e)
```

**Why Strict Mode?**
- Without strict mode, Pydantic v2 coerces `"yes"` → `True` and `"true"` → `True`
- This could silently accept malformed Gemini output
- Strict mode ensures `in_scope: true` must be a real boolean

### 16.6 What IS Validated vs NOT Validated

| Validation Layer | What It Checks | Example Catch |
|------------------|----------------|---------------|
| **JSON syntax** (`json.loads()`) | Valid JSON structure | `{incomplete...` |
| **URL format** (`urlparse()`) | Valid URL for domain extraction | `not-a-url` |
| **Pydantic schema** | Required fields present | Missing `copper` key |
| **Pydantic strict** | Correct types | `"yes"` instead of `true` |

| NOT Validated | Risk | Example |
|---------------|------|---------|
| Value correctness | Wrong claim code stored | `claim_code: "wrong"` |
| Source reliability | Gemini may cite bad source | Non-CBP website |
| Completeness | Gemini may omit metals | Missing aluminum entirely |

### 16.7 Complete Test Suite

**File:** `tests/test_mcp_parsing.py` - 33 tests covering all parsing scenarios

#### 16.7.1 parse_json_response() Tests

| Test | What It Verifies |
|------|------------------|
| `test_valid_json_only` | Pure JSON parses correctly |
| `test_json_with_preamble` | Text before JSON is ignored |
| `test_json_with_postamble` | Text after JSON is ignored |
| `test_json_with_preamble_and_postamble` | Surrounding text handled |
| `test_nested_json` | Deep nesting works |
| `test_invalid_json_returns_raw` | Fallback on bad JSON |
| `test_partial_json_returns_raw` | Incomplete JSON handled |
| `test_empty_string` | Empty input returns raw_response |
| `test_json_with_markdown_code_block` | ```json blocks work |
| `test_multiple_json_objects_takes_outer` | Outermost JSON used |
| `test_json_with_arrays` | Arrays parse correctly |
| `test_unicode_in_json` | Unicode characters handled |
| `test_json_with_special_chars` | Special chars in strings work |

#### 16.7.2 Schema Validation Tests

| Test | What It Verifies |
|------|------------------|
| `test_valid_section_232_result` | Correct data passes |
| `test_missing_required_field_fails` | Missing `hts_code` caught |
| `test_wrong_type_for_in_scope` | `"yes"` string rejected |
| `test_string_true_coercion` | `"true"` string rejected |
| `test_section_301_valid_result` | Section 301 schema works |
| `test_section_301_minimal_valid` | Optional fields can be null |

#### 16.7.3 extract_grounding_urls() Tests

| Test | What It Verifies |
|------|------------------|
| `test_empty_response` | Empty candidates returns `[]` |
| `test_no_candidates` | `None` candidates handled |
| `test_candidates_no_metadata` | Missing metadata handled |
| `test_metadata_no_chunks` | Missing chunks handled |
| `test_single_grounding_url` | Single URL extracted |
| `test_multiple_grounding_urls` | Multiple URLs extracted |
| `test_chunk_without_web` | Chunks without `web` skipped |
| `test_exception_handling` | Exceptions return `[]` |

#### 16.7.4 Integration Tests

| Test | What It Verifies |
|------|------------------|
| `test_parse_then_validate_success` | Full workflow succeeds |
| `test_parse_success_validate_fail` | Valid JSON, invalid schema |
| `test_parse_fail_returns_raw` | Parse failure handled |
| `test_validation_helper_success` | Helper function works |
| `test_validation_helper_parse_failure` | Helper handles parse fail |
| `test_validation_helper_schema_failure` | Helper handles schema fail |

### 16.8 Running the Tests

```bash
# Run all parsing tests
pipenv run pytest tests/test_mcp_parsing.py -v

# Run all v9.0 persistence tests
pipenv run pytest tests/test_v9_search_persistence.py -v

# Run both together
pipenv run pytest tests/test_mcp_parsing.py tests/test_v9_search_persistence.py -v
# Expected: 56 passed
```

### 16.9 Expected JSON Schema from Gemini

#### Section 232 Response

```json
{
    "hts_code": "8544.42.9090",
    "copper": {
        "in_scope": true,
        "claim_code": "9903.78.01",
        "disclaim_code": "9903.78.02",
        "source": "CBP CSMS #65936570 (Aug 15, 2025)"
    },
    "steel": {
        "in_scope": true,
        "claim_code": "9903.80.01",
        "disclaim_code": "9903.80.02",
        "source": "Steel HTS List (Aug 18, 2025)"
    },
    "aluminum": {
        "in_scope": true,
        "claim_code": "9903.85.01",
        "disclaim_code": "9903.85.09",
        "source": "Aluminum Derivatives List"
    },
    "notes": "HTS 8544.42.9090 is insulated copper wire, classified as derivative"
}
```

#### Section 301 Response

```json
{
    "hts_code": "8544.42.9090",
    "included": true,
    "list_name": "list_3",
    "chapter_99_code": "9903.88.03",
    "duty_rate": 0.25,
    "source": "USTR Section 301 List 3",
    "exclusions": null,
    "notes": "25% duty on Chinese origin goods"
}
```

### 16.10 Potential Gemini Output Issues

| Issue | How We Handle It |
|-------|------------------|
| No JSON in response | `parse_json_response()` returns `{"raw_response": text}` |
| JSON parsing error | Fallback to raw_response, validation fails |
| `"in_scope": "yes"` | Pydantic strict mode rejects, `is_valid: false` |
| Missing metal key | Pydantic raises `ValidationError` |
| Extra narrative text | Extracted via `find('{')` / `rfind('}')` |
| Multiple JSON objects | Takes outermost (first `{` to last `}`) |

### 16.11 Future Improvement Options

#### Option A: Gemini Structured Output

Use Gemini's native JSON mode to enforce output format:

```python
config = types.GenerateContentConfig(
    tools=[google_search_tool],
    response_mime_type="application/json",  # Force JSON output
    response_schema=Section232Result        # Enforce Pydantic schema
)
```

**Status:** Not implemented (may conflict with Google Search grounding tool)

#### Option B: Fallback LLM Parsing

If JSON extraction fails, use a second LLM call to extract structured data:

```python
def fallback_parse(raw_response: str) -> dict:
    """Use a small model to extract JSON from messy text."""
    prompt = f"Extract JSON from: {raw_response}"
    # Call gemini-flash for cheap extraction
    ...
```

**Status:** Not implemented (current approach works well)

#### Option C: Retry with Clearer Prompt

On validation failure, retry with more explicit instructions:

```python
if not validation.is_valid:
    retry_prompt = f"""
    Your previous response was not valid JSON.
    Please return ONLY the JSON object, no other text:
    {schema_template}
    """
```

**Status:** Not implemented (adds latency and cost)

### 16.12 Files Reference

| File | Purpose |
|------|---------|
| `mcp_servers/hts_verifier.py` | MCP server with `parse_json_response()`, `extract_grounding_urls()` |
| `mcp_servers/schemas.py` | Pydantic schemas with strict mode validation |
| `mcp_servers/search_cache.py` | Cache persistence with `persist_search_result()` |
| `tests/test_mcp_parsing.py` | 33 parsing and validation tests |
| `tests/test_v9_search_persistence.py` | 23 persistence and caching tests |
| `app/chat/vector_stores/tariff_search.py` | Pinecone integration for vector caching |

### 16.13 Summary

1. **Gemini receives a prompt** asking for JSON output with specific schema
2. **Response text is parsed** using simple string extraction (`find` + `rfind` + `json.loads`)
3. **Grounding URLs are extracted** from response metadata
4. **Pydantic validates** the parsed JSON with strict mode (catches type errors)
5. **Results are persisted** to PostgreSQL (structured) and Pinecone (vector)
6. **Validation status is returned** so callers know if schema matched
7. **54 tests verify** all parsing, validation, and persistence logic

---

## 17. Evidence-First Citations Architecture (v9.2)

**Date:** January 2026
**Version:** v9.2 - Evidence-First Citations

### 17.1 Problem Statement

v9.1 stored vague source references like `"source": "CSMS bulletin"`. This was:
- **Not indexable** - Can't search for specific evidence
- **Not verifiable** - No way to click and confirm
- **Not auditable** - Can't prove to customs why a decision was made

### 17.2 Solution: Two-Layer Citation Strategy

```
                    Gemini Response
                          │
          ┌───────────────┼───────────────┐
          │               │               │
          ▼               ▼               ▼
   Google Grounding   JSON Output    Raw Response
   (Layer 1)          (Layer 2)
          │               │
          │               ├── copper.citations[].quoted_text
          │               ├── copper.citations[].source_url
          │               ├── copper.citations[].source_document
          │               │
          ▼               ▼
   grounding_sources   evidence_quotes
   (urls, titles)      (verbatim proofs)
```

**Layer 1 - Google Grounding (automatic):**
- URLs Gemini observed during search
- Page titles and generic snippets

**Layer 2 - Gemini Citations (prompt-controlled):**
- Specific quoted text that proves each claim
- Source URL where the quote was found
- This is the actual "proof"

### 17.3 New JSON Schema (v9.2)

Instead of `"source": "CSMS bulletin"`, we now ask for:

```json
{
  "hts_code": "8544.42.9090",
  "query_type": "section_232",
  "results": {
    "copper": {
      "in_scope": true,
      "claim_code": "9903.78.01",
      "disclaim_code": "9903.78.02",
      "citations": [
        {
          "source_url": "https://content.govdelivery.com/...",
          "source_title": "CBP CSMS #65936570",
          "source_document": "CSMS #65936570",
          "effective_date": "2025-08-18",
          "location_hint": "Table row: 8544.42.90",
          "evidence_type": "table",
          "quoted_text": "8544.42.90 - Insulated copper wire and cable"
        }
      ]
    },
    "steel": { "in_scope": true, "citations": [...] },
    "aluminum": { "in_scope": null, "citations": [...] }
  },
  "notes": null
}
```

Key changes:
- `citations[]` array replaces vague `source` string
- `in_scope: null` allowed for insufficient evidence
- `quoted_text` must be verbatim from the source
- Multiple citations supported per metal

### 17.4 Business Validation Rules

When `in_scope=true`, the response MUST have proof:

| Rule | Validation |
|------|------------|
| `claim_code` required | `in_scope=true` must have `claim_code` |
| Citation required | Must have ≥1 citation with `source_url` + `quoted_text` |
| HTS in quote (warning) | `quoted_text` should contain the HTS code |
| `in_scope=null` OK | Honest uncertainty doesn't require proof |
| `in_scope=false` OK | Negative determination doesn't require proof |

### 17.5 Pydantic Schemas

```python
# mcp_servers/schemas.py

class Citation(BaseModel):
    """Specific quoted evidence from source document."""
    model_config = ConfigDict(strict=True)

    source_url: str  # Required
    source_title: Optional[str] = None
    source_document: Optional[str] = None
    effective_date: Optional[str] = None
    location_hint: Optional[str] = None
    evidence_type: Optional[str] = None  # table|paragraph|bullet|scope_statement
    quoted_text: Optional[str] = None  # Verbatim, max 400 chars


class MetalScopeV2(BaseModel):
    """Schema for individual metal scope result WITH citations."""
    model_config = ConfigDict(strict=True)

    in_scope: Optional[bool] = None  # true/false/null
    claim_code: Optional[str] = None
    disclaim_code: Optional[str] = None
    citations: List[Citation] = []


class Section232ResultV2(BaseModel):
    """Schema for Section 232 with nested results structure."""
    model_config = ConfigDict(strict=True)

    hts_code: str
    query_type: str = "section_232"
    results: Dict[str, MetalScopeV2]
    notes: Optional[str] = None
```

### 17.6 Evidence Quotes Table

```python
# app/web/db/models/tariff_tables.py

class EvidenceQuote(BaseModel):
    """Normalized citations extracted from Gemini responses."""
    __tablename__ = "evidence_quotes"

    id = db.Column(db.String(36), primary_key=True)
    search_result_id = db.Column(db.String(36), db.ForeignKey('gemini_search_results.id'))

    # Context
    program_id = db.Column(db.String(50))  # 'section_232', 'section_301'
    material = db.Column(db.String(20))     # 'copper', 'steel', 'aluminum'
    hts_code = db.Column(db.String(20))

    # Decision
    in_scope = db.Column(db.Boolean, nullable=True)  # true/false/null
    claim_code = db.Column(db.String(20))

    # The proof
    source_url = db.Column(db.Text)
    source_document = db.Column(db.String(255))
    quoted_text = db.Column(db.Text)
    quote_hash = db.Column(db.String(64))  # SHA-256 for dedup

    # Verification
    quote_verified = db.Column(db.Boolean, default=False)
    url_in_grounding_metadata = db.Column(db.Boolean, default=False)
```

### 17.7 Evidence-First Prompt

The prompt now requires citations with verbatim quotes:

```python
prompt = f"""You are verifying U.S. Section 232 tariff scope using OFFICIAL sources.

EVIDENCE REQUIREMENTS:
For EACH metal (copper/steel/aluminum):
- Set in_scope to:
  - true ONLY if you found explicit evidence the HTS is listed
  - false ONLY if you found explicit evidence it is excluded
  - null if you cannot confirm either way

If in_scope is true:
- claim_code must be provided
- citations must include at least ONE citation where:
  - source_url is present
  - quoted_text is VERBATIM from the source and includes the HTS code

If you cannot extract a verbatim quote:
- set quoted_text to null (do NOT paraphrase)
"""
```

### 17.8 Validation Flow

```
verify_hts_scope()
        │
        ▼
  Gemini API Call
        │
        ▼
  parse_json_response()
        │
        ▼
  validate_section_232_v2()  ──── Schema valid? ───► validation.is_valid
        │
        ▼
  validate_citations_have_proof()  ──── Has proof? ───► validation.business_errors
        │
        ▼
  validate_citations_contain_hts()  ──► Has HTS? ───► validation.business_warnings
```

### 17.9 MCP Tool Response (v9.2)

```json
{
  "success": true,
  "scope": { /* v9.2 schema with citations */ },
  "raw_response": "...",
  "metadata": {
    "model": "gemini-2.5-flash",
    "grounding_urls": ["https://cbp.gov/..."],
    "schema_version": "v2"
  },
  "validation": {
    "is_valid": true,
    "error": null,
    "business_errors": [],
    "business_warnings": []
  }
}
```

### 17.10 Tests Added (21 new tests)

| Test Class | Tests | Purpose |
|------------|-------|---------|
| `TestCitationSchema` | 4 | Citation model validation |
| `TestMetalScopeV2Schema` | 4 | MetalScopeV2 with citations[] |
| `TestSection232ResultV2Schema` | 3 | Nested results structure |
| `TestBusinessValidation` | 6 | in_scope=true requires proof |
| `TestCitationHtsValidation` | 4 | quoted_text should contain HTS |

**Total tests now: 54** (33 original + 21 new)

### 17.11 Trust Model

| Trust Level | Condition |
|-------------|-----------|
| **High** | `quote_verified=true` AND `url_in_grounding_metadata=true` |
| **Medium** | `quote_verified=false` BUT `url_in_grounding_metadata=true` |
| **Low** | `quote_verified=false` AND `url_in_grounding_metadata=false` |

### 17.12 Files Modified

| File | Changes |
|------|---------|
| `mcp_servers/schemas.py` | Added Citation, MetalScopeV2, Section232ResultV2, business validation |
| `mcp_servers/hts_verifier.py` | Updated prompt, v2 validation, `use_v2_schema` parameter |
| `app/web/db/models/tariff_tables.py` | Added EvidenceQuote model |
| `scripts/migrate_v9_search_tables.py` | Added EvidenceQuote table creation |
| `tests/test_mcp_parsing.py` | Added 21 new v9.2 tests |

### 17.13 Backwards Compatibility

- `use_v2_schema=True` (default) uses v9.2 evidence-first schema
- `use_v2_schema=False` uses v9.1 legacy schema
- Legacy schemas (`Section232Result`, `MetalScope`) still available
- Gradual migration: run both schemas during transition
