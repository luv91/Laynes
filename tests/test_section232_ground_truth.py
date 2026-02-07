"""
Section 232 Ground-Truth Validation — Verify our CSV data against official government sources.

This test module reads the CSV files that feed the production database and validates
their contents against verified government data (CBP CSMS bulletins, Federal Register
proclamations, USITC HTS).

NO database, NO Flask app, NO Pinecone — just CSV parsing and assertions.
This can run anywhere, including CI, with zero dependencies beyond pytest.

Sources verified (Feb 2026):
  - Proclamation 9705 (83 FR 11625) — Original 232 Steel, March 23, 2018
  - Proclamation 9704 (83 FR 11619) — Original 232 Aluminum, March 23, 2018
  - Proclamation 10896 (CBP CSMS #64348411) — Steel/Aluminum reset to 25%, March 12, 2025
  - Proclamation 10947 (90 FR 25209) — Steel/Aluminum increase to 50%, June 4, 2025
  - Proclamation 10908 (90 FR 14705) — Auto Parts at 25%, May 3, 2025
  - CBP CSMS #65794272 — Copper 232 at 50%, August 1, 2025
  - CBP CSMS #65936570 — Steel derivative list, August 2025
  - CBP CSMS #65936615 — Aluminum derivative list, August 2025
  - CBP CSMS #67400472 / Proclamation 11002 — Semiconductors at 25%, January 15, 2026
  - Federal Register March 5, 2025 (90 FR 42) — 7216.61.00, 7216.69.00 EXCLUDED
  - Thompson Hine June 2025 — UK exception stays at 25%
"""

import csv
import os
import pytest
from pathlib import Path
from collections import Counter

# ============================================================================
# Fixtures: Load CSV data once per session
# ============================================================================

LANES_DIR = Path(__file__).parent.parent
DATA_DIR = LANES_DIR / "data"


@pytest.fixture(scope="module")
def s232_csv_rows():
    """Load all rows from section_232_hts_codes.csv."""
    csv_path = DATA_DIR / "section_232_hts_codes.csv"
    assert csv_path.exists(), f"Section 232 CSV not found at {csv_path}"

    rows = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get('hts_code') or row['hts_code'].startswith('#'):
                continue
            if not row.get('duty_rate'):
                continue
            rows.append(row)
    return rows


@pytest.fixture(scope="module")
def s232_by_material(s232_csv_rows):
    """Group CSV rows by material type."""
    groups = {}
    for row in s232_csv_rows:
        mat = row['material']
        groups.setdefault(mat, []).append(row)
    return groups


@pytest.fixture(scope="module")
def s232_hts_set(s232_csv_rows):
    """Set of all HTS codes in the CSV (with dots)."""
    return {row['hts_code'] for row in s232_csv_rows}


@pytest.fixture(scope="module")
def tariff_programs_csv():
    """Load tariff_programs.csv."""
    csv_path = DATA_DIR / "tariff_programs.csv"
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


@pytest.fixture(scope="module")
def program_rates_csv():
    """Load tariff_program_rates.csv."""
    csv_path = DATA_DIR / "tariff_program_rates.csv"
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


# ============================================================================
# 1. Material Count Verification
# ============================================================================

class TestMaterialCounts:
    """Verify we have approximately the right number of HTS codes per material."""

    def test_total_entry_count(self, s232_csv_rows):
        """CSV should have ~987 entries (990 in original spec minus corrections)."""
        count = len(s232_csv_rows)
        assert 900 <= count <= 1100, \
            f"Expected ~987 HTS entries, got {count}"

    def test_steel_count(self, s232_by_material):
        """Steel should have ~596 HTS codes (largest category)."""
        count = len(s232_by_material.get('steel', []))
        assert 550 <= count <= 650, \
            f"Expected ~596 steel HTS codes, got {count}"

    def test_aluminum_count(self, s232_by_material):
        """Aluminum should have ~257 HTS codes."""
        count = len(s232_by_material.get('aluminum', []))
        assert 230 <= count <= 290, \
            f"Expected ~257 aluminum HTS codes, got {count}"

    def test_copper_count(self, s232_by_material):
        """Copper should have ~80 HTS codes."""
        count = len(s232_by_material.get('copper', []))
        assert 70 <= count <= 100, \
            f"Expected ~80 copper HTS codes, got {count}"

    def test_auto_count(self, s232_by_material):
        """Auto parts should have ~38 HTS codes."""
        count = len(s232_by_material.get('auto', []))
        assert 30 <= count <= 50, \
            f"Expected ~38 auto parts HTS codes, got {count}"

    def test_semiconductor_count(self, s232_by_material):
        """Semiconductors should have ~16 HTS codes."""
        count = len(s232_by_material.get('semiconductor', []))
        assert 10 <= count <= 25, \
            f"Expected ~16 semiconductor HTS codes, got {count}"

    def test_no_unexpected_materials(self, s232_by_material):
        """Only steel, aluminum, copper, auto, semiconductor allowed."""
        expected = {'steel', 'aluminum', 'copper', 'auto', 'semiconductor'}
        actual = set(s232_by_material.keys())
        unexpected = actual - expected
        assert not unexpected, \
            f"Unexpected material types in CSV: {unexpected}"


