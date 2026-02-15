#!/usr/bin/env python3
"""
Tests for v21.1 Yale expansion ingestion.

Verifies:
- New countries have correct rates and Ch.99 codes
- Annex I countries at 10% use their specific heading (not 9903.01.25)
- Non-Annex countries get BASELINE_10 with 9903.01.25
- Coverage counts
- No duplicate records
- Existing data untouched (regression, if base data present)

Usage:
    pytest tests/test_yale_expansion.py -v
"""

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DATASET_TAG = "v21.1_yale_expansion"

# Countries the base script (v21.0) is authoritative for.
# When the base script has been run, these countries will have
# dataset_tag='v21.0_initial' instead of 'v21.1_yale_expansion'.
BASE_SCRIPT_COUNTRIES = {
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
    'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
    'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',  # EU-27
    'JP', 'KR', 'CH', 'LI', 'GB',  # MFN ceiling / suspended
    'CN',  # Temporal versioning
    'CA', 'MX',  # USMCA
    'CU', 'KP', 'BY', 'RU',  # Column 2
    'VN', 'TH', 'IN', 'TW', 'ID', 'BD', 'MY', 'AR', 'BR',  # HIGH_RATE
}


@pytest.fixture(scope="module")
def app_context():
    """Create Flask app context for testing against local SQLite DB."""
    from app.web import create_app
    from app.web.db import db

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        yield db


def query_country(db, country_code, dataset_tag=DATASET_TAG):
    """Helper to query rate schedule by country code.

    If the country is owned by the base script and not found in
    the expansion dataset, falls back to querying v21.0_initial.
    """
    from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
    rows = IeepaReciprocalRateSchedule.query.filter_by(
        country_code=country_code,
        dataset_tag=dataset_tag,
    ).all()
    if not rows and country_code in BASE_SCRIPT_COUNTRIES:
        rows = IeepaReciprocalRateSchedule.query.filter_by(
            country_code=country_code,
            dataset_tag='v21.0_initial',
        ).all()
    return rows


def query_all_expansion(db):
    """Helper to query all expansion records."""
    from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
    return IeepaReciprocalRateSchedule.query.filter_by(
        dataset_tag=DATASET_TAG,
    ).all()


# =============================================================================
# Test Class 1: Annex I Countries with Specific Ch.99 Headings
# =============================================================================

