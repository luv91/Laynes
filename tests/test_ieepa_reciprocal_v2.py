"""
v21.0: IEEPA Reciprocal Engine V2 - Golden Test Vectors (TDD)

These tests MUST be written BEFORE the V2 resolver is implemented.
They define expected behavior based on the design document.

Test Coverage:
- 20 golden test vectors from design doc Section 8
- Tests 1-13: Core functionality (MFN ceiling, 232 exempt, Annex II, etc.)
- Tests 14-20: Round 2 reviewer corrections (temporal, transshipment, TIB, in-transit)

NOTE: Tests initially @pytest.mark.skip until V2 resolver is implemented.
Run with USE_IEEPA_V2_ENGINE=true to use V2 resolver.
"""

import json
import os
import pytest
from datetime import date
from unittest.mock import patch

# Database URL for testing - must be set via environment variable
PROD_DB_URL = os.environ.get('IEEPA_TEST_DB_URL', '')


def get_v2_app():
    """
    Create Flask app configured for V2 engine.
    Requires IEEPA_TEST_DB_URL environment variable to be set.
    """
    if not PROD_DB_URL:
        pytest.skip('IEEPA_TEST_DB_URL not set — skipping V2 integration tests')

    # Force V2 engine
    os.environ['USE_IEEPA_V2_ENGINE'] = 'true'
    os.environ['SQLALCHEMY_DATABASE_URI'] = PROD_DB_URL

    from app.web import create_app
    from app.chat.tools import stacking_tools

    # Reset cached app
    stacking_tools._flask_app = None

    app = create_app()
    app.config['TESTING'] = True
    stacking_tools._flask_app = app

    return app


@pytest.fixture
def v2_app_context():
    """
    Provide app context for V2 engine tests with production database.
    """
    app = get_v2_app()

    with app.app_context():
        yield app

    # Clean up
    from app.chat.tools import stacking_tools
    stacking_tools._flask_app = None
    os.environ.pop('USE_IEEPA_V2_ENGINE', None)


# =============================================================================
# Helper Functions
# =============================================================================

def call_v2_resolver(
    hts_digits: str,
    country_code: str,
    entry_date: date,
    entered_value: float = 10000.00,
    base_mfn_ad_val: float = None,
    load_date: date = None,
    vessel_final_mode: bool = None,
    us_content_pct: float = None,
    chapter98_claim: str = None,
    cbp_transshipment: bool = False,
    is_donation: bool = False,
    is_info_material: bool = False
) -> dict:
    """
    Helper to call the V2 resolver.

    Returns parsed JSON result dict.
    """
    # Import here to avoid circular imports at module load time
    from app.chat.tools.stacking_tools import resolve_ieepa_reciprocal_v2

    result = resolve_ieepa_reciprocal_v2(
        hts_digits=hts_digits.replace('.', ''),
        country_code=country_code,
        entry_date=entry_date,
        entered_value=entered_value,
        base_mfn_ad_val=base_mfn_ad_val,
        load_date=load_date,
        vessel_final_mode=vessel_final_mode,
        us_content_pct=us_content_pct,
        chapter98_claim=chapter98_claim,
        cbp_transshipment=cbp_transshipment,
        is_donation=is_donation,
        is_info_material=is_info_material
    )

    return result


# =============================================================================
# Test Class: Core Functionality (Tests 1-13)
# =============================================================================