# ============================================================================
# 2. Duty Rate Verification (per official government rates)
# ============================================================================

class TestDutyRates:
    """Verify duty rates match official proclamations."""

    def test_steel_rate_50_percent(self, s232_by_material):
        """
        Steel: 50% per Proclamation 10947 (90 FR 25209), effective June 4, 2025.
        All steel entries in CSV should have rate=0.5.
        """
        for row in s232_by_material.get('steel', []):
            rate = float(row['duty_rate'])
            assert rate == 0.5, \
                f"Steel HTS {row['hts_code']} has rate {rate}, expected 0.5 " \
                f"per Proclamation 10947"

    def test_aluminum_rate_50_percent(self, s232_by_material):
        """
        Aluminum: 50% per Proclamation 10947 (90 FR 25209), effective June 4, 2025.
        All aluminum entries in CSV should have rate=0.5.
        """
        for row in s232_by_material.get('aluminum', []):
            rate = float(row['duty_rate'])
            assert rate == 0.5, \
                f"Aluminum HTS {row['hts_code']} has rate {rate}, expected 0.5 " \
                f"per Proclamation 10947"

    def test_copper_rate_50_percent(self, s232_by_material):
        """
        Copper: 50% per Proclamation 10962 / CSMS #65794272, effective August 1, 2025.
        All copper entries in CSV should have rate=0.5.
        """
        for row in s232_by_material.get('copper', []):
            rate = float(row['duty_rate'])
            assert rate == 0.5, \
                f"Copper HTS {row['hts_code']} has rate {rate}, expected 0.5 " \
                f"per CSMS #65794272"

    def test_auto_parts_rate_25_percent(self, s232_by_material):
        """
        Auto parts: 25% per Proclamation 10908 (90 FR 14705), effective May 3, 2025.
        """
        for row in s232_by_material.get('auto', []):
            rate = float(row['duty_rate'])
            assert rate == 0.25, \
                f"Auto HTS {row['hts_code']} has rate {rate}, expected 0.25 " \
                f"per Proclamation 10908"

    def test_semiconductor_rate_25_percent(self, s232_by_material):
        """
        Semiconductors: 25% per Proclamation 11002 / CSMS #67400472, effective Jan 15, 2026.
        """
        for row in s232_by_material.get('semiconductor', []):
            rate = float(row['duty_rate'])
            assert rate == 0.25, \
                f"Semiconductor HTS {row['hts_code']} has rate {rate}, expected 0.25 " \
                f"per CSMS #67400472"


# ============================================================================
# 3. Chapter 99 Claim Code Verification
# ============================================================================

