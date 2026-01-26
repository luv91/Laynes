# Section 301 Trade Compliance Engine - Design Document

---

## 1. CURRENT vs NEXT DESIGN COMPARISON

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         SECTION 301 ENGINE DESIGN COMPARISON                             │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### CURRENT STATE (Baseline)

```
INPUTS                           ENGINE                              OUTPUTS
──────                           ──────                              ───────

┌─────────────┐              ┌─────────────────┐              ┌─────────────────┐
│ • COO       │              │                 │              │ • applies: bool │
│ • HTS10     │─────────────▶│  Simple Lookup  │─────────────▶│ • rate: %       │
│ • entry_date│              │  (HTS match)    │              │ • ch99_heading  │
└─────────────┘              └─────────────────┘              └─────────────────┘

LIMITATIONS:
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ ✗ No source versioning (can't reproduce historical evaluations)                     │
│ ✗ No temporal windows (doesn't handle phased rate changes)                          │
│ ✗ Manual data updates (no automated ingestion pipeline)                             │
│ ✗ No exclusion verification workflow                                                │
│ ✗ No HTS revision handling (breaks when codes renumber)                             │
│ ✗ No TBD rate handling (semiconductors 2027)                                        │
│ ✗ No audit trail for compliance defense                                             │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### NEXT DESIGN (Target Architecture)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              NEXT DESIGN - FULL ARCHITECTURE                             │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────┐
│            INPUTS               │
│                                 │
│  • COO (country of origin)      │
│  • HTS10 (10-digit code)        │
│  • entry_date (or as_of_date)   │
│  • [product_description]        │
│  • [structured_attributes]      │
└────────────────┬────────────────┘
│
┌─────────────────────────────────────┼─────────────────────────────────────┐
│                                     ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────┐   │
│  │                    LAYER 1: DETERMINISTIC CORE                    │   │
│  │                    (System of Record - No LLM)                    │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                     │                                     │
│    ┌────────────────────────────────┼────────────────────────────────┐   │
│    │                                ▼                                │   │
│    │  ┌──────────────────────────────────────────────────────────┐  │   │
│    │  │              STEP 1: COUNTRY GATE                        │  │   │
│    │  │                                                          │  │   │
│    │  │   If COO != CN → Return {applies: false, reason: "No301"}│  │   │
│    │  │   (HK/MO are != CN, so automatically excluded)           │  │   │
│    │  └──────────────────────────────────────────────────────────┘  │   │
│    │                                │                                │   │
│    │                                ▼                                │   │
│    │  ┌──────────────────────────────────────────────────────────┐  │   │
│    │  │              STEP 2: HTS VALIDATION                      │  │   │
│    │  │                                                          │  │   │
│    │  │   Query hts_code_history:                                │  │   │
│    │  │   • Is HTS10 valid on entry_date?                        │  │   │
│    │  │   • If invalid → return INVALID_HTS_FOR_DATE             │  │   │
│    │  │                  + suggested_codes[]                     │  │   │
│    │  └──────────────────────────────────────────────────────────┘  │   │
│    │                                │                                │   │
│    │                                ▼                                │   │
│    │  ┌──────────────────────────────────────────────────────────┐  │   │
│    │  │              STEP 3: INCLUSION MATCH                     │  │   │
│    │  │                                                          │  │   │
│    │  │   Query tariff_measures WHERE:                           │  │   │
│    │  │   • effective_start <= entry_date < effective_end        │  │   │
│    │  │   • Match HTS10 first (exact)                            │  │   │
│    │  │   • Fallback HTS8 (exact)                                │  │   │
│    │  │   • NO cascade to HTS6/4/2                               │  │   │
│    │  │                                                          │  │   │
│    │  │   If no match → Return {applies: false}                  │  │   │
│    │  └──────────────────────────────────────────────────────────┘  │   │
│    │                                │                                │   │
│    │                                ▼                                │   │
│    │  ┌──────────────────────────────────────────────────────────┐  │   │
│    │  │              STEP 4: EXCLUSION CHECK                     │  │   │
│    │  │                                                          │  │   │
│    │  │   Query exclusion_claims WHERE:                          │  │   │
│    │  │   • HTS matches constraints                              │  │   │
│    │  │   • effective_start <= entry_date < effective_end        │  │   │
│    │  │                                                          │  │   │
│    │  │   If match found:                                        │  │   │
│    │  │   • has_exclusion_candidate = true                       │  │   │
│    │  │   • verification_required = true (ALWAYS)                │  │   │
│    │  │   • Trigger Layer 2 for verification help                │  │   │
│    │  └──────────────────────────────────────────────────────────┘  │   │
│    │                                │                                │   │
│    │                                ▼                                │   │
│    │  ┌──────────────────────────────────────────────────────────┐  │   │
│    │  │              STEP 5: RATE STATUS CHECK                   │  │   │
│    │  │                                                          │  │   │
│    │  │   If additional_rate IS NULL:                            │  │   │
│    │  │   • rate_status = "pending"                              │  │   │
│    │  │   • confidence_status = PENDING_PUBLICATION              │  │   │
│    │  │   Else:                                                  │  │   │
│    │  │   • rate_status = "confirmed"                            │  │   │
│    │  └──────────────────────────────────────────────────────────┘  │   │
│    │                                │                                │   │
│    │                                ▼                                │   │
│    │  ┌──────────────────────────────────────────────────────────┐  │   │
│    │  │              STEP 6: FUTURE DATE CHECK                   │  │   │
│    │  │                                                          │  │   │
│    │  │   If entry_date > today:                                 │  │   │
│    │  │   • is_future_date = true                                │  │   │
│    │  │   • confidence_status = SCHEDULED | PENDING_PUBLICATION  │  │   │
│    │  └──────────────────────────────────────────────────────────┘  │   │
│    └────────────────────────────────┼────────────────────────────────┘   │
│                                     │                                     │
└─────────────────────────────────────┼─────────────────────────────────────┘
│
│ (if exclusion candidate exists)
▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │               LAYER 2: LLM-ASSISTED VERIFICATION HELPER              │ │
│  │               (Advisory Only - Never Auto-Approves)                  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────┐ │
│  │ A. SEMANTIC     │    │ B. CONSTRAINT   │    │ C. CHECKLIST           │ │
│  │    RETRIEVAL    │    │    EXTRACTION   │    │    GENERATION          │ │
│  │                 │    │    (Gemini)     │    │                         │ │
│  │ • Embed product │    │ • Parse excl.   │    │ • Required evidence    │ │
│  │   description   │    │   scope text    │    │ • Missing attributes   │ │
│  │ • Retrieve top  │    │ • Extract hard  │    │ • Pass/fail/unknown    │ │
│  │   N candidates  │    │   constraints   │    │   per constraint       │ │
│  │ • Score + rank  │    │   (weight, dim, │    │ • Confidence score     │ │
│  │                 │    │   material...)  │    │                         │ │
│  └────────┬────────┘    └────────┬────────┘    └────────────┬────────────┘ │
│           │                      │                          │              │
│           └──────────────────────┼──────────────────────────┘              │
│                                  │                                         │
│                                  ▼                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                    VERIFICATION PACKET                                │ │
│  │                                                                       │ │
│  │  {                                                                    │ │
│  │    "exclusion_candidates": [...],                                     │ │
│  │    "extracted_constraints": [...],                                    │ │
│  │    "constraint_results": {passed: [], failed: [], unknown: []},       │ │
│  │    "evidence_checklist": ["datasheet", "COO cert", ...],              │ │
│  │    "match_score": 0.87,                                               │ │
│  │    "verification_status": "REVIEW_REQUIRED"  ← ALWAYS                 │ │
│  │  }                                                                    │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FINAL OUTPUT                                    │
│                                                                             │
│  {                                                                          │
│    "applies": true,                                                         │
│    "chapter99_heading": "9903.91.03",                                       │
│    "additional_rate": 100,                                                  │
│    "rate_status": "confirmed" | "pending",                                  │
│    "legal_basis": "Note 31, Subdivision (d)",                               │
│    "source_version": "USTR_FRN_2024-29462",                                 │
│                                                                             │
│    "exclusion": {                                                           │
│      "has_candidate": true,                                                 │
│      "claim_ch99_heading": "9903.88.69",                                    │
│      "verification_required": true,                                         │
│      "verification_packet": {...}                                           │
│    },                                                                       │
│                                                                             │
│    "temporal": {                                                            │
│      "is_future_date": false,                                               │
│      "confidence_status": "CONFIRMED"                                       │
│    },                                                                       │
│                                                                             │
│    "hts_validation": {                                                      │
│      "status": "VALID",                                                     │
│      "suggested_codes": null                                                │
│    }                                                                        │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. DATA MODEL

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                    DATA MODEL                                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

CURRENT (Minimal)                          NEXT (Full SCD Type 2 + Audit)
─────────────────                          ──────────────────────────────

┌─────────────────────┐                    ┌─────────────────────────────────────────────┐
│ section301_rates    │                    │ tariff_measures (SCD Type 2)                │
│                     │                    │                                             │
│ • hts_code          │                    │ • id (PK)                                   │
│ • rate              │                    │ • program ("301_NOTE20" | "301_NOTE31")     │
│ • list_number       │                    │ • ch99_heading                              │
│                     │                    │ • scope_hts_type (HTS8 | HTS10)             │
│ (no dates)          │                    │ • scope_hts_value                           │
│ (no versioning)     │                    │ • additional_rate (NULL = TBD)              │
│ (no legal basis)    │                    │ • rate_status (confirmed | pending)         │
└─────────────────────┘                    │ • legal_basis (subdivision ref)             │
│ • effective_start                           │
│ • effective_end (NULL = open)               │
│ • source_version_id (FK)                    │
│ • created_at, updated_at                    │
└─────────────────────────────────────────────┘

(none)                                     ┌─────────────────────────────────────────────┐
│ exclusion_claims                            │
│                                             │
│ • id (PK)                                   │
│ • note_bucket ("20(vvv)" | "20(www)")       │
│ • claim_ch99_heading (9903.88.69/70)        │
│ • hts_constraints (JSONB)                   │
│ • description_scope_text                    │
│ • effective_start                           │
│ • effective_end                             │
│ • source_version_id (FK)                    │
│ • verification_required (default: true)    │
└─────────────────────────────────────────────┘

(none)                                     ┌─────────────────────────────────────────────┐
│ hts_code_history (Dual Indexing)            │
│                                             │
│ • id (PK)                                   │
│ • hts_type (8 | 10)                         │
│ • code                                      │
│ • valid_from                                │
│ • valid_to (end-exclusive)                  │
│ • replaced_by_code (nullable)               │
│ • canonical_concept_id (optional)           │
│ • source_version_id (FK)                    │
└─────────────────────────────────────────────┘

(none)                                     ┌─────────────────────────────────────────────┐
│ source_versions (Audit Backbone)            │
│                                             │
│ • id (PK)                                   │
│ • source_type (USTR_FRN | USITC_CHINA |    │
│                USITC_HTS | CBP_CSMS | ...)  │
│ • publisher (USTR | USITC | CBP)            │
│ • document_id                               │
│ • published_at                              │
│ • retrieved_at                              │
│ • content_hash (sha256)                     │
│ • effective_start (if stated)               │
│ • effective_end (if stated)                 │
│ • supersedes_source_version_id (nullable)   │
│ • raw_artifact_path                         │
└─────────────────────────────────────────────┘
```

