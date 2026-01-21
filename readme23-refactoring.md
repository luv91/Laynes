# Complete Database Architecture

**Date:** January 20, 2026
**Status:** IMPLEMENTED (Object Storage Complete)

---

## CRITICAL CLARIFICATION: NO FALLBACK CHAIN

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    THERE IS NO FALLBACK BETWEEN DATABASES                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  The app uses ONE database at a time based on DATABASE_URL environment var:    │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                                                                          │  │
│  │   LOCAL DEVELOPMENT                    PRODUCTION (Railway)              │  │
│  │   ─────────────────                    ───────────────────               │  │
│  │   DATABASE_URL not set                 DATABASE_URL=postgresql://...     │  │
│  │           │                                     │                        │  │
│  │           ▼                                     ▼                        │  │
│  │   ┌─────────────────┐                  ┌─────────────────┐              │  │
│  │   │    SQLite       │                  │   PostgreSQL    │              │  │
│  │   │ instance/       │      OR          │   (Railway)     │              │  │
│  │   │ sqlite.db       │                  │                 │              │  │
│  │   └─────────────────┘                  └─────────────────┘              │  │
│  │                                                                          │  │
│  │   These are MUTUALLY EXCLUSIVE - never both at once!                    │  │
│  │                                                                          │  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  Q: Does SQLite "fall back" to PostgreSQL or vice versa?                       │
│  A: NO. You pick ONE based on your environment.                                │
│                                                                                  │
│  Q: Does the app check PostgreSQL, then fall back to SQLite, then CSV?         │
│  A: NO. There is no fallback chain. You use ONE database.                      │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### What Gets Updated Where?

| Data Type | Updated By | Storage |
|-----------|-----------|---------|
| **Tariff rates** (section_301, section_232, ieepa) | Extraction pipeline | Database (PostgreSQL OR SQLite) |
| **Document metadata** | FetchWorker | Database |
| **Ingest jobs** | Pipeline workers | Database |
| **Evidence packets** | CommitWorker | Database |
| **CSV files** | **NEVER updated by app** | Read-only seed data |
| **Raw document blobs** | FetchWorker | Local filesystem only |

