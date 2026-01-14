# Tariff System Refactoring Plan

**Date:** January 14, 2026
**Status:** PLANNING
**Goal:** Consolidate fragmented data sources into unified temporal architecture

---

## Executive Summary

The tariff system has excellent architecture layers (watchers, pipeline, temporal tables, Write Gate) but suffers from **fragmented data sources** and **disconnected import scripts**. This document outlines the refactoring needed to unify the system.

---

## Current Architecture (KEEP - Layers are Good)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 6: WRITE GATE (Dual-LLM Verification)                   ✓ KEEP      │
│  - Gemini extracts, GPT-4 verifies                                          │
│  - Auto-inserts to temporal tables                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 5: STACKING CALCULATOR                                   ✓ KEEP      │
│  - build_entry_stack() for duty calculation                                 │
│  - Uses get_rate_as_of() for temporal queries                              │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 4: QUERY (Temporal Lookups)                              ✓ KEEP      │
│  - Section301Rate.get_rate_as_of(hts, date)                                │
│  - Section232Rate.get_rate_as_of(hts, material, country, date)             │
│  - IeepaRate.get_rate_as_of(program, country, date)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 3: TEMPORAL STORAGE                                      ✓ KEEP      │
│  - Section301Rate (effective_start, effective_end)                          │
│  - Section232Rate (effective_start, effective_end)                          │
│  - IeepaRate (effective_start, effective_end)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 2: INGESTION PIPELINE                                    ✓ KEEP      │
│  - FETCH → RENDER → CHUNK → EXTRACT → VALIDATE → COMMIT                    │
│  - IngestJob queue with status tracking                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  Layer 1: DISCOVERY (Watchers)                                  ✓ KEEP      │
│  - FederalRegisterWatcher, CBPCSMSWatcher, USITCWatcher                    │
│  - GitHub Actions runs daily at 6 AM UTC                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**All 6 layers are correctly designed and should be KEPT.**

---

## The Problem: Fragmented Data Sources

