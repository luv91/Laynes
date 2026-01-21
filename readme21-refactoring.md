# Tariff System Architecture - Complete Design

**Date:** January 18, 2026
**Version:** 3.0 (Post-Implementation)
**Status:** IMPLEMENTED

---

## Executive Summary

This document describes the complete architecture of the tariff stacking system after the v17.0 refactoring. The system now follows a **Database-as-Source-of-Truth** design where:
- All data is read from and written to the PostgreSQL database
- CSV files are used only for initial seeding (first deploy)
- Runtime data (pipeline discoveries, evidence) is preserved across deploys
- Evidence packets provide full audit trail for every committed rate

---

## Current System Status

### Database Tables (as of Jan 18, 2026)

| Table | Rows | Purpose |
|-------|------|---------|
| `section_301_rates` | 10,787 | Section 301 temporal rates |
| `section_232_rates` | 1,600 | Section 232 temporal rates |
| `section_232_materials` | 933 | Section 232 HTS scope |
| `ieepa_rates` | 45 | IEEPA temporal rates |
| `hts_base_rates` | 15,263 | MFN base rates |
| `ingest_jobs` | 20 | Document processing history |
| `official_documents` | 20 | Fetched documents |
| `evidence_packets` | 3 | Audit trail proofs |

### Ingest Job Status

| Source | Count | Status Breakdown |
|--------|-------|------------------|
| `email_csms` | 7 | 1 committed, 6 completed_no_changes |
| `federal_register` | 12 | 12 completed_no_changes |
| `usitc` | 1 | 1 completed_no_changes |

---

