Section 301 Trade Compliance Engine - Design Document

 ---
 1. CURRENT vs NEXT DESIGN COMPARISON

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                         SECTION 301 ENGINE DESIGN COMPARISON                             │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

 CURRENT STATE (Baseline)

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

 NEXT DESIGN (Target Architecture)

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

 ---
 2. DATA MODEL

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

 ---
 3. INGESTION PIPELINE (Future Updates)

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

 ---
 4. CONFLICT RESOLUTION & SOURCE HIERARCHY

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

 ---
 5. DESIGN DECISIONS (Locked)

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

 ---
 6. REFRESH CADENCE

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

 ---
 7. KEY DESIGN PRINCIPLES

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

 ---
 8. OFFICIAL DATA SOURCES

 | Source                  | URL                                                                                             | Refresh     |
 |-------------------------|-------------------------------------------------------------------------------------------------|-------------|
 | USITC HTS Archive       | https://www.usitc.gov/harmonized_tariff_information/hts/archive/list                            | Per-release |
 | USITC China Tariffs CSV | https://hts.usitc.gov/reststop/file?release=currentRelease&filename=China%20Tariffs             | Weekly      |
 | USTR Federal Register   | https://www.federalregister.gov (search USTR)                                                   | Daily       |
 | CBP Section 301 FAQs    | https://www.cbp.gov/trade/programs-administration/entry-summary/section-301-trade-remedies/faqs | Daily       |
 | CBP CSMS Search         | https://www.cbp.gov/trade/cargo-security/csms                                                   | Daily       |

 ---
 9. MIGRATION & DATA INTEGRITY STRATEGY

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                         COMPLETE CHANGE INVENTORY                                        │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

 9.1 DATABASE CHANGES

   POSTGRESQL CHANGES
   ──────────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ EXISTING TABLES (Archive, Don't Delete)                                             │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  section301_rates                                                                   │
   │  ├── Action: RENAME to section301_rates_archive_YYYYMMDD                            │
   │  ├── Reason: Preserve for rollback + audit                                          │
   │  └── Status: Read-only after migration                                              │
   │                                                                                     │
   │  (any other existing 301-related tables)                                            │
   │  └── Same pattern: archive with timestamp                                           │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ NEW TABLES (Create)                                                                 │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  1. source_versions (create FIRST - other tables reference it)                      │
   │     ├── Purpose: Audit backbone, tracks all data sources                            │
   │     ├── Dependencies: None                                                          │
   │     └── Indexes: source_type, document_id, content_hash                             │
   │                                                                                     │
   │  2. tariff_measures (create SECOND)                                                 │
   │     ├── Purpose: Replace section301_rates with SCD Type 2                           │
   │     ├── Dependencies: FK to source_versions                                         │
   │     ├── Indexes: (scope_hts_value, effective_start, effective_end)                  │
   │     │            (ch99_heading), (program)                                          │
   │     └── Migrate data from: section301_rates                                         │
   │                                                                                     │
   │  3. exclusion_claims (create THIRD)                                                 │
   │     ├── Purpose: Track 301 exclusions with verification workflow                    │
   │     ├── Dependencies: FK to source_versions                                         │
   │     ├── Indexes: (claim_ch99_heading), (effective_start, effective_end)             │
   │     └── Initial data: Load from USTR exclusion notices                              │
   │                                                                                     │
   │  4. hts_code_history (create FOURTH)                                                │
   │     ├── Purpose: Dual indexing for HTS code validity                                │
   │     ├── Dependencies: FK to source_versions                                         │
   │     ├── Indexes: (code, valid_from, valid_to), (replaced_by_code)                   │
   │     └── Initial data: Load from USITC HTS archive                                   │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ SUPPORTING TABLES (Optional but Recommended)                                        │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  5. ingestion_runs (for pipeline tracking)                                          │
   │     ├── Purpose: Log each ingestion with stats                                      │
   │     └── Columns: id, source_type, started_at, completed_at,                         │
   │                  rows_added, rows_changed, rows_closed, status, error_msg           │
   │                                                                                     │
   │  6. consistency_checks (for verification audit)                                     │
   │     ├── Purpose: Log verification results                                           │
   │     └── Columns: id, check_type, environment, passed, details, checked_at           │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

 9.2 SQLITE CHANGES

   SQLITE CHANGES (Local/Edge)
   ───────────────────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ Strategy: Full rebuild from PostgreSQL (not incremental)                            │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  BEFORE MIGRATION:                                                                  │
   │  └── Backup: cp lanes.db lanes_backup_YYYYMMDD.db                                   │
   │                                                                                     │
   │  DURING MIGRATION:                                                                  │
   │  ├── Drop old tables (SQLite only - PG originals preserved)                         │
   │  ├── Create new schema (mirror PG exactly)                                          │
   │  └── Bulk load from PG export                                                       │
   │                                                                                     │
   │  TABLES TO CREATE:                                                                  │
   │  ├── tariff_measures (same schema as PG)                                            │
   │  ├── exclusion_claims (same schema as PG)                                           │
   │  ├── hts_code_history (same schema as PG)                                           │
   │  └── source_versions (same schema as PG, for reference)                             │
   │                                                                                     │
   │  NOTE: SQLite is READ-ONLY replica. No writes except during sync.                   │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

 9.3 CSV/FILE CHANGES

   CSV & FILE CHANGES
   ──────────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ File Structure                                                                      │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  /data/                                                                             │
   │  ├── /archive/                         (never delete, append only)                  │
   │  │   ├── section301_rates_20260125.csv                                              │
   │  │   ├── tariff_measures_20260125.csv                                               │
   │  │   └── ...                                                                        │
   │  │                                                                                  │
   │  ├── /current/                         (latest snapshots)                           │
   │  │   ├── tariff_measures.csv                                                        │
   │  │   ├── exclusion_claims.csv                                                       │
   │  │   ├── hts_code_history.csv                                                       │
   │  │   └── manifest.json                 (checksums + row counts)                     │
   │  │                                                                                  │
   │  ├── /raw/                             (original source files)                      │
   │  │   ├── /usitc/                                                                    │
   │  │   │   └── china_tariffs_20260125.csv                                             │
   │  │   ├── /ustr/                                                                     │
   │  │   │   └── frn_2024-29462.pdf                                                     │
   │  │   └── /cbp/                                                                      │
   │  │       └── csms_62411889.html                                                     │
   │  │                                                                                  │
   │  └── /exports/                         (versioned releases)                         │
   │      ├── v1.0.0/                                                                    │
   │      ├── v2.0.0/                                                                    │
   │      └── latest -> v2.0.0/                                                          │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ manifest.json Format                                                                │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  {                                                                                  │
   │    "generated_at": "2026-01-25T10:30:00Z",                                          │
   │    "source_version": "pg_snapshot_20260125",                                        │
   │    "files": {                                                                       │
   │      "tariff_measures.csv": {                                                       │
   │        "row_count": 12847,                                                          │
   │        "sha256": "abc123...",                                                       │
   │        "columns": ["id", "program", "ch99_heading", ...]                            │
   │      },                                                                             │
   │      "exclusion_claims.csv": { ... },                                               │
   │      "hts_code_history.csv": { ... }                                                │
   │    }                                                                                │
   │  }                                                                                  │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

 9.4 CODE/APPLICATION CHANGES

   CODE CHANGES
   ────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ Engine Changes                                                                      │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  QUERIES TO UPDATE:                                                                 │
   │                                                                                     │
   │  OLD:                                                                               │
   │  SELECT rate FROM section301_rates WHERE hts_code = ?                               │
   │                                                                                     │
   │  NEW:                                                                               │
   │  SELECT additional_rate, ch99_heading, legal_basis, source_version_id               │
   │  FROM tariff_measures                                                               │
   │  WHERE scope_hts_value = ?                                                          │
   │    AND effective_start <= ?                                                         │
   │    AND (effective_end IS NULL OR effective_end > ?)                                 │
   │  ORDER BY                                                                           │
   │    CASE scope_hts_type WHEN 'HTS10' THEN 1 ELSE 2 END,  -- HTS10 > HTS8             │
   │    effective_start DESC                                                             │
   │  LIMIT 1                                                                            │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ New Functions to Add                                                                │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  1. validate_hts_code(hts: str, entry_date: date) -> HtsValidation                  │
   │     └── Checks hts_code_history, returns VALID/INVALID + suggestions                │
   │                                                                                     │
   │  2. check_exclusion(hts: str, entry_date: date) -> ExclusionResult                  │
   │     └── Queries exclusion_claims, returns candidates + verification_required        │
   │                                                                                     │
   │  3. get_rate_confidence(measure: TariffMeasure, entry_date: date) -> Confidence     │
   │     └── Returns CONFIRMED/SCHEDULED/PENDING based on rate_status + date             │
   │                                                                                     │
   │  4. evaluate_301(coo: str, hts: str, entry_date: date) -> Section301Result          │
   │     └── Main entry point, orchestrates steps 1-6                                    │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ API Response Changes                                                                │
   ├─────────────────────────────────────────────────────────────────────────────────────┤
   │                                                                                     │
   │  OLD RESPONSE:                                                                      │
   │  {                                                                                  │
   │    "applies": true,                                                                 │
   │    "rate": 25                                                                       │
   │  }                                                                                  │
   │                                                                                     │
   │  NEW RESPONSE (backward compatible):                                                │
   │  {                                                                                  │
   │    "applies": true,                                                                 │
   │    "rate": 25,                          // Keep for backward compat                 │
   │                                                                                     │
   │    // New fields (additive)                                                         │
   │    "chapter99_heading": "9903.91.01",                                               │
   │    "additional_rate": 25,                                                           │
   │    "rate_status": "confirmed",                                                      │
   │    "legal_basis": "Note 31, Subdivision (b)",                                       │
   │    "source_version": "USTR_FRN_2024-29462",                                         │
   │    "exclusion": { ... },                                                            │
   │    "temporal": { ... },                                                             │
   │    "hts_validation": { ... }                                                        │
   │  }                                                                                  │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

 9.5 MIGRATION ORDER (Critical Path)

   MIGRATION SEQUENCE
   ──────────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │                                                                                     │
   │  STEP 1: PREPARE (No changes yet)                                                   │
   │  ├── [ ] Backup PostgreSQL database                                                 │
   │  ├── [ ] Backup SQLite file                                                         │
   │  ├── [ ] Archive current CSV files                                                  │
   │  └── [ ] Document current row counts                                                │
   │                                                                                     │
   │  STEP 2: CREATE NEW SCHEMA (PostgreSQL)                                             │
   │  ├── [ ] CREATE TABLE source_versions                                               │
   │  ├── [ ] CREATE TABLE tariff_measures                                               │
   │  ├── [ ] CREATE TABLE exclusion_claims                                              │
   │  ├── [ ] CREATE TABLE hts_code_history                                              │
   │  ├── [ ] CREATE TABLE ingestion_runs (optional)                                     │
   │  └── [ ] CREATE TABLE consistency_checks (optional)                                 │
   │                                                                                     │
   │  STEP 3: MIGRATE DATA (PostgreSQL)                                                  │
   │  ├── [ ] Insert initial source_version for migration                                │
   │  ├── [ ] INSERT INTO tariff_measures FROM section301_rates                          │
   │  ├── [ ] Load exclusion_claims from USTR data                                       │
   │  └── [ ] Load hts_code_history from USITC archive                                   │
   │                                                                                     │
   │  STEP 4: VERIFY POSTGRESQL                                                          │
   │  ├── [ ] Row count check (old vs new)                                               │
   │  ├── [ ] Spot check 10 random HTS codes                                             │
   │  └── [ ] Run regression tests                                                       │
   │                                                                                     │
   │  STEP 5: ARCHIVE OLD TABLES (PostgreSQL)                                            │
   │  ├── [ ] RENAME section301_rates TO section301_rates_archive_YYYYMMDD               │
   │  └── [ ] (Any other old tables)                                                     │
   │                                                                                     │
   │  STEP 6: SYNC SQLITE                                                                │
   │  ├── [ ] Backup existing SQLite                                                     │
   │  ├── [ ] Create new schema in SQLite                                                │
   │  ├── [ ] Bulk load from PostgreSQL                                                  │
   │  └── [ ] Verify row counts match                                                    │
   │                                                                                     │
   │  STEP 7: EXPORT CSV                                                                 │
   │  ├── [ ] Export tariff_measures.csv                                                 │
   │  ├── [ ] Export exclusion_claims.csv                                                │
   │  ├── [ ] Export hts_code_history.csv                                                │
   │  ├── [ ] Generate manifest.json                                                     │
   │  └── [ ] Verify checksums                                                           │
   │                                                                                     │
   │  STEP 8: UPDATE CODE                                                                │
   │  ├── [ ] Update queries to use new tables                                           │
   │  ├── [ ] Add new validation functions                                               │
   │  ├── [ ] Update API responses (backward compatible)                                 │
   │  └── [ ] Run full test suite                                                        │
   │                                                                                     │
   │  STEP 9: FINAL VERIFICATION                                                         │
   │  ├── [ ] Cross-environment consistency check (PG, SQLite, CSV)                      │
   │  ├── [ ] End-to-end API test                                                        │
   │  └── [ ] Sign-off                                                                   │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

 9.6 ROLLBACK PLAN

   ROLLBACK PLAN (If Something Goes Wrong)
   ───────────────────────────────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │                                                                                     │
   │  ROLLBACK STEP 1: Restore PostgreSQL                                                │
   │  └── RENAME section301_rates_archive_YYYYMMDD TO section301_rates                   │
   │      (New tables can stay - they don't interfere)                                   │
   │                                                                                     │
   │  ROLLBACK STEP 2: Restore SQLite                                                    │
   │  └── cp lanes_backup_YYYYMMDD.db lanes.db                                           │
   │                                                                                     │
   │  ROLLBACK STEP 3: Restore CSV                                                       │
   │  └── cp /data/archive/section301_rates_YYYYMMDD.csv /data/current/                  │
   │                                                                                     │
   │  ROLLBACK STEP 4: Revert code                                                       │
   │  └── git revert (or feature flag off)                                               │
   │                                                                                     │
   │  TIME TO ROLLBACK: < 5 minutes (all backups in place)                               │
   │                                                                                     │
   └─────────────────────────────────────────────────────────────────────────────────────┘

 9.7 VERIFICATION CHECKLIST

   POST-MIGRATION VERIFICATION
   ───────────────────────────

   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │ CHECK                          │ POSTGRESQL │ SQLITE │ CSV    │ API    │           │
   ├────────────────────────────────┼────────────┼────────┼────────┼────────┤           │
   │ Row count matches              │     [ ]    │  [ ]   │  [ ]   │  N/A   │           │
   │ Schema correct                 │     [ ]    │  [ ]   │  [ ]   │  N/A   │           │
   │ Indexes created                │     [ ]    │  [ ]   │  N/A   │  N/A   │           │
   │ FK constraints valid           │     [ ]    │  N/A   │  N/A   │  N/A   │           │
   │ Sample query returns same      │     [ ]    │  [ ]   │  [ ]   │  [ ]   │           │
   │ Regression tests pass          │     [ ]    │  [ ]   │  N/A   │  [ ]   │           │
   │ Performance acceptable         │     [ ]    │  [ ]   │  N/A   │  [ ]   │           │
   │ Backward compat maintained     │     N/A    │  N/A   │  N/A   │  [ ]   │           │
   └────────────────────────────────┴────────────┴────────┴────────┴────────┴───────────┘

 ---
 10. SECTION 301 REDONE - January 25, 2026

 10.1 CURRENT IMPLEMENTATION DESIGN

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                    SECTION 301 - CURRENT IMPLEMENTATION (v19.0)                          │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   FLOW:
   ─────

   User Input (HTS, COO, Date)
            │
            ▼
   ┌─────────────────────────────────┐
   │  1. COUNTRY GATE                │
   │  ─────────────────              │
   │  Section 301 ONLY applies to    │
   │  COO = CN (China)               │
   │                                 │
   │  HK, MO, TW = NOT China         │
   │  → 301 does NOT apply           │
   └─────────────────────────────────┘
            │ (if COO = CN)
            ▼
   ┌─────────────────────────────────┐
   │  2. HTS LOOKUP                  │
   │  ─────────────────              │
   │  Query: section_301_rates       │
   │                                 │
   │  WHERE hts_8digit = {input[:8]} │
   │  AND effective_start <= date    │
   │  AND (effective_end IS NULL     │
   │       OR effective_end > date)  │
   │                                 │
   │  Priority: role='exclude' first │
   │            then role='impose'   │
   └─────────────────────────────────┘
            │
            ▼
   ┌─────────────────────────────────┐
   │  3. RESULT                      │
   │  ─────────────────              │
   │  IF found:                      │
   │    → chapter_99_code (e.g.      │
   │      9903.88.01/02/03/15)       │
   │    → duty_rate (25%, 50%, etc.) │
   │    → list_name (list_1/2/3/4a)  │
   │                                 │
   │  IF not found:                  │
   │    → 301 does NOT apply         │
   │    → NO FALLBACK (v19.0 fix)    │
   └─────────────────────────────────┘

 10.2 KEY FILES & CODE PATHS

   FILE                                          PURPOSE
   ────                                          ───────

   app/chat/graphs/stacking_rag.py               Main stacking logic
     └── Lines 602-626                           Section 301 handling (FIXED v19.0)

   app/chat/tools/stacking_tools.py              Tool functions
     └── check_program_inclusion()               HTS lookup in section_301_rates
     └── get_program_output()                    Fallback lookup (should NOT be used for 301)

   app/web/db/models/tariff_tables.py            ORM models
     └── Section301Rate                          Main 301 rates table model
     └── Section301Rate.get_rate_as_of()         Temporal lookup with exclusion priority

   DATABASE TABLES:
   ────────────────
   section_301_rates          10,810 rows    Main HTS→Rate mapping (temporal)
   section_301_inclusions        20 rows     Legacy static table (deprecated)
   section_301_exclusions         2 rows     Product-specific exclusions
   program_codes                  0 rows     NO section_301 default (FIXED v19.0)

 10.3 BUG FOUND & FIXED (v19.0 - January 25, 2026)

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                              BUG: INCORRECT 301 FALLBACK                                 │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   SYMPTOM:
   ────────
   HTS codes NOT on 301 list (e.g., 3002.12.0010) were incorrectly
   showing Section 301 @ 25% applied.

   ROOT CAUSE:
   ───────────
   1. check_program_inclusion("section_301", "3002.12.0010") → included: False ✓
   2. Code FELL BACK to program_codes table lookup
   3. program_codes had default row: section_301 → 9903.88.03 @ 25%
   4. Result: 301 incorrectly applied to ALL China imports

   BUGGY CODE (stacking_rag.py lines 617-626):
   ───────────────────────────────────────────
   else:
       # Fallback to program_codes table    ← THIS WAS THE BUG
       output = TOOL_MAP["get_program_output"].invoke({...})
       if output.get("found"):
           chapter_99_code = output.get("chapter_99_code")

   FIX APPLIED:
   ────────────
   1. CODE FIX (stacking_rag.py):
      - Removed fallback to program_codes for Section 301
      - Set action = "skip" when HTS not in section_301_rates
      - Required duty_rate to be present (no silent 0.25 default)

   2. DATA FIX (both SQLite and PostgreSQL):
      - Deleted: program_codes WHERE program_id = 'section_301'
      - This prevents future regressions

   FIXED CODE:
   ───────────
   if inclusion_result.get("included"):
       action = "apply"
       chapter_99_code = inclusion_result.get("chapter_99_code")
       duty_rate = inclusion_result.get("duty_rate")  # Required, no default
   else:
       # v19.0 FIX: NO FALLBACK for enumerated programs
       action = "skip"

 10.4 TEST CASES VERIFIED (January 25, 2026)

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                         SECTION 301 TEST RESULTS (COO=CN)                                │
 │                         Both SQLite (local) and PostgreSQL (Railway) verified            │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   │ HTS Code     │ COO │ Country │ Expected                 │ Actual Result      │ Status │
   │──────────────│─────│─────────│──────────────────────────│────────────────────│────────│
   │ 9018.90.8000 │ CN  │ China   │ No 301                   │ No 301             │ ✅     │
   │ 9027.50.4015 │ CN  │ China   │ 301 applies              │ 9903.88.01 @ 25%   │ ✅     │
   │ 3002.12.0010 │ CN  │ China   │ No 301                   │ No 301             │ ✅     │
   │ 7326.90.8660 │ CN  │ China   │ 301 + 232                │ 9903.88.03 @ 25%   │ ✅     │
   │ 7616.99.1000 │ CN  │ China   │ 301 + 232                │ 9903.88.03 @ 25%   │ ✅     │
   │ 8501.31.4000 │ CN  │ China   │ 9903.88.02 OR .69        │ 9903.88.02 @ 25%   │ ✅     │
   │ 8473.30.1180 │ CN  │ China   │ 9903.88.03 OR .69        │ 9903.88.03 @ 25%   │ ✅     │
   │ 8471.50.0150 │ CN  │ China   │ 301 applies              │ 9903.88.03 @ 25%   │ ✅     │
   │ 8504.40.9580 │ CN  │ China   │ 9903.88.03 OR .69        │ 9903.88.03 @ 25%   │ ✅     │

   TARIFF STACKER VERIFICATION (8501.31.4000, COO=CN):
   ───────────────────────────────────────────────────
   Program                      │ Ch99 Code   │ Rate │ Status
   ─────────────────────────────│─────────────│──────│───────
   Section 301 China Tariffs    │ 9903.88.02  │ 25%  │ ✅
   IEEPA Fentanyl Tariff        │ 9903.01.24  │ 10%  │ ✅
   IEEPA Reciprocal Tariff      │ 9903.01.25  │ 10%  │ ✅
   Base HTS (MFN)               │ 8501.31.4000│  4%  │ ✅
   ─────────────────────────────│─────────────│──────│───────
   TOTAL                        │             │ 49%  │ ✅

 10.5 DATA SOURCES

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                              SECTION 301 DATA SOURCES                                    │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   SOURCE                              URL                                     REFRESH
   ──────                              ───                                     ───────

   USITC China Tariffs CSV             hts.usitc.gov/reststop/file?release=   Weekly
                                       currentRelease&filename=China%20Tariffs

   USTR Federal Register Notices       federalregister.gov (USTR search)      Daily

   CBP Section 301 FAQs                cbp.gov/trade/programs-administration/ Daily
                                       entry-summary/section-301-trade-remedies

   DATA IN DATABASE:
   ─────────────────
   Table                    │ Rows    │ Source
   ─────────────────────────│─────────│────────────────────────────
   section_301_rates        │ 10,810  │ USITC China Tariffs CSV
   section_301_exclusions   │      2  │ USTR Exclusion Notices
   section_301_inclusions   │     20  │ Legacy (deprecated)

   CHAPTER 99 CODES IN DATABASE:
   ─────────────────────────────
   Ch99 Code    │ List        │ Rows  │ Rate
   ─────────────│─────────────│───────│─────
   9903.88.01   │ list_1      │ 1,082 │ 25%
   9903.88.02   │ list_2      │   285 │ 25%
   9903.88.03   │ list_3      │ 5,790 │ 25%
   9903.88.15   │ list_4A     │ 3,237 │ 7.5%
   9903.88.69   │ exclusion   │     1 │ 0%   (role='exclude')
   9903.91.01-08│ 4-yr review │   ~40 │ 25-100% (strategic sectors)

 10.6 KNOWN LIMITATIONS & FUTURE WORK

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                              KNOWN LIMITATIONS                                           │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   1. EXCLUSION OPTION (9903.88.69/70) NOT SHOWN AS CHOICE
      ─────────────────────────────────────────────────────
      Current: Only shows exclusion code if HTS has approved exclusion in DB
      Expected: User might want to see "9903.88.03 OR 9903.88.69" as options

      Design Decision Needed:
      - Option A: Current behavior (show exclusion only if in exclusion table)
      - Option B: Always show both options, let user claim exclusion

   2. NO HARDCODING IN CURRENT IMPLEMENTATION
      ───────────────────────────────────────
      ✅ All rates come from section_301_rates table
      ✅ All Chapter 99 codes come from database
      ✅ Country gate uses ProgramCountryScope table (data-driven)
      ✅ No fallback to program_codes for Section 301 (v19.0 fix)

   3. TEMPORAL RATES WORKING
      ──────────────────────
      ✅ effective_start/effective_end dates respected
      ✅ as_of_date parameter supported for historical lookups
      ✅ Role-based priority (exclude > impose)

   4. FUTURE ENHANCEMENTS
      ────────────────────
      - [ ] Add more exclusion entries to section_301_exclusions
      - [ ] Implement exclusion claim/disclaim workflow
      - [ ] Add source_version tracking for audit trail
      - [ ] Automated USITC CSV ingestion pipeline

 10.7 VERIFICATION COMMANDS

 # Test Section 301 lookup (local SQLite)
 python -c "
 import os
 os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/sqlite.db'
 from app.web import create_app
 from app.chat.tools.stacking_tools import check_program_inclusion
 import json

 app = create_app()
 with app.app_context():
     result = check_program_inclusion.invoke({
         'program_id': 'section_301',
         'hts_code': '8501.31.4000'
     })
     print(json.loads(result))
 "

 # Test Railway PostgreSQL
 DATABASE_URL="postgresql://..." python scripts/test_hts_codes_verification.py

 # Verify no fallback in program_codes
 sqlite3 instance/sqlite.db "SELECT * FROM program_codes WHERE program_id = 'section_301'"
 # Should return: (no rows)

 10.8 DATA SYNC ARCHITECTURE (January 25, 2026)

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                         SECTION 301 DATA SYNC ARCHITECTURE                               │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   DATA FLOW (CURRENT):
   ────────────────────

   ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
   │   DATA SOURCES  │      │     SQLite      │      │   PostgreSQL    │
   │                 │      │   (Local Dev)   │      │    (Railway)    │
   │ • USITC CSV     │      │                 │      │                 │
   │ • USTR FRN      │─────▶│   PRIMARY       │─────▶│   PRODUCTION    │
   │ • Manual CSV    │      │   INGEST        │      │   SYNC TARGET   │
   │                 │      │                 │      │                 │
   │                 │      │  10,784 rows    │      │  10,810 rows    │
   └─────────────────┘      └─────────────────┘      └─────────────────┘
                                    │                        │
                                    │   ❌ NO REVERSE        │
                                    │      SYNC              │
                                    ▼                        │
                            ┌─────────────────┐              │
                            │      CSV        │              │
                            │   (Archive)     │◀─────────────┘
                            │                 │    ❌ NO AUTO
                            │  10,785 rows    │       EXPORT
                            └─────────────────┘


   KEY FILES:
   ──────────
   app/ingestion/section301_processor.py    Main ingestion pipeline
     └── USITCChinaTariffsProcessor         Fetches & processes USITC CSV
     └── FederalRegisterSection301Processor  Processes USTR FRN notices
     └── Section301IngestionPipeline         Orchestrates all sources

   app/sync/pg_sync.py                       SQLite → PostgreSQL sync
     └── sync_to_postgresql()                Replicates new rows
     └── AUTO_SYNC_ENABLED env var           Controls auto-sync

   scripts/migrate_section301_to_new_schema.py   CSV → SQLite migration
   scripts/consolidate_section_301_csvs.py       CSV consolidation


   DOCUMENT_ID CREATION:
   ─────────────────────
   Source                │ Document ID Format                    │ Example
   ──────────────────────│───────────────────────────────────────│────────────────────────
   USITC CSV             │ china_tariffs_YYYYMMDD_HHMMSS         │ china_tariffs_20260125_103000
   Federal Register      │ Document number                       │ 2024-29462
   Manual CSV Migration  │ migration_csv_YYYYMMDD_HHMMSS         │ migration_csv_20260125_120000

   ⚠️  Document IDs identify ENTIRE DATA SOURCES, not individual rows
   ⚠️  Content hash (SHA-256) prevents duplicate ingestion


   DATA CONSISTENCY STATUS (January 25, 2026):
   ───────────────────────────────────────────
   Storage       │ Rows    │ Temporal Data │ Status
   ──────────────│─────────│───────────────│────────────────────────────
   PostgreSQL    │ 10,810  │ ✅ All have effective_start, 352 have effective_end │ PRIMARY
   SQLite        │ 10,784  │ ✅ All have effective_start, 350 have effective_end │ 26 rows behind
   CSV           │ 10,785  │ ✅ Has both columns                                  │ 25 rows behind

   ⚠️  DISCREPANCY: 26 rows difference between PostgreSQL and SQLite


   SYNC GAPS IDENTIFIED:
   ─────────────────────
   Gap                              │ Impact                         │ Risk
   ─────────────────────────────────│────────────────────────────────│──────
   No PostgreSQL → SQLite sync      │ Local dev gets stale           │ Medium
   No PostgreSQL → CSV export       │ CSVs become outdated           │ Medium
   26-row discrepancy               │ Data inconsistency             │ High
   No cross-DB validation           │ Silent data drift              │ High
   No bi-directional sync           │ Manual intervention required   │ Medium


   RECOMMENDED FIXES:
   ──────────────────
   1. [ ] Implement PostgreSQL → SQLite sync for local dev refresh
   2. [ ] Add automated CSV export after PostgreSQL ingestion
   3. [ ] Create reconciliation script to compare row counts across all 3
   4. [ ] Add checksums to manifest.json for verification
   5. [ ] Investigate and fix 26-row discrepancy

 10.9 DATA SYNC FIX PLAN (January 25, 2026)

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                         DATA SYNC FIX - MINIMAL IMPLEMENTATION                           │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   ROOT CAUSE OF 26-ROW DISCREPANCY:
   ──────────────────────────────────
   • PostgreSQL has 10,810 rows (26 MORE than SQLite's 10,784)
   • Sync code checks `id` uniqueness, but constraint is on business key:
     (hts_8digit, chapter_99_code, effective_start)
   • Some rows inserted directly to PostgreSQL, then sync tried to re-insert
     with different ids → unique constraint violations → silently skipped

   FIX APPROACH:
   ─────────────
   Fix 1: RECONCILE DATA (one-time)
   Fix 2: ADD REVERSE SYNC (PostgreSQL → SQLite)
   Fix 3: ADD CSV EXPORT (after sync)

 Fix 1: Reconcile Data (One-Time Script)

 # scripts/reconcile_section_301.py

 """
 Reconcile section_301_rates between PostgreSQL and SQLite.
 Strategy: PostgreSQL is now the source of truth (has more rows).
 Pull missing rows from PostgreSQL → SQLite.
 """

 def reconcile():
     # 1. Get all business keys from PostgreSQL
     pg_keys = get_pg_business_keys()  # (hts_8digit, chapter_99_code, effective_start)

     # 2. Get all business keys from SQLite
     sqlite_keys = get_sqlite_business_keys()

     # 3. Find rows in PG but not in SQLite
     missing_in_sqlite = pg_keys - sqlite_keys  # Should be 26 rows

     # 4. For each missing key, fetch full row from PG and insert to SQLite
     for key in missing_in_sqlite:
         row = fetch_row_from_pg(key)
         insert_to_sqlite(row)

     # 5. Verify counts match
     assert get_pg_count() == get_sqlite_count()

 Fix 2: Reverse Sync (PostgreSQL → SQLite)

 # app/sync/pg_sync.py - ADD FUNCTION

 def sync_from_postgresql(table_name: str = None):
     """
     Pull data from PostgreSQL to SQLite (reverse sync).
     Uses business-key deduplication for section_301_rates.
     """
     tables = [table_name] if table_name else SYNC_TABLES

     for table in tables:
         if table == 'section_301_rates':
             # Use business key for dedup
             business_key_cols = ['hts_8digit', 'chapter_99_code', 'effective_start']
             existing_keys = get_sqlite_business_keys(table, business_key_cols)

             for row in fetch_pg_rows(table):
                 key = (row['hts_8digit'], row['chapter_99_code'], row['effective_start'])
                 if key not in existing_keys:
                     insert_to_sqlite(table, row)
         else:
             # Use id-based dedup for other tables
             existing_ids = get_sqlite_ids(table)
             for row in fetch_pg_rows(table):
                 if row['id'] not in existing_ids:
                     insert_to_sqlite(table, row)

 Fix 3: CSV Export After Sync

 # app/sync/pg_sync.py - ADD FUNCTION

 def export_to_csv(table_name: str, output_dir: str = 'data/current'):
     """
     Export table to CSV for archival/backup.
     """
     import csv
     from datetime import datetime

     # Query all rows from PostgreSQL
     rows = fetch_all_pg_rows(table_name)

     # Write to CSV
     output_path = f"{output_dir}/{table_name}.csv"
     with open(output_path, 'w', newline='') as f:
         writer = csv.DictWriter(f, fieldnames=rows[0].keys())
         writer.writeheader()
         writer.writerows(rows)

     # Update manifest
     update_manifest(table_name, output_path, len(rows))

     return output_path

 Implementation Steps

   STEP  │ FILE                        │ CHANGE
   ──────│─────────────────────────────│─────────────────────────────────────────
   1     │ scripts/reconcile_301.py    │ CREATE: One-time reconciliation script
   2     │ app/sync/pg_sync.py         │ ADD: sync_from_postgresql() function
   3     │ app/sync/pg_sync.py         │ ADD: export_to_csv() function
   4     │ app/sync/pg_sync.py         │ ADD: update_manifest() helper
   5     │ RUN: reconcile_301.py       │ Fix the 26-row discrepancy
   6     │ VERIFY: row counts          │ Confirm all 3 match (PG, SQLite, CSV)

 Files to Modify

   app/sync/pg_sync.py                   # Add reverse sync + CSV export
   scripts/reconcile_section_301.py      # CREATE: one-time fix script
   data/current/manifest.json            # UPDATE: add checksums after export

 ---
 11. NOTE 31 SUBDIVISION MAPPING BUG FIX (January 25, 2026)

 11.1 BUG DESCRIPTION

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                    BUG: WRONG CHAPTER 99 HEADING FOR 100% RATE ITEMS                     │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   SYMPTOM:
   ────────
   HTS 9018.31.00.40 (syringes) from China shows:
     WRONG:  9903.91.02 @ 100%
     CORRECT: 9903.91.03 @ 100%

   ROOT CAUSE:
   ───────────
   Ingestion code mapped 100% rate items to wrong Chapter 99 heading.

   U.S. NOTE 31 SUBDIVISION MAPPING (CORRECT):
   ────────────────────────────────────────────
   Subdivision │ Chapter 99   │ Rate
   ────────────│──────────────│─────
   (b)         │ 9903.91.01   │ 25%
   (c)         │ 9903.91.02   │ 50%
   (d)         │ 9903.91.03   │ 100%  ← Electric Vehicles, Syringes should be HERE

   CURRENT DATABASE STATE (WRONG):
   ────────────────────────────────
   9903.91.02 @ 50%  → Semiconductors, Solar Cells (CORRECT)
   9903.91.02 @ 100% → Electric Vehicles, Syringes (WRONG - should be 9903.91.03)
   9903.91.03 @ 25%  → Battery Parts, Critical Minerals (WRONG - should be higher rate or different code)

 11.2 AFFECTED DATA

   10 HTS CODES WITH WRONG MAPPING (9903.91.02 @ 100%):
   ────────────────────────────────────────────────────

   ID     │ HTS8      │ List                    │ Source Doc
   ───────│───────────│─────────────────────────│───────────
   9833   │ 87024031  │ Electric Vehicles       │ 2024-21217
   9835   │ 87024061  │ Electric Vehicles       │ 2024-21217
   9837   │ 87029031  │ Electric Vehicles       │ 2024-21217
   9839   │ 87029061  │ Electric Vehicles       │ 2024-21217
   9852   │ 87036000  │ Electric Vehicles       │ 2024-21217
   9854   │ 87037000  │ Electric Vehicles       │ 2024-21217
   9856   │ 87038000  │ Electric Vehicles       │ 2024-21217
   9858   │ 87039001  │ Electric Vehicles       │ 2024-21217
   10198  │ 90183100  │ Syringes and Needles    │ 2024-21217
   10199  │ 90183200  │ Syringes and Needles    │ 2024-21217

 11.3 FIX PLAN

   STEP 1: UPDATE POSTGRESQL
   ─────────────────────────
   UPDATE section_301_rates
   SET chapter_99_code = '9903.91.03'
   WHERE chapter_99_code = '9903.91.02'
     AND duty_rate = 1.0
     AND effective_start = '2024-09-27';

   -- This updates 10 rows (8 EVs + 2 Syringes)

   STEP 2: SYNC TO SQLITE
   ──────────────────────
   Run: python -c "from app.sync.pg_sync import sync_from_postgresql; sync_from_postgresql('section_301_rates')"

   Note: Since we're updating existing rows (same business key, different ch99),
         we need to UPDATE, not INSERT. May need custom sync logic.

   STEP 3: EXPORT TO CSV
   ─────────────────────
   Run: python -c "from app.sync.pg_sync import export_to_csv; export_to_csv('section_301_rates')"

   STEP 4: VERIFY
   ──────────────
   Query both databases:
   SELECT chapter_99_code, duty_rate, COUNT(*)
   FROM section_301_rates
   WHERE chapter_99_code IN ('9903.91.02', '9903.91.03')
   GROUP BY chapter_99_code, duty_rate
   ORDER BY chapter_99_code, duty_rate;

   EXPECTED RESULT AFTER FIX:
   ──────────────────────────
   9903.91.02 @ 50%   → 3 rows  (Semiconductors only)
   9903.91.03 @ 25%   → 348 rows (unchanged)
   9903.91.03 @ 100%  → 10 rows  (EVs + Syringes, NEW)

 11.4 IMPLEMENTATION SCRIPT

 # scripts/fix_note31_subdivision_mapping.py

 """
 Fix Note 31 subdivision mapping bug.
 Changes chapter_99_code from 9903.91.02 to 9903.91.03 for 100% rate items.
 """

 import os
 from sqlalchemy import create_engine, text

 def fix_note31_mapping(dry_run: bool = False):
     # PostgreSQL update
     pg_url = os.environ.get('DATABASE_URL')
     pg_engine = create_engine(pg_url)

     with pg_engine.connect() as conn:
         # Find affected rows
         result = conn.execute(text("""
             SELECT id, hts_8digit, chapter_99_code, duty_rate, list_name
             FROM section_301_rates
             WHERE chapter_99_code = '9903.91.02'
               AND duty_rate = 1.0
         """))
         affected = result.fetchall()

         print(f"Found {len(affected)} rows to fix:")
         for row in affected:
             print(f"  ID={row[0]}: HTS8={row[1]}, Ch99={row[2]} → 9903.91.03, List={row[4]}")

         if not dry_run and affected:
             # Apply fix
             conn.execute(text("""
                 UPDATE section_301_rates
                 SET chapter_99_code = '9903.91.03'
                 WHERE chapter_99_code = '9903.91.02'
                   AND duty_rate = 1.0
             """))
             conn.commit()
             print(f"\nUpdated {len(affected)} rows in PostgreSQL")

     # SQLite update (same logic)
     sqlite_path = 'instance/sqlite.db'
     if os.path.exists(sqlite_path):
         import sqlite3
         sqlite_conn = sqlite3.connect(sqlite_path)
         cursor = sqlite_conn.cursor()

         if not dry_run:
             cursor.execute("""
                 UPDATE section_301_rates
                 SET chapter_99_code = '9903.91.03'
                 WHERE chapter_99_code = '9903.91.02'
                   AND duty_rate = 1.0
             """)
             sqlite_conn.commit()
             print(f"Updated {cursor.rowcount} rows in SQLite")

         sqlite_conn.close()

 if __name__ == "__main__":
     import argparse
     parser = argparse.ArgumentParser()
     parser.add_argument('--dry-run', action='store_true')
     args = parser.parse_args()
     fix_note31_mapping(dry_run=args.dry_run)

 11.5 REVISED FIX PLAN (Minimal, Durable)

 Bug Classification: Data bug, not architecture bug. No overhaul needed.

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                    MINIMAL 3-STEP FIX + VALIDATION                                       │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

 STEP 1: Fix the CSV Source of Truth

 File: data/section_301_rates_temporal.csv

 Change: For the 10 rows with chapter_99_code=9903.91.02 AND duty_rate=1.0 AND source_doc=2024-21217:
 - Change chapter_99_code from 9903.91.02 → 9903.91.03
 - Keep rate, dates, everything else unchanged

 Affected rows:
 87024031,9903.91.02,1.0,... → 87024031,9903.91.03,1.0,...
 87024061,9903.91.02,1.0,... → 87024061,9903.91.03,1.0,...
 87029031,9903.91.02,1.0,... → 87029031,9903.91.03,1.0,...
 87029061,9903.91.02,1.0,... → 87029061,9903.91.03,1.0,...
 87036000,9903.91.02,1.0,... → 87036000,9903.91.03,1.0,...
 87037000,9903.91.02,1.0,... → 87037000,9903.91.03,1.0,...
 87038000,9903.91.02,1.0,... → 87038000,9903.91.03,1.0,...
 87039001,9903.91.02,1.0,... → 87039001,9903.91.03,1.0,...
 90183100,9903.91.02,1.0,... → 90183100,9903.91.03,1.0,...
 90183200,9903.91.02,1.0,... → 90183200,9903.91.03,1.0,...

 STEP 2: Fix chapter99_resolver.py Mappings

 File: app/workers/chapter99_resolver.py (lines 46-53)

 Changes:
 # BEFORE (WRONG):
 "9903.91.01": {..., "rate": 0.50},  # Wrong
 "9903.91.02": {..., "rate": 0.50},  # Correct
 "9903.91.03": {..., "rate": 0.25},  # Wrong
 "9903.91.20": {..., "rate": 1.00},  # Doesn't exist

 # AFTER (CORRECT - per U.S. Note 31):
 "9903.91.01": {..., "rate": 0.25},  # subdivision (b)
 "9903.91.02": {..., "rate": 0.50},  # subdivision (c) - unchanged
 "9903.91.03": {..., "rate": 1.00},  # subdivision (d)
 # DELETE 9903.91.20 - phantom code

 STEP 3: Add Ingestion-Time Validation (Scoped)

 File: scripts/populate_tariff_tables.py (in populate_section_301_temporal())

 Add validation for Note 31 headings only:
 # Note 31 heading ↔ rate invariants (legal requirement)
 NOTE_31_INVARIANTS = {
     "9903.91.01": 0.25,  # subdivision (b)
     "9903.91.02": 0.50,  # subdivision (c)
     "9903.91.03": 1.00,  # subdivision (d)
 }

 # During CSV load, validate Note 31 rows:
 if chapter_99_code.startswith("9903.91."):
     expected_rate = NOTE_31_INVARIANTS.get(chapter_99_code)
     if expected_rate and abs(duty_rate - expected_rate) > 0.001:
         raise ValueError(
             f"Note 31 invariant violation: {chapter_99_code} must have "
             f"rate {expected_rate}, got {duty_rate} for HTS {hts_8digit}"
         )

 STEP 4: Add Golden Test Cases

 File: tests/test_section301_engine.py or new tests/test_note31_golden.py

 def test_note31_golden_cases():
     """Golden cases to catch mapping swaps."""

     # Case 1: Syringes → 9903.91.03 @ 100%
     result = get_301_rate("90183100", "CN", date(2026, 1, 26))
     assert result["chapter_99_code"] == "9903.91.03"
     assert result["duty_rate"] == 1.00

     # Case 2: Electric Vehicles → 9903.91.03 @ 100%
     result = get_301_rate("87036000", "CN", date(2026, 1, 26))
     assert result["chapter_99_code"] == "9903.91.03"
     assert result["duty_rate"] == 1.00

     # Case 3: Semiconductors → 9903.91.02 @ 50%
     result = get_301_rate("38180000", "CN", date(2026, 1, 26))
     assert result["chapter_99_code"] == "9903.91.02"
     assert result["duty_rate"] == 0.50

 STEP 5: Re-Ingest and Verify

 # Option A: Full re-ingest (preferred)
 python scripts/populate_tariff_tables.py --reset

 # Option B: Targeted SQL patch (if can't rebuild)
 UPDATE section_301_rates
 SET chapter_99_code = '9903.91.03'
 WHERE source_doc = '2024-21217'
   AND duty_rate = 1.0
   AND chapter_99_code = '9903.91.02';

 # Verify fix
 python -c "
 from app.web.db.models.tariff_tables import Section301Rate
 result = Section301Rate.query.filter_by(hts_8digit='90183100').first()
 print(f'Syringes: {result.chapter_99_code} @ {result.duty_rate}')
 # Expected: 9903.91.03 @ 1.0
 "

 11.6 FILES TO MODIFY

   FILE                                         │ ACTION
   ─────────────────────────────────────────────│───────────────────
   data/section_301_rates_temporal.csv          │ FIX: 10 rows Ch99 code
   app/workers/chapter99_resolver.py            │ FIX: rate mappings (lines 46-53)
   scripts/populate_tariff_tables.py            │ ADD: Note 31 invariant validation
   tests/test_note31_golden.py                  │ CREATE: golden test cases

 11.7 WHY THIS FIX IS DURABLE

 | Approach              | Pros                   | Cons                                |
 |-----------------------|------------------------|-------------------------------------|
 | Patch DB only         | Quick                  | Bug recurs on next ingestion        |
 | Refactor architecture | "Clean"                | Overkill, risky, slow               |
 | Fix source + validate | Durable, minimal, fast | Requires correct source maintenance |

 Root cause addressed: CSV had wrong data, resolver had wrong fallbacks, no validation caught it.
 After fix: All three sources aligned to legal reality, validation prevents recurrence.

 ---
 12. BUG: 348 ROWS WITH INCORRECT 9903.91.03 @ 25% (January 26, 2026)

 12.1 BUG SUMMARY

 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                    BUG: 348 ROWS VIOLATE NOTE 31 INVARIANT                              │
 └─────────────────────────────────────────────────────────────────────────────────────────┘

   ISSUE:     348 rows have chapter_99_code = '9903.91.03' but duty_rate = 0.25 (25%)
   LEGAL:     9903.91.03 (subdivision d) MUST be 100%, not 25%
   CORRECT:   These rows should use 9903.91.01 (subdivision b = 25%)
   IMPACT:    Incorrect ACE filing codes - importers would claim wrong subdivision
   SOURCE:    CSV data entry error in data/section_301_rates_temporal.csv
   ORIGIN:    Federal Register document 2024-21217 (Four-Year Review)

 12.2 AFFECTED DATA BREAKDOWN

 | List Name                       | Row Count | HTS Range    | Correct Code |
 |---------------------------------|-----------|--------------|--------------|
 | Steel and Aluminum Products     | 321       | 72xxx, 76xxx | 9903.91.01   |
 | Other Critical Minerals         | 26        | 26xxx, 28xxx | 9903.91.01   |
 | Battery Parts (Non-lithium-ion) | 1         | 85076000     | 9903.91.01   |
 | TOTAL                           | 348       | —            | —            |

 Sample HTS codes affected:
 - Steel: 72061000, 72069000, 72071100, 72082530, 72084030
 - Minerals: 26020000, 26050000, 26060000, 28259030, 28418000
 - Battery: 85076000

 12.3 ROOT CAUSE ANALYSIS

   ROOT CAUSE: Data entry error when populating CSV from FR 2024-21217

   The error chain:
   ┌─────────────────────────────────────────────────────────────────────┐
   │ 1. FR 2024-21217 lists products for Note 31 strategic increases    │
   │ 2. CSV was populated with WRONG chapter_99_code for 25% items:     │
   │    - Used 9903.91.03 (subdivision d = 100%)                        │
   │    - Should be 9903.91.01 (subdivision b = 25%)                    │
   │ 3. Ingestion code reads CSV values directly, no transformation     │
   │ 4. Current validation only logs warnings, doesn't fail             │
   │ 5. Error persisted in database                                     │
   └─────────────────────────────────────────────────────────────────────┘

   U.S. Note 31 Legal Requirement:
   ┌────────────────┬────────────────┬────────────────┐
   │ Subdivision    │ Chapter 99     │ Rate           │
   ├────────────────┼────────────────┼────────────────┤
   │ (b)            │ 9903.91.01     │ 25%            │
   │ (c)            │ 9903.91.02     │ 50%            │
   │ (d)            │ 9903.91.03     │ 100%           │
   └────────────────┴────────────────┴────────────────┘

 12.4 FIX PLAN

 STEP 1: Fix CSV Source (348 rows)

 File: data/section_301_rates_temporal.csv

 Change: For all rows with chapter_99_code='9903.91.03' AND duty_rate=0.25:
 - Change chapter_99_code from 9903.91.03 → 9903.91.01
 - Keep rate, dates, everything else unchanged

 Script:
 # scripts/fix_note31_348_rows.py
 import csv

 INPUT = 'data/section_301_rates_temporal.csv'
 OUTPUT = 'data/section_301_rates_temporal.csv'

 with open(INPUT, 'r') as f:
     rows = list(csv.DictReader(f))

 fixed = 0
 for row in rows:
     if row['chapter_99_code'] == '9903.91.03' and float(row['duty_rate']) == 0.25:
         row['chapter_99_code'] = '9903.91.01'
         fixed += 1

 # Write back
 with open(OUTPUT, 'w', newline='') as f:
     writer = csv.DictWriter(f, fieldnames=rows[0].keys())
     writer.writeheader()
     writer.writerows(rows)

 print(f"Fixed {fixed} rows: 9903.91.03 @ 25% → 9903.91.01 @ 25%")

 STEP 2: Update PostgreSQL Database

 -- Fix in PostgreSQL
 UPDATE section_301_rates
 SET chapter_99_code = '9903.91.01'
 WHERE chapter_99_code = '9903.91.03'
   AND duty_rate = 0.25;

 -- Verify fix
 SELECT chapter_99_code, duty_rate, COUNT(*)
 FROM section_301_rates
 WHERE chapter_99_code IN ('9903.91.01', '9903.91.02', '9903.91.03')
 GROUP BY chapter_99_code, duty_rate
 ORDER BY chapter_99_code, duty_rate;

 STEP 3: Update SQLite Database

 import sqlite3

 conn = sqlite3.connect('instance/sqlite.db')
 cursor = conn.cursor()
 cursor.execute("""
     UPDATE section_301_rates
     SET chapter_99_code = '9903.91.01'
     WHERE chapter_99_code = '9903.91.03'
       AND duty_rate = 0.25
 """)
 conn.commit()
 print(f"Fixed {cursor.rowcount} rows in SQLite")
 conn.close()

 STEP 4: Implement "Strict New Only" Validation

 File: scripts/populate_tariff_tables.py

 Approach: Block NEW violations, log EXISTING legacy violations for separate cleanup.

 Why this approach:
 - Prevents recurrence immediately (new violations blocked)
 - Doesn't break ingestion today (legacy rows allowed)
 - Creates clean remediation path (legacy violations logged for cleanup ticket)

 # Note 31 heading ↔ rate invariants (legal requirement)
 NOTE_31_INVARIANTS = {
     "9903.91.01": 0.25,  # subdivision (b)
     "9903.91.02": 0.50,  # subdivision (c)
     "9903.91.03": 1.00,  # subdivision (d)
 }

 # Track legacy violations for reporting
 legacy_violations = []

 # During CSV import loop:
 if chapter_99_code in NOTE_31_INVARIANTS:
     expected_rate = NOTE_31_INVARIANTS[chapter_99_code]
     if abs(duty_rate - expected_rate) > 0.001:
         # Check if this row already exists in database (legacy)
         row_key = (hts_8digit, chapter_99_code, str(effective_start))

         existing = Section301Rate.query.filter_by(
             hts_8digit=hts_8digit,
             chapter_99_code=chapter_99_code,
             effective_start=effective_start
         ).first()

         if existing:
             # Legacy violation - log but allow
             legacy_violations.append({
                 'hts': hts_8digit,
                 'ch99': chapter_99_code,
                 'rate': duty_rate,
                 'expected': expected_rate,
                 'source': source_doc
             })
             logging.warning(
                 f"LEGACY Note 31 violation (grandfathered): {chapter_99_code} @ "
                 f"{duty_rate*100}% for HTS {hts_8digit}"
             )
         else:
             # NEW violation - fail ingestion
             raise ValueError(
                 f"NEW Note 31 invariant violation: {chapter_99_code} must have "
                 f"rate {expected_rate*100}%, got {duty_rate*100}% for HTS {hts_8digit}. "
                 f"Fix the source CSV before adding new rows."
             )

 # After import loop, generate legacy violation report
 if legacy_violations:
     report_path = 'data/reports/note31_legacy_violations.json'
     with open(report_path, 'w') as f:
         json.dump({
             'generated_at': datetime.now().isoformat(),
             'total_violations': len(legacy_violations),
             'by_heading': {
                 ch99: [v for v in legacy_violations if v['ch99'] == ch99]
                 for ch99 in set(v['ch99'] for v in legacy_violations)
             },
             'violations': legacy_violations[:20]  # Top 20 sample
         }, f, indent=2)
     logging.info(f"Legacy violation report: {report_path} ({len(legacy_violations)} rows)")

 STEP 5: Add Comprehensive Golden Tests

 File: tests/test_section301_engine.py

 Add tests for ALL Note 31 subdivisions:
 class TestNote31InvariantDatabase:
     """Test that database has correct Note 31 mapping."""

     def test_no_9903_91_03_at_25_percent(self, app):
         """9903.91.03 should NEVER have 25% rate."""
         with app.app_context():
             count = Section301Rate.query.filter(
                 Section301Rate.chapter_99_code == '9903.91.03',
                 Section301Rate.duty_rate == 0.25
             ).count()
             assert count == 0, f"Found {count} rows with 9903.91.03 @ 25% (should be 0)"

     def test_note31_heading_rate_consistency(self, app):
         """All Note 31 headings must have correct rates."""
         INVARIANTS = {
             "9903.91.01": 0.25,
             "9903.91.02": 0.50,
             "9903.91.03": 1.00,
         }
         with app.app_context():
             for ch99, expected_rate in INVARIANTS.items():
                 violations = Section301Rate.query.filter(
                     Section301Rate.chapter_99_code == ch99,
                     Section301Rate.duty_rate != expected_rate
                 ).all()
                 assert len(violations) == 0, (
                     f"Found {len(violations)} violations for {ch99}: "
                     f"expected {expected_rate*100}%, got different rates"
                 )

 12.5 FILES TO MODIFY

   FILE                                         │ ACTION
   ─────────────────────────────────────────────│───────────────────
   data/section_301_rates_temporal.csv          │ FIX: 348 rows 9903.91.03→9903.91.01
   scripts/populate_tariff_tables.py            │ CHANGE: warning → strict validation
   tests/test_section301_engine.py              │ ADD: database invariant tests

 12.6 VERIFICATION CHECKLIST

   [ ] CSV fixed: No rows with 9903.91.03 @ 0.25
   [ ] PostgreSQL fixed: Same verification
   [ ] SQLite fixed: Same verification
   [ ] Validation is strict: Ingestion fails on new violations
   [ ] Tests added: Database invariant tests pass
   [ ] Note 31 invariants hold:
       - 9903.91.01 only has 25% rates
       - 9903.91.02 only has 50% rates
       - 9903.91.03 only has 100% rates

 12.7 EXPECTED RESULTS AFTER FIX

 -- After fix, this query should return:
 SELECT chapter_99_code, duty_rate, COUNT(*) as count
 FROM section_301_rates
 WHERE chapter_99_code IN ('9903.91.01', '9903.91.02', '9903.91.03')
 GROUP BY chapter_99_code, duty_rate
 ORDER BY chapter_99_code, duty_rate;

 -- Expected:
 -- 9903.91.01 | 0.25 | 350  (was 2, now + 348 fixed rows)
 -- 9903.91.02 | 0.50 |  21  (unchanged)
 -- 9903.91.03 | 1.00 |  11  (unchanged - EVs + Syringes)

# =======
| Storage    | 9903.91.01 @ 25% | 9903.91.02 @ 50% | 9903.91.03 @ 100% | Violations |
  |------------|------------------|------------------|-------------------|------------|
  | PostgreSQL | 350 rows         | 3 rows           | 10 rows           | ✓ None     |
  | SQLite     | 350 rows         | 3 rows           | 10 rows           | ✓ None     |
  | CSV        | 350 rows         | 3 rows           | 10 rows           | ✓ None     |

⏺ All tasks complete. Here's a summary of the Note 31 bug fix:

  Fixed: 348 Rows with Incorrect Chapter 99 Heading

  | Step | Action                                                                                            | Status |
  |------|---------------------------------------------------------------------------------------------------|--------|
  | 1    | Fixed CSV source (data/section_301_rates_temporal.csv) - 348 rows changed 9903.91.03 → 9903.91.01 | ✓      |
  | 2    | Updated PostgreSQL - scoped update using source_doc='2024-21217'                                  | ✓      |
  | 3    | Updated SQLite - matching scoped update                                                           | ✓      |
  | 4    | Implemented strict-new-only validation in populate_tariff_tables.py:340-366                       | ✓      |
  | 5    | Added database invariant tests to tests/test_section301_engine.py                                 | ✓      |
  | 6    | Verified invariants across PostgreSQL, SQLite, and CSV                                            | ✓      |

  Current Note 31 Distribution (All 3 Storage Layers Match)

  9903.91.01 @ 25%:  350 rows  (subdivision b) ✓
  9903.91.02 @ 50%:    3 rows  (subdivision c) ✓
  9903.91.03 @ 100%:  10 rows  (subdivision d) ✓

  New Safeguards

  - Strict validation: New ingestion rows with Note 31 invariant violations will now fail immediately
  - Database invariant tests: TestNote31InvariantDatabase class with 3 tests catches future regressions
  - Float tolerance: All comparisons use 1e-6 or 0.01 tolerance to avoid flaky results


