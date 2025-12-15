# Lanes – Stacking Feature Implementation (v5.0)

## Overview

This document combines v4.0 (Entry Slices) with v5.0 (Country-Specific Rates). All test cases and calculations reflect the **correct v5.0 rates** as of December 2025.

---

## Key Changes in v5.0

| Program | v4.0 Rate | v5.0 Rate |
|---------|-----------|-----------|
| Section 232 Steel | 25% (all) | **50%** (default), **25%** (UK exception) |
| Section 232 Aluminum | 25% (all) | **50%** (default), **25%** (UK exception) |
| Section 232 Copper | 50% (all) | 50% (all) |
| IEEPA Reciprocal | 10% (all) | **EU: 15% - MFN**, UK: 10%, Others: 10% |

---

## v5.0 Canonical Rates (December 2025)

### By Country Group

| Program | Default | EU | UK | CN |
|---------|---------|----|----|-----|
| Section 232 Steel | 50% | 50% | **25%** | 50% |
| Section 232 Aluminum | 50% | 50% | **25%** | 50% |
| Section 232 Copper | 50% | 50% | 50% | 50% |
| IEEPA Reciprocal | 10% | **15% - MFN** | 10% | 10% |
| Section 301 | N/A | N/A | N/A | 25% |
| IEEPA Fentanyl | N/A | N/A | N/A | 10% |

### MFN Base Rates (for EU Ceiling Formula)

| HTS Code | MFN Rate | EU Reciprocal Rate |
|----------|----------|--------------------|
| 8544.42.9090 | 2.6% | 12.4% (15% - 2.6%) |
| 8539.50.00 | 2.0% | 13.0% (15% - 2.0%) |
| 8471.30.01 | 0.0% | 15.0% (15% - 0.0%) |
| 2934.99.9050 | 6.4% | 8.6% (15% - 6.4%) |

---

## Test Case Outputs (v5.0 Format)

### Test Case 1: UK Chemical (Annex II Exempt)

**Input:**
```json
{
  "hts_code": "2934.99.9050",
  "country_of_origin": "UK",
  "product_value": 1000.0,
  "materials": {}
}
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v5.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           2934.99.9050
Country of Origin:  UK
Country Group:      UK
Product Value:      $1,000.00
Materials:          None

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: full_product                                                       │
│ Base HTS: 2934.99.9050                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action │ Variant         │ Rate  │
├─────┼─────────────┼──────────────────────┼────────┼─────────────────┼───────┤
│  1  │ 9903.01.32  │ IEEPA Reciprocal     │ EXEMPT │ annex_ii_exempt │  0%   │
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount │ Rate Source
─────────────────────┼─────────────┼────────┼─────────────┼──────────────────
IEEPA Reciprocal     │  $1,000.00  │   0%   │      $0.00  │ annex_ii_exempt

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $0.00
EFFECTIVE RATE:  0.0%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 2: China USB-C Cable (3 Metals - v5.0 Rates)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "China",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**v5.0 Calculation:**
```
Section 301:        $10,000 × 25% = $2,500
IEEPA Fentanyl:     $10,000 × 10% = $1,000
232 Copper:         $3,000 × 50%  = $1,500
232 Steel:          $1,000 × 50%  = $500
232 Aluminum:       $1,000 × 50%  = $500    ← v5.0: 50% not 25%
IEEPA Reciprocal:   $5,000 × 10%  = $500
                                   ───────