class TestIeepaReciprocalV2Core:
    """Core V2 resolver tests - MFN ceiling, 232 exempt, Annex II, etc."""

    def test_01_italian_wine_mfn_ceiling_topup(self, v2_app_context):
        """
        Test #1: Italian wine - MFN ceiling with top-up.

        Wine (2204.21.50) from Italy (EU):
        - Base MFN: ~2% ad valorem
        - EU rate: 13% ceiling
        - Since MFN (2%) < ceiling (15%), top-up applies
        - Chapter 99: 9903.02.20 (EU top-up code)
        """
        result = call_v2_resolver(
            hts_digits='2204215000',
            country_code='IT',
            entry_date=date(2026, 2, 10),
            entered_value=10000.00,
            base_mfn_ad_val=2.0  # 2% base MFN
        )

        assert result['chapter_99_code'] == '9903.02.20', "Should use EU top-up code"
        # EU ceiling is 15%, not 13%
        assert result['duty_rate'] == 15.0, "Should apply 15% ceiling rate (EU standard)"
        assert result['variant'] == 'mfn_ceiling', "Should be MFN ceiling variant"
        assert result.get('requires_manual_review') is False

    def test_02_italian_wool_sweater_mfn_ceiling_zero(self, v2_app_context):
        """
        Test #2: Italian wool sweater - MFN >= ceiling, no duty.

        Wool sweater (6110.11.00) from Italy:
        - Base MFN: 16% (or higher for textiles)
        - EU ceiling: 15%
        - Since MFN (16%) >= ceiling (15%), IEEPA = 0%
        - Chapter 99: 9903.02.19 (EU zero code)
        """
        result = call_v2_resolver(
            hts_digits='6110110000',
            country_code='IT',
            entry_date=date(2026, 2, 10),
            entered_value=10000.00,
            base_mfn_ad_val=16.0  # 16% base MFN
        )

        assert result['chapter_99_code'] == '9903.02.19', "Should use EU zero code"
        assert result['duty_rate'] == 0.0, "Should apply 0% (MFN >= ceiling)"
        assert result['variant'] == 'mfn_ceiling'

    def test_03_japanese_car(self, v2_app_context):
        """
        Test #3: Japanese car - Japan-specific ceiling code.

        Car (8703.23.01) from Japan:
        - Japan uses per-partner codes
        - Chapter 99: 9903.02.73 (Japan top-up) or 9903.02.72 (Japan zero)
        """
        result = call_v2_resolver(
            hts_digits='8703230100',
            country_code='JP',
            entry_date=date(2026, 2, 10),
            entered_value=30000.00,
            base_mfn_ad_val=2.5  # 2.5% base MFN for autos
        )

        # Japan top-up code when MFN < 15%
        assert result['chapter_99_code'] == '9903.02.73', "Should use Japan top-up code"
        assert result['duty_rate'] == 15.0, "Japan ceiling is 15% (resolver reports ceiling, not top-up)"

    @pytest.mark.skip(reason="Steel pipe 7304.19.10 not yet in 232 materials data")
    def test_04_japanese_steel_pipe_232_exempt(self, v2_app_context):
        """
        Test #4: Japanese steel pipe - Section 232 exempts from IEEPA.

        Steel pipe (7304.19.10) from Japan:
        - Subject to Section 232 steel tariff
        - IEEPA reciprocal does NOT apply on top of 232
        - Chapter 99: 9903.01.33 (232 exemption from IEEPA)

        NOTE: Skipped until 7304.19.10 is added to section_232_materials table.
        """
        result = call_v2_resolver(
            hts_digits='7304191000',
            country_code='JP',
            entry_date=date(2026, 2, 10),
            entered_value=50000.00
        )

        assert result['chapter_99_code'] == '9903.01.33', "Should use 232 exemption code"
        assert result['duty_rate'] == 0.0, "232 products exempt from IEEPA reciprocal"
        assert result['variant'] == 'metal_exempt'

    def test_05_vietnamese_furniture_high_rate(self, v2_app_context):
        """
        Test #5: Vietnamese furniture - reciprocal rate.

        Furniture (9403.60.80) from Vietnam:
        - Vietnam rate: 20% (EO 14326 Annex I)
        """
        result = call_v2_resolver(
            hts_digits='9403608000',
            country_code='VN',
            entry_date=date(2026, 2, 10),
            entered_value=5000.00
        )

        assert result['chapter_99_code'] == '9903.02.69', "Should use Vietnam code (EO 14326)"
        assert result['duty_rate'] == 20.0, "Vietnam rate is 20% (EO 14326)"
        assert result['variant'] == 'taxable'

    def test_06_vietnamese_steel_frame_furniture_split(self, v2_app_context):
        """
        Test #6: Vietnamese steel-frame furniture - potential split.

        Steel furniture (9403.20.00) from Vietnam:
        - May require split treatment if steel component subject to 232
        """
        result = call_v2_resolver(
            hts_digits='9403200000',
            country_code='VN',
            entry_date=date(2026, 2, 10),
            entered_value=5000.00
        )

        # This depends on how splits are implemented
        # For now, test that it returns a result
        assert 'chapter_99_code' in result
        assert 'duty_rate' in result

    def test_07_uk_machinery_deal_override(self, v2_app_context):
        """
        Test #7: UK machinery - deal override rate.

        Machinery (8481.80.50) from UK:
        - UK has deal override for 8481 at 5%
        - Deal override takes precedence over baseline
        """
        result = call_v2_resolver(
            hts_digits='8481805000',
            country_code='GB',
            entry_date=date(2026, 2, 10),
            entered_value=20000.00
        )

        # UK has deal override for machinery at 5%
        assert result['duty_rate'] == 5.0, "UK machinery at deal override 5%"
        assert result['variant'] == 'deal_override', "Should be deal override variant"

    @pytest.mark.skip(reason="Laptop 8471 not yet in product exclusions data")
    def test_08_chinese_laptop_annex_ii_exempt(self, v2_app_context):
        """
        Test #8: Chinese laptop - Annex II (semiconductor) exemption.

        Laptop (8471.30.01) from China:
        - Covered by Annex II semiconductor exclusion
        - Chapter 99: 9903.01.32 (Annex II exemption code)

        NOTE: Skipped until 8471 is added to ieepa_reciprocal_product_exclusions table.
        """
        result = call_v2_resolver(
            hts_digits='8471300100',
            country_code='CN',
            entry_date=date(2026, 2, 10),
            entered_value=1000.00
        )

        assert result['chapter_99_code'] == '9903.01.32', "Should use Annex II exemption code"
        assert result['duty_rate'] == 0.0, "Annex II products exempt"
        assert result['variant'] == 'annex_ii_exempt'

    def test_09_chinese_steel_bolts_232_exempt(self, v2_app_context):
        """
        Test #9: Chinese steel bolts - Section 232 exempts from IEEPA.

        Steel bolts (7318.15.20) from China:
        - Subject to Section 232 steel derivative tariff
        - Exempt from IEEPA reciprocal
        """
        result = call_v2_resolver(
            hts_digits='7318152000',
            country_code='CN',
            entry_date=date(2026, 2, 10),
            entered_value=5000.00
        )

        assert result['chapter_99_code'] == '9903.01.33', "Should use 232 exemption code"
        assert result['duty_rate'] == 0.0, "232 products exempt"
        assert result['variant'] in ('metal_exempt', 's232_subject'), "Should be 232 exempt variant"

    def test_10_indian_textiles(self, v2_app_context):
        """
        Test #10: Indian textiles - fixed rate.

        Textiles (5208.31.60) from India:
        - India rate: 25% (or negotiated deal rate)
        """
        result = call_v2_resolver(
            hts_digits='5208316000',
            country_code='IN',
            entry_date=date(2026, 2, 10),
            entered_value=3000.00
        )

        assert result['chapter_99_code'] == '9903.02.26', "Should use India code (9903.02.34 is Lesotho)"
        # Note: India may have deal rate different from baseline
        assert 'duty_rate' in result

    def test_11_cuban_goods_column2_exempt(self, v2_app_context):
        """
        Test #11: Cuban goods - Column 2 country exemption.

        Any goods from Cuba:
        - Column 2 countries exempt from IEEPA reciprocal
        - Chapter 99: 9903.01.29
        """
        result = call_v2_resolver(
            hts_digits='2204210000',  # Wine
            country_code='CU',
            entry_date=date(2026, 2, 10),
            entered_value=1000.00
        )

        assert result['chapter_99_code'] == '9903.01.29', "Should use Column 2 exemption code"
        assert result['duty_rate'] == 0.0, "Column 2 countries exempt"
        assert result['variant'] in ('exempt', 'column2'), "Should be exempt variant"

    def test_12_canadian_goods_usmca_exempt(self, v2_app_context):
        """
        Test #12: Canadian goods - USMCA exemption.

        Any goods from Canada:
        - USMCA partners exempt from IEEPA reciprocal
        - Chapter 99: 9903.01.26
        """
        result = call_v2_resolver(
            hts_digits='8471300100',  # Laptop
            country_code='CA',
            entry_date=date(2026, 2, 10),
            entered_value=1500.00
        )

        assert result['chapter_99_code'] == '9903.01.26', "Should use USMCA exemption code"
        assert result['duty_rate'] == 0.0, "USMCA partners exempt"
        assert result['variant'] in ('exempt', 'usmca'), "Should be exempt variant"

    @pytest.mark.skip(reason="US content split feature not yet implemented in V2")
    def test_13_us_content_split_from_thailand(self, v2_app_context):
        """
        Test #13: US content split from Thailand.

        Product from Thailand with 30% US content:
        - Only 70% of value subject to IEEPA
        - Split plan required

        NOTE: Skipped until US content split feature is implemented in V2 resolver.
        """
        result = call_v2_resolver(
            hts_digits='8471300100',
            country_code='TH',
            entry_date=date(2026, 2, 10),
            entered_value=10000.00,
            us_content_pct=30.0  # 30% US content
        )

        # Should have split plan
        assert result.get('split_plan') is not None or result.get('creates_split') is True
        # 70% of value subject to tariff
        if result.get('split_plan'):
            assert result['split_plan']['line_1']['value'] == 3000.00  # US content
            assert result['split_plan']['line_2']['value'] == 7000.00  # Foreign content


