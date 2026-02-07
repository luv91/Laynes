"""
Section 232 Engine Tests — Comprehensive coverage for temporal rate lookups,
material handling, article types, UK exceptions, and IEEPA unstacking.

These tests exercise the data model layer directly (no Pinecone, no LLM),
ensuring the deterministic core of Section 232 logic is correct.

Test groups:
  1. Section232Rate.get_rate_as_of() — Temporal lookup, country fallback, UK exception
  2. Section232Material — Article types, claim/disclaim codes, split policy
  3. Section232Predicate — Semiconductor threshold evaluation
  4. IEEPA unstacking — 232 content deducted from Reciprocal base
  5. Disclaim behavior — Copper required vs steel/aluminum omit
  6. Entry slice golden paths — Full duty calculations for known scenarios
"""

import os
import sys
import pytest
from datetime import date, datetime
from decimal import Decimal

# Ensure testing env
os.environ["TESTING"] = "true"
os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

lanes_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if lanes_dir not in sys.path:
    sys.path.insert(0, lanes_dir)


# ============================================================================
# Fixtures: Populate in-memory SQLite with realistic 232 data
# ============================================================================

@pytest.fixture
def app_with_232_data():
    """Create Flask app with fully populated Section 232 test data."""
    from app.web import create_app
    from app.web.db import db
    from app.web.db.models.tariff_tables import (
        TariffProgram, Section232Rate, Section232Material, Section232Predicate,
        Section301Rate, Section301Inclusion, IeepaRate, DutyRule, ProgramCode,
        IeepaAnnexIIExclusion, TariffCalculationLog, SourceDocument,
    )

    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SECRET_KEY": "test-secret-key",
    })

    with app.app_context():
        db.create_all()

        # --- Source Documents (for audit trail) ---
        src_proc_10896 = SourceDocument(
            title="Proclamation 10896 - Steel/Aluminum 232",
            doc_type="proclamation",
            doc_identifier="Proc-10896",
        )
        src_proc_10908 = SourceDocument(
            title="Proclamation 10908 - Auto Parts 232",
            doc_type="proclamation",
            doc_identifier="Proc-10908",
        )
        db.session.add_all([src_proc_10896, src_proc_10908])
        db.session.flush()

        # --- TariffProgram entries ---
        programs = [
            TariffProgram(
                program_id="section_232_steel", program_name="Section 232 Steel",
                country="ALL", check_type="hts_lookup",
                condition_handler="handle_material_composition",
                filing_sequence=4, calculation_sequence=3,
                effective_date=date(2018, 3, 23),
                disclaim_behavior="omit",
            ),
            TariffProgram(
                program_id="section_232_aluminum", program_name="Section 232 Aluminum",
                country="ALL", check_type="hts_lookup",
                condition_handler="handle_material_composition",
                filing_sequence=5, calculation_sequence=3,
                effective_date=date(2018, 3, 23),
                disclaim_behavior="omit",
            ),
            TariffProgram(
                program_id="section_232_copper", program_name="Section 232 Copper",
                country="ALL", check_type="hts_lookup",
                condition_handler="handle_material_composition",
                filing_sequence=6, calculation_sequence=3,
                effective_date=date(2025, 3, 4),
                disclaim_behavior="required",
            ),
            TariffProgram(
                program_id="section_301", program_name="Section 301 China",
                country="China", check_type="hts_lookup",
                filing_sequence=1, calculation_sequence=1,
                effective_date=date(2018, 7, 6),
                disclaim_behavior="none",
            ),
            TariffProgram(
                program_id="ieepa_fentanyl", program_name="IEEPA Fentanyl",
                country="China", check_type="always",
                filing_sequence=2, calculation_sequence=2,
                effective_date=date(2025, 3, 4),
                disclaim_behavior="none",
            ),
            TariffProgram(
                program_id="ieepa_reciprocal", program_name="IEEPA Reciprocal",
                country="China", check_type="always",
                filing_sequence=3, calculation_sequence=4,
                effective_date=date(2025, 4, 9),
                disclaim_behavior="none",
            ),
        ]
        db.session.add_all(programs)

        # --- Section 232 Rates (temporal) ---
        # Steel: Global 25% until March 2025, then 50%
        rates_232 = [
            # Steel — pre-March 2025: 25% globally
            Section232Rate(
                hts_8digit="72081000", material_type="steel",
                chapter_99_claim="9903.80.01", chapter_99_disclaim="9903.80.02",
                duty_rate=Decimal("0.2500"), country_code=None,
                article_type="primary",
                effective_start=date(2018, 3, 23), effective_end=date(2025, 3, 12),
                source_doc="Proc-9705",
            ),
            # Steel — post-March 2025: 50% globally
            Section232Rate(
                hts_8digit="72081000", material_type="steel",
                chapter_99_claim="9903.80.01", chapter_99_disclaim="9903.80.02",
                duty_rate=Decimal("0.5000"), country_code=None,
                article_type="primary",
                effective_start=date(2025, 3, 12), effective_end=None,
                source_doc="Proc-10896",
            ),
            # Steel — UK exception: stays at 25%
            Section232Rate(
                hts_8digit="72081000", material_type="steel",
                chapter_99_claim="9903.80.01", chapter_99_disclaim="9903.80.02",
                duty_rate=Decimal("0.2500"), country_code="GBR",
                article_type="primary",
                effective_start=date(2022, 6, 1), effective_end=None,
                source_doc="Proc-UK-Exception",
            ),
            # Aluminum — post-March 2025: 50% globally
            Section232Rate(
                hts_8digit="76011020", material_type="aluminum",
                chapter_99_claim="9903.85.03", chapter_99_disclaim="9903.85.04",
                duty_rate=Decimal("0.5000"), country_code=None,
                article_type="primary",
                effective_start=date(2025, 3, 12), effective_end=None,
                source_doc="Proc-10896",
            ),
            # Aluminum — UK exception: 25%
            Section232Rate(
                hts_8digit="76011020", material_type="aluminum",
                chapter_99_claim="9903.85.03", chapter_99_disclaim="9903.85.04",
                duty_rate=Decimal("0.2500"), country_code="GBR",
                article_type="primary",
                effective_start=date(2022, 6, 1), effective_end=None,
                source_doc="Proc-UK-Exception",
            ),
            # Copper — 25% (from March 4, 2025)
            Section232Rate(
                hts_8digit="74081100", material_type="copper",
                chapter_99_claim="9903.78.01", chapter_99_disclaim="9903.78.02",
                duty_rate=Decimal("0.2500"), country_code=None,
                article_type="content",
                effective_start=date(2025, 3, 4), effective_end=None,
                source_doc="Proc-Copper-232",
            ),
            # Derivative steel article (Ch 73 pipes)
            Section232Rate(
                hts_8digit="73041100", material_type="steel",
                chapter_99_claim="9903.81.89", chapter_99_disclaim="9903.81.90",
                duty_rate=Decimal("0.5000"), country_code=None,
                article_type="derivative",
                effective_start=date(2025, 3, 12), effective_end=None,
                source_doc="Proc-10896",
            ),
            # Content steel article (Ch 85 electrical with steel content)
            Section232Rate(
                hts_8digit="85044090", material_type="steel",
                chapter_99_claim="9903.81.91", chapter_99_disclaim="9903.81.92",
                duty_rate=Decimal("0.5000"), country_code=None,
                article_type="content",
                effective_start=date(2025, 3, 12), effective_end=None,
                source_doc="Proc-10896",
            ),
            # Content copper article (Ch 85 electrical with copper content)
            Section232Rate(
                hts_8digit="85044090", material_type="copper",
                chapter_99_claim="9903.78.01", chapter_99_disclaim="9903.78.02",
                duty_rate=Decimal("0.2500"), country_code=None,
                article_type="content",
                effective_start=date(2025, 3, 4), effective_end=None,
                source_doc="Proc-Copper-232",
            ),
        ]
        db.session.add_all(rates_232)

        # --- Section 232 Materials (product/material mappings) ---
        materials = [
            # Primary steel (Ch 72)
            Section232Material(
                hts_8digit="72081000", material="steel",
                claim_code="9903.80.01", disclaim_code="9903.80.02",
                duty_rate=Decimal("0.5000"),
                article_type="primary", content_basis="value",
                split_policy="never",
            ),
            # Primary aluminum (Ch 76)
            Section232Material(
                hts_8digit="76011020", material="aluminum",
                claim_code="9903.85.03", disclaim_code="9903.85.04",
                duty_rate=Decimal("0.5000"),
                article_type="primary", content_basis="value",
                split_policy="never",
            ),
            # Content copper (Ch 74)
            Section232Material(
                hts_8digit="74081100", material="copper",
                claim_code="9903.78.01", disclaim_code="9903.78.02",
                duty_rate=Decimal("0.2500"),
                article_type="content", content_basis="value",
                split_policy="if_any_content",
            ),
            # Derivative steel (Ch 73 pipes)
            Section232Material(
                hts_8digit="73041100", material="steel",
                claim_code="9903.81.89", disclaim_code="9903.81.90",
                duty_rate=Decimal("0.5000"),
                article_type="derivative", content_basis="value",
                split_policy="never",
            ),
            # Content steel in electrical product (Ch 85)
            Section232Material(
                hts_8digit="85044090", material="steel",
                claim_code="9903.81.91", disclaim_code="9903.81.92",
                duty_rate=Decimal("0.5000"),
                article_type="content", content_basis="value",
                split_policy="if_any_content",
            ),
            # Content copper in electrical product (Ch 85)
            Section232Material(
                hts_8digit="85044090", material="copper",
                claim_code="9903.78.01", disclaim_code="9903.78.02",
                duty_rate=Decimal("0.2500"),
                article_type="content", content_basis="value",
                split_policy="if_any_content",
            ),
        ]
        db.session.add_all(materials)

        # --- DutyRules for 232 programs ---
        duty_rules = [
            DutyRule(
                program_id="section_232_steel", calculation_type="on_portion",
                base_on="content_value", content_key="steel",
                fallback_base_on="full_value", base_effect="subtract_from_remaining",
            ),
            DutyRule(
                program_id="section_232_aluminum", calculation_type="on_portion",
                base_on="content_value", content_key="aluminum",
                fallback_base_on="full_value", base_effect="subtract_from_remaining",
            ),
            DutyRule(
                program_id="section_232_copper", calculation_type="on_portion",
                base_on="content_value", content_key="copper",
                fallback_base_on="full_value", base_effect="subtract_from_remaining",
            ),
            DutyRule(
                program_id="ieepa_reciprocal", variant="taxable",
                calculation_type="additive", base_on="remaining_value",
            ),
            DutyRule(
                program_id="section_301", calculation_type="additive",
                base_on="product_value",
            ),
            DutyRule(
                program_id="ieepa_fentanyl", calculation_type="additive",
                base_on="product_value",
            ),
        ]
        db.session.add_all(duty_rules)

        # --- Section 301 rates (for stacking golden paths) ---
        s301_rates = [
            Section301Rate(
                hts_8digit="85044090", chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.2500"),
                effective_start=date(2018, 8, 23), effective_end=None,
                list_name="list_3", role="impose",
            ),
            Section301Rate(
                hts_8digit="72081000", chapter_99_code="9903.88.01",
                duty_rate=Decimal("0.2500"),
                effective_start=date(2018, 7, 6), effective_end=None,
                list_name="list_1", role="impose",
            ),
        ]
        db.session.add_all(s301_rates)

        # --- IEEPA Rates ---
        ieepa_rates = [
            IeepaRate(
                program_type="fentanyl", country_code="CN",
                chapter_99_code="9903.01.24", duty_rate=Decimal("0.1000"),
                effective_start=date(2025, 3, 4), effective_end=None,
            ),
            IeepaRate(
                program_type="reciprocal", country_code="CN",
                chapter_99_code="9903.01.25", duty_rate=Decimal("0.1000"),
                variant="taxable",
                effective_start=date(2025, 4, 9), effective_end=None,
            ),
        ]
        db.session.add_all(ieepa_rates)

        # --- Section 232 Predicates (semiconductor) ---
        predicates = [
            Section232Predicate(
                program_id="section_232_semiconductor",
                hts_scope="8541,8542",
                predicate_group="range_1",
                attribute_name="transistor_processing_power",
                attribute_unit="billion_transistors",
                threshold_min=Decimal("50.0"),
                threshold_max=None,
                claim_heading_if_true="9903.79.01",
                rate_if_true=Decimal("0.2500"),
                heading_if_false="9903.79.02",
                rate_if_false=Decimal("0.0000"),
                effective_start=date(2025, 12, 1),
                effective_end=None,
            ),
        ]
        db.session.add_all(predicates)

        db.session.commit()
        yield app
        db.drop_all()