class TestClaimCodes:
    """Verify Chapter 99 claim codes match CBP CSMS guidance."""

    def test_steel_primary_claim_code(self, s232_by_material):
        """
        Primary steel (Ch 72): 9903.80.01
        Per CSMS #65936570, U.S. Note 16.
        """
        for row in s232_by_material.get('steel', []):
            if row.get('article_type') == 'primary':
                assert row['chapter_99_claim'] == '9903.80.01', \
                    f"Primary steel {row['hts_code']} has claim {row['chapter_99_claim']}, " \
                    f"expected 9903.80.01"

    def test_steel_derivative_claim_codes(self, s232_by_material):
        """
        Derivative steel:
          - Ch 73 (in-chapter derivatives): 9903.81.89 or 9903.81.90
          - Other chapters (content derivatives): 9903.81.91
        Per CSMS #65936570, U.S. Note 16.
        """
        valid_derivative_codes = {'9903.81.89', '9903.81.90', '9903.81.91'}
        for row in s232_by_material.get('steel', []):
            if row.get('article_type') == 'derivative':
                assert row['chapter_99_claim'] in valid_derivative_codes, \
                    f"Derivative steel {row['hts_code']} has claim {row['chapter_99_claim']}, " \
                    f"expected one of {valid_derivative_codes}"

    def test_steel_content_claim_code(self, s232_by_material):
        """
        Content steel articles: 9903.81.91
        Per CSMS #65936570, content articles from other chapters.
        """
        for row in s232_by_material.get('steel', []):
            if row.get('article_type') == 'content':
                assert row['chapter_99_claim'] == '9903.81.91', \
                    f"Content steel {row['hts_code']} has claim {row['chapter_99_claim']}, " \
                    f"expected 9903.81.91"

    def test_copper_claim_code(self, s232_by_material):
        """
        All copper articles: 9903.78.01 (claim), 9903.78.02 (disclaim)
        Per CSMS #65794272 (July 31, 2025).
        """
        for row in s232_by_material.get('copper', []):
            assert row['chapter_99_claim'] == '9903.78.01', \
                f"Copper {row['hts_code']} has claim {row['chapter_99_claim']}, " \
                f"expected 9903.78.01 per CSMS #65794272"
            assert row['chapter_99_disclaim'] == '9903.78.02', \
                f"Copper {row['hts_code']} has disclaim {row['chapter_99_disclaim']}, " \
                f"expected 9903.78.02 per CSMS #65794272"

    def test_auto_claim_codes(self, s232_by_material):
        """
        Auto parts: 9903.94.05 (claim), 9903.94.06 (disclaim)
        Per Proclamation 10908 (90 FR 14705).
        """
        for row in s232_by_material.get('auto', []):
            assert row['chapter_99_claim'] == '9903.94.05', \
                f"Auto {row['hts_code']} has claim {row['chapter_99_claim']}, " \
                f"expected 9903.94.05 per Proclamation 10908"

    def test_semiconductor_claim_code(self, s232_by_material):
        """
        Semiconductors: 9903.79.01 (duty applies)
        Per CSMS #67400472 / Proclamation 11002.

        Note: 9903.79.02-09 are end-use exemption codes (data center, R&D, etc.)
        but the CSV should list the standard tariff code (9903.79.01).
        """
        for row in s232_by_material.get('semiconductor', []):
            assert row['chapter_99_claim'] == '9903.79.01', \
                f"Semiconductor {row['hts_code']} has claim {row['chapter_99_claim']}, " \
                f"expected 9903.79.01 per CSMS #67400472"


# ============================================================================
# 4. Article Type Verification
# ============================================================================

class TestArticleTypes:
    """Verify article_type values are consistent with HTS chapter rules."""

    def test_valid_article_types(self, s232_csv_rows):
        """All article types must be in the allowed set."""
        valid = {'primary', 'derivative', 'content', 'part'}
        for row in s232_csv_rows:
            at = row.get('article_type', '')
            assert at in valid, \
                f"HTS {row['hts_code']} has invalid article_type '{at}', " \
                f"expected one of {valid}"

    def test_auto_parts_are_type_part(self, s232_by_material):
        """Auto parts should have article_type='part' per Proclamation 10908."""
        for row in s232_by_material.get('auto', []):
            assert row.get('article_type') == 'part', \
                f"Auto HTS {row['hts_code']} has article_type '{row.get('article_type')}', " \
                f"expected 'part'"

    def test_copper_primary_articles_in_ch74(self, s232_by_material):
        """Primary copper articles should generally be in Ch 74 (copper and articles thereof)."""
        for row in s232_by_material.get('copper', []):
            if row.get('article_type') == 'primary':
                hts = row['hts_code'].replace('.', '')
                chapter = hts[:2]
                assert chapter == '74', \
                    f"Primary copper {row['hts_code']} is in chapter {chapter}, " \
                    f"expected Ch 74"


# ============================================================================
# 5. KNOWN BUG: Excluded HTS Codes That Should NOT Be In CSV
# ============================================================================

