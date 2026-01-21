# Tests Added - January 2026

## New Test Files

### tests/test_normalization.py

Tests HTS and country code normalization consistency across the codebase.

**Classes:**

| Class | Purpose |
|-------|---------|
| `TestHTSNormalization` | HTS code normalization (dots, spaces, lengths) |
| `TestCountryNormalization` | Country code to ISO-2 conversion |
| `TestHTSTo8Digit` | 10-digit to 8-digit truncation |

**Key Tests:**

- `test_normalize_dotted_8digit`: "8544.42.90" → "85444290"
- `test_normalize_dotted_10digit`: "8544.42.9090" → "8544429090"
- `test_normalize_with_spaces`: " 8544.42.90 " → "85444290"
- `test_all_normalizers_consistent_*`: Verifies HTSValidator, WriteGate, and inline normalizers produce identical output
- `test_country_name_to_iso2`: "China" → "CN"
- `test_germany_variants`: All of "Germany", "DE", "de" → "DE"
- `test_hong_kong_variants`: "Hong Kong", "HK", "hong kong" → "HK"

**Normalizers Tested:**

- `app/services/hts_validator.py:HTSValidator._normalize_hts()`
- `app/services/write_gate.py:WriteGate._normalize_hts()`
- `app/chat/tools/stacking_tools.py:normalize_country()`
- Inline pattern: `hts_code.replace(".", "")[:8]`

---

### tests/test_role_precedence.py

Tests that Section 301 exclusions (role='exclude') always take precedence over impose rates (role='impose').

**Classes:**

| Class | Purpose |
|-------|---------|
| `TestRolePrecedence` | Core exclusion vs impose precedence |
| `TestRolePrecedenceEdgeCases` | Edge cases (same day, multiple exclusions) |

**Key Tests:**

- `test_exclude_beats_impose_same_hts`: When both exist, exclusion (0%) wins over impose (25%)
- `test_impose_when_no_exclusion`: Impose rate returned when no active exclusion
- `test_exclusion_respects_effective_dates`: Future exclusions don't apply before their effective_start
- `test_expired_exclusion_falls_back_to_impose`: After exclusion expires, impose applies
- `test_exclusion_starts_same_day_as_impose`: Exclusion wins when effective dates match
- `test_multiple_exclusions_returns_most_recent`: Most recent exclusion returned

**Implementation Detail:**

The precedence is implemented in `Section301Rate.get_rate_as_of()` using:

```python
.order_by(
    case((cls.role == 'exclude', 0), else_=1),  # Exclusions first
    cls.effective_start.desc()                   # Most recent within priority
)
```

---

## Bug Fix

### CommitEngine Race Condition

**Problem:** Without row locking, two concurrent document processors could both read the same "active" rate and both try to supersede it, creating duplicate rates in the database.

**Solution:** Added `.with_for_update()` to lock rows during transaction.

**File:** `app/workers/commit_engine.py`

**Changes:** 6 locations (2 per rate type × 3 rate types)

| Rate Table | Function | Line |
|------------|----------|------|
| Section301Rate | `_commit_301()` | ~149 |
| Section301Rate | `_commit_301_schedule()` | ~253 |
| Section232Rate | `_commit_232()` | ~385 |
| Section232Rate | `_commit_232_schedule()` | ~478 |
| IeepaRate | `_commit_ieepa()` | ~558 |
| IeepaRate | `_commit_ieepa_schedule()` | ~645 |

**Before (vulnerable):**
```python
existing = Section301Rate.query.filter(
    Section301Rate.hts_8digit == hts_8digit,
    Section301Rate.effective_end.is_(None)
).all()
```

**After (fixed):**
```python
existing = Section301Rate.query.filter(
    Section301Rate.hts_8digit == hts_8digit,
    Section301Rate.effective_end.is_(None)
).with_for_update().all()
```

**How it works:**
- `with_for_update()` acquires a row-level lock on matching rows
- Other transactions wait until the lock is released
- Combined with `db.session.begin_nested()` (SAVEPOINT), ensures atomic supersession

---

## Running the Tests

```bash
# Run all new tests
pipenv run pytest tests/test_normalization.py tests/test_role_precedence.py -v

# Run specific test class
pipenv run pytest tests/test_role_precedence.py::TestRolePrecedence -v
```
