# Tariff Stacker Test Cases

This document describes all test cases for the Tariff Stacker v4.0/v6.0/v7.0 implementation.

**Version History:**
- v7.0 (Jan 2026): Phoebe-aligned ACE filing with disclaim_behavior
- v6.0: Country normalization (Macau, Hong Kong)
- v4.0: Entry slices architecture

---

## Architecture Overview

The v4.0+ architecture uses **Entry Slices** for ACE-ready filing:
- Products with 232 metals are split into multiple ACE entries
- Each entry has a `slice_type` and a `stack` of Chapter 99 codes
- IEEPA Reciprocal is calculated on `remaining_value` (after 232 deductions)

**v7.0 Key Changes:**
- Steel/Aluminum disclaim codes are **NEVER FILED** (omit behavior)
- Copper disclaim appears in ALL non-copper slices when applicable (required behavior)
- HTS-specific claim codes (301 list-dependent, steel primary vs derivative)

---

## Test Case 1: USB-C Cable from China (Full Scenario)

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_description": "USB-C cable for data transfer and charging",
    "product_value": 10000.0,
    "materials": {"copper": 0.05, "steel": 0.20, "aluminum": 0.72, "zinc": 0.03}
}
```

### Material Value Conversion
| Material | Percentage | Dollar Value |
|----------|------------|--------------|
| Copper | 5% | $500 |
| Steel | 20% | $2,000 |
| Aluminum | 72% | $7,200 |
| Zinc | 3% | $300 (non-232) |

### Expected Output

**Programs (6):**
- section_301
- ieepa_fentanyl
- section_232_copper
- section_232_steel
- section_232_aluminum
- ieepa_reciprocal

**Entries (4) - v7.0 Filing Behavior:**

| Entry | slice_type | line_value | 232 Codes Filed | IEEPA Reciprocal |
|-------|------------|------------|-----------------|------------------|
| 1 | non_metal | $300 | copper disclaim only | paid (9903.01.25) |
| 2 | copper_slice | $500 | copper claim | exempt (9903.01.33) |
| 3 | steel_slice | $2,000 | steel claim + copper disclaim | exempt (9903.01.33) |
| 4 | aluminum_slice | $7,200 | aluminum claim + copper disclaim | exempt (9903.01.33) |

**v7.0 Note:** Steel/aluminum disclaim codes do NOT appear. Copper disclaim appears in non-copper slices.

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $500 | 50% | $250 |
| 232 Steel | $2,000 | 50% | $1,000 |
| 232 Aluminum | $7,200 | 25% | $1,800 |
| IEEPA Reciprocal | $300 | 10% | $30 |
| **Total** | | | **$6,580** |

**Effective Rate:** 65.8%

---

## Test Case 2: High Steel Content

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_value": 10000.0,
    "materials": {"copper": 0.15, "steel": 0.80, "aluminum": 0.03, "zinc": 0.02}
}
```

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $1,500 | 50% | $750 |
| 232 Steel | $8,000 | 50% | $4,000 |
| 232 Aluminum | $300 | 25% | $75 |
| IEEPA Reciprocal | $200 | 10% | $20 |
| **Total** | | | **$8,345** |

**Effective Rate:** 83.45%

---

## Test Case 3: All Materials at 10%

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_value": 10000.0,
    "materials": {"copper": 0.10, "steel": 0.10, "aluminum": 0.10}
}
```

**Effective Rate:** 54.5%

---

## Test Case 4: Non-China Origin (Germany)

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "Germany",
    "product_value": 10000.0,
    "materials": {"copper": 0.05, "steel": 0.20, "aluminum": 0.72}
}
```

**Programs (3) - 232 only, NO China-specific programs:**
- section_232_copper
- section_232_steel
- section_232_aluminum

**NOT included:**
- section_301 (China only)
- ieepa_fentanyl (China/HK/MO only)
- ieepa_reciprocal (not applied to Germany)

**Effective Rate:** 30.5%

---

## Test Case 5: IEEPA Unstacking (Phase 6.5)

