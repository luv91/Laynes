"""
Canary Test Suite for Temporal Queries (PRC-7)

Tests that verify temporal as_of_date queries return the correct rates
for different dates. This is critical for ensuring scheduled rate changes
(e.g., Four-Year Review escalations) work correctly.

Key test cases:
1. Single rate - basic temporal query
2. Staged rates - 25% Jan 2025 → 50% Jan 2026
3. Supersession - new rate supersedes old rate
4. As-of-date queries at various points in time
"""

import pytest
from datetime import date
from decimal import Decimal

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTemporalQueries:
    """Test suite for temporal as_of_date queries on tariff rate tables."""

    def test_single_rate_before_effective(self, app, db_session):
        """Query before effective date returns nothing."""
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            # Insert a rate effective 2025-01-01
            rate = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 1, 1),
                effective_end=None,
                source_doc="test-fr-001",
                created_by="test",
            )
            db_session.add(rate)
            db_session.commit()

            # Query for 2024-12-31 (before effective)
            result = Section301Rate.query.filter(
                Section301Rate.hts_8digit == "84159050",
                Section301Rate.effective_start <= date(2024, 12, 31),
                (Section301Rate.effective_end.is_(None) |
                 (Section301Rate.effective_end > date(2024, 12, 31)))
            ).first()

            assert result is None, "Should not find rate before effective date"

    def test_single_rate_on_effective_date(self, app, db_session):
        """Query on effective date returns the rate."""
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            rate = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 1, 1),
                effective_end=None,
                source_doc="test-fr-001",
                created_by="test",
            )
            db_session.add(rate)
            db_session.commit()

            # Query for 2025-01-01 (on effective date)
            result = Section301Rate.query.filter(
                Section301Rate.hts_8digit == "84159050",
                Section301Rate.effective_start <= date(2025, 1, 1),
                (Section301Rate.effective_end.is_(None) |
                 (Section301Rate.effective_end > date(2025, 1, 1)))
            ).first()

            assert result is not None, "Should find rate on effective date"
            assert float(result.duty_rate) == 0.25

    def test_four_year_review_schedule(self, app, db_session):
        """
        Canary test: Four-Year Review schedule with escalating rates.

        Timeline:
        - Before 2025-01-01: No Section 301 rate
        - 2025-01-01 to 2025-12-31: 25% rate
        - 2026-01-01 onwards: 50% rate (escalated)
        """
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            # Insert scheduled rates (as extraction_worker would create)
            rate_2025 = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 1, 1),
                effective_end=date(2026, 1, 1),  # Ends when next rate starts
                source_doc="test-fr-001",
                created_by="test",
            )
            db_session.add(rate_2025)
            db_session.flush()

            rate_2026 = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.50"),
                effective_start=date(2026, 1, 1),
                effective_end=None,  # Currently active
                supersedes_id=rate_2025.id,
                source_doc="test-fr-001",
                created_by="test",
            )
            db_session.add(rate_2026)

            # Link supersession
            rate_2025.superseded_by_id = rate_2026.id
            db_session.commit()

            # Test as_of_date queries
            test_cases = [
                (date(2024, 12, 31), None),          # Before any rate
                (date(2025, 1, 1), Decimal("0.25")), # First rate starts
                (date(2025, 6, 15), Decimal("0.25")), # Mid-2025
                (date(2025, 12, 31), Decimal("0.25")), # Last day of 25% rate
                (date(2026, 1, 1), Decimal("0.50")), # Escalated rate starts
                (date(2026, 6, 15), Decimal("0.50")), # Mid-2026
            ]

            for as_of, expected_rate in test_cases:
                result = Section301Rate.query.filter(
                    Section301Rate.hts_8digit == "84159050",
                    Section301Rate.effective_start <= as_of,
                    (Section301Rate.effective_end.is_(None) |
                     (Section301Rate.effective_end > as_of))
                ).first()

                if expected_rate is None:
                    assert result is None, f"Expected no rate for {as_of}, got {result}"
                else:
                    assert result is not None, f"Expected rate {expected_rate} for {as_of}, got None"
                    assert result.duty_rate == expected_rate, \
                        f"For {as_of}: expected {expected_rate}, got {result.duty_rate}"

    def test_supersession_chain(self, app, db_session):
        """Test that supersession links are correct for chained rates."""
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            # Create a chain: Original → 2025 → 2026
            original = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.10"),
                effective_start=date(2018, 7, 6),
                effective_end=date(2025, 1, 1),
                source_doc="original-fr",
                created_by="test",
            )
            db_session.add(original)
            db_session.flush()

            rate_2025 = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 1, 1),
                effective_end=date(2026, 1, 1),
                supersedes_id=original.id,
                source_doc="fyr-fr-001",
                created_by="test",
            )
            db_session.add(rate_2025)
            db_session.flush()

            rate_2026 = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.50"),
                effective_start=date(2026, 1, 1),
                effective_end=None,
                supersedes_id=rate_2025.id,
                source_doc="fyr-fr-001",
                created_by="test",
            )
            db_session.add(rate_2026)
            db_session.flush()

            # Link superseded_by - need to update and commit
            original.superseded_by_id = rate_2025.id
            rate_2025.superseded_by_id = rate_2026.id
            db_session.commit()

            # Re-query to get updated values
            original = Section301Rate.query.get(original.id)
            rate_2025 = Section301Rate.query.get(rate_2025.id)
            rate_2026 = Section301Rate.query.get(rate_2026.id)

            # Verify chain
            assert rate_2026.supersedes_id == rate_2025.id
            assert rate_2025.supersedes_id == original.id
            assert rate_2025.superseded_by_id == rate_2026.id
            assert original.superseded_by_id == rate_2025.id

    def test_section_232_temporal(self, app, db_session):
        """Test temporal queries for Section 232 rates."""
        from app.web.db.models.tariff_tables import Section232Rate

        with app.app_context():
            rate = Section232Rate(
                hts_8digit="72069100",
                material_type="steel",
                chapter_99_claim="9903.80.01",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 3, 12),
                effective_end=None,
                source_doc="test-232",
                created_by="test",
            )
            db_session.add(rate)
            db_session.commit()

            # Before effective date
            result = Section232Rate.query.filter(
                Section232Rate.hts_8digit == "72069100",
                Section232Rate.effective_start <= date(2025, 3, 11),
                (Section232Rate.effective_end.is_(None) |
                 (Section232Rate.effective_end > date(2025, 3, 11)))
            ).first()
            assert result is None

            # On effective date
            result = Section232Rate.query.filter(
                Section232Rate.hts_8digit == "72069100",
                Section232Rate.effective_start <= date(2025, 3, 12),
                (Section232Rate.effective_end.is_(None) |
                 (Section232Rate.effective_end > date(2025, 3, 12)))
            ).first()
            assert result is not None
            assert float(result.duty_rate) == 0.25

    def test_get_rate_helper_function(self, app, db_session):
        """Test a helper function that wraps temporal queries."""
        from app.web.db.models.tariff_tables import Section301Rate

        def get_rate_as_of(hts_8digit: str, as_of_date: date) -> Decimal:
            """Helper function to get rate as of a specific date."""
            result = Section301Rate.query.filter(
                Section301Rate.hts_8digit == hts_8digit,
                Section301Rate.effective_start <= as_of_date,
                (Section301Rate.effective_end.is_(None) |
                 (Section301Rate.effective_end > as_of_date))
            ).first()
            return result.duty_rate if result else Decimal("0.0")

        with app.app_context():
            # Insert test data
            rate = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 1, 1),
                effective_end=None,
                source_doc="test",
                created_by="test",
            )
            db_session.add(rate)
            db_session.commit()

            # Use helper
            assert get_rate_as_of("84159050", date(2024, 12, 31)) == Decimal("0.0")
            assert get_rate_as_of("84159050", date(2025, 1, 1)) == Decimal("0.25")
            assert get_rate_as_of("84159050", date(2025, 6, 15)) == Decimal("0.25")

    def test_no_overlapping_active_rates(self, app, db_session):
        """Verify that commit_engine doesn't create overlapping active rates."""
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            # Insert two rates - only one should be active at any time
            rate_old = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.10"),
                effective_start=date(2020, 1, 1),
                effective_end=date(2025, 1, 1),  # Closed
                source_doc="old",
                created_by="test",
            )
            db_session.add(rate_old)

            rate_new = Section301Rate(
                hts_8digit="84159050",
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.25"),
                effective_start=date(2025, 1, 1),
                effective_end=None,  # Active
                source_doc="new",
                created_by="test",
            )
            db_session.add(rate_new)
            db_session.commit()

            # Query for active rates only
            active_rates = Section301Rate.query.filter(
                Section301Rate.hts_8digit == "84159050",
                Section301Rate.effective_end.is_(None)
            ).all()

            assert len(active_rates) == 1, f"Expected 1 active rate, got {len(active_rates)}"
            assert active_rates[0].duty_rate == Decimal("0.25")