---

## 3. INGESTION PIPELINE (Future Updates)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         AUTOMATED INGESTION PIPELINE                                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│           INGESTION TRIGGERS            │
└─────────────────────────────────────────┘
│
┌─────────────────────────────┼─────────────────────────────┐
│                             │                             │
▼                             ▼                             ▼
┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
│     DAILY       │          │     WEEKLY      │          │   PER-RELEASE   │
│                 │          │                 │          │                 │
│ • CBP CSMS feed │          │ • USITC China   │          │ • USITC HTS     │
│ • USTR FR       │          │   Tariffs diff  │          │   Archive       │
│   monitoring    │          │                 │          │ • Exclusion     │
│                 │          │                 │          │   extensions    │
└────────┬────────┘          └────────┬────────┘          └────────┬────────┘
│                             │                             │
└─────────────────────────────┼─────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: FETCH & HASH                                                                     │
│                                                                                          │
│  ┌───────────────┐     ┌───────────────┐     ┌───────────────┐                          │
│  │ Download raw  │────▶│ Compute SHA256│────▶│ Compare to    │                          │
│  │ source file   │     │ content_hash  │     │ last ingestion│                          │
│  └───────────────┘     └───────────────┘     └───────┬───────┘                          │
│                                                      │                                   │
│                              ┌────────────────────────┴────────────────────────┐        │
│                              │                                                 │        │
│                              ▼                                                 ▼        │
│                     ┌─────────────────┐                            ┌──────────────┐    │
│                     │ HASH UNCHANGED  │                            │ HASH CHANGED │    │
│                     │ Skip ingestion  │                            │ Continue...  │    │
│                     └─────────────────┘                            └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: CREATE SOURCE VERSION RECORD                                                     │
│                                                                                          │
│  INSERT INTO source_versions (                                                           │
│    source_type, publisher, document_id,                                                  │
│    published_at, retrieved_at, content_hash,                                             │
│    raw_artifact_path                                                                     │
│  )                                                                                       │
│                                                                                          │
│  Store raw file to: /artifacts/{source_type}/{document_id}/{hash}.raw                    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: PARSE & DIFF (Source-Specific)                                                   │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐    │
│  │ USITC_CHINA_TARIFFS:                                                            │    │
│  │ • Parse CSV → extract HTS8/10 + List assignment                                 │    │
│  │ • Diff against current tariff_measures                                          │    │
│  │ • Identify: ADDED, REMOVED, CHANGED rows                                        │    │
│  ├─────────────────────────────────────────────────────────────────────────────────┤    │
│  │ USTR_FRN:                                                                       │    │
│  │ • Parse FR notice → extract rate changes, effective dates                       │    │
│  │ • Map to Note 20/31 subdivisions                                                │    │
│  │ • Identify affected ch99_headings                                               │    │
│  ├─────────────────────────────────────────────────────────────────────────────────┤    │
│  │ USITC_HTS:                                                                      │    │
│  │ • Parse HTS release → extract code validity windows                             │    │
│  │ • Build hts_code_history entries                                                │    │
│  │ • Detect renumbered codes → populate replaced_by_code                           │    │
│  ├─────────────────────────────────────────────────────────────────────────────────┤    │
│  │ USTR_EXCLUSION:                                                                 │    │
│  │ • Parse extension notice → update effective_end dates                           │    │
│  │ • Add new exclusion_claims if any                                               │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: APPLY CHANGES (SCD Type 2)                                                       │
│                                                                                          │
│  FOR EACH changed record:                                                                │
│                                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐    │
│  │ IF existing row with same key:                                                  │    │
│  │   • Close out: SET effective_end = new_effective_start                          │    │
│  │   • INSERT new row with new source_version_id                                   │    │
│  │                                                                                 │    │
│  │ IF new row (no prior):                                                          │    │
│  │   • INSERT with effective_start from source                                     │    │
│  │                                                                                 │    │
│  │ IF removal (code no longer listed):                                             │    │
│  │   • Close out: SET effective_end = source published_at                          │    │
│  │   • Do NOT delete (preserve history)                                            │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: VALIDATE & LOG                                                                   │
│                                                                                          │
│  • Run sanity checks (row counts, rate bounds, date logic)                               │
│  • Log ingestion_run with stats: added/changed/closed counts                             │
│  • Alert on anomalies (e.g., >100 changes, rate >200%)                                   │
│  • Update data freshness dashboard                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. CONFLICT RESOLUTION & SOURCE HIERARCHY

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              SOURCE HIERARCHY                                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