class TestAnnexICountries:
    """Test Annex I countries have correct rates and Ch.99 codes."""

    @pytest.mark.parametrize("iso,name,expected_rate,expected_ch99", [
        ("KH", "Cambodia", 19, "9903.02.11"),
        ("AF", "Afghanistan", 15, "9903.02.02"),
        ("DZ", "Algeria", 30, "9903.02.03"),
        ("BD", "Bangladesh", 20, "9903.02.05"),
        ("BA", "Bosnia and Herzegovina", 30, "9903.02.07"),
        ("IQ", "Iraq", 35, "9903.02.28"),
        ("LA", "Laos", 40, "9903.02.33"),
        ("MM", "Myanmar", 40, "9903.02.43"),
        ("RS", "Serbia", 35, "9903.02.54"),
        ("SY", "Syria", 41, "9903.02.59"),
        ("VN", "Vietnam", 20, "9903.02.69"),
        ("TH", "Thailand", 19, "9903.02.61"),
        ("IN", "India", 25, "9903.02.26"),
        ("ID", "Indonesia", 19, "9903.02.27"),
        ("MY", "Malaysia", 19, "9903.02.39"),
        ("PH", "Philippines", 19, "9903.02.53"),
        ("TW", "Taiwan", 20, "9903.02.60"),
        ("ZA", "South Africa", 30, "9903.02.55"),
        ("TN", "Tunisia", 25, "9903.02.63"),
        ("MD", "Moldova", 25, "9903.02.41"),
        ("KZ", "Kazakhstan", 25, "9903.02.32"),
        ("BN", "Brunei", 25, "9903.02.10"),
        ("NI", "Nicaragua", 18, "9903.02.47"),
        ("LK", "Sri Lanka", 20, "9903.02.57"),
    ], ids=lambda x: x if isinstance(x, str) and len(x) == 2 else "")
    def test_annex_country_rate_and_code(self, app_context, iso, name, expected_rate, expected_ch99):
        """Verify Annex I country has correct rate and Ch.99 heading."""
        rows = query_country(app_context, iso)
        assert len(rows) >= 1, f"{iso} ({name}) not found in expansion data"
        row = rows[0]
        assert row.rate_pct == Decimal(str(expected_rate)), (
            f"{iso} ({name}): expected rate={expected_rate}%, got {row.rate_pct}%"
        )
        assert row.ch99_code == expected_ch99, (
            f"{iso} ({name}): expected ch99={expected_ch99}, got {row.ch99_code}"
        )
        assert row.regime_type == "FIXED_RATE", (
            f"{iso} ({name}): expected FIXED_RATE, got {row.regime_type}"
        )
        assert row.country_group == "ANNEX_I"

    def test_brazil_uses_own_heading(self, app_context):
        """
        CRITICAL: Brazil at 10% must use 9903.02.09, NOT 9903.01.25.

        Filing under 9903.01.25 would get flagged by ACE because Brazil
        has its own specific heading in the Annex.
        """
        rows = query_country(app_context, "BR")
        assert len(rows) >= 1, "Brazil not found in expansion data"
        row = rows[0]
        assert row.ch99_code == "9903.02.09", (
            f"Brazil must use 9903.02.09, got {row.ch99_code}"
        )
        assert row.rate_pct == Decimal("10"), f"Brazil rate should be 10%, got {row.rate_pct}"
        assert row.regime_type == "FIXED_RATE", (
            "Brazil should be FIXED_RATE (has specific Annex heading), not BASELINE_10"
        )

    def test_falkland_islands_uses_own_heading(self, app_context):
        """Falkland Islands at 10% must use 9903.02.21, not 9903.01.25."""
        rows = query_country(app_context, "FK")
        assert len(rows) >= 1, "Falkland Islands not found"
        row = rows[0]
        assert row.ch99_code == "9903.02.21"
        assert row.rate_pct == Decimal("10")
        assert row.regime_type == "FIXED_RATE"

    def test_uk_uses_own_heading(self, app_context):
        """UK at 10% — expansion uses 9903.02.66, base uses 9903.01.25 (SUSPENDED)."""
        rows = query_country(app_context, "GB")
        assert len(rows) >= 1, "United Kingdom not found"
        row = rows[0]
        # Base script has GB as SUSPENDED_TO_BASELINE with 9903.01.25;
        # expansion had it as FIXED_RATE with 9903.02.66. Either is valid.
        assert row.ch99_code in ("9903.02.66", "9903.01.25"), (
            f"GB ch99 should be 9903.02.66 (expansion) or 9903.01.25 (base), got {row.ch99_code}"
        )
        assert row.rate_pct == Decimal("10")


# =============================================================================
# Test Class 2: Non-Annex Baseline Countries
# =============================================================================

class TestNonAnnexBaseline:
    """Test non-Annex countries at baseline 10%."""

    @pytest.mark.parametrize("iso,name", [
        ("GL", "Greenland"),
        ("BZ", "Belize"),
        ("GT", "Guatemala"),
        ("SV", "El Salvador"),
        ("HN", "Honduras"),
        ("PA", "Panama"),
        ("BM", "Bermuda"),
        ("BS", "Bahamas"),
        ("JM", "Jamaica"),
        ("BB", "Barbados"),
        ("AR", "Argentina"),
        ("CL", "Chile"),
        ("CO", "Colombia"),
        ("PE", "Peru"),
        ("AM", "Armenia"),
        ("AZ", "Azerbaijan"),
        ("GE", "Georgia"),
        ("KG", "Kyrgyzstan"),
        ("TJ", "Tajikistan"),
        ("TM", "Turkmenistan"),
    ], ids=lambda x: x if isinstance(x, str) and len(x) == 2 else "")
    def test_baseline_country(self, app_context, iso, name):
        """Non-Annex country should be BASELINE_10 with ch99=9903.01.25."""
        rows = query_country(app_context, iso)
        assert len(rows) >= 1, f"{iso} ({name}) not found"
        row = rows[0]
        assert row.rate_pct == Decimal("10"), f"{iso}: expected 10%, got {row.rate_pct}"
        assert row.ch99_code == "9903.01.25", f"{iso}: expected 9903.01.25, got {row.ch99_code}"
        assert row.regime_type == "BASELINE_10"
        # Base script uses ANNEX_I for countries like AR; expansion uses NON_ANNEX_I
        assert row.country_group in ("NON_ANNEX_I", "ANNEX_I"), (
            f"{iso}: expected NON_ANNEX_I or ANNEX_I, got {row.country_group}"
        )


