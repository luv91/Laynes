# Section 232 Stacking Test Cases (v13.0)

**Date:** January 2026
**Total Tests:** 19 (7 Phoebe + 12 Automated)
**Status:** All Passing

---

## 1. Test Suite Overview

### 1.1 Test Files

| File | Tests | Purpose |
|------|-------|---------|
| `tests/test_stacking_v7_phoebe.py` | 7 | Phoebe-aligned ACE filing examples |
| `tests/test_stacking_automated.py` | 12 | Comprehensive stacking scenarios |

### 1.2 Running Tests

```bash
# Run Phoebe tests
pipenv run python tests/test_stacking_v7_phoebe.py -v

# Run automated tests
pipenv run python tests/test_stacking_automated.py -v

# Run all tests
pipenv run python tests/test_stacking_v7_phoebe.py && pipenv run python tests/test_stacking_automated.py
```

---

## 2. Phoebe-Aligned Test Cases (v7.0)

These tests validate behavior against Phoebe's actual ACE filing examples.

### TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)

**Source:** Phoebe Example 1

**Input:**
```python
hts_code = "9403.99.9045"  # Furniture parts
country = "China"
product_value = 123.12
materials = {"steel": 61.56, "aluminum": 61.56}
```

**Expected Output:**
- 2 slices: `steel_slice`, `aluminum_slice`
- NO residual slice (all value allocated to metals)
- Steel uses derivative code `9903.81.91` (not 9903.80.01)
- No copper codes (copper not applicable to this HTS)
- No steel disclaim in aluminum slice (omit behavior)
- No aluminum disclaim in steel slice (omit behavior)

**Key Behaviors Tested:**
1. `disclaim_behavior='omit'` for steel
2. `disclaim_behavior='omit'` for aluminum
3. HTS-specific claim_code (9903.81.91 for derivative steel)

---

### TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)

**Source:** Phoebe Example 2

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 36.00
materials = {"copper": 18.00, "aluminum": 18.00}
```

**Expected Output:**
- 2 slices: `copper_slice`, `aluminum_slice`
- Copper disclaim (9903.78.02) appears in aluminum slice
- Aluminum is OMITTED in copper slice (not disclaimed)

**Key Behaviors Tested:**
1. `disclaim_behavior='required'` for copper - copper disclaim in aluminum slice
2. `disclaim_behavior='omit'` for aluminum - no aluminum code in copper slice
3. HTS 8544.42.9090 has copper + aluminum only (NO steel)

---

### TC-v7.0-003: No 232 Claimed (Residual Only)

**Source:** Phoebe Example 3

**Input:**
```python
hts_code = "8539.50.0000"  # LED lamps (NOT in 232 scope)
country = "China"
product_value = 174.00
materials = {}  # No metals declared
```

**Expected Output:**
- 1 slice: `full` (residual)
- NO 232 codes at all
- Uses `9903.88.03` (List 3) for Section 301
- Uses `9903.01.25` (paid) for IEEPA Reciprocal

**Key Behaviors Tested:**
1. HTS not in any 232 scope means no 232 codes
2. 301 code comes from section_301_inclusions (list-specific)

---

### TC-v7.0-004: Copper Full Claim

**Source:** Phoebe Example 4

**Input:**
```python
hts_code = "8544.42.2000"
country = "China"
product_value = 66.00
materials = {"copper": 66.00}
```

**Expected Output:**
- 1 slice: `copper_slice`
- No residual (100% copper)
- Copper claim code `9903.78.01`

**Key Behaviors Tested:**
1. HTS 8544.42.2000 has copper ONLY (no aluminum, no steel)
2. Full value allocation to single metal

---

### TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)

**Source:** Phoebe Example 5

**Input:**
```python
hts_code = "9403.99.9045"
country = "China"
product_value = 3348.00
materials = {"steel": 3046.68, "aluminum": 21.09}
```

**Expected Output:**
- 3 slices: `non_metal`, `steel_slice`, `aluminum_slice`
- Residual slice: NO steel disclaim, NO aluminum disclaim
- Steel slice: Uses `9903.81.91` (derivative)
- Residual value: $280.23 ($3,348 - $3,046.68 - $21.09)

**Key Behaviors Tested:**
1. Residual/non_metal slice creation
2. Steel derivative code usage
3. Accurate value splitting

---

### TC-v7.0-006: Annex II Exemption

**Source:** Phoebe Example 6

**Input:**
```python
hts_code = "8473.30.5100"  # Computer parts
country = "China"
product_value = 842.40
materials = {"aluminum": 126.36}
```

**Expected Output:**
- 2 slices: `non_metal`, `aluminum_slice`
- Uses `9903.01.32` (Annex II exempt) for IEEPA Reciprocal
- Uses `9903.88.69` for Section 301

**Key Behaviors Tested:**
1. Annex II exemption detection (HTS prefix matching)
2. `annex_ii_exempt` variant for IEEPA Reciprocal

---

### TC-v7.0-008: No Steel/Aluminum Disclaim Codes

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 1000.00
materials = {"copper": 1000.00}
```

