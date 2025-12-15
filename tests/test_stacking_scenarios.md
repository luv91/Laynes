# Stacking Feature Test Cases

This document describes the test scenarios for the Tariff Stacking Calculator, including:
- Input parameters
- Expected decisions and WHY
- Expected output (filing lines, duties)
- Verification criteria

---

## Test Case 1: USB-C Cable from China (Full Scenario)

### Input Parameters

| Parameter | Value |
|-----------|-------|
| HTS Code | `8544.42.9090` |
| Country of Origin | `China` |
| Product Description | `USB-C cable for data transfer and charging` |
| Product Value | `$10,000.00` |
| Material Composition | copper: 5%, steel: 20%, aluminum: 72%, zinc: 3% |

### Expected Decision Sequence

#### Step 1: Initialize - Get Applicable Programs

**Tool Called:** `get_applicable_programs(country="China", hts_code="8544.42.9090")`

**Expected Result:** 6 programs found (ordered by filing_sequence):

| Seq | Program ID | Program Name | Check Type | Why Applicable |
|-----|------------|--------------|------------|----------------|
| 1 | section_301 | Section 301 China Tariffs | hts_lookup | Country = China |
| 2 | ieepa_fentanyl | IEEPA Fentanyl Tariff | always | Country = China |
| 3 | section_232_copper | Section 232 Copper | hts_lookup | Country = ALL |
| 4 | section_232_steel | Section 232 Steel | hts_lookup | Country = ALL |
| 5 | section_232_aluminum | Section 232 Aluminum | hts_lookup | Country = ALL |
| 6 | ieepa_reciprocal | IEEPA Reciprocal Tariff | always | Country = China, depends on 232 |

**Decision:** `Found 6 applicable programs`
**Reason:** Query tariff_programs table for country=China OR country=ALL

---

#### Step 2: Process Section 301

**Tool Called:** `check_program_inclusion(program_id="section_301", hts_code="8544.42.9090")`

**Expected Result:**
```json
{
  "included": true,
  "hts_8digit": "85444290",
  "list_name": "list_3",
  "chapter_99_code": "9903.88.03",
  "duty_rate": 0.25
}
```

**Decision:** `included`
**Reason:** HTS 85444290 found in section_301_inclusions table (List 3 - $200B list)
**Source:** `301_List_3.pdf`

**Tool Called:** `check_program_exclusion(program_id="section_301", hts_code="8544.42.9090", product_description="USB-C cable...")`

**Expected Result:**
```json
{
  "excluded": false,
  "reason": "No active exclusions for this HTS code"
}
```

**Decision:** `not_excluded`
**Reason:** No exclusion entries in section_301_exclusions match this HTS/product
**Source:** N/A

**Tool Called:** `get_program_output(program_id="section_301", action="apply")`

**Expected Result:**
```json
{
  "chapter_99_code": "9903.88.03",
  "duty_rate": 0.25,
  "applies_to": "full"
}
```

**Filing Line Added:**
```
9903.88.03 → Section 301 China Tariffs [apply] (25.0%)
```

---

#### Step 3: Process IEEPA Fentanyl

**Tool Called:** `check_program_inclusion(program_id="ieepa_fentanyl", hts_code="8544.42.9090")`

**Expected Result:**
```json
{
  "included": true,
  "check_type": "always",
  "reason": "IEEPA Fentanyl Tariff applies to all qualifying imports"
}
```

**Decision:** `always_applies`
**Reason:** check_type="always" means this program applies to ALL imports from China regardless of HTS
**Source:** `IEEPA_Fentanyl_Notice.pdf`

**Tool Called:** `get_program_output(program_id="ieepa_fentanyl", action="apply")`

**Expected Result:**
```json
{
  "chapter_99_code": "9903.01.24",
  "duty_rate": 0.20,
  "applies_to": "full"
}
```

**Filing Line Added:**
```
9903.01.24 → IEEPA Fentanyl Tariff [apply] (20.0%)
```

---

#### Step 4: Process Section 232 Copper

**Tool Called:** `check_program_inclusion(program_id="section_232_copper", hts_code="8544.42.9090")`

**Expected Result:**
```json
{
  "included": true,
  "material": "copper",
  "claim_code": "9903.78.01",
  "disclaim_code": "9903.78.02",
  "duty_rate": 0.25
}
```

