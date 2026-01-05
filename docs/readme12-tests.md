# Lanes Tariff System - Test Documentation

**Version:** v9.3 (Evidence-First Citations + Vector Indexing)
**Date:** January 2026
**Total Tests:** 121+

---

## Table of Contents

1. [Test Summary](#1-test-summary)
2. [Tariff Amount Tests (CRITICAL)](#2-tariff-amount-tests-critical)
3. [Tariff Stacking Tests](#3-tariff-stacking-tests)
4. [V9 Search Persistence Tests](#4-v9-search-persistence-tests)
5. [Vector Indexing Tests](#5-vector-indexing-tests)
6. [MCP Parsing Tests](#6-mcp-parsing-tests)
7. [Reference Tables](#7-reference-tables)
8. [Running Tests](#8-running-tests)

---

## 1. Test Summary

### Test Files Overview

| Category | File | Tests | Purpose |
|----------|------|-------|---------|
| **Tariff Stacking** | `test_stacking_v7_phoebe.py` | 7 | Phoebe-aligned ACE filing (dollar amounts) |
| **Tariff Stacking** | `test_stacking_automated.py` | 12 | Phase 6/6.5 duty calculations |
| **Tariff Stacking** | `test_stacking_v7_stability.py` | 7 | Edge cases and error handling |
| **V9 Search** | `test_v9_search_persistence.py` | 23 | PostgreSQL/cache layer tests |
| **V9 Vector** | `test_vector_indexing.py` | 18 | Pinecone/evidence quote indexing |
| **MCP Parsing** | `test_mcp_parsing.py` | 54+ | JSON parsing and schema validation |
| **Total** | | **121+** | |

---

## 2. Tariff Amount Tests (CRITICAL)

These tests verify exact dollar amounts for tariff calculations. They are the most business-critical tests.

### 2.1 v7.0 Phoebe Example Tests (7 tests)

**File:** `tests/test_stacking_v7_phoebe.py`

These tests are based on real Phoebe ACE filing examples and verify exact tariff amounts.

#### TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)

```
Input:
  HTS: 9403.99.9045 (Furniture parts)
  Country: China
  Value: $123.12
  Quantity: 6
  Materials: steel=$61.56, aluminum=$61.56

Expected:
  - 2 slices (steel_claim, aluminum_claim)
  - NO residual slice (all value allocated)
  - Steel uses derivative code 9903.81.91
  - No copper codes (not applicable to this HTS)
  - disclaim_behavior='omit' for steel/aluminum

Total Duty: Based on $123.12 product value
```

#### TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $36.00
  Quantity: 3
  Materials: copper=$18.00, aluminum=$18.00

Expected:
  - 2 slices (copper_claim, aluminum_claim)
  - Copper disclaim (9903.78.02) in aluminum slice (required behavior)
  - Aluminum OMITTED in copper slice (omit behavior)

Total Duty: Based on $36.00 product value
```

#### TC-v7.0-003: No 232 Claimed (Residual Only)

```
Input:
  HTS: 8536.90.8585 (Electrical switches)
  Country: China
  Value: $174.00
  Quantity: 3
  Materials: {} (none)

Expected:
  - 1 slice (full product)
  - NO 232 codes (omitted entirely)
  - 301 code: 9903.88.01 (List 1)
  - IEEPA Reciprocal: 9903.01.25 (paid)

Total Duty: Based on $174.00 product value
  - Section 301: $174.00 × 25% = $43.50
  - IEEPA Fentanyl: $174.00 × 10% = $17.40
  - IEEPA Reciprocal: $174.00 × 10% = $17.40
```

#### TC-v7.0-004: Copper Full Claim

```
Input:
  HTS: 8544.42.2000
  Country: China
  Value: $66.00
  Quantity: 6
  Materials: copper=$66.00

Expected:
  - 1 slice (copper_slice)
  - No residual (100% copper)
  - Copper claim code: 9903.78.01

Total Duty: Based on $66.00 product value
  - Section 232 Copper: $66.00 × 50% = $33.00
```

#### TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)

```
Input:
  HTS: 9403.99.9045
  Country: China
  Value: $3,348.00
  Quantity: 18
  Materials: steel=$3,046.68, aluminum=$21.09

Expected:
  - 3 slices (residual $280.23, steel_claim, aluminum_claim)
  - Residual: NO steel disclaim, NO aluminum disclaim
  - Steel: Uses 9903.81.91 (derivative)

Total Duty: Based on $3,348.00 product value
  - Residual value: $3,348.00 - $3,046.68 - $21.09 = $280.23
  - Section 232 Steel: $3,046.68 × 50% = $1,523.34
  - Section 232 Aluminum: $21.09 × 25% = $5.27
```

#### TC-v7.0-006: Annex II Exemption

```
Input:
  HTS: 8473.30.5100 (Computer parts)
  Country: China
  Value: $842.40
  Quantity: 27
  Materials: aluminum=$126.36

Expected:
  - 2 slices (residual, aluminum_claim)
  - IEEPA Reciprocal: 9903.01.32 (Annex II exempt)
  - 301 code: 9903.88.69

Total Duty: Based on $842.40 product value
  - Annex II exemption reduces IEEPA Reciprocal duty
```

#### TC-v7.0-008: No Steel/Aluminum Disclaim Codes

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $1,000.00
  Materials: copper=$1,000.00

Expected:
  - NO 9903.80.02 (steel disclaim) in any output
  - NO 9903.85.09 (aluminum disclaim) in any output
  - Only copper claim code appears

Purpose: Verify disclaim_behavior='omit' works correctly
```

---

### 2.2 Automated Stacking Tests (12 tests)

**File:** `tests/test_stacking_automated.py`

These tests verify full duty calculations with exact dollar amounts and effective rates.

#### Case 1: USB-C China Full Scenario

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $10,000.00
  Materials: copper=5%, steel=20%, aluminum=72%, zinc=3%
  (Converted to: copper=$500, steel=$2,000, aluminum=$7,200)

Duty Breakdown:
  - Section 301:      $10,000 × 25%  = $2,500.00
  - IEEPA Fentanyl:   $10,000 × 10%  = $1,000.00
  - 232 Copper:       $500 × 50%     = $250.00
  - 232 Steel:        $2,000 × 50%   = $1,000.00
  - 232 Aluminum:     $7,200 × 25%   = $1,800.00
  - IEEPA Reciprocal: $300 × 10%     = $30.00

Total Duty: $6,580.00
Effective Rate: 65.8%
Entries: 4 (non_metal $300 + copper $500 + steel $2,000 + aluminum $7,200)
```

#### Case 2: High Steel Content

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $10,000.00
  Materials: copper=15%, steel=80%, aluminum=3%, zinc=2%

Duty Breakdown:
  - Section 301:      $10,000 × 25%  = $2,500.00
  - IEEPA Fentanyl:   $10,000 × 10%  = $1,000.00
  - 232 Copper:       $1,500 × 50%   = $750.00
  - 232 Steel:        $8,000 × 50%   = $4,000.00
  - 232 Aluminum:     $300 × 25%     = $75.00
  - IEEPA Reciprocal: $200 × 10%     = $20.00

Total Duty: $8,345.00
Effective Rate: 83.45%
```

#### Case 3: All Materials at 10%

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $10,000.00
  Materials: copper=10%, steel=10%, aluminum=10%

Duty Breakdown:
  - Section 301:      $10,000 × 25%  = $2,500.00
  - IEEPA Fentanyl:   $10,000 × 10%  = $1,000.00
  - 232 Copper:       $1,000 × 50%   = $500.00
  - 232 Steel:        $1,000 × 50%   = $500.00
  - 232 Aluminum:     $1,000 × 25%   = $250.00
  - IEEPA Reciprocal: $7,000 × 10%   = $700.00

Total Duty: $5,450.00
Effective Rate: 54.5%
```

#### Case 4: Non-China Origin (Germany)

```
Input:
  HTS: 8544.42.9090
  Country: Germany
  Value: $10,000.00
  Materials: copper=5%, steel=20%, aluminum=72%

Duty Breakdown (232 only - no China programs):
  - 232 Copper:   $500 × 50%     = $250.00
  - 232 Steel:    $2,000 × 50%   = $1,000.00
  - 232 Aluminum: $7,200 × 25%   = $1,800.00

Total Duty: $3,050.00
Effective Rate: 30.5%
Programs: 3 (only Section 232)
```

#### Case 5: IEEPA Unstacking (Phase 6.5)

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $10,000.00
  Materials: copper=30%, steel=10%, aluminum=10%

IEEPA Unstacking Calculation:
  remaining_value = $10,000 - $3,000 - $1,000 - $1,000 = $5,000

Duty Breakdown:
  - Section 301:      $10,000 × 25%  = $2,500.00
  - IEEPA Fentanyl:   $10,000 × 10%  = $1,000.00
  - 232 Copper:       $3,000 × 50%   = $1,500.00
  - 232 Steel:        $1,000 × 50%   = $500.00
  - 232 Aluminum:     $1,000 × 25%   = $250.00
  - IEEPA Reciprocal: $5,000 × 10%   = $500.00 (NOT $1,000!)

Total Duty: $6,250.00
Effective Rate: 62.5%

Key: IEEPA Reciprocal is on remaining_value, NOT product_value
```

#### Case 6: No Double-Subtraction Validation

```
Input: Same as Case 5

Validation:
  - remaining_value must be $5,000 (NOT $0)
  - Each material deducted exactly ONCE:
    - Copper: $3,000 (not $6,000)
    - Steel: $1,000 (not $2,000)
    - Aluminum: $1,000 (not $2,000)

Purpose: Catch the double-subtraction bug
```

#### v4.0 Case 1: UK Chemical (Annex II Exempt)

```
Input:
  HTS: 2934.99.9050 (Plasmid/Chemical)
  Country: UK
  Value: $1,000.00
  Materials: {} (none)

Expected:
  - UK subject to IEEPA Reciprocal
  - BUT HTS 2934.99 is Annex II exempt (pharmaceutical)
  - IEEPA Reciprocal: 9903.01.32 (exempt, variant='annex_ii_exempt')

Total Duty: $0.00
Entries: 1 (full, no metals)
```

#### v4.0 Case 2: China 3-Metal Cable

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $10,000.00
  Materials: copper=$3,000, steel=$1,000, aluminum=$1,000

Entries:
  1. non_metal ($5,000): 301[apply], Fentanyl[apply], Reciprocal[paid]
  2. copper_slice ($3,000): 301[apply], Fentanyl[apply], Reciprocal[exempt], Copper[claim]
  3. steel_slice ($1,000): 301[apply], Fentanyl[apply], Reciprocal[exempt], Steel[claim]
  4. aluminum_slice ($1,000): 301[apply], Fentanyl[apply], Reciprocal[exempt], Aluminum[claim]

Total Duty: $6,250.00
Effective Rate: 62.5%
```

#### v4.0 Case 3: Germany 3-Metal Cable (232 only)

```
Input:
  HTS: 8544.42.9090
  Country: Germany
  Value: $10,000.00
  Materials: copper=$3,000, steel=$1,000, aluminum=$1,000

Expected:
  - NO Section 301 (not China)
  - NO IEEPA Fentanyl (not China)
  - NO IEEPA Reciprocal (not China)
  - ONLY Section 232 programs

Total Duty: $2,250.00
Effective Rate: 22.5%
```

#### v4.0 Case 4: China Single-Metal (Copper only)

```
Input:
  HTS: 8544.42.9090
  Country: China
  Value: $10,000.00
  Materials: copper=$3,000

Duty Breakdown:
  - Section 301:      $10,000 × 25%  = $2,500.00
  - IEEPA Fentanyl:   $10,000 × 10%  = $1,000.00
  - 232 Copper:       $3,000 × 50%   = $1,500.00
  - IEEPA Reciprocal: $7,000 × 10%   = $700.00

Total Duty: $5,700.00
Effective Rate: 57.0%
Entries: 2 (non_metal $7,000 + copper_slice $3,000)
```

---

## 3. Tariff Stacking Tests

### 3.1 v7.0 Stability Tests (7 tests)

**File:** `tests/test_stacking_v7_stability.py`

| Test ID | Description | Purpose |
|---------|-------------|---------|
| TC-v7.0-009 | Quantity Duplication | All slices get same quantity (100), values split |
| TC-v7.0-010 | Rounding / Penny Drift | No drift when values are $33.33 × 3 = $99.99 |
| TC-v7.0-011 | Invalid Allocation | Handle sum of materials > product value |
| TC-v7.0-013 | Copper Applicable, No Copper Slice | Copper disclaim in all non-copper slices |
| TC-v7.0-014 | No Duplicate Copper Disclaim | Exactly 1 copper disclaim per slice |
| TC-v7.0-015 | Slice Value Sum Validation | Sum of slices = product value |
| TC-v7.0-016 | Zero Metal Value Handling | No slice for $0 metal values |

---

## 4. V9 Search Persistence Tests

**File:** `tests/test_v9_search_persistence.py` (23 tests)

### 4.1 Model Tests

| Test | Description |
|------|-------------|
| `test_create_search_result` | Create GeminiSearchResult record |
| `test_is_expired_with_no_expiry` | Results without expiry never expire |
| `test_is_expired_with_future_expiry` | Future expiry = not expired |
| `test_is_expired_with_past_expiry` | Past expiry = expired |
| `test_verified_results_never_expire` | is_verified=True bypasses expiry |
| `test_as_dict` | Serialization to dictionary |
| `test_create_grounding_source` | Create linked grounding source |
| `test_cascade_delete` | Delete parent cascades to children |
| `test_create_audit_log` | Create SearchAuditLog entry |

### 4.2 Vector Search Tests

| Test | Description |
|------|-------------|
| `test_split_into_chunks_short_text` | Short text = 1 chunk |
| `test_split_into_chunks_with_paragraphs` | Paragraph-based chunking |
| `test_split_into_chunks_long_text` | Long text splits properly |
| `test_split_into_chunks_empty_text` | Empty = 0 chunks |
| `test_create_embedding` | OpenAI embedding creation |
| `test_chunk_and_embed` | Chunk + embed returns vector format |

### 4.3 Source Reliability Tests

| Test | Description |
|------|-------------|
| `test_extract_domain` | URL → domain extraction |
| `test_classify_source_type` | Domain → source type (official_cbp, federal_register, etc.) |
| `test_get_reliability_score` | Source type → reliability score (1.0, 0.95, 0.50) |

### 4.4 Cache Tests

| Test | Description |
|------|-------------|
| `test_generate_uuid` | UUID generation |
| `test_check_postgres_cache_miss` | Cache miss when no data |
| `test_check_postgres_cache_hit` | Cache hit when data exists |
| `test_check_cache_before_gemini_force_search` | force_search bypasses cache |
| `test_verify_hts_scope_output_format` | Output format validation |

---

## 5. Vector Indexing Tests

**File:** `tests/test_vector_indexing.py` (18 tests)

### 5.1 Evidence Quote Indexing Tests

| Test | Description |
|------|-------------|
| `test_index_evidence_quotes_creates_vectors` | 2 citations → 2 vectors |
| `test_chunk_type_is_evidence_quote` | metadata.chunk_type = "evidence_quote" |
| `test_metadata_includes_decision_fields` | in_scope, claim_code, material in metadata |
| `test_url_in_grounding_metadata_flag` | URL matching → url_in_grounding_metadata=True |
| `test_citations_without_quoted_text_skipped` | quoted_text=null → not indexed |
| `test_reliability_score_from_domain` | cbp.gov = 1.0, other = 0.50 |
| `test_empty_results_returns_zero` | No results → 0 vectors |

### 5.2 Search Filter Tests

| Test | Description |
|------|-------------|
| `test_search_filters_by_chunk_type` | Filter by chunk_type="evidence_quote" |
| `test_search_filters_by_material` | Filter by material="copper" |
| `test_search_combines_multiple_filters` | Combine hts_code + query_type + chunk_type + material |

### 5.3 Evidence Quote Persistence Tests

| Test | Description |
|------|-------------|
| `test_persist_evidence_quotes_creates_records` | Creates EvidenceQuote records |
| `test_quote_hash_is_computed` | SHA256 hash of quoted_text |
| `test_url_in_grounding_metadata_computed` | URL in grounding → True |
| `test_effective_date_parsed` | "2025-08-18" → date(2025, 8, 18) |
| `test_non_v92_response_returns_zero` | Legacy response → 0 quotes |

### 5.4 Helper Function Tests

| Test | Description |
|------|-------------|
| `test_extract_domain` | URL parsing |
| `test_classify_source_type` | Domain classification |
| `test_get_reliability_score` | Score lookup |

---

## 6. MCP Parsing Tests

**File:** `tests/test_mcp_parsing.py` (54+ tests)

### 6.1 parse_json_response Tests

| Test | Description |
|------|-------------|
| `test_valid_json_only` | Pure JSON parsed correctly |
| `test_json_with_preamble` | "Based on my search..." + JSON |
| `test_json_with_postamble` | JSON + "I hope this helps..." |
| `test_json_with_preamble_and_postamble` | Text + JSON + text |
| `test_nested_json` | Nested objects parsed |
| `test_invalid_json_returns_raw` | Bad JSON → {"raw_response": ...} |
| `test_partial_json_returns_raw` | Truncated JSON → raw_response |
| `test_empty_string` | "" → {"raw_response": ""} |
| `test_json_with_markdown_code_block` | ```json ... ``` |
| `test_multiple_json_objects_takes_outer` | Outer object returned |
| `test_json_with_arrays` | Arrays parsed correctly |
| `test_unicode_in_json` | Unicode characters handled |
| `test_json_with_special_chars` | Special chars (# , etc.) |

### 6.2 Schema Validation Tests

| Test | Description |
|------|-------------|
| `test_valid_section_232_result` | Valid data passes |
| `test_missing_required_field_fails` | Missing hts_code → ValidationError |
| `test_wrong_type_for_in_scope` | in_scope="yes" → ValidationError |
| `test_string_true_coercion` | "true" not coerced to True |
| `test_section_301_valid_result` | Section 301 schema validation |
| `test_section_301_minimal_valid` | Required fields only |

### 6.3 extract_grounding_urls Tests

| Test | Description |
|------|-------------|
| `test_empty_response` | No candidates → [] |
| `test_no_candidates` | candidates=None → [] |
| `test_candidates_no_metadata` | No grounding_metadata → [] |
| `test_metadata_no_chunks` | No grounding_chunks → [] |
| `test_single_grounding_url` | 1 URL extracted |
| `test_multiple_grounding_urls` | Multiple URLs extracted |
| `test_chunk_without_web` | web=None → skipped |
| `test_exception_handling` | Graceful exception handling |

### 6.4 v9.2 Citation Schema Tests

| Test | Description |
|------|-------------|
| `test_valid_citation_full` | All citation fields |
| `test_citation_minimal` | source_url only |
| `test_citation_with_null_quoted_text` | quoted_text=null valid |
| `test_citation_missing_source_url_fails` | source_url required |
| `test_valid_metal_scope_v2` | MetalScopeV2 with citations[] |
| `test_metal_scope_v2_null_in_scope` | in_scope=null (unknown) |
| `test_metal_scope_v2_multiple_citations` | Multiple citations |
| `test_metal_scope_v2_empty_citations` | citations=[] valid |
| `test_valid_section_232_result_v2` | V2 nested results structure |
| `test_section_232_v2_validation_function` | validate_section_232_v2() |
| `test_section_232_v2_validation_raw_response` | Parse failure handling |

### 6.5 Business Validation Tests

| Test | Description |
|------|-------------|
| `test_validate_citations_have_proof_success` | in_scope=True + proof → pass |
| `test_validate_citations_have_proof_missing_claim_code` | in_scope=True, no claim_code → error |
| `test_validate_citations_have_proof_missing_citation` | in_scope=True, no citations → error |
| `test_validate_citations_have_proof_citation_no_quote` | Citation without quoted_text → error |
| `test_validate_citations_have_proof_null_in_scope_ok` | in_scope=None doesn't require proof |
| `test_validate_citations_have_proof_false_in_scope_ok` | in_scope=False doesn't require proof |

### 6.6 Citation HTS Validation Tests

| Test | Description |
|------|-------------|
| `test_quote_contains_hts_10_digit` | "8544.42.9090" in quote → no warning |
| `test_quote_contains_hts_8_digit` | "8544.42.90" in quote → no warning |
| `test_quote_missing_hts_warning` | No HTS in quote → warning |
| `test_quote_hts_without_dots` | "85444290" matches → no warning |

---

## 7. Reference Tables

### 7.1 Tariff Rates

| Program | Rate | Base |
|---------|------|------|
| Section 301 (List 1-3) | 25% | Product value |
| Section 301 (List 4A) | 7.5% | Product value |
| IEEPA Fentanyl | 10% | Product value |
| IEEPA Reciprocal | 10% | remaining_value (after 232) |
| Section 232 Copper | 50% | Copper content value |
| Section 232 Steel | 50% | Steel content value |
| Section 232 Aluminum | 25% | Aluminum content value |

### 7.2 Key Chapter 99 Codes

| Code | Program | Action |
|------|---------|--------|
| 9903.78.01 | Section 232 Copper | Claim |
| 9903.78.02 | Section 232 Copper | Disclaim |
| 9903.80.01-03 | Section 232 Steel | Claim |
| 9903.81.91 | Section 232 Steel (Derivative) | Claim |
| 9903.85.01-08 | Section 232 Aluminum | Claim |
| 9903.88.01 | Section 301 List 1 | Apply |
| 9903.88.02 | Section 301 List 2 | Apply |
| 9903.88.03 | Section 301 List 3 | Apply |
| 9903.88.15 | Section 301 List 4A | Apply |
| 9903.88.69 | Section 301 (other) | Apply |
| 9903.01.25 | IEEPA Reciprocal | Paid |
| 9903.01.32 | IEEPA Annex II | Exempt |

### 7.3 Disclaim Behavior

| Material | Behavior | Effect |
|----------|----------|--------|
| Copper | `required` | Disclaim (9903.78.02) in ALL non-copper slices |
| Steel | `omit` | Never appears as disclaim |
| Aluminum | `omit` | Never appears as disclaim |

### 7.4 Source Reliability Scores

| Domain | Source Type | Score |
|--------|-------------|-------|
| cbp.gov | official_cbp | 1.0 |
| federalregister.gov | federal_register | 1.0 |
| ustr.gov | ustr | 0.95 |
| usitc.gov | usitc | 0.95 |
| (other) | other | 0.50 |

---

## 8. Running Tests

### 8.1 All Tests

```bash
cd lanes
pipenv run pytest tests/ -v
```

### 8.2 Specific Test Files

```bash
# Phoebe ACE filing tests (tariff amounts)
pipenv run pytest tests/test_stacking_v7_phoebe.py -v

# Automated stacking tests (duty calculations)
pipenv run pytest tests/test_stacking_automated.py -v

# V9 search persistence tests
pipenv run pytest tests/test_v9_search_persistence.py -v

# Vector indexing tests
pipenv run pytest tests/test_vector_indexing.py -v

# MCP parsing tests
pipenv run pytest tests/test_mcp_parsing.py -v
```

### 8.3 Non-pytest Test Files

Some test files use a custom runner:

```bash
# v7.0 Phoebe tests
pipenv run python tests/test_stacking_v7_phoebe.py -v

# Automated stacking tests
pipenv run python tests/test_stacking_automated.py -v

# Stability tests
pipenv run python tests/test_stacking_v7_stability.py -v
```

### 8.4 Coverage

```bash
pipenv run pytest tests/ --cov=app --cov=mcp_servers --cov-report=html
```

---

## Quick Reference: Critical Dollar Amount Tests

| Test | Input Value | Materials | Expected Duty | Rate |
|------|-------------|-----------|---------------|------|
| Case 1 | $10,000 | Cu 5%, St 20%, Al 72% | **$6,580** | 65.8% |
| Case 2 | $10,000 | Cu 15%, St 80%, Al 3% | **$8,345** | 83.45% |
| Case 3 | $10,000 | Cu 10%, St 10%, Al 10% | **$5,450** | 54.5% |
| Case 4 (DE) | $10,000 | Cu 5%, St 20%, Al 72% | **$3,050** | 30.5% |
| Case 5 | $10,000 | Cu 30%, St 10%, Al 10% | **$6,250** | 62.5% |
| v4.0-1 (UK) | $1,000 | None (Annex II) | **$0** | 0% |
| v4.0-4 (CN) | $10,000 | Cu $3,000 only | **$5,700** | 57.0% |

---

*Generated: January 2026*