## Complete Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         TARIFF STACKING SYSTEM ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           LAYER 1: DISCOVERY                                 │   │
│  │                      (GitHub Actions - Daily at 6 AM UTC)                    │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐       │   │
│  │   │ Federal Register │   │   Email CSMS     │   │    USITC HTS     │       │   │
│  │   │     Watcher      │   │    Watcher       │   │     Watcher      │       │   │
│  │   │                  │   │                  │   │                  │       │   │
│  │   │ Polls: api.      │   │ Polls: Gmail     │   │ Polls: hts.      │       │   │
│  │   │ federalregister  │   │ inbox for CBP    │   │ usitc.gov        │       │   │
│  │   │ .gov/documents   │   │ notifications    │   │                  │       │   │
│  │   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘       │   │
│  │            │                      │                      │                 │   │
│  │            └──────────────────────┼──────────────────────┘                 │   │
│  │                                   │                                         │   │
│  │                                   ▼                                         │   │
│  │                    ┌──────────────────────────┐                             │   │
│  │                    │       IngestJob          │                             │   │
│  │                    │    (status: queued)      │                             │   │
│  │                    │                          │                             │   │
│  │                    │ Fields:                  │                             │   │
│  │                    │  - source                │                             │   │
│  │                    │  - external_id           │                             │   │
│  │                    │  - url                   │                             │   │
│  │                    │  - discovered_at         │                             │   │
│  │                    └────────────┬─────────────┘                             │   │
│  │                                 │                                           │   │
│  └─────────────────────────────────┼───────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           LAYER 2: PROCESSING                                │   │
│  │                      (DocumentPipeline - 6 stages)                           │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐      │   │
│  │   │  FETCH  │──▶│ RENDER  │──▶│  CHUNK  │──▶│ EXTRACT │──▶│VALIDATE │      │   │
│  │   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘      │   │
│  │        │             │             │             │             │            │   │
│  │        ▼             ▼             ▼             ▼             ▼            │   │
│  │   Download      Convert to    Split into    LLM extracts   Verify HTS      │   │
│  │   XML/PDF/      canonical     semantic      HTS codes,     in document,    │   │
│  │   HTML          text with     chunks for    rates, dates   rates match     │   │
│  │                 line numbers  RAG/LLM                                      │   │
│  │                                                                             │   │
│  │   Stores:       Stores:       Stores:       Creates:       Creates:        │   │
│  │   official_     canonical_    document_     Candidate      Validation      │   │
│  │   documents     text column   chunks        Change         Result          │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           LAYER 3: WRITE GATE                                │   │
│  │                      (Evidence-Gated Checkpoint)                             │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │   WriteGate.check(candidate, validation, document):                        │   │
│  │                                                                             │   │
│  │   ┌──────────────────────────────────────────────────────────────────────┐ │   │
│  │   │  CHECK 1: Tier A Source?                                             │ │   │
│  │   │    ✓ federal_register (federalregister.gov)                          │ │   │
│  │   │    ✓ email_csms (govdelivery.com from CBP)                           │ │   │
│  │   │    ✓ cbp_csms (csms.cbp.gov)                                         │ │   │
│  │   │    ✓ usitc (hts.usitc.gov)                                           │ │   │
│  │   │    ✗ Other sources → REJECTED                                        │ │   │
│  │   └──────────────────────────────────────────────────────────────────────┘ │   │
│  │   ┌──────────────────────────────────────────────────────────────────────┐ │   │
│  │   │  CHECK 2: Document Hash Stored?                                      │ │   │
│  │   │    ✓ SHA256 hash of raw document bytes                               │ │   │
│  │   │    ✗ Missing hash → REJECTED                                         │ │   │
│  │   └──────────────────────────────────────────────────────────────────────┘ │   │
│  │   ┌──────────────────────────────────────────────────────────────────────┐ │   │
│  │   │  CHECK 3: HTS Code Found in Document?                                │ │   │
│  │   │    ✓ HTS code appears in canonical text                              │ │   │
│  │   │    ✗ HTS not found → REJECTED                                        │ │   │
│  │   └──────────────────────────────────────────────────────────────────────┘ │   │
│  │   ┌──────────────────────────────────────────────────────────────────────┐ │   │
│  │   │  CHECK 4: Rate Found in Document?                                    │ │   │
│  │   │    ✓ Rate percentage appears near HTS code                           │ │   │
│  │   │    ✗ Rate not found → REJECTED                                       │ │   │
│  │   └──────────────────────────────────────────────────────────────────────┘ │   │
│  │                                                                             │   │
│  │   If ALL checks pass → Create EvidencePacket → APPROVED                    │   │
│  │   If ANY check fails → Store in review_queue → NEEDS_REVIEW                │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           LAYER 4: COMMIT                                    │   │
│  │                      (CommitEngine - Database Updates)                       │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │   CommitEngine.commit_candidate(candidate, evidence, doc, job):            │   │
│  │                                                                             │   │
│  │   1. Find existing active rate (effective_end IS NULL)                     │   │
│  │   2. Close existing rate:                                                  │   │
│  │        old.effective_end = new.effective_start                             │   │
│  │        old.superseded_by_id = new.id                                       │   │
│  │   3. Create new rate:                                                      │   │
│  │        new.supersedes_id = old.id                                          │   │
│  │        new.evidence_id = evidence.id                                       │   │
│  │   4. Write audit log entry                                                 │   │
│  │   5. Update IngestJob status = "committed"                                 │   │
│  │                                                                             │   │
│  │   Tables Updated:                                                          │   │
│  │   ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐   │   │
│  │   │ section_301_rates  │  │ section_232_rates  │  │    ieepa_rates     │   │   │
│  │   │                    │  │                    │  │                    │   │   │
│  │   │ - hts_8digit       │  │ - hts_8digit       │  │ - country_code     │   │   │
│  │   │ - chapter_99_code  │  │ - material_type    │  │ - program_type     │   │   │
│  │   │ - duty_rate        │  │ - article_type     │  │ - chapter_99_code  │   │   │
│  │   │ - effective_start  │  │ - duty_rate        │  │ - duty_rate        │   │   │
│  │   │ - effective_end    │  │ - effective_start  │  │ - effective_start  │   │   │
│  │   │ - supersedes_id    │  │ - effective_end    │  │ - effective_end    │   │   │
│  │   │ - evidence_id      │  │ - country_code     │  │ - variant          │   │   │
│  │   └────────────────────┘  └────────────────────┘  └────────────────────┘   │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           LAYER 5: QUERY                                     │   │
│  │                      (stacking_tools.py - Rate Lookups)                      │   │
│  ├─────────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                             │   │
│  │   calculate_stacked_rate(hts_code, country, value, as_of_date):            │   │
│  │                                                                             │   │
│  │   1. Section301Rate.get_rate_as_of(hts_8digit, as_of_date)                 │   │
│  │        → Returns rate where effective_start <= date < effective_end        │   │
│  │                                                                             │   │
│  │   2. Section232Rate.get_rate_as_of(hts_8digit, country, as_of_date)        │   │
│  │        → Checks country-specific exceptions (UK 25%)                       │   │
│  │        → Falls back to default rate                                        │   │
│  │                                                                             │   │
│  │   3. IeepaRate.get_rate_as_of(country, program_type, as_of_date)           │   │
│  │        → Fentanyl for CN/HK/MO                                             │   │
│  │        → Reciprocal with EU formula support                                │   │
│  │                                                                             │   │
│  │   4. HtsBaseRate.get_mfn_rate(hts_code)                                    │   │
│  │        → Column 1 General rate for base duty                               │   │
│  │                                                                             │   │
│  │   Returns: FilingResult with:                                              │   │
│  │     - filing_lines (each duty component)                                   │   │
│  │     - total_duty                                                           │   │
│  │     - chapter_99_codes                                                     │   │
│  │                                                                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Temporal Rate Design