# =============================================================================
# Test Class: Round 2 Corrections (Tests 14-20)
# =============================================================================

class TestIeepaReciprocalV2Round2Corrections:
    """Tests specifically for Round 2 reviewer corrections."""

    def test_14_china_april_10_historical(self, v2_app_context):
        """
        Test #14: China April 10 historical rate (before suspension).

        Any goods from China on April 10, 2025:
        - China rate was 34% before May 14 suspension
        - Chapter 99: 9903.01.63

        This tests TEMPORAL VERSIONING of rates.
        """
        result = call_v2_resolver(
            hts_digits='9403608000',  # Furniture
            country_code='CN',
            entry_date=date(2025, 4, 10),  # Before May 14 suspension
            entered_value=10000.00
        )

        assert result['chapter_99_code'] == '9903.01.63', "Should use historical 34% code"
        assert result['duty_rate'] == 34.0, "China rate was 34% on April 10"

    def test_15_transshipment_cbp_determination(self, v2_app_context):
        """
        Test #15: Transshipment - CBP-directed 40% penalty.

        Goods with CBP transshipment determination:
        - Overrides normal country rate
        - 40% penalty rate applies
        - Chapter 99: 9903.02.01

        This tests EXCEPTION RULE priority 1.
        """
        result = call_v2_resolver(
            hts_digits='9403608000',
            country_code='VN',  # Normally 20% (EO 14326)
            entry_date=date(2026, 2, 10),
            entered_value=10000.00,
            cbp_transshipment=True  # CBP determination flag
        )

        assert result['chapter_99_code'] == '9903.02.01', "Should use transshipment code"
        assert result['duty_rate'] == 40.0, "Transshipment penalty is 40%"
        assert result['variant'] == 'transshipment'

    def test_16_tib_from_germany(self, v2_app_context):
        """
        Test #16: TIB (Temporary Import Bond) from Germany.

        Goods with TIB claim:
        - Must report country's Chapter 99 code
        - But duty is 0% while goods under bond
        - Chapter 99: Country-dependent (DE = 9903.02.20 for EU)

        This tests TIB exception rule with NULL ch99_code in rule.
        """
        result = call_v2_resolver(
            hts_digits='8471300100',
            country_code='DE',
            entry_date=date(2026, 2, 10),
            entered_value=10000.00,
            chapter98_claim='TIB'
        )

        # Code comes from country schedule (EU), not exception rule
        assert result['chapter_99_code'] == '9903.02.20', "Should use EU code for reporting"
        assert result['duty_rate'] == 0.0, "TIB entries report 0% duty"
        assert result['action'] == 'report_only'

    def test_17_in_transit_aug_window_vietnam(self, v2_app_context):
        """
        Test #17: In-transit August window from Vietnam.

        Goods loaded before Aug 7, 2025, entered Aug 7 - Oct 4:
        - Qualify for baseline 10% instead of country rate
        - Vietnam would normally be 41%
        - Chapter 99: 9903.01.25 (baseline)

        This tests Bug A (transit_entry_start) and Bug B (requires_flag).
        """
        result = call_v2_resolver(
            hts_digits='9403608000',  # Furniture
            country_code='VN',
            entry_date=date(2025, 9, 1),  # Within Aug window
            entered_value=10000.00,
            load_date=date(2025, 8, 1),  # Loaded before Aug 7
            vessel_final_mode=True
        )

        assert result['chapter_99_code'] == '9903.01.25', "Should use baseline code"
        assert result['duty_rate'] == 10.0, "In-transit gets baseline 10%"
        assert result['variant'] in ('in_transit', 'in_transit_aug'), "Should be in-transit variant"

    def test_17b_in_transit_aug_skips_baseline_countries(self, v2_app_context):
        """
        Test #17b: In-transit August window does NOT apply to baseline countries.

        UK is already at baseline 10%, so in-transit window gives no benefit.
        Rule should be skipped per Bug B fix (requires_flag = 'country_would_exceed_baseline').
        """
        result = call_v2_resolver(
            hts_digits='8481805000',  # Machinery
            country_code='GB',  # UK - already at baseline
            entry_date=date(2025, 9, 1),
            entered_value=10000.00,
            load_date=date(2025, 8, 1),
            vessel_final_mode=True
        )

        # Should NOT use in-transit rule, just normal baseline
        assert result['duty_rate'] == 10.0, "UK at baseline 10%"
        # Variant should NOT be in_transit since rule was skipped
        assert result['variant'] != 'in_transit', "Baseline countries skip in-transit rule"

    def test_18_argentina_deal_product(self, v2_app_context):
        """
        Test #18: Argentina deal product.

        Specific product (coffee 0901.XX) from Argentina:
        - Deal override provides reduced rate
        - Tests DEAL OVERRIDE table lookup
        """
        result = call_v2_resolver(
            hts_digits='0901110000',  # Coffee
            country_code='AR',
            entry_date=date(2026, 2, 10),
            entered_value=5000.00
        )

        # Deal override should provide reduced rate
        # Exact values depend on deal data
        assert 'chapter_99_code' in result
        assert result.get('deal_name') is not None or 'deal' in result.get('variant', '')

    def test_19_korean_auto_parts_232_steel(self, v2_app_context):
        """
        Test #19: Korean auto parts - Section 232 steel exemption.

        Auto parts (8708.99.81) from Korea:
        - HTS 8708.99.81 is in section_232_materials as steel
        - 232 exemption takes precedence over Korea MFN ceiling
        - Chapter 99: 9903.01.33 (232 exemption code)
        """
        result = call_v2_resolver(
            hts_digits='8708998100',
            country_code='KR',
            entry_date=date(2026, 2, 10),
            entered_value=15000.00,
            base_mfn_ad_val=2.5  # Low MFN rate
        )

        # Auto parts with steel content are 232 exempt from IEEPA
        assert result['chapter_99_code'] == '9903.01.33', "Should use 232 exemption code"
        assert result['duty_rate'] == 0.0, "232 products exempt from IEEPA"
        assert result['variant'] in ('metal_exempt', 's232_subject'), "Should be 232 exempt variant"

    def test_20_swiss_watch(self, v2_app_context):
        """
        Test #20: Swiss watch - Switzerland-specific ceiling.

        Watch (9101.11.40) from Switzerland:
        - Switzerland uses per-partner codes
        - Chapter 99: 9903.02.83 (Switzerland top-up) or 9903.02.82 (zero)
        - Ceiling: 15% (EO 14346)
        """
        result = call_v2_resolver(
            hts_digits='9101114000',
            country_code='CH',
            entry_date=date(2026, 2, 10),
            entered_value=5000.00,
            base_mfn_ad_val=3.0  # Watch MFN ~3-6%
        )

        assert result['chapter_99_code'] == '9903.02.83', "Should use Switzerland top-up code"
        assert result['duty_rate'] == 15.0, "Switzerland ceiling is 15% (resolver reports ceiling, not top-up)"


