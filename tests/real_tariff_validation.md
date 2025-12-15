# Real Tariff Rate Validation

This document compares our sample test data against **actual 2025 tariff rates** from official sources.

---

## HTS 8544.42.90.90 - USB-C Cable from China

### Real Tariff Rates (2025)

| Tariff Program | Our Sample Rate | Real Rate (2025) | Status | Source |
|----------------|-----------------|------------------|--------|--------|
| **Base Duty** | Not included | **2.6%** | ❌ MISSING | [USITC HTS](https://hts.usitc.gov) |
| **Section 301 (List 3)** | 25% | **25%** | ✅ Correct | [USTR](https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions) |
| **Section 232 Steel** | 25% | **50%** (increased 2025) | ⚠️ Outdated | [CBP FAQ](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs) |
| **Section 232 Aluminum** | 10% | **25%** (may be 50%) | ⚠️ Check | [White & Case](https://www.whitecase.com/insight-alert/trump-administration-increases-steel-and-aluminum-section-232-tariffs-50-and-narrows) |
| **IEEPA Fentanyl** | 20% | **10%** (Nov 2025) | ⚠️ Outdated | [CBP IEEPA FAQ](https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ) |
| **IEEPA Reciprocal** | 0% (disclaim) | **10%** or higher | ⚠️ Outdated | [Thompson Coburn](https://www.thompsoncoburn.com/insights/58-november-4-2025-reducing-the-20-ieepa-fentanyl-tariffs-on-china-to-10-reciprocal-tariffs-on-china-remain-at-10-until-november-2026/) |

---

## Real-World Example: USB-C Cable Import

### Invoice Example

```
COMMERCIAL INVOICE
==================
Seller: Shenzhen Electronics Co., Ltd
        123 Technology Road, Shenzhen, China

Buyer:  ABC Imports LLC
        456 Commerce St, Los Angeles, CA 90001

Date:   December 7, 2025
PO#:    PO-2025-1234

+------------------------------------------------------------------+
| Item | Description                  | Qty    | Unit   | Total    |
+------+------------------------------+--------+--------+----------|
| 1    | USB Type-C Cable, 1m         | 1,000  | $10.00 | $10,000  |
|      | Data/Charging, Braided       |        |        |          |
|      | Material: Copper wiring,     |        |        |          |
|      | Aluminum shell, Steel braid  |        |        |          |
+------------------------------------------------------------------+
| Country of Origin: CHINA (CN)                                    |
| HTS Code: 8544.42.90.90                                          |
| Total Invoice Value: $10,000.00 USD                              |
+------------------------------------------------------------------+
```

### Material Composition (from product spec)
- Copper conductors: 5%
- Steel braiding: 20%
- Aluminum connector shells: 72%
- Plastic insulation: 3%

---

## Tariff Calculation: Our System vs Real

### Our System Output (Current Sample Data)

```
Total Duty: $5,220.00 (52.20%)

Breakdown:
- Section 301: $2,500 (25%)
- IEEPA Fentanyl: $2,000 (20%)
- Section 232 Aluminum: $720 (72% × 10%)
- IEEPA Reciprocal: $0 (disclaim → paid, no extra duty)
```

### Real Calculation (2025 Rates)

```
Product Value: $10,000

1. BASE DUTY: $10,000 × 2.6% = $260
   (We were missing this!)

2. SECTION 301 (List 3): $10,000 × 25% = $2,500
   ✅ Same as our calculation

3. IEEPA FENTANYL: $10,000 × 10% = $1,000
   (We had 20%, now reduced to 10%)

4. SECTION 232 ALUMINUM:
   - Material: 72% > 25% threshold → CLAIM
   - New rate: 25% (was 10%)
   - Duty: $10,000 × 72% × 25% = $1,800
   (We calculated $720 with 10% rate)

5. SECTION 232 STEEL:
   - Material: 20% < 25% threshold → DISCLAIM
   - No additional duty
   ✅ Same as our calculation

6. SECTION 232 COPPER:
   - Material: 5% < 25% threshold → DISCLAIM
   - No additional duty
   ✅ Same as our calculation

7. IEEPA RECIPROCAL:
   - Has 232 claims (aluminum) → use "paid" code
   - Rate: 10% additional
   - Duty: $10,000 × 10% = $1,000
   (We had 0% - this is a significant miss!)

TOTAL REAL DUTY: $260 + $2,500 + $1,000 + $1,800 + $1,000 = $6,560
EFFECTIVE RATE: 65.6%
```

### Comparison Summary

| Component | Our Calculation | Real Calculation | Difference |
|-----------|-----------------|------------------|------------|
| Base Duty | $0 | $260 | -$260 |
| Section 301 | $2,500 | $2,500 | $0 |
| IEEPA Fentanyl | $2,000 | $1,000 | +$1,000 |
| Section 232 Aluminum | $720 | $1,800 | -$1,080 |
| IEEPA Reciprocal | $0 | $1,000 | -$1,000 |
| **TOTAL** | **$5,220** | **$6,560** | **-$1,340** |
| **Effective Rate** | **52.2%** | **65.6%** | **-13.4%** |

---

## What Needs to be Updated

### 1. Add Base Duty Rate

We need to add the base HTS duty rate (from Column 1 General) to calculations:

```sql
-- Add base_duty_rate column to tariff calculation
ALTER TABLE section_301_inclusions ADD COLUMN base_duty_rate DECIMAL(5,4);
UPDATE section_301_inclusions SET base_duty_rate = 0.026 WHERE hts_8digit = '85444290';
```

### 2. Update Section 232 Rates

```sql
-- Update to current 2025 rates (may need verification)
UPDATE section_232_materials SET duty_rate = 0.50 WHERE material = 'steel';  -- Was 25%, now 50%
UPDATE section_232_materials SET duty_rate = 0.25 WHERE material = 'aluminum';  -- Was 10%, now 25%
UPDATE section_232_materials SET duty_rate = 0.25 WHERE material = 'copper';  -- Was 25%, check if now 50%
```

### 3. Update IEEPA Fentanyl Rate

```sql
-- Update to current rate (10% as of Nov 2025)
UPDATE program_codes SET duty_rate = 0.10 WHERE program_id = 'ieepa_fentanyl';
```

### 4. Add IEEPA Reciprocal Duty

The IEEPA Reciprocal "paid" action should have a duty rate, not 0%:

```sql
-- Add duty rate for reciprocal tariff
UPDATE program_codes SET duty_rate = 0.10 WHERE program_id = 'ieepa_reciprocal' AND action = 'paid';
```

---

## CRITICAL: Tariffs Change Frequently!

The tariff rates have changed multiple times in 2025 alone:

| Date | Event | Impact |
|------|-------|--------|
| Feb 4, 2025 | IEEPA Fentanyl starts | 10% duty |
| Mar 3, 2025 | IEEPA Fentanyl increase | 20% duty |
| Mar 12, 2025 | Section 232 increase | Steel/Aluminum to 50% |
| Apr 2025 | Reciprocal tariff chaos | 84% → 125% → back to 10% |
| Nov 10, 2025 | US-China deal | IEEPA reduced to 10% |

**Conclusion:** Our system needs a way to track **effective dates** and update rates based on the import date.

---

## Sources

1. [USTR Section 301 Tariff Actions](https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions)
2. [CBP Section 232 FAQ](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs)
3. [CBP IEEPA FAQ](https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ)
4. [USITC Harmonized Tariff Schedule](https://hts.usitc.gov/)
5. [White & Case - Section 232 Increases](https://www.whitecase.com/insight-alert/trump-administration-increases-steel-and-aluminum-section-232-tariffs-50-and-narrows)
6. [Thompson Coburn - IEEPA Update](https://www.thompsoncoburn.com/insights/58-november-4-2025-reducing-the-20-ieepa-fentanyl-tariffs-on-china-to-10-reciprocal-tariffs-on-china-remain-at-10-until-november-2026/)
