"""
Role Precedence Tests

Verifies that Section 301 exclusions (role='exclude')
always take precedence over impose rates (role='impose').

Per CBP guidance: When an active exclusion exists for an HTS code,
the exclusion rate applies (typically 0%) rather than the impose rate.

These tests verify:
1. Exclusions beat impose rates for the same HTS code
2. Exclusions respect their effective date windows
3. Expired exclusions fall back to impose rates
4. The SQL ORDER BY case() expression works correctly
"""

import pytest
import sys
import os
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRolePrecedence:
    """Test exclusion vs impose precedence in Section301Rate."""

    def test_exclude_beats_impose_same_hts(self, app):
        """
        Exclusion (0%) should be returned over impose (25%) for same HTS.

        Setup:
        - HTS 85411010 has impose rate of 25% (effective 2024-01-01)
        - HTS 85411010 has exclusion rate of 0% (effective 2024-06-01)

        Expected:
        - Query as of 2024-07-01 should return exclusion (0%)
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "85411010"
            query_date = date(2024, 7, 1)

            # Create impose rate (25%)
            impose_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.25"),
                effective_start=date(2024, 1, 1),
                effective_end=None,
                role="impose",
                list_name="test_list",
            )
            db.session.add(impose_rate)

            # Create exclusion rate (0%)
            exclude_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.66",
                duty_rate=Decimal("0.00"),
                effective_start=date(2024, 6, 1),
                effective_end=None,
                role="exclude",
                list_name="test_exclusion",
            )
            db.session.add(exclude_rate)
            db.session.commit()

            # Query should return exclusion
            result = Section301Rate.get_rate_as_of(test_hts, query_date)

            assert result is not None, "Should find a rate"
            assert result.role == "exclude", f"Expected exclusion, got {result.role}"
            assert float(result.duty_rate) == 0.0, f"Expected 0%, got {result.duty_rate}"

    def test_impose_when_no_exclusion(self, app):
        """
        Impose rate returned when no active exclusion exists.

        Setup:
        - HTS 84181000 has impose rate of 50% (effective 2024-01-01)
        - No exclusion exists

        Expected:
        - Query returns impose rate (50%)
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "84181000"
            query_date = date(2024, 7, 1)

            # Create impose rate only (50%)
            impose_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.91.02",
                duty_rate=Decimal("0.50"),
                effective_start=date(2024, 1, 1),
                effective_end=None,
                role="impose",
                list_name="strategic_medical",
            )
            db.session.add(impose_rate)
            db.session.commit()

            # Query should return impose since no exclusion
            result = Section301Rate.get_rate_as_of(test_hts, query_date)

            assert result is not None, "Should find a rate"
            assert result.role == "impose", f"Expected impose, got {result.role}"
            assert float(result.duty_rate) == 0.50, f"Expected 50%, got {result.duty_rate}"

    def test_exclusion_respects_effective_dates(self, app):
        """
        Exclusion only applies within its effective time window.

        Setup:
        - HTS 90183100 has impose rate of 100% (effective 2024-01-01)
        - HTS 90183100 has exclusion of 0% (effective 2025-01-01, future)

        Expected:
        - Query as of 2024-07-01 returns impose (exclusion not yet active)
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "90183100"
            query_date = date(2024, 7, 1)  # Before exclusion is active

            # Create impose rate (100%)
            impose_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.91.02",
                duty_rate=Decimal("1.00"),
                effective_start=date(2024, 1, 1),
                effective_end=None,
                role="impose",
                list_name="strategic_medical",
            )
            db.session.add(impose_rate)

            # Create future exclusion (not yet active)
            future_exclude = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.66",
                duty_rate=Decimal("0.00"),
                effective_start=date(2025, 1, 1),  # Future date
                effective_end=None,
                role="exclude",
                list_name="future_exclusion",
            )
            db.session.add(future_exclude)
            db.session.commit()

            # Query as of 2024-07-01 should return impose (exclusion not active yet)
            result = Section301Rate.get_rate_as_of(test_hts, query_date)

            assert result is not None, "Should find a rate"
            assert result.role == "impose", f"Expected impose, got {result.role}"
            assert float(result.duty_rate) == 1.00, f"Expected 100%, got {result.duty_rate}"

    def test_expired_exclusion_falls_back_to_impose(self, app):
        """
        After exclusion expires, impose rate applies.

        Setup:
        - HTS 39269097 has impose rate of 25% (effective 2024-01-01)
        - HTS 39269097 had exclusion of 0% (effective 2024-01-01 to 2024-06-01)

        Expected:
        - Query as of 2024-07-01 returns impose (exclusion expired)
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "39269097"
            query_date = date(2024, 7, 1)  # After exclusion expires

            # Create impose rate (25%)
            impose_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.25"),
                effective_start=date(2024, 1, 1),
                effective_end=None,
                role="impose",
                list_name="list_3",
            )
            db.session.add(impose_rate)

            # Create expired exclusion
            expired_exclude = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.66",
                duty_rate=Decimal("0.00"),
                effective_start=date(2024, 1, 1),
                effective_end=date(2024, 6, 1),  # Expired
                role="exclude",
                list_name="expired_exclusion",
            )
            db.session.add(expired_exclude)
            db.session.commit()

            # Query as of 2024-07-01 should return impose (exclusion expired)
            result = Section301Rate.get_rate_as_of(test_hts, query_date)

            assert result is not None, "Should find a rate"
            assert result.role == "impose", f"Expected impose (exclusion expired), got {result.role}"
            assert float(result.duty_rate) == 0.25, f"Expected 25%, got {result.duty_rate}"

    def test_query_returns_most_recent_impose_when_multiple(self, app):
        """
        When multiple impose rates exist, return most recent effective_start.

        Setup:
        - HTS 63079098 has impose at 25% (effective 2024-01-01)
        - HTS 63079098 has impose at 50% (effective 2024-09-01)

        Expected:
        - Query as of 2024-10-01 returns 50% (most recent)
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "63079098"
            query_date = date(2024, 10, 1)

            # Old impose rate (25%)
            old_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.25"),
                effective_start=date(2024, 1, 1),
                effective_end=date(2024, 9, 1),  # Superseded
                role="impose",
                list_name="list_3",
            )
            db.session.add(old_rate)

            # New impose rate (50%)
            new_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.91.07",
                duty_rate=Decimal("0.50"),
                effective_start=date(2024, 9, 1),
                effective_end=None,
                role="impose",
                list_name="facemasks",
            )
            db.session.add(new_rate)
            db.session.commit()

            # Query should return newer rate
            result = Section301Rate.get_rate_as_of(test_hts, query_date)

            assert result is not None, "Should find a rate"
            assert float(result.duty_rate) == 0.50, f"Expected 50%, got {result.duty_rate}"
            assert result.chapter_99_code == "9903.91.07"

    def test_no_rate_found_returns_none(self, app):
        """
        Query for HTS code with no rates returns None.
        """
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            # Query for non-existent HTS
            result = Section301Rate.get_rate_as_of("00000000", date(2024, 7, 1))
            assert result is None, "Should return None for unknown HTS"


class TestRolePrecedenceEdgeCases:
    """Edge cases for role precedence."""

    def test_exclusion_starts_same_day_as_impose(self, app):
        """
        When exclusion and impose start on the same day, exclusion wins.
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "85423900"
            same_date = date(2024, 1, 1)

            # Impose and exclude start same day
            impose_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.03",
                duty_rate=Decimal("0.25"),
                effective_start=same_date,
                effective_end=None,
                role="impose",
            )
            exclude_rate = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.66",
                duty_rate=Decimal("0.00"),
                effective_start=same_date,
                effective_end=None,
                role="exclude",
            )
            db.session.add_all([impose_rate, exclude_rate])
            db.session.commit()

            result = Section301Rate.get_rate_as_of(test_hts, same_date)

            assert result is not None
            assert result.role == "exclude", "Exclusion should win when same effective date"

    def test_multiple_exclusions_returns_most_recent(self, app):
        """
        When multiple active exclusions exist, return most recent.
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section301Rate

        with app.app_context():
            test_hts = "85414200"
            query_date = date(2024, 10, 1)

            # Older exclusion
            old_exclude = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.60",
                duty_rate=Decimal("0.00"),
                effective_start=date(2024, 1, 1),
                effective_end=None,
                role="exclude",
            )
            # Newer exclusion
            new_exclude = Section301Rate(
                hts_8digit=test_hts,
                chapter_99_code="9903.88.66",
                duty_rate=Decimal("0.00"),
                effective_start=date(2024, 6, 1),
                effective_end=None,
                role="exclude",
            )
            db.session.add_all([old_exclude, new_exclude])
            db.session.commit()

            result = Section301Rate.get_rate_as_of(test_hts, query_date)

            assert result is not None
            assert result.chapter_99_code == "9903.88.66", "Should return most recent exclusion"