### CSV Files Are READ-ONLY Seed Data

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      CSV FILES: ONE-WAY IMPORT ONLY                             │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  On app startup (populate_tariff_tables.py):                                    │
│                                                                                  │
│     data/section_301_rates_temporal.csv ──────► Database (section_301_rates)   │
│     data/section_232_hts_codes.csv ───────────► Database (section_232_rates)   │
│     data/ieepa_rates_temporal.csv ────────────► Database (ieepa_rates)         │
│     data/mfn_base_rates_8digit.csv ───────────► Database (mfn_base_rates)      │
│                                                                                  │
│  Direction: CSV → Database (ONE WAY)                                           │
│  The CSVs are NEVER written back to by the application.                        │
│  They are static files maintained manually when regulations change.            │
│                                                                                  │
│  New rates from Federal Register documents:                                     │
│     Document extraction ──────► Database (directly, NOT to CSV)                │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### The Only "Fallback" Is For Document Content

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│            DOCUMENT CONTENT FALLBACK (storage_uri vs raw_bytes)                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  doc.content property:                                                          │
│                                                                                  │
│     if doc.storage_uri:           ← NEW documents (post-migration)             │
│         return read_from_local_filesystem(storage_uri)                          │
│     else:                                                                        │
│         return doc.raw_bytes      ← LEGACY documents (pre-migration)           │
│                                                                                  │
│  This is the ONLY fallback in the system.                                       │
│  It's for backwards compatibility with old documents that have raw_bytes        │
│  stored in the database instead of on the filesystem.                           │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## OVERVIEW: WHERE DOES DATA LIVE?

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           DATA STORAGE LOCATIONS                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────────────┐   ┌────────────────────────┐   ┌────────────────┐ │
│  │  LOCAL FILESYSTEM       │   │  PostgreSQL (Railway)   │   │  CSV FILES     │ │
│  │  (storage/documents/)   │   │  (Online Database)      │   │  (data/*.csv)  │ │
│  │                         │   │                         │   │                │ │
│  │  • Raw documents        │   │  • Metadata             │   │  • Seed data   │ │
│  │  • XML/PDF/HTML/DOCX    │   │  • Extracted rates      │   │  • Initial     │ │
│  │  • Referenced via       │   │  • Evidence packets     │   │    HTS codes   │ │
│  │    storage_uri          │   │  • Audit logs           │   │  • Base rates  │ │
│  │                         │   │  • Ingest jobs          │   │  • Annex II    │ │
│  │  NEVER online!          │   │  • Search cache         │   │    exclusions  │ │
│  └─────────────────────────┘   └────────────────────────┘   └────────────────┘ │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Key constraint:** Blobs (raw document bytes) NEVER go over the network to PostgreSQL.

---

## PART 1: DOCUMENT DISCOVERY (How Documents Arrive)

Documents enter the system via two mechanisms:

### 1A. Email Notification (CBP CSMS)
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  EMAIL NOTIFICATION FLOW (CBP CSMS Bulletins)                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  1. CBP posts new CSMS bulletin on csms.cbp.gov                                │
│     │                                                                            │
│     ▼                                                                            │
│  2. GovDelivery sends email notification                                        │
│     "Subject: [CSMS #65936570] Section 232 Duty Update..."                     │
│     │                                                                            │
│     ▼                                                                            │
│  3. Watcher (GitHub Action or local) checks GovDelivery RSS/email API           │
│     Runs daily via: .github/workflows/regulatory-watcher.yml                    │
│     │                                                                            │
│     ▼                                                                            │
│  4. Parses bulletin URL from notification                                        │
│     Creates IngestJob with:                                                      │
│       - source: "cbp_csms"                                                       │
│       - external_id: "65936570"                                                 │
│       - url: "https://csms.cbp.gov/..."                                         │
│     │                                                                            │
│     ▼                                                                            │
│  5. IngestJob enters queue (status: "queued")                                   │
│     Stored in: PostgreSQL (ingest_jobs table)                                   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 1B. API Polling (Federal Register)
```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  API POLLING FLOW (Federal Register Documents)                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  1. Watcher queries Federal Register API:                                       │
│     GET https://www.federalregister.gov/api/v1/documents.json?                 │
│         conditions[term]="section 301" OR "section 232"                        │
│     │                                                                            │
│     ▼                                                                            │
│  2. API returns list of recent notices                                          │
│     [{"document_number": "2025-12052", "title": "...", ...}, ...]              │
│     │                                                                            │
│     ▼                                                                            │
│  3. For each new/updated document:                                              │
│     Creates IngestJob with:                                                      │
│       - source: "federal_register"                                               │
│       - external_id: "2025-12052"                                               │
│       - url: API endpoint (not HTML - avoids CAPTCHA!)                          │
│     │                                                                            │
│     ▼                                                                            │
│  4. IngestJob enters queue (status: "queued")                                   │
│     Stored in: PostgreSQL (ingest_jobs table)                                   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## PART 2: DOCUMENT PROCESSING PIPELINE

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      DOCUMENT PROCESSING FLOW                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  STAGE 1: FETCH (FetchWorker)                                                   │
│  ────────────────────────────────────────────────────────────────────────────── │
│  Input:  IngestJob with URL                                                     │
│  Output: Raw document bytes                                                      │
│                                                                                  │
│     Federal Register API / CBP URL                                              │
│             │                                                                    │
│             ▼                                                                    │
│     response.content (raw bytes: XML/PDF/HTML)                                  │
│             │                                                                    │
│             ├─────────────────────────────────────┐                             │
│             │                                     │                             │
│             ▼                                     ▼                             │
│     ┌─────────────────────┐           ┌──────────────────────┐                 │
│     │  LOCAL FILESYSTEM   │           │  PostgreSQL          │                 │
│     │  storage/documents/ │           │                      │                 │
│     │                     │           │  official_documents: │                 │
│     │  federal_register/  │           │  - id, source        │                 │
│     │    2024-12345/      │ ◄─────────┤  - storage_uri       │                 │
│     │      abc123.xml     │           │  - content_hash      │                 │
│     └─────────────────────┘           │  - content_type      │                 │
│                                       └──────────────────────┘                 │
│                                                                                  │
│  STAGE 2: RENDER (RenderWorker)                                                 │
│  ────────────────────────────────────────────────────────────────────────────── │
│  Input:  Raw bytes from LOCAL FILESYSTEM (via storage_uri)                      │
│  Output: Line-numbered canonical text                                           │
│                                                                                  │
│     doc.content → reads local file → parses XML/PDF/HTML                        │
│             │                                                                    │
│             ▼                                                                    │
│     canonical_text (stored in PostgreSQL):                                      │
│     L0001: DEPARTMENT OF THE TREASURY                                           │
│     L0002: Customs and Border Protection                                        │
│     L0003: Section 232 Duties on Steel...                                       │
│                                                                                  │
│  STAGE 3: CHUNK (ChunkWorker)                                                   │
│  ────────────────────────────────────────────────────────────────────────────── │
│  Input:  canonical_text from PostgreSQL                                         │
│  Output: Document chunks for RAG                                                │
│                                                                                  │
│     Splits canonical_text into semantic chunks                                  │
│     Stores in: PostgreSQL (document_chunks table)                               │
│                                                                                  │
│  STAGE 4: EXTRACT (ExtractionWorker)                                            │
│  ────────────────────────────────────────────────────────────────────────────── │
│  Input:  LOCAL FILESYSTEM (XML tables), PostgreSQL (chunks for LLM RAG)        │
│  Output: CandidateChange objects                                                │
│                                                                                  │
│     For XML: ET.fromstring(doc.content) → parse GPOTABLE elements              │
│     For LLM: Use document chunks for context                                   │
│             │                                                                    │
│             ▼                                                                    │
│     candidate_changes (in PostgreSQL):                                          │
│     - hts_code: "8544.42.90"                                                    │
│     - chapter_99_code: "9903.91.07"                                             │
│     - rate: 0.50                                                                │
│     - evidence_quote: "8544.42.90 ... 50%"                                      │
│                                                                                  │
│  STAGE 5: VALIDATE (WriteGate + ValidatorLLM)                                   │
│  ────────────────────────────────────────────────────────────────────────────── │
│  Input:  CandidateChange from PostgreSQL                                        │
│  Output: Validated or rejected change                                           │
│                                                                                  │
│     WriteGate checks:                                                           │
│     1. Evidence quote exists verbatim in canonical_text                        │
│     2. HTS code appears in the quote                                            │
│     3. Rate is parseable and in valid range                                     │
│             │                                                                    │
│             ▼                                                                    │
│     If passed → status: "validated"                                             │
│     If failed → status: "needs_review" → queue for human review                │
│                                                                                  │
│  STAGE 6: COMMIT                                                                 │
│  ────────────────────────────────────────────────────────────────────────────── │
│  Input:  Validated CandidateChange                                              │
│  Output: Committed tariff rate                                                  │
│                                                                                  │
│     Writes to PostgreSQL:                                                       │
│     - section_301_rates / section_232_rates / ieepa_rates                      │
│     - evidence_packets (audit trail)                                            │
│     - tariff_audit_log                                                          │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## PART 3: COMPLETE DATABASE SCHEMA

### PostgreSQL Tables (Online - Railway)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         POSTGRESQL TABLES (~38 tables)                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  DOCUMENT PIPELINE (Ingestion)                                                  │
│  ─────────────────────────────                                                  │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ official_documents                                                       │   │
│  │ ─────────────────                                                        │   │
│  │ id              VARCHAR(36)   PK                                         │   │
│  │ source          VARCHAR(50)   NOT NULL  -- federal_register, cbp_csms   │   │
│  │ external_id     VARCHAR(100)  NOT NULL  -- document_number, bulletin_id │   │
│  │ storage_uri     VARCHAR(500)  -- "local://federal_register/2024-12345/..."│  │
│  │ content_hash    VARCHAR(64)   NOT NULL  -- SHA256                        │   │
│  │ content_type    VARCHAR(50)   -- application/xml, text/html, etc.       │   │
│  │ content_size    INTEGER       -- bytes                                   │   │
│  │ canonical_text  TEXT          -- line-numbered text for evidence search │   │
│  │ title           VARCHAR(500)                                             │   │
│  │ publication_date DATE                                                    │   │
│  │ effective_date  DATE                                                     │   │
│  │ status          VARCHAR(50)   -- fetched → rendered → chunked → ...     │   │
│  │ raw_bytes       BYTEA         -- LEGACY (null for new docs)             │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ document_chunks                                                          │   │
│  │ ───────────────                                                          │   │
│  │ id              VARCHAR(36)   PK                                         │   │
│  │ document_id     VARCHAR(36)   FK → official_documents                   │   │
│  │ chunk_index     INTEGER       NOT NULL                                   │   │
│  │ text            TEXT          NOT NULL  -- chunk content                 │   │
│  │ line_start      INTEGER       -- L0001 start                            │   │
│  │ line_end        INTEGER       -- L0050 end                              │   │
│  │ chunk_type      VARCHAR(50)   -- narrative, table, heading              │   │
│  │ embedding_id    VARCHAR(100)  -- Pinecone/vector DB reference           │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ ingest_jobs                                                              │   │
│  │ ───────────                                                              │   │
│  │ id              VARCHAR(36)   PK                                         │   │
│  │ source          VARCHAR(50)   NOT NULL                                   │   │
│  │ external_id     VARCHAR(100)  NOT NULL                                   │   │
│  │ url             VARCHAR(500)                                             │   │
│  │ content_hash    VARCHAR(64)   -- for dedup/version detection            │   │
│  │ status          VARCHAR(50)   -- queued → fetching → ... → committed   │   │
│  │ document_id     VARCHAR(36)   FK → official_documents                   │   │
│  │ error_message   TEXT                                                     │   │
│  │ changes_extracted INTEGER                                                │   │
│  │ changes_committed INTEGER                                                │   │
│  │ UNIQUE(source, external_id, content_hash)                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  TARIFF RATE TABLES (Extracted Data)                                           │
│  ────────────────────────────────────                                          │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ section_301_rates (Temporal - time-series tracking)                      │   │
│  │ ─────────────────                                                        │   │
│  │ id              INTEGER       PK                                         │   │
│  │ hts_8digit      VARCHAR(10)   NOT NULL  -- "85444290"                   │   │
│  │ chapter_99_code VARCHAR(16)   NOT NULL  -- "9903.91.07"                 │   │
│  │ duty_rate       NUMERIC(5,4)  NOT NULL  -- 0.50 = 50%                   │   │
│  │ effective_start DATE          NOT NULL  -- when rate begins             │   │
│  │ effective_end   DATE          -- NULL = currently active                │   │
│  │ list_name       VARCHAR(64)   -- "list_4a", "strategic_medical"         │   │
│  │ role            VARCHAR(16)   -- "impose" or "exclude"                  │   │
│  │ source_doc      VARCHAR(256)  -- "2024-21217" (FR document #)           │   │
│  │ supersedes_id   INTEGER       FK → self  -- previous rate               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ section_232_rates (Steel, Aluminum, Copper)                              │   │
│  │ ─────────────────                                                        │   │
│  │ id              INTEGER       PK                                         │   │
│  │ hts_8digit      VARCHAR(10)   NOT NULL                                   │   │
│  │ material_type   VARCHAR(20)   NOT NULL  -- steel, aluminum, copper      │   │
│  │ chapter_99_claim VARCHAR(16)  NOT NULL  -- "9903.80.01"                 │   │
│  │ chapter_99_disclaim VARCHAR(16)                                          │   │
│  │ duty_rate       NUMERIC(5,4)  NOT NULL                                   │   │
│  │ country_code    VARCHAR(3)    -- NULL=all, 'GBR'=UK exception           │   │
│  │ article_type    VARCHAR(20)   -- 'primary', 'derivative', 'content'     │   │
│  │ effective_start DATE          NOT NULL                                   │   │
│  │ effective_end   DATE                                                     │   │
│  │ source_doc      VARCHAR(256)                                             │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ ieepa_rates (Fentanyl + Reciprocal)                                      │   │
│  │ ───────────                                                              │   │
│  │ id              INTEGER       PK                                         │   │
│  │ program_type    VARCHAR(20)   NOT NULL  -- 'fentanyl', 'reciprocal'     │   │
│  │ country_code    VARCHAR(3)    -- 'CHN', 'HKG', etc.                     │   │
│  │ chapter_99_code VARCHAR(16)   NOT NULL                                   │   │
│  │ duty_rate       NUMERIC(5,4)  NOT NULL                                   │   │
│  │ variant         VARCHAR(32)   -- 'taxable', 'annex_ii_exempt'           │   │
│  │ rate_type       VARCHAR(20)   -- 'fixed', 'formula'                     │   │
│  │ rate_formula    VARCHAR(64)   -- '15pct_minus_mfn' for EU ceiling       │   │
│  │ effective_start DATE          NOT NULL                                   │   │
│  │ effective_end   DATE                                                     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  AUDIT & EVIDENCE TABLES                                                        │
│  ───────────────────────                                                        │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ evidence_packets                                                         │   │
│  │ ────────────────                                                         │   │
│  │ id              VARCHAR(36)   PK                                         │   │
│  │ document_id     VARCHAR(36)   FK → official_documents                   │   │
│  │ document_hash   VARCHAR(64)   -- SHA256 at extraction time              │   │
│  │ line_start      INTEGER       -- L0047                                  │   │
│  │ line_end        INTEGER       -- L0052                                  │   │
│  │ quote_text      TEXT          -- verbatim quote from document           │   │
│  │ proves_hts_code VARCHAR(12)                                              │   │
│  │ proves_rate     NUMERIC(5,4)                                             │   │
│  │ proves_program  VARCHAR(50)   -- section_301, section_232_steel         │   │
│  │ quote_verified  BOOLEAN       -- WriteGate verified                     │   │
│  │ human_verified  BOOLEAN       -- human reviewed                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ candidate_changes (Review Queue)                                         │   │
│  │ ─────────────────                                                        │   │
│  │ id              VARCHAR(36)   PK                                         │   │
│  │ job_id          VARCHAR(36)   FK → ingest_jobs                          │   │
│  │ change_type     VARCHAR(20)   -- 'add', 'update', 'expire'              │   │
│  │ target_table    VARCHAR(50)   -- 'section_301_rates'                    │   │
│  │ hts_code        VARCHAR(12)                                              │   │
│  │ proposed_rate   NUMERIC(5,4)                                             │   │
│  │ evidence_quote  TEXT                                                     │   │
│  │ status          VARCHAR(20)   -- pending, validated, rejected, committed│   │
│  │ validation_errors TEXT                                                   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  COUNTRY & SCOPE TABLES                                                         │
│  ──────────────────────                                                         │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ country_aliases                                                          │   │
│  │ ───────────────                                                          │   │
│  │ Maps various inputs to ISO codes:                                        │   │
│  │   'Macau', 'MO', 'MAC' → iso_alpha2='MO'                                │   │
│  │   'China', 'CN', 'PRC' → iso_alpha2='CN'                                │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ program_country_scope                                                    │   │
│  │ ────────────────────                                                     │   │
│  │ Data-driven country applicability per program:                           │   │
│  │   program_id='ieepa_fentanyl', iso_alpha2='CN' → applies                │   │
│  │   program_id='ieepa_fentanyl', iso_alpha2='HK' → applies                │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  SEARCH CACHE (v9.0)                                                            │
│  ──────────────────                                                             │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │ gemini_search_results                                                    │   │
│  │ ─────────────────────                                                    │   │
│  │ Caches Gemini search responses for HTS scope lookups                    │   │
│  │ Key: (hts_code, query_type, material)                                   │   │
│  │ Value: result_json with parsed structured output                        │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### CSV Seed Files (data/*.csv)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CSV SEED DATA                                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  data/mfn_base_rates_8digit.csv                                                 │
│  ─────────────────────────────                                                  │
│  MFN Column 1 base rates from USITC HTS.                                        │
│  Used for EU 15% ceiling formula: reciprocal = max(0, 15% - MFN_rate)          │
│                                                                                  │
│  Columns: hts_8digit, column1_rate, description                                 │
│  Example: 85444290, 0.026, "Insulated electric conductors..."                  │
│  Records: ~10,000 HTS codes                                                     │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  data/section_301_rates_temporal.csv                                            │
│  ───────────────────────────────────                                            │
│  Historical Section 301 rates with time-series tracking.                        │
│  Includes 2024 Four-Year Review rate increases.                                 │
│                                                                                  │
│  Columns: hts_8digit, chapter_99_code, duty_rate, effective_start,             │
│           effective_end, list_name, sector                                      │
│  Example: 85444290, 9903.91.07, 0.50, 2025-01-01, , strategic_medical          │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  data/section_232_hts_codes.csv                                                 │
│  ─────────────────────────────                                                  │
│  Section 232 HTS codes for steel, aluminum, copper.                             │
│  Extracted from CBP CSMS bulletins.                                             │
│                                                                                  │
│  Columns: hts_8digit, material_type, chapter_99_claim, chapter_99_disclaim,    │
│           duty_rate, article_type                                               │
│  Example: 72071100, steel, 9903.80.01, 9903.80.02, 0.50, primary               │
│  Records: 931 codes (596 steel, 255 aluminum, 80 copper)                       │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  data/ieepa_rates_temporal.csv                                                  │
│  ─────────────────────────────                                                  │
│  IEEPA Fentanyl and Reciprocal rates with time-series.                         │
│                                                                                  │
│  Columns: program_type, country_code, chapter_99_code, duty_rate,              │
│           variant, effective_start, effective_end                              │
│  Example: fentanyl, CN, 9903.89.05, 0.20, taxable, 2025-04-02,                 │
│                                                                                  │
│  ─────────────────────────────────────────────────────────────────────────────  │
│                                                                                  │
│  data/annex_ii_exemptions.csv                                                   │
│  ──────────────────────────                                                     │
│  IEEPA Reciprocal Annex II exemptions (pharmaceuticals, critical minerals).    │
│                                                                                  │
│  Columns: hts_code, category, description, effective_date                      │
│  Example: 2941, pharmaceutical, "Antibiotics", 2025-04-02                      │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

These CSVs are loaded on startup by: scripts/populate_tariff_tables.py
```

### Local Filesystem (storage/documents/)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      LOCAL FILESYSTEM STORAGE                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  storage/                                                                        │
│  └── documents/                                                                  │
│      ├── federal_register/                                                       │
│      │   ├── 2024-12345/                                                        │
│      │   │   └── abc123def456.xml    ← 7.2 MB XML file                         │
│      │   ├── 2025-01234/                                                        │
│      │   │   └── fed789abc012.txt    ← raw text from API                       │
│      │   └── 2025-10524/                                                        │
│      │       └── 301update2025.xml                                              │
│      │                                                                           │
│      ├── cbp_csms/                                                              │
│      │   ├── 65936570/                                                          │
│      │   │   └── section232steel.html                                           │
│      │   └── 65794272/                                                          │
│      │       └── coppernotice.html                                              │
│      │                                                                           │
│      └── usitc/                                                                  │
│          └── hts_2025_rev1/                                                     │
│              └── hts_export.xlsx                                                │
│                                                                                  │
│  Storage URI format:                                                            │
│    "local://federal_register/2024-12345/abc123def456.xml"                       │
│                                                                                  │
│  These files are NEVER uploaded to PostgreSQL.                                  │
│  Referenced by: official_documents.storage_uri column                           │
│  Read by: doc.content property → get_storage().get(uri)                         │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## PART 4: DATA FLOW SUMMARY BY STAGE

| Stage | Reads From | Writes To |
|-------|-----------|----------|
| **Discovery** (Watcher) | Federal Register API, CBP RSS | PostgreSQL: ingest_jobs |
| **Fetch** | External URLs | Local filesystem + PostgreSQL metadata |
| **Render** | Local filesystem (via storage_uri) | PostgreSQL: canonical_text |
| **Chunk** | PostgreSQL: canonical_text | PostgreSQL: document_chunks |
| **Extract** | Local filesystem + PostgreSQL chunks | PostgreSQL: candidate_changes |
| **Validate** | PostgreSQL: canonical_text, candidates | PostgreSQL: update status |
| **Commit** | PostgreSQL: validated candidates | PostgreSQL: tariff rate tables |

---

## PART 5: STORAGE ABSTRACTION (Object Storage)

### Storage Abstraction Layer

```python
# app/storage/__init__.py - Factory pattern for storage backends

def get_storage() -> StorageBackend:
    backend = os.environ.get("STORAGE_BACKEND", "local")  # or "s3"
    if backend == "local":
        return LocalStorage("storage/documents")
    elif backend == "s3":
        return S3Storage(bucket=os.environ["S3_BUCKET"])

# app/storage/local.py - Local filesystem implementation
class LocalStorage(StorageBackend):
    SCHEME = "local"

    def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"local://{key}"

    def get(self, uri: str) -> bytes:
        key = uri.replace("local://", "")
        return (self.base_path / key).read_bytes()

# app/models/document_store.py - Transparent access via property
class OfficialDocument(db.Model):
    storage_uri = db.Column(db.String(500))  # "local://..."
    raw_bytes = db.Column(db.LargeBinary)    # Legacy fallback

    @property
    def content(self) -> bytes:
        """Get content from storage_uri or legacy raw_bytes."""
        if self.storage_uri:
            return get_storage().get(self.storage_uri)
        return self.raw_bytes  # Fallback for old records

    def store_content(self, data: bytes, content_type: str) -> str:
        """Store content and return URI."""
        key = f"{self.source}/{self.external_id}/{self.content_hash[:16]}.ext"
        self.storage_uri = get_storage().put(key, data, content_type)
        self.raw_bytes = None  # Don't store in DB
        return self.storage_uri
```

---

## PART 6: KEY DESIGN DECISIONS

### Q: Where does the document go when it arrives?
**A:** LOCAL FILESYSTEM only. The `raw_bytes` (actual document content) goes to `storage/documents/`.

### Q: How is information extracted?
**A:** Worker reads from local filesystem via `doc.content` property, which resolves `storage_uri` to local path.

### Q: Does it persist to SQLite first then PostgreSQL?
**A:** NO. Direct to PostgreSQL for metadata. Blobs stay local. No SQLite in production.

### Q: What goes to PostgreSQL (online)?
- Document metadata (id, source, storage_uri, content_hash, content_type, content_size)
- Rendered canonical_text (line-numbered text for evidence search)
- Document chunks (for RAG)
- Ingest jobs (tracking)
- Extracted tariff rates (the actual business data)
- Evidence packets, audit logs

### Q: What stays local (never online)?
- raw_bytes (actual XML/PDF/HTML content)
- Stored at path like `storage/documents/federal_register/2024-12345/abc123.xml`
- Referenced by `storage_uri = "local://federal_register/2024-12345/abc123.xml"`

---

## IMPLEMENTATION STATUS

| Component | Status |
|-----------|--------|
| Object storage abstraction | COMPLETE |
| storage_uri column | COMPLETE |
| content property | COMPLETE |
| FetchWorker → store_content() | COMPLETE |
| RenderWorker → doc.content | COMPLETE |
| ExtractionWorker → doc.content | COMPLETE |
| Migration script | COMPLETE |
| CSV seed data loading | COMPLETE |

---

## FILES CREATED/MODIFIED

### New Files

| File | Purpose |
|------|---------|
| `app/storage/__init__.py` | Factory function, exports |
| `app/storage/base.py` | Abstract StorageBackend class |
| `app/storage/local.py` | Local filesystem implementation |
| `scripts/migrate_to_object_storage.py` | Migration script |

### Modified Files

| File | Change |
|------|--------|
| `app/models/document_store.py` | Add `storage_uri`, `content` property, `store_content()` |
| `app/workers/fetch_worker.py` | Use `doc.store_content()` instead of `doc.raw_bytes = ...` |
| `app/workers/render_worker.py` | Use `doc.content` instead of `doc.raw_bytes` |
| `app/workers/extraction_worker.py` | Use `doc.content` instead of `doc.raw_bytes` |

---

## ENVIRONMENT VARIABLES

```bash
# Local development (default)
STORAGE_BACKEND=local
STORAGE_PATH=storage/documents

# Production (future S3)
STORAGE_BACKEND=s3
S3_BUCKET=tariff-documents
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-1
```

---

## SIZE IMPACT

| Storage | Before | After |
|---------|--------|-------|
| **PostgreSQL** | ~36 MB | ~15 MB |
| **Local filesystem** | 0 | ~20 MB |
| **Total** | ~36 MB | ~35 MB (same, but DB is lighter) |

Future: Can move filesystem to S3 for even cheaper storage.

---

## PART 7: AUTO-SYNC (SQLite → PostgreSQL)

**Status:** IMPLEMENTED (January 2026)

### Overview

The auto-sync feature allows local development with SQLite while automatically replicating data to PostgreSQL (Railway) after each pipeline run. This provides the best of both worlds:
- **Fast local development** with SQLite
- **Production data parity** with PostgreSQL

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           AUTO-SYNC ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  LOCAL MACHINE                              RAILWAY (Production)                │
│  ─────────────                              ─────────────────────                │
│                                                                                  │
│  ┌─────────────────┐                       ┌─────────────────┐                 │
│  │    SQLite       │  ──── AUTO-SYNC ───► │   PostgreSQL    │                 │
│  │ instance/       │      (after each     │                 │                 │
│  │ sqlite.db       │       pipeline run)  │                 │                 │
│  └─────────────────┘                       └─────────────────┘                 │
│         ▲                                                                       │
│         │                                                                       │
│  process_ingest_queue.py                                                        │
│         │                                                                       │
│         ▼                                                                       │
│  ┌─────────────────┐                                                           │
│  │ After batch:    │                                                           │
│  │ sync_to_pg()    │                                                           │
│  └─────────────────┘                                                           │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### How It Works

1. **Pipeline processes documents locally** → writes to SQLite
2. **After batch completes** → `run_auto_sync()` is called
3. **Sync module** → connects to both databases
4. **For each table** (in FK order):
   - Get existing IDs in PostgreSQL
   - Find new rows in SQLite (not in PostgreSQL)
   - Clean NUL characters (PostgreSQL rejects `\x00`)
   - Insert new rows with per-row commits

### Environment Variables

```bash
# .env
AUTO_SYNC_ENABLED=true                    # Enable/disable auto-sync
DATABASE_URL_REMOTE=postgresql://...      # Remote PostgreSQL for sync

# Local (default when DATABASE_URL not set)
SQLALCHEMY_DATABASE_URI=sqlite:///sqlite.db
```

### Tables Synced (FK Dependency Order)

Tables are synced in **foreign key dependency order** to avoid constraint violations:

```
SYNC_TABLES = [
    'official_documents',  # 1st - Parent (no FK dependencies)
    'ingest_jobs',         # 2nd - References documents via document_id
    'candidate_changes',   # 3rd - References jobs via job_id
    'section_301_rates',   # 4th - No FK to above tables
    'section_232_rates',   # 5th - No FK to above tables
    'ieepa_rates',         # 6th - No FK to above tables
    'tariff_audit_log',    # 7th - For audit trail
    'evidence_packets',    # 8th - References documents
]
```

### What Gets Synced vs. Excluded

| Synced | Excluded |
|--------|----------|
| Document metadata | raw_bytes (blobs stay local) |
| Ingest job status | storage_uri (local paths) |
| Candidate changes | created_at/updated_at timestamps |
| Tariff rates (301, 232, IEEPA) | |
| Evidence packets | |
| Audit logs | |

### NUL Character Handling

PostgreSQL rejects strings containing `\x00` (NUL character). The sync module cleans these:

```python
def clean_text(val):
    """Remove NUL characters that PostgreSQL rejects."""
    if isinstance(val, str):
        return val.replace('\x00', '')
    return val
```

### Sync Module Files

| File | Purpose |
|------|---------|
| `app/sync/__init__.py` | Module init, exports |
| `app/sync/pg_sync.py` | Main sync logic |
| `scripts/process_ingest_queue.py` | Calls sync after pipeline |
| `tests/test_sync_integration.py` | Integration tests |

### Key Functions

```python
# app/sync/pg_sync.py

def is_sync_enabled() -> bool:
    """Check if AUTO_SYNC_ENABLED=true and DATABASE_URL_REMOTE is set."""

def sync_to_postgresql(tables: Optional[List[str]] = None) -> dict:
    """
    Sync SQLite data to PostgreSQL.

    Returns:
        {
            'enabled': True,
            'tables': {
                'section_301_rates': {'added': 100, 'errors': 0},
                ...
            },
            'total_added': 500,
            'total_errors': 0
        }
    """

def sync_table(table_name, sqlite_conn, pg_engine, exclude_cols=None):
    """Sync a single table. Returns (added_count, error_count)."""
```

### Integration with Pipeline

```python
# scripts/process_ingest_queue.py

def run_auto_sync(results: list):
    """Run auto-sync to PostgreSQL if enabled and changes were made."""
    if not results:
        return

    if not is_sync_enabled():
        logger.debug("Auto-sync disabled")
        return

    # Only sync if there were successful jobs
    successful_jobs = sum(1 for r in results
                         if r.get("status") in ("committed", "completed_no_changes"))

    if successful_jobs == 0:
        return

    sync_results = sync_to_postgresql()
    logger.info(f"Sync complete: {sync_results['total_added']} rows added")
```

### Integration Tests

```bash
# Run integration tests
DATABASE_URL_REMOTE="postgresql://..." AUTO_SYNC_ENABLED=true \
    pipenv run pytest tests/test_sync_integration.py -v
```

**Test coverage (17 tests):**
- Module import verification
- Environment variable checking
- NUL character cleaning
- Database connections (SQLite + PostgreSQL)
- Required tables existence
- Data count matching
- Specific HTS code sync verification
- Sync idempotency (running twice doesn't duplicate)
- Selective table sync
- FK ordering validation
- Edge cases (empty results, disabled sync)

### Idempotency

The sync is **idempotent** - running it multiple times won't duplicate data:

```python
# Get existing IDs in PostgreSQL
existing_ids = set(row[0] for row in pg_conn.execute(
    text(f'SELECT id FROM {table_name}')
).fetchall())

# Skip if already exists
if row_dict['id'] in existing_ids:
    continue
```

### Error Handling

- **Per-row commits**: Each row commits separately to handle FK failures gracefully
- **Error counting**: Tracks errors per table, logs first 5
- **Graceful degradation**: Sync failures don't break the pipeline

```python
try:
    pg_conn.execute(text(f'INSERT INTO ...'), row_dict)
    pg_conn.commit()  # Per-row commit
    new_count += 1
except Exception as e:
    error_count += 1
    pg_conn.rollback()
    if error_count <= 5:
        logger.warning(f"Error syncing {table_name}: {str(e)[:100]}")
```

### Manual Sync

You can also trigger sync manually:

```python
from app.sync import sync_to_postgresql

# Sync all tables
result = sync_to_postgresql()

# Sync specific tables only
result = sync_to_postgresql(tables=['section_301_rates', 'section_232_rates'])
```

---

## COMPLETE DATABASE DESIGN SUMMARY

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      COMPLETE DATABASE ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA STORAGE TIERS                              │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                         │   │
│  │  TIER 1: STATIC SEED DATA (data/*.csv)                                 │   │
│  │  ─────────────────────────────────────                                 │   │
│  │  • section_301_rates_temporal.csv  → Loaded on startup                 │   │
│  │  • section_232_hts_codes.csv       → Never modified by app             │   │
│  │  • ieepa_rates_temporal.csv        → Manual updates only               │   │
│  │  • mfn_base_rates_8digit.csv                                           │   │
│  │  • annex_ii_exemptions.csv                                             │   │
│  │                                                                         │   │
│  │  TIER 2: LOCAL SQLITE (instance/sqlite.db)                             │   │
│  │  ────────────────────────────────────────                              │   │
│  │  • Primary database for local development                              │   │
│  │  • Pipeline writes extracted data here                                 │   │
│  │  • Fast, no network latency                                            │   │
│  │                                                                         │   │
│  │  TIER 3: REMOTE POSTGRESQL (Railway)                                   │   │
│  │  ───────────────────────────────────                                   │   │
│  │  • Production database                                                 │   │
│  │  • Auto-synced from SQLite after pipeline runs                         │   │
│  │  • Serves API requests in production                                   │   │
│  │                                                                         │   │
│  │  TIER 4: LOCAL FILESYSTEM (storage/documents/)                         │   │
│  │  ─────────────────────────────────────────────                         │   │
│  │  • Raw document blobs (XML, PDF, HTML)                                 │   │
│  │  • NEVER uploaded to cloud                                             │   │
│  │  • Referenced via storage_uri column                                   │   │
│  │                                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA FLOW                                       │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                         │   │
│  │                     ┌─────────────┐                                     │   │
│  │                     │   STARTUP   │                                     │   │
│  │                     └──────┬──────┘                                     │   │
│  │                            │                                            │   │
│  │                            ▼                                            │   │
│  │   data/*.csv ─────► populate_tariff_tables.py ─────► Database          │   │
│  │                                                                         │   │
│  │                     ┌─────────────┐                                     │   │
│  │                     │  PIPELINE   │                                     │   │
│  │                     └──────┬──────┘                                     │   │
│  │                            │                                            │   │
│  │   External URLs ──► FetchWorker ──► storage/documents/ (blobs)         │   │
│  │                            │                                            │   │
│  │                            ├──► SQLite (metadata, rates)               │   │
│  │                            │                                            │   │
│  │                            ▼                                            │   │
│  │                     ┌─────────────┐                                     │   │
│  │                     │  AUTO-SYNC  │                                     │   │
│  │                     └──────┬──────┘                                     │   │
│  │                            │                                            │   │
│  │   SQLite ─────────────────►│─────────────────► PostgreSQL              │   │
│  │   (if AUTO_SYNC_ENABLED)   │                   (Railway)               │   │
│  │                                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    ENVIRONMENT CONFIGURATIONS                           │   │
│  ├─────────────────────────────────────────────────────────────────────────┤   │
│  │                                                                         │   │
│  │  LOCAL DEVELOPMENT:                                                     │   │
│  │    DATABASE_URL=(not set) → Uses SQLite                                │   │
│  │    AUTO_SYNC_ENABLED=true                                              │   │
│  │    DATABASE_URL_REMOTE=postgresql://...                                │   │
│  │                                                                         │   │
│  │  PRODUCTION (Railway):                                                  │   │
│  │    DATABASE_URL=postgresql://... → Uses PostgreSQL directly            │   │
│  │    AUTO_SYNC_ENABLED=false (not needed)                                │   │
│  │                                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Key Tables (38 total)

| Category | Tables | Records |
|----------|--------|---------|
| **Document Pipeline** | official_documents, ingest_jobs, candidate_changes, document_chunks | Varies |
| **Tariff Rates** | section_301_rates, section_232_rates, ieepa_rates, mfn_base_rates | ~20,000+ |
| **Country/Scope** | country_aliases, program_country_scope | ~300 |
| **Audit/Evidence** | evidence_packets, tariff_audit_log | Varies |
| **Cache** | gemini_search_results | Varies |

### Implementation Status (Updated)

| Component | Status |
|-----------|--------|
| Object storage abstraction | COMPLETE |
| storage_uri column | COMPLETE |
| content property | COMPLETE |
| FetchWorker → store_content() | COMPLETE |
| RenderWorker → doc.content | COMPLETE |
| ExtractionWorker → doc.content | COMPLETE |
| Migration script | COMPLETE |
| CSV seed data loading | COMPLETE |
| **Auto-sync module** | **COMPLETE** |
| **Auto-sync integration** | **COMPLETE** |
| **Integration tests** | **COMPLETE (17 tests)** |