TIER 0 — Binding Legal Authority (HIGHEST PRIORITY)
├── USTR Federal Register Notices + Technical Corrections
└── HTS Chapter 99 Legal Text (Notes 20 & 31)

TIER 1 — Authoritative Reference Datasets
├── USITC "China Tariffs" machine-readable CSV
└── USITC HTS Archive (versioned releases)

TIER 2 — Operational Filing Guidance
└── CBP Section 301 FAQs + CSMS Messages

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         CONFLICT RESOLUTION RULES                                        │
└─────────────────────────────────────────────────────────────────────────────────────────┘

SCENARIO                                    RESOLUTION
────────                                    ──────────

USITC CSV says HTS is on List 1,           Tier 0 wins. Flag discrepancy for review.
but USTR FRN says it's excluded            Log: "Source conflict: {hts} on {date}"

Two sources have different rates           Use USTR FRN rate (Tier 0).
for same HTS/date                          Store both source_version_ids for audit.

Exclusion extension extends date,          Create new exclusion_claims row with
but original entry still exists            updated effective_end. Link via
supersedes_source_version_id.

HTS code renumbered mid-year               Close old code in hts_code_history.
Insert new code with replaced_by link.
Update tariff_measures with new HTS.

Rate becomes TBD (semiconductors)          Insert row with additional_rate = NULL,
rate_status = "pending".
Engine returns PENDING_PUBLICATION.

┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              PRECEDENCE RULES                                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

1. EXCLUSION > INCLUSION
└── Validated exclusion claim bypasses standard rate

2. HTS10 > HTS8
└── Most specific enumerated match wins

3. SPECIFICITY + RECENCY
└── If ties: latest source_version wins

4. TIER 0 > TIER 1 > TIER 2
└── Legal authority trumps reference data trumps guidance
```

---

## 5. DESIGN DECISIONS (Locked)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           DESIGN DECISIONS                                               │
└─────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┬─────────────────────────────────────────────────────────────────────┐
│ QUESTION        │ DECISION                                                            │
├─────────────────┼─────────────────────────────────────────────────────────────────────┤
│ TBD Rates       │ Store with NULL rate + rate_status="pending"                        │
│ (Semiconductors)│ Engine returns applies=true but confidence=PENDING_PUBLICATION      │
│                 │ Caller decides how to handle (block, warn, estimate)                │
├─────────────────┼─────────────────────────────────────────────────────────────────────┤
│ Exclusion       │ Soft match + flag (Option 2)                                        │
│ Verification    │ • Always verification_required=true                                 │
│                 │ • LLM (Gemini) provides semantic retrieval + constraint extraction  │
│                 │ • Returns verification_packet with checklist, never auto-approves   │
├─────────────────┼─────────────────────────────────────────────────────────────────────┤
│ HTS Revisions   │ Dual indexing (Option 3)                                            │
│                 │ • hts_code_history table tracks validity windows                    │
│                 │ • Never silently remap codes                                        │
│                 │ • Return INVALID_HTS_FOR_DATE + suggested_codes if mismatch         │
├─────────────────┼─────────────────────────────────────────────────────────────────────┤
│ Future Date     │ Warn but allow (Option 2)                                           │
│ Queries         │ • Support what-if for planning/quoting                              │
│                 │ • Return is_future_date=true + confidence_status                    │
│                 │ • CONFIRMED / SCHEDULED / PENDING_PUBLICATION                       │
└─────────────────┴─────────────────────────────────────────────────────────────────────┘
```

