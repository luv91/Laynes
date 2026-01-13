# Regulatory Update Pipeline - Phase 3 Complete

**Date:** January 10, 2026
**Version:** 5.0 (Phase 3 Complete)
**Status:** PRODUCTION READY - Full Operational Hardening

---

## Phase Summary

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1** | Stage 1-2: Infrastructure + Automation | ✅ Complete |
| **Phase 2** | Stage 3: PRC Compliance + Temporal Fix | ✅ Complete |
| **Phase 3** | Operational Hardening | ✅ Complete |

---

## Phase 3: What Was Completed

Phase 3 addressed all remaining operational hardening requirements for production deployment.

### Completion Summary

| Item | Status | Details |
|------|--------|---------|
| **PRC-0: Alembic Migrations** | ✅ Complete | Flask-Migrate initialized, initial migration created |
| **CBP CSMS Watcher** | ✅ Complete | Date filtering, wired to run_watchers.py |
| **USITC Watcher** | ✅ Complete | Wired to run_watchers.py |
| **LLM RAG Extraction** | ✅ Complete | Full OpenAI integration with gpt-4o-mini |
| **S3 Manifest Upload** | ✅ Complete | boto3 integration, configurable via env |
| **Monitoring & Alerts** | ✅ Complete | /admin/health, /admin/metrics endpoints |

---

## Detailed Changes

### 1. Alembic Migrations (PRC-0)

**Files Changed:**
- `app/web/__init__.py` - Added Flask-Migrate integration
- `migrations/` - New directory with Alembic configuration

**Implementation:**
```python
from flask_migrate import Migrate

migrate = Migrate()

def register_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
```

**Usage:**
```bash
# Initialize (already done)
flask db init

# Create migration
flask db migrate -m "Description"

# Apply migrations
flask db upgrade

# Check current version
flask db current
```

**Current Migration:** `5f4dff226bfa` (Initial regulatory pipeline tables)

---

### 2. CBP CSMS Watcher

**File:** `app/watchers/cbp_csms.py`

**Changes:**
- Added `_extract_date()` method for date filtering
- Filters bulletins by `since_date` parameter
- Parses MM/DD/YYYY and YYYY-MM-DD date formats from page content

```python
def poll(self, since_date: Optional[date] = None) -> List[DiscoveredDocument]:
    # ... existing discovery logic ...

    # Try to extract date from surrounding context
    pub_date = self._extract_date(link)

    # Filter by since_date if we found a date
    if pub_date and since_date and pub_date < since_date:
        continue
```

**File:** `scripts/run_watchers.py`

**Changes:**
- Wired `poll_cbp_csms()` to call `CBPCSMSWatcher`
- Added `poll_usitc()` for USITC integration
- Added `usitc` to source choices

```python
def poll_cbp_csms(since_date: date):
    from app.watchers.cbp_csms import CBPCSMSWatcher
    watcher = CBPCSMSWatcher()
    return watcher.poll(since_date)
```

---

### 3. USITC Watcher

**File:** `scripts/run_watchers.py`

**Changes:**
- Added USITC to `--source` options
- Wired `poll_usitc()` to call `USITCWatcher`

```python
@click.option('--source', '-s', default='federal_register',
              type=click.Choice(['federal_register', 'cbp_csms', 'usitc', 'all']),
              help='Source to poll')
```

---

### 4. LLM RAG Extraction

**File:** `app/workers/extraction_worker.py`

**Changes:**
- Added `TARIFF_EXTRACTION_PROMPT` for structured tariff extraction
- Implemented `_extract_from_rag()` with full OpenAI integration
- Uses `gpt-4o-mini` for fast, cost-effective extraction
- Graceful degradation when `OPENAI_API_KEY` not set

```python
TARIFF_EXTRACTION_PROMPT = """You are an expert at extracting tariff rate changes...

For each tariff change found, provide a JSON object with these fields:
- hts_code: The 8 or 10 digit HTS code
- chapter_99_code: The Chapter 99 heading if mentioned
- rate: The duty rate as a decimal
- effective_date: The effective date in YYYY-MM-DD format
- description: Brief product description
- program: The tariff program
- evidence_quote: The exact text that supports this change
..."""

def _extract_from_rag(self, doc: OfficialDocument) -> List[CandidateChange]:
    if not os.environ.get("OPENAI_API_KEY"):
        return []  # Graceful degradation

    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

    for chunk in chunks:
        prompt = TARIFF_EXTRACTION_PROMPT.format(text=chunk.text[:8000])
        response = llm.invoke(prompt)
        # Parse JSON response into CandidateChange objects
```

