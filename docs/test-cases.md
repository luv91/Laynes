# Tariff Stacker Test Cases

This document describes all test cases for the Tariff Stacker v4.0/v6.0 implementation.

---

## Architecture Overview

The v4.0 architecture uses **Entry Slices** for ACE-ready filing:
- Products with 232 metals are split into multiple ACE entries
- Each entry has a `slice_type` and a `stack` of Chapter 99 codes
- IEEPA Reciprocal is calculated on `remaining_value` (after 232 deductions)

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

**Entries (4):**

| Entry | slice_type | line_value | 232 Claim | IEEPA Reciprocal |
|-------|------------|------------|-----------|------------------|
| 1 | non_metal | $300 | all disclaim | paid (9903.01.25) |
| 2 | copper_slice | $500 | copper=claim | exempt (9903.01.33) |
| 3 | steel_slice | $2,000 | steel=claim | exempt (9903.01.33) |
| 4 | aluminum_slice | $7,200 | aluminum=claim | exempt (9903.01.33) |

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

**Unstacking:**
```json
{
    "initial_value": 10000.0,
    "content_deductions": {
        "copper": 500.0,
        "steel": 2000.0,
        "aluminum": 7200.0
    },
    "remaining_value": 300.0
}
```

---

## Test Case 2: High Steel Content

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_description": "USB-C cable with steel reinforcement",
    "product_value": 10000.0,
    "materials": {"copper": 0.15, "steel": 0.80, "aluminum": 0.03, "zinc": 0.02}
}
```

### Material Value Conversion
| Material | Percentage | Dollar Value |
|----------|------------|--------------|
| Copper | 15% | $1,500 |
| Steel | 80% | $8,000 |
| Aluminum | 3% | $300 |
| Zinc | 2% | $200 (non-232) |

### Expected Output

**Entries (4):**

| Entry | slice_type | line_value |
|-------|------------|------------|
| 1 | non_metal | $200 |
| 2 | copper_slice | $1,500 |
| 3 | steel_slice | $8,000 |
| 4 | aluminum_slice | $300 |

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
    "product_description": "USB-C cable mostly plastic",
    "product_value": 10000.0,
    "materials": {"copper": 0.10, "steel": 0.10, "aluminum": 0.10}
}
```

### Material Value Conversion
| Material | Percentage | Dollar Value |
|----------|------------|--------------|
| Copper | 10% | $1,000 |
| Steel | 10% | $1,000 |
| Aluminum | 10% | $1,000 |
| Other | 70% | $7,000 (non-232) |

### Expected Output

**Entries (4):**

| Entry | slice_type | line_value |
|-------|------------|------------|
| 1 | non_metal | $7,000 |
| 2 | copper_slice | $1,000 |
| 3 | steel_slice | $1,000 |
| 4 | aluminum_slice | $1,000 |

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $1,000 | 50% | $500 |
| 232 Steel | $1,000 | 50% | $500 |
| 232 Aluminum | $1,000 | 25% | $250 |
| IEEPA Reciprocal | $7,000 | 10% | $700 |
| **Total** | | | **$5,450** |

**Effective Rate:** 54.5%

---

## Test Case 4: Non-China Origin (Germany)

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "Germany",
    "product_description": "USB-C cable from Germany",
    "product_value": 10000.0,
    "materials": {"copper": 0.05, "steel": 0.20, "aluminum": 0.72}
}
```

### Expected Output

**Programs (3) - 232 only, NO China-specific programs:**
- section_232_copper
- section_232_steel
- section_232_aluminum

**NOT included:**
- section_301 (China only)
- ieepa_fentanyl (China/HK/MO only)
- ieepa_reciprocal (not applied to Germany)

**Entries (4):**

| Entry | slice_type | line_value |
|-------|------------|------------|
| 1 | non_metal | $300 |
| 2 | copper_slice | $500 |
| 3 | steel_slice | $2,000 |
| 4 | aluminum_slice | $7,200 |

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| 232 Copper | $500 | 50% | $250 |
| 232 Steel | $2,000 | 50% | $1,000 |
| 232 Aluminum | $7,200 | 25% | $1,800 |
| **Total** | | | **$3,050** |

**Effective Rate:** 30.5%

---

## Test Case 5: IEEPA Unstacking (Phase 6.5)

This test verifies the CBP rule: "Content subject to Section 232 is NOT subject to Reciprocal IEEPA"

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_description": "USB-C cable with mixed metals (research doc example)",
    "product_value": 10000.0,
    "materials": {"copper": 0.30, "steel": 0.10, "aluminum": 0.10}
}
```