---

## 6. REFRESH CADENCE

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              INGESTION SCHEDULE                                          │
└─────────────────────────────────────────────────────────────────────────────────────────┘

FREQUENCY        SOURCE                          ACTION
─────────        ──────                          ──────

DAILY            CBP CSMS feed                   Poll for new bulletins
(automated)      USTR Federal Register           Monitor for new notices/corrections

WEEKLY           USITC "China Tariffs" CSV       Diff check (even if release unchanged)

PER-RELEASE      USITC HTS Archive               Ingest each Basic Edition + Revisions
(immediate)      USTR Exclusion extensions       Update effective_end dates immediately

ON-DEMAND        Technical corrections           Manual trigger when announced
Rate TBD announcements          Update pending → confirmed
```

---

## 7. KEY DESIGN PRINCIPLES

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           DESIGN PRINCIPLES                                              │
└─────────────────────────────────────────────────────────────────────────────────────────┘

1. DETERMINISTIC CORE
└── No LLM in critical evaluation path. Pure match + time-window + precedence.

2. SOURCE HIERARCHY
└── Tier 0 (USTR FRN) > Tier 1 (USITC CSV) > Tier 2 (CBP guidance)

3. SCD TYPE 2 VERSIONING
└── Full audit trail. Reproduce any historical evaluation exactly.

4. NO HTS6/4/2 FALLBACK
└── Section 301 is enumerated at HTS8/10. No cascading to avoid false positives.

5. END-EXCLUSIVE DATES
└── effective_start <= entry_date < effective_end
└── "through Nov 10" → effective_end = Nov 11

6. LLM AS ADVISORY ONLY
└── Exclusion verification uses Gemini for ranking/extraction
└── Never auto-approves. Always verification_required=true
```