---

### 5. S3 Manifest Upload

**File:** `scripts/run_watchers.py`

**Changes:**
- Added `upload_manifest_to_s3()` function
- Uploads to S3 when `MANIFEST_S3_BUCKET` env var is set
- Falls back to local storage when S3 not configured

```python
def upload_manifest_to_s3(local_path: Path, filename: str) -> str:
    bucket = os.environ.get("MANIFEST_S3_BUCKET")
    if not bucket:
        return None

    import boto3
    s3 = boto3.client('s3')
    s3_key = f"regulatory_runs/{year}/{month}/{filename}"
    s3.upload_file(str(local_path), bucket, s3_key)
    return f"s3://{bucket}/{s3_key}"
```

**Configuration:**
```bash
# Optional - set to enable S3 upload
export MANIFEST_S3_BUCKET=my-regulatory-bucket

# AWS credentials (standard boto3 config)
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
```

---

### 6. Monitoring & Health Check Endpoints

**File:** `app/web/views/admin_views.py`

**New Endpoints:**

#### `GET /admin/health`
Health check for load balancers and monitoring systems.

```json
{
  "status": "healthy",
  "timestamp": "2026-01-10T12:00:00",
  "checks": {
    "database": "ok",
    "queue_depth": 5,
    "stuck_jobs": 0,
    "failed_runs_24h": 0,
    "last_run_hours_ago": 2.5
  },
  "issues": [],
  "warnings": []
}
```

**Status codes:**
- `200` - Healthy or degraded (with warnings)
- `503` - Unhealthy (critical issues)

**Health checks performed:**
- Database connectivity
- Queue depth (warning if > 100)
- Stuck jobs (processing > 1 hour)
- Failed runs in last 24h
- Data freshness (warning if no run in 24h)

#### `GET /admin/metrics`
Prometheus-compatible metrics endpoint.

```
# HELP pipeline_queue_depth Number of jobs in queue
# TYPE pipeline_queue_depth gauge
pipeline_queue_depth{status="queued"} 5
pipeline_queue_depth{status="processing"} 1

# HELP pipeline_pending_review Number of candidates pending review
# TYPE pipeline_pending_review gauge
pipeline_pending_review 3

# HELP pipeline_jobs_completed_total Jobs completed today
# TYPE pipeline_jobs_completed_total counter
pipeline_jobs_completed_total 15

# HELP pipeline_last_run_seconds_ago Seconds since last successful run
# TYPE pipeline_last_run_seconds_ago gauge
pipeline_last_run_seconds_ago 9000
```

---

## Test Results

```bash
$ pipenv run pytest tests/test_temporal_queries.py tests/test_integration.py -v

======================== 24 passed in 2.72s ========================
```

All 24 tests pass:
- 10 temporal query tests
- 14 integration tests

---

## Environment Variables (Complete List)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `SECRET_KEY` | Yes | Flask secret key |
| `OPENAI_API_KEY` | No | Enables LLM RAG extraction |
| `MANIFEST_S3_BUCKET` | No | S3 bucket for manifest uploads |
| `AWS_ACCESS_KEY_ID` | No* | Required if S3 enabled |
| `AWS_SECRET_ACCESS_KEY` | No* | Required if S3 enabled |
| `AWS_REGION` | No | AWS region (default: us-east-1) |

---

## API Endpoints Summary

### Admin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/health` | GET | Health check for monitoring |
| `/admin/metrics` | GET | Prometheus metrics |
| `/admin/freshness` | GET | Data freshness per source |
| `/admin/pipeline/status` | GET | Pipeline queue status |
| `/admin/needs-review` | GET | List pending candidates |
| `/admin/needs-review/<id>` | GET | Candidate detail |
| `/admin/needs-review/<id>/approve` | POST | Approve candidate |
| `/admin/needs-review/<id>/reject` | POST | Reject candidate |
| `/admin/runs` | GET | List regulatory runs |
| `/admin/runs/<id>` | GET | Run detail |
| `/admin/audit-log` | GET | Audit log entries |
| `/admin/pipeline/trigger-watcher` | POST | Manual watcher trigger |
| `/admin/pipeline/process-queue` | POST | Manual queue processing |

---

## File Changes Summary