**Decision:** `included`
**Reason:** HTS 85444290 found in section_232_materials with material=copper
**Source:** `232_Copper.pdf`

**Tool Called:** `check_material_composition(hts_code="8544.42.9090", materials={"copper": 0.05, "steel": 0.20, "aluminum": 0.72})`

**Expected Result for Copper:**
```json
{
  "material": "copper",
  "percentage": 0.05,
  "threshold": 0.25,
  "action": "disclaim",
  "chapter_99_code": "9903.78.02",
  "duty_rate": 0
}
```

**Decision:** `disclaim`
**Reason:** Copper percentage (5%) is BELOW threshold (25%), so no duty applies
**Business Logic:** If material content < 25%, product is not considered a "derivative" of that material
**Source:** `232_Copper.pdf`

**Filing Line Added:**
```
9903.78.02 → Section 232 Copper [disclaim]
```

---

#### Step 5: Process Section 232 Steel

**Tool Called:** `check_program_inclusion(program_id="section_232_steel", hts_code="8544.42.9090")`

**Expected Result:**
```json
{
  "included": true,
  "material": "steel",
  "claim_code": "9903.80.01",
  "disclaim_code": "9903.80.02"
}
```

**Tool Called:** `check_material_composition` (already called, reuse result)

**Expected Result for Steel:**
```json
{
  "material": "steel",
  "percentage": 0.20,
  "threshold": 0.25,
  "action": "disclaim",
  "chapter_99_code": "9903.80.02",
  "duty_rate": 0
}
```

**Decision:** `disclaim`
**Reason:** Steel percentage (20%) is BELOW threshold (25%), so no duty applies
**Source:** `232_Steel.pdf`

**Filing Line Added:**
```
9903.80.02 → Section 232 Steel [disclaim]
```

---

#### Step 6: Process Section 232 Aluminum

**Tool Called:** `check_program_inclusion(program_id="section_232_aluminum", hts_code="8544.42.9090")`

**Expected Result:**
```json
{
  "included": true,
  "material": "aluminum",
  "claim_code": "9903.85.08",
  "disclaim_code": "9903.85.09",
  "duty_rate": 0.10
}
```

**Tool Called:** `check_material_composition` (already called, reuse result)

**Expected Result for Aluminum:**
```json
{
  "material": "aluminum",
  "percentage": 0.72,
  "threshold": 0.25,
  "action": "claim",
  "chapter_99_code": "9903.85.08",
  "duty_rate": 0.10,
  "applies_to": "partial (72.0%)"
}
```

**Decision:** `claim`
**Reason:** Aluminum percentage (72%) is ABOVE threshold (25%), so duty applies on that portion
**Business Logic:** Product is considered an "aluminum derivative" because >25% aluminum content
**Source:** `232_Aluminum.pdf`

**Filing Line Added:**
```
9903.85.08 → Section 232 Aluminum [claim] (10.0%)
```

---

#### Step 7: Process IEEPA Reciprocal

**Tool Called:** `check_program_inclusion(program_id="ieepa_reciprocal", hts_code="8544.42.9090")`

**Expected Result:**
```json
{
  "included": true,
  "check_type": "always"
}
```

**Tool Called:** `resolve_program_dependencies(program_id="ieepa_reciprocal", previous_results={...})`

**Previous Results Checked:**
- section_232_copper: `any_claims = false` (disclaimed)
- section_232_steel: `any_claims = false` (disclaimed)
- section_232_aluminum: `any_claims = true` (claimed!)

**Expected Result:**
```json
{
  "dependency": "section_232",
  "dependency_met": true,
  "action": "paid",
  "chapter_99_code": "9903.01.33",
  "duty_rate": 0,
  "reason": "Section 232 claims exist, must pay IEEPA reciprocal"
}
```

**Decision:** `paid`
**Reason:** At least one Section 232 claim exists (aluminum), so IEEPA reciprocal is marked as "paid"
**Business Logic:** IEEPA Reciprocal is a conditional tariff that applies when importer claims ANY Section 232 benefit. Since aluminum was claimed, this must be filed.
**Source:** `IEEPA_Reciprocal.pdf`

**Filing Line Added:**
```
9903.01.33 → IEEPA Reciprocal Tariff [paid]
```

---

#### Step 8: Calculate Duties

**Tool Called:** `calculate_duties(filing_lines=[...], product_value=10000, materials={...})`