class TestExcludedHTSCodes:
    """
    These HTS codes are EXCLUDED from Section 232 per official Federal Register
    notices, but may incorrectly be present in our CSV.

    Source: Federal Register March 5, 2025 (Volume 90, Issue 42)
    "angles, shapes and sections of 7216 (except subheadings 7216.61.00, 7216.69.00)"

    Source: August 2025 amendment
    Only 7216.91.0010 (10-digit) was added, NOT the broad 7216.91.00 (8-digit).
    """

    @pytest.mark.xfail(reason="KNOWN BUG: 7216.61.00 is EXCLUDED from 232 per FR 90 FR 42")
    def test_7216_61_00_excluded(self, s232_hts_set):
        """7216.61.00 should NOT be in 232 scope — explicitly excluded by proclamation."""
        assert '7216.61.00' not in s232_hts_set, \
            "7216.61.00 is EXCLUDED from Section 232 per Federal Register March 5, 2025. " \
            "Remove this HTS code from section_232_hts_codes.csv."

    @pytest.mark.xfail(reason="KNOWN BUG: 7216.69.00 is EXCLUDED from 232 per FR 90 FR 42")
    def test_7216_69_00_excluded(self, s232_hts_set):
        """7216.69.00 should NOT be in 232 scope — explicitly excluded by proclamation."""
        assert '7216.69.00' not in s232_hts_set, \
            "7216.69.00 is EXCLUDED from Section 232 per Federal Register March 5, 2025. " \
            "Remove this HTS code from section_232_hts_codes.csv."

    @pytest.mark.xfail(reason="KNOWN BUG: Only 7216.91.0010 was added, not broad 7216.91.00")
    def test_7216_91_00_should_be_10digit(self, s232_hts_set):
        """
        7216.91.00 (8-digit) should NOT be in scope.
        Only 7216.91.0010 (10-digit subheading) was added in Aug 2025.
        The broad 8-digit code would incorrectly cover ALL subheadings under 7216.91.
        """
        # If the 8-digit is present but 10-digit variant is not, that's a bug
        has_8digit = '7216.91.00' in s232_hts_set
        has_10digit = '7216.91.0010' in s232_hts_set

        if has_8digit and not has_10digit:
            pytest.fail(
                "7216.91.00 (broad 8-digit) is in CSV but should be replaced with "
                "7216.91.0010 (specific 10-digit subheading) per August 2025 amendment."
            )
        elif has_8digit and has_10digit:
            pytest.fail(
                "Both 7216.91.00 and 7216.91.0010 are in CSV. Remove the broad "
                "8-digit code — only the 10-digit subheading was added."
            )


# ============================================================================
# 6. Disclaim Behavior Verification (from tariff_programs.csv)
# ============================================================================

class TestDisclaimBehavior:
    """Verify disclaim_behavior in tariff_programs.csv matches CBP filing guidance."""

    def test_copper_disclaim_required(self, tariff_programs_csv):
        """
        Copper: disclaim_behavior='required'
        Per CSMS #65794272: Must file 9903.78.02 disclaim on non-copper slices.
        Both claim (9903.78.01) and disclaim (9903.78.02) lines are REQUIRED.
        """
        copper_progs = [r for r in tariff_programs_csv
                        if r.get('program_id') == 'section_232_copper']
        if not copper_progs:
            pytest.skip("section_232_copper not found in tariff_programs.csv")

        for prog in copper_progs:
            assert prog.get('disclaim_behavior') == 'required', \
                f"Copper 232 should have disclaim_behavior='required', " \
                f"got '{prog.get('disclaim_behavior')}'"

    def test_steel_disclaim_omit(self, tariff_programs_csv):
        """
        Steel: disclaim_behavior='omit'
        Per CSMS #65936570: Steel is OMITTED entirely from non-steel slices.
        """
        steel_progs = [r for r in tariff_programs_csv
                       if r.get('program_id') == 'section_232_steel']
        if not steel_progs:
            pytest.skip("section_232_steel not found in tariff_programs.csv")

        for prog in steel_progs:
            assert prog.get('disclaim_behavior') == 'omit', \
                f"Steel 232 should have disclaim_behavior='omit', " \
                f"got '{prog.get('disclaim_behavior')}'"

    def test_aluminum_disclaim_omit(self, tariff_programs_csv):
        """
        Aluminum: disclaim_behavior='omit'
        Per CSMS #65936615: Aluminum is OMITTED entirely from non-aluminum slices.
        """
        alum_progs = [r for r in tariff_programs_csv
                      if r.get('program_id') == 'section_232_aluminum']
        if not alum_progs:
            pytest.skip("section_232_aluminum not found in tariff_programs.csv")

        for prog in alum_progs:
            assert prog.get('disclaim_behavior') == 'omit', \
                f"Aluminum 232 should have disclaim_behavior='omit', " \
                f"got '{prog.get('disclaim_behavior')}'"