---

## 8. OFFICIAL DATA SOURCES

| Source | URL | Refresh |
|--------|-----|---------|
| USITC HTS Archive | https://www.usitc.gov/harmonized_tariff_information/hts/archive/list | Per-release |
| USITC China Tariffs CSV | https://hts.usitc.gov/reststop/file?release=currentRelease&filename=China%20Tariffs | Weekly |
| USTR Federal Register | https://www.federalregister.gov (search USTR) | Daily |
| CBP Section 301 FAQs | https://www.cbp.gov/trade/programs-administration/entry-summary/section-301-trade-remedies/faqs | Daily |
| CBP CSMS Search | https://www.cbp.gov/trade/cargo-security/csms | Daily |

---

## 9. DATA SYNC ARCHITECTURE & FIX (January 25, 2026)

### 9.1 Problem Identified

**Data Discrepancy Across Storage Systems:**

| Storage | Row Count | Status |
|---------|-----------|--------|
| PostgreSQL (Railway) | 10,810 | Primary |
| SQLite (Local Dev) | 10,784 | 26 rows behind |
| CSV (Archive) | 10,785 | 25 rows behind |

### 9.2 Root Cause

The sync mechanism in `app/sync/pg_sync.py` checked for `id` uniqueness, but the actual database constraint was on the **business key**: `(hts_8digit, chapter_99_code, effective_start)`.

```
SYNC BUG:
─────────
1. PostgreSQL received direct data loads (bypassing SQLite)
2. SQLite → PostgreSQL sync tried to insert same business keys with different ids
3. Unique constraint violations occurred → rows silently skipped
4. Result: 26 rows in PostgreSQL never made it to SQLite
```

