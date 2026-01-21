"""
End-to-end tests for tariff calculation API output.
Tests verify that the stacking tools return correct rates and programs.

These tests check the fixes for:
1. Country normalization (China -> CN)
2. Section 301 temporal rate lookup
3. IEEPA Fentanyl program inclusion
"""

import pytest
import json
from datetime import date


class TestCountryNormalization:
    """Test that country names are correctly normalized to ISO codes."""

    def test_china_normalizes_to_cn(self):
        """Test 'China' normalizes to 'CN'."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import normalize_country

        app = create_app()
        with app.app_context():
            result = normalize_country('China')
            assert result['iso_alpha2'] == 'CN'
            assert result['normalized'] == True

    def test_hong_kong_normalizes_to_hk(self):
        """Test 'Hong Kong' normalizes to 'HK'."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import normalize_country

        app = create_app()
        with app.app_context():
            result = normalize_country('Hong Kong')
            assert result['iso_alpha2'] == 'HK'

    def test_iso_code_passthrough(self):
        """Test ISO codes pass through unchanged."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import normalize_country

        app = create_app()
        with app.app_context():
            for code in ['CN', 'cn', 'HK', 'MO']:
                result = normalize_country(code)
                assert result['iso_alpha2'] == code.upper()


class TestGetApplicablePrograms:
    """Test that get_applicable_programs returns correct programs for China."""

    def test_china_returns_section_301(self):
        """Test that China imports get Section 301 program."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'China',
                'hts_code': '8544.42.9090'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]
            assert 'section_301' in program_ids, \
                f"Section 301 not found in programs: {program_ids}"

    def test_china_returns_ieepa_fentanyl(self):
        """Test that China imports get IEEPA Fentanyl program."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'China',
                'hts_code': '8544.42.9090'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]
            assert 'ieepa_fentanyl' in program_ids, \
                f"IEEPA Fentanyl not found in programs: {program_ids}"

    def test_china_returns_at_least_5_programs(self):
        """Test that China imports get multiple programs (301, IEEPA, 232)."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'China',
                'hts_code': '8544.42.9090'
            })
            data = json.loads(result)

            total = data.get('total', 0)
            assert total >= 5, \
                f"Expected at least 5 programs, got {total}"


class TestSection301Rates:
    """Test Section 301 rates are correctly returned."""

    def test_hts_3818_returns_50_percent(self):
        """Test HTS 3818.00.00.20 returns 50% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '3818.00.00.20'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.50, \
                f"Expected 50% (0.50), got {duty_rate * 100}%"

    def test_hts_9018_returns_100_percent(self):
        """Test HTS 9018.31.0040 returns 100% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '9018.31.0040'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 1.0, \
                f"Expected 100% (1.0), got {duty_rate * 100}%"

    def test_hts_8541_returns_50_percent(self):
        """Test HTS 8541.42.0010 returns 50% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '8541.42.0010'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.50, \
                f"Expected 50% (0.50), got {duty_rate * 100}%"


class TestTemporalLookup:
    """Test that temporal rate lookups work correctly."""

    def test_section_301_temporal_lookup(self):
        """Test Section 301 uses temporal lookup with effective_start/end."""
        from app.web import create_app
        from app.web.db.models.tariff_tables import Section301Rate

        app = create_app()
        with app.app_context():
            # Get rate as of today
            rate = Section301Rate.get_rate_as_of('38180000', date.today())

            assert rate is not None, "No rate found for HTS 38180000"
            assert rate.duty_rate == 0.50, \
                f"Expected 50% duty rate, got {rate.duty_rate * 100}%"
            assert rate.effective_start is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