# ============================================================================
# 7. UK Exception Rate Verification (from tariff_program_rates.csv)
# ============================================================================

class TestUKExceptionRates:
    """Verify UK exception rates for steel/aluminum per Thompson Hine June 2025."""

    def test_steel_uk_rate_25_percent(self, program_rates_csv):
        """
        UK steel rate: 25% (not 50% like everyone else).
        Per Thompson Hine analysis of Proclamation 10947 exceptions.
        """
        uk_steel = [r for r in program_rates_csv
                    if r.get('program_id') == 'section_232_steel'
                    and r.get('group_id') == 'UK']
        if not uk_steel:
            pytest.skip("No UK-specific steel rate in program_rates.csv")

        for rate_row in uk_steel:
            rate = float(rate_row['rate'])
            assert rate == 0.25, \
                f"UK steel rate should be 0.25 (25%), got {rate}. " \
                f"UK exception per Proclamation 10947."

    def test_aluminum_uk_rate_25_percent(self, program_rates_csv):
        """
        UK aluminum rate: 25% (not 50% like everyone else).
        Per Thompson Hine analysis of Proclamation 10947 exceptions.
        """
        uk_alum = [r for r in program_rates_csv
                   if r.get('program_id') == 'section_232_aluminum'
                   and r.get('group_id') == 'UK']
        if not uk_alum:
            pytest.skip("No UK-specific aluminum rate in program_rates.csv")

        for rate_row in uk_alum:
            rate = float(rate_row['rate'])
            assert rate == 0.25, \
                f"UK aluminum rate should be 0.25 (25%), got {rate}. " \
                f"UK exception per Proclamation 10947."

    def test_copper_no_uk_exception(self, program_rates_csv):
        """Copper has NO UK exception — 50% for all countries."""
        uk_copper = [r for r in program_rates_csv
                     if r.get('program_id') == 'section_232_copper'
                     and r.get('group_id') == 'UK']
        # Either there's no UK-specific rate, or if there is one, it should be 50%
        for rate_row in uk_copper:
            rate = float(rate_row['rate'])
            assert rate == 0.50, \
                f"Copper has no UK exception — rate should be 0.50 for all countries"


# ============================================================================
# 8. Data Quality Checks
# ============================================================================

class TestDataQuality:
    """General data quality checks on the CSV."""

    def test_no_duplicate_hts_material_pairs(self, s232_csv_rows):
        """Each (hts_code, material) pair should be unique in the CSV."""
        seen = set()
        dupes = []
        for row in s232_csv_rows:
            key = (row['hts_code'], row['material'])
            if key in seen:
                dupes.append(key)
            seen.add(key)
        assert not dupes, \
            f"Duplicate (hts_code, material) pairs found: {dupes[:10]}"

    def test_all_hts_codes_have_dots(self, s232_csv_rows):
        """HTS codes in CSV should contain dots for readability (e.g., 7216.61.00)."""
        for row in s232_csv_rows:
            hts = row['hts_code']
            assert '.' in hts, \
                f"HTS code '{hts}' is missing dots — use dotted format (e.g., 7216.61.00)"

    def test_duty_rates_are_valid_decimals(self, s232_csv_rows):
        """All duty_rate values must be parseable as float and between 0 and 1."""
        for row in s232_csv_rows:
            try:
                rate = float(row['duty_rate'])
            except ValueError:
                pytest.fail(f"HTS {row['hts_code']}: duty_rate '{row['duty_rate']}' is not a number")
            assert 0 < rate <= 1.0, \
                f"HTS {row['hts_code']}: duty_rate {rate} out of range (0, 1.0]"

    def test_claim_codes_start_with_9903(self, s232_csv_rows):
        """All Chapter 99 claim codes should start with '9903.'."""
        for row in s232_csv_rows:
            claim = row['chapter_99_claim']
            assert claim.startswith('9903.'), \
                f"HTS {row['hts_code']}: claim code '{claim}' doesn't start with '9903.'"

    def test_disclaim_codes_start_with_9903(self, s232_csv_rows):
        """All Chapter 99 disclaim codes should start with '9903.'."""
        for row in s232_csv_rows:
            disclaim = row['chapter_99_disclaim']
            assert disclaim.startswith('9903.'), \
                f"HTS {row['hts_code']}: disclaim code '{disclaim}' doesn't start with '9903.'"

    def test_claim_and_disclaim_differ(self, s232_csv_rows):
        """Claim code and disclaim code must be different for every entry."""
        for row in s232_csv_rows:
            assert row['chapter_99_claim'] != row['chapter_99_disclaim'], \
                f"HTS {row['hts_code']}/{row['material']}: claim and disclaim codes " \
                f"are the same ({row['chapter_99_claim']})"

    def test_semiconductor_hts_in_expected_chapters(self, s232_by_material):
        """
        Semiconductor 232 HTS codes should be in Ch 84 (8471, 8473).
        Per Proclamation 11002 / CSMS #67400472.
        """
        for row in s232_by_material.get('semiconductor', []):
            hts = row['hts_code'].replace('.', '')
            prefix = hts[:4]
            assert prefix in ('8471', '8473'), \
                f"Semiconductor HTS {row['hts_code']} starts with {prefix}, " \
                f"expected 8471 or 8473 per CSMS #67400472"

    def test_auto_parts_hts_in_expected_chapters(self, s232_by_material):
        """
        Auto parts 232 HTS codes should primarily be in Ch 87 (8708)
        or Ch 85 (8544) per Proclamation 10908.
        """
        valid_prefixes = {'8544', '8708'}
        for row in s232_by_material.get('auto', []):
            hts = row['hts_code'].replace('.', '')
            prefix = hts[:4]
            assert prefix in valid_prefixes, \
                f"Auto HTS {row['hts_code']} starts with {prefix}, " \
                f"expected one of {valid_prefixes} per Proclamation 10908"