### Material Value Conversion
| Material | Percentage | Dollar Value |
|----------|------------|--------------|
| Copper | 30% | $3,000 |
| Steel | 10% | $1,000 |
| Aluminum | 10% | $1,000 |
| Other | 50% | $5,000 (non-232) |

### Expected Output

**Entries (4):**

| Entry | slice_type | line_value |
|-------|------------|------------|
| 1 | non_metal | $5,000 |
| 2 | copper_slice | $3,000 |
| 3 | steel_slice | $1,000 |
| 4 | aluminum_slice | $1,000 |

**Unstacking (Key Feature):**
```json
{
    "initial_value": 10000.0,
    "content_deductions": {
        "copper": 3000.0,
        "steel": 1000.0,
        "aluminum": 1000.0
    },
    "remaining_value": 5000.0
}
```

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $3,000 | 50% | $1,500 |
| 232 Steel | $1,000 | 50% | $500 |
| 232 Aluminum | $1,000 | 25% | $250 |
| IEEPA Reciprocal | **$5,000** | 10% | **$500** |
| **Total** | | | **$6,250** |

**Effective Rate:** 62.5%

**Why This Matters:**
- Without unstacking: IEEPA Reciprocal = $10,000 × 10% = $1,000
- With unstacking: IEEPA Reciprocal = $5,000 × 10% = $500
- **Savings: $500**

---

## Test Case 6: No Double-Subtraction in Unstacking

This test verifies that each material is deducted only ONCE, even with multiple entries.

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_description": "USB-C cable - double subtraction test",
    "product_value": 10000.0,
    "materials": {"copper": 0.30, "steel": 0.10, "aluminum": 0.10}
}
```

### Expected Output

**Deductions (each material once):**

| Material | Deduction | NOT |
|----------|-----------|-----|
| Copper | $3,000 | $6,000 (doubled) |
| Steel | $1,000 | $2,000 (doubled) |
| Aluminum | $1,000 | $2,000 (doubled) |

**Remaining Value:**
- Correct: $10,000 - $3,000 - $1,000 - $1,000 = **$5,000**
- Wrong (if doubled): $10,000 - $6,000 - $2,000 - $2,000 = **$0**

---

## v4.0 Test Case 1: UK Chemical (Annex II Exempt)

### Input
```python
{
    "hts_code": "2934.99.9050",
    "country": "UK",
    "product_description": "Plasmid DNA for research",
    "product_value": 1000.0,
    "materials": {}  # No metals
}
```

### Expected Output

**Programs (1):**
- ieepa_reciprocal (with Annex II exemption)

**Entries (1):**

| Entry | slice_type | line_value | IEEPA Reciprocal |
|-------|------------|------------|------------------|
| 1 | full | $1,000 | exempt (9903.01.32) |

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| IEEPA Reciprocal | $1,000 | 0% (exempt) | $0 |
| **Total** | | | **$0** |

**Why Exempt:**
- HTS 2934.99 is in Annex II exclusion list (pharmaceuticals/chemicals)
- Uses code 9903.01.32 (Annex II exempt variant)

---

## v4.0 Test Case 2: China 3-Metal USB-C Cable

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_description": "USB-C cable with copper, steel, aluminum",
    "product_value": 10000.0,
    "materials": {"copper": 3000.0, "steel": 1000.0, "aluminum": 1000.0}  # Dollar values
}
```

### Expected Output

**Entries (4):**

| Entry | slice_type | line_value | Stack |
|-------|------------|------------|-------|
| 1 | non_metal | $5,000 | 301[apply], Fentanyl[apply], Reciprocal[paid], Cu/St/Al[disclaim] |
| 2 | copper_slice | $3,000 | 301[apply], Fentanyl[apply], Reciprocal[exempt], Cu[claim], St/Al[disclaim] |
| 3 | steel_slice | $1,000 | 301[apply], Fentanyl[apply], Reciprocal[exempt], St[claim], Cu/Al[disclaim] |
| 4 | aluminum_slice | $1,000 | 301[apply], Fentanyl[apply], Reciprocal[exempt], Al[claim], Cu/St[disclaim] |

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $3,000 | 50% | $1,500 |
| 232 Steel | $1,000 | 50% | $500 |
| 232 Aluminum | $1,000 | 25% | $250 |
| IEEPA Reciprocal | $5,000 | 10% | $500 |
| **Total** | | | **$6,250** |

**Effective Rate:** 62.5%

---