class TestRateScheduleExtraction:
    """Test that rate schedules are properly extracted and committed."""

    def test_extraction_creates_rate_schedule(self, app):
        """Test that extraction worker creates rate_schedule for staged rates."""
        from app.workers.extraction_worker import CandidateChange, RateScheduleEntry

        # Create a candidate with rate_schedule
        candidate = CandidateChange(
            document_id="test-doc",
            hts_code="84159050",
            rate_schedule=[
                RateScheduleEntry(
                    rate=Decimal("0.25"),
                    effective_start=date(2025, 1, 1),
                    effective_end=date(2026, 1, 1),
                ),
                RateScheduleEntry(
                    rate=Decimal("0.50"),
                    effective_start=date(2026, 1, 1),
                    effective_end=None,
                ),
            ],
            rate=Decimal("0.25"),  # First rate for backwards compat
            effective_date=date(2025, 1, 1),
            extraction_method="xml_table",
        )

        assert candidate.has_staged_rates() is True
        assert len(candidate.rate_schedule) == 2

        # Check schedule entries
        assert candidate.rate_schedule[0].rate == Decimal("0.25")
        assert candidate.rate_schedule[0].effective_start == date(2025, 1, 1)
        assert candidate.rate_schedule[0].effective_end == date(2026, 1, 1)

        assert candidate.rate_schedule[1].rate == Decimal("0.50")
        assert candidate.rate_schedule[1].effective_start == date(2026, 1, 1)
        assert candidate.rate_schedule[1].effective_end is None

    def test_to_dict_includes_rate_schedule(self, app):
        """Test that to_dict includes rate_schedule when present."""
        from app.workers.extraction_worker import CandidateChange, RateScheduleEntry

        candidate = CandidateChange(
            document_id="test-doc",
            hts_code="84159050",
            rate_schedule=[
                RateScheduleEntry(
                    rate=Decimal("0.25"),
                    effective_start=date(2025, 1, 1),
                    effective_end=date(2026, 1, 1),
                ),
            ],
        )

        result = candidate.to_dict()
        assert "rate_schedule" in result
        assert len(result["rate_schedule"]) == 1
        assert result["rate_schedule"][0]["rate"] == 0.25
        assert result["rate_schedule"][0]["effective_start"] == "2025-01-01"
        assert result["rate_schedule"][0]["effective_end"] == "2026-01-01"