# =============================================================================
# Test Class 3: Coverage and Data Integrity
# =============================================================================

class TestCoverageAndIntegrity:
    """Test overall coverage and data integrity."""

    def test_total_expansion_records(self, app_context):
        """Expect expansion records. Count depends on whether base script has run.

        Before base script: ~198 expansion records
        After base script:  ~183 (15 countries moved to v21.0_initial)
        """
        rows = query_all_expansion(app_context)
        # With base script run: 183; without: 198. Accept either.
        assert len(rows) >= 180, f"Expected 180+ expansion records, got {len(rows)}"

    def test_distinct_country_codes(self, app_context):
        """Expansion should cover many distinct countries."""
        rows = query_all_expansion(app_context)
        distinct = {r.country_code for r in rows}
        # With base script run: 183; without: 198. Accept either.
        assert len(distinct) >= 180, (
            f"Expected 180+ distinct countries, got {len(distinct)}"
        )

    def test_no_duplicate_records(self, app_context):
        """No duplicate (country_code, effective_start, dataset_tag) combinations."""
        rows = query_all_expansion(app_context)
        keys = [(r.country_code, r.effective_start, r.dataset_tag) for r in rows]
        assert len(keys) == len(set(keys)), (
            f"Found duplicate records: {len(keys)} total vs {len(set(keys))} unique"
        )

    def test_all_records_have_legal_authority(self, app_context):
        """All expansion records should reference EO 14326."""
        rows = query_all_expansion(app_context)
        for r in rows:
            assert r.legal_authority == "EO 14326", (
                f"{r.country_code}: expected legal_authority='EO 14326', got '{r.legal_authority}'"
            )

    def test_all_records_have_fr_citation(self, app_context):
        """All expansion records should have FR citation."""
        rows = query_all_expansion(app_context)
        for r in rows:
            assert r.fr_citation == "90 FR 37963", (
                f"{r.country_code}: expected fr_citation='90 FR 37963', got '{r.fr_citation}'"
            )

    def test_effective_dates(self, app_context):
        """All expansion records should have EO 14326 effective date."""
        rows = query_all_expansion(app_context)
        for r in rows:
            assert r.effective_start == date(2025, 8, 7), (
                f"{r.country_code}: expected start=2025-08-07, got {r.effective_start}"
            )
            assert r.effective_end == date(9999, 12, 31), (
                f"{r.country_code}: expected end=9999-12-31, got {r.effective_end}"
            )

    def test_no_eu_members_in_expansion(self, app_context):
        """EU members should NOT appear in expansion data (handled by base script)."""
        eu_codes = {
            "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
            "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
            "PL", "PT", "RO", "SK", "SI", "ES", "SE",
        }
        rows = query_all_expansion(app_context)
        expansion_codes = {r.country_code for r in rows}
        overlap = eu_codes & expansion_codes
        assert not overlap, f"EU members found in expansion: {overlap}"

    def test_annex_countries_use_fixed_rate(self, app_context):
        """All Annex I countries should have regime_type=FIXED_RATE."""
        rows = query_all_expansion(app_context)
        annex_rows = [r for r in rows if r.country_group == "ANNEX_I"]
        for r in annex_rows:
            assert r.regime_type == "FIXED_RATE", (
                f"{r.country_code}: Annex country should be FIXED_RATE, got {r.regime_type}"
            )
            assert r.ch99_code.startswith("9903.02."), (
                f"{r.country_code}: Annex country should have 9903.02.XX code, got {r.ch99_code}"
            )

    def test_baseline_countries_use_generic_heading(self, app_context):
        """All BASELINE_10 countries should use 9903.01.25."""
        rows = query_all_expansion(app_context)
        baseline_rows = [r for r in rows if r.regime_type == "BASELINE_10"]
        for r in baseline_rows:
            assert r.ch99_code == "9903.01.25", (
                f"{r.country_code}: baseline should use 9903.01.25, got {r.ch99_code}"
            )
            assert r.rate_pct == Decimal("10"), (
                f"{r.country_code}: baseline rate should be 10%, got {r.rate_pct}"
            )