### Current State (BAD)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA SOURCES - FRAGMENTED                                      ✗ FIX      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  /data/section_301_hts_codes.csv (1.5 MB)    ─┐                            │
│  /data/section_301_2024_review.csv (75 KB)   ─┼──→ Conflicting data!       │
│  /docs/section301_csv_only_GPT/* (7.2 MB)    ─┘    Different sources       │
│                                                                             │
│  scripts/populate_tariff_tables.py     ─┐                                  │
│  scripts/import_section_301_csv.py     ─┼──→ Multiple scripts, not all     │
│  scripts/import_2024_review_rates.py   ─┘    called in deploy!             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Target State (GOOD)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA SOURCES - UNIFIED                                         ✓ TARGET   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  /data/section_301_rates_temporal.csv        ──→ ONE file, ALL rates       │
│  (contains effective_start, effective_end)       with time periods         │
│                                                                             │
│  scripts/populate_tariff_tables.py           ──→ ONE script reads ONE CSV  │
│  (reads unified temporal CSV)                    and populates temporal    │
│                                                  tables correctly          │
│                                                                             │
│  GitHub Actions (daily)                      ──→ Future changes detected   │
│  + WriteGate                                     and auto-inserted         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Files Analysis

### REDUNDANT FILES - DELETE

| File/Directory | Size | Reason | Action |
|----------------|------|--------|--------|
| `/docs/section301_csv_only_GPT/` | 7.2 MB | GPT-generated intermediate files, superseded by `/data/section_301_hts_codes.csv` | **DELETE** |
| `/docs/section301_fix_pack/*.csv` | ~100 KB | Patch files, fixes already integrated | **DELETE** |
| `/docs/mfn_base_rates_pack/` | ~5 MB | Duplicate of `/data/mfn_base_rates_8digit.csv` | **DELETE** |

**Total space recovered: ~12.3 MB**

### ORPHANED SCRIPTS - ARCHIVE OR DELETE

| Script | Purpose | Called By | Status | Action |
|--------|---------|-----------|--------|--------|
| `scripts/import_section_301_csv.py` | Bulk import static Section 301 data | Nothing | ORPHANED | **ARCHIVE** (dangerous if called) |
| `scripts/import_mfn_base_rates.py` | Import MFN base rates | Nothing | ORPHANED | **INTEGRATE** into populate |
| `scripts/parse_fr_2024_review.py` | Parse Federal Register XML | Nothing | ORPHANED | **DELETE** (output not used) |
| `scripts/analyze_301_csvs.py` | Debugging utility | Nothing | ORPHANED | **DELETE** |
| `scripts/populate_v6_tables.py` | Old version | Nothing | OBSOLETE | **DELETE** |

### PRODUCTION SCRIPTS - KEEP & MODIFY

| Script | Purpose | Called By | Action |
|--------|---------|-----------|--------|
| `scripts/populate_tariff_tables.py` | Master initialization | `railway.toml` | **MODIFY** to use unified CSV |
| `scripts/import_2024_review_rates.py` | 2024 review temporal rates | `railway.toml` | **MERGE** into populate_tariff_tables.py |
| `scripts/run_watchers.py` | Poll regulatory sources | GitHub Actions | **KEEP** |
| `scripts/process_ingest_queue.py` | Process ingestion queue | GitHub Actions | **KEEP** |
| `scripts/parse_cbp_232_lists.py` | Parse CBP DOCX → CSV | Manual | **KEEP** (one-time use) |

### DATA FILES - CONSOLIDATE

| Current Files | Action | Target |
|---------------|--------|--------|
| `/data/section_301_hts_codes.csv` | MERGE | `/data/section_301_rates_temporal.csv` |
| `/data/section_301_2024_review.csv` | MERGE | `/data/section_301_rates_temporal.csv` |
| `/data/section_232_hts_codes.csv` | KEEP | Already temporal-aware |
| `/data/mfn_base_rates_8digit.csv` | KEEP | Used for formula calculations |
| `/data/annex_ii_exemptions.csv` | KEEP | IEEPA exclusions |

---

## Implementation Plan

### Phase 1: Create Unified Temporal CSV

**Script:** `scripts/consolidate_section_301_csvs.py` (CREATE)

```python
"""
One-time script to merge:
  - /data/section_301_hts_codes.csv (legacy static, 10,422 rows)
  - /data/section_301_2024_review.csv (2024 temporal, 396 rows)

Into:
  - /data/section_301_rates_temporal.csv (unified, ~11,000 rows)
"""

import pandas as pd
from datetime import date, timedelta

def consolidate():
    # 1. Load legacy CSV (all rates from 2019)
    legacy = pd.read_csv('data/section_301_hts_codes.csv')
    legacy['effective_start'] = '2019-05-10'  # Legacy default date
    legacy['effective_end'] = None  # Still active (will be superseded)

    # 2. Load 2024 review CSV (has staged increases)
    review_2024 = pd.read_csv('data/section_301_2024_review.csv')

    # 3. For each HTS in 2024 review:
    #    - Find matching legacy row
    #    - Set legacy.effective_end = review.effective_start - 1 day
    for _, review_row in review_2024.iterrows():
        hts = review_row['hts_8digit']
        new_effective_start = review_row['effective_start']

        # Find and close legacy rate
        mask = (legacy['hts_8digit'] == hts) & (legacy['effective_end'].isna())
        if mask.any():
            legacy.loc[mask, 'effective_end'] = (
                pd.to_datetime(new_effective_start) - timedelta(days=1)
            ).strftime('%Y-%m-%d')

    # 4. Combine and output
    combined = pd.concat([legacy, review_2024], ignore_index=True)
    combined.to_csv('data/section_301_rates_temporal.csv', index=False)

    print(f"Created unified CSV: {len(combined)} rows")
```

**Output CSV Format:**
```csv
hts_8digit,chapter_99_code,duty_rate,effective_start,effective_end,list_name,source
38180000,9903.88.03,0.25,2019-05-10,2024-09-26,list_3,legacy
38180000,9903.91.02,0.50,2024-09-27,2025-12-31,list_3,ustr_2024_review
38180000,9903.91.02,1.00,2026-01-01,,list_3,ustr_2024_review
```

### Phase 2: Modify populate_tariff_tables.py

**Current:**
```python
# Lines ~2000-2500 of populate_tariff_tables.py
def populate_section_301_rates():
    # Hardcoded sample data OR reads from legacy CSV
    ...

# Called separately in railway.toml
# python scripts/import_2024_review_rates.py
```

**After:**
```python
def populate_section_301_rates():
    """Load Section 301 rates from unified temporal CSV."""
    df = pd.read_csv('data/section_301_rates_temporal.csv')

    for _, row in df.iterrows():
        Section301Rate.create(
            hts_8digit=row['hts_8digit'],
            chapter_99_code=row['chapter_99_code'],
            duty_rate=row['duty_rate'],
            effective_start=row['effective_start'],
            effective_end=row['effective_end'] if pd.notna(row['effective_end']) else None,
            list_name=row['list_name'],
            source_doc=row['source'],
        )

    db.session.commit()
    print(f"Imported {len(df)} Section 301 rates")
```

### Phase 3: Simplify railway.toml

**Current:**
```toml
[deploy]
startCommand = "python scripts/populate_tariff_tables.py --reset && python scripts/import_2024_review_rates.py && gunicorn..."
```

**After:**
```toml
[deploy]
startCommand = "python scripts/populate_tariff_tables.py --reset && gunicorn..."
```

No more chaining multiple import scripts!

### Phase 4: Delete Redundant Files

```bash
# Delete redundant directories
rm -rf docs/section301_csv_only_GPT/
rm -rf docs/section301_fix_pack/
rm -rf docs/mfn_base_rates_pack/

# Archive orphaned scripts
mkdir -p scripts/archived/
mv scripts/import_section_301_csv.py scripts/archived/
mv scripts/parse_fr_2024_review.py scripts/archived/
mv scripts/analyze_301_csvs.py scripts/archived/
mv scripts/populate_v6_tables.py scripts/archived/

# Delete merged source CSVs (after verifying consolidated CSV works)
rm data/section_301_hts_codes.csv
rm data/section_301_2024_review.csv

# Delete orphaned import script
rm scripts/import_2024_review_rates.py
```

### Phase 5: Update .gitignore

Add to prevent recreating redundant files:
```
# Archived scripts (not used in production)
scripts/archived/

# Legacy CSVs (replaced by temporal versions)
data/section_301_hts_codes.csv
data/section_301_2024_review.csv
```

---

## Verification Checklist

After refactoring, verify:

- [ ] `data/section_301_rates_temporal.csv` exists with ~11,000 rows
- [ ] `railway.toml` has single command (no chained scripts)
- [ ] `pipenv run python scripts/populate_tariff_tables.py --reset` works
- [ ] Query returns correct rates:
  ```python
  # Should return 25% (legacy rate before 2024 review)
  Section301Rate.get_rate_as_of("38180000", date(2023, 1, 1))

  # Should return 50% (2024 review rate)
  Section301Rate.get_rate_as_of("38180000", date(2025, 6, 1))

  # Should return 100% (2026 increase)
  Section301Rate.get_rate_as_of("38180000", date(2026, 6, 1))
  ```
- [ ] GitHub Actions workflow still works
- [ ] WriteGate can still insert new rates automatically

---

## Future Rate Changes (After Refactoring)

**Manual intervention: ZERO**

When USTR publishes new rate changes:
1. GitHub Actions (daily @ 6 AM UTC) polls Federal Register
2. Watcher detects new notice
3. WriteGate extracts and verifies using dual-LLM
4. Temporal table gets new row automatically
5. Old rate gets `effective_end` set

**No new CSV files. No new import scripts. Fully automated.**

---

## Summary Table

| Before | After |
|--------|-------|
| 2 CSV files for Section 301 | 1 unified temporal CSV |
| 7+ import scripts | 1 populate script |
| Chained deploy commands | Single deploy command |
| ~12 MB redundant files | Deleted |
| Manual CSV updates per year | Automatic via WriteGate |
| Easy to miss import steps | Single source of truth |

---

## Files Modified Summary

| File | Action |
|------|--------|
| `scripts/consolidate_section_301_csvs.py` | CREATE (one-time merge) |
| `scripts/populate_tariff_tables.py` | MODIFY (read unified CSV) |
| `railway.toml` | SIMPLIFY (single command) |
| `data/section_301_rates_temporal.csv` | CREATE (unified) |
| `data/section_301_hts_codes.csv` | DELETE (merged) |
| `data/section_301_2024_review.csv` | DELETE (merged) |
| `scripts/import_2024_review_rates.py` | DELETE (merged) |
| `scripts/import_section_301_csv.py` | ARCHIVE |
| `scripts/populate_v6_tables.py` | DELETE |
| `scripts/parse_fr_2024_review.py` | DELETE |
| `scripts/analyze_301_csvs.py` | DELETE |
| `docs/section301_csv_only_GPT/` | DELETE (7.2 MB) |
| `docs/section301_fix_pack/` | DELETE |
| `docs/mfn_base_rates_pack/` | DELETE |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Data loss during merge | Create backup before running consolidate script |
| Wrong rates after merge | Verify with test queries before deploying |
| Breaking GitHub Actions | Test workflow after changes |
| Railway deploy failure | Test locally with `--reset` flag first |

---

## Execution Order

1. **Backup** - Create backup of current data/ directory
2. **Create** - Run `consolidate_section_301_csvs.py` to create unified CSV
3. **Verify** - Test queries against unified CSV
4. **Modify** - Update `populate_tariff_tables.py` to use unified CSV
5. **Test** - Run `populate_tariff_tables.py --reset` locally
6. **Simplify** - Update `railway.toml` to single command
7. **Deploy** - Push changes, verify Railway deploy works
8. **Cleanup** - Delete redundant files and directories
9. **Document** - Update readme19 with new architecture