Verifies: "Content subject to Section 232 is NOT subject to Reciprocal IEEPA"

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_value": 10000.0,
    "materials": {"copper": 0.30, "steel": 0.10, "aluminum": 0.10}
}
```

**Unstacking:**
- Without unstacking: IEEPA Reciprocal = $10,000 x 10% = $1,000
- With unstacking: IEEPA Reciprocal = $5,000 x 10% = $500
- **Savings: $500**

---

## v4.0 Test Case 1: UK Chemical (Annex II Exempt)

### Input
```python
{
    "hts_code": "2934.99.9050",
    "country": "UK",
    "product_value": 1000.0,
    "materials": {}
}
```

**Expected:**
- Uses code 9903.01.32 (Annex II exempt)
- Total duty: $0

---

## v6.0 Enhancement Test Cases

### TC6-TC8: Macau Country Normalization

| Test | Input | Expected ISO | Expected Name |
|------|-------|--------------|---------------|
| TC6 | "Macau" | MO | Macau |
| TC7 | "MO" | MO | Macau |
| TC8 | "Macao" | MO | Macau |

### Additional Normalization Tests

| Country | Variants Tested | Expected ISO |
|---------|-----------------|--------------|
| China | China, CN, china, cn, PRC, prc | CN |
| Hong Kong | Hong Kong, HK, hong kong, hk, Hongkong | HK |
| Germany | Germany, DE, Deutschland, germany, de | DE |

---

## Chapter 99 Code Reference (v7.0 Updated)

### Active Filing Codes

| Program | Action | Code | Description |
|---------|--------|------|-------------|
| Section 301 | apply | 9903.88.01 | China List 1 |
| Section 301 | apply | 9903.88.03 | China List 3 |
| Section 301 | apply | 9903.88.69 | Other 301 lists |
| IEEPA Fentanyl | apply | 9903.01.24 | Fentanyl tariff (CN/HK/MO) |
| IEEPA Reciprocal | paid | 9903.01.25 | Taxable reciprocal |
| IEEPA Reciprocal | exempt | 9903.01.32 | Annex II exempt |
| IEEPA Reciprocal | exempt | 9903.01.33 | Metal content exempt |
| 232 Copper | claim | 9903.78.01 | Copper claim |
| 232 Copper | disclaim | 9903.78.02 | Copper disclaim (filed when applicable but not claimed) |
| 232 Steel | claim | 9903.80.01 | Steel primary claim |
| 232 Steel | claim | 9903.81.91 | Steel derivative claim (HTS-dependent) |
| 232 Aluminum | claim | 9903.85.08 | Aluminum claim |

### v7.0 Filing Behavior

| Metal | Claim Code | Disclaim Code | Disclaim Behavior | Notes |
|-------|------------|---------------|-------------------|-------|
| **Copper** | 9903.78.01 | 9903.78.02 | `required` | Disclaim filed in OTHER slices |
| **Steel** | 9903.80.01 or 9903.81.91 | ~~9903.80.02~~ | `omit` | **NEVER FILE disclaim** |
| **Aluminum** | 9903.85.08 | ~~9903.85.09~~ | `omit` | **NEVER FILE disclaim** |

### Legacy Codes (NOT FILED in v7.0)

These codes exist in the database but are **never filed** due to `disclaim_behavior='omit'`:

| Program | Code | Status |
|---------|------|--------|
| 232 Steel | 9903.80.02 | **LEGACY - Never filed** |
| 232 Aluminum | 9903.85.09 | **LEGACY - Never filed** |

---

## Duty Rate Reference

| Program | Rate | Notes |
|---------|------|-------|
| Section 301 | 25% | Applied to full product value |
| IEEPA Fentanyl | 10% | Applied to full product value |
| IEEPA Reciprocal | 10% | Applied to remaining_value (after 232 deductions) |
| 232 Copper | 50% | Applied to copper content value only |
| 232 Steel | 50% | Applied to steel content value only |
| 232 Aluminum | 25% | Applied to aluminum content value only |

---

## v7.0 Phoebe-Aligned ACE Filing Test Cases (Jan 2026)

### Key v7.0 Changes

1. **disclaim_behavior on TariffProgram:**
   - `required` (Copper): Must file disclaim code in OTHER slices when applicable
   - `omit` (Steel/Aluminum): Omit entirely when not claimed (no disclaim line)
   - `none` (Other programs): No disclaim concept

2. **HTS-specific claim codes:** Steel can be 9903.80.01 (primary) OR 9903.81.91 (derivative)

3. **disclaim_behavior applies to filing, not scope:**
   - If program is NOT applicable to HTS, no codes appear at all
   - If program IS applicable but not claimed, disclaim_behavior determines filing

### TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)

**Source:** Phoebe Example 1

```python
{
    "hts_code": "9403.99.9045",  # Furniture parts
    "country": "CN",
    "product_value": 123.12,
    "quantity": 6,
    "materials": {"steel": 61.56, "aluminum": 61.56}
}
```

**Expected:**
- 2 slices (steel_claim, aluminum_claim)
- Steel uses derivative code **9903.81.91** (not 9903.80.01)
- **NO copper codes** (copper not applicable to this HTS)
- **NO steel disclaim in aluminum slice** (steel uses `omit` behavior)
- **NO aluminum disclaim in steel slice** (aluminum uses `omit` behavior)

### TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)

**Source:** Phoebe Example 2

```python
{
    "hts_code": "8544.42.9090",
    "country": "CN",
    "product_value": 36.00,
    "materials": {"copper": 18.00, "aluminum": 18.00}
}
```

**Expected:**
- **Copper disclaim (9903.78.02) appears in aluminum slice** (`required` behavior)
- **Aluminum is OMITTED in copper slice** (`omit` behavior)

| Slice | Copper Code | Aluminum Code |
|-------|-------------|---------------|
| aluminum_slice | 9903.78.02 (disclaim) | 9903.85.08 (claim) |
| copper_slice | 9903.78.01 (claim) | OMITTED |

### TC-v7.0-003: No 232 Claimed (Residual Only)

**Source:** Phoebe Example 3

```python
{
    "hts_code": "8536.90.8585",  # Electrical switches
    "country": "CN",
    "product_value": 174.00,
    "materials": {}
}
```

**Expected:**
- 1 slice (full/residual)
- **NO 232 codes at all** (omitted, not disclaimed)
- Uses **9903.88.01** (List 1) - HTS-specific
- Uses **9903.01.25** (paid) for IEEPA Reciprocal

### TC-v7.0-004: Copper Full Claim

```python
{
    "hts_code": "8544.42.2000",
    "country": "CN",
    "product_value": 66.00,
    "materials": {"copper": 66.00}
}
```

**Expected:**
- 1 slice (copper_claim), no residual
- Copper claim code **9903.78.01**

### TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)

```python
{
    "hts_code": "9403.99.9045",
    "country": "CN",
    "product_value": 3348.00,
    "materials": {"steel": 3046.68, "aluminum": 21.09}
}
```

**Expected:**

| Slice | Value | 232 Codes |
|-------|-------|-----------|
| residual | $280.23 | **NONE** |
| steel_claim | $3,046.68 | 9903.81.91 (claim) |
| aluminum_claim | $21.09 | 9903.85.08 (claim) |

### TC-v7.0-006: Annex II Exemption

```python
{
    "hts_code": "8473.30.5100",  # Computer parts
    "country": "CN",
    "product_value": 842.40,
    "materials": {"aluminum": 126.36}
}
```

**Expected:**
- Uses **9903.01.32** (Annex II exempt) for IEEPA Reciprocal
- Uses **9903.88.69** (different 301 list)

---

## v7.0 Macau/Hong Kong Integration Tests (NEW)

These tests verify that country normalization flows into program applicability.

### TC-v7.0-015: Macau Normalization + Fentanyl Applicability

**Purpose:** Ensure country normalization happens BEFORE program scope resolution.

```python
{
    "hts_code": "8544.42.9090",
    "country": "Macau",  # Should normalize to MO
    "product_value": 1000.00,
    "materials": {"copper": 1000.00}
}
```

**Expected:**
- `normalized_country_iso`: "MO"
- `programs_applied` MUST include: `ieepa_fentanyl` (MO is covered)
- Stack MUST contain: `9903.01.24` (Fentanyl code)
- `section_301` should NOT apply (MO is not CN)

### TC-v7.0-016: Hong Kong Normalization + Fentanyl Applicability

```python
{
    "hts_code": "8544.42.9090",
    "country": "Hongkong",  # Should normalize to HK
    "product_value": 1000.00,
    "materials": {"copper": 1000.00}
}
```

**Expected:**
- `normalized_country_iso`: "HK"
- `programs_applied` MUST include: `ieepa_fentanyl`
- `section_301` should NOT apply (HK is not CN)

### TC-v7.0-017: CN vs MO Behavioral Difference

**Purpose:** Same HTS, same materials, different country = different programs.

```yaml
Test A:
  country: "CN"
  expected_programs: [section_301, ieepa_fentanyl, section_232_copper, ieepa_reciprocal]