# =============================================================================
# Test Class: Bug Fix Verification
# =============================================================================

class TestIeepaReciprocalV2BugFixes:
    """Tests to verify specific bug fixes from reviewer feedback."""

    def test_bug_c_mfn_ceiling_missing_base_rate(self, v2_app_context):
        """
        Bug C fix: MFN ceiling with missing base rate returns conservative estimate.

        When base_mfn_ad_val is None:
        - Should NOT return None/None
        - Should return conservative estimate (ceiling rate)
        - Should set requires_manual_review = True
        """
        result = call_v2_resolver(
            hts_digits='2204215000',  # Wine
            country_code='IT',
            entry_date=date(2026, 2, 10),
            entered_value=10000.00,
            base_mfn_ad_val=None  # Missing!
        )

        # Should NOT be None
        assert result['chapter_99_code'] is not None, "Should not return None code"
        assert result['duty_rate'] is not None, "Should not return None rate"

        # Conservative estimate
        assert result['duty_rate'] == 15.0 or result['duty_rate'] == 13.0, "Should use ceiling rate"
        assert result['requires_manual_review'] is True, "Should require manual review"
        assert 'MFN' in result.get('review_reason', ''), "Should explain why manual review needed"

    def test_bug_a_transit_entry_start_lower_bound(self, v2_app_context):
        """
        Bug A fix: In-transit rules check transit_entry_start.

        Entry date BEFORE transit_entry_start should NOT match rule.
        """
        result = call_v2_resolver(
            hts_digits='9403608000',
            country_code='VN',
            entry_date=date(2025, 8, 5),  # Before Aug 7 window starts
            entered_value=10000.00,
            load_date=date(2025, 8, 1),  # Loaded before Aug 7
            vessel_final_mode=True
        )

        # Should NOT get in-transit benefit (entry too early)
        # Vietnam rate should apply
        assert result['variant'] != 'in_transit', "Should not match in-transit (entry too early)"
        assert result['duty_rate'] == 41.0 or result['duty_rate'] == 10.0, "Should use normal rate"

    def test_temporal_semantics_closed_open(self, v2_app_context):
        """
        Verify temporal semantics use closed-open intervals.

        effective_start <= date < effective_end
        End date is day AFTER last valid day.
        """
        # Test China suspension boundary: May 14, 2025
        # May 13 should still be 34%, May 14 should be 10%

        result_may13 = call_v2_resolver(
            hts_digits='9403608000',
            country_code='CN',
            entry_date=date(2025, 5, 13),  # Last day of 34%
            entered_value=10000.00
        )

        result_may14 = call_v2_resolver(
            hts_digits='9403608000',
            country_code='CN',
            entry_date=date(2025, 5, 14),  # First day of 10%
            entered_value=10000.00
        )

        assert result_may13['duty_rate'] == 34.0, "May 13 should be 34%"
        assert result_may14['duty_rate'] == 10.0, "May 14 should be 10%"