```
lanes/
├── app/
│   ├── web/
│   │   ├── __init__.py              # ✅ Added Flask-Migrate
│   │   └── views/
│   │       └── admin_views.py       # ✅ Added /health, /metrics
│   │
│   └── workers/
│       └── extraction_worker.py     # ✅ Full LLM RAG extraction
│
├── migrations/
│   ├── alembic.ini                  # ✅ NEW
│   ├── env.py                       # ✅ NEW
│   ├── README                       # ✅ NEW
│   ├── script.py.mako               # ✅ NEW
│   └── versions/
│       └── 5f4dff226bfa_initial.py  # ✅ NEW
│
├── scripts/
│   └── run_watchers.py              # ✅ CBP/USITC wired, S3 upload
│
└── readme18-phase3-complete.md      # This document
```

---

## Production Deployment Checklist

### Infrastructure

- [ ] Set `DATABASE_URL` to PostgreSQL (not SQLite)
- [ ] Run `flask db upgrade` on first deploy
- [ ] Configure Railway/Heroku scheduler for `run_watchers.py`
- [ ] Configure worker process for `process_ingest_queue.py`

### Optional Integrations

- [ ] Set `OPENAI_API_KEY` for LLM extraction
- [ ] Set `MANIFEST_S3_BUCKET` for S3 manifest storage
- [ ] Configure AWS credentials if using S3

### Monitoring

- [ ] Configure load balancer health check to `/admin/health`
- [ ] Configure Prometheus scraping for `/admin/metrics`
- [ ] Set up alerts for:
  - `pipeline_queue_depth > 100`
  - `pipeline_last_run_seconds_ago > 86400` (24h)
  - `pipeline_pending_review > 50`

---

## Architecture After Phase 3

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  PHASE 3 COMPLETE: Full Production Hardening                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ✅ Phase 1: Infrastructure + Automation                                     ║
║     ├── Watchers (FR, CBP, USITC)                                           ║
║     ├── Document Pipeline (Fetch → Render → Chunk → Extract)                ║
║     ├── CommitEngine with supersession                                       ║
║     └── RegulatoryRun tracking                                              ║
║                                                                              ║
║  ✅ Phase 2: PRC Compliance                                                  ║
║     ├── PRC-3: rate_schedule → multi-row commits                            ║
║     ├── PRC-4: /admin/needs-review endpoints                                ║
║     ├── PRC-5: /admin/freshness from regulatory_runs                        ║
║     ├── PRC-6: Structured JSON logging                                      ║
║     └── PRC-7: 10 canary tests for temporal queries                         ║
║                                                                              ║
║  ✅ Phase 3: Operational Hardening (NEW)                                     ║
║     ├── PRC-0: Alembic migrations                                           ║
║     ├── CBP CSMS watcher with date filtering                                ║
║     ├── USITC watcher integration                                           ║
║     ├── LLM RAG extraction (gpt-4o-mini)                                    ║
║     ├── S3 manifest upload                                                  ║
║     └── /admin/health + /admin/metrics endpoints                            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## All PRC Criteria - Final Status

| PRC | Requirement | Status | Evidence |
|-----|-------------|--------|----------|
| **PRC-0** | Alembic migrations | ✅ | `flask db upgrade` works |
| **PRC-1** | Scheduler/worker runs | ✅ | Scripts + Procfile |
| **PRC-2** | Commits have evidence | ✅ | evidence_id linked |
| **PRC-3** | Temporal as_of_date queries | ✅ | 10 canary tests pass |
| **PRC-4** | needs_review stored | ✅ | Admin endpoints |
| **PRC-5** | Freshness from runs | ✅ | /admin/freshness |
| **PRC-6** | Structured logging | ✅ | JSON with job_id, doc_id |
| **PRC-7** | Canary tests | ✅ | 24/24 tests pass |

---

## Usage Examples

### Poll All Sources

```bash
python scripts/run_watchers.py --all --since 2026-01-01 --export-manifest
```

### Check Health

```bash
curl http://localhost:5000/admin/health | jq
```

### Monitor Metrics

```bash
curl http://localhost:5000/admin/metrics
```

### Trigger Manual Watcher

```bash
curl -X POST http://localhost:5000/admin/pipeline/trigger-watcher \
  -H "Content-Type: application/json" \
  -d '{"source": "federal_register", "since_date": "2026-01-01"}'
```

---

*Document created: January 10, 2026*
*Phase 1 completed: January 10, 2026*
*Phase 2 completed: January 10, 2026*
*Phase 3 completed: January 10, 2026*