Each rate table uses temporal versioning to track historical and current rates:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TEMPORAL RATE VERSIONING                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Example: Section 301 rate changes for HTS 8541.42.0010 (semiconductors)   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Rate v1                                                            │   │
│   │  hts_8digit: 85414200                                               │   │
│   │  duty_rate: 0.25 (25%)                                              │   │
│   │  effective_start: 2018-08-23                                        │   │
│   │  effective_end: 2024-09-27  ←── Closed when v2 created              │   │
│   │  superseded_by_id: v2.id                                            │   │
│   │  source_doc: FR-2018-08-16_2018-17709                               │   │
│   └───────────────────────────────────────┬─────────────────────────────┘   │
│                                           │                                 │
│                                           ▼                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Rate v2                                                            │   │
│   │  hts_8digit: 85414200                                               │   │
│   │  duty_rate: 0.50 (50%)                                              │   │
│   │  effective_start: 2024-09-27                                        │   │
│   │  effective_end: 2025-01-01  ←── Closed when v3 created              │   │
│   │  supersedes_id: v1.id                                               │   │
│   │  superseded_by_id: v3.id                                            │   │
│   │  source_doc: 2024-21217                                             │   │
│   └───────────────────────────────────────┬─────────────────────────────┘   │
│                                           │                                 │
│                                           ▼                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  Rate v3 (CURRENT)                                                  │   │
│   │  hts_8digit: 85414200                                               │   │
│   │  duty_rate: 1.00 (100%)                                             │   │
│   │  effective_start: 2025-01-01                                        │   │
│   │  effective_end: NULL  ←── NULL means currently active               │   │
│   │  supersedes_id: v2.id                                               │   │
│   │  superseded_by_id: NULL                                             │   │
│   │  source_doc: 2024-21217                                             │   │
│   │  evidence_id: [uuid]  ←── Links to proof                            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Query: get_rate_as_of('85414200', date(2024, 10, 15))                     │
│   Returns: Rate v2 (50%) because 2024-09-27 <= 2024-10-15 < 2025-01-01      │
│                                                                             │
│   Query: get_rate_as_of('85414200', date(2025, 1, 15))                      │
│   Returns: Rate v3 (100%) because 2025-01-01 <= 2025-01-15 < NULL           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Evidence Packet Design