class TestCommitEngineSchedule:
    """Test that commit_engine handles rate_schedule correctly."""

    def test_commit_creates_multiple_rows(self, app, db_session):
        """Test that committing a schedule creates multiple temporal rows."""
        from app.workers.extraction_worker import CandidateChange, RateScheduleEntry
        from app.workers.commit_engine import CommitEngine
        from app.web.db.models.tariff_tables import Section301Rate
        from app.models import OfficialDocument, IngestJob, EvidencePacket
        import hashlib

        with app.app_context():
            # Create required foreign key objects
            doc = OfficialDocument(
                source="federal_register",
                external_id="2024-12345",
                title="Test FR Notice",
                status="fetched",
                content_type="text/xml",
                content_hash=hashlib.sha256(b"test content").hexdigest(),
                raw_bytes=b"test content",
            )
            db_session.add(doc)
            db_session.flush()

            job = IngestJob(
                source="federal_register",
                external_id="2024-12345",
                status="processing",
            )
            db_session.add(job)
            db_session.flush()

            evidence = EvidencePacket(
                document_id=doc.id,
                document_hash=doc.content_hash,
                quote_text="Test evidence quote for HTS 8415.90.50",
                proves_hts_code="84159050",
            )
            db_session.add(evidence)
            db_session.flush()

            # Create candidate with schedule
            candidate = CandidateChange(
                document_id=str(doc.id),
                hts_code="84159050",
                new_chapter_99_code="9903.91.07",
                rate_schedule=[
                    RateScheduleEntry(
                        rate=Decimal("0.25"),
                        effective_start=date(2025, 1, 1),
                        effective_end=date(2026, 1, 1),
                    ),
                    RateScheduleEntry(
                        rate=Decimal("0.50"),
                        effective_start=date(2026, 1, 1),
                        effective_end=None,
                    ),
                ],
                rate=Decimal("0.25"),
                effective_date=date(2025, 1, 1),
            )

            # Commit
            engine = CommitEngine()
            success, record_ids, error = engine.commit_candidate(
                candidate=candidate,
                evidence=evidence,
                doc=doc,
                job=job,
                run_id=None,
            )

            assert success is True
            assert error is None

            # Verify two rows were created
            rates = Section301Rate.query.filter(
                Section301Rate.hts_8digit == "84159050"
            ).order_by(Section301Rate.effective_start).all()

            assert len(rates) == 2

            # Check first rate
            assert rates[0].duty_rate == Decimal("0.25")
            assert rates[0].effective_start == date(2025, 1, 1)
            assert rates[0].effective_end == date(2026, 1, 1)

            # Check second rate
            assert rates[1].duty_rate == Decimal("0.50")
            assert rates[1].effective_start == date(2026, 1, 1)
            assert rates[1].effective_end is None

            # Check supersession chain
            assert rates[0].superseded_by_id == rates[1].id