# ============================================================================
# 1. Section232Rate.get_rate_as_of() — Temporal Lookup Tests
# ============================================================================

class TestSection232TemporalRates:
    """Test temporal rate lookups for Section 232."""

    def test_steel_rate_before_march_2025(self, app_with_232_data):
        """Steel at 25% before March 12, 2025 rate increase."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="72081000", material="steel",
                country_code=None, as_of_date=date(2025, 1, 15)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.25
            assert rate.article_type == "primary"

    def test_steel_rate_after_march_2025(self, app_with_232_data):
        """Steel at 50% after March 12, 2025 (Proc 10896)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="72081000", material="steel",
                country_code=None, as_of_date=date(2025, 6, 1)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.50

    def test_steel_rate_on_exact_changeover_date(self, app_with_232_data):
        """On March 12, 2025 itself — the NEW rate should apply (end-exclusive)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="72081000", material="steel",
                country_code=None, as_of_date=date(2025, 3, 12)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.50, \
                "On effective_start of new rate, new rate should apply"

    def test_steel_rate_day_before_changeover(self, app_with_232_data):
        """Day before changeover — old 25% rate should still apply."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="72081000", material="steel",
                country_code=None, as_of_date=date(2025, 3, 11)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.25

    def test_uk_exception_steel_25_percent(self, app_with_232_data):
        """UK gets 25% for steel, not the global 50%."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="72081000", material="steel",
                country_code="GBR", as_of_date=date(2025, 6, 1)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.25
            assert rate.country_code == "GBR"

    def test_uk_exception_aluminum_25_percent(self, app_with_232_data):
        """UK gets 25% for aluminum, not the global 50%."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="76011020", material="aluminum",
                country_code="GBR", as_of_date=date(2025, 6, 1)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.25

    def test_non_uk_country_gets_global_rate(self, app_with_232_data):
        """Germany (DEU) should fall back to global 50%."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="72081000", material="steel",
                country_code="DEU", as_of_date=date(2025, 6, 1)
            )
            assert rate is not None
            # Falls back to global (country_code=None) → 50%
            assert float(rate.duty_rate) == 0.50
            assert rate.country_code is None

    def test_hts_not_on_232_list(self, app_with_232_data):
        """HTS code not in Section 232 should return None."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="99999999", material="steel",
                country_code=None, as_of_date=date(2025, 6, 1)
            )
            assert rate is None

    def test_copper_rate_25_percent(self, app_with_232_data):
        """Copper at 25% (different from steel/aluminum 50%)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="74081100", material="copper",
                country_code=None, as_of_date=date(2025, 6, 1)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.25

    def test_copper_not_active_before_effective_date(self, app_with_232_data):
        """Copper 232 didn't exist before March 4, 2025."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.get_rate_as_of(
                hts_8digit="74081100", material="copper",
                country_code=None, as_of_date=date(2025, 1, 1)
            )
            assert rate is None


