# Unified Temporal Tariff Pipeline - Complete System Architecture

**Version:** 13.0
**Date:** January 2026
**Status:** Production Ready

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Temporal Database Design](#3-temporal-database-design)
4. [Document Discovery Layer (Watchers)](#4-document-discovery-layer-watchers)
5. [Document Ingestion Pipeline](#5-document-ingestion-pipeline)
6. [Extraction and Commit Engine](#6-extraction-and-commit-engine)
7. [Stacking Calculator Integration](#7-stacking-calculator-integration)
8. [Cron and Scheduling](#8-cron-and-scheduling)
9. [Data Flow Diagrams](#9-data-flow-diagrams)
10. [Database Schema Reference](#10-database-schema-reference)
11. [Operational Commands](#11-operational-commands)

---

## 1. Executive Summary

The Unified Temporal Tariff Pipeline is a complete end-to-end system for:

1. **Discovering** new tariff regulations from official government sources
2. **Ingesting** documents (PDF, XML, HTML, DOCX) into a structured database
3. **Extracting** tariff changes using deterministic parsing + LLM analysis
4. **Committing** changes to temporal rate tables with full audit trail
5. **Querying** historical rates for any date using `get_rate_as_of()` methods

### Key Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Temporal First** | All rate tables use `effective_start`/`effective_end` for time-series tracking |
| **Evidence-Based** | Every rate links back to source document with line numbers |
| **Graceful Fallback** | Temporal lookup → Static table → Hardcoded constants |
| **Audit Trail** | TariffAuditLog tracks all INSERT/UPDATE/SUPERSEDE operations |
| **Idempotent** | Content hashing prevents duplicate processing |

### Current Data Counts

| Table | Rows | Description |
|-------|------|-------------|
| `section_301_rates` | 11,878 | Section 301 China tariffs (temporal) |
| `section_232_rates` | 1,596 | Section 232 Steel/Aluminum/Copper (temporal) |
| `ieepa_rates` | 45 | IEEPA Fentanyl and Reciprocal (temporal) |
| `section_232_materials` | 838 | Static HTS-to-material mapping |
| `official_documents` | ~100+ | Ingested Federal Register notices |

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        REGULATORY UPDATE PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ Federal Register│  │   CBP CSMS      │  │     USITC       │             │
│  │     Watcher     │  │    Watcher      │  │    Watcher      │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                ▼                                            │
│                    ┌───────────────────────┐                               │
│                    │   run_watchers.py     │  ◄── Cron (manual/scheduled)  │
│                    │   (Discovery Phase)   │                               │
│                    └───────────┬───────────┘                               │
│                                ▼                                            │
│                    ┌───────────────────────┐                               │
│                    │      IngestJob        │  Queue (status=queued)        │
│                    │   (10 queued docs)    │                               │
│                    └───────────┬───────────┘                               │
│                                ▼                                            │
│           ┌────────────────────────────────────────────┐                   │
│           │        process_ingest_queue.py             │                   │
│           │           (Pipeline Phase)                 │                   │
│           ├────────────────────────────────────────────┤                   │
│           │                                            │                   │
│           │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │                   │
│           │  │  FETCH   │→ │  RENDER  │→ │  CHUNK   │ │                   │
│           │  │ (HTTP)   │  │(XML/PDF) │  │ (500tok) │ │                   │
│           │  └──────────┘  └──────────┘  └──────────┘ │                   │
│           │        │                                   │                   │
│           │        ▼                                   │                   │
│           │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │                   │
│           │  │ EXTRACT  │→ │ VALIDATE │→ │  COMMIT  │ │                   │
│           │  │(LLM+XML) │  │(Evidence)│  │(Temporal)│ │                   │
│           │  └──────────┘  └──────────┘  └──────────┘ │                   │
│           │                                            │                   │
│           └────────────────────────────────────────────┘                   │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    TEMPORAL RATE TABLES                              │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  section_301_rates    section_232_rates    ieepa_rates              │   │
│  │  ├─ hts_8digit        ├─ hts_8digit        ├─ program_type          │   │
│  │  ├─ duty_rate         ├─ material_type     ├─ country_code          │   │
│  │  ├─ effective_start   ├─ duty_rate         ├─ duty_rate             │   │
│  │  ├─ effective_end     ├─ effective_start   ├─ variant               │   │
│  │  └─ supersedes_id     ├─ effective_end     ├─ effective_start       │   │
│  │                       └─ country_code      └─ effective_end         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    STACKING CALCULATOR                               │   │
│  │            get_rate_as_of(hts_code, import_date)                    │   │
│  │                                                                      │   │
│  │   "What's the duty rate for HTS 8544.42.90 imported on 2025-02-15?" │   │
│  │   → Section 232 Steel: 25% (before March 2025 increase to 50%)      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Temporal Database Design

### 3.1 Why Temporal Tables?

**The Problem (Design Flaw 6):**
- Section 301 was already temporal ✅
- Section 232 used static tables (no history) ❌
- IEEPA used hardcoded Python constants ❌

**The Solution:**
All tariff programs now use temporal tables with `effective_start`/`effective_end` columns:

```sql
-- Query: "What was the steel tariff rate on February 15, 2025?"
SELECT duty_rate FROM section_232_rates
WHERE hts_8digit = '72081000'
  AND material_type = 'steel'
  AND effective_start <= '2025-02-15'
  AND (effective_end IS NULL OR effective_end > '2025-02-15')
ORDER BY effective_start DESC
LIMIT 1;

-- Result: 0.25 (25% - before the March 2025 increase to 50%)
```

### 3.2 Temporal Table Schema

#### Section301Rate

```python
class Section301Rate(BaseModel):
    __tablename__ = "section_301_rates"

    # Core identification
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)
    hts_10digit = db.Column(db.String(12), nullable=True)
    chapter_99_code = db.Column(db.String(16), nullable=False)

    # Rate
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)  # 0.2500 = 25%

    # Temporal validity
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)  # NULL = currently active

    # Classification
    list_name = db.Column(db.String(64), nullable=True)  # "list_3", "list_4a"
    sector = db.Column(db.String(64), nullable=True)     # "medical", "ev_battery"
    role = db.Column(db.String(16), default='impose')    # 'impose' or 'exclude'

    # Supersession chain
    supersedes_id = db.Column(db.Integer, db.ForeignKey('section_301_rates.id'))
    superseded_by_id = db.Column(db.Integer, db.ForeignKey('section_301_rates.id'))

    # Audit trail
    source_doc = db.Column(db.String(256), nullable=True)
    created_by = db.Column(db.String(64), default='system')
```

#### Section232Rate

```python
class Section232Rate(BaseModel):
    __tablename__ = "section_232_rates"

    # Core identification
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)
    material_type = db.Column(db.String(20), nullable=False)  # 'steel', 'aluminum', 'copper'

    # Chapter 99 codes
    chapter_99_claim = db.Column(db.String(16), nullable=False)
    chapter_99_disclaim = db.Column(db.String(16), nullable=True)

    # Rate
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)

    # Country scope (NULL = global default)
    country_code = db.Column(db.String(3), nullable=True, index=True)  # 'GBR' for UK exception

    # Article type per U.S. Note 16
    article_type = db.Column(db.String(20), nullable=True)  # 'primary', 'derivative', 'content'

    # Temporal validity
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)

    # Audit trail
    source_doc = db.Column(db.String(256), nullable=True)
    created_by = db.Column(db.String(64), default='system')
```

#### IeepaRate

```python
class IeepaRate(BaseModel):
    __tablename__ = "ieepa_rates"

    # Program identification
    program_type = db.Column(db.String(20), nullable=False)  # 'fentanyl', 'reciprocal'
    country_code = db.Column(db.String(3), nullable=True, index=True)  # 'CN', 'HK', 'MO'

    # Chapter 99 code and rate
    chapter_99_code = db.Column(db.String(16), nullable=False)
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)

    # Variant (for reciprocal exemptions)
    variant = db.Column(db.String(32), nullable=True)  # 'standard', 'annex_ii_exempt', etc.
    rate_type = db.Column(db.String(20), default='ad_valorem')

    # Temporal validity
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)

    # Audit trail
    source_doc = db.Column(db.String(256), nullable=True)
    created_by = db.Column(db.String(64), default='system')
```

### 3.3 Historical Rate Data

#### Section 232 Rate History

| Material | Period | Rate | Source |
|----------|--------|------|--------|
| Steel | Mar 2018 - Mar 2025 | 25% | Proclamation 9705 |
| Steel | Mar 2025 - present | 50% | Proclamation 10896 |
| Aluminum | Mar 2018 - Mar 2025 | 10% | Proclamation 9704 |
| Aluminum | Mar 2025 - present | 50% | Proclamation 10896 |
| Copper | Mar 2025 - present | 50% | Proclamation 10896 |

#### IEEPA Fentanyl Rate History (China)

| Period | Rate | Source |
|--------|------|--------|
| Feb 4, 2025 - Apr 8, 2025 | 10% | EO 14195 (original) |
| Apr 9, 2025 - Nov 14, 2025 | 20% | EO 14257 (doubled for China) |
| Nov 15, 2025 - present | 10% | EO 14357 (reduced) |

*Note: Hong Kong (HK) and Macau (MO) stayed at 10% throughout.*

### 3.4 get_rate_as_of() Query Methods

```python
# Section 301: Role-based precedence (exclusions override impositions)
@classmethod
def get_rate_as_of(cls, hts_8digit: str, as_of_date: date) -> Optional["Section301Rate"]:
    return cls.query.filter(
        cls.hts_8digit == hts_8digit,
        cls.effective_start <= as_of_date,
        or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
    ).order_by(
        case((cls.role == 'exclude', 0), else_=1),  # Exclusions first
        cls.effective_start.desc()
    ).first()

# Section 232: Country-specific with global fallback
@classmethod
def get_rate_as_of(cls, hts_8digit: str, material: str, country_code: str,
                   as_of_date: date) -> Optional["Section232Rate"]:
    # Try country-specific first (e.g., UK at 25%)
    rate = cls.query.filter(
        cls.hts_8digit == hts_8digit,
        cls.material_type == material,
        cls.country_code == country_code,
        cls.effective_start <= as_of_date,
        or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
    ).first()

    if rate:
        return rate

    # Fall back to global rate (country_code = NULL)
    return cls.query.filter(
        cls.hts_8digit == hts_8digit,
        cls.material_type == material,
        cls.country_code.is_(None),
        cls.effective_start <= as_of_date,
        or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
    ).first()

# IEEPA: Variant-aware lookup
@classmethod
def get_rate_as_of(cls, program_type: str, country_code: str,
                   as_of_date: date, variant: str = None) -> Optional["IeepaRate"]:
    query = cls.query.filter(
        cls.program_type == program_type,
        cls.country_code == country_code,
        cls.effective_start <= as_of_date,
        or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
    )
    if variant:
        query = query.filter(cls.variant == variant)
    return query.order_by(cls.effective_start.desc()).first()
```

---

## 4. Document Discovery Layer (Watchers)

### 4.1 Watcher Architecture

```
app/watchers/
├── __init__.py           # Exports all watchers
├── base.py               # BaseWatcher abstract class + DiscoveredDocument
├── federal_register.py   # Federal Register API watcher
├── cbp_csms.py          # CBP CSMS archive watcher
└── usitc.py             # USITC HTS update watcher
```

### 4.2 Federal Register Watcher

**Source:** Federal Register API (`https://www.federalregister.gov/api/v1`)

**Search Terms Monitored:**
- "Section 301"
- "IEEPA" (International Emergency Economic Powers Act)
- "Section 232"
- "9903" (Chapter 99 tariff codes)
- "tariff modification"

**Poll Frequency:** Every 6 hours (configurable)

```python
class FederalRegisterWatcher(BaseWatcher):
    SOURCE_NAME = "federal_register"
    POLL_INTERVAL_HOURS = 6
    BASE_URL = "https://www.federalregister.gov/api/v1"

    SEARCH_QUERIES = [
        "Section 301",
        "IEEPA tariff",
        "Section 232 steel aluminum",
        "9903",  # Chapter 99 codes
    ]

    def poll(self, since_date: date) -> List[DiscoveredDocument]:
        documents = []
        for query in self.SEARCH_QUERIES:
            results = self._search(query, since_date)
            for doc in results:
                documents.append(DiscoveredDocument(
                    source=self.SOURCE_NAME,
                    external_id=doc['document_number'],
                    xml_url=doc.get('full_text_xml_url'),
                    pdf_url=doc.get('pdf_url'),
                    html_url=doc.get('html_url'),
                    title=doc['title'],
                    publication_date=doc['publication_date'],
                    effective_date=doc.get('effective_on'),
                    metadata={'agencies': doc.get('agencies', [])},
                ))
        return self.deduplicate(documents)
```

**Output Format:** XML with `<GPOTABLE>` structured data for tariff schedules

### 4.3 CBP CSMS Watcher

**Source:** CBP Cargo Systems Messaging Service Archive

**Content Monitored:**
- CSMS bulletins (e.g., #65936570, #65794272)
- Section 232 steel/aluminum/copper lists
- Entry summary guidance updates

```python
class CBPCSMSWatcher(BaseWatcher):
    SOURCE_NAME = "cbp_csms"
    POLL_INTERVAL_HOURS = 12
    ARCHIVE_URL = "https://www.cbp.gov/document/guidance/csms-archive"

    def poll(self, since_date: date) -> List[DiscoveredDocument]:
        # Scrape archive page for monthly PDF compilations
        # Extract date ranges from link text
        # Return documents for processing
```

### 4.4 USITC Watcher

**Source:** U.S. International Trade Commission HTS updates

**Content Monitored:**
- HTS schedule revisions
- Statistical suffix changes
- Chapter 99 updates

### 4.5 DiscoveredDocument Data Class

```python
@dataclass
class DiscoveredDocument:
    source: str                    # "federal_register", "cbp_csms", "usitc"
    external_id: str               # Document number (e.g., "2026-00206")
    pdf_url: Optional[str]         # Direct PDF link
    xml_url: Optional[str]         # Full-text XML link (preferred)
    html_url: Optional[str]        # HTML version
    title: str                     # Document title
    publication_date: date         # Publication date
    effective_date: Optional[date] # When rules take effect
    metadata: Dict[str, Any]       # Source-specific metadata
    discovered_at: datetime        # When watcher found it
    discovered_by: str             # Watcher name

    def preferred_url(self) -> str:
        """Priority: XML > HTML > PDF (for text extraction quality)"""
        return self.xml_url or self.html_url or self.pdf_url
```

---

## 5. Document Ingestion Pipeline

### 5.1 Pipeline Stages

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         DOCUMENT PIPELINE                                 │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   STAGE 1: FETCH                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  FetchWorker.process_job(job)                                    │   │
│   │  • HTTP GET job.url (timeout=60s)                               │   │
│   │  • Compute SHA256 content_hash                                   │   │
│   │  • Check for duplicate by hash                                   │   │
│   │  • Store OfficialDocument with raw_bytes                        │   │
│   │  • Detect content_type: xml, pdf, html, docx                    │   │
│   │  Output: OfficialDocument (status=fetched)                      │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              ▼                                           │
│   STAGE 2: RENDER                                                        │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  RenderWorker.process(doc, job)                                  │   │
│   │  • Route by content_type:                                        │   │
│   │    - XML: Parse GPOTABLE, extract P/FP/HD text elements         │   │
│   │    - PDF: pdfplumber extract_text() with page markers           │   │
│   │    - HTML: BeautifulSoup, remove nav/script/style               │   │
│   │    - DOCX: python-docx paragraphs + tables                      │   │
│   │  • Add line numbers: "L0001: First line content"                │   │
│   │  Output: doc.canonical_text (line-numbered)                     │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              ▼                                           │
│   STAGE 3: CHUNK                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  ChunkWorker.process(doc, job)                                   │   │
│   │  • Split by section headings (=== HEADING ===)                  │   │
│   │  • Target: 500 tokens per chunk (min 100, max 900)              │   │
│   │  • Track: line_start, line_end, chunk_type, section_heading     │   │
│   │  • Chunk types: narrative, table, heading                       │   │
│   │  Output: DocumentChunk[] records                                │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              ▼                                           │
│   STAGE 4: EXTRACT                                                       │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  ExtractionWorker.extract_from_document(doc, job)                │   │
│   │  • Dual extraction strategy:                                     │   │
│   │    1. XML Tables: Deterministic GPOTABLE parsing                │   │
│   │    2. LLM RAG: Send chunks to GPT with TARIFF_EXTRACTION_PROMPT │   │
│   │  • Extract: hts_code, rate, chapter_99_code, effective_date     │   │
│   │  • Find evidence: quote text, line numbers                      │   │
│   │  • Resolve Chapter 99 codes using Chapter99Resolver             │   │
│   │  Output: CandidateChange[] records                              │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              ▼                                           │
│   STAGE 5: VALIDATE                                                      │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  ValidationWorker.validate(candidate, doc)                       │   │
│   │  • Verify HTS code appears in canonical_text                    │   │
│   │  • Verify Chapter 99 code appears                               │   │
│   │  • Verify rate (percentage or decimal)                          │   │
│   │  • Verify evidence quote matches source                         │   │
│   │  • Assign confidence score (1.0 for XML, variable for LLM)      │   │
│   │  Output: ValidationResult (is_valid, confidence, reason)        │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                              ▼                                           │
│   STAGE 6: COMMIT                                                        │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │  CommitEngine.commit_candidate(candidate, evidence, doc, job)    │   │
│   │  • WriteGate approval check                                      │   │
│   │  • Route by program: section_301, section_232_*, ieepa_*        │   │
│   │  • Find existing active rate (effective_end IS NULL)            │   │
│   │  • Close old rate: effective_end = new.effective_start          │   │
│   │  • Insert new rate with supersedes_id link                      │   │
│   │  • Write TariffAuditLog and RegulatoryRunChange                 │   │
│   │  Output: (success, record_id, error_message)                    │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 5.2 IngestJob Model

```python
class IngestJob(BaseModel):
    __tablename__ = "ingest_jobs"

    # Identification
    source = db.Column(db.String(64), nullable=False, index=True)
    external_id = db.Column(db.String(256), nullable=False, index=True)
    url = db.Column(db.String(1024), nullable=True)

    # Content tracking
    content_hash = db.Column(db.String(64), nullable=True, index=True)
    revision_number = db.Column(db.Integer, default=1)
    parent_job_id = db.Column(db.Integer, db.ForeignKey('ingest_jobs.id'))

    # Processing
    status = db.Column(db.String(32), default='queued', index=True)
    processing_reason = db.Column(db.String(64))  # 'initial', 'correction', 'reparse'
    attempt_number = db.Column(db.Integer, default=1)
    retry_count = db.Column(db.Integer, default=0)

    # Results
    document_id = db.Column(db.Integer, db.ForeignKey('official_documents.id'))
    changes_extracted = db.Column(db.Integer, default=0)
    changes_validated = db.Column(db.Integer, default=0)
    changes_committed = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text, nullable=True)

    # Timestamps
    discovered_at = db.Column(db.DateTime)
    discovered_by = db.Column(db.String(64))
    claimed_at = db.Column(db.DateTime)
    claimed_by = db.Column(db.String(128))
    completed_at = db.Column(db.DateTime)
```

**Status Lifecycle:**
```
queued → fetching → fetched → rendering → rendered → chunking → chunked
       → extracting → extracted → validating → validated → committing → committed

Terminal states:
  - committed: Changes written to temporal tables
  - completed_no_changes: No tariff changes found (not a tariff notice)
  - needs_review: WriteGate rejected, requires human review
  - validation_failed: Evidence doesn't match
  - failed: Exception during processing
```

### 5.3 PDF Extraction Details

**Library:** `pdfplumber`

```python
def _render_pdf(self, raw_bytes: bytes) -> str:
    """Extract text from PDF with page markers."""
    import pdfplumber
    from io import BytesIO

    lines = []
    line_num = 1

    with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            # Add page marker
            lines.append(f"L{line_num:04d}: === PAGE {page_num} ===")
            line_num += 1

            # Extract text
            text = page.extract_text() or ""
            for line in text.split('\n'):
                if line.strip():
                    lines.append(f"L{line_num:04d}: {line}")
                    line_num += 1

    return '\n'.join(lines)
```

**Output Format:**
```
L0001: === PAGE 1 ===
L0002: DEPARTMENT OF COMMERCE
L0003: International Trade Administration
L0004:
L0005: Notice of Modification of Section 301 Tariffs
...
L0047: === PAGE 2 ===
L0048: EFFECTIVE DATE: This rule is effective January 1, 2026
```

### 5.4 XML Table Extraction Details

**Target Elements:** `<GPOTABLE>` (Government Publishing Office Tables)

```python
def _extract_from_xml(self, doc: OfficialDocument) -> List[CandidateChange]:
    """Deterministic extraction from Federal Register XML tables."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(doc.raw_bytes)
    candidates = []

    for table in root.findall('.//GPOTABLE'):
        context = self._get_table_context(table)
        chapter_99_code = self.chapter99_resolver.resolve(context)

        for row in table.findall('.//ROW'):
            entries = row.findall('ENT')
            if len(entries) >= 2:
                hts_code = self._extract_hts(entries[0].text)
                description = entries[1].text or ""

                if len(entries) >= 3:
                    rate = self._parse_rate(entries[2].text)

                if hts_code:
                    candidates.append(CandidateChange(
                        document_id=str(doc.id),
                        hts_code=hts_code,
                        description=description,
                        new_chapter_99_code=chapter_99_code,
                        rate=rate,
                        extraction_method="xml_table",
                        evidence_quote=self._find_evidence(hts_code, doc),
                    ))

    return candidates
```

---

## 6. Extraction and Commit Engine

### 6.1 CandidateChange Data Class

```python
@dataclass
class CandidateChange:
    document_id: str
    hts_code: str                          # "8544.42.90" or "85444290"
    description: str
    old_chapter_99_code: Optional[str]
    new_chapter_99_code: str               # "9903.88.03"

    # Single rate (simple case)
    rate: Optional[Decimal]                # 0.25 for 25%
    effective_date: Optional[date]

    # Multi-rate schedule (staged increases)
    rate_schedule: List[RateScheduleEntry] = field(default_factory=list)

    # Program identification
    program: str                           # "section_301", "section_232_steel", etc.
    product_group: str

    # Evidence tracking
    evidence_quote: str                    # Verbatim text from document
    evidence_chunk_id: Optional[str]
    evidence_line_start: int
    evidence_line_end: int

    # Extraction metadata
    extraction_method: str                 # "xml_table" or "llm_rag"

    def has_staged_rates(self) -> bool:
        return len(self.rate_schedule) > 1
```

### 6.2 RateScheduleEntry (Multi-Rate Support)

```python
@dataclass
class RateScheduleEntry:
    rate: Decimal
    effective_start: date
    effective_end: Optional[date]
```

**Example: Four-Year Review Staged Increase**
```python
rate_schedule = [
    RateScheduleEntry(rate=Decimal('0.25'), effective_start=date(2025, 1, 1),
                      effective_end=date(2026, 1, 1)),
    RateScheduleEntry(rate=Decimal('0.50'), effective_start=date(2026, 1, 1),
                      effective_end=None),
]
```

### 6.3 Commit Engine - Supersession Logic

```python
def _commit_301(self, candidate, evidence, doc, job, run_id):
    """Commit Section 301 rate with temporal supersession."""

    hts_8digit = candidate.hts_code.replace(".", "")[:8]

    # 1. Find existing active rates
    existing_rates = Section301Rate.query.filter(
        Section301Rate.hts_8digit == hts_8digit,
        Section301Rate.effective_end.is_(None)  # Active rates only
    ).all()

    # 2. Close overlapping rates (set effective_end)
    supersedes_id = None
    for old_rate in existing_rates:
        if old_rate.effective_start <= candidate.effective_date:
            old_rate.effective_end = candidate.effective_date
            supersedes_id = old_rate.id

    # 3. Insert new rate with supersession link
    new_rate = Section301Rate(
        hts_8digit=hts_8digit,
        chapter_99_code=candidate.new_chapter_99_code,
        duty_rate=candidate.rate,
        effective_start=candidate.effective_date,
        effective_end=None,  # Active
        supersedes_id=supersedes_id,
        source_doc=str(doc.id),
        created_by="commit_engine",
    )
    db.session.add(new_rate)

    # 4. Link old rate to new
    if supersedes_id:
        old_rate = Section301Rate.query.get(supersedes_id)
        old_rate.superseded_by_id = new_rate.id

    # 5. Write audit log
    self._write_audit_log(
        table_name="section_301_rates",
        record_id=new_rate.id,
        action="SUPERSEDE" if supersedes_id else "INSERT",
        new_values=new_rate.as_dict(),
        source_doc=doc,
        job_id=job.id,
    )

    db.session.commit()
    return (True, str(new_rate.id), None)
```

### 6.4 Audit Trail

**TariffAuditLog Table:**
```python
class TariffAuditLog(BaseModel):
    __tablename__ = "tariff_audit_log"

    table_name = db.Column(db.String(64), nullable=False)
    record_id = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(32), nullable=False)  # INSERT, SUPERSEDE, UPDATE
    old_values = db.Column(db.JSON, nullable=True)
    new_values = db.Column(db.JSON, nullable=False)
    source_doc = db.Column(db.String(256), nullable=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey('evidence_packets.id'))
    job_id = db.Column(db.Integer, db.ForeignKey('ingest_jobs.id'))
    run_id = db.Column(db.Integer, db.ForeignKey('regulatory_runs.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

---

## 7. Stacking Calculator Integration

### 7.1 Temporal Lookup in Stacking Tools

**File:** `app/chat/tools/stacking_tools.py`

```python
def get_ieepa_rate_temporal(program_type: str, country_code: str,
                            as_of_date=None, variant: str = None):
    """
    Get IEEPA rate from temporal table with fallback to hardcoded constants.

    Two-stage fallback pattern:
    1. Try temporal table first (production data)
    2. Fall back to hardcoded constants (development/backwards compatibility)
    """
    lookup_date = as_of_date or date.today()

    # Stage 1: Try temporal table
    try:
        app = get_flask_app()
        with app.app_context():
            models = get_models()
            IeepaRate = models.get("IeepaRate")
            if IeepaRate:
                rate = IeepaRate.get_rate_as_of(
                    program_type=program_type,
                    country_code=country_code,
                    as_of_date=lookup_date,
                    variant=variant
                )
                if rate:
                    return {
                        'code': rate.chapter_99_code,
                        'rate': float(rate.duty_rate),
                        'source': 'temporal',
                        'effective_start': rate.effective_start.isoformat(),
                    }
    except Exception:
        pass  # Fall through to hardcoded

    # Stage 2: Fallback to hardcoded constants
    if program_type == 'fentanyl':
        return {
            'code': IEEPA_CODES['fentanyl']['code'],  # '9903.01.24'
            'rate': IEEPA_CODES['fentanyl']['rate'],  # 0.10
            'source': 'hardcoded',
        }
    elif program_type == 'reciprocal':
        variant_key = variant or 'standard'
        return {
            'code': IEEPA_CODES['reciprocal'][variant_key]['code'],
            'rate': IEEPA_CODES['reciprocal'][variant_key]['rate'],
            'source': 'hardcoded',
        }
```

### 7.2 Usage in build_entry_stack()

```python
@tool
def build_entry_stack(hts_code: str, country: str, import_date: str = None, ...):
    """Build complete tariff stack for an import."""

    # Normalize country code
    normalized = normalize_country(country)
    country_iso2 = normalized.get("iso_alpha2")

    # For IEEPA Fentanyl: Use temporal lookup
    if program_id == "ieepa_fentanyl":
        fentanyl_rate = get_ieepa_rate_temporal(
            program_type='fentanyl',
            country_code=country_iso2,
            as_of_date=import_date  # Historical lookup!
        )
        chapter_99_code = fentanyl_rate['code']
        duty_rate = fentanyl_rate['rate']

    # For Section 232: Temporal lookup via check_program_inclusion
    elif program_id.startswith("section_232_"):
        inclusion_result = check_program_inclusion.invoke({
            "program_id": program_id,
            "hts_code": hts_code,
            "as_of_date": import_date,  # Pass date for temporal lookup
        })
```

### 7.3 Example Query

**User Question:** "What are the duties on HTS 7215.50.00 (steel wire) from China imported on February 15, 2025?"

**System Lookup:**

```python
# Section 301
rate_301 = Section301Rate.get_rate_as_of('72155000', date(2025, 2, 15))
# Returns: 25% (List 3)

# Section 232 Steel
rate_232 = Section232Rate.get_rate_as_of(
    hts_8digit='72155000',
    material='steel',
    country_code=None,  # Global rate
    as_of_date=date(2025, 2, 15)
)
# Returns: 25% (BEFORE March 2025 increase to 50%!)

# IEEPA Fentanyl
rate_ieepa = IeepaRate.get_rate_as_of(
    program_type='fentanyl',
    country_code='CN',
    as_of_date=date(2025, 2, 15)
)
# Returns: 10% (EO 14195 original rate)

# IEEPA Reciprocal: Not applicable (started April 2025)
```

**Result:**
- Base Rate: 0%
- Section 301: 25%
- Section 232 Steel: 25% (historical, not 50%)
- IEEPA Fentanyl: 10%
- **Total Additional Duties: 60%**

---

## 8. Cron and Scheduling

### 8.1 Manual Execution

```bash
# Poll Federal Register for new documents (default: last 7 days)
pipenv run python scripts/run_watchers.py

# Poll with specific date range
pipenv run python scripts/run_watchers.py --source federal_register --since 2026-01-01

# Poll all sources
pipenv run python scripts/run_watchers.py --all

# Dry run (discover but don't queue)
pipenv run python scripts/run_watchers.py --dry-run

# Process queued documents (default: 50 jobs)
pipenv run python scripts/process_ingest_queue.py

# Process limited number
pipenv run python scripts/process_ingest_queue.py --max-jobs 10

# Run in daemon mode (continuous processing)
pipenv run python scripts/process_ingest_queue.py --daemon --interval 60
```

### 8.2 Cron Configuration

**Linux/macOS Cron (every 6 hours):**
```cron
# Poll watchers every 6 hours
0 */6 * * * cd /path/to/lanes && pipenv run python scripts/run_watchers.py --all >> /var/log/watchers.log 2>&1

# Process queue every hour
0 * * * * cd /path/to/lanes && pipenv run python scripts/process_ingest_queue.py --max-jobs 50 >> /var/log/ingest.log 2>&1
```

### 8.3 Railway Scheduler

**railway.toml:**
```toml
[deploy]
startCommand = "pipenv run gunicorn -w 4 -b 0.0.0.0:$PORT 'app.web:create_app()'"

[cron.watchers]
schedule = "0 */6 * * *"
command = "pipenv run python scripts/run_watchers.py --all"

[cron.ingest]
schedule = "0 * * * *"
command = "pipenv run python scripts/process_ingest_queue.py"
```

### 8.4 Systemd Service (Linux)

```ini
# /etc/systemd/system/tariff-ingest.service
[Unit]
Description=Tariff Document Ingestion Daemon
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/lanes
ExecStart=/opt/lanes/.venv/bin/python scripts/process_ingest_queue.py --daemon --interval 300
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 9. Data Flow Diagrams

### 9.1 Complete Pipeline Flow

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE DATA FLOW                                  │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ PHASE 1: DISCOVERY (run_watchers.py)                                 │ │
│  ├──────────────────────────────────────────────────────────────────────┤ │
│  │                                                                      │ │
│  │  FederalRegisterWatcher.poll(since_date)                            │ │
│  │     │                                                                │ │
│  │     ▼                                                                │ │
│  │  HTTP GET https://www.federalregister.gov/api/v1/documents.json     │ │
│  │  ?conditions[term]="Section 301"&conditions[publication_date][gte]= │ │
│  │     │                                                                │ │
│  │     ▼                                                                │ │
│  │  DiscoveredDocument[]                                               │ │
│  │  ├─ external_id: "2026-00206"                                       │ │
│  │  ├─ xml_url: "https://www.govinfo.gov/.../2026-00206.xml"          │ │
│  │  ├─ title: "Notice of Modification..."                              │ │
│  │  └─ publication_date: "2026-01-10"                                  │ │
│  │     │                                                                │ │
│  │     ▼                                                                │ │
│  │  enqueue_discovered_documents(run_id, documents)                    │ │
│  │     │                                                                │ │
│  │     ▼                                                                │ │
│  │  IngestJob (status="queued")                                        │ │
│  │  RegulatoryRunDocument (status="discovered")                        │ │
│  │                                                                      │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                 │                                          │
│                                 ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ PHASE 2: PROCESSING (process_ingest_queue.py)                        │ │
│  ├──────────────────────────────────────────────────────────────────────┤ │
│  │                                                                      │ │
│  │  IngestJob.claim_next()  ←─ FOR UPDATE SKIP LOCKED (Postgres)       │ │
│  │     │                                                                │ │
│  │     ▼                                                                │ │
│  │  ┌────────────────┐                                                  │ │
│  │  │  FETCH STAGE   │                                                  │ │
│  │  │                │                                                  │ │
│  │  │  HTTP GET xml_url                                                │ │
│  │  │  SHA256 hash                                                     │ │
│  │  │  Store raw_bytes                                                 │ │
│  │  └───────┬────────┘                                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  OfficialDocument                                                   │ │
│  │  ├─ raw_bytes: <4274 bytes XML>                                     │ │
│  │  ├─ content_hash: "db6445324d65..."                                 │ │
│  │  ├─ content_type: "text/xml"                                        │ │
│  │  └─ status: "fetched"                                               │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  ┌────────────────┐                                                  │ │
│  │  │  RENDER STAGE  │                                                  │ │
│  │  │                │                                                  │ │
│  │  │  Parse XML:    │                                                  │ │
│  │  │  - Extract <P>, <FP>, <HD>, <GPOTABLE>                           │ │
│  │  │  - Add line numbers                                              │ │
│  │  │  - Mark sections (=== HEADING ===)                               │ │
│  │  └───────┬────────┘                                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  doc.canonical_text =                                               │ │
│  │  """                                                                 │ │
│  │  L0001: === DEPARTMENT OF COMMERCE ===                              │ │
│  │  L0002: International Trade Administration                          │ │
│  │  L0003:                                                             │ │
│  │  L0004: Notice of Modification of Section 301 Tariffs               │ │
│  │  ...                                                                 │ │
│  │  L0047: === EFFECTIVE DATE ===                                      │ │
│  │  L0048: This rule is effective January 1, 2026                      │ │
│  │  """                                                                 │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  ┌────────────────┐                                                  │ │
│  │  │  CHUNK STAGE   │                                                  │ │
│  │  │                │                                                  │ │
│  │  │  Split by headings                                               │ │
│  │  │  Target: 500 tokens                                              │ │
│  │  │  Track: line_start, line_end                                     │ │
│  │  └───────┬────────┘                                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  DocumentChunk[]                                                    │ │
│  │  ├─ chunk_index: 0                                                  │ │
│  │  │  ├─ text: "L0001: === DEPARTMENT OF COMMERCE ===..."             │ │
│  │  │  ├─ line_start: 1, line_end: 23                                  │ │
│  │  │  ├─ chunk_type: "narrative"                                      │ │
│  │  │  └─ section_heading: "DEPARTMENT OF COMMERCE"                    │ │
│  │  ├─ chunk_index: 1                                                  │ │
│  │  │  ├─ text: "L0024: === TARIFF SCHEDULE ===..."                    │ │
│  │  │  ├─ chunk_type: "table"                                          │ │
│  │  │  └─ ...                                                           │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  ┌────────────────┐                                                  │ │
│  │  │ EXTRACT STAGE  │                                                  │ │
│  │  │                │                                                  │ │
│  │  │  Method 1: XML Table Parsing                                     │ │
│  │  │  - Parse <GPOTABLE> elements                                     │ │
│  │  │  - Extract HTS from <ROW><ENT>8544.42.90</ENT>                   │ │
│  │  │  - Parse rates, effective dates                                  │ │
│  │  │  - Resolve Chapter 99 codes                                      │ │
│  │  │                                                                  │ │
│  │  │  Method 2: LLM RAG                                               │ │
│  │  │  - Send chunks to GPT-4                                          │ │
│  │  │  - TARIFF_EXTRACTION_PROMPT                                      │ │
│  │  │  - Parse JSON response                                           │ │
│  │  └───────┬────────┘                                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  CandidateChange[]                                                  │ │
│  │  ├─ hts_code: "8544.42.90"                                          │ │
│  │  ├─ new_chapter_99_code: "9903.88.03"                               │ │
│  │  ├─ rate: 0.25                                                      │ │
│  │  ├─ effective_date: "2026-01-01"                                    │ │
│  │  ├─ program: "section_301"                                          │ │
│  │  ├─ evidence_quote: "HTS 8544.42.90... 25 percent..."               │ │
│  │  ├─ evidence_line_start: 47                                         │ │
│  │  └─ extraction_method: "xml_table"                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  ┌────────────────┐                                                  │ │
│  │  │ VALIDATE STAGE │                                                  │ │
│  │  │                │                                                  │ │
│  │  │  Verify HTS appears in text ✓                                    │ │
│  │  │  Verify Chapter 99 appears ✓                                     │ │
│  │  │  Verify rate appears ✓                                           │ │
│  │  │  Find evidence quote ✓                                           │ │
│  │  └───────┬────────┘                                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  ValidationResult                                                   │ │
│  │  ├─ is_valid: true                                                  │ │
│  │  ├─ confidence: 1.0  (XML table = deterministic)                    │ │
│  │  └─ reason: null                                                    │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  ┌────────────────┐                                                  │ │
│  │  │  COMMIT STAGE  │                                                  │ │
│  │  │                │                                                  │ │
│  │  │  1. WriteGate approval                                           │ │
│  │  │  2. Find existing active rate                                    │ │
│  │  │  3. Close old rate (effective_end)                               │ │
│  │  │  4. Insert new rate (supersedes_id)                              │ │
│  │  │  5. Write TariffAuditLog                                         │ │
│  │  │  6. Write RegulatoryRunChange                                    │ │
│  │  └───────┬────────┘                                                  │ │
│  │          │                                                           │ │
│  │          ▼                                                           │ │
│  │  section_301_rates (NEW ROW)                                        │ │
│  │  ├─ hts_8digit: "85444290"                                          │ │
│  │  ├─ chapter_99_code: "9903.88.03"                                   │ │
│  │  ├─ duty_rate: 0.2500                                               │ │
│  │  ├─ effective_start: 2026-01-01                                     │ │
│  │  ├─ effective_end: NULL (active)                                    │ │
│  │  ├─ supersedes_id: 12345 (previous rate)                            │ │
│  │  └─ source_doc: "doc-uuid-here"                                     │ │
│  │                                                                      │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                 │                                          │
│                                 ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ PHASE 3: QUERY (stacking_tools.py)                                   │ │
│  ├──────────────────────────────────────────────────────────────────────┤ │
│  │                                                                      │ │
│  │  User: "What's the duty on 8544.42.90 from China on 2025-02-15?"    │ │
│  │                                                                      │ │
│  │  Section301Rate.get_rate_as_of('85444290', date(2025, 2, 15))       │ │
│  │     → 25% (9903.88.03, List 3)                                      │ │
│  │                                                                      │ │
│  │  Section232Rate.get_rate_as_of('85444290', 'copper', None,          │ │
│  │                                 date(2025, 2, 15))                   │ │
│  │     → 50% (9903.78.01)                                              │ │
│  │                                                                      │ │
│  │  IeepaRate.get_rate_as_of('fentanyl', 'CN', date(2025, 2, 15))      │ │
│  │     → 10% (9903.01.24, EO 14195)                                    │ │
│  │                                                                      │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Supersession Chain Visualization

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TEMPORAL SUPERSESSION CHAIN                               │
│                    (Section 232 Steel Rate History)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Timeline: ────────────────────────────────────────────────────────────▶   │
│            2018        2020        2022        2024    2025-03-12           │
│                                                            │                │
│  ┌──────────────────────────────────────────────────────┐  │                │
│  │ Section232Rate #1                                     │  │                │
│  │ ├─ hts_8digit: "72081000"                            │  │                │
│  │ ├─ material_type: "steel"                            │  │                │
│  │ ├─ duty_rate: 0.25 (25%)                             │  │                │
│  │ ├─ effective_start: 2018-03-23                       │  │                │
│  │ ├─ effective_end: 2025-03-11  ◄────────────────────────┤                │
│  │ ├─ supersedes_id: NULL                               │  │                │
│  │ ├─ superseded_by_id: #2 ───────────────────────────────┼───┐            │
│  │ └─ source_doc: "Proclamation 9705"                   │  │   │            │
│  └──────────────────────────────────────────────────────┘  │   │            │
│                                                            │   │            │
│                                                            ▼   │            │
│                                              ┌──────────────────────────┐   │
│                                              │ Section232Rate #2        │   │
│                                              │ ├─ hts_8digit: "72081000"│   │
│                                              │ ├─ duty_rate: 0.50 (50%) │   │
│                                              │ ├─ effective_start:      │   │
│                                              │ │     2025-03-12         │   │
│                                              │ ├─ effective_end: NULL   │   │
│                                              │ │     (ACTIVE)           │   │
│                                              │ ├─ supersedes_id: #1 ◄───┘   │
│                                              │ ├─ superseded_by_id: NULL    │
│                                              │ └─ source_doc:              │
│                                              │     "Proclamation 10896"    │
│                                              └──────────────────────────┘   │
│                                                                             │
│  Query: get_rate_as_of('72081000', 'steel', None, date(2025, 2, 15))       │
│  Result: Rate #1 (25%) ← effective_start <= 2025-02-15 <= effective_end    │
│                                                                             │
│  Query: get_rate_as_of('72081000', 'steel', None, date(2025, 4, 15))       │
│  Result: Rate #2 (50%) ← effective_start <= 2025-04-15, effective_end=NULL │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Database Schema Reference

### 10.1 Core Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `ingest_jobs` | Processing queue | source, external_id, status, content_hash |
| `official_documents` | Stored documents | raw_bytes, canonical_text, content_hash |
| `document_chunks` | RAG chunks | document_id, text, line_start, line_end |
| `section_301_rates` | Section 301 rates (temporal) | hts_8digit, duty_rate, effective_start/end |
| `section_232_rates` | Section 232 rates (temporal) | hts_8digit, material_type, effective_start/end |
| `ieepa_rates` | IEEPA rates (temporal) | program_type, country_code, effective_start/end |
| `section_232_materials` | Static HTS→material map | hts_8digit, material, claim_code |
| `tariff_audit_log` | Audit trail | table_name, record_id, action, old/new_values |
| `regulatory_runs` | Batch runs | trigger, status, summary_counts |
| `evidence_packets` | Evidence links | document_id, quote_text, line_start/end |

### 10.2 Indexes for Temporal Queries

```sql
-- Section 301
CREATE INDEX idx_301_rates_hts_date
ON section_301_rates (hts_8digit, effective_start, effective_end);

-- Section 232
CREATE INDEX idx_232_rates_hts_date
ON section_232_rates (hts_8digit, effective_start, effective_end);

-- IEEPA
CREATE INDEX idx_ieepa_rates_date
ON ieepa_rates (program_type, effective_start, effective_end);
```

---

## 11. Operational Commands

### 11.1 Discovery and Ingestion

```bash
# Poll Federal Register for new documents
pipenv run python scripts/run_watchers.py --source federal_register

# Poll all sources
pipenv run python scripts/run_watchers.py --all

# Poll with custom date range
pipenv run python scripts/run_watchers.py --since 2026-01-01

# Dry run (discover but don't queue)
pipenv run python scripts/run_watchers.py --dry-run

# Process queued documents
pipenv run python scripts/process_ingest_queue.py

# Process with limit
pipenv run python scripts/process_ingest_queue.py --max-jobs 10

# Run in daemon mode
pipenv run python scripts/process_ingest_queue.py --daemon --interval 60

# Reprocess failed jobs
pipenv run python scripts/process_ingest_queue.py --reprocess
```

### 11.2 Data Population

```bash
# Populate all tariff tables (including temporal)
pipenv run python scripts/populate_tariff_tables.py

# Reset and repopulate
pipenv run python scripts/populate_tariff_tables.py --reset

# Migrate Section 232 to temporal (standalone)
pipenv run python scripts/migrate_232_to_temporal.py

# Migrate IEEPA to temporal (standalone)
pipenv run python scripts/migrate_ieepa_to_temporal.py
```

### 11.3 Testing Temporal Queries

```bash
# Run temporal query tests
pipenv run pytest tests/test_temporal_queries.py -v

# Verify temporal data manually
pipenv run python -c "
from datetime import date
from app.web import create_app
from app.web.db.models.tariff_tables import Section232Rate, IeepaRate

app = create_app()
with app.app_context():
    # Steel rate in Feb 2025 (before increase)
    rate = Section232Rate.get_rate_as_of('72081000', 'steel', None, date(2025, 2, 15))
    print(f'Steel Feb 2025: {rate.duty_rate}')  # 0.25 (25%)

    # Steel rate in Apr 2025 (after increase)
    rate = Section232Rate.get_rate_as_of('72081000', 'steel', None, date(2025, 4, 15))
    print(f'Steel Apr 2025: {rate.duty_rate}')  # 0.50 (50%)

    # Fentanyl rate in Sep 2025 (doubled period)
    rate = IeepaRate.get_rate_as_of('fentanyl', 'CN', date(2025, 9, 1))
    print(f'Fentanyl Sep 2025: {rate.duty_rate}')  # 0.20 (20%)
"
```

### 11.4 Monitoring

```bash
# Check queue depth
pipenv run python -c "
from app.web import create_app
from app.models import IngestJob

app = create_app()
with app.app_context():
    queued = IngestJob.query.filter_by(status='queued').count()
    failed = IngestJob.query.filter_by(status='failed').count()
    print(f'Queued: {queued}, Failed: {failed}')
"

# Check temporal table counts
pipenv run python -c "
from app.web import create_app
from app.web.db.models.tariff_tables import Section301Rate, Section232Rate, IeepaRate

app = create_app()
with app.app_context():
    print(f'section_301_rates: {Section301Rate.query.count()} rows')
    print(f'section_232_rates: {Section232Rate.query.count()} rows')
    print(f'ieepa_rates: {IeepaRate.query.count()} rows')
"
```

---

## Summary

The Unified Temporal Tariff Pipeline provides:

1. **Complete Discovery** - Watchers poll Federal Register, CBP CSMS, and USITC
2. **Robust Ingestion** - 6-stage pipeline handles PDF, XML, HTML, DOCX
3. **Dual Extraction** - Deterministic XML parsing + LLM RAG for comprehensive coverage
4. **Temporal Storage** - All rates tracked with effective_start/effective_end dates
5. **Full Audit Trail** - Every change linked to source document with evidence
6. **Historical Queries** - `get_rate_as_of(hts_code, date)` returns rate for any date
7. **Graceful Fallback** - Temporal → Static → Hardcoded for backwards compatibility

**Files Modified for v13.0 Temporal Unification:**
- `app/web/db/models/tariff_tables.py` - Section232Rate, IeepaRate models
- `app/chat/tools/stacking_tools.py` - get_ieepa_rate_temporal(), temporal lookups
- `scripts/populate_tariff_tables.py` - populate_section_232_temporal(), populate_ieepa_temporal()
- `scripts/migrate_232_to_temporal.py` - Standalone migration script
- `scripts/migrate_ieepa_to_temporal.py` - Standalone migration script
- `tests/test_temporal_queries.py` - Temporal query test cases


# =======+>

Asked later, and led to this:

 Tariff System Data Flow Documentation

     Date: January 12, 2026
     Purpose: Document how data flows in the tariff calculation system
     Status: DOCUMENTATION COMPLETE

     ---
     Part 1: HTS Lookup Flow (User Query)

     When User Enters an HTS Code

     User Input: HTS 8302.41.6015, Country: China
                         ↓
     ┌─────────────────────────────────────────┐
     │  POST /tariff/calculate                 │
     │  app/web/views/tariff_views.py          │
     └─────────────────────────────────────────┘
                         ↓
     ┌─────────────────────────────────────────┐
     │  StackingRAG.calculate_stacking()       │
     │  app/chat/graphs/stacking_rag.py        │
     └─────────────────────────────────────────┘
                         ↓
              ┌─────────┴─────────┐
              ↓                   ↓
     ┌─────────────────┐ ┌─────────────────┐
     │ Section 301     │ │ Section 232     │
     │ (China tariffs) │ │ (metals)        │
     └─────────────────┘ └─────────────────┘
              ↓                   ↓
        TEMPORAL FIRST      TEMPORAL FIRST
              ↓                   ↓
     ┌─────────────────┐ ┌─────────────────┐
     │section_301_rates│ │section_232_rates│
     │ 10,394 rows ✓   │ │ 1,596 rows ✓    │
     └─────────────────┘ └─────────────────┘
              ↓ fallback          ↓ fallback
     ┌─────────────────┐ ┌─────────────────┐
     │section_301_     │ │section_232_     │
     │inclusions       │ │materials        │
     │ 10,407 rows ✓   │ │ 838 rows ✓      │
     └─────────────────┘ └─────────────────┘

     Lookup Priority

     | Program     | Table 1 (Temporal) | Table 2 (Static Fallback) |
     |-------------|--------------------|---------------------------|
     | Section 301 | section_301_rates  | section_301_inclusions    |
     | Section 232 | section_232_rates  | section_232_materials     |
     | IEEPA       | ieepa_rates        | program_codes             |

     ---
     Part 2: Update Flow (New Notices)

     How New Tariff Notices Get Into the System

     Phase 1: Notice Published (External)

     CBP publishes: CSMS#65794272 "Steel tariff scope expanded"
     Federal Register publishes: 90 FR 12345 "Section 301 modifications"

     Phase 2: Watcher Detection

     Location: app/watchers/

     | Watcher                | Source              | Polling Interval |
     |------------------------|---------------------|------------------|
     | CBPCSMSWatcher         | cbp.gov/csms        | Every 12 hours   |
     | FederalRegisterWatcher | federalregister.gov | Every 6 hours    |
     | USITCWatcher           | hts.usitc.gov       | On demand        |

     Detection Logic:
     - Scan for keywords: "section 232", "301", "tariff", "9903"
     - Extract: CSMS#, effective dates, HTS code patterns
     - Return: DiscoveredDocument with metadata

     Phase 3: Trusted Extraction

     Location: app/ingestion/connectors/

     | Connector        | Trusted Domains                  | Tier |
     |------------------|----------------------------------|------|
     | CSMSConnector    | content.govdelivery.com, cbp.gov | A    |
     | GovInfoConnector | federalregister.gov, govinfo.gov | A    |
     | USITCConnector   | hts.usitc.gov                    | A    |

     Extraction Output:
     ConnectorResult(
         document_id=uuid,
         source="CSMS",
         canonical_id="CSMS#65794272",
         extracted_text="Clean text from HTML...",
         sha256_raw="abc123...",           # Change detection
         hts_codes_found=["8544.42.90"],   # Regex extracted
         programs_found=["section_232_steel"],
         effective_start=date(2026, 1, 15)
     )

     Phase 4: Database Storage

     Location: app/web/db/models/document.py

     documents table:
     ├─ id: uuid
     ├─ source: "CSMS"
     ├─ canonical_id: "CSMS#65794272"
     ├─ extracted_text: "Full clean text..."
     ├─ sha256_raw: "abc123..."
     ├─ hts_codes_mentioned: ["8544.42.90"]
     └─ published_at, effective_start

     Phase 5: Chunking for RAG

     Location: app/ingestion/chunker.py

     DocumentChunker(
         min_chunk_size=200,    # Avoid tiny fragments
         max_chunk_size=1200,   # Fit in context window
         overlap=50,            # Maintain continuity
         strategy="paragraph"   # Split by paragraphs
     )

     Output:
     document_chunks table:
     ├─ chunk_index: 0, 1, 2...
     ├─ text: "200-1200 char chunk"
     ├─ char_start, char_end: Position in original
     ├─ text_hash: SHA-256 for dedup
     └─ embedding_id: Pinecone vector ID

     Phase 6: Vector Embedding

     Location: app/chat/vector_stores/tariff_search.py

     Chunk text → OpenAI embedding (1536 dim) → Pinecone

     Pinecone Metadata:
     {
       "chunk_type": "evidence_quote",
       "hts_code": "8544.42.90",
       "program": "section_232_steel",
       "source": "CSMS",
       "canonical_id": "CSMS#65794272",
       "chunk_text": "HTS 8544..."
     }

     Phase 7: RAG Lookup (Three-Tier Cache)

     Location: app/chat/vector_stores/tariff_search.py

     User asks: "Is HTS 8544.42.90 in scope for 232?"
                         ↓
     ┌─────────────────────────────────────────┐
     │ TIER 1: PostgreSQL (Verified Assertions)│
     │ SELECT * FROM verified_assertions       │
     │ WHERE hts_code='8544.42.90'            │
     │ → If found: Return immediately          │
     └─────────────────────────────────────────┘
                         ↓ if not found
     ┌─────────────────────────────────────────┐
     │ TIER 2: Pinecone (Semantic Cache)       │
     │ Vector search with metadata filters     │
     │ → If good match: Return cached answer   │
     └─────────────────────────────────────────┘
                         ↓ if not found
     ┌─────────────────────────────────────────┐
     │ TIER 3: Gemini (Live Search)            │
     │ Call Gemini with Google Search grounding│
     │ → Store result in cache for next time   │
     └─────────────────────────────────────────┘

     ---
     Part 3: Complete Flow Diagram

     ┌─────────────────────────────────────────────────────────────────┐
     │                    EXTERNAL SOURCES                             │
     │  CBP CSMS | Federal Register | USITC | White House             │
     └────────────────────────┬────────────────────────────────────────┘
                              │
                              ↓
     ┌─────────────────────────────────────────────────────────────────┐
     │  WATCHERS (app/watchers/)                                       │
     │  Poll every 6-12 hours, detect new notices                      │
     └────────────────────────┬────────────────────────────────────────┘
                              │
                              ↓
     ┌─────────────────────────────────────────────────────────────────┐
     │  CONNECTORS (app/ingestion/connectors/)                         │
     │  Tier-A trusted fetch, extract HTS codes & dates                │
     └────────────────────────┬────────────────────────────────────────┘
                              │
                              ↓
     ┌─────────────────────────────────────────────────────────────────┐
     │  DOCUMENTS TABLE (app/web/db/models/document.py)                │
     │  Store full text + metadata + SHA-256 hash                      │
     └────────────────────────┬────────────────────────────────────────┘
                              │
                              ↓
     ┌─────────────────────────────────────────────────────────────────┐
     │  CHUNKER (app/ingestion/chunker.py)                             │
     │  Split into 200-1200 char chunks with overlap                   │
     └────────────────────────┬────────────────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ↓                             ↓
     ┌─────────────────────┐      ┌─────────────────────┐
     │  DOCUMENT_CHUNKS    │      │  PINECONE VECTORS   │
     │  PostgreSQL table   │      │  1536-dim embeddings│
     │  (text positions)   │      │  (semantic search)  │
     └─────────────────────┘      └─────────────────────┘
               │                             │
               └──────────────┬──────────────┘
                              ↓
     ┌─────────────────────────────────────────────────────────────────┐
     │  TEMPORAL RATE TABLES (app/web/db/models/tariff_tables.py)      │
     │  section_301_rates | section_232_rates | ieepa_rates            │
     │  (Manual import via scripts/populate_tariff_tables.py)          │
     └────────────────────────┬────────────────────────────────────────┘
                              │
                              ↓
     ┌─────────────────────────────────────────────────────────────────┐
     │  USER QUERY: "Calculate tariff for HTS 8544.42.90, China"       │
     │                                                                 │
     │  1. Temporal tables → section_301_rates (10,394 rows)           │
     │  2. Static fallback → section_301_inclusions (10,407 rows)      │
     │  3. RAG for verification → Pinecone + Gemini                    │
     └─────────────────────────────────────────────────────────────────┘

     ---
     Part 4: Current Implementation Status

     What's Working Now

     | Component         | Status        | Notes                             |
     |-------------------|---------------|-----------------------------------|
     | Watchers          | ✓ Implemented | CBP CSMS, Federal Register, USITC |
     | Connectors        | ✓ Implemented | Tier-A trusted extraction         |
     | Document storage  | ✓ Implemented | Full audit trail                  |
     | Chunker           | ✓ Implemented | Paragraph-based, 200-1200 chars   |
     | Pinecone vectors  | ✓ Implemented | Two indices (docs, tariff-search) |
     | Temporal tables   | ✓ Populated   | 301=10,394, 232=1,596, IEEPA=45   |
     | RAG 3-tier lookup | ✓ Implemented | PostgreSQL → Pinecone → Gemini    |

     What's Manual vs Automatic

     | Process           | Current State  | Future State         |
     |-------------------|----------------|----------------------|
     | Watcher polling   | Manual trigger | Scheduled (Celery)   |
     | Data extraction   | Manual trigger | Auto on detection    |
     | Rate table update | Manual script  | Auto with Write Gate |
     | Vector indexing   | Manual trigger | Auto on new chunks   |

     ---
     Part 5: Key Files Reference

     | File                                    | Purpose                    |
     |-----------------------------------------|----------------------------|
     | app/watchers/cbp_csms.py                | Monitor CBP CSMS bulletins |
     | app/watchers/federal_register.py        | Monitor Federal Register   |
     | app/watchers/usitc.py                   | Monitor USITC HTS updates  |
     | app/ingestion/connectors/csms.py        | Extract from CSMS          |
     | app/ingestion/chunker.py                | Split docs into chunks     |
     | app/chat/vector_stores/tariff_search.py | Pinecone integration       |
     | app/web/db/models/document.py           | Document/chunk models      |
     | app/web/db/models/tariff_tables.py      | Rate table models          |
     | scripts/populate_tariff_tables.py       | Import CSV to tables       |

     ---
     Summary

     Q: How do updates happen when new notices come up?

     A: The pipeline is:
     1. Watchers poll official sources every 6-12 hours
     2. Connectors fetch and extract from Tier-A trusted domains
     3. Documents stored with full audit trail + SHA-256 hash
     4. Chunks created for RAG retrieval (200-1200 chars)
     5. Vectors embedded in Pinecone for semantic search
     6. Rate tables updated (currently manual via populate script)

     Q: How does RAG use this data?

     A: Three-tier lookup:
     1. PostgreSQL - Verified assertions (fastest, highest trust)
     2. Pinecone - Semantic cache (avoid repeat API calls)
     3. Gemini - Live search with Google grounding (last resort)

     Q: Is it automatic?

     A: Currently semi-automatic:
     - Watchers/connectors/chunkers are implemented
     - Rate table updates require manual script run
     - Future: Write Gate will enable fully automated updates

⏺ Documentation complete. Here's the key takeaway:

  Summary: Your Two Questions Answered

  1. User Query: "Will it work for all HTS codes now?"

  YES - Temporal tables are populated:
  - section_301_rates: 10,394 rows
  - section_232_rates: 1,596 rows
  - ieepa_rates: 45 rows

  2. Updates: "How do new notices get into the system?"

  Current State: Semi-Automatic

  Notice Published (CBP/FR/USITC)
          ↓
     ✓ Watcher detects
          ↓
     ✓ Connector extracts
          ↓
     ✓ Chunks → Pinecone (RAG works!)
          ↓
     ❌ Rate tables → MANUAL script

  The Gap: When a new CSMS comes out, RAG can find and answer questions about it, but the actual duty calculation tables need manual update via pipenv run python 
  scripts/populate_tariff_tables.py.

  Future: Write Gate will close this gap by auto-inserting validated HTS codes into temporal tables.
  
  
  # =====>
  
  ❌ Rate tables → MANUAL script --> yes we should automate it right. as soon as there is any change? or something. like rate is calculated or it is manual what is the meaning of that? 

⏺ Great question! Let me clarify what's manual vs automated:

  Current State: What's "Manual"?

  When a new CSMS notice comes out (e.g., "New HTS codes added to Section 232"):

  | Step                  | Current State | What It Means                          |
  |-----------------------|---------------|----------------------------------------|
  | 1. Detect notice      | ✓ Automated   | Watcher finds new CSMS                 |
  | 2. Extract HTS codes  | ✓ Automated   | Connector parses text                  |
  | 3. Store in documents | ✓ Automated   | Database gets full text                |
  | 4. Chunk for RAG      | ✓ Automated   | Pinecone gets vectors                  |
  | 5. Update rate tables | ❌ Manual      | Someone runs populate_tariff_tables.py |

  "Manual" means: A human must run a Python script to insert the new HTS codes into the temporal rate tables that drive the actual duty calculation.

  Why Is This a Problem?

  Day 1: CBP publishes CSMS "HTS 9999.99.99 now in Section 232 scope"
          ↓
  Day 1: RAG knows about it (can answer "Is 9999.99.99 in scope?" → YES)
          ↓
  Day 1: BUT duty calculation says "No 232 rate found" ❌
          (because section_232_rates table wasn't updated)
          ↓
  Day ?: Someone manually runs script → NOW calculation works ✓

  What Should Be Automated?

  CURRENT (Semi-Auto):
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │   Watcher   │ →  │  Connector  │ →  │   RAG Only  │
  │  (auto)     │    │  (auto)     │    │  (works)    │
  └─────────────┘    └─────────────┘    └─────────────┘
                                                ↓
                                        Rate tables: ❌ Manual

  IDEAL (Full Auto):
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │   Watcher   │ →  │  Connector  │ →  │ Write Gate  │ →  │ Rate Tables │
  │  (auto)     │    │  (auto)     │    │  (validate) │    │  (auto!)    │
  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘

  The Missing Piece: Write Gate

  The Write Gate would:

  1. Take extracted HTS codes from connectors
  2. Validate against source (is this really from CBP? Is the quote accurate?)
  3. Auto-insert into temporal tables (section_301_rates, section_232_rates, etc.)
  4. Track provenance (which notice added this code?)

  # CONCEPTUAL - What Write Gate would do:
  def process_new_notice(notice):
      # 1. Extract HTS codes from notice
      hts_codes = extract_hts_codes(notice.text)

      # 2. Validate each code
      for hts in hts_codes:
          if validate_against_source(hts, notice.url):
              # 3. Auto-insert into rate table
              Section301Rate.create(
                  hts_8digit=hts,
                  chapter_99_code=notice.chapter_99_code,
                  duty_rate=notice.rate,
                  effective_start=notice.effective_date,
                  source_doc=notice.canonical_id  # Audit trail
              )

      # 4. No human intervention needed!

  Should We Build This?

  Yes, but with safeguards:

  | Approach           | Risk             | Benefit           |
  |--------------------|------------------|-------------------|
  | Fully automatic    | Bad data gets in | Zero delay        |
  | Human review queue | Delay            | Verified accuracy |
  | Auto + alerts      | Some risk        | Fast + auditable  |

  Recommended: Auto-insert with human review queue for edge cases

  Would you like me to implement the Write Gate automation? This would:
  1. Connect watcher → connector → rate table insert
  2. Add a needs_review_queue for uncertain extractions
  3. Enable real-time rate table updates when notices come out


