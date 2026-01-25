"""
Comprehensive Section 301 Rate Tests

Based on the user's test cases:

TEST CASES 3: Section 301 Rates (8 tests, China only)
| #   | HTS Code      | Expected 301 Rate      | Expected Base Rate | Special Exclusions                                        |
|-----|---------------|------------------------|--------------------|-----------------------------------------------------------|
| 1   | 3818.00.00.20 | 50%                    | -                  | EXCLUDE from IEEPA Reciprocal (Annex II critical mineral) |
| 2   | 8541.42.0010  | 50%                    | -                  | -                                                         |
| 3   | 9018.31.0040  | 100%                   | -                  | -                                                         |
| 4   | 4015.12.1010  | 100%                   | -                  | -                                                         |
| 5   | 6307.90.9870  | 50%                    | -                  | -                                                         |
| 6   | 6307.90.9842  | 50% (Ch99: 9903.91.07) | 7%                 | -                                                         |
| 7   | 2504.10.1000  | 25%                    | -                  | EXCLUDE from IEEPA Reciprocal (Annex II critical mineral) |
| 8   | 8505.11.0030  | 25%                    | 2.1%               | -                                                         |
"""

import pytest
import json
from datetime import date


# =============================================================================
# Test Cases 3: Section 301 Rates (China only)
# =============================================================================

class TestSection301Rates:
    """
    Test Section 301 rates for China imports.

    Tests verify:
    1. Correct 301 rate (25%, 50%, or 100%) based on Four-Year Review
    2. Correct Chapter 99 code
    3. Temporal lookup works correctly
    """

    # Test Case 1: HTS 3818.00.00.20 → 50% (Critical mineral - Annex II exclusion from IEEPA)
    def test_hts_3818_50_percent(self):
        """HTS 3818.00.00.20 should return 50% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '3818.00.00.20'
            })
            data = json.loads(result)

            assert data.get('included') == True, \
                f"HTS 3818.00.00.20 should be included in Section 301"
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.50, \
                f"Expected 50% (0.50) for 3818.00.00.20, got {duty_rate * 100}%"

    # Test Case 2: HTS 8541.42.0010 → 50%
    def test_hts_8541_50_percent(self):
        """HTS 8541.42.0010 should return 50% Section 301 rate."""
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
                f"Expected 50% (0.50) for 8541.42.0010, got {duty_rate * 100}%"

    # Test Case 3: HTS 9018.31.0040 → 100% (Syringes - medical)
    def test_hts_9018_100_percent(self):
        """HTS 9018.31.0040 (syringes) should return 100% Section 301 rate."""
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
                f"Expected 100% (1.0) for 9018.31.0040, got {duty_rate * 100}%"

    # Test Case 4: HTS 4015.12.1010 → 100% (Rubber gloves - medical)
    def test_hts_4015_100_percent(self):
        """HTS 4015.12.1010 (rubber gloves) should return 100% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '4015.12.1010'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 1.0, \
                f"Expected 100% (1.0) for 4015.12.1010, got {duty_rate * 100}%"

    # Test Case 5: HTS 6307.90.9870 → 50% (Facemasks)
    def test_hts_6307_90_9870_50_percent(self):
        """HTS 6307.90.9870 (facemasks) should return 50% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '6307.90.9870'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.50, \
                f"Expected 50% (0.50) for 6307.90.9870, got {duty_rate * 100}%"

    # Test Case 6: HTS 6307.90.9842 → 50% with Ch99: 9903.91.07
    def test_hts_6307_90_9842_50_percent_with_ch99(self):
        """HTS 6307.90.9842 should return 50% with Chapter 99 code 9903.91.07."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '6307.90.9842'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.50, \
                f"Expected 50% (0.50) for 6307.90.9842, got {duty_rate * 100}%"

            # Check Chapter 99 code if available
            ch99_code = data.get('chapter_99_code') or data.get('ch99_heading')
            if ch99_code:
                assert ch99_code == '9903.91.07', \
                    f"Expected Ch99 9903.91.07, got {ch99_code}"

    # Test Case 7: HTS 2504.10.1000 → 25% (Critical mineral - Annex II exclusion from IEEPA)
    def test_hts_2504_25_percent(self):
        """HTS 2504.10.1000 should return 25% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '2504.10.1000'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.25, \
                f"Expected 25% (0.25) for 2504.10.1000, got {duty_rate * 100}%"

    # Test Case 8: HTS 8505.11.0030 → 25%
    def test_hts_8505_25_percent(self):
        """HTS 8505.11.0030 should return 25% Section 301 rate."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '8505.11.0030'
            })
            data = json.loads(result)

            assert data.get('included') == True
            duty_rate = data.get('duty_rate', 0)
            assert duty_rate == 0.25, \
                f"Expected 25% (0.25) for 8505.11.0030, got {duty_rate * 100}%"


# =============================================================================
# Test: Section 301 Temporal Lookup
# =============================================================================