# =============================================================================
# Test Class: Compatibility Layer
# =============================================================================

class TestIeepaReciprocalV2Compatibility:
    """Tests for V1/V2 compatibility wrapper."""

    def test_wrapper_converts_percentage_to_decimal(self, v2_app_context):
        """
        Bug D verification: Wrapper converts V2 percentage to V1 decimal.

        V2 uses percentage (10.0 = 10%)
        V1 expects decimal (0.10 = 10%)
        Wrapper must convert.
        """
        from app.chat.tools.stacking_tools import resolve_reciprocal_variant

        # resolve_reciprocal_variant is a LangChain @tool, use .invoke()
        result_json = resolve_reciprocal_variant.invoke({
            'hts_code': '8481.80.50',
            'slice_type': 'full',
            'country_code': 'GB',
            'import_date': '2026-02-10'
        })

        result = json.loads(result_json)

        # V1 format uses decimal - UK has deal override at 5%, so 0.05
        assert result['duty_rate'] < 1.0, "V1 format is decimal, not percentage"

    def test_wrapper_passes_v2_inputs(self, v2_app_context):
        """
        Gap #2 verification: Wrapper passes V2 inputs to resolver.
        """
        from app.chat.tools.stacking_tools import resolve_reciprocal_variant

        # Call with V2 inputs - resolve_reciprocal_variant is a LangChain @tool, use .invoke()
        result_json = resolve_reciprocal_variant.invoke({
            'hts_code': '9403.60.80',
            'slice_type': 'full',
            'country_code': 'VN',
            'import_date': '2025-09-01',
            # V2 inputs
            'entered_value': 10000.00,
            'load_date': '2025-08-01',
            'vessel_final_mode': True
        })

        result = json.loads(result_json)

        # Should get in-transit benefit if V2 inputs are passed through
        assert result['variant'] in ('in_transit', 'in_transit_aug'), "Should receive V2 inputs"