**Expected Output:**
- NO `9903.80.02` (steel disclaim) anywhere in output
- NO `9903.85.09` (aluminum disclaim) anywhere in output

**Key Behaviors Tested:**
1. Steel disclaim codes NEVER appear (omit behavior)
2. Aluminum disclaim codes NEVER appear (omit behavior)

---

## 3. Automated Stacking Test Cases

### Test Case 1: USB-C Cable from China (Full Scenario)

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.0
materials = {"copper": 0.05, "aluminum": 0.72}  # 5% copper, 72% aluminum
```

**Expected Calculation:**
| Program | Basis | Rate | Duty |
|---------|-------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $500 | 50% | $250 |
| 232 Aluminum | $7,200 | 50% | $3,600 |
| IEEPA Reciprocal | $2,300 | 10% | $230 |
| **Total** | | | **$7,580 (75.8%)** |

**Key Validations:**
- 6 programs returned (including steel, even if not used)
- 3 entries: `non_metal`, `copper_slice`, `aluminum_slice`
- NO `steel_slice` (HTS not in steel scope)
- `remaining_value` = $2,300

---

### Test Case 2: High Steel Content (Furniture Parts)

**Input:**
```python
hts_code = "9403.99.9045"  # HTS with steel in scope
country = "China"
product_value = 10000.0
materials = {"steel": 0.80, "aluminum": 0.15}  # 80% steel, 15% aluminum
```

**Expected Calculation:**
| Program | Basis | Rate | Duty |
|---------|-------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Steel | $8,000 | 50% | $4,000 |
| 232 Aluminum | $1,500 | 50% | $750 |
| IEEPA Reciprocal | $500 | 10% | $50 |
| **Total** | | | **$8,300 (83.0%)** |

---

### Test Case 3: Copper + Aluminum at 10% Each

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.0
materials = {"copper": 0.10, "aluminum": 0.10}
```

**Expected Calculation:**
| Program | Basis | Rate | Duty |
|---------|-------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $1,000 | 50% | $500 |
| 232 Aluminum | $1,000 | 50% | $500 |
| IEEPA Reciprocal | $8,000 | 10% | $800 |
| **Total** | | | **$5,300 (53.0%)** |

**Key Validations:**
- 3 entries: `non_metal` ($8,000), `copper_slice` ($1,000), `aluminum_slice` ($1,000)
- IEEPA Reciprocal is "paid" on non_metal slice

---

### Test Case 4: Non-China Origin (Germany)

**Input:**
```python
hts_code = "8544.42.9090"
country = "Germany"
product_value = 10000.0
materials = {"copper": 0.05, "aluminum": 0.72}
```

**Expected Calculation:**
| Program | Basis | Rate | Duty |
|---------|-------|------|------|
| 232 Copper | $500 | 50% | $250 |
| 232 Aluminum | $7,200 | 50% | $3,600 |
| **Total** | | | **$3,850 (38.5%)** |

**Key Validations:**
- 3 programs (232 only, no China-specific programs)
- NO Section 301, IEEPA Fentanyl, or IEEPA Reciprocal
- 3 entries: `non_metal`, `copper_slice`, `aluminum_slice`

---

### Test Case 5: IEEPA Unstacking (Phase 6.5)

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.0
materials = {"copper": 0.30, "aluminum": 0.10}
```

**Expected Calculation:**
| Program | Basis | Rate | Duty |
|---------|-------|------|------|
| Section 301 | $10,000 | 25% | $2,500 |
| IEEPA Fentanyl | $10,000 | 10% | $1,000 |
| 232 Copper | $3,000 | 50% | $1,500 |
| 232 Aluminum | $1,000 | 50% | $500 |
| IEEPA Reciprocal | $6,000 | 10% | $600 |
| **Total** | | | **$6,100 (61.0%)** |

**Key Validations:**
- `remaining_value` = $6,000 (correctly unstacked)
- IEEPA Reciprocal only on `remaining_value`, not full product

---

### Test Case 6: No Double-Subtraction in Unstacking

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.0
materials = {"copper": 0.30, "aluminum": 0.10}
```

**Key Validations:**
- `remaining_value` = $6,000 (NOT $0 or negative)
- 2 materials in `content_deductions`
- Copper deducted exactly once: $3,000
- Aluminum deducted exactly once: $1,000

---

