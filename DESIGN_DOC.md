# Tariff Stacking Calculator - Design Document

## The Problem: Death by a Thousand Tariffs

### Who feels this pain?

**Customs brokers and self-filing importers** who must determine:
- Which tariff programs apply to a product
- What order to file them in
- How to calculate duties correctly
- What documentation CBP requires

### Why is this hard now?

Before 2025, a typical import had 1-2 tariff considerations. Today, a single product can trigger **6+ overlapping programs**, each with:
- Different inclusion/exclusion rules
- Material composition dependencies
- Inter-program interactions
- Specific filing order requirements

**The result:** What took 10 minutes now takes 45-60 minutes per entry. Brokers report **4x-8x longer processing times** since the tariff changes began.

---

## A Real Example: USB-C Cable from China

Let's walk through what a broker faces today with a simple USB-C cable.

### The Product

```
HTS: 8544.42.9090 (Electrical conductors, for voltage ≤1kV, with connectors)
Country: China
Value: $10,000

Materials:
  Copper:   $3,000 (30%)
  Steel:    $1,000 (10%)
  Aluminum: $1,000 (10%)
  Other:    $5,000 (50%)
```

### The Broker's Mental Checklist

**Step 1: "Is this on Section 301?"**
- Pull up USTR List 1, 2, 3, 4a...
- Search for HTS 8544.42.90
- Found on List 3 → 25% tariff applies
- Check exclusions list → No active exclusion
- **Result:** 301 applies at 25% on full $10,000

**Step 2: "Does IEEPA Fentanyl apply?"**
- From China? Yes → 10% tariff (no exceptions)
- **Result:** Fentanyl applies at 10% on full $10,000

**Step 3: "What about Section 232 metals?"**
- Does product contain copper? → Yes, $3,000
- Does product contain steel? → Yes, $1,000
- Does product contain aluminum? → Yes, $1,000
- **New rule (July 2025):** Need dollar VALUE of each metal, not just percentage
- **New rule:** Must split into 2 filing lines per metal (content + non-content)
- If importer can't provide values → 50% on FULL product value (penalty)
- **Result:** 6 filing lines for 3 metals

**Step 4: "IEEPA Reciprocal - but what's the base?"**
- 232 content is EXCLUDED from IEEPA Reciprocal base
- Remaining value = $10,000 − $3,000 − $1,000 − $1,000 = **$5,000**
- **Result:** Reciprocal applies at 10% on $5,000 (not $10,000)

**Step 5: "What's the filing sequence?"**
- CBP requires specific order
- 232 must come before IEEPA Reciprocal (to calculate remaining value first)

### The Filing Output

```
Line 1:  8544.42.9090     Base HTS
Line 2:  9903.88.03       Section 301        (25% on $10,000)
Line 3:  9903.01.25       IEEPA Fentanyl     (10% on $10,000)
Line 4:  9903.78.02       232 Non-Copper     ($7,000 value, 0%)
Line 5:  9903.78.01       232 Copper Content ($3,000 value, 50%)
Line 6:  9903.85.09       232 Non-Aluminum   ($9,000 value, 0%)
Line 7:  9903.85.08       232 Aluminum       ($1,000 value, 25%)
Line 8:  9903.80.02       232 Non-Steel      ($9,000 value, 0%)
Line 9:  9903.80.01       232 Steel Content  ($1,000 value, 50%)
Line 10: 9903.01.33       IEEPA Reciprocal   (10% on $5,000)
```

**10 filing lines total.** The "non-metal" 232 lines (0% duty) are for CBP reporting only - they don't affect duty calculation.

### The Math

```
Section 301:        $10,000 × 25%  = $2,500
IEEPA Fentanyl:     $10,000 × 10%  = $1,000
232 Copper:         $3,000  × 50%  = $1,500
232 Steel:          $1,000  × 50%  = $500
232 Aluminum:       $1,000  × 25%  = $250
IEEPA Reciprocal:   $5,000  × 10%  = $500   ← on remaining value, NOT $10,000
                                    -------
Total Duty:                         $6,250  (62.5% effective rate)
```

**Unstacking calculation:**
```
Starting value:     $10,000
Less copper:        − $3,000
Less steel:         − $1,000
Less aluminum:      − $1,000
                    --------
Remaining (IEEPA):  $5,000
```

### Common Mistakes This Prevents

| Mistake | Impact |
|---------|--------|
| IEEPA Reciprocal on full $10,000 | $500 overcharge |
| Using percentages instead of $ values for 232 | Wrong duty amount |
| Wrong filing order | CBP rejection |
| Missing a program | Penalties + interest |
| Double-counting 232 content in IEEPA | $500 overcharge |

---

## Our Solution: Answer Questions Once, Get Full Stack

### The Vision

> **Importer answers all questions upfront. Broker receives full stack with audit trail.**

Instead of the broker manually checking 6+ programs, cross-referencing PDFs, and doing complex math:

1. **System asks:** HTS code, country, product description, material composition (with values)
2. **System returns:** Complete filing sequence + duty calculation + plain English explanation + sources