**Duty Calculation Breakdown:**

| Program | Action | Rate | Base | Calculation | Duty Amount |
|---------|--------|------|------|-------------|-------------|
| section_301 | apply | 25% | product_value | $10,000 × 0.25 | $2,500.00 |
| ieepa_fentanyl | apply | 20% | product_value | $10,000 × 0.20 | $2,000.00 |
| section_232_copper | disclaim | 0% | - | - | $0.00 |
| section_232_steel | disclaim | 0% | - | - | $0.00 |
| section_232_aluminum | claim | 10% | material_percentage | $10,000 × 0.72 × 0.10 | $720.00 |
| ieepa_reciprocal | paid | 0% | - | - | $0.00 |

**Total Duty:** $5,220.00
**Effective Rate:** 52.20%

---

### Expected Final Output

```
## Tariff Stacking Result for HTS 8544.42.9090
**Country of Origin:** China
**Product:** USB-C cable for data transfer and charging
**Product Value:** $10,000.00
**Material Composition:** copper: 5.0%, steel: 20.0%, aluminum: 72.0%, zinc: 3.0%

### CBP Filing Lines
```
8544.42.9090
├── 9903.88.03 → Section 301 China Tariffs [apply] (25.0%)
├── 9903.01.24 → IEEPA Fentanyl Tariff [apply] (20.0%)
├── 9903.78.02 → Section 232 Copper [disclaim]
├── 9903.80.02 → Section 232 Steel [disclaim]
├── 9903.85.08 → Section 232 Aluminum [claim] (10.0%)
├── 9903.01.33 → IEEPA Reciprocal Tariff [paid]
```

### Duty Calculation
- **Product Value:** $10,000.00
- **Total Duty:** $5,220.00
- **Effective Rate:** 52.20%
```

---

### Verification Criteria

| Criteria | Expected | Pass/Fail |
|----------|----------|-----------|
| 6 programs found | 6 | ✅ |
| Section 301 included | Yes | ✅ |
| Section 301 not excluded | Yes | ✅ |
| Copper disclaimed (5% < 25%) | Yes | ✅ |
| Steel disclaimed (20% < 25%) | Yes | ✅ |
| Aluminum claimed (72% > 25%) | Yes | ✅ |
| IEEPA Reciprocal = paid (has 232 claims) | Yes | ✅ |
| Total duty = $5,220 | $5,220 | ✅ |
| Effective rate = 52.20% | 52.20% | ✅ |
| Filing lines in correct sequence | Yes | ✅ |

---

## Test Case 2: USB-C Cable - No Aluminum (Different Material Composition)

### Input Parameters

| Parameter | Value |
|-----------|-------|
| HTS Code | `8544.42.9090` |
| Country of Origin | `China` |
| Product Value | `$10,000.00` |
| Material Composition | copper: 15%, steel: 80%, aluminum: 3%, zinc: 2% |

### Expected Decisions

| Program | Decision | Reason |
|---------|----------|--------|
| section_301 | apply | HTS in List 3 |
| ieepa_fentanyl | apply | Always applies to China |
| section_232_copper | disclaim | 15% < 25% threshold |
| section_232_steel | **claim** | 80% > 25% threshold |
| section_232_aluminum | disclaim | 3% < 25% threshold |
| ieepa_reciprocal | **paid** | Steel was claimed |

### Expected Duty Calculation

| Program | Calculation | Amount |
|---------|-------------|--------|
| section_301 | $10,000 × 25% | $2,500 |
| ieepa_fentanyl | $10,000 × 20% | $2,000 |
| section_232_steel | $10,000 × 80% × 25% | $2,000 |
| **Total** | | **$6,500** |
| **Effective Rate** | | **65%** |

---

## Test Case 3: USB-C Cable - All Materials Below Threshold

### Input Parameters

| Parameter | Value |
|-----------|-------|
| HTS Code | `8544.42.9090` |
| Country of Origin | `China` |
| Product Value | `$10,000.00` |
| Material Composition | copper: 10%, steel: 10%, aluminum: 10%, plastic: 70% |

### Expected Decisions

| Program | Decision | Reason |
|---------|----------|--------|
| section_301 | apply | HTS in List 3 |
| ieepa_fentanyl | apply | Always applies to China |
| section_232_copper | disclaim | 10% < 25% threshold |
| section_232_steel | disclaim | 10% < 25% threshold |
| section_232_aluminum | disclaim | 10% < 25% threshold |
| ieepa_reciprocal | **disclaim** | NO 232 claims exist |

