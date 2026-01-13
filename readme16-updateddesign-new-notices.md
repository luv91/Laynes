# Regulatory Update Pipeline - Complete Design Document

**Date:** January 10, 2026
**Version:** 1.0
**Scope:** China-focused tariff programs (Section 301, Section 232, IEEPA Fentanyl, IEEPA Reciprocal)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Current System Architecture](#3-current-system-architecture)
4. [Target System Architecture](#4-target-system-architecture)
5. [Component Design](#5-component-design)
6. [Database Schema Changes](#6-database-schema-changes)
7. [Watcher Implementation](#7-watcher-implementation)
8. [Document Processing Pipeline](#8-document-processing-pipeline)
9. [RAG Extraction & Validation](#9-rag-extraction--validation)
10. [Integration with Existing System](#10-integration-with-existing-system)
11. [File Structure](#11-file-structure)
12. [Implementation Phases](#12-implementation-phases)
13. [API Reference](#13-api-reference)

---

## 1. Executive Summary

### The Problem
The current system uses **static data imports** from 2018-2020 Federal Register notices. When USTR published the **September 2024 Four-Year Review** with new rates effective January 2026, our system had no mechanism to detect or ingest these changes.

**Example:** HTS 6307.90.98 (facemasks)
- Our DB returns: `9903.88.15 @ 7.5%` (List 4A, 2020 rate)
- Reality as of Jan 2026: `9903.91.07 @ 50%` (Strategic Sector, 2024 review)

### The Solution
Build a **Regulatory Update Pipeline** that:
1. **WATCHES** official sources (Federal Register, CBP, USITC)
2. **FETCHES** new documents with full audit trail
3. **EXTRACTS** changes using RAG + LLM
4. **VALIDATES** extractions against source text
5. **COMMITS** to temporal database with evidence

### Scope (China Focus)
| Program | Source | Update Frequency |
|---------|--------|------------------|
| Section 301 | Federal Register, USTR | Monthly+ |
| Section 232 (Steel/Aluminum/Copper) | CBP CSMS, Federal Register | Quarterly |
| IEEPA Fentanyl | Federal Register, EO | Rare |
| IEEPA Reciprocal | Federal Register, EO | Rare |
| MFN Base Rates | USITC HTS | Annually + updates |

---

## 2. Problem Statement

### Why We Missed the January 2026 Update

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CURRENT SYSTEM (Static)                                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  2018-2020 FR PDFs ──► One-time Parse ──► Static DB ──► Answer         │
│                                                                         │
│  ❌ No detection of new notices                                         │
│  ❌ No ingestion pipeline                                               │
│  ❌ No temporal rate tracking                                           │
│  ❌ No freshness warnings                                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### What Changed (Sept 2024 Four-Year Review)

| Sector | HTS Examples | Old Rate | 2025 Rate | 2026 Rate | New Ch.99 |
|--------|--------------|----------|-----------|-----------|-----------|
| **Medical** | 6307.90.98xx (facemasks) | 7.5% | 25% | **50%** | 9903.91.07 |
| **Semiconductors** | 8541.xx, 8542.xx | 25% | 50% | 50% | 9903.91.01-02 |
| **EVs** | 8703.60, 8703.80 | 25% | 100% | 100% | 9903.91.20 |
| **Batteries** | 8507.xx | 7.5% | 25% | 25% | 9903.91.11-12 |
| **Critical Minerals** | Various | 0-25% | 25% | 25% | 9903.91.03-05 |

---

## 3. Current System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CURRENT ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐                                                       │
│  │   User      │                                                       │
│  │   Query     │                                                       │
│  └──────┬──────┘                                                       │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    FLASK APP (app/web/)                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │   │
│  │  │ tariff_views│  │conversation │  │  auth_views │             │   │
│  │  │    .py      │  │  _views.py  │  │     .py     │             │   │
│  │  └──────┬──────┘  └─────────────┘  └─────────────┘             │   │
│  └─────────┼───────────────────────────────────────────────────────┘   │
│            │                                                            │
│            ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              STACKING RAG (app/chat/graphs/stacking_rag.py)      │   │
│  │                                                                  │   │
│  │  Orchestrates: get_applicable_programs → plan_entry_slices      │   │
│  │                → build_entry_stack → calculate_duties           │   │
│  └──────────────────────────────┬──────────────────────────────────┘   │
│                                 │                                       │
│            ┌────────────────────┼────────────────────┐                 │
│            ▼                    ▼                    ▼                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │ STACKING TOOLS  │  │    DATABASE     │  │  GEMINI SEARCH  │        │
│  │ (stacking_      │  │  (PostgreSQL)   │  │  (Web fallback) │        │
│  │  tools.py)      │  │                 │  │                 │        │
│  │                 │  │ • section_301   │  │  Used when DB   │        │
│  │ 15+ LangChain   │  │   _inclusions   │  │  has no answer  │        │
│  │ tools           │  │ • section_232   │  │                 │        │
│  │                 │  │   _materials    │  │                 │        │
│  │                 │  │ • hts_base_rates│  │                 │        │
│  │                 │  │ • program_codes │  │                 │        │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘        │
│                                                                         │
│  STATIC DATA IMPORT (scripts/)                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ parse_fr_301_pdfs.py  ──►  section_301_hts_codes.csv            │   │
│  │ parse_cbp_232_lists.py ──► section_232_hts_codes.csv            │   │
│  │ build_mfn_base_rates.py ──► mfn_base_rates_8digit.csv           │   │
│  │                                                                  │   │
│  │ import_section_301_csv.py ──► DB                                │   │
│  │ import_mfn_base_rates.py ──► DB                                 │   │
│  │ populate_tariff_tables.py ──► DB                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ❌ NO WATCHERS                                                         │
│  ❌ NO CONTINUOUS UPDATES                                               │
│  ❌ NO TEMPORAL TRACKING                                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Current Tables (Static)

| Table | Records | Temporal? | Problem |
|-------|---------|-----------|---------|
| `section_301_inclusions` | 11,491 | ❌ No | Can't track rate changes |
| `section_232_materials` | 838 | ❌ No | Single rate per HTS |
| `hts_base_rates` | 12,176 | ⚠️ Partial | Has effective_date but no end |
| `program_codes` | 24 | ❌ No | Static mapping |

---

## 4. Target System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           TARGET ARCHITECTURE                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                        LAYER 1: WATCHERS                                   │  │
│  │                      (Scheduled Jobs - Hourly/Daily)                       │  │
│  │                                                                            │  │
│  │   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │  │
│  │   │  Federal    │    │    CBP      │    │   USITC     │                  │  │
│  │   │  Register   │    │   CSMS      │    │    HTS      │                  │  │
│  │   │  Watcher    │    │  Watcher    │    │  Watcher    │                  │  │
│  │   │             │    │             │    │             │                  │  │
│  │   │ API: JSON   │    │ HTML scrape │    │ API/CSV     │                  │  │
│  │   │ + XML fetch │    │ + PDF/DOCX  │    │ bulk sync   │                  │  │
│  │   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                  │  │
│  │          │                  │                  │                          │  │
│  │          └──────────────────┼──────────────────┘                          │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │     INGEST QUEUE            │                              │  │
│  │              │  (ingest_jobs table)        │                              │  │
│  │              │                             │                              │  │
│  │              │  { source, doc_id, url,     │                              │  │
│  │              │    discovered_at, status }  │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  └─────────────────────────────┼─────────────────────────────────────────────┘  │
│                                │                                                 │
│  ┌─────────────────────────────┼─────────────────────────────────────────────┐  │
│  │                        LAYER 2: DOCUMENT PROCESSING                        │  │
│  │                                                                            │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │      FETCH WORKER           │                              │  │
│  │              │                             │                              │  │
│  │              │  • Download raw bytes       │                              │  │
│  │              │  • Compute SHA256 hash      │                              │  │
│  │              │  • Store in document_store  │                              │  │
│  │              │  • Extract metadata         │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  │                             │                                              │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │      RENDER WORKER          │                              │  │
│  │              │                             │                              │  │
│  │              │  Format-specific rendering: │                              │  │
│  │              │  • XML → parse <GPOTABLE>   │  ◄── PREFERRED (structured)  │  │
│  │              │  • HTML → strip + extract   │                              │  │
│  │              │  • PDF → pdfplumber         │  ◄── FALLBACK                │  │
│  │              │  • DOCX → python-docx       │                              │  │
│  │              │                             │                              │  │
│  │              │  Output: canonical_text     │                              │  │
│  │              │          (line-numbered)    │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  │                             │                                              │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │      CHUNK WORKER           │                              │  │
│  │              │                             │                              │  │
│  │              │  • Split by section/page    │                              │  │
│  │              │  • 300-900 tokens per chunk │                              │  │
│  │              │  • Store with line refs     │                              │  │
│  │              │  • Embed for vector search  │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  └─────────────────────────────┼─────────────────────────────────────────────┘  │
│                                │                                                 │
│  ┌─────────────────────────────┼─────────────────────────────────────────────┐  │
│  │                        LAYER 3: EXTRACTION & VALIDATION                    │  │
│  │                                                                            │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │     EXTRACTION WORKER       │                              │  │
│  │              │         (RAG + LLM)         │                              │  │
│  │              │                             │                              │  │
│  │              │  For Federal Register XML:  │                              │  │
│  │              │  • Parse <GPOTABLE> directly│  ◄── DETERMINISTIC           │  │
│  │              │  • No LLM needed for tables │                              │  │
│  │              │                             │                              │  │
│  │              │  For unstructured (PDF):    │                              │  │
│  │              │  • Retrieve relevant chunks │                              │  │
│  │              │  • LLM extracts changes     │  ◄── RAG EXTRACTION          │  │
│  │              │                             │                              │  │
│  │              │  Output: CandidateChanges[] │                              │  │
│  │              │  {                          │                              │  │
│  │              │    hts_8digit,              │                              │  │
│  │              │    old_code, new_code,      │                              │  │
│  │              │    old_rate, new_rate,      │                              │  │
│  │              │    effective_date,          │                              │  │
│  │              │    evidence_chunk_id,       │                              │  │
│  │              │    evidence_lines           │                              │  │
│  │              │  }                          │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  │                             │                                              │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │    VALIDATION WORKER        │                              │  │
│  │              │       (RAG + LLM)           │                              │  │
│  │              │                             │                              │  │
│  │              │  For each CandidateChange:  │                              │  │
│  │              │  1. Retrieve evidence chunk │                              │  │
│  │              │  2. LLM verifies extraction │                              │  │
│  │              │  3. Check quote exists      │                              │  │
│  │              │     VERBATIM in source      │                              │  │
│  │              │                             │                              │  │
│  │              │  Output: CONFIRMED/REJECTED │                              │  │
│  │              │          + evidence packet  │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  │                             │                                              │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │      WRITE GATE             │                              │  │
│  │              │   (Deterministic Checks)    │                              │  │
│  │              │                             │                              │  │
│  │              │  MUST have:                 │                              │  │
│  │              │  ✓ Tier A source domain     │                              │  │
│  │              │  ✓ Document hash verified   │                              │  │
│  │              │  ✓ Evidence quote verbatim  │                              │  │
│  │              │  ✓ HTS code in quote        │                              │  │
│  │              │  ✓ Rate/code in quote       │                              │  │
│  │              │                             │                              │  │
│  │              │  Creates:                   │                              │  │
│  │              │  • Audit log entry          │                              │  │
│  │              │  • Evidence packet          │                              │  │
│  │              └──────────────┬──────────────┘                              │  │
│  └─────────────────────────────┼─────────────────────────────────────────────┘  │
│                                │                                                 │
│  ┌─────────────────────────────┼─────────────────────────────────────────────┐  │
│  │                        LAYER 4: TEMPORAL DATABASE                          │  │
│  │                                                                            │  │
│  │                             ▼                                              │  │
│  │              ┌─────────────────────────────┐                              │  │
│  │              │    COMMIT TO TEMPORAL DB    │                              │  │
│  │              │                             │                              │  │
│  │              │  section_301_rates (NEW):   │                              │  │
│  │              │  • hts_8digit               │                              │  │
│  │              │  • chapter_99_code          │                              │  │
│  │              │  • duty_rate                │                              │  │
│  │              │  • effective_start  ◄───────│── When rate begins           │  │
│  │              │  • effective_end    ◄───────│── When superseded (nullable) │  │
│  │              │  • source_doc_id            │                              │  │
│  │              │  • evidence_id              │                              │  │
│  │              │                             │                              │  │
│  │              │  Query "as of date":        │                              │  │
│  │              │  WHERE effective_start <= D │                              │  │
│  │              │    AND (effective_end IS    │                              │  │
│  │              │         NULL OR end > D)    │                              │  │
│  │              └─────────────────────────────┘                              │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
│  ┌───────────────────────────────────────────────────────────────────────────┐  │
│  │                     EXISTING SYSTEM (Enhanced)                             │  │
│  │                                                                            │  │
│  │   User Query ──► Stacking RAG ──► Stacking Tools ──► TEMPORAL DB          │  │
│  │                                         │                                  │  │
│  │                                         ▼                                  │  │
│  │                              Query with as_of_date                         │  │
│  │                              (defaults to TODAY)                           │  │
│  │                                                                            │  │
│  │   UI shows: "Data last synced: 2026-01-10 08:00 UTC"                      │  │
│  │             "Federal Register watcher: ✓ current"                         │  │
│  │             "CBP CSMS watcher: ✓ current"                                 │  │
│  └───────────────────────────────────────────────────────────────────────────┘  │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Component Design

### 5.1 Watchers

#### Federal Register Watcher

```python
# app/watchers/federal_register_watcher.py

class FederalRegisterWatcher:
    """
    Polls Federal Register API for new Section 301 / IEEPA notices.

    API Endpoint: https://www.federalregister.gov/api/v1/documents.json

    Key search terms:
    - "section 301"
    - "9903.88" (original 301 codes)
    - "9903.91" (2024 review codes)
    - "USTR"
    - "China tariff"
    - "IEEPA"
    """

    SEARCH_TERMS = [
        "section 301 China",
        "9903.88",
        "9903.91",
        "USTR modification",
        "IEEPA fentanyl",
        "IEEPA reciprocal",
    ]

    def poll(self, since_date: date) -> List[DiscoveredDocument]:
        """
        Poll API for documents published since last check.

        Returns list of documents to enqueue for ingestion.
        """
        discovered = []

        for term in self.SEARCH_TERMS:
            url = (
                f"https://www.federalregister.gov/api/v1/documents.json"
                f"?conditions[term]={quote(term)}"
                f"&conditions[publication_date][gte]={since_date}"
                f"&conditions[agencies][]=trade-representative"
                f"&order=newest"
                f"&per_page=50"
            )

            response = requests.get(url)
            data = response.json()

            for doc in data.get("results", []):
                discovered.append(DiscoveredDocument(
                    source="federal_register",
                    external_id=doc["document_number"],
                    publication_date=doc["publication_date"],
                    title=doc["title"],
                    pdf_url=doc.get("pdf_url"),
                    xml_url=doc.get("full_text_xml_url"),
                    html_url=doc.get("html_url"),
                    effective_date=doc.get("effective_on"),
                    metadata=doc
                ))

        return deduplicate(discovered)
```

#### CBP CSMS Watcher

```python
# app/watchers/cbp_csms_watcher.py

class CBPCSMSWatcher:
    """
    Polls CBP CSMS archive for new bulletins.

    CSMS provides operational filing instructions for:
    - Section 232 reporting codes
    - Implementation dates
    - ACE filing guidance

    Archive: https://www.cbp.gov/trade/csms/archive
    """

    KEYWORDS = [
        "section 232",
        "section 301",
        "steel",
        "aluminum",
        "copper",
        "tariff",
        "9903",
    ]

    def poll(self, since_date: date) -> List[DiscoveredDocument]:
        """
        Scrape CSMS archive for new bulletins.

        CBP doesn't have a clean JSON API, so we:
        1. Fetch archive HTML
        2. Parse bulletin listings
        3. Filter by keywords
        4. Fetch attachments (PDF/DOCX)
        """
        # Implementation: HTML scraping + attachment fetching
        pass
```

#### USITC HTS Watcher

```python
# app/watchers/usitc_watcher.py

class USITCWatcher:
    """
    Monitors USITC for HTS updates (MFN base rates).

    Two modes:
    1. Bulk sync: Download annual HTS CSV release
    2. On-demand: Verify specific HTS via RESTStop API

    RESTStop API: https://hts.usitc.gov/reststop/search?keyword=XXXX
    """

    def check_for_new_release(self) -> Optional[str]:
        """
        Check if USITC has published a new HTS edition.

        Returns download URL if new release detected.
        """
        pass

    def verify_hts(self, hts_code: str) -> dict:
        """
        On-demand verification of specific HTS code.

        Used during query-time to validate/refresh stale data.
        """
        url = f"https://hts.usitc.gov/reststop/search?keyword={hts_code}"
        response = requests.get(url)
        return response.json()
```

### 5.2 Document Store

```python
# app/models/document_store.py

class OfficialDocument(db.Model):
    """
    Stores raw official documents with audit trail.
    """
    __tablename__ = "official_documents"

    id = db.Column(UUID, primary_key=True, default=uuid4)

    # Source identification
    source = db.Column(db.String(50), nullable=False)  # federal_register, cbp_csms, usitc
    external_id = db.Column(db.String(100), nullable=False)  # document_number, bulletin_id

    # URLs
    pdf_url = db.Column(db.String(500))
    xml_url = db.Column(db.String(500))
    html_url = db.Column(db.String(500))

    # Raw content
    raw_bytes = db.Column(db.LargeBinary)  # Original file bytes
    content_hash = db.Column(db.String(64), nullable=False)  # SHA256
    content_type = db.Column(db.String(50))  # application/pdf, text/xml, etc.

    # Rendered content
    canonical_text = db.Column(db.Text)  # Line-numbered plain text

    # Metadata
    title = db.Column(db.String(500))
    publication_date = db.Column(db.Date)
    effective_date = db.Column(db.Date)

    # Processing status
    status = db.Column(db.String(50), default="fetched")
    # fetched → rendered → chunked → extracted → validated → committed

    # Relationships
    parent_document_id = db.Column(UUID, db.ForeignKey("official_documents.id"))
    chunks = db.relationship("DocumentChunk", backref="document")

    # Timestamps
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint("source", "external_id", "content_hash"),
    )


class DocumentChunk(db.Model):
    """
    Chunks of documents for RAG retrieval.
    """
    __tablename__ = "document_chunks"

    id = db.Column(UUID, primary_key=True, default=uuid4)
    document_id = db.Column(UUID, db.ForeignKey("official_documents.id"), nullable=False)

    # Position
    chunk_index = db.Column(db.Integer, nullable=False)
    page_start = db.Column(db.Integer)
    page_end = db.Column(db.Integer)
    line_start = db.Column(db.Integer)
    line_end = db.Column(db.Integer)

    # Content
    text = db.Column(db.Text, nullable=False)
    token_count = db.Column(db.Integer)

    # Embedding (for vector search)
    embedding = db.Column(db.ARRAY(db.Float))  # Or store in Pinecone

    # Metadata
    section_heading = db.Column(db.String(200))
    chunk_type = db.Column(db.String(50))  # narrative, table, annex
```

### 5.3 Evidence Store

```python
# app/models/evidence.py

class EvidencePacket(db.Model):
    """
    Stores proof that a DB change is supported by official text.
    """
    __tablename__ = "evidence_packets"

    id = db.Column(UUID, primary_key=True, default=uuid4)

    # Source document
    document_id = db.Column(UUID, db.ForeignKey("official_documents.id"), nullable=False)
    document_hash = db.Column(db.String(64), nullable=False)

    # Evidence location
    chunk_id = db.Column(UUID, db.ForeignKey("document_chunks.id"))
    page_number = db.Column(db.Integer)
    line_start = db.Column(db.Integer)
    line_end = db.Column(db.Integer)

    # Evidence content
    quote_text = db.Column(db.Text, nullable=False)  # Exact quote
    context_before = db.Column(db.Text)  # +/- 20 lines
    context_after = db.Column(db.Text)

    # What it proves
    proves_hts_code = db.Column(db.String(12))
    proves_chapter_99 = db.Column(db.String(12))
    proves_rate = db.Column(db.Numeric(5, 4))
    proves_effective_date = db.Column(db.Date)

    # Validation
    validated_by = db.Column(db.String(50))  # llm_validator, human
    validated_at = db.Column(db.DateTime)
    confidence_score = db.Column(db.Float)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

---

## 6. Database Schema Changes

### 6.1 New Temporal Table: section_301_rates

```sql
-- Replaces section_301_inclusions for temporal rate tracking

CREATE TABLE section_301_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- HTS identification
    hts_8digit VARCHAR(10) NOT NULL,

    -- Chapter 99 code and rate
    chapter_99_code VARCHAR(12) NOT NULL,
    duty_rate NUMERIC(5,4) NOT NULL,

    -- Temporal validity
    effective_start DATE NOT NULL,
    effective_end DATE,  -- NULL = currently active

    -- Classification
    list_name VARCHAR(32),  -- list_1, list_2, list_3, list_4a, strategic_medical, etc.
    sector VARCHAR(50),     -- medical, semiconductor, ev, battery, etc.

    -- Audit trail
    source_doc_id UUID REFERENCES official_documents(id),
    evidence_id UUID REFERENCES evidence_packets(id),

    -- Supersession
    supersedes_id UUID REFERENCES section_301_rates(id),
    superseded_by_id UUID REFERENCES section_301_rates(id),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(50),  -- system, human

    -- Constraints
    UNIQUE(hts_8digit, chapter_99_code, effective_start)
);

-- Index for "as of date" queries
CREATE INDEX idx_301_rates_hts_date ON section_301_rates(hts_8digit, effective_start, effective_end);

-- Query: Get rate for HTS X on date D
-- SELECT * FROM section_301_rates
-- WHERE hts_8digit = '63079098'
--   AND effective_start <= '2026-01-10'
--   AND (effective_end IS NULL OR effective_end > '2026-01-10')
-- ORDER BY effective_start DESC
-- LIMIT 1;
```

### 6.2 Migration Strategy

```python
# migrations/add_temporal_301_rates.py

def upgrade():
    """
    Add temporal section_301_rates table while preserving existing data.
    """

    # 1. Create new table
    op.create_table("section_301_rates", ...)

    # 2. Migrate existing data from section_301_inclusions
    #    All existing rows become "effective_start = original_effective_date, effective_end = NULL"
    op.execute("""
        INSERT INTO section_301_rates (
            hts_8digit, chapter_99_code, duty_rate,
            effective_start, effective_end,
            list_name, created_by
        )
        SELECT
            hts_8digit, chapter_99_code, duty_rate,
            COALESCE(effective_start, '2018-07-06'), NULL,
            list_name, 'migration'
        FROM section_301_inclusions
        WHERE status = 'active'
    """)

    # 3. Keep old table for reference (rename)
    op.rename_table("section_301_inclusions", "section_301_inclusions_legacy")

    # 4. Create view for backward compatibility
    op.execute("""
        CREATE VIEW section_301_inclusions AS
        SELECT * FROM section_301_rates
        WHERE effective_end IS NULL
    """)
```

### 6.3 Ingest Jobs Table

```sql
CREATE TABLE ingest_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source
    source VARCHAR(50) NOT NULL,  -- federal_register, cbp_csms, usitc
    external_id VARCHAR(100) NOT NULL,
    url VARCHAR(500),

    -- Discovery
    discovered_at TIMESTAMP NOT NULL,
    discovered_by VARCHAR(50),  -- watcher name

    -- Status workflow
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    -- queued → fetching → fetched → rendering → rendered
    -- → chunking → chunked → extracting → extracted
    -- → validating → validated → committing → committed
    -- OR → needs_review → reviewed → committed
    -- OR → failed

    -- Processing
    document_id UUID REFERENCES official_documents(id),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,

    UNIQUE(source, external_id)
);
```

### 6.4 Audit Log

```sql
CREATE TABLE tariff_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What changed
    table_name VARCHAR(50) NOT NULL,
    record_id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,  -- INSERT, UPDATE, SUPERSEDE

    -- Before/after
    old_values JSONB,
    new_values JSONB,

    -- Why
    source_doc_id UUID REFERENCES official_documents(id),
    evidence_id UUID REFERENCES evidence_packets(id),
    change_reason TEXT,

    -- Who/when
    performed_by VARCHAR(50) NOT NULL,  -- system, human:user_id
    performed_at TIMESTAMP DEFAULT NOW(),

    -- For debugging
    job_id UUID REFERENCES ingest_jobs(id)
);
```

---

## 7. Watcher Implementation

### 7.1 Federal Register Watcher (Detailed)

```python
# app/watchers/federal_register.py

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional
import requests
from urllib.parse import quote

@dataclass
class DiscoveredDocument:
    source: str
    external_id: str
    publication_date: date
    title: str
    pdf_url: Optional[str]
    xml_url: Optional[str]
    html_url: Optional[str]
    effective_date: Optional[date]
    metadata: dict


class FederalRegisterWatcher:
    """
    Watches Federal Register API for tariff-related notices.

    Targets:
    - Section 301 modifications (USTR)
    - IEEPA notices (EO)
    - Tariff modifications

    Schedule: Every 6 hours
    """

    BASE_URL = "https://www.federalregister.gov/api/v1"

    # Agencies to watch
    AGENCIES = [
        "office-of-the-united-states-trade-representative",
        "international-trade-administration",
        "customs-and-border-protection",
    ]

    # Search queries (will poll each separately)
    QUERIES = [
        # Section 301
        {"term": "section 301", "type": "NOTICE"},
        {"term": "9903.88", "type": "NOTICE"},
        {"term": "9903.91", "type": "NOTICE"},
        {"term": "China tariff modification", "type": "NOTICE"},

        # IEEPA
        {"term": "IEEPA", "type": "NOTICE"},
        {"term": "fentanyl tariff", "type": "NOTICE"},

        # General tariff
        {"term": "tariff modification", "type": "NOTICE"},
    ]

    def __init__(self, db_session):
        self.db = db_session
        self.last_poll_key = "federal_register_last_poll"

    def get_last_poll_date(self) -> date:
        """Get date of last successful poll from DB."""
        setting = self.db.query(SystemSetting).filter_by(key=self.last_poll_key).first()
        if setting:
            return datetime.fromisoformat(setting.value).date()
        # Default: 30 days ago
        return date.today() - timedelta(days=30)

    def poll(self) -> List[DiscoveredDocument]:
        """
        Poll Federal Register API for new documents.

        Returns deduplicated list of documents to enqueue.
        """
        since_date = self.get_last_poll_date()
        discovered = []
        seen_ids = set()

        for query in self.QUERIES:
            try:
                docs = self._search(query["term"], since_date, query.get("type"))
                for doc in docs:
                    if doc.external_id not in seen_ids:
                        seen_ids.add(doc.external_id)
                        discovered.append(doc)
            except Exception as e:
                logger.error(f"FR search failed for '{query['term']}': {e}")

        # Update last poll date
        self._update_last_poll()

        logger.info(f"Federal Register watcher found {len(discovered)} new documents")
        return discovered

    def _search(self, term: str, since_date: date, doc_type: str = None) -> List[DiscoveredDocument]:
        """Execute single search query."""
        params = {
            "conditions[term]": term,
            "conditions[publication_date][gte]": since_date.isoformat(),
            "order": "newest",
            "per_page": 100,
        }

        if doc_type:
            params["conditions[type][]"] = doc_type

        response = requests.get(f"{self.BASE_URL}/documents.json", params=params)
        response.raise_for_status()
        data = response.json()

        results = []
        for doc in data.get("results", []):
            results.append(DiscoveredDocument(
                source="federal_register",
                external_id=doc["document_number"],
                publication_date=date.fromisoformat(doc["publication_date"]),
                title=doc["title"],
                pdf_url=doc.get("pdf_url"),
                xml_url=doc.get("full_text_xml_url"),
                html_url=doc.get("html_url"),
                effective_date=date.fromisoformat(doc["effective_on"]) if doc.get("effective_on") else None,
                metadata=doc
            ))

        return results

    def enqueue_documents(self, documents: List[DiscoveredDocument]):
        """Create ingest jobs for discovered documents."""
        for doc in documents:
            # Check if already processed
            existing = self.db.query(IngestJob).filter_by(
                source=doc.source,
                external_id=doc.external_id
            ).first()

            if existing:
                logger.debug(f"Skipping already-known document: {doc.external_id}")
                continue

            job = IngestJob(
                source=doc.source,
                external_id=doc.external_id,
                url=doc.xml_url or doc.pdf_url or doc.html_url,
                discovered_at=datetime.utcnow(),
                discovered_by="federal_register_watcher",
                status="queued",
            )
            self.db.add(job)

        self.db.commit()
```

### 7.2 Watcher Scheduler

```python
# app/watchers/scheduler.py

from apscheduler.schedulers.background import BackgroundScheduler

def setup_watchers(app):
    """
    Configure watcher schedules.

    Runs in background thread of Flask app.
    """
    scheduler = BackgroundScheduler()

    # Federal Register: every 6 hours
    scheduler.add_job(
        run_federal_register_watcher,
        trigger="interval",
        hours=6,
        id="federal_register_watcher",
        replace_existing=True,
    )

    # CBP CSMS: every 12 hours
    scheduler.add_job(
        run_cbp_csms_watcher,
        trigger="interval",
        hours=12,
        id="cbp_csms_watcher",
        replace_existing=True,
    )

    # USITC HTS: daily at 2am
    scheduler.add_job(
        run_usitc_watcher,
        trigger="cron",
        hour=2,
        id="usitc_watcher",
        replace_existing=True,
    )

    scheduler.start()
    return scheduler


def run_federal_register_watcher():
    """Execute Federal Register watcher."""
    with app.app_context():
        watcher = FederalRegisterWatcher(db.session)
        documents = watcher.poll()
        watcher.enqueue_documents(documents)
```

---

## 8. Document Processing Pipeline

### 8.1 Fetch Worker

```python
# app/workers/fetch_worker.py

import hashlib
import requests

class FetchWorker:
    """
    Downloads and stores raw documents.
    """

    def process_job(self, job: IngestJob):
        """
        Fetch document and store with hash.
        """
        job.status = "fetching"
        db.session.commit()

        try:
            # Prefer XML > HTML > PDF
            url = job.url
            content_type = self._detect_type(url)

            response = requests.get(url, timeout=60)
            response.raise_for_status()
            raw_bytes = response.content

            # Compute hash
            content_hash = hashlib.sha256(raw_bytes).hexdigest()

            # Check for duplicate
            existing = OfficialDocument.query.filter_by(content_hash=content_hash).first()
            if existing:
                job.document_id = existing.id
                job.status = "fetched"
                db.session.commit()
                return existing

            # Store document
            doc = OfficialDocument(
                source=job.source,
                external_id=job.external_id,
                pdf_url=job.url if content_type == "application/pdf" else None,
                xml_url=job.url if content_type == "text/xml" else None,
                raw_bytes=raw_bytes,
                content_hash=content_hash,
                content_type=content_type,
                fetched_at=datetime.utcnow(),
                status="fetched",
            )

            # Get metadata from FR API if applicable
            if job.source == "federal_register":
                self._enrich_from_api(doc, job.external_id)

            db.session.add(doc)
            job.document_id = doc.id
            job.status = "fetched"
            db.session.commit()

            return doc

        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.retry_count += 1
            db.session.commit()
            raise
```

### 8.2 Render Worker

```python
# app/workers/render_worker.py

import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pdfplumber

class RenderWorker:
    """
    Converts raw documents to canonical line-numbered text.

    Output format:
    L001: First line of document
    L002: Second line
    ...

    This enables evidence citing: "Lines L047-L052"
    """

    def process(self, doc: OfficialDocument):
        """
        Render document based on content type.
        """
        doc.status = "rendering"
        db.session.commit()

        if doc.content_type == "text/xml":
            canonical_text = self._render_xml(doc.raw_bytes)
        elif doc.content_type == "text/html":
            canonical_text = self._render_html(doc.raw_bytes)
        elif doc.content_type == "application/pdf":
            canonical_text = self._render_pdf(doc.raw_bytes)
        else:
            raise ValueError(f"Unsupported content type: {doc.content_type}")

        doc.canonical_text = canonical_text
        doc.status = "rendered"
        db.session.commit()

    def _render_xml(self, raw_bytes: bytes) -> str:
        """
        Parse Federal Register XML.

        Key elements:
        - <GPOTABLE>: Structured tables with HTS codes
        - <P>: Paragraphs
        - <FP>: Formatted paragraphs
        """
        root = ET.fromstring(raw_bytes)
        lines = []
        line_num = 1

        # Extract all text elements
        for elem in root.iter():
            if elem.text and elem.text.strip():
                for text_line in elem.text.strip().split("\n"):
                    lines.append(f"L{line_num:04d}: {text_line}")
                    line_num += 1

        return "\n".join(lines)

    def _render_pdf(self, raw_bytes: bytes) -> str:
        """
        Extract text from PDF using pdfplumber.
        """
        import io
        lines = []
        line_num = 1

        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                lines.append(f"L{line_num:04d}: --- PAGE {page_num} ---")
                line_num += 1

                for text_line in text.split("\n"):
                    lines.append(f"L{line_num:04d}: {text_line}")
                    line_num += 1

        return "\n".join(lines)
```

### 8.3 XML Table Extractor (Deterministic)

```python
# app/workers/xml_table_extractor.py

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

@dataclass
class ExtractedRate:
    hts_code: str
    description: str
    rate: float
    effective_year: int
    line_start: int
    line_end: int


class XMLTableExtractor:
    """
    Deterministic extraction from Federal Register <GPOTABLE> elements.

    NO LLM NEEDED - tables are already structured!

    Example XML:
    <GPOTABLE COLS="4">
      <ROW>
        <ENT>8507.90.40</ENT>
        <ENT>Parts of lead-acid storage batteries</ENT>
        <ENT>25</ENT>
        <ENT>2024</ENT>
      </ROW>
    </GPOTABLE>
    """

    def extract_tables(self, raw_bytes: bytes) -> List[ExtractedRate]:
        """
        Parse all <GPOTABLE> elements and extract HTS/rate data.
        """
        root = ET.fromstring(raw_bytes)
        results = []

        for table in root.iter("GPOTABLE"):
            cols = int(table.get("COLS", 4))

            for row in table.findall(".//ROW"):
                entries = row.findall("ENT")
                if len(entries) >= 3:
                    hts_code = self._clean_hts(entries[0].text or "")

                    if self._is_valid_hts(hts_code):
                        results.append(ExtractedRate(
                            hts_code=hts_code,
                            description=entries[1].text or "" if len(entries) > 1 else "",
                            rate=self._parse_rate(entries[2].text or "") if len(entries) > 2 else 0,
                            effective_year=self._parse_year(entries[3].text or "") if len(entries) > 3 else 2024,
                            line_start=0,  # TODO: track line numbers
                            line_end=0,
                        ))

        return results

    def _is_valid_hts(self, code: str) -> bool:
        """Validate HTS code format (not Chapter 99)."""
        import re
        if not code:
            return False
        if code.startswith("99"):
            return False
        return bool(re.match(r'^\d{4}\.\d{2}\.\d{2,4}$', code))

    def _parse_rate(self, text: str) -> float:
        """Parse rate string to decimal."""
        import re
        match = re.search(r'(\d+(?:\.\d+)?)', text)
        if match:
            return float(match.group(1)) / 100
        return 0.0
```

---

## 9. RAG Extraction & Validation

### 9.1 When RAG is Used

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    RAG USAGE IN THE PIPELINE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  DOCUMENT TYPE          EXTRACTION METHOD                               │
│  ─────────────          ──────────────────                              │
│                                                                         │
│  Federal Register XML   DETERMINISTIC (parse <GPOTABLE>)               │
│  with <GPOTABLE>        No LLM needed - tables are structured          │
│                                                                         │
│  Federal Register XML   RAG + LLM EXTRACTION                           │
│  narrative sections     Needed for effective dates, scope clauses      │
│                                                                         │
│  CBP CSMS HTML          HYBRID                                          │
│                         Simple: regex for CSMS numbers, dates          │
│                         Complex: RAG for filing instructions           │
│                                                                         │
│  CBP DOCX attachments   RAG + LLM EXTRACTION                           │
│                         Unstructured lists of HTS codes                │
│                                                                         │
│  USITC CSV/API          DETERMINISTIC                                   │
│                         Already machine-readable                        │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│  VALIDATION             ALWAYS uses RAG + LLM                           │
│                         Cross-check extraction against source          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Extraction Worker (RAG)

```python
# app/workers/extraction_worker.py

from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

class ExtractionWorker:
    """
    Extracts tariff changes from documents using RAG.

    Two modes:
    1. DETERMINISTIC: XML tables → parse directly
    2. RAG: Unstructured → LLM extraction
    """

    EXTRACTION_PROMPT = """You are extracting tariff changes from an official Federal Register notice.

DOCUMENT CONTEXT:
{document_context}

CHUNK TO ANALYZE:
{chunk_text}

Extract ALL tariff changes mentioned. For each change, provide:
- hts_code: The HTS code affected (format: XXXX.XX.XX or XXXX.XX.XXXX)
- old_chapter_99_code: Previous Chapter 99 code (if mentioned)
- new_chapter_99_code: New Chapter 99 code (e.g., 9903.91.07)
- old_rate: Previous rate as decimal (e.g., 0.075 for 7.5%)
- new_rate: New rate as decimal (e.g., 0.50 for 50%)
- effective_date: When this change takes effect (YYYY-MM-DD)
- evidence_quote: Exact quote from the text that supports this (max 200 chars)

Return as JSON array:
[
  {
    "hts_code": "6307.90.98",
    "old_chapter_99_code": "9903.88.15",
    "new_chapter_99_code": "9903.91.07",
    "old_rate": 0.075,
    "new_rate": 0.50,
    "effective_date": "2026-01-01",
    "evidence_quote": "Products of China...subject to an additional 50 percent ad valorem rate of duty..."
  }
]

If no tariff changes found in this chunk, return: []

IMPORTANT:
- Only extract from THIS chunk, not from memory
- Only include changes with clear HTS codes and rates
- Do NOT include Chapter 99 codes as HTS codes (99XX.XX.XX are filing codes, not product codes)
"""

    def extract_from_document(self, doc: OfficialDocument) -> List[CandidateChange]:
        """
        Extract all tariff changes from document.
        """
        doc.status = "extracting"
        db.session.commit()

        candidates = []

        # Step 1: Try deterministic XML extraction first
        if doc.content_type == "text/xml":
            xml_extractor = XMLTableExtractor()
            table_results = xml_extractor.extract_tables(doc.raw_bytes)

            for result in table_results:
                candidates.append(CandidateChange(
                    document_id=doc.id,
                    hts_code=result.hts_code,
                    new_rate=result.rate,
                    effective_date=date(result.effective_year, 1, 1),
                    extraction_method="xml_table",
                    evidence_line_start=result.line_start,
                    evidence_line_end=result.line_end,
                ))

        # Step 2: RAG extraction for narrative content
        chunks = doc.chunks
        for chunk in chunks:
            if chunk.chunk_type == "narrative":
                llm_candidates = self._extract_with_llm(doc, chunk)
                candidates.extend(llm_candidates)

        doc.status = "extracted"
        db.session.commit()

        return candidates

    def _extract_with_llm(self, doc: OfficialDocument, chunk: DocumentChunk) -> List[CandidateChange]:
        """Use LLM to extract from unstructured chunk."""
        llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)

        prompt = ChatPromptTemplate.from_template(self.EXTRACTION_PROMPT)

        response = llm.invoke(prompt.format(
            document_context=f"Document: {doc.title}\nSource: {doc.source}\nPublished: {doc.publication_date}",
            chunk_text=chunk.text
        ))

        # Parse JSON response
        import json
        try:
            changes = json.loads(response.content)
        except json.JSONDecodeError:
            return []

        candidates = []
        for change in changes:
            candidates.append(CandidateChange(
                document_id=doc.id,
                hts_code=change.get("hts_code"),
                old_chapter_99_code=change.get("old_chapter_99_code"),
                new_chapter_99_code=change.get("new_chapter_99_code"),
                old_rate=change.get("old_rate"),
                new_rate=change.get("new_rate"),
                effective_date=change.get("effective_date"),
                evidence_quote=change.get("evidence_quote"),
                evidence_chunk_id=chunk.id,
                extraction_method="llm_rag",
            ))

        return candidates
```

### 9.3 Validation Worker

```python
# app/workers/validation_worker.py

class ValidationWorker:
    """
    Validates extracted changes against source documents.

    Two-layer validation:
    1. LLM Validator: Cross-check extraction against retrieved chunks
    2. Deterministic Checks: Verify evidence quote exists verbatim
    """

    VALIDATION_PROMPT = """You are validating a tariff data extraction.

PROPOSED CHANGE:
- HTS Code: {hts_code}
- New Chapter 99 Code: {new_chapter_99_code}
- New Rate: {new_rate}
- Effective Date: {effective_date}
- Evidence Quote: "{evidence_quote}"

SOURCE CHUNK:
{chunk_text}

QUESTIONS:
1. Does the source chunk actually mention HTS code {hts_code}?
2. Does it mention Chapter 99 code {new_chapter_99_code}?
3. Does it mention the rate {new_rate}?
4. Does the evidence quote appear VERBATIM in the source?

Return JSON:
{{
  "is_valid": true/false,
  "hts_found": true/false,
  "chapter_99_found": true/false,
  "rate_found": true/false,
  "quote_verbatim": true/false,
  "corrected_quote": "..." (if quote was close but not exact),
  "rejection_reason": "..." (if invalid)
}}
"""

    def validate(self, candidate: CandidateChange) -> ValidationResult:
        """
        Validate a candidate change.
        """
        # Step 1: Get source chunk
        chunk = DocumentChunk.query.get(candidate.evidence_chunk_id)
        if not chunk:
            return ValidationResult(is_valid=False, reason="Evidence chunk not found")

        # Step 2: LLM validation
        llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)
        prompt = ChatPromptTemplate.from_template(self.VALIDATION_PROMPT)

        response = llm.invoke(prompt.format(
            hts_code=candidate.hts_code,
            new_chapter_99_code=candidate.new_chapter_99_code,
            new_rate=candidate.new_rate,
            effective_date=candidate.effective_date,
            evidence_quote=candidate.evidence_quote,
            chunk_text=chunk.text,
        ))

        result = json.loads(response.content)

        # Step 3: Deterministic verification
        if result.get("is_valid"):
            # Check quote exists verbatim
            if candidate.evidence_quote not in chunk.text:
                # Try corrected quote
                corrected = result.get("corrected_quote", "")
                if corrected and corrected in chunk.text:
                    candidate.evidence_quote = corrected
                else:
                    return ValidationResult(
                        is_valid=False,
                        reason="Evidence quote not found verbatim in source"
                    )

        return ValidationResult(
            is_valid=result.get("is_valid", False),
            reason=result.get("rejection_reason"),
            confidence=1.0 if all([
                result.get("hts_found"),
                result.get("chapter_99_found"),
                result.get("rate_found"),
                result.get("quote_verbatim"),
            ]) else 0.7
        )
```

### 9.4 Write Gate

```python
# app/workers/write_gate.py

class WriteGate:
    """
    Final checkpoint before database write.

    Deterministic checks that MUST pass:
    1. Source is Tier A (federalregister.gov, cbp.gov, usitc.gov)
    2. Document hash is stored
    3. Evidence quote exists VERBATIM in canonical_text
    4. Evidence contains HTS code
    5. Evidence contains rate or Chapter 99 code
    """

    TIER_A_SOURCES = ["federal_register", "cbp_csms", "usitc"]

    def check(self, candidate: CandidateChange, validation: ValidationResult) -> WriteDecision:
        """
        Determine if change can be committed.
        """
        doc = OfficialDocument.query.get(candidate.document_id)

        # Check 1: Tier A source
        if doc.source not in self.TIER_A_SOURCES:
            return WriteDecision(
                approved=False,
                reason=f"Source '{doc.source}' is not Tier A"
            )

        # Check 2: Document hash exists
        if not doc.content_hash:
            return WriteDecision(
                approved=False,
                reason="Document hash not stored"
            )

        # Check 3: Evidence quote exists verbatim
        if candidate.evidence_quote not in doc.canonical_text:
            return WriteDecision(
                approved=False,
                reason="Evidence quote not found verbatim in document"
            )

        # Check 4: HTS code in evidence
        if candidate.hts_code not in candidate.evidence_quote:
            return WriteDecision(
                approved=False,
                reason="HTS code not found in evidence quote"
            )

        # Check 5: Rate or Chapter 99 in evidence
        rate_str = f"{int(candidate.new_rate * 100)}"
        ch99 = candidate.new_chapter_99_code or ""

        if rate_str not in candidate.evidence_quote and ch99 not in candidate.evidence_quote:
            return WriteDecision(
                approved=False,
                reason="Neither rate nor Chapter 99 code found in evidence quote"
            )

        # All checks passed
        return WriteDecision(
            approved=True,
            evidence_packet=self._create_evidence_packet(candidate, doc)
        )

    def _create_evidence_packet(self, candidate: CandidateChange, doc: OfficialDocument) -> EvidencePacket:
        """Create audit-grade evidence packet."""
        # Find line numbers for evidence quote
        lines = doc.canonical_text.split("\n")
        line_start = None
        line_end = None

        for i, line in enumerate(lines):
            if candidate.evidence_quote[:50] in line:
                line_start = i + 1
                break

        if line_start:
            line_end = line_start
            for i in range(line_start, min(line_start + 10, len(lines))):
                if candidate.evidence_quote[-50:] in lines[i]:
                    line_end = i + 1
                    break

        # Get context lines (+/- 20)
        context_start = max(0, (line_start or 0) - 20)
        context_end = min(len(lines), (line_end or 0) + 20)

        return EvidencePacket(
            document_id=doc.id,
            document_hash=doc.content_hash,
            page_number=None,  # TODO: extract from line numbers
            line_start=line_start,
            line_end=line_end,
            quote_text=candidate.evidence_quote,
            context_before="\n".join(lines[context_start:(line_start or 0) - 1]),
            context_after="\n".join(lines[(line_end or 0):context_end]),
            proves_hts_code=candidate.hts_code,
            proves_chapter_99=candidate.new_chapter_99_code,
            proves_rate=candidate.new_rate,
            proves_effective_date=candidate.effective_date,
            validated_by="write_gate",
            validated_at=datetime.utcnow(),
        )
```

---

## 10. Integration with Existing System

### 10.1 Modified Stacking Tools

```python
# app/chat/tools/stacking_tools.py (MODIFIED)

@tool("check_program_inclusion")
def check_program_inclusion(program_id: str, hts_code: str, as_of_date: date = None) -> str:
    """
    Check if HTS code is included in a tariff program.

    NOW TEMPORAL: Uses as_of_date to query correct rate.
    """
    if as_of_date is None:
        as_of_date = date.today()

    hts_8digit = hts_code.replace(".", "")[:8]

    if program_id == "section_301":
        # TEMPORAL QUERY (NEW)
        rate_record = Section301Rate.query.filter(
            Section301Rate.hts_8digit == hts_8digit,
            Section301Rate.effective_start <= as_of_date,
            db.or_(
                Section301Rate.effective_end.is_(None),
                Section301Rate.effective_end > as_of_date
            )
        ).order_by(Section301Rate.effective_start.desc()).first()

        if rate_record:
            return json.dumps({
                "included": True,
                "chapter_99_code": rate_record.chapter_99_code,
                "duty_rate": float(rate_record.duty_rate),
                "list_name": rate_record.list_name,
                "sector": rate_record.sector,
                "effective_date": rate_record.effective_start.isoformat(),
                "source_doc_id": str(rate_record.source_doc_id) if rate_record.source_doc_id else None,
            })
        else:
            return json.dumps({"included": False})

    # ... rest of existing logic
```

### 10.2 Modified Tariff Views

```python
# app/web/views/tariff_views.py (MODIFIED)

@bp.route("/tariff/calculate", methods=["POST"])
def calculate_tariff():
    """Calculate tariff stacking."""
    data = request.json or {}

    # NEW: Support as_of_date parameter
    as_of_date = data.get("as_of_date")
    if as_of_date:
        as_of_date = date.fromisoformat(as_of_date)
    else:
        as_of_date = date.today()

    # Pass to stacking RAG
    result = rag.calculate_stacking(
        hts_code=data.get("hts_code"),
        country=data.get("country"),
        product_value=data.get("product_value"),
        materials=data.get("materials"),
        as_of_date=as_of_date,  # NEW
    )

    # NEW: Include data freshness in response
    freshness = get_data_freshness()

    return jsonify({
        **result,
        "data_freshness": freshness,
    })


def get_data_freshness() -> dict:
    """Get freshness info for each data source."""
    return {
        "section_301": {
            "last_updated": get_last_update("section_301_rates"),
            "source": "Federal Register",
            "watcher_status": get_watcher_status("federal_register"),
        },
        "section_232": {
            "last_updated": get_last_update("section_232_materials"),
            "source": "CBP CSMS",
            "watcher_status": get_watcher_status("cbp_csms"),
        },
        "mfn_base_rates": {
            "last_updated": get_last_update("hts_base_rates"),
            "source": "USITC HTS",
            "watcher_status": get_watcher_status("usitc"),
        },
    }
```

### 10.3 UI Freshness Indicator

```javascript
// client/src/components/TariffCalculator.svelte (ADD)

<!-- Freshness Badge -->
<div class="freshness-indicator">
  {#if result.data_freshness}
    <div class="freshness-badge {getFreshnessClass(result.data_freshness.section_301)}">
      Section 301: {formatDate(result.data_freshness.section_301.last_updated)}
      {#if isStale(result.data_freshness.section_301)}
        <span class="warning">⚠️ May be outdated</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .freshness-indicator {
    font-size: 12px;
    color: #64748b;
    margin-top: 8px;
  }
  .freshness-badge.current { color: #10b981; }
  .freshness-badge.stale { color: #f59e0b; }
  .freshness-badge.outdated { color: #ef4444; }
  .warning { color: #f59e0b; margin-left: 4px; }
</style>
```

---

## 11. File Structure

```
lanes/
├── app/
│   ├── watchers/                    # NEW: Watcher implementations
│   │   ├── __init__.py
│   │   ├── base.py                  # BaseWatcher class
│   │   ├── federal_register.py      # Federal Register API watcher
│   │   ├── cbp_csms.py              # CBP CSMS scraper
│   │   ├── usitc.py                 # USITC HTS watcher
│   │   └── scheduler.py             # APScheduler configuration
│   │
│   ├── workers/                     # NEW: Pipeline workers
│   │   ├── __init__.py
│   │   ├── fetch_worker.py          # Document fetcher
│   │   ├── render_worker.py         # Text renderer
│   │   ├── chunk_worker.py          # Chunking + embedding
│   │   ├── extraction_worker.py     # RAG extraction
│   │   ├── xml_table_extractor.py   # Deterministic XML parser
│   │   ├── validation_worker.py     # LLM validator
│   │   ├── write_gate.py            # Final checks
│   │   └── pipeline.py              # Worker orchestration
│   │
│   ├── models/                      # NEW: Document + evidence models
│   │   ├── document_store.py        # OfficialDocument, DocumentChunk
│   │   ├── evidence.py              # EvidencePacket
│   │   ├── ingest_job.py            # IngestJob
│   │   └── audit_log.py             # TariffAuditLog
│   │
│   ├── web/
│   │   ├── db/
│   │   │   └── models/
│   │   │       ├── tariff_tables.py # MODIFIED: Add Section301Rate
│   │   │       └── ...
│   │   └── views/
│   │       └── tariff_views.py      # MODIFIED: Add freshness
│   │
│   └── chat/
│       └── tools/
│           └── stacking_tools.py    # MODIFIED: Temporal queries
│
├── migrations/                      # NEW: Database migrations
│   ├── versions/
│   │   ├── xxx_add_temporal_301_rates.py
│   │   ├── xxx_add_document_store.py
│   │   ├── xxx_add_ingest_jobs.py
│   │   └── xxx_add_audit_log.py
│
├── scripts/
│   ├── run_watchers.py              # NEW: Manual watcher trigger
│   ├── process_ingest_queue.py      # NEW: Manual queue processor
│   └── backfill_2024_review.py      # NEW: Import 2024 Four-Year Review
│
└── tests/
    ├── test_watchers/               # NEW
    │   ├── test_federal_register_watcher.py
    │   └── ...
    ├── test_workers/                # NEW
    │   ├── test_extraction_worker.py
    │   ├── test_validation_worker.py
    │   └── ...
    └── test_integration/            # NEW
        └── test_full_pipeline.py
```

---

## 12. Implementation Phases

### Phase 1: Quick Fix (1-2 days)
**Goal:** Fix immediate data gap for 2024 Four-Year Review

- [ ] Manually download FR Doc 2024-21217
- [ ] Parse XML tables for new 9903.91.xx codes
- [ ] Add to section_301_inclusions with effective_start
- [ ] Verify facemask (6307.90.98) returns 50%

### Phase 2: Temporal Schema (3-5 days)
**Goal:** Enable rate changes over time

- [ ] Create section_301_rates table
- [ ] Migrate existing data
- [ ] Modify stacking_tools.py for temporal queries
- [ ] Add as_of_date parameter to API

### Phase 3: Watchers (5-7 days)
**Goal:** Auto-detect new documents

- [ ] Implement FederalRegisterWatcher
- [ ] Implement ingest_jobs queue
- [ ] Add scheduler
- [ ] Test with recent FR notices

### Phase 4: Document Pipeline (7-10 days)
**Goal:** Full fetch → store → render → chunk

- [ ] Create OfficialDocument model
- [ ] Implement fetch_worker
- [ ] Implement render_worker (XML, HTML, PDF)
- [ ] Implement chunk_worker
- [ ] Store in Pinecone/vector DB

### Phase 5: RAG Extraction (5-7 days)
**Goal:** Extract changes from documents

- [ ] Implement XMLTableExtractor (deterministic)
- [ ] Implement RAG extraction for narrative
- [ ] Create CandidateChange model

### Phase 6: Validation + Write Gate (5-7 days)
**Goal:** Audit-grade verification

- [ ] Implement validation_worker
- [ ] Implement write_gate
- [ ] Create EvidencePacket model
- [ ] Create audit_log

### Phase 7: UI + Freshness (2-3 days)
**Goal:** Show data currency to users

- [ ] Add freshness badges to UI
- [ ] Add watcher status endpoint
- [ ] Add "last updated" per program

---

## 13. API Reference

### 13.1 Federal Register API

```
Base URL: https://www.federalregister.gov/api/v1

GET /documents.json
  ?conditions[term]=section+301
  &conditions[publication_date][gte]=2024-01-01
  &conditions[agencies][]=trade-representative
  &order=newest
  &per_page=50

Response:
{
  "count": 42,
  "results": [
    {
      "document_number": "2024-21217",
      "publication_date": "2024-09-18",
      "title": "Notice of Modification...",
      "effective_on": "2024-09-27",
      "pdf_url": "https://...",
      "full_text_xml_url": "https://...",
      "html_url": "https://..."
    }
  ]
}
```

### 13.2 USITC RESTStop API

```
Base URL: https://hts.usitc.gov/reststop

GET /search?keyword=6307.90.98

Response:
[
  {
    "htsno": "6307.90.98",
    "description": "Other made up articles...",
    "general": "7%",
    "special": "Free (AU,BH,CA,CL...)",
    "other": "40%",
    "footnotes": ["See chapter 99 statistical note 1"]
  }
]
```

### 13.3 Internal Ingest Job API

```
POST /api/internal/ingest
{
  "source": "federal_register",
  "external_id": "2024-21217",
  "url": "https://www.federalregister.gov/documents/full_text/xml/2024/09/18/2024-21217.xml"
}

Response:
{
  "job_id": "uuid",
  "status": "queued"
}

GET /api/internal/ingest/{job_id}

Response:
{
  "job_id": "uuid",
  "status": "committed",
  "document_id": "uuid",
  "changes_applied": 47,
  "evidence_packets": 47
}
```

---

## 14. Critical Refinements & Risk Mitigations

### 14.1 Job + Document Versioning (HIGH PRIORITY)

**Problem:** Current `UNIQUE(source, external_id)` on `ingest_jobs` prevents reprocessing when:
- A notice is corrected/amended
- Attachments change
- Parser is improved and needs re-run

**Fix:**

```sql
-- REVISED ingest_jobs table
CREATE TABLE ingest_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source identification
    source VARCHAR(50) NOT NULL,
    external_id VARCHAR(100) NOT NULL,
    url VARCHAR(500),

    -- VERSIONING (NEW)
    revision_number INTEGER DEFAULT 1,
    source_updated_at TIMESTAMP,  -- From API metadata
    content_hash VARCHAR(64),      -- Hash of fetched content
    parent_job_id UUID REFERENCES ingest_jobs(id),  -- Previous processing attempt

    -- Processing attempt tracking
    attempt_number INTEGER DEFAULT 1,
    processing_reason VARCHAR(100),  -- initial, correction, reparse, attachment_change

    -- ... rest of fields ...

    -- REVISED CONSTRAINT: Allow multiple jobs per external_id
    UNIQUE(source, external_id, content_hash)
);

-- official_documents remains unique on content
-- UNIQUE(source, external_id, content_hash) already correct
```

**Workflow:**
```
1. Watcher detects document
2. Check: Does ingest_job exist for (source, external_id)?
   - If NO: Create new job
   - If YES: Fetch content, compute hash
     - If hash differs: Create NEW job with parent_job_id = previous
     - If hash same: Skip (already processed)
3. Federal Register API provides "updated_at" - use this to detect corrections
```

### 14.2 Worker Production Reliability (HIGH PRIORITY)

**Problem:** APScheduler inside Flask duplicates jobs when running multiple web instances.

**Fix:** Separate scheduler service with DB-based locking:

```python
# app/workers/job_processor.py

class JobProcessor:
    """
    Production-grade job processor with DB locking.

    Runs as separate service, NOT inside Flask web process.
    """

    def claim_next_job(self) -> Optional[IngestJob]:
        """
        Claim next available job using FOR UPDATE SKIP LOCKED.

        Prevents duplicate processing across multiple workers.
        """
        job = db.session.execute(text("""
            SELECT * FROM ingest_jobs
            WHERE status = 'queued'
            ORDER BY discovered_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """)).fetchone()

        if job:
            # Mark as claimed
            db.session.execute(text("""
                UPDATE ingest_jobs
                SET status = 'processing',
                    claimed_by = :worker_id,
                    claimed_at = NOW()
                WHERE id = :job_id
            """), {"worker_id": self.worker_id, "job_id": job.id})
            db.session.commit()

        return job
```

**Deployment Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│  PRODUCTION DEPLOYMENT                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  WEB TIER (Multiple Instances)                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  Flask #1   │  │  Flask #2   │  │  Flask #3   │            │
│  │  (Gunicorn) │  │  (Gunicorn) │  │  (Gunicorn) │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│         │                │                │                    │
│         └────────────────┼────────────────┘                    │
│                          ▼                                      │
│                    ┌───────────┐                               │
│                    │    DB     │                               │
│                    │ (Postgres)│                               │
│                    └───────────┘                               │
│                          ▲                                      │
│         ┌────────────────┼────────────────┐                    │
│         │                │                │                    │
│  WORKER TIER (Separate Processes)                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  Scheduler  │  │  Worker #1  │  │  Worker #2  │            │
│  │  (1 only)   │  │ (processor) │  │ (processor) │            │
│  │             │  │             │  │             │            │
│  │ Runs        │  │ Claims jobs │  │ Claims jobs │            │
│  │ watchers    │  │ via SKIP    │  │ via SKIP    │            │
│  │ on cron     │  │ LOCKED      │  │ LOCKED      │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 14.3 Temporal Tables for ALL Programs (HIGH PRIORITY)

**Problem:** Only Section 301 has temporal tracking. Section 232 and IEEPA can also change.

**Fix:** Create temporal tables for all programs:

```sql
-- Section 232 temporal rates
CREATE TABLE section_232_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- HTS identification
    hts_8digit VARCHAR(10) NOT NULL,
    material_type VARCHAR(20) NOT NULL,  -- steel, aluminum, copper

    -- Chapter 99 codes
    chapter_99_claim VARCHAR(12) NOT NULL,
    chapter_99_disclaim VARCHAR(12),

    -- Rate
    duty_rate NUMERIC(5,4) NOT NULL,

    -- Country exception (NEW - for UK 25% vs global 50%)
    country_code VARCHAR(3),  -- NULL = all countries, 'GBR' = UK exception

    -- Temporal
    effective_start DATE NOT NULL,
    effective_end DATE,

    -- Audit
    source_doc_id UUID REFERENCES official_documents(id),
    evidence_id UUID REFERENCES evidence_packets(id),

    UNIQUE(hts_8digit, material_type, country_code, effective_start)
);

-- IEEPA temporal rates
CREATE TABLE ieepa_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Program identification
    program_type VARCHAR(20) NOT NULL,  -- fentanyl, reciprocal

    -- Country scope
    country_code VARCHAR(3),  -- NULL = all, 'CHN', 'HKG', 'MAC'

    -- Chapter 99 codes
    chapter_99_code VARCHAR(12) NOT NULL,

    -- Rate
    duty_rate NUMERIC(5,4) NOT NULL,

    -- Conditions
    condition_type VARCHAR(50),  -- metal_exempt, annex_ii_exclusion

    -- Temporal
    effective_start DATE NOT NULL,
    effective_end DATE,

    -- Audit
    source_doc_id UUID REFERENCES official_documents(id),

    UNIQUE(program_type, country_code, chapter_99_code, effective_start)
);
```

### 14.4 Staged/Multi-Date Changes in Extraction (MEDIUM PRIORITY)

**Problem:** `CandidateChange` assumes single `effective_date`, but notices often have schedules:
- "25% effective Jan 1, 2025"
- "50% effective Jan 1, 2026"

**Fix:** Revised CandidateChange model:

```python
@dataclass
class CandidateChange:
    """
    A proposed tariff change extracted from a document.

    Supports staged implementations with multiple effective dates.
    """
    document_id: UUID
    hts_code: str

    # Chapter 99 codes
    old_chapter_99_code: Optional[str]
    new_chapter_99_code: str

    # STAGED RATES (NEW)
    rate_schedule: List[RateScheduleEntry]  # Can have multiple entries

    # Evidence
    evidence_quote: str
    evidence_chunk_id: UUID
    evidence_line_start: int
    evidence_line_end: int

    extraction_method: str  # xml_table, llm_rag


@dataclass
class RateScheduleEntry:
    """Single rate entry in a staged schedule."""
    rate: Decimal
    effective_start: date
    effective_end: Optional[date]  # NULL = until superseded


# Example extraction from 2024 Four-Year Review:
# CandidateChange(
#     hts_code="6307.90.98",
#     new_chapter_99_code="9903.91.07",
#     rate_schedule=[
#         RateScheduleEntry(rate=0.25, effective_start=date(2025,1,1), effective_end=date(2025,12,31)),
#         RateScheduleEntry(rate=0.50, effective_start=date(2026,1,1), effective_end=None),
#     ],
#     ...
# )
```

### 14.5 Evidence for Deterministic XML Extraction (HIGH PRIORITY)

**Problem:** XML table extraction marks evidence as "TODO" - loses audit trail.

**Fix:** Track line numbers during XML rendering:

```python
# app/workers/xml_table_extractor.py

class XMLTableExtractor:
    """
    Deterministic extraction with REAL evidence tracking.
    """

    def extract_tables(self, raw_bytes: bytes, canonical_text: str) -> List[ExtractedRate]:
        """
        Parse tables AND track line numbers for evidence.
        """
        root = ET.fromstring(raw_bytes)
        results = []

        # Build line-to-content index from canonical_text
        line_index = self._build_line_index(canonical_text)

        for table in root.iter("GPOTABLE"):
            for row in table.findall(".//ROW"):
                entries = row.findall("ENT")
                if len(entries) >= 3:
                    hts_code = self._clean_hts(entries[0].text or "")

                    if self._is_valid_hts(hts_code):
                        # FIND EVIDENCE LINE NUMBERS
                        line_start, line_end = self._find_line_range(
                            line_index,
                            hts_code,
                            entries[2].text or ""  # rate
                        )

                        results.append(ExtractedRate(
                            hts_code=hts_code,
                            description=entries[1].text or "",
                            rate=self._parse_rate(entries[2].text or ""),
                            effective_year=self._parse_year(entries[3].text or ""),
                            line_start=line_start,  # REAL VALUE
                            line_end=line_end,       # REAL VALUE
                            evidence_quote=self._extract_quote(canonical_text, line_start, line_end),
                        ))

        return results

    def _build_line_index(self, canonical_text: str) -> dict:
        """Build searchable index of line numbers to content."""
        index = {}
        for i, line in enumerate(canonical_text.split("\n"), 1):
            # Strip line number prefix (L0001: content)
            content = line.split(": ", 1)[1] if ": " in line else line
            index[i] = content
        return index

    def _find_line_range(self, line_index: dict, hts_code: str, rate_str: str) -> Tuple[int, int]:
        """Find lines containing both HTS code and rate."""
        for line_num, content in line_index.items():
            if hts_code in content and rate_str in content:
                return (line_num, line_num)
        return (0, 0)  # Not found - will fail write gate
```

### 14.6 Section 232 Derivative Bucket Logic (MEDIUM PRIORITY)

**Problem:** Section 232 derivatives have different Chapter 99 codes based on HTS Chapter:
- Steel derivatives in Chapter 73: `9903.81.90`
- Steel derivatives NOT in Chapter 73: `9903.81.91`

**Fix:** Add HTS Chapter check to CandidateChange processing:

```python
# app/workers/section_232_processor.py

class Section232Processor:
    """
    Processes Section 232 changes with correct bucket assignment.
    """

    # Derivative bucket mapping
    DERIVATIVE_BUCKETS = {
        "steel": {
            "primary_chapters": ["72", "73"],
            "primary_code": "9903.80.01",
            "derivative_in_chapter": "9903.81.90",   # Ch 73 derivatives
            "derivative_other": "9903.81.91",        # Non-Ch 73 derivatives
        },
        "aluminum": {
            "primary_chapters": ["76"],
            "primary_code": "9903.85.03",
            "derivative_in_chapter": "9903.85.07",   # Ch 76 derivatives
            "derivative_other": "9903.85.08",        # Non-Ch 76 derivatives
        },
        "copper": {
            "primary_chapters": ["74"],
            "primary_code": "9903.78.01",
            "derivative_in_chapter": None,           # No separate bucket
            "derivative_other": None,
        },
    }

    def assign_chapter_99_code(self, hts_code: str, material: str, is_derivative: bool) -> str:
        """
        Assign correct Chapter 99 code based on HTS chapter.
        """
        bucket = self.DERIVATIVE_BUCKETS.get(material)
        if not bucket:
            raise ValueError(f"Unknown material: {material}")

        if not is_derivative:
            return bucket["primary_code"]

        # Check HTS chapter
        hts_chapter = hts_code[:2]

        if hts_chapter in bucket["primary_chapters"]:
            return bucket["derivative_in_chapter"] or bucket["primary_code"]
        else:
            return bucket["derivative_other"] or bucket["primary_code"]
```

### 14.7 USITC API Authentication (MEDIUM PRIORITY)

**Problem:** USITC RESTStop API requires Login.gov account for high-volume automated access.

**Fix:** Add authentication support to USITC watcher:

```python
# app/watchers/usitc_watcher.py

class USITCWatcher:
    """
    USITC HTS watcher with Login.gov authentication.

    For bulk/high-volume access, Login.gov MFA is required.
    For occasional lookups, anonymous access may work.
    """

    def __init__(self, config):
        self.login_gov_email = config.get("LOGIN_GOV_EMAIL")
        self.login_gov_password = config.get("LOGIN_GOV_PASSWORD")
        self.mfa_secret = config.get("LOGIN_GOV_MFA_SECRET")  # TOTP secret

        self.session = requests.Session()
        self.authenticated = False

    def authenticate(self):
        """
        Authenticate with Login.gov for USITC access.

        Uses TOTP for MFA (requires storing MFA secret securely).
        """
        if self.authenticated:
            return

        # Step 1: Get CSRF token from login page
        login_page = self.session.get("https://hts.usitc.gov/login")
        csrf_token = self._extract_csrf(login_page.text)

        # Step 2: Submit credentials
        # (Login.gov redirects through OAuth flow)

        # Step 3: Handle MFA
        import pyotp
        totp = pyotp.TOTP(self.mfa_secret)
        mfa_code = totp.now()

        # Step 4: Complete authentication
        # ... OAuth flow completion ...

        self.authenticated = True

    def search(self, keyword: str) -> dict:
        """Search with authentication if configured."""
        if self.login_gov_email:
            self.authenticate()

        response = self.session.get(
            f"https://hts.usitc.gov/reststop/search",
            params={"keyword": keyword}
        )
        return response.json()
```

**Configuration:**
```python
# Environment variables (stored securely)
USITC_LOGIN_GOV_EMAIL=your-email@example.com
USITC_LOGIN_GOV_PASSWORD=<encrypted>
USITC_LOGIN_GOV_MFA_SECRET=<totp-secret>  # From Login.gov setup
```

### 14.8 UK Rate Exception for Section 232 (MEDIUM PRIORITY)

**Problem:** UK has 25% rate vs global 50% rate for Section 232 steel/aluminum.

**Fix:** Country exception handling in temporal table and queries:

```python
# app/chat/tools/stacking_tools.py (MODIFIED)

def get_section_232_rate(hts_code: str, material: str, country: str, as_of_date: date) -> dict:
    """
    Get Section 232 rate with country exception handling.
    """
    hts_8digit = hts_code.replace(".", "")[:8]

    # Try country-specific rate first
    rate_record = Section232Rate.query.filter(
        Section232Rate.hts_8digit == hts_8digit,
        Section232Rate.material_type == material,
        Section232Rate.country_code == get_country_code(country),  # e.g., 'GBR'
        Section232Rate.effective_start <= as_of_date,
        db.or_(
            Section232Rate.effective_end.is_(None),
            Section232Rate.effective_end > as_of_date
        )
    ).first()

    # Fall back to global rate (country_code = NULL)
    if not rate_record:
        rate_record = Section232Rate.query.filter(
            Section232Rate.hts_8digit == hts_8digit,
            Section232Rate.material_type == material,
            Section232Rate.country_code.is_(None),  # Global rate
            Section232Rate.effective_start <= as_of_date,
            db.or_(
                Section232Rate.effective_end.is_(None),
                Section232Rate.effective_end > as_of_date
            )
        ).first()

    if rate_record:
        return {
            "included": True,
            "rate": float(rate_record.duty_rate),
            "chapter_99_claim": rate_record.chapter_99_claim,
            "country_exception": rate_record.country_code is not None,
        }

    return {"included": False}


# Country code mapping
COUNTRY_CODES = {
    "United Kingdom": "GBR",
    "UK": "GBR",
    "Great Britain": "GBR",
    # ... other countries ...
}
```

---

## 15. Updated Implementation Phases

### Phase 1: Quick Fix (1-2 days) - UNCHANGED
- Import 2024 Four-Year Review manually

### Phase 2: Temporal Schema (5-7 days) - EXPANDED
- [ ] Create section_301_rates table
- [ ] **NEW:** Create section_232_rates table with country_exception
- [ ] **NEW:** Create ieepa_rates table
- [ ] Migrate existing data
- [ ] Modify stacking_tools.py for temporal queries
- [ ] **NEW:** Implement UK rate exception logic

### Phase 3: Watchers (7-10 days) - EXPANDED
- [ ] Implement FederalRegisterWatcher with revision tracking
- [ ] **NEW:** Implement job versioning (allow re-processing)
- [ ] **NEW:** Separate scheduler service (not in Flask)
- [ ] **NEW:** DB locking (FOR UPDATE SKIP LOCKED)
- [ ] Implement ingest_jobs queue
- [ ] **NEW:** USITC Login.gov authentication

### Phase 4: Document Pipeline (7-10 days) - UNCHANGED

### Phase 5: RAG Extraction (7-10 days) - EXPANDED
- [ ] Implement XMLTableExtractor with REAL line tracking
- [ ] **NEW:** Support staged rate schedules (multi-date)
- [ ] **NEW:** Section 232 derivative bucket logic
- [ ] Implement RAG extraction for narrative

### Phase 6: Validation + Write Gate (5-7 days) - UNCHANGED

### Phase 7: UI + Freshness (2-3 days) - UNCHANGED

---

## 16. Risk Summary

| Risk | Severity | Mitigation | Section |
|------|----------|------------|---------|
| Job can't be reprocessed | HIGH | Versioning on content_hash | 14.1 |
| Duplicate jobs in production | HIGH | Separate scheduler + DB locks | 14.2 |
| 232/IEEPA rates change, missed | HIGH | Temporal tables for all programs | 14.3 |
| Staged rates not captured | MEDIUM | Multi-entry rate_schedule | 14.4 |
| XML extraction loses audit | HIGH | Real line number tracking | 14.5 |
| Wrong 232 derivative bucket | MEDIUM | HTS Chapter check logic | 14.6 |
| USITC rate-limited | MEDIUM | Login.gov authentication | 14.7 |
| UK 232 rate wrong | MEDIUM | Country exception flag | 14.8 |

---

*Document generated: January 10, 2026*
*Last updated: January 10, 2026 - Added critical refinements (Section 14-16)*