### How We Solved Each Layer

#### Layer 1: Section 301 (China Tariffs)

**The challenge:** 4 different lists, each with thousands of HTS codes, plus exclusions that expire and get extended.

**Our approach:**
- Parsed all USTR lists into `section_301_inclusions` table
- Parsed exclusions into `section_301_exclusions` table with expiration dates
- **Inclusion check:** Exact HTS 8-digit match (deterministic)
- **Exclusion check:** HTS match + semantic description match (LLM for fuzzy matching)

**Rules vs LLM boundary:** The inclusion/exclusion decision is deterministic. The LLM is only used to score description similarity for exclusions - it never decides rates or does math.

**Why this works:** When USTR adds codes or extends exclusions, we update table rows - no code changes.

#### Layer 2: IEEPA Fentanyl

**The challenge:** Applies to ALL products from China - no HTS check, no exclusions.

**Our approach:**
- `check_type = 'always'` in tariff_programs table
- From China? → 10% on full product value (no exceptions)

**Future-proof:** In the current ruleset (Dec 2025), Fentanyl is a blanket 10% for CN/HK. If CBP later scopes it by HTS, we just flip it to `check_type = 'hts_lookup'` with an inclusion table - no code changes.

#### Layer 3: Section 232 Metals (The Hard One)

**The challenge (July 2025 rules):**
- Duty based on material content VALUE, not percentage
- Must split into 2 filing lines per metal (non-content + content)
- If value unknown → penalty: 50% on FULL product value
- Different rates: Copper 50%, Steel 50%, Aluminum 25%

**Our approach:**
- Ask user for material VALUES (not just percentages)
- Store `content_basis = 'value'` in rules table
- Generate split lines automatically when content > 0
- Track `fallback_base_on = 'full_value'` for penalty case

**The split logic (data-driven):**
```
IF copper_value > 0:
  Line A: Non-copper content, value = $10,000 - $3,000 = $7,000, duty = 0%
  Line B: Copper content, value = $3,000, duty = 50% = $1,500
```

**Why data-driven?** We don't hardcode special cases for copper vs steel vs aluminum. Each material is just a row in `section_232_materials` with `duty_rate`, `split_policy`, and `content_basis='value'`. The same engine code runs for all three. If CBP changes the rule to "only split if copper > 10%", we update a database row, not code.

#### Layer 4: IEEPA Reciprocal (The Tricky One)

**The discovery:** CBP guidance states "Content subject to Section 232 is NOT subject to Reciprocal IEEPA."

**What this means:**
```
WRONG: IEEPA Reciprocal = $10,000 × 10% = $1,000
RIGHT: IEEPA Reciprocal = ($10,000 - $3,000 - $1,000 - $1,000) × 10% = $500
```

**Our approach - "Unstacking":**
- Track `remaining_value` as we process programs
- 232 programs have `base_effect = 'subtract_from_remaining'`
- IEEPA Reciprocal has `base_on = 'remaining_value'`
- Filing sequence ensures 232 runs BEFORE IEEPA Reciprocal

**Why data-driven?** We don't special-case "section_232_*" in code. Any program with `base_effect = 'subtract_from_remaining'` will shrink `remaining_value`, and any program with `base_on = 'remaining_value'` will use that reduced base. Currently only IEEPA Reciprocal uses remaining value, but the pattern is generic.

**The math:**
```
remaining_value = $10,000        # Start
remaining_value -= $3,000        # After copper
remaining_value -= $1,000        # After steel
remaining_value -= $1,000        # After aluminum
                  -------
remaining_value = $5,000         # IEEPA Reciprocal base
```

#### Layer 5: Filing Sequence

**The challenge:** Programs must be filed in specific order, and order affects calculations.

**Our approach:**
- `filing_sequence` column in tariff_programs table
- 301 and Fentanyl first (on full value)
- 232 metals next (to calculate remaining_value)
- IEEPA Reciprocal last (uses remaining_value)

```
filing_sequence:
  1 → section_301
  2 → ieepa_fentanyl
  3 → section_232_copper
  4 → section_232_steel
  5 → section_232_aluminum
  6 → ieepa_reciprocal
```

**Why this order?** It's not arbitrary - it's legally forced:
- **301 and Fentanyl** don't care about metal content, so they always see full product value
- **232 metals** both add duty AND change the base for later programs, so they must run before Reciprocal
- **Reciprocal** is defined by CBP to exclude 232 content, so it must run after all 232 content has been accounted for

---

## Design Decisions: Why We Built It This Way

### Decision 1: Data-Driven Rules

**The question:** Hardcode rules in Python or store in database?