### v4.0 Case 1: UK Chemical (Annex II Exempt)

**Input:**
```python
hts_code = "2934.99.9050"  # Pharmaceutical
country = "UK"
product_value = 1000.0
materials = {}
```

**Expected Output:**
- 1 entry: `full` slice
- Uses `9903.01.32` (Annex II exempt) for IEEPA Reciprocal
- `variant = 'annex_ii_exempt'`
- `action = 'exempt'`
- Total duty: **$0**

---

### v4.0 Case 2: China 2-Metal USB-C Cable

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.0
materials = {"copper": 3000.0, "aluminum": 1000.0}  # Content VALUES
```

**Expected Output:**
- 3 entries: `non_metal` ($6,000), `copper_slice` ($3,000), `aluminum_slice` ($1,000)
- NO `steel_slice`
- IEEPA Reciprocal: "paid" on non_metal, "exempt" on metal slices
- Total duty: **$6,100 (61.0%)**

---

### v4.0 Case 3: Germany 2-Metal Cable (232 only)

**Input:**
```python
hts_code = "8544.42.9090"
country = "Germany"
product_value = 10000.0
materials = {"copper": 3000.0, "aluminum": 1000.0}
```

**Expected Output:**
- 3 entries: `non_metal`, `copper_slice`, `aluminum_slice`
- NO China-specific programs
- NO `section_232_steel` (HTS not in steel scope)
- Total duty: **$2,000 (20.0%)**

---

### v4.0 Case 4: China Single-Metal (Copper only)

**Input:**
```python
hts_code = "8544.42.9090"
country = "China"
product_value = 10000.0
materials = {"copper": 3000.0}
```

**Expected Output:**
- 2 entries: `non_metal` ($7,000), `copper_slice` ($3,000)
- NO `steel_slice`, NO `aluminum_slice`
- `remaining_value` = $7,000
- Total duty: **$5,700 (57.0%)**

---

### v4.0: Entries/Filing Lines Consistency

Verifies that `entries.stack` and `filing_lines` contain consistent data.

**Key Validations:**
- `len(filing_lines)` equals sum of all entry stack lengths
- All chapter_99_codes from entries appear in filing_lines

---

### Decision Audit Trail

Verifies that all decisions have proper audit trail with sources.

**Key Validations:**
- `decisions` array is populated
- Each decision has: `step`, `program_id`, `decision`
- At least one decision has `source_doc`

---

## 4. Rate Verification Table

### 4.1 Expected Rates Used in Tests

| Program | Rate | Notes |
|---------|------|-------|
| Section 232 Copper | **50%** | All countries |
| Section 232 Steel | **50%** | Default (UK: 25%) |
| Section 232 Aluminum | **50%** | Default (UK: 25%) |
| Section 301 | 25% | China only |
| IEEPA Fentanyl | 10% | China/HK/Macau |
| IEEPA Reciprocal | 10% | Default |

### 4.2 Rate Change History

| Date | Change | Authority |
|------|--------|-----------|
| June 4, 2025 | Aluminum/Steel: 25% → 50% | 90 FR 10524 |
| July 2025 | Copper: 25% → 50% | CSMS #65794272 |
| Nov 2025 | IEEPA Fentanyl: 20% → 10% | White House |

---

## 5. Common Test Failures and Solutions

### 5.1 "Expected X programs, got Y"

**Cause:** Programs list includes all applicable programs for country, even if not used for HTS.

**Solution:** The programs list is country-based. Steel program may appear for China even if HTS isn't in steel scope. Check entries instead.

### 5.2 "Steel slice should not exist"

**Cause:** Materials input includes steel, but HTS is not in steel scope.

**Solution:** Only pass materials that are in scope for the HTS. For 8544.42.9090, use copper and aluminum only.

### 5.3 "Expected aluminum rate 50%, got 25%"

**Cause:** Database still has old 25% rate.

**Solution:** Re-run database population:
```bash
pipenv run python scripts/populate_tariff_tables.py --reset
```

### 5.4 "Expected 1 entry, got 0"

**Cause:** HTS is in 232 scope but no materials provided.

**Solution:** Use an HTS that is NOT in 232 scope for "no metals" tests, or provide materials matching the HTS scope.

---

## 6. Verification Checklist

Before submitting code changes, verify:

- [ ] All 7 Phoebe tests passing
- [ ] All 12 automated tests passing
- [ ] Aluminum rate is 50% (not 25%)
- [ ] Steel rate is 50% (not 25%)
- [ ] 8544.42.9090 has copper + aluminum only (no steel)
- [ ] 8544.42.2000 has copper only (no aluminum)
- [ ] 8539.50.0000 is NOT in section_232_materials

---

*Last Updated: January 2026*