Every committed rate change has a linked evidence packet:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EVIDENCE PACKET                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Example: CSMS #67400472 - Section 232 Semiconductors                       │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  evidence_packet                                                      │  │
│  │  ─────────────────                                                    │  │
│  │  id: cc99add5-3e85-467e-9187-9014edcf494f                             │  │
│  │  document_id: 898bf9be-1e32-4607-843f-26f751699e73                    │  │
│  │  document_hash: e177d7ad6b3aa7dbb9151634dca3a4bc7ea93eaf...           │  │
│  │                                                                       │  │
│  │  ── Location in Document ──                                           │  │
│  │  line_start: 3                                                        │  │
│  │  line_end: 23                                                         │  │
│  │                                                                       │  │
│  │  ── Extracted Quote ──                                                │  │
│  │  quote_text: "imposes 25 percent ad valorem duties on certain         │  │
│  │              imports of semiconductors and their derivative products" │  │
│  │                                                                       │  │
│  │  ── Context ──                                                        │  │
│  │  context_before: "CSMS # 67400472 - GUIDANCE: Section 232..."         │  │
│  │  context_after: "Semiconductor articles that are for use in..."       │  │
│  │                                                                       │  │
│  │  ── What It Proves ──                                                 │  │
│  │  proves_hts_code: 8471.50                                             │  │
│  │  proves_chapter_99: 9903.79.01                                        │  │
│  │  proves_rate: 0.25 (25%)                                              │  │
│  │  proves_effective_date: 2026-01-15                                    │  │
│  │                                                                       │  │
│  │  ── Verification ──                                                   │  │
│  │  verified_by: write_gate                                              │  │
│  │  verified_at: 2026-01-16 05:12:33                                     │  │
│  │  confidence_score: 1.0                                                │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Links to:                                                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐                        │
│  │ official_documents  │    │ section_232_rates   │                        │
│  │ (raw content)       │    │ (evidence_id FK)    │                        │
│  └─────────────────────┘    └─────────────────────┘                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEPLOYMENT ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   RAILWAY (Production)                                                      │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   railway.toml:                                                     │   │
│   │   startCommand = "python scripts/populate_tariff_tables.py          │   │
│   │                   --seed-if-empty && gunicorn wsgi:app..."          │   │
│   │                                                                     │   │
│   │   ┌───────────────────┐        ┌───────────────────┐               │   │
│   │   │  Flask App        │───────▶│  PostgreSQL       │               │   │
│   │   │  (gunicorn)       │        │  (Railway)        │               │   │
│   │   └───────────────────┘        └───────────────────┘               │   │
│   │                                        │                            │   │
│   │                                        │ Persists:                  │   │
│   │                                        │ - section_301_rates        │   │
│   │                                        │ - section_232_rates        │   │
│   │                                        │ - ieepa_rates              │   │
│   │                                        │ - ingest_jobs              │   │
│   │                                        │ - official_documents       │   │
│   │                                        │ - evidence_packets         │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   GITHUB ACTIONS (Daily Watcher)                                            │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   .github/workflows/regulatory-watcher.yml                          │   │
│   │   Schedule: 0 6 * * * (6 AM UTC daily)                              │   │
│   │                                                                     │   │
│   │   Step 1: Poll All Sources                                          │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │ pipenv run python scripts/run_watchers.py --all              │   │   │
│   │   │                                                              │   │   │
│   │   │ Polls:                                                       │   │   │
│   │   │   - Federal Register API                                     │   │   │
│   │   │   - Gmail inbox (CSMS emails)                                │   │   │
│   │   │   - USITC HTS updates                                        │   │   │
│   │   │                                                              │   │   │
│   │   │ Creates: IngestJob records (status: queued)                  │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                                                                     │   │
│   │   Step 2: Process Queue                                             │   │
│   │   ┌─────────────────────────────────────────────────────────────┐   │   │
│   │   │ pipenv run python scripts/process_ingest_queue.py            │   │   │
│   │   │                                                              │   │   │
│   │   │ For each queued job:                                         │   │   │
│   │   │   Fetch → Render → Chunk → Extract → Validate → Commit       │   │   │
│   │   │                                                              │   │   │
│   │   │ Updates: Database tables on Railway PostgreSQL               │   │   │
│   │   └─────────────────────────────────────────────────────────────┘   │   │
│   │                                                                     │   │
│   │   Connects to Railway DB via DATABASE_URL secret                    │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   STARTUP BEHAVIOR                                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │   populate_tariff_tables.py --seed-if-empty:                        │   │
│   │                                                                     │   │
│   │   IF table is empty:                                                │   │
│   │       Load from CSV (initial seed)                                  │   │
│   │       Mark provenance = "csv_seed"                                  │   │
│   │                                                                     │   │
│   │   IF table has data:                                                │   │
│   │       SKIP loading (preserve runtime data)                          │   │
│   │       Print "PRESERVING (seed-if-empty mode)"                       │   │
│   │                                                                     │   │
│   │   This ensures:                                                     │   │
│   │   ✓ First deploy loads initial data from CSV                        │   │
│   │   ✓ Subsequent deploys preserve pipeline discoveries                │   │
│   │   ✓ Evidence packets and audit logs are never lost                  │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Sources

### CSV Files (Seed Data)