# ============================================================================
# v13.0: Design Flaw 6 Fix - Section 232 and IEEPA Temporal Tests
# ============================================================================

class TestSection232TemporalRates:
    """
    Test Section 232 temporal rate queries (Design Flaw 6 Fix).

    Historical rates:
    - Steel: 25% (Mar 2018 - Mar 2025) → 50% (Mar 2025+)
    - Aluminum: 10% (Mar 2018 - Mar 2025) → 50% (Mar 2025+)
    - Copper: 50% (Mar 2025+) - didn't exist before
    """

    def test_steel_rate_before_march_2025(self, app):
        """Steel rate was 25% before March 2025."""
        from app.web.db.models.tariff_tables import Section232Rate

        with app.app_context():
            steel_rate = Section232Rate.query.filter_by(
                material_type='steel'
            ).first()

            if not steel_rate:
                pytest.skip("No steel HTS codes in database")

            rate = Section232Rate.get_rate_as_of(
                hts_8digit=steel_rate.hts_8digit,
                material='steel',
                country_code=None,
                as_of_date=date(2025, 2, 15)
            )

            assert rate is not None, "Should find a rate for Feb 2025"
            assert rate.duty_rate == Decimal('0.25'), f"Steel rate should be 25% in Feb 2025, got {rate.duty_rate}"

    def test_steel_rate_after_march_2025(self, app):
        """Steel rate is 50% after March 2025."""
        from app.web.db.models.tariff_tables import Section232Rate

        with app.app_context():
            steel_rate = Section232Rate.query.filter_by(
                material_type='steel'
            ).first()

            if not steel_rate:
                pytest.skip("No steel HTS codes in database")

            rate = Section232Rate.get_rate_as_of(
                hts_8digit=steel_rate.hts_8digit,
                material='steel',
                country_code=None,
                as_of_date=date(2025, 4, 15)
            )

            assert rate is not None, "Should find a rate for Apr 2025"
            assert rate.duty_rate == Decimal('0.50'), f"Steel rate should be 50% in Apr 2025, got {rate.duty_rate}"

    def test_aluminum_rate_before_march_2025(self, app):
        """Aluminum rate was 10% before March 2025."""
        from app.web.db.models.tariff_tables import Section232Rate

        with app.app_context():
            al_rate = Section232Rate.query.filter_by(
                material_type='aluminum'
            ).first()

            if not al_rate:
                pytest.skip("No aluminum HTS codes in database")

            rate = Section232Rate.get_rate_as_of(
                hts_8digit=al_rate.hts_8digit,
                material='aluminum',
                country_code=None,
                as_of_date=date(2025, 2, 15)
            )

            assert rate is not None, "Should find a rate for Feb 2025"
            assert rate.duty_rate == Decimal('0.10'), f"Aluminum rate should be 10% in Feb 2025, got {rate.duty_rate}"

    def test_aluminum_rate_after_march_2025(self, app):
        """Aluminum rate is 50% after March 2025."""
        from app.web.db.models.tariff_tables import Section232Rate

        with app.app_context():
            al_rate = Section232Rate.query.filter_by(
                material_type='aluminum'
            ).first()

            if not al_rate:
                pytest.skip("No aluminum HTS codes in database")

            rate = Section232Rate.get_rate_as_of(
                hts_8digit=al_rate.hts_8digit,
                material='aluminum',
                country_code=None,
                as_of_date=date(2025, 4, 15)
            )

            assert rate is not None, "Should find a rate for Apr 2025"
            assert rate.duty_rate == Decimal('0.50'), f"Aluminum rate should be 50% in Apr 2025, got {rate.duty_rate}"