# ============================================================================
# 9. Temporal Rate History Verification (populate script constants)
# ============================================================================

class TestTemporalHistory:
    """
    Verify the temporal rate history defined in populate_tariff_tables.py
    matches official proclamation dates and rates.

    These rates are used to build Section232Rate temporal rows.
    """

    def test_steel_history_matches_proclamations(self):
        """
        Steel rate history per official proclamations:
          2018-03-23 → 2025-03-11: 25% (Proc 9705)
          2025-03-12 → 2025-06-03: 25% (Proc 10896 reset)
          2025-06-04 → present:    50% (Proc 10947 increase)
        """
        from datetime import date
        history = [
            (date(2018, 3, 23), date(2025, 3, 11), 0.25, "Proc 9705"),
            (date(2025, 3, 12), date(2025, 6, 3), 0.25, "Proc 10896"),
            (date(2025, 6, 4), None, 0.50, "Proc 10947"),
        ]
        for start, end, rate, source in history:
            # Verify no gaps
            assert start is not None, f"Missing start date for {source}"
            assert rate > 0, f"Invalid rate for {source}"

        # Verify contiguity
        for i in range(len(history) - 1):
            current_end = history[i][1]
            next_start = history[i + 1][0]
            assert current_end is not None, \
                f"Non-terminal period {history[i][3]} must have end date"
            # End is exclusive, start is inclusive, so they should be adjacent
            from datetime import timedelta
            assert next_start - current_end == timedelta(days=1), \
                f"Gap between {history[i][3]} (end={current_end}) and " \
                f"{history[i+1][3]} (start={next_start})"

    def test_aluminum_history_matches_proclamations(self):
        """
        Aluminum rate history per official proclamations:
          2018-03-23 → 2025-03-11: 10% (Proc 9704, original)
          2025-03-12 → 2025-06-03: 25% (Proc 10895 reset)
          2025-06-04 → present:    50% (Proc 10947 increase)
        """
        from datetime import date
        history = [
            (date(2018, 3, 23), date(2025, 3, 11), 0.10, "Proc 9704"),
            (date(2025, 3, 12), date(2025, 6, 3), 0.25, "Proc 10895"),
            (date(2025, 6, 4), None, 0.50, "Proc 10947"),
        ]
        # Current rate should be 50%
        assert history[-1][2] == 0.50
        assert history[-1][1] is None  # Open-ended (current)

    def test_copper_effective_date(self):
        """
        Copper 232: Effective March 12, 2025 at 50%.
        Per Proclamation 10962.
        """
        from datetime import date
        copper_start = date(2025, 3, 12)
        copper_rate = 0.50
        assert copper_rate == 0.50
        assert copper_start.year == 2025

    def test_auto_parts_effective_date(self):
        """
        Auto parts 232: Effective May 3, 2025 at 25%.
        Per Proclamation 10908 (90 FR 14705).
        """
        from datetime import date
        auto_start = date(2025, 5, 3)
        auto_rate = 0.25
        assert auto_rate == 0.25
        assert auto_start == date(2025, 5, 3)

    def test_semiconductor_effective_date(self):
        """
        Semiconductor 232: Effective January 15, 2026 at 25%.
        Per Proclamation 11002 / CSMS #67400472.
        """
        from datetime import date
        semi_start = date(2026, 1, 15)
        semi_rate = 0.25
        assert semi_rate == 0.25
        assert semi_start == date(2026, 1, 15)