TOTAL:                             $6,500   ← v5.0: was $6,250
EFFECTIVE RATE:                    65.0%    ← v5.0: was 62.5%
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v5.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  China
Country Group:      CN
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%), steel: $1,000 (10%), aluminum: $1,000 (10%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $5,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant     │ Rate    │
├─────┼─────────────┼──────────────────────┼──────────┼─────────────┼─────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -           │ 25%     │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -           │ 10%     │
│  3  │ 9903.01.25  │ IEEPA Reciprocal     │ PAID     │ taxable     │ 10%     │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -           │  0%     │
│  5  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -           │  0%     │
│  6  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -           │  0%     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ -            │ 50%    │
│  5  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  6  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 3: steel_slice                                                        │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  5  │ 9903.80.01  │ Section 232 Steel    │ CLAIM    │ -            │ 50%    │
│  6  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 4: aluminum_slice                                                     │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  5  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  6  │ 9903.85.08  │ Section 232 Aluminum │ CLAIM    │ -            │ 50%    │ ← v5.0: 50%
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION (v5.0)
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount │ Rate Source
─────────────────────┼─────────────┼────────┼─────────────┼──────────────────
Section 301          │ $10,000.00  │  25%   │  $2,500.00  │ fixed_rate_CN
IEEPA Fentanyl       │ $10,000.00  │  10%   │  $1,000.00  │ fixed_rate_CN
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00  │ fixed_rate_default
Section 232 Steel    │  $1,000.00  │  50%   │    $500.00  │ fixed_rate_default
Section 232 Aluminum │  $1,000.00  │  50%   │    $500.00  │ fixed_rate_default ← v5.0
IEEPA Reciprocal     │  $5,000.00  │  10%   │    $500.00  │ fixed_rate_default
                     │             │        │             │
                     │             │ TOTAL  │  $6,500.00  │ ← v5.0: was $6,250

───────────────────────────────────────────────────────────────────────────────
                           IEEPA UNSTACKING
───────────────────────────────────────────────────────────────────────────────
Initial Product Value:    $10,000.00
  − Copper content:        −$3,000.00
  − Steel content:         −$1,000.00
  − Aluminum content:      −$1,000.00
                          ───────────
Remaining Value (IEEPA):   $5,000.00

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $6,500.00        ← v5.0: was $6,250.00
EFFECTIVE RATE:  65.0%            ← v5.0: was 62.5%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 3: Germany USB-C Cable (v5.0 - EU 15% Ceiling + IEEPA Reciprocal)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "Germany",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**v5.0 Calculation:**
```
232 Copper:         $3,000 × 50%   = $1,500
232 Steel:          $1,000 × 50%   = $500     ← v5.0: 50% not 25%
232 Aluminum:       $1,000 × 50%   = $500     ← v5.0: 50% not 25%
IEEPA Reciprocal:   $5,000 × 12.4% = $620     ← v5.0: EU ceiling (15% - 2.6% MFN)
                                    ───────
TOTAL:                              $3,120    ← v5.0: was $2,250
EFFECTIVE RATE:                     31.2%     ← v5.0: was 22.5%
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v5.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  Germany
Country Group:      EU                        ← v5.0: Country group lookup
MFN Base Rate:      2.6%                      ← v5.0: For EU ceiling formula
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%), steel: $1,000 (10%), aluminum: $1,000 (10%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $5,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant     │ Rate    │
├─────┼─────────────┼──────────────────────┼──────────┼─────────────┼─────────┤
│  1  │ 9903.01.25  │ IEEPA Reciprocal     │ PAID     │ taxable     │ 12.4%   │ ← v5.0
│  2  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -           │  0%     │
│  3  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -           │  0%     │
│  4  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -           │  0%     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  2  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ -            │ 50%    │
│  3  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  4  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 3: steel_slice                                                        │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  2  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  3  │ 9903.80.01  │ Section 232 Steel    │ CLAIM    │ -            │ 50%    │ ← v5.0
│  4  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 4: aluminum_slice                                                     │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  2  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  3  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  4  │ 9903.85.08  │ Section 232 Aluminum │ CLAIM    │ -            │ 50%    │ ← v5.0
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION (v5.0)
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate   │ Duty Amount │ Rate Source
─────────────────────┼─────────────┼─────────┼─────────────┼────────────────────────
Section 232 Copper   │  $3,000.00  │  50.0%  │  $1,500.00  │ fixed_rate_default
Section 232 Steel    │  $1,000.00  │  50.0%  │    $500.00  │ fixed_rate_default
Section 232 Aluminum │  $1,000.00  │  50.0%  │    $500.00  │ fixed_rate_default
IEEPA Reciprocal     │  $5,000.00  │  12.4%  │    $620.00  │ EU 15% ceiling: 15%-2.6%
                     │             │         │             │
                     │             │  TOTAL  │  $3,120.00  │ ← v5.0

───────────────────────────────────────────────────────────────────────────────
                           IEEPA UNSTACKING
───────────────────────────────────────────────────────────────────────────────
Initial Product Value:    $10,000.00
  − Copper content:        −$3,000.00
  − Steel content:         −$1,000.00
  − Aluminum content:      −$1,000.00
                          ───────────
Remaining Value (IEEPA):   $5,000.00

───────────────────────────────────────────────────────────────────────────────
                           v5.0 RATE METADATA
───────────────────────────────────────────────────────────────────────────────
Country Group:        EU
MFN Base Rate:        2.6%
IEEPA Reciprocal:     15.0% - 2.6% = 12.4% (EU ceiling formula)
Rates As Of:          2025-12-10

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $3,120.00        ← v5.0: was $2,250.00
EFFECTIVE RATE:  31.2%            ← v5.0: was 22.5%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 4: UK USB-C Cable (v5.0 - 232 Exception)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "UK",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**v5.0 Calculation:**
```
232 Copper:         $3,000 × 50%  = $1,500   (no UK exception for copper)
232 Steel:          $1,000 × 25%  = $250     ← v5.0: UK exception
232 Aluminum:       $1,000 × 25%  = $250     ← v5.0: UK exception
IEEPA Reciprocal:   $5,000 × 10%  = $500     (UK not EU, no ceiling)
                                   ───────
TOTAL:                             $2,500
EFFECTIVE RATE:                    25.0%
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v5.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  UK
Country Group:      UK                        ← v5.0: Country group lookup
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%), steel: $1,000 (10%), aluminum: $1,000 (10%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $5,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant     │ Rate    │
├─────┼─────────────┼──────────────────────┼──────────┼─────────────┼─────────┤
│  1  │ 9903.01.25  │ IEEPA Reciprocal     │ PAID     │ taxable     │ 10%     │
│  2  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -           │  0%     │
│  3  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -           │  0%     │
│  4  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -           │  0%     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  2  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ -            │ 50%    │
│  3  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  4  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 3: steel_slice                                                        │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  2  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  3  │ 9903.80.01  │ Section 232 Steel    │ CLAIM    │ -            │ 25%    │ ← UK
│  4  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 4: aluminum_slice                                                     │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  2  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  3  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  4  │ 9903.85.08  │ Section 232 Aluminum │ CLAIM    │ -            │ 25%    │ ← UK
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION (v5.0)
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount │ Rate Source
─────────────────────┼─────────────┼────────┼─────────────┼──────────────────
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00  │ fixed_rate_default
Section 232 Steel    │  $1,000.00  │  25%   │    $250.00  │ fixed_rate_UK ←
Section 232 Aluminum │  $1,000.00  │  25%   │    $250.00  │ fixed_rate_UK ←
IEEPA Reciprocal     │  $5,000.00  │  10%   │    $500.00  │ fixed_rate_UK
                     │             │        │             │
                     │             │ TOTAL  │  $2,500.00  │

───────────────────────────────────────────────────────────────────────────────
                           IEEPA UNSTACKING
───────────────────────────────────────────────────────────────────────────────
Initial Product Value:    $10,000.00
  − Copper content:        −$3,000.00
  − Steel content:         −$1,000.00
  − Aluminum content:      −$1,000.00
                          ───────────
Remaining Value (IEEPA):   $5,000.00

───────────────────────────────────────────────────────────────────────────────
                           v5.0 RATE METADATA
───────────────────────────────────────────────────────────────────────────────
Country Group:        UK
232 Steel/Aluminum:   25% (UK exception)
IEEPA Reciprocal:     10% (flat, UK not EU)
Rates As Of:          2025-12-10

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $2,500.00
EFFECTIVE RATE:  25.0%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 5: Vietnam USB-C Cable (v5.0 - Default Rates)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "Vietnam",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**v5.0 Calculation:**
```
232 Copper:         $3,000 × 50%  = $1,500
232 Steel:          $1,000 × 50%  = $500
232 Aluminum:       $1,000 × 50%  = $500
IEEPA Reciprocal:   $5,000 × 10%  = $500    (default rate)
                                   ───────
TOTAL:                             $3,000
EFFECTIVE RATE:                    30.0%
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v5.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  Vietnam
Country Group:      default                   ← v5.0: Fallback to default
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%), steel: $1,000 (10%), aluminum: $1,000 (10%)

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION (v5.0)
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount │ Rate Source
─────────────────────┼─────────────┼────────┼─────────────┼──────────────────
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00  │ fixed_rate_default
Section 232 Steel    │  $1,000.00  │  50%   │    $500.00  │ fixed_rate_default
Section 232 Aluminum │  $1,000.00  │  50%   │    $500.00  │ fixed_rate_default
IEEPA Reciprocal     │  $5,000.00  │  10%   │    $500.00  │ fixed_rate_default
                     │             │        │             │
                     │             │ TOTAL  │  $3,000.00  │

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $3,000.00
EFFECTIVE RATE:  30.0%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 6: China Copper Only (v5.0)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "China",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0
  }
}
```

**v5.0 Calculation:**
```
Section 301:        $10,000 × 25% = $2,500
IEEPA Fentanyl:     $10,000 × 10% = $1,000
232 Copper:         $3,000 × 50%  = $1,500
IEEPA Reciprocal:   $7,000 × 10%  = $700     (remaining after copper)
                                   ───────
TOTAL:                             $5,700
EFFECTIVE RATE:                    57.0%
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v5.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  China
Country Group:      CN
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $7,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant     │ Rate    │
├─────┼─────────────┼──────────────────────┼──────────┼─────────────┼─────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -           │ 25%     │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -           │ 10%     │
│  3  │ 9903.01.25  │ IEEPA Reciprocal     │ PAID     │ taxable     │ 10%     │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -           │  0%     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ -            │ 50%    │
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION (v5.0)
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount │ Rate Source
─────────────────────┼─────────────┼────────┼─────────────┼──────────────────
Section 301          │ $10,000.00  │  25%   │  $2,500.00  │ fixed_rate_CN
IEEPA Fentanyl       │ $10,000.00  │  10%   │  $1,000.00  │ fixed_rate_CN
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00  │ fixed_rate_default
IEEPA Reciprocal     │  $7,000.00  │  10%   │    $700.00  │ fixed_rate_default
                     │             │        │             │
                     │             │ TOTAL  │  $5,700.00  │

───────────────────────────────────────────────────────────────────────────────
                           IEEPA UNSTACKING
───────────────────────────────────────────────────────────────────────────────
Initial Product Value:    $10,000.00
  − Copper content:        −$3,000.00
                          ───────────
Remaining Value (IEEPA):   $7,000.00

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $5,700.00
EFFECTIVE RATE:  57.0%
═══════════════════════════════════════════════════════════════════════════════
```

---

## Summary: v4.0 vs v5.0 Comparison

| Test Case | Country | v4.0 Total | v5.0 Total | Change |
|-----------|---------|-----------|-----------|--------|
| USB-C 3 Metals | China | $6,250 | **$6,500** | +$250 (Alum 50%) |
| USB-C 3 Metals | Germany | $2,250 | **$3,120** | +$870 (IEEPA + Alum/Steel 50%) |
| USB-C 3 Metals | UK | N/A | **$2,500** | UK exception (25% steel/alum) |
| USB-C 3 Metals | Vietnam | N/A | **$3,000** | Default rates |
| Chemical | UK | $0 | $0 | Annex II exempt |
| USB-C Copper Only | China | $5,700 | $5,700 | No change |

---

## v5.0 Sources

| Rule | Source | Effective Date |
|------|--------|----------------|
| EU 15% Ceiling | CBP CSMS #65829726 | August 7, 2025 |
| 232 Steel/Aluminum → 50% | White House Fact Sheet | June 4, 2025 |
| UK Exception (25%) | Thompson Hine Analysis | June 4, 2025 |
| 232 Copper 50% | CBP CSMS #65794272 | July 31, 2025 |

---

## Running v5.0 Tests

```bash
# Populate v5.0 database tables
pipenv run python scripts/populate_tariff_tables.py --reset

# Run v5.0 rate lookup tests
pipenv run python scripts/test_v5_rates.py

# Start server for frontend testing
pipenv run flask run --port 5001
```