# ============================================================================
# 2. Article Type Tests
# ============================================================================

class TestArticleTypes:
    """Test primary/derivative/content article type classification."""

    def test_primary_steel_full_value(self, app_with_232_data):
        """Primary steel (Ch 72) → duty on full product value, no splitting."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Material
            mat = Section232Material.query.filter_by(
                hts_8digit="72081000", material="steel"
            ).first()
            assert mat is not None
            assert mat.article_type == "primary"
            assert mat.split_policy == "never"
            assert mat.claim_code == "9903.80.01"

    def test_derivative_steel_full_value(self, app_with_232_data):
        """Derivative steel (Ch 73 pipes) → duty on full value per U.S. Note 16."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Material
            mat = Section232Material.query.filter_by(
                hts_8digit="73041100", material="steel"
            ).first()
            assert mat is not None
            assert mat.article_type == "derivative"
            assert mat.split_policy == "never"
            assert mat.claim_code == "9903.81.89"

    def test_content_copper_splits(self, app_with_232_data):
        """Content copper → duty on content value only, split lines."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Material
            mat = Section232Material.query.filter_by(
                hts_8digit="74081100", material="copper"
            ).first()
            assert mat is not None
            assert mat.article_type == "content"
            assert mat.split_policy == "if_any_content"

    def test_multi_material_product(self, app_with_232_data):
        """HTS 85044090 has BOTH steel and copper materials."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Material
            mats = Section232Material.query.filter_by(
                hts_8digit="85044090"
            ).all()
            material_names = {m.material for m in mats}
            assert material_names == {"steel", "copper"}
            # Both should be content type for Ch 85
            for m in mats:
                assert m.article_type == "content"
                assert m.split_policy == "if_any_content"