# =============================================================================
# Test Class: Feature Flag
# =============================================================================

class TestFeatureFlag:
    """Tests for feature flag behavior."""

    def test_v1_engine_with_flag_false(self):
        """
        USE_IEEPA_V2_ENGINE=false should use V1 engine.
        """
        os.environ['USE_IEEPA_V2_ENGINE'] = 'false'
        os.environ['SQLALCHEMY_DATABASE_URI'] = PROD_DB_URL

        try:
            from app.web import create_app
            from app.chat.tools import stacking_tools
            from app.chat.tools.stacking_tools import resolve_reciprocal_variant

            # Reset cached app to pick up new env var
            stacking_tools._flask_app = None
            app = create_app()
            stacking_tools._flask_app = app

            with app.app_context():
                # resolve_reciprocal_variant is a LangChain @tool, use .invoke()
                result_json = resolve_reciprocal_variant.invoke({
                    'hts_code': '8481.80.50',
                    'slice_type': 'full',
                    'country_code': 'GB',
                    'import_date': '2026-02-10'
                })

                # V1 should return valid JSON
                result = json.loads(result_json)
                assert 'variant' in result

        finally:
            # Guard against UnboundLocalError if import above failed
            try:
                stacking_tools._flask_app = None
            except NameError:
                pass
            os.environ.pop('USE_IEEPA_V2_ENGINE', None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