| File | Rows | Purpose |
|------|------|---------|
| `data/section_301_rates_temporal.csv` | 10,784 | Section 301 rates with effective dates |
| `data/section_232_hts_codes.csv` | 933 | Section 232 HTS scope |
| `data/mfn_base_rates_8digit.csv` | 15,263 | MFN Column 1 base rates |
| `data/annex_ii_exemptions.csv` | 37 | IEEPA Reciprocal exemptions |

### Watchers (Runtime Discovery)

| Watcher | File | Source | Output |
|---------|------|--------|--------|
| Federal Register | `app/watchers/federal_register.py` | api.federalregister.gov | IngestJob (queued) |
| Email CSMS | `app/watchers/email_csms.py` | Gmail inbox | IngestJob (queued) |
| CBP CSMS | `app/watchers/cbp_csms.py` | csms.cbp.gov | IngestJob (queued) |
| USITC | `app/watchers/usitc.py` | hts.usitc.gov | IngestJob (queued) |

---

## Implementation Status

### Completed (v17.0)

| Task | File | Status |
|------|------|--------|
| Remove `--reset` from deploy | `railway.toml` | ✅ DONE |
| Add `--seed-if-empty` flag | `scripts/populate_tariff_tables.py` | ✅ DONE |
| Preserve Section 301 data | `populate_section_301_temporal()` | ✅ DONE |
| Preserve Section 232 data | `populate_section_232_temporal()` | ✅ DONE |
| Preserve IEEPA data | `populate_ieepa_temporal()` | ✅ DONE |
| Add 8426.19.00 to Section 301 | `data/section_301_rates_temporal.csv` | ✅ DONE |
| Add 7606.12.30 to Section 232 | `data/section_232_hts_codes.csv` | ✅ DONE |
| Add 7606.12.60 to Section 232 | `data/section_232_hts_codes.csv` | ✅ DONE |
| Create backfill runner | `scripts/backfill_historical_docs.py` | ✅ DONE |
| Create reconciliation job | `scripts/reconcile_coverage.py` | ✅ DONE |

### Pending (Future)

| Task | File | Status |
|------|------|--------|
| Add DB → CSV export | `scripts/export_rates_to_csv.py` | TODO |
| Auto-commit CSV to git | `.github/workflows/` | TODO |
| Add CBP website watcher | `app/watchers/cbp_csms.py` | Partial |

---

## Scripts Reference

### Daily Operations (GitHub Actions)

```bash
# Poll all regulatory sources
pipenv run python scripts/run_watchers.py --all --since 7

# Process queued documents
pipenv run python scripts/process_ingest_queue.py --max-jobs 50
```

### Manual Operations

```bash
# Backfill historical documents
pipenv run python scripts/backfill_historical_docs.py --since 2024-01-01 --dry-run
pipenv run python scripts/backfill_historical_docs.py --since 2024-01-01 --process

# Check coverage gaps
pipenv run python scripts/reconcile_coverage.py
pipenv run python scripts/reconcile_coverage.py --check-hts 8426.19.00 7606.12.30

# Export database to CSV (backup)
pipenv run python scripts/reconcile_coverage.py --export-csv

# Repopulate (seed only if empty)
pipenv run python scripts/populate_tariff_tables.py --seed-if-empty

# Full reset (DANGER: loses runtime data)
pipenv run python scripts/populate_tariff_tables.py --reset
```

---

## Environment Variables

### Required for Pipeline

```env
DATABASE_URL=postgresql://user:pass@host:5432/db
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=...
```

### Required for Email CSMS Watcher

```env
GMAIL_CSMS_EMAIL=your-email@gmail.com
GMAIL_CSMS_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

---

## Summary

The v17.0 refactoring established the Database-as-Source-of-Truth architecture:

1. **Database is SSOT**: All queries read from PostgreSQL
2. **CSV is seed only**: Loaded once on first deploy
3. **Runtime data preserved**: Pipeline discoveries survive deploys
4. **Evidence-gated commits**: Every rate change has proof
5. **Temporal versioning**: Historical rates are preserved
6. **Automated discovery**: Daily watchers poll official sources

The system now correctly handles the full lifecycle:
- Discovery (watchers) → Processing (pipeline) → Validation (write gate) → Storage (temporal tables) → Query (stacking tools)

---

**End of Document**