Test B:
  country: "MO"
  expected_programs: [ieepa_fentanyl, section_232_copper, ieepa_reciprocal]
  # NO section_301 (Macau is not China)
```

---

## v7.0 Steel Code Regression Tests (NEW)

### TC-v7.0-020: Primary Steel Code (NOT Derivative)

**Purpose:** Verify steel claim code is HTS-specific, not hardcoded to 9903.81.91.

```python
{
    "hts_code": "8544.42.9090",  # USB-C cable - uses PRIMARY steel code
    "country": "CN",
    "product_value": 1000.00,
    "materials": {"steel": 500.00}
}
```

**Expected:**
- Steel claim code: **9903.80.01** (primary, NOT 9903.81.91)
- Furniture parts (9403.99.9045) use derivative 9903.81.91
- USB-C cables (8544.42.9090) use primary 9903.80.01

| HTS | Product Type | Steel Claim Code |
|-----|--------------|------------------|
| 9403.99.9045 | Furniture parts | 9903.81.91 (derivative) |
| 8544.42.9090 | USB-C cable | 9903.80.01 (primary) |

---

## v7.0 Scope Gating Tests (NEW)

### TC-v7.0-021: Copper Claimed But NOT Applicable

**Purpose:** Verify that scope gates behavior - can't file what the HTS doesn't allow.

```python
{
    "hts_code": "9403.99.9045",  # Only flags for steel+aluminum, NOT copper
    "country": "CN",
    "product_value": 1000.00,
    "materials": {"copper": 500.00}  # User claims copper anyway
}
```

**Expected:**
- `copper_slice`: **NOT created** (copper not applicable to this HTS)
- Warning or info: "Copper claimed but not applicable to HTS"
- Only steel/aluminum codes possible for this HTS

### TC-v7.0-022: Copper Applicable But Zero Value

**Purpose:** If copper is applicable and user claims $0, no copper slice but disclaim still appears.

```python
{
    "hts_code": "8544.42.9090",  # Flags for copper
    "country": "CN",
    "product_value": 1000.00,
    "materials": {"copper": 0, "aluminum": 500.00}  # Copper $0
}
```

**Expected:**
- No `copper_slice` (no copper value)
- `aluminum_slice` and `residual_slice` have copper disclaim (9903.78.02)
- Copper disclaim appears because HTS flags for copper, even if not claimed

---

## Stability Test Cases

| Test Case | Description | Key Assertion |
|-----------|-------------|---------------|
| TC-v7.0-009 | Quantity Duplication | All slices have same quantity, NOT split |
| TC-v7.0-010 | Rounding / Penny Drift | Sum of slice values = product value exactly |
| TC-v7.0-011 | Invalid Allocation | Error when materials sum > product value |
| TC-v7.0-013 | Copper Applicable, No Claim | Copper disclaim in all non-copper slices |
| TC-v7.0-014 | No Duplicate Copper Disclaim | Copper disclaim appears exactly ONCE per slice |

---

## Future Test Cases (Placeholders)

### TC-v7.0-018: Program Suppression (Timber)

When timber/vehicles is implemented:
```python
# Seed: program_suppressions: suppressor="section_232_timber", suppressed="ieepa_reciprocal"
# Assert: reciprocal line absent OR forced to suppressed variant
```

### TC12-TC13: 301 Exclusion with Description Matching

When implemented:
- TC12: HTS matches + description matches = exclusion applies
- TC13: HTS matches + description NOT match = exclusion does NOT apply

---

## Running Tests

```bash
# Run all automated stacking tests
pipenv run python tests/test_stacking_automated.py

# Run with verbose output
pipenv run python tests/test_stacking_automated.py -v

# Run v6 enhancement tests
pipenv run python tests/test_v6_enhancements.py

# Run v7.0 Phoebe tests
pipenv run python tests/test_stacking_v7_phoebe.py

# Run v7.0 stability tests
pipenv run python tests/test_stacking_v7_stability.py
```