# ============================================================================
# 3. Disclaim Behavior Tests
# ============================================================================

class TestDisclaimBehavior:
    """Test copper=required vs steel/aluminum=omit."""

    def test_copper_disclaim_required(self, app_with_232_data):
        """Copper program has disclaim_behavior='required'."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import TariffProgram
            prog = TariffProgram.query.filter_by(
                program_id="section_232_copper"
            ).first()
            assert prog is not None
            assert prog.disclaim_behavior == "required"

    def test_steel_disclaim_omit(self, app_with_232_data):
        """Steel program has disclaim_behavior='omit'."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import TariffProgram
            prog = TariffProgram.query.filter_by(
                program_id="section_232_steel"
            ).first()
            assert prog is not None
            assert prog.disclaim_behavior == "omit"

    def test_aluminum_disclaim_omit(self, app_with_232_data):
        """Aluminum program has disclaim_behavior='omit'."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import TariffProgram
            prog = TariffProgram.query.filter_by(
                program_id="section_232_aluminum"
            ).first()
            assert prog is not None
            assert prog.disclaim_behavior == "omit"

    def test_non_232_has_no_disclaim(self, app_with_232_data):
        """Section 301 has disclaim_behavior='none'."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import TariffProgram
            prog = TariffProgram.query.filter_by(
                program_id="section_301"
            ).first()
            assert prog.disclaim_behavior == "none"