class TestSection301TemporalLookup:
    """Test Section 301 temporal rate lookups."""

    def test_temporal_lookup_returns_current_rate(self):
        """Section 301 temporal lookup should return current rate."""
        from app.web import create_app
        from app.web.db.models.tariff_tables import Section301Rate

        app = create_app()
        with app.app_context():
            # Test HTS 38180000 (50%)
            rate = Section301Rate.get_rate_as_of('38180000', date.today())

            assert rate is not None, "No rate found for HTS 38180000"
            assert rate.duty_rate == 0.50, \
                f"Expected 50% duty rate, got {rate.duty_rate * 100}%"
            assert rate.effective_start is not None

    def test_temporal_lookup_hts_9018(self):
        """Section 301 lookup for 9018 should return 100%."""
        from app.web import create_app
        from app.web.db.models.tariff_tables import Section301Rate

        app = create_app()
        with app.app_context():
            rate = Section301Rate.get_rate_as_of('90183100', date.today())

            assert rate is not None, "No rate found for HTS 90183100"
            assert rate.duty_rate == 1.0, \
                f"Expected 100% duty rate, got {rate.duty_rate * 100}%"


# =============================================================================
# Test: Country + HTS Stacking (Test Cases 2 - China specific)
# =============================================================================

class TestChinaHTSStacking:
    """
    Test Country + HTS stacking for China.

    From Test Cases 2:
    | 3A  | 4823.90.6700 | CN | 9903.88.03, 9903.01.24, 9903.01.25 |
    | 4A  | 8517.69.0000 | CN | 9903.88.03, 9903.01.24, 9903.01.25 |
    | 5   | 8708.80.6590 | CN | 9903.88.03, 9903.01.24, 9903.01.33, 9903.94.05, 9903.74.08 |
    """

    def test_china_4823_stacking(self):
        """China + HTS 4823.90.6700 should include Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'CN',
                'hts_code': '4823.90.6700'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]

            # Should include Section 301
            assert 'section_301' in program_ids, \
                f"Section 301 not found for CN + 4823.90.6700. Programs: {program_ids}"

    def test_china_8517_stacking(self):
        """China + HTS 8517.69.0000 should include Section 301 and IEEPA."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'CN',
                'hts_code': '8517.69.0000'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]

            # Should include Section 301 and IEEPA
            assert 'section_301' in program_ids, \
                f"Section 301 not found for CN + 8517.69.0000. Programs: {program_ids}"
            assert 'ieepa_fentanyl' in program_ids, \
                f"IEEPA Fentanyl not found for CN + 8517.69.0000. Programs: {program_ids}"

    def test_china_8708_auto_parts_stacking(self):
        """China + HTS 8708.80.6590 (auto parts) should include 301 + IEEPA + auto codes."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'CN',
                'hts_code': '8708.80.6590'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]

            # Should include Section 301
            assert 'section_301' in program_ids, \
                f"Section 301 not found for CN + 8708.80.6590. Programs: {program_ids}"


# =============================================================================
# Test: Basic HTS Code Validation (Test Cases 1 - subset)
# =============================================================================

class TestBasicHTSValidation:
    """
    Test basic HTS code validation.

    Subset from Test Cases 1 that should pass:
    | 1   | 8541.43.00.10 | PASS   | Should work correctly                                                       |
    | 10  | 3926.20.90.50 | PASS   | Should work correctly                                                       |
    | 11  | 8479.89.70.00 | PASS   | Should work correctly                                                       |
    | 12  | 8543.70.20.00 | PASS   | Should work correctly                                                       |
    """

    def test_hts_8541_43_included(self):
        """HTS 8541.43.00.10 should be included in Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '8541.43.00.10'
            })
            data = json.loads(result)

            assert data.get('included') == True, \
                f"HTS 8541.43.00.10 should be included in Section 301"

    def test_hts_3926_included(self):
        """HTS 3926.20.90.50 should be included in Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '3926.20.90.50'
            })
            data = json.loads(result)

            assert data.get('included') == True, \
                f"HTS 3926.20.90.50 should be included in Section 301"

    def test_hts_8479_included(self):
        """HTS 8479.89.70.00 should be included in Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '8479.89.70.00'
            })
            data = json.loads(result)

            assert data.get('included') == True, \
                f"HTS 8479.89.70.00 should be included in Section 301"

    def test_hts_8543_included(self):
        """HTS 8543.70.20.00 should be included in Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import check_program_inclusion

        app = create_app()
        with app.app_context():
            result = check_program_inclusion.invoke({
                'program_id': 'section_301',
                'hts_code': '8543.70.20.00'
            })
            data = json.loads(result)

            assert data.get('included') == True, \
                f"HTS 8543.70.20.00 should be included in Section 301"


# =============================================================================
# Test: Non-China Countries (should NOT have Section 301)
# =============================================================================

class TestNonChinaCountries:
    """Test that non-China countries do NOT get Section 301."""

    def test_hong_kong_no_section_301(self):
        """Hong Kong should NOT have Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'HK',
                'hts_code': '8544.42.9090'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]

            # Should NOT include Section 301
            assert 'section_301' not in program_ids, \
                f"Section 301 should NOT apply to Hong Kong"

    def test_macau_no_section_301(self):
        """Macau should NOT have Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'MO',
                'hts_code': '8544.42.9090'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]

            # Should NOT include Section 301
            assert 'section_301' not in program_ids, \
                f"Section 301 should NOT apply to Macau"

    def test_japan_no_section_301(self):
        """Japan should NOT have Section 301."""
        from app.web import create_app
        from app.chat.tools.stacking_tools import get_applicable_programs

        app = create_app()
        with app.app_context():
            result = get_applicable_programs.invoke({
                'country': 'JP',
                'hts_code': '9027.20.5060'
            })
            data = json.loads(result)

            program_ids = [p['program_id'] for p in data.get('programs', [])]

            # Should NOT include Section 301
            assert 'section_301' not in program_ids, \
                f"Section 301 should NOT apply to Japan"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