**We chose database because:**
- Tariff rates change frequently (copper went 25% → 50% in July 2025)
- New programs get added (IEEPA didn't exist 2 years ago)
- Exclusions expire and get extended
- With database: update a row. With code: deploy new version.

### Decision 2: Content Value, Not Percentage

**The question:** Calculate 232 duty on percentage or dollar value?

**CBP decided for us (July 2025):** Dollar value of material content.

**Why it matters:**
- Old way: 5% copper × $10,000 × 25% = $125
- New way: $3,000 copper value × 50% = $1,500
- Big difference when material prices vary

### Decision 3: Line Splitting

**The question:** One filing line or two per 232 material?

**CBP requires two:**
- Line 1: Non-copper content (for reporting, 0% duty)
- Line 2: Copper content (actual duty)

**Why CBP wants this:** Tracks material content separately for trade statistics.

### Decision 4: IEEPA Unstacking

**The question:** Should 232 content reduce IEEPA Reciprocal base?

**CBP says yes:** "Content subject to Section 232 is NOT subject to Reciprocal IEEPA."

**Business impact:** Without unstacking, we'd overcharge $500 on our USB-C example. Multiply by thousands of entries = significant overcollection.

---

## The Audit Trail: Why Every Decision is Traceable

Brokers need to explain their calculations to importers and CBP. Every output includes:

```
Decision: Section 301 applies (25%)
  Reason: HTS 85444290 found in List 3
  Source: USTR Notice 2018-0026, page 47

Decision: IEEPA Reciprocal base = $5,000 (not $10,000)
  Reason: 232 content excluded per CBP guidance
  Calculation: $10,000 - $3,000(Cu) - $1,000(Al) - $1,000(Steel)
  Source: CBP IEEPA FAQ, Section 4.2
```

---

## Business Impact

### Time Savings

| Metric | Before | After |
|--------|--------|-------|
| Time per complex entry | 45-60 min | ~5 min |
| Entries per day (per broker) | 8-12 | 40-60 |
| Error rate | High (manual) | Near-zero (deterministic) |

### Error Reduction

| Error Type | Manual Risk | System |
|------------|-------------|--------|
| Miss a program | Common | Impossible (checks all) |
| Wrong filing order | Common | Enforced by sequence |
| Math errors | Common | Calculated exactly |
| Outdated rates | Common | Database always current |
| IEEPA overcharge | Very common | Unstacking handled |

### The ROI Conversation

> "If we can solve this - importer answers all questions up front and broker receives a full stack with an audit trail - what do you think would be the business impact for brokerages?"
>
> "Game changer. Seriously. It's where all brokers' time is going currently."

**Conservative estimate:**
- 50 minutes saved per complex entry
- 10 complex entries per broker per day
- 500 minutes = 8+ hours saved per broker per day
- That's essentially **doubling broker capacity** without hiring

---

## What's In Scope vs Future

### Currently Implemented

| Program | Status |
|---------|--------|
| Section 301 (Lists 1-4) | ✅ With exclusions |
| Section 232 Copper | ✅ 50%, content-value, split lines |
| Section 232 Steel | ✅ 50%, content-value, split lines |
| Section 232 Aluminum | ✅ 25%, content-value, split lines |
| IEEPA Fentanyl | ✅ 10% on full value |
| IEEPA Reciprocal | ✅ With unstacking |
| Audit trail | ✅ Full citations |

### Future Additions

| Program | Complexity |
|---------|------------|
| AD/CVD (Antidumping) | High - case-specific rates |
| FTAs (USMCA, etc.) | High - rules of origin |
| MPF/HMF | Low - simple percentages |
| Auto 232 | Medium - short-circuits other 232s |
| Quota/TRQ | Medium - quantity tracking |

---

## The Complete USB-C Example

**Input:**
```
HTS: 8544.42.9090
Country: China
Value: $10,000
Copper: $3,000 (30%)
Steel: $1,000 (10%)
Aluminum: $1,000 (10%)
```

**Output:**
```
FILING SEQUENCE
===============
1. 9903.88.03  Section 301           25% on $10,000  = $2,500
2. 9903.01.25  IEEPA Fentanyl        10% on $10,000  = $1,000
3. 9903.78.02  232 Non-Copper        0% on $7,000    = $0
4. 9903.78.01  232 Copper Content    50% on $3,000   = $1,500
5. 9903.80.02  232 Non-Steel         0% on $9,000    = $0
6. 9903.80.01  232 Steel Content     50% on $1,000   = $500
7. 9903.85.09  232 Non-Aluminum      0% on $9,000    = $0
8. 9903.85.08  232 Aluminum Content  25% on $1,000   = $250
9. 9903.01.33  IEEPA Reciprocal      10% on $5,000   = $500
                                                      ------
TOTAL DUTY                                            $6,250

Effective Rate: 62.5%

IEEPA UNSTACKING DETAIL
=======================
Starting value:    $10,000
Less copper:       -$3,000
Less steel:        -$1,000
Less aluminum:     -$1,000
Remaining base:    $5,000 ← IEEPA Reciprocal calculated on this
```

---

## References

- [USTR Section 301 Actions](https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions)
- [CBP Section 232 FAQ](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs)
- [CBP CSMS #65794272](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ebf0e0) - Copper content-value rules (July 2025)
- [CBP IEEPA FAQ](https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ)