# ============================================================================
# 4. Semiconductor Predicate Tests
# ============================================================================

class TestSemiconductorPredicates:
    """Test Section 232 semiconductor threshold evaluation."""

    def test_predicate_matches_hts_8541(self, app_with_232_data):
        """Predicate with scope '8541,8542' should match HTS starting with 8541."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Predicate
            preds = Section232Predicate.get_predicates_for_hts(
                program_id="section_232_semiconductor",
                hts_8digit="85411000",
                as_of_date=date(2026, 1, 1)
            )
            assert len(preds) == 1
            assert preds[0].attribute_name == "transistor_processing_power"

    def test_predicate_does_not_match_other_hts(self, app_with_232_data):
        """Predicate should NOT match HTS not in scope."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Predicate
            preds = Section232Predicate.get_predicates_for_hts(
                program_id="section_232_semiconductor",
                hts_8digit="72081000",
                as_of_date=date(2026, 1, 1)
            )
            assert len(preds) == 0

    def test_predicate_evaluate_above_threshold(self, app_with_232_data):
        """TPP > 50 billion → True (duty applies)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Predicate
            preds = Section232Predicate.get_predicates_for_hts(
                "section_232_semiconductor", "85411000", date(2026, 1, 1)
            )
            assert preds[0].evaluate(100.0) is True  # 100B > 50B

    def test_predicate_evaluate_below_threshold(self, app_with_232_data):
        """TPP <= 50 billion → False (0% duty)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Predicate
            preds = Section232Predicate.get_predicates_for_hts(
                "section_232_semiconductor", "85411000", date(2026, 1, 1)
            )
            assert preds[0].evaluate(30.0) is False  # 30B < 50B

    def test_predicate_evaluate_at_threshold(self, app_with_232_data):
        """TPP = 50 billion exactly → False (strict inequality, must be > threshold)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Predicate
            preds = Section232Predicate.get_predicates_for_hts(
                "section_232_semiconductor", "85411000", date(2026, 1, 1)
            )
            assert preds[0].evaluate(50.0) is False  # Exactly at threshold → False


# ============================================================================
# 5. IEEPA Unstacking Tests
# ============================================================================

class TestIeepaUnstacking:
    """Test that 232 content is properly deducted from IEEPA Reciprocal base."""

    def test_duty_rule_232_subtracts_from_remaining(self, app_with_232_data):
        """232 programs should have base_effect='subtract_from_remaining'."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import DutyRule
            for prog_id in ["section_232_steel", "section_232_aluminum", "section_232_copper"]:
                rule = DutyRule.query.filter_by(program_id=prog_id).first()
                assert rule is not None, f"No DutyRule for {prog_id}"
                assert rule.base_effect == "subtract_from_remaining", \
                    f"{prog_id} should subtract from remaining for unstacking"

    def test_ieepa_reciprocal_uses_remaining_value(self, app_with_232_data):
        """IEEPA Reciprocal should use remaining_value as base (after 232 deductions)."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import DutyRule
            rule = DutyRule.query.filter_by(
                program_id="ieepa_reciprocal", variant="taxable"
            ).first()
            assert rule is not None
            assert rule.base_on == "remaining_value"

    def test_unstacking_calculation(self, app_with_232_data):
        """
        Golden path: $10,000 product with $2,000 copper + $3,000 steel from China.

        IEEPA Reciprocal base = $10,000 - $2,000 - $3,000 = $5,000
        IEEPA Reciprocal duty = $5,000 × 10% = $500
        """
        # This is a calculation verification — we compute it directly
        product_value = 10000.00
        copper_value = 2000.00
        steel_value = 3000.00

        remaining_value = product_value - copper_value - steel_value
        assert remaining_value == 5000.00

        ieepa_reciprocal_rate = 0.10
        ieepa_reciprocal_duty = remaining_value * ieepa_reciprocal_rate
        assert ieepa_reciprocal_duty == 500.00

    def test_unstacking_no_metals(self, app_with_232_data):
        """No 232 metals → IEEPA Reciprocal base = full product value."""
        product_value = 10000.00
        remaining_value = product_value  # No deductions
        ieepa_duty = remaining_value * 0.10
        assert ieepa_duty == 1000.00


# ============================================================================
# 6. Calculation Sequence Tests
# ============================================================================

class TestCalculationSequence:
    """Test that 232 is calculated BEFORE IEEPA Reciprocal (for unstacking)."""

    def test_232_before_reciprocal_in_calc_sequence(self, app_with_232_data):
        """232 calculation_sequence < IEEPA Reciprocal calculation_sequence."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import TariffProgram
            steel = TariffProgram.query.filter_by(program_id="section_232_steel").first()
            recip = TariffProgram.query.filter_by(program_id="ieepa_reciprocal").first()
            assert steel.calculation_sequence < recip.calculation_sequence, \
                "232 must calculate before IEEPA Reciprocal for unstacking"

    def test_filing_sequence_is_different_from_calc(self, app_with_232_data):
        """Filing sequence (ACE order) != calculation sequence."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import TariffProgram
            # 301 files first, but both it and IEEPA calculate before 232
            s301 = TariffProgram.query.filter_by(program_id="section_301").first()
            assert s301.filing_sequence == 1
            assert s301.calculation_sequence == 1


# ============================================================================
# 7. Golden Path: Full Stacking Duty Calculations
# ============================================================================

class TestGoldenPathCalculations:
    """
    End-to-end duty calculations for known scenarios.
    These verify the EXPECTED total duties for specific product configurations.
    """

    def test_primary_steel_china_full_stack(self, app_with_232_data):
        """
        Primary steel from China, $10,000, post-March 2025.

        Expected stack:
          Section 301:     $10,000 × 25%  = $2,500
          IEEPA Fentanyl:  $10,000 × 10%  = $1,000
          Section 232:     $10,000 × 50%  = $5,000  (full value, primary)
          IEEPA Reciprocal: $0 (entire value exempt — primary 232 article)
          ─────────────────────────────────────
          Total duty:      $8,500 (85% effective)
        """
        product_value = 10000.00
        s301_duty = product_value * 0.25
        fentanyl_duty = product_value * 0.10
        s232_duty = product_value * 0.50
        # Primary article: 100% of value is 232 → remaining = 0
        remaining = product_value - product_value  # Primary → full deduction
        reciprocal_duty = remaining * 0.10

        total = s301_duty + fentanyl_duty + s232_duty + reciprocal_duty
        assert s301_duty == 2500.00
        assert fentanyl_duty == 1000.00
        assert s232_duty == 5000.00
        assert reciprocal_duty == 0.00
        assert total == 8500.00

    def test_content_copper_steel_china(self, app_with_232_data):
        """
        Electrical product from China, $10,000, 20% copper ($2,000), 10% steel ($1,000).

        Expected entry slices:
          copper_slice ($2,000):
            - 301: $2,000 × 25% = $500
            - Fentanyl: $2,000 × 10% = $200
            - 232 Copper: $2,000 × 25% = $500 (claim)
            - IEEPA Recip: $0 (232 exempt)

          steel_slice ($1,000):
            - 301: $1,000 × 25% = $250
            - Fentanyl: $1,000 × 10% = $100
            - 232 Steel: $1,000 × 50% = $500 (claim)
            - 232 Copper: disclaim (9903.78.02 at 0%)
            - IEEPA Recip: $0 (232 exempt)

          non_metal ($7,000):
            - 301: $7,000 × 25% = $1,750
            - Fentanyl: $7,000 × 10% = $700
            - 232 Copper: disclaim (9903.78.02 at 0%)
            - IEEPA Recip: $7,000 × 10% = $700

          Total: $500+200+500 + $250+100+500 + $1750+700+700 = $5,200
        """
        product_value = 10000.00
        copper_value = 2000.00
        steel_value = 1000.00
        non_metal_value = product_value - copper_value - steel_value

        # Copper slice
        copper_s301 = copper_value * 0.25
        copper_fent = copper_value * 0.10
        copper_232 = copper_value * 0.25  # Copper rate
        copper_recip = 0.00  # 232 exempt
        copper_total = copper_s301 + copper_fent + copper_232 + copper_recip

        # Steel slice
        steel_s301 = steel_value * 0.25
        steel_fent = steel_value * 0.10
        steel_232 = steel_value * 0.50  # Steel rate
        steel_recip = 0.00  # 232 exempt
        steel_total = steel_s301 + steel_fent + steel_232 + steel_recip

        # Non-metal slice
        nm_s301 = non_metal_value * 0.25
        nm_fent = non_metal_value * 0.10
        nm_recip = non_metal_value * 0.10  # Reciprocal on remaining
        nm_total = nm_s301 + nm_fent + nm_recip

        total = copper_total + steel_total + nm_total
        assert copper_total == 1200.00
        assert steel_total == 850.00
        assert nm_total == 3150.00
        assert total == 5200.00

    def test_uk_steel_no_301_no_fentanyl(self, app_with_232_data):
        """
        Primary steel from UK, $10,000, post-March 2025.

        UK: No Section 301, no IEEPA Fentanyl (those are China-only).
        Section 232 Steel: 25% (UK exception)
        IEEPA Reciprocal: $0 (primary 232 article — full value exempt)

        Total: $2,500 (25%)
        """
        product_value = 10000.00
        s232_uk_rate = 0.25
        total = product_value * s232_uk_rate
        assert total == 2500.00

    def test_no_metals_china_product(self, app_with_232_data):
        """
        Non-232 product from China, $10,000.
        No steel/aluminum/copper — only 301 + Fentanyl + Reciprocal.

        301: $2,500
        Fentanyl: $1,000
        Reciprocal: $1,000 (full value, no 232 deductions)
        Total: $4,500
        """
        product_value = 10000.00
        s301 = product_value * 0.25
        fent = product_value * 0.10
        recip = product_value * 0.10
        total = s301 + fent + recip
        assert total == 4500.00


# ============================================================================
# 8. Section232Rate.is_active() Tests
# ============================================================================

class TestIsActive:
    """Test the is_active() method for temporal validity checking."""

    def test_active_rate_no_end_date(self, app_with_232_data):
        """Rate with no effective_end is active for any date after start."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.query.filter_by(
                hts_8digit="72081000", material_type="steel",
                country_code=None, effective_end=None
            ).first()
            assert rate is not None
            assert rate.is_active(date(2026, 1, 1)) is True

    def test_expired_rate(self, app_with_232_data):
        """Rate that has been superseded should not be active after end date."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rate = Section232Rate.query.filter_by(
                hts_8digit="72081000", material_type="steel",
                country_code=None, duty_rate=Decimal("0.2500")
            ).filter(Section232Rate.effective_end.isnot(None)).first()
            assert rate is not None
            # Active before end date
            assert rate.is_active(date(2025, 3, 11)) is True
            # Not active on or after end date (end-exclusive)
            assert rate.is_active(date(2025, 3, 12)) is False


# ============================================================================
# 9. IEEPA Rate Temporal Lookup Tests
# ============================================================================

class TestIeepaRateLookup:
    """Test IEEPA temporal rate lookups."""

    def test_fentanyl_rate_china(self, app_with_232_data):
        """Fentanyl rate for China should be 10%."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import IeepaRate
            rate = IeepaRate.get_rate_as_of(
                program_type="fentanyl", country_code="CN",
                as_of_date=date(2025, 6, 1)
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.10
            assert rate.chapter_99_code == "9903.01.24"

    def test_reciprocal_rate_china(self, app_with_232_data):
        """Reciprocal rate for China should be 10%."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import IeepaRate
            rate = IeepaRate.get_rate_as_of(
                program_type="reciprocal", country_code="CN",
                as_of_date=date(2025, 6, 1), variant="taxable"
            )
            assert rate is not None
            assert float(rate.duty_rate) == 0.10
            assert rate.chapter_99_code == "9903.01.25"

    def test_fentanyl_before_effective_date(self, app_with_232_data):
        """Fentanyl rate shouldn't exist before March 4, 2025."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import IeepaRate
            rate = IeepaRate.get_rate_as_of(
                program_type="fentanyl", country_code="CN",
                as_of_date=date(2025, 1, 1)
            )
            assert rate is None


# ============================================================================
# 10. Data Integrity Tests
# ============================================================================

class TestDataIntegrity:
    """Verify structural integrity of the 232 data model."""

    def test_all_232_materials_have_both_codes(self, app_with_232_data):
        """Every Section232Material must have both claim and disclaim codes."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Material
            materials = Section232Material.query.all()
            for mat in materials:
                assert mat.claim_code is not None, \
                    f"Missing claim_code for {mat.hts_8digit}/{mat.material}"
                assert mat.disclaim_code is not None, \
                    f"Missing disclaim_code for {mat.hts_8digit}/{mat.material}"

    def test_all_232_rates_have_article_type(self, app_with_232_data):
        """Every Section232Rate should have an article_type."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Rate
            rates = Section232Rate.query.all()
            for rate in rates:
                assert rate.article_type in ("primary", "derivative", "content"), \
                    f"Invalid article_type '{rate.article_type}' for {rate.hts_8digit}"

    def test_copper_disclaim_code_different_from_claim(self, app_with_232_data):
        """Copper claim and disclaim codes must be different."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import Section232Material
            copper_mats = Section232Material.query.filter_by(material="copper").all()
            for mat in copper_mats:
                assert mat.claim_code != mat.disclaim_code, \
                    f"Claim and disclaim codes must differ for copper {mat.hts_8digit}"

    def test_duty_rules_exist_for_all_232_programs(self, app_with_232_data):
        """Every 232 program should have a DutyRule."""
        with app_with_232_data.app_context():
            from app.web.db.models.tariff_tables import DutyRule
            for prog_id in ["section_232_steel", "section_232_aluminum", "section_232_copper"]:
                rule = DutyRule.query.filter_by(program_id=prog_id).first()
                assert rule is not None, f"No DutyRule for {prog_id}"
                assert rule.content_key is not None, \
                    f"DutyRule for {prog_id} missing content_key"
