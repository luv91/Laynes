# Section 232 Bulk HTS Import - Design Document

**Version:** 1.1 (Corrected)
**Date:** January 2026
**Author:** System Design
**Status:** PLANNING
**Review:** Incorporates expert feedback on Chapter 99 code mapping, country exceptions, and 10-digit precision

---

## 1. Problem Statement

### Current Situation
The `section_232_materials` table has only **7 entries** covering 5 HTS codes:
- 85444290 (copper, aluminum)
- 85444220 (copper, aluminum)
- 85369085 (copper, aluminum)
- 84733051 (copper, steel, aluminum)
- 94039990 (steel, aluminum)

### The Gap
CBP publishes **10,000+ HTS codes** subject to Section 232 duties:
- ~5,000 Steel HTS codes (Chapters 72, 73, derivatives)
- ~3,000 Aluminum HTS codes (Chapter 76, derivatives)
- ~500 Copper HTS codes (per CSMS #65794272)
- 428 new derivative codes added August 2025

### Impact
When customers search HTS codes NOT in our database:
```
Customer: HTS 8302.41.6015 (door hardware with steel/aluminum)
System:   Queries section_232_materials → EMPTY
Result:   "No Section 232 applies" → WRONG!
```

---

## 2. Goal

**Import ALL CBP Section 232 HTS codes into `section_232_materials` table** so that:
1. Any HTS code searched returns correct 232 material flags
2. Stacking calculations include appropriate 232 duties
3. No customer sees incorrect "0% 232" when 232 should apply
4. **NEW:** Correct Chapter 99 codes assigned based on HTS chapter (primary vs derivative)

---

## 3. Critical Correction: Chapter 99 Codes are NOT Fixed Per Material

### V1.0 Assumption (WRONG)
```
Steel → always 9903.80.01
Aluminum → always 9903.85.08
```

### V1.1 Reality (CORRECT)

The correct Chapter 99 claim code depends on **BOTH the material AND the HTS chapter**:

| Material | HTS Category | Claim Code | Disclaim Code | Notes |
|----------|--------------|------------|---------------|-------|
| **Steel** | Chapters 72-73 (Primary) | 9903.80.01 | 9903.80.02 | Primary mill articles |
| **Steel** | Other Chapters (Derivatives) | 9903.81.91 | 9903.80.02 | Non-Chapter 73 derivatives (Note 16n) |
| **Aluminum** | Chapter 76 (Primary) | 9903.85.03 | 9903.85.09 | Primary aluminum articles |
| **Aluminum** | Other Chapters (Derivatives) | 9903.85.08 | 9903.85.09 | Non-Chapter 76 derivatives (Note 19k) |
| **Copper** | All Chapters | 9903.78.01 | 9903.78.02 | Copper is consistent across all HTS |

### Why This Matters
- HTS 7201.10.0000 (Chapter 72, steel primary) → 9903.80.01
- HTS 8302.41.6015 (Chapter 83, steel derivative) → 9903.81.91
- HTS 7601.10.3000 (Chapter 76, aluminum primary) → 9903.85.03
- HTS 8544.42.9090 (Chapter 85, aluminum derivative) → 9903.85.08

---

## 4. Country-Specific Rates (UK Exception)

### Standard Rate (All Countries except UK)
| Material | Rate | Effective Date |
|----------|------|----------------|
| Steel | 50% | June 4, 2025 (doubled from 25%) |
| Aluminum | 50% | June 4, 2025 (doubled from 25%) |
| Copper | 50% | July 31, 2025 |

### UK Exception (25% Rate)
The United Kingdom has a "prosperous deal" exception:

| Material | UK Rate | UK Claim Code | UK Disclaim Code |
|----------|---------|---------------|------------------|
| Steel | 25% | 9903.81.98 | 9903.80.02 |
| Aluminum | 25% | 9903.85.15 | 9903.85.09 |
| Copper | 50% | 9903.78.01 | 9903.78.02 | (No UK exception for copper)

### Russia Exception (200% Rate)
Russia has elevated rates - handled separately in `tariff_programs`.

### Implementation Decision
**Option A (Recommended):** Store standard (non-UK) codes in `section_232_materials`. Handle UK exception in `tariff_programs` country logic (already exists).

**Option B:** Add `country_exception` column to `section_232_materials` with separate rows for UK.

---

## 5. 10-Digit vs 8-Digit Precision

### Current Design (8-digit)
```sql
hts_8digit VARCHAR(10) NOT NULL  -- e.g., "83024160"
```

### Problem
Different 10-digit codes under the same 8-digit may have different Chapter 99 buckets:
- 8544.42.2000 → Copper only
- 8544.42.9090 → Copper + Aluminum

### Recommended Approach
**Store 10-digit, match with fallback:**

```python
def lookup_232_materials(hts_code):
    """
    Look up 232 materials with 10-digit exact match first,
    then fall back to 8-digit prefix match.
    """
    hts_10 = hts_code.replace('.', '')[:10]
    hts_8 = hts_10[:8]

    # Try exact 10-digit match first
    results = Section232Material.query.filter_by(hts_code=hts_10).all()

    # Fall back to 8-digit if no exact match
    if not results:
        results = Section232Material.query.filter(
            Section232Material.hts_code.startswith(hts_8)
        ).all()

    return results
```

### Schema Change (Minor)
```sql
-- Rename column for clarity (or keep as-is and store 10-digit)
ALTER TABLE section_232_materials RENAME COLUMN hts_8digit TO hts_code;
-- Now stores up to 10 digits without dots
```

---

## 6. Data Sources

### Official CBP Lists

| Source | Material | URL | Format |
|--------|----------|-----|--------|
| CBP Steel List (Mar 2025) | Steel | [steelHTSlist.pdf](https://content.govdelivery.com/attachments/USDHSCBP/2025/03/11/file_attachments/3192385/steelHTSlist%20final%20(1).pdf) | PDF |
| CBP Aluminum List | Aluminum | CBP GovDelivery | PDF |
| CBP Copper List | Copper | [CSMS Bulletin](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ebf0e0) | PDF |
| Aug 2025 Derivatives | Steel + Aluminum | [Federal Register 90 FR 40326](https://www.federalregister.gov/documents/2025/08/19/2025-15819/adoption-and-procedures-of-the-section-232-steel-and-aluminum-tariff-inclusions-process) | PDF |

### Important Note on PDF Parsing
The CBP PDFs contain:
1. **Explicit 10-digit codes** (easy to parse)
2. **8-digit codes** (need expansion)
3. **Bucket references** ("all codes in heading X") - require USITC expansion

**You may need USITC HTS data to expand headings to full 10-digit codes.**

### Unofficial Excel (Pre-parsed)

| Source | URL | Notes |
|--------|-----|-------|
| Descartes CustomsInfo | syslp.customsinfo.com/Sections/Home/Download/Sec232-SteelAlum.xlsx | Updated regularly |
| Deringer | anderinger.com Forms page | Unofficial but well-maintained |

---

## 7. Database Schema

### Current Table: `section_232_materials`

```sql
CREATE TABLE section_232_materials (
    id INTEGER PRIMARY KEY,
    hts_8digit VARCHAR(10) NOT NULL,      -- Consider renaming to hts_code, store 10-digit
    material VARCHAR(32) NOT NULL,         -- "steel", "aluminum", "copper"
    claim_code VARCHAR(16) NOT NULL,       -- Chapter-specific! See Section 3
    disclaim_code VARCHAR(16) NOT NULL,
    duty_rate NUMERIC(5,4) NOT NULL,       -- 0.50 for standard, varies by country
    threshold_percent NUMERIC(5,4),
    source_doc VARCHAR(256),
    content_basis VARCHAR(32),             -- "value" or "quantity"
    quantity_unit VARCHAR(16),             -- "kg"
    split_policy VARCHAR(32),              -- "if_any_content"
    split_threshold_pct NUMERIC(5,4),
    UNIQUE(hts_8digit, material)
);
```

### Recommended Addition (Optional)
```sql
ALTER TABLE section_232_materials ADD COLUMN is_derivative BOOLEAN DEFAULT FALSE;
ALTER TABLE section_232_materials ADD COLUMN effective_date DATE;
```

---

## 8. Import Script (V1.1 - Chapter-Aware)

```python
# scripts/import_232_hts_codes.py (V1.1)

import csv
from app.web.db import db
from app.web.db.models.tariff_tables import Section232Material

def get_chapter_99_codes(hts_code: str, material: str) -> dict:
    """
    Get correct Chapter 99 codes based on HTS chapter AND material.

    This is the KEY CORRECTION from V1.0 - codes are NOT fixed per material.
    """
    chapter = hts_code.replace('.', '')[:2]  # First 2 digits = HTS chapter

    if material == 'copper':
        # Copper is consistent across all chapters
        return {
            'claim_code': '9903.78.01',
            'disclaim_code': '9903.78.02',
            'duty_rate': 0.50,
            'is_derivative': chapter not in ['74']  # Chapter 74 is primary copper
        }

    elif material == 'steel':
        if chapter in ['72', '73']:
            # Primary steel (Chapters 72-73)
            return {
                'claim_code': '9903.80.01',
                'disclaim_code': '9903.80.02',
                'duty_rate': 0.50,
                'is_derivative': False
            }
        else:
            # Derivative steel (all other chapters)
            return {
                'claim_code': '9903.81.91',
                'disclaim_code': '9903.80.02',
                'duty_rate': 0.50,
                'is_derivative': True
            }

    elif material == 'aluminum':
        if chapter == '76':
            # Primary aluminum (Chapter 76)
            return {
                'claim_code': '9903.85.03',
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50,
                'is_derivative': False
            }
        else:
            # Derivative aluminum (all other chapters)
            return {
                'claim_code': '9903.85.08',
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50,
                'is_derivative': True
            }

    raise ValueError(f"Unknown material: {material}")


def import_232_from_csv(csv_path: str, material: str, source_doc: str):
    """
    Import HTS codes from CSV into section_232_materials.

    V1.1: Assigns correct Chapter 99 codes based on HTS chapter.
    """
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        count = 0
        skipped = 0

        for row in reader:
            hts_raw = row.get('hts_code', '').strip()
            hts_clean = hts_raw.replace('.', '')

            # Store up to 10 digits
            hts_code = hts_clean[:10] if len(hts_clean) >= 10 else hts_clean[:8]

            if not hts_code or len(hts_code) < 8:
                skipped += 1
                continue

            # Get chapter-specific codes
            codes = get_chapter_99_codes(hts_code, material)

            # Check if already exists
            existing = Section232Material.query.filter_by(
                hts_8digit=hts_code[:8],  # Use 8-digit for uniqueness check
                material=material
            ).first()

            if existing:
                skipped += 1
                continue

            entry = Section232Material(
                hts_8digit=hts_code,  # Store full code (up to 10 digits)
                material=material,
                claim_code=codes['claim_code'],
                disclaim_code=codes['disclaim_code'],
                duty_rate=codes['duty_rate'],
                source_doc=source_doc,
                content_basis='value',
                quantity_unit='kg',
                split_policy='if_any_content',
            )
            db.session.add(entry)
            count += 1

        db.session.commit()
        print(f"Imported {count} {material} HTS codes from {csv_path} (skipped {skipped})")


def validate_import():
    """Validate the import by checking code distribution."""
    from sqlalchemy import func

    # Count by material
    by_material = db.session.query(
        Section232Material.material,
        func.count(Section232Material.id)
    ).group_by(Section232Material.material).all()

    print("\n=== Import Validation ===")
    print("Count by material:")
    for material, count in by_material:
        print(f"  {material}: {count}")

    # Count by claim_code (verify chapter-based mapping)
    by_code = db.session.query(
        Section232Material.claim_code,
        func.count(Section232Material.id)
    ).group_by(Section232Material.claim_code).all()

    print("\nCount by claim_code:")
    for code, count in by_code:
        print(f"  {code}: {count}")

    # Sample check: verify a known derivative
    sample = Section232Material.query.filter_by(hts_8digit='85444290').all()
    print(f"\nSample HTS 8544.42.9090:")
    for s in sample:
        print(f"  {s.material}: {s.claim_code} (derivative={s.claim_code in ['9903.81.91', '9903.85.08']})")


if __name__ == '__main__':
    from app import create_app
    app = create_app()

    with app.app_context():
        # Import each material list
        import_232_from_csv('data/cbp_232_lists/steel_hts.csv', 'steel', 'CBP_Steel_Aug2025')
        import_232_from_csv('data/cbp_232_lists/aluminum_hts.csv', 'aluminum', 'CBP_Aluminum_Aug2025')
        import_232_from_csv('data/cbp_232_lists/copper_hts.csv', 'copper', 'CSMS_65794272_Copper')

        # Validate
        validate_import()
```

---

## 9. Code Changes Required

### Change 1: Update `stacking_tools.py` (Minor)

The existing lookup code works, but should use the correct claim_code from the database (not override):

```python
# Current code (line 706-709) - ALREADY CORRECT
inclusion = Section232Material.query.filter_by(
    hts_8digit=hts_8digit,
    material=material
).first()

if inclusion:
    return json.dumps({
        "included": True,
        "claim_code": inclusion.claim_code,  # ← Uses DB value, not hardcoded
        "disclaim_code": inclusion.disclaim_code,
        ...
    })
```

**No change needed** - the code already reads claim_code from the database.

### Change 2: Handle "Composition Unknown" Policy

Per CBP guidance, if metal content value is unknown, treat as full entered value:

```python
# Add to stacking logic
if content_value is None or content_value == 0:
    # Unknown content = treat as full value (1-line filing)
    content_value = product_value
    filing_lines = 1
else:
    # Known content = 2-line filing (metal + remainder)
    filing_lines = 2
```

---

## 10. Expected Data After Import

### Database Contents

```sql
SELECT COUNT(*) FROM section_232_materials;
-- Target: ~10,000+

SELECT material, claim_code, COUNT(*)
FROM section_232_materials
GROUP BY material, claim_code;

-- Expected distribution:
-- steel    | 9903.80.01 | ~3,000  (primary, Ch 72-73)
-- steel    | 9903.81.91 | ~2,000  (derivative, other chapters)
-- aluminum | 9903.85.03 | ~1,500  (primary, Ch 76)
-- aluminum | 9903.85.08 | ~2,000  (derivative, other chapters)
-- copper   | 9903.78.01 | ~500    (all copper)
```

### Sample Queries

```sql
-- Query for derivative steel article (Chapter 83)
SELECT * FROM section_232_materials WHERE hts_8digit LIKE '8302%' AND material = 'steel';
-- claim_code should be 9903.81.91 (derivative)

-- Query for primary aluminum (Chapter 76)
SELECT * FROM section_232_materials WHERE hts_8digit LIKE '7601%' AND material = 'aluminum';
-- claim_code should be 9903.85.03 (primary)
```

---

## 11. Multi-Material HTS Codes

Many HTS codes are subject to **multiple 232 regimes simultaneously**:

| HTS Code | Materials | Filing Requirement |
|----------|-----------|-------------------|
| 8544.42.2000 | Copper only | 1 metal slice |
| 8544.42.9090 | Copper + Aluminum | 2 metal slices |
| 9403.99.9045 | Steel + Aluminum | 2 metal slices |
| 8302.41.6015 | Steel + Aluminum | 2 metal slices |

### How This Works in Database

```sql
-- HTS 8544.42.9090 has TWO rows:
INSERT INTO section_232_materials VALUES
(NULL, '8544429090', 'copper', '9903.78.01', '9903.78.02', 0.50, ...),
(NULL, '8544429090', 'aluminum', '9903.85.08', '9903.85.09', 0.50, ...);
```

The stacking engine queries ALL materials for an HTS code and creates separate slices.

---

## 12. Auto Parts 232 Conflict

**Important:** If a product is subject to Auto Parts 232 (Proclamation 10908), the copper/steel/aluminum 232 duties **do not apply**.

### Handling
- Maintain a separate list of HTS codes under Auto 232
- During import, flag or exclude these codes
- OR handle in stacking logic with program priority

---

## 13. Success Criteria (V1.1)

| Test Case | Expected Result |
|-----------|-----------------|
| HTS 8302.41.6015 (Chapter 83, China) | Steel derivative (9903.81.91) + Aluminum derivative (9903.85.08) |
| HTS 7615.10.7130 (Chapter 76, China) | Aluminum primary (9903.85.03) |
| HTS 7317.00.5502 (Chapter 73, China) | Steel primary (9903.80.01) |
| HTS 8504.90.9642 (Chapter 85, China) | Steel derivative (9903.81.91) + Aluminum derivative (9903.85.08) |
| HTS 8536.90.8585 (Chapter 85, China) | Aluminum derivative (9903.85.08) only |
| HTS 8544.42.9090 (Chapter 85, UK) | Copper (9903.78.01, 50%) + Aluminum (9903.85.15, 25%) |
| Stacking calculation | Correct 50% rate (or 25% UK) applied per material |

---

## 14. File Structure

```
lanes/
├── data/
│   └── cbp_232_lists/
│       ├── steel_primary_hts.csv      # Chapter 72-73 codes
│       ├── steel_derivative_hts.csv   # Other chapter steel codes
│       ├── aluminum_primary_hts.csv   # Chapter 76 codes
│       ├── aluminum_derivative_hts.csv # Other chapter aluminum codes
│       ├── copper_hts.csv             # All copper codes
│       └── README.md                  # Source documentation
├── scripts/
│   ├── populate_tariff_tables.py      # Existing (sample data)
│   └── import_232_hts_codes.py        # V1.1: Chapter-aware import
└── readme14-10k-hts-codes-sec232.md   # This document (V1.1)
```

---

## 15. Timeline (V1.1)

| Phase | Task | Estimate |
|-------|------|----------|
| 1 | Download CBP PDFs + unofficial Excel | 1 hour |
| 2 | Parse/convert to CSV with chapter info | 3-4 hours |
| 3 | Create V1.1 import script (chapter-aware) | 2 hours |
| 4 | Test locally with validation | 2 hours |
| 5 | Deploy to Railway | 30 min |
| **Total** | | **8-10 hours** |

---

## 16. Questions Resolved

| Question | Answer |
|----------|--------|
| Are Chapter 99 codes fixed per material? | **NO** - Depends on HTS chapter (primary vs derivative) |
| How to handle UK? | Use `tariff_programs` country logic (already exists) or add UK-specific rows |
| 8-digit or 10-digit? | Store 10-digit, fall back to 8-digit match |
| What about composition unknown? | Treat as full value (1-line filing per CBP guidance) |
| Multi-material codes? | Multiple rows per HTS code (copper + aluminum = 2 rows) |

---

## 17. References

### Official Sources
- [CBP Steel HTS List (March 2025)](https://content.govdelivery.com/attachments/USDHSCBP/2025/03/11/file_attachments/3192385/steelHTSlist%20final%20(1).pdf)
- [Federal Register 90 FR 40326 - Aug 2025 Derivatives](https://www.federalregister.gov/documents/2025/08/19/2025-15819/adoption-and-procedures-of-the-section-232-steel-and-aluminum-tariff-inclusions-process)
- [CBP Copper CSMS Bulletin](https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ebf0e0)
- [CBP 232 FAQ](https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs)

### Rate Sources
- [Congress.gov - June 2025 Rate Increase to 50%](https://www.congress.gov)
- [Reuters - UK 25% Exception](https://www.reuters.com)

### Expert Guidance
- Presidential Proclamations 9704, 9705, 10895, 10896
- CSMS #65936570 (Steel Aug 2025)
- CSMS #65936615 (Aluminum Aug 2025)
- CSMS #65794272 (Copper July 2025)

---

## 18. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial design |
| 1.1 | Jan 2026 | **MAJOR:** Fixed Chapter 99 mapping (chapter-based, not just material), added UK exception handling, added 10-digit support recommendation, added composition unknown policy, added validation step |

---

*Last Updated: January 2026 (V1.1)*