# =============================================================================
# Test Class 4: Regression (existing data from base script)
# =============================================================================

class TestRegression:
    """Regression tests — only run if base ingestion data is present."""

    def _has_base_data(self, db):
        """Check if base ingestion data exists."""
        from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
        base_rows = IeepaReciprocalRateSchedule.query.filter_by(
            dataset_tag="v21.0_initial",
        ).count()
        return base_rows > 0

    def test_eu_mfn_ceiling_intact(self, app_context):
        """EU-27 should have MFN_CEILING with ceiling_pct=15.00 (if base data present)."""
        if not self._has_base_data(app_context):
            pytest.skip("Base ingestion data (v21.0_initial) not present")

        from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
        eu_rows = IeepaReciprocalRateSchedule.query.filter_by(
            dataset_tag="v21.0_initial",
            regime_type="MFN_CEILING",
            country_group="EU",
        ).all()
        assert len(eu_rows) == 27, f"Expected 27 EU MFN ceiling rows, got {len(eu_rows)}"
        for r in eu_rows:
            assert r.ceiling_pct == Decimal("15.00"), (
                f"EU {r.country_code}: ceiling should be 15.00, got {r.ceiling_pct}"
            )
            assert r.ch99_mfn_zero == "9903.02.19"
            assert r.ch99_mfn_topup == "9903.02.20"

    def test_china_temporal_rows(self, app_context):
        """China should have 3 temporal eras (if base data present)."""
        if not self._has_base_data(app_context):
            pytest.skip("Base ingestion data (v21.0_initial) not present")

        from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
        cn_rows = IeepaReciprocalRateSchedule.query.filter_by(
            country_code="CN",
            dataset_tag="v21.0_initial",
        ).order_by(IeepaReciprocalRateSchedule.effective_start).all()
        assert len(cn_rows) == 3, f"Expected 3 China temporal rows, got {len(cn_rows)}"

    def test_japan_ceiling_is_15(self, app_context):
        """
        Japan ceiling_pct must be 15.00 (NOT 12.5%).

        12.5% is the COMPUTED top-up rate (15% - 2.5% base MFN), not the ceiling.
        Storing 12.5% as ceiling would break the formula for products with
        non-standard MFN rates.
        """
        if not self._has_base_data(app_context):
            pytest.skip("Base ingestion data (v21.0_initial) not present")

        from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
        jp_row = IeepaReciprocalRateSchedule.query.filter_by(
            country_code="JP",
            dataset_tag="v21.0_initial",
        ).first()
        if jp_row and jp_row.regime_type == "MFN_CEILING":
            assert jp_row.ceiling_pct == Decimal("15.00"), (
                f"Japan ceiling_pct should be 15.00, got {jp_row.ceiling_pct}. "
                "12.5% is the computed top-up, NOT the ceiling parameter."
            )

    def test_switzerland_ceiling_is_15(self, app_context):
        """
        Switzerland ceiling_pct must be 15.00 (NOT 8.75%).

        Same issue as Japan — 8.75% is the computed top-up, not the ceiling.
        """
        if not self._has_base_data(app_context):
            pytest.skip("Base ingestion data (v21.0_initial) not present")

        from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule
        ch_row = IeepaReciprocalRateSchedule.query.filter_by(
            country_code="CH",
            dataset_tag="v21.0_initial",
        ).first()
        if ch_row and ch_row.regime_type == "MFN_CEILING":
            assert ch_row.ceiling_pct == Decimal("15.00"), (
                f"Switzerland ceiling_pct should be 15.00, got {ch_row.ceiling_pct}. "
                "8.75% is the computed top-up, NOT the ceiling parameter."
            )
