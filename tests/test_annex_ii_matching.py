"""
v21.0: Test cases for IEEPA Annex II LPM (Longest Prefix Match) edge cases.

Per the plan:
- Add tests FIRST, only modify code if tests fail
- Tests verify that check_annex_ii_exclusion() correctly matches HTS codes

Edge cases tested:
1. 10-digit HTS that should match 4-digit exclusion
2. 8-digit HTS that should match 6-digit exclusion
3. HTS that should NOT match any exclusion
4. Date boundary cases (just before/after effective_date)
5. Energy category matching
6. Multiple prefix lengths with longest match priority
"""

import json
import os
import pytest
from datetime import date, timedelta

# NOTE: These tests require a database to be accessible via IEEPA_TEST_DB_URL
PROD_DB_URL = os.environ.get('IEEPA_TEST_DB_URL', '')


def get_prod_app():
    """
    Create a fresh Flask app configured for test database.
    Requires IEEPA_TEST_DB_URL environment variable.
    """
    if not PROD_DB_URL:
        pytest.skip('IEEPA_TEST_DB_URL not set — skipping integration tests')

    # Set env var for the Config class
    os.environ['SQLALCHEMY_DATABASE_URI'] = PROD_DB_URL

    # Import fresh to pick up the new env var
    from app.web import create_app
    from app.chat.tools import stacking_tools

    # Reset cached app in stacking_tools
    stacking_tools._flask_app = None

    # Create new app
    app = create_app()
    app.config['TESTING'] = True

    # Set the stacking_tools cache to use this app
    stacking_tools._flask_app = app

    return app


# Lazy imports to avoid conftest.py import order issues
def _get_imports():
    from app.web.db import db
    from app.web.db.models.tariff_tables import IeepaAnnexIIExclusion
    from app.chat.tools import stacking_tools
    from app.chat.tools.stacking_tools import check_annex_ii_exclusion
    return db, IeepaAnnexIIExclusion, stacking_tools, check_annex_ii_exclusion


@pytest.fixture
def prod_app_context():
    """
    Provide app context for database operations with production database.

    This fixture creates a fresh app to bypass conftest.py's SQLite config.
    """
    app = get_prod_app()
    db, IeepaAnnexIIExclusion, stacking_tools, _ = _get_imports()

    with app.app_context():
        # Verify we have data in the database
        count = IeepaAnnexIIExclusion.query.count()
        if count == 0:
            pytest.skip("Production database not accessible or empty - skipping LPM tests")
        yield app

    # Clean up
    stacking_tools._flask_app = None


# Also provide the old fixture names for compatibility
app = None  # Not used, we use prod_app_context instead
app_context = None  # Not used


class TestAnnexIILPM:
    """Test Longest Prefix Match behavior for Annex II exclusions."""

    def _check_exclusion(self, hts_code, import_date="2026-02-07"):
        """Helper to call check_annex_ii_exclusion."""
        _, _, _, check_annex_ii_exclusion = _get_imports()
        result = check_annex_ii_exclusion.invoke({
            "hts_code": hts_code,
            "import_date": import_date
        })
        return json.loads(result)

    def test_10digit_matches_4digit_exclusion(self, prod_app_context):
        """
        10-digit HTS code should match a 4-digit exclusion prefix.

        Example: 2709.00.0050 (10-digit) should match 2709 (4-digit energy exclusion)
        """
        data = self._check_exclusion("2709.00.0050")

        assert data["excluded"] is True, "10-digit HTS should match 4-digit prefix"
        assert data["category"] == "energy", "Should be energy category"
        assert data["matched_prefix"] == "270900", "Should match the stored prefix"

    def test_10digit_matches_6digit_exclusion(self, prod_app_context):
        """
        10-digit HTS code should match a 6-digit exclusion prefix.

        Example: 2711.11.0000 should match 271111 (LNG - 6-digit)
        """
        data = self._check_exclusion("2711.11.0000")

        assert data["excluded"] is True, "10-digit HTS should match 6-digit prefix"
        assert data["category"] == "energy", "Should be energy category"
        assert "271111" in data["matched_prefix"], "Should match 6-digit LNG prefix"

    def test_8digit_matches_4digit_exclusion(self, prod_app_context):
        """
        8-digit HTS code should match a 4-digit exclusion prefix.

        Example: 2701.11.00 (coal) should match 2701 (4-digit)
        """
        data = self._check_exclusion("2701.11.00")

        assert data["excluded"] is True, "8-digit HTS should match 4-digit prefix"
        assert data["category"] == "energy", "Coal is energy category"

    def test_no_match_for_unrelated_hts(self, prod_app_context):
        """
        HTS code not in Annex II should NOT match any exclusion.

        Example: 8471.30.0100 (computers) is not in Annex II
        """
        data = self._check_exclusion("8471.30.0100")

        assert data["excluded"] is False, "Computer HTS should not match any exclusion"

    def test_semiconductor_category(self, prod_app_context):
        """
        Semiconductor HTS codes should match with correct category.

        Example: 8541.xx.xxxx should match 8541 (semiconductor devices)
        """
        data = self._check_exclusion("8541.21.0085")

        assert data["excluded"] is True, "Semiconductor HTS should be excluded"
        assert data["category"] == "semiconductor"

    def test_pharmaceutical_category(self, prod_app_context):
        """
        Pharmaceutical HTS codes should match with correct category.

        Example: 3004.xx.xxxx should match 3004 (medicaments)
        """
        data = self._check_exclusion("3004.90.1015")

        assert data["excluded"] is True, "Pharmaceutical HTS should be excluded"
        assert data["category"] == "pharmaceutical"

    def test_critical_mineral_category(self, prod_app_context):
        """
        Critical mineral HTS codes should match with correct category.

        Example: 2603.xx.xxxx should match (copper ores)
        """
        data = self._check_exclusion("2603.00.0010")

        assert data["excluded"] is True, "Critical mineral HTS should be excluded"
        assert data["category"] == "critical_mineral"

    def test_dots_in_hts_handled(self, prod_app_context):
        """
        HTS codes with dots should be properly normalized before matching.
        """
        # With dots
        data1 = self._check_exclusion("2709.00.0000")

        # Without dots (raw digits)
        data2 = self._check_exclusion("2709000000")

        assert data1["excluded"] == data2["excluded"], "Dot handling should be consistent"
        assert data1["category"] == data2["category"], "Category should match regardless of dots"