## v4.0 Test Case 3: Germany 3-Metal Cable (232 only)

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "Germany",
    "product_description": "USB-C cable from Germany",
    "product_value": 10000.0,
    "materials": {"copper": 3000.0, "steel": 1000.0, "aluminum": 1000.0}  # Dollar values
}
```

### Expected Output

**Programs (3) - NO China-specific programs:**
- section_232_copper
- section_232_steel
- section_232_aluminum

**Entries (4) - Stacks contain ONLY 232 programs:**

| Entry | slice_type | line_value | Stack |
|-------|------------|------------|-------|
| 1 | non_metal | $5,000 | Cu/St/Al[disclaim] |
| 2 | copper_slice | $3,000 | Cu[claim], St/Al[disclaim] |
| 3 | steel_slice | $1,000 | St[claim], Cu/Al[disclaim] |
| 4 | aluminum_slice | $1,000 | Al[claim], Cu/St[disclaim] |

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| 232 Copper | $3,000 | 50% | $1,500 |
| 232 Steel | $1,000 | 50% | $500 |
| 232 Aluminum | $1,000 | 25% | $250 |
| **Total** | | | **$2,250** |

**Effective Rate:** 22.5%

---

## v4.0 Test Case 4: China Single-Metal (Copper only)

### Input
```python
{
    "hts_code": "8544.42.9090",
    "country": "China",
    "product_description": "USB-C cable with copper only",
    "product_value": 10000.0,
    "materials": {"copper": 3000.0}  # Only copper
}
```

### Expected Output

**Entries (2) - Only non_metal + copper_slice:**

| Entry | slice_type | line_value |
|-------|------------|------------|
| 1 | non_metal | $7,000 |
| 2 | copper_slice | $3,000 |

**NOT included:**
- steel_slice (no steel content)
- aluminum_slice (no aluminum content)

**Unstacking:**
```json
{
    "initial_value": 10000.0,
    "content_deductions": {
        "copper": 3000.0
    },
    "remaining_value": 7000.0
}
```

**Duty Calculation:**
| Program | Base Value | Rate | Duty |
|---------|------------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $3,000 | 50% | $1,500 |
| IEEPA Reciprocal | $7,000 | 10% | $700 |
| **Total** | | | **$5,700** |

**Effective Rate:** 57.0%

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

### TC9-TC11: Program Suppressions (Placeholder)

These tests are placeholders for when timber/vehicles programs are implemented:
- TC9: Section 232 Timber should suppress IEEPA Reciprocal
- TC10: Timber product duty calculation
- TC11: Section 232 Vehicles should suppress IEEPA Reciprocal

### TC12-TC13: 301 Exclusion Tests (Placeholder)

These tests are placeholders for enhanced 301 exclusion matching:
- TC12: 301 exclusion with hts_only match type
- TC13: 301 exclusion with hts_and_description_confirmed match type

### TC14: Order Independence

Suppression resolution should produce the same result regardless of program order:
```python
programs_order_a = ["ieepa_reciprocal", "section_232_timber", "section_301"]
programs_order_b = ["section_232_timber", "section_301", "ieepa_reciprocal"]
programs_order_c = ["section_301", "ieepa_reciprocal", "section_232_timber"]

# All should produce the same suppressed set
suppressed_a == suppressed_b == suppressed_c  # True
```

### TC15: Date Regression

Same product on different dates should give different results:
- Pre-Fentanyl (before Feb 4, 2025): IEEPA Fentanyl NOT active
- Post-Fentanyl (after Feb 4, 2025): IEEPA Fentanyl IS active

---

## Chapter 99 Code Reference

| Program | Action | Code | Description |
|---------|--------|------|-------------|
| Section 301 | apply | 9903.88.03 | China List 1-4 |
| IEEPA Fentanyl | apply | 9903.01.24 | Fentanyl tariff (CN/HK/MO) |
| IEEPA Reciprocal | paid | 9903.01.25 | Taxable reciprocal |
| IEEPA Reciprocal | exempt | 9903.01.32 | Annex II exempt |
| IEEPA Reciprocal | exempt | 9903.01.33 | Metal content exempt |
| 232 Copper | claim | 9903.78.01 | Copper derivative claim |
| 232 Copper | disclaim | 9903.78.02 | Copper derivative disclaim |
| 232 Steel | claim | 9903.80.01 | Steel derivative claim |
| 232 Steel | disclaim | 9903.80.02 | Steel derivative disclaim |
| 232 Aluminum | claim | 9903.85.08 | Aluminum derivative claim |
| 232 Aluminum | disclaim | 9903.85.09 | Aluminum derivative disclaim |

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

## Running Tests

```bash
# Run all automated stacking tests
pipenv run python tests/test_stacking_automated.py

# Run with verbose output
pipenv run python tests/test_stacking_automated.py -v

# Run v6 enhancement tests
pipenv run python tests/test_v6_enhancements.py

# Run with verbose output
pipenv run python tests/test_v6_enhancements.py -v
```