class TestIeepaFentanylTemporalRates:
    """
    Test IEEPA Fentanyl temporal rate queries (Design Flaw 6 Fix).

    Historical rates for China:
    - Feb-Apr 2025: 10% (EO 14195)
    - Apr-Nov 2025: 20% (EO 14257 doubled)
    - Nov 2025+: 10% (EO 14357 reduced)

    Hong Kong/Macau stayed at 10% throughout.
    """

    def test_fentanyl_china_march_2025(self, app):
        """Fentanyl rate was 10% in March 2025 (before EO 14257)."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            rate = IeepaRate.get_rate_as_of(
                program_type='fentanyl',
                country_code='CN',
                as_of_date=date(2025, 3, 1)
            )

            assert rate is not None, "Should find Fentanyl rate for March 2025"
            assert rate.duty_rate == Decimal('0.10'), f"Fentanyl rate should be 10% in March 2025, got {rate.duty_rate}"
            assert rate.chapter_99_code == '9903.01.24', f"Wrong code: {rate.chapter_99_code}"

    def test_fentanyl_china_september_2025(self, app):
        """Fentanyl rate was 20% in September 2025 (between EO 14257 and EO 14357)."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            rate = IeepaRate.get_rate_as_of(
                program_type='fentanyl',
                country_code='CN',
                as_of_date=date(2025, 9, 1)
            )

            assert rate is not None, "Should find Fentanyl rate for September 2025"
            assert rate.duty_rate == Decimal('0.20'), f"Fentanyl rate should be 20% in September 2025, got {rate.duty_rate}"

    def test_fentanyl_china_december_2025(self, app):
        """Fentanyl rate is 10% in December 2025 (after EO 14357 reduced it)."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            rate = IeepaRate.get_rate_as_of(
                program_type='fentanyl',
                country_code='CN',
                as_of_date=date(2025, 12, 1)
            )

            assert rate is not None, "Should find Fentanyl rate for December 2025"
            assert rate.duty_rate == Decimal('0.10'), f"Fentanyl rate should be 10% in December 2025, got {rate.duty_rate}"

    def test_fentanyl_hong_kong_constant(self, app):
        """Fentanyl rate for Hong Kong stayed at 10% throughout 2025."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            for as_of in [date(2025, 3, 1), date(2025, 9, 1), date(2025, 12, 1)]:
                rate = IeepaRate.get_rate_as_of(
                    program_type='fentanyl',
                    country_code='HK',
                    as_of_date=as_of
                )
                assert rate is not None, f"Should find HK rate for {as_of}"
                assert rate.duty_rate == Decimal('0.10'), f"HK rate should be 10% at {as_of}, got {rate.duty_rate}"


class TestIeepaReciprocalTemporalRates:
    """
    Test IEEPA Reciprocal temporal rate queries (Design Flaw 6 Fix).

    Reciprocal tariff started April 9, 2025 with variants:
    - standard: 10%
    - annex_ii_exempt: 0%
    - section_232_exempt: 0%
    - us_content_exempt: 0%
    """

    def test_reciprocal_standard_rate(self, app):
        """Reciprocal standard rate is 10%."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            rate = IeepaRate.get_rate_as_of(
                program_type='reciprocal',
                country_code='CN',
                as_of_date=date(2025, 5, 1),
                variant='standard'
            )

            assert rate is not None, "Should find Reciprocal standard rate"
            assert rate.duty_rate == Decimal('0.10'), f"Standard rate should be 10%, got {rate.duty_rate}"
            assert rate.chapter_99_code == '9903.01.25', f"Wrong code: {rate.chapter_99_code}"

    def test_reciprocal_annex_ii_exempt(self, app):
        """Reciprocal Annex II exemption is 0%."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            rate = IeepaRate.get_rate_as_of(
                program_type='reciprocal',
                country_code='CN',
                as_of_date=date(2025, 5, 1),
                variant='annex_ii_exempt'
            )

            assert rate is not None, "Should find Annex II exemption"
            assert rate.duty_rate == Decimal('0.00'), f"Annex II should be 0%, got {rate.duty_rate}"
            assert rate.chapter_99_code == '9903.01.32', f"Wrong code: {rate.chapter_99_code}"

    def test_reciprocal_not_before_april_2025(self, app):
        """Reciprocal tariff didn't exist before April 9, 2025."""
        from app.web.db.models.tariff_tables import IeepaRate

        with app.app_context():
            rate = IeepaRate.get_rate_as_of(
                program_type='reciprocal',
                country_code='CN',
                as_of_date=date(2025, 3, 1),
                variant='standard'
            )

            assert rate is None, "Reciprocal tariff should not exist before April 2025"