### 9.3 Solution Implemented

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                         DATA SYNC FIX - IMPLEMENTATION                                   │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  FIX 1: RECONCILIATION SCRIPT (One-Time)
  ────────────────────────────────────────
  File: scripts/reconcile_section_301.py

  • Compares business keys between PostgreSQL and SQLite
  • Pulls missing rows from PostgreSQL → SQLite
  • Handles Decimal/date type conversions for SQLite
  • Supports --dry-run mode for preview

  Usage:
    python scripts/reconcile_section_301.py --dry-run  # Preview
    python scripts/reconcile_section_301.py            # Execute


  FIX 2: REVERSE SYNC (PostgreSQL → SQLite)
  ─────────────────────────────────────────
  File: app/sync/pg_sync.py
  Function: sync_from_postgresql()

  • Uses business-key deduplication for tariff tables
  • Prevents duplicate inserts based on actual unique constraints
  • Supports all tables in SYNC_TABLES

  Usage:
    from app.sync.pg_sync import sync_from_postgresql
    result = sync_from_postgresql()


  FIX 3: CSV EXPORT WITH MANIFEST
  ────────────────────────────────
  File: app/sync/pg_sync.py
  Functions: export_to_csv(), export_all_tariff_tables(), update_manifest()

  • Exports tables to CSV for archival/backup
  • Generates manifest.json with checksums (SHA-256)
  • Tracks row counts and column metadata

  Usage:
    from app.sync.pg_sync import export_all_tariff_tables
    result = export_all_tariff_tables('data/current')
```

### 9.4 New Data Flow

```
  DATA FLOW (AFTER FIX):
  ──────────────────────

  ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
  │   DATA SOURCES  │      │   PostgreSQL    │      │     SQLite      │
  │                 │      │   (Primary)     │      │   (Local Dev)   │
  │ • USITC CSV     │      │                 │      │                 │
  │ • USTR FRN      │─────▶│   10,810 rows   │─────▶│   10,810 rows   │
  │ • Manual CSV    │      │                 │      │                 │
  └─────────────────┘      └─────────────────┘      └─────────────────┘
                                   │                        │
                                   │  ✅ REVERSE SYNC       │
                                   │     ENABLED            │
                                   ▼                        ▼
                           ┌─────────────────┐      ┌─────────────────┐
                           │      CSV        │      │    manifest     │
                           │   (Archive)     │      │     .json       │
                           │                 │      │                 │
                           │  10,810 rows    │      │  SHA-256 hashes │
                           └─────────────────┘      └─────────────────┘
```

### 9.5 Verification Results

```
=== FINAL DATA CONSISTENCY VERIFICATION ===

PostgreSQL (Railway):
  section_301_rates: 10,810 rows  ✅
  section_232_rates: 1,637 rows   ✅
  ieepa_rates: 45 rows            ✅

SQLite (Local):
  section_301_rates: 10,810 rows  ✅
  section_232_rates: 1,637 rows   ✅
  ieepa_rates: 45 rows            ✅

CSV (Export):
  section_301_rates: 10,810 rows  ✅
  section_232_rates: 1,637 rows   ✅
  ieepa_rates: 45 rows            ✅

STATUS: ALL SYSTEMS IN SYNC ✅
```

### 9.6 Files Modified/Created

| File | Action | Purpose |
|------|--------|---------|
| `scripts/reconcile_section_301.py` | Created | One-time data reconciliation |
| `app/sync/pg_sync.py` | Modified | Added reverse sync + CSV export |
| `data/current/manifest.json` | Created | Checksums and metadata |
| `data/current/section_301_rates.csv` | Exported | Current data snapshot |
| `data/current/section_232_rates.csv` | Exported | Current data snapshot |
| `data/current/ieepa_rates.csv` | Exported | Current data snapshot |

### 9.7 Maintenance Commands

```bash
# Check data consistency
python -c "
from app.sync.pg_sync import sync_from_postgresql, export_all_tariff_tables
print('Syncing from PostgreSQL...')
print(sync_from_postgresql())
print('Exporting to CSV...')
print(export_all_tariff_tables())
"

# Run reconciliation (if needed)
DATABASE_URL='postgresql://...' python scripts/reconcile_section_301.py --dry-run

# Verify manifest checksums
cat data/current/manifest.json | python -m json.tool
```