### Expected Duty Calculation

| Program | Calculation | Amount |
|---------|-------------|--------|
| section_301 | $10,000 × 25% | $2,500 |
| ieepa_fentanyl | $10,000 × 20% | $2,000 |
| **Total** | | **$4,500** |
| **Effective Rate** | | **45%** |

### Key Verification
- IEEPA Reciprocal should be `disclaim` (code 9903.01.25), NOT `paid`
- This is because NO Section 232 materials were claimed

---

## Test Case 4: Non-China Origin (No 301/IEEPA)

### Input Parameters

| Parameter | Value |
|-----------|-------|
| HTS Code | `8544.42.9090` |
| Country of Origin | `Germany` |
| Product Value | `$10,000.00` |
| Material Composition | copper: 5%, steel: 20%, aluminum: 72% |

### Expected Decisions

Only Section 232 programs should apply (country = "ALL"):

| Program | Decision | Reason |
|---------|----------|--------|
| section_232_copper | disclaim | 5% < 25% threshold |
| section_232_steel | disclaim | 20% < 25% threshold |
| section_232_aluminum | claim | 72% > 25% threshold |

### Expected Duty Calculation

| Program | Calculation | Amount |
|---------|-------------|--------|
| section_232_aluminum | $10,000 × 72% × 10% | $720 |
| **Total** | | **$720** |
| **Effective Rate** | | **7.2%** |

### Key Verification
- NO Section 301 (only applies to China)
- NO IEEPA Fentanyl (only applies to China)
- NO IEEPA Reciprocal (only applies to China)
- Only Section 232 programs apply (country = "ALL")

---

## Test Case 5: Product with Exclusion Match

### Input Parameters

| Parameter | Value |
|-----------|-------|
| HTS Code | `8539.50.0000` (LED lamps) |
| Country of Origin | `China` |
| Product Description | `LED lamps for medical diagnostic equipment` |
| Product Value | `$10,000.00` |

### Expected Decisions

| Program | Decision | Reason |
|---------|----------|--------|
| section_301 | **excluded** | Matches exclusion description "LED lamps specifically designed for use with medical diagnostic equipment" |

### Key Verification
- Section 301 should NOT apply because product matches exclusion criteria
- Semantic matching should identify "medical diagnostic equipment" in both descriptions

---

## Decision Logic Summary

### Why Claim vs Disclaim for Section 232?

```
IF material_percentage > threshold (25%):
    action = "claim"
    → Pay duty on that portion of product value
    → Use claim_code (e.g., 9903.85.08 for aluminum)
ELSE:
    action = "disclaim"
    → No duty for this material
    → Use disclaim_code (e.g., 9903.85.09 for aluminum)
```

**Business Rationale:** The 25% threshold determines if a product is considered a "derivative" of that material. A USB cable with 5% copper is not a "copper derivative", but one with 72% aluminum IS an "aluminum derivative".

### Why Paid vs Disclaim for IEEPA Reciprocal?

```
IF any_section_232_claims == true:
    action = "paid"
    → File with code 9903.01.33
    → Indicates Section 232 benefits were claimed
ELSE:
    action = "disclaim"
    → File with code 9903.01.25
    → Indicates no Section 232 benefits claimed
```

**Business Rationale:** IEEPA Reciprocal is a reporting mechanism. If you claimed ANY Section 232 tariff benefit, you must report it with the "paid" code. If you disclaimed all Section 232 materials, you use the "disclaim" code.

---

## Running Tests

```bash
# Run the automated test
pipenv run python scripts/test_stacking.py

# Reset and repopulate test data
pipenv run python scripts/populate_tariff_tables.py --reset
```

---

## Data Sources

All decisions trace back to government documents:

| Table | Source Documents |
|-------|------------------|
| section_301_inclusions | 301_List_1.pdf, 301_List_2.pdf, 301_List_3.pdf, 301_List_4A.pdf |
| section_301_exclusions | 301_Exclusions_FRN.pdf |
| section_232_materials | 232_Copper.pdf, 232_Steel.pdf, 232_Aluminum.pdf |
| program_codes | Various USTR/Commerce notices |
| duty_rules | CBP filing requirements |