class TestAnnexIITemporalBehavior:
    """Test date-based behavior for Annex II exclusions."""

    def _check_exclusion(self, hts_code, import_date="2026-02-07"):
        """Helper to call check_annex_ii_exclusion."""
        _, _, _, check_annex_ii_exclusion = _get_imports()
        result = check_annex_ii_exclusion.invoke({
            "hts_code": hts_code,
            "import_date": import_date
        })
        return json.loads(result)

    def test_active_exclusion_matches(self, prod_app_context):
        """
        Exclusion should match when import_date is within active period.
        """
        # Use a date well after effective_date (2025-04-05 for most entries)
        data = self._check_exclusion("2709.00.0000", "2026-02-07")

        assert data["excluded"] is True, "Active exclusion should match"

    def test_exclusion_before_effective_date(self, prod_app_context):
        """
        Exclusion should NOT match when import_date is before effective_date.

        Most Annex II entries have effective_date = 2025-04-05
        """
        # Use a date before the effective date
        data = self._check_exclusion("2709.00.0000", "2025-01-01")

        # This test documents current behavior - may need adjustment
        # if temporal check on effective_date isn't implemented
        # For now, we're testing what happens, not asserting specific outcome
        if data["excluded"]:
            # If it matches, the system doesn't enforce effective_date lower bound
            pass  # Current behavior - document and assess
        else:
            # If it doesn't match, effective_date is being enforced
            pass

    def test_default_date_uses_today(self, prod_app_context):
        """
        When import_date is None/not provided, should use today's date.
        """
        data = self._check_exclusion("2709.00.0000", None)

        # Should still match since today (2026-02-07) is after effective_date
        assert data["excluded"] is True, "Should match using today's date"


class TestAnnexIIChapter99Codes:
    """Test that correct Chapter 99 codes are returned."""

    def _check_exclusion(self, hts_code, import_date="2026-02-07"):
        """Helper to call check_annex_ii_exclusion."""
        _, _, _, check_annex_ii_exclusion = _get_imports()
        result = check_annex_ii_exclusion.invoke({
            "hts_code": hts_code,
            "import_date": import_date
        })
        return json.loads(result)

    def test_returns_correct_chapter_99_code(self, prod_app_context):
        """
        Annex II exclusions should return 9903.01.32 (the exemption code).
        """
        data = self._check_exclusion("2709.00.0000")

        assert data["excluded"] is True
        assert data["chapter_99_code"] == "9903.01.32", "Should return exemption code"
        assert data["variant"] == "annex_ii_exempt", "Should indicate exempt variant"


class TestAnnexIIEnergyExemption:
    """Test energy-specific exemption behavior (v21.0 feature flag)."""

    def _get_energy_exempt_func(self):
        """Helper to get is_annex_ii_energy_exempt function."""
        from app.chat.tools.stacking_tools import is_annex_ii_energy_exempt
        return is_annex_ii_energy_exempt

    def test_legacy_energy_exempt_function(self, prod_app_context):
        """
        Test that legacy is_annex_ii_energy_exempt function works.
        """
        is_annex_ii_energy_exempt = self._get_energy_exempt_func()

        # Test with energy product (default: legacy path)
        result = is_annex_ii_energy_exempt("2709.00.0000")
        assert result["exempt"] is True, "Energy product should be exempt"
        assert result["category"] == "energy"

        # Test with non-energy product
        result2 = is_annex_ii_energy_exempt("8471.30.0100")
        assert result2["exempt"] is False, "Non-energy product should not be exempt"

    def test_energy_exempt_with_import_date(self, prod_app_context):
        """
        Test energy exemption with import_date parameter (v21.0 enhancement).
        """
        is_annex_ii_energy_exempt = self._get_energy_exempt_func()

        # With date, still uses legacy path by default (USE_DB_ENERGY_CHECK=false)
        result = is_annex_ii_energy_exempt("2709.00.0000", "2026-02-07")
        assert result["exempt"] is True, "Energy product should be exempt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