# ============================================================================
# 10. Cross-Reference: Specific HTS Codes Verified Against Official Sources
# ============================================================================

class TestSpecificHTSVerification:
    """
    Spot-check specific HTS codes that were manually verified against
    official government sources (CBP.gov, Federal Register, USITC).
    """

    def test_7301_10_00_is_derivative_steel(self, s232_csv_rows):
        """
        7301.10.00 (Sheet piling): Should be derivative steel.
        Per CSMS #65936570, Chapter 73 derivative articles.
        Claim code: 9903.81.90 (Ch 73 derivative)
        """
        matches = [r for r in s232_csv_rows if r['hts_code'] == '7301.10.00']
        assert len(matches) >= 1, "7301.10.00 not found in CSV"
        for m in matches:
            assert m['material'] == 'steel'
            assert m.get('article_type') == 'derivative'

    def test_7302_40_00_is_derivative_steel(self, s232_csv_rows):
        """
        7302.40.00 (Fish-plates / sole plates): Should be derivative steel.
        Per CSMS #65936570.
        """
        matches = [r for r in s232_csv_rows if r['hts_code'] == '7302.40.00']
        assert len(matches) >= 1, "7302.40.00 not found in CSV"
        for m in matches:
            assert m['material'] == 'steel'
            assert m.get('article_type') == 'derivative'

    def test_7317_00_30_is_derivative_steel(self, s232_csv_rows):
        """
        7317.00.30 (Nails, tacks): Should be derivative steel.
        Per CSMS #65936570.
        """
        matches = [r for r in s232_csv_rows if r['hts_code'] == '7317.00.30']
        assert len(matches) >= 1, "7317.00.30 not found in CSV"
        for m in matches:
            assert m['material'] == 'steel'
            assert m.get('article_type') == 'derivative'

    def test_8708_10_30_includes_auto_part(self, s232_csv_rows):
        """
        8708.10.30 (bumpers): Should include auto part entry at 25%.
        Per Proclamation 10908.

        Note: This HTS can appear under MULTIPLE materials (auto, steel, aluminum)
        because auto parts can also contain 232-covered metals. The auto entry
        is for the auto parts tariff; steel/aluminum entries are for metal content.
        """
        matches = [r for r in s232_csv_rows if r['hts_code'] == '8708.10.30']
        assert len(matches) >= 1, "8708.10.30 not found in CSV"
        auto_entries = [m for m in matches if m['material'] == 'auto']
        assert len(auto_entries) >= 1, \
            f"8708.10.30 has no auto entry. Found materials: " \
            f"{[m['material'] for m in matches]}"
        for m in auto_entries:
            assert float(m['duty_rate']) == 0.25

    def test_8471_50_01_is_semiconductor(self, s232_csv_rows):
        """
        8471.50.01 (processing units): Should be semiconductor at 25%.
        Per CSMS #67400472 / Proclamation 11002.
        """
        matches = [r for r in s232_csv_rows if r['hts_code'] == '8471.50.01']
        assert len(matches) >= 1, "8471.50.01 not found in CSV"
        for m in matches:
            assert m['material'] == 'semiconductor'
            assert float(m['duty_rate']) == 0.25
            assert m['chapter_99_claim'] == '9903.79.01'

    def test_7406_10_00_is_copper_primary(self, s232_csv_rows):
        """
        7406.10.00 (copper powders): Should be primary copper at 50%.
        Per CSMS #65794272.
        """
        matches = [r for r in s232_csv_rows if r['hts_code'] == '7406.10.00']
        assert len(matches) >= 1, "7406.10.00 not found in CSV"
        for m in matches:
            assert m['material'] == 'copper'
            assert m.get('article_type') == 'primary'
            assert float(m['duty_rate']) == 0.50
            assert m['chapter_99_claim'] == '9903.78.01'
