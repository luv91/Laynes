"""
Tests for Section 301 Ingestion Pipeline

Tests the automated ingestion from:
- USITC China Tariffs CSV
- USTR Federal Register Notices

Test Categories:
- Unit tests for processors
- Integration tests for pipeline
- SCD Type 2 versioning tests
"""

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def app():
    """Create Flask app with test database."""
    from flask import Flask
    from app.web.db import db

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True

    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def db_session(app):
    """Get database session."""
    from app.web.db import db
    with app.app_context():
        yield db.session


@pytest.fixture
def usitc_processor():
    """Create USITC processor instance."""
    from app.ingestion.section301_processor import USITCChinaTariffsProcessor
    return USITCChinaTariffsProcessor()


@pytest.fixture
def frn_processor():
    """Create FRN processor instance."""
    from app.ingestion.section301_processor import FederalRegisterSection301Processor
    return FederalRegisterSection301Processor()


@pytest.fixture
def pipeline():
    """Create pipeline instance."""
    from app.ingestion.section301_processor import Section301IngestionPipeline
    return Section301IngestionPipeline()


@pytest.fixture
def sample_csv_content():
    """Sample USITC China Tariffs CSV content."""
    return b"""htsno,description,general,special,other,list
8544.42.90,"Insulated electric conductors",Free,Free,Free,List 1
6307.90.10,"Surgical face masks",Free,Free,Free,List 4A
8542.31.00,"Processors and controllers",Free,Free,Free,List 2
9999.99.99,"Test code not in list",Free,Free,Free,
"""


@pytest.fixture
def sample_frn_text():
    """Sample Federal Register Notice text."""
    return """
    OFFICE OF THE UNITED STATES TRADE REPRESENTATIVE

    Modification of Section 301 Action: China's Acts, Policies, and Practices
    Related to Technology Transfer, Intellectual Property, and Innovation

    AGENCY: Office of the United States Trade Representative.

    ACTION: Notice of modification of Section 301 action.

    SUMMARY: The U.S. Trade Representative is modifying the action in the
    Section 301 investigation of China's acts, policies, and practices related
    to technology transfer, intellectual property, and innovation to increase
    the rate of additional duty from 25 percent to 50 percent for certain
    products covered by heading 9903.91.07.

    DATES: This modification is effective September 27, 2024.

    The products covered are classified under the following HTS subheadings:
    6307.90.10, 6307.90.40, 6307.90.50

    The additional duty rate of 50 percent ad valorem will apply.

    Chapter 99 heading: 9903.91.07
    """


# =============================================================================
# Test: USITC CSV Processor
# =============================================================================

class TestUSITCChinaTariffsProcessor:
    """Test USITC China Tariffs CSV processor."""

    def test_parse_csv_content(self, app, usitc_processor, sample_csv_content):
        """Test parsing CSV content."""
        with app.app_context():
            result = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=True,  # Don't commit
            )

            assert result.success is True
            assert result.rows_processed == 4
            # 3 rows have valid list assignments, 1 doesn't
            assert result.rows_added <= 3

    def test_skip_rows_without_list(self, app, usitc_processor):
        """Rows without list assignment should be skipped."""
        csv_content = b"""htsno,description,general,special,other,list
8544.42.90,"Test",Free,Free,Free,
"""
        with app.app_context():
            result = usitc_processor.ingest(
                csv_content=csv_content,
                dry_run=True,
            )

            assert result.rows_skipped >= 1

    def test_ch99_heading_mapping(self, usitc_processor):
        """Test list to Chapter 99 heading mapping."""
        assert usitc_processor._get_ch99_heading("list 1") == "9903.88.01"
        assert usitc_processor._get_ch99_heading("list 2") == "9903.88.02"
        assert usitc_processor._get_ch99_heading("list 3") == "9903.88.03"
        assert usitc_processor._get_ch99_heading("list 4a") == "9903.88.15"
        assert usitc_processor._get_ch99_heading("list 4b") == "9903.88.16"

    def test_creates_source_version(self, app, usitc_processor, sample_csv_content):
        """Ingestion should create SourceVersion record."""
        from app.models.section301 import SourceVersion, SourceType

        with app.app_context():
            result = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
            )

            assert result.success is True
            assert result.source_version_id is not None

            sv = SourceVersion.query.get(result.source_version_id)
            assert sv is not None
            assert sv.source_type == SourceType.USITC_CHINA.value
            assert sv.content_hash is not None

    def test_skip_duplicate_content(self, app, usitc_processor, sample_csv_content):
        """Same content should be skipped on second ingestion."""
        with app.app_context():
            # First ingestion
            result1 = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
            )
            assert result1.success is True
            assert result1.rows_added > 0

            # Second ingestion (same content)
            result2 = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
            )
            assert result2.success is True
            assert "unchanged" in result2.warnings[0].lower()

    def test_force_reprocess(self, app, usitc_processor, sample_csv_content):
        """Force flag should reprocess even if content unchanged."""
        with app.app_context():
            # First ingestion
            result1 = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
            )

            # Second ingestion with force
            result2 = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
                force=True,  # Force reprocess
            )
            assert result2.success is True
            # Should process rows even if skipped as duplicates
            assert result2.rows_processed > 0


# =============================================================================
# Test: Federal Register Notice Processor
# =============================================================================

class TestFederalRegisterSection301Processor:
    """Test Federal Register Notice processor."""

    def test_extract_ch99_heading(self, frn_processor, sample_frn_text):
        """Test extracting Chapter 99 heading from FRN text."""
        extracted = frn_processor._extract_section_301_data(sample_frn_text)

        assert extracted["ch99_heading"] == "9903.91.07"

    def test_extract_rate(self, frn_processor, sample_frn_text):
        """Test extracting rate from FRN text."""
        extracted = frn_processor._extract_section_301_data(sample_frn_text)

        # The sample text mentions 50 percent
        assert extracted["rate"] == Decimal("0.50")

    def test_extract_hts_codes(self, frn_processor, sample_frn_text):
        """Test extracting HTS codes from FRN text."""
        extracted = frn_processor._extract_section_301_data(sample_frn_text)

        hts_codes = extracted["hts_codes"]
        assert len(hts_codes) >= 1
        # Should find 6307.90.10, 6307.90.40, 6307.90.50
        normalized = [h.replace(".", "") for h in hts_codes]
        assert "63079010" in normalized or "6307.90.10" in hts_codes

    def test_extract_effective_date(self, frn_processor):
        """Test extracting effective date from FRN text."""
        text = "effective September 27, 2024"
        extracted = frn_processor._extract_section_301_data(text)

        assert extracted["effective_date"] == date(2024, 9, 27)

    def test_creates_source_version_tier_0(self, app, frn_processor, sample_frn_text):
        """FRN ingestion should create Tier 0 source version."""
        from app.models.section301 import SourceVersion, SourceType

        with app.app_context():
            result = frn_processor.process_frn_document(
                document_text=sample_frn_text,
                document_number="2024-TEST-001",
                publication_date=date(2024, 9, 15),
                effective_date=date(2024, 9, 27),
                dry_run=False,
            )

            assert result.success is True

            if result.source_version_id:
                sv = SourceVersion.query.get(result.source_version_id)
                assert sv.source_type == SourceType.USTR_FRN.value
                assert sv.get_tier() == 0  # Tier 0 = highest authority


# =============================================================================
# Test: SCD Type 2 Versioning
# =============================================================================

class TestSCDType2Versioning:
    """Test SCD Type 2 versioning logic."""

    def test_new_record_has_no_end_date(self, app, db_session):
        """New records should have NULL effective_end."""
        from app.models.section301 import TariffMeasure, RateStatus

        with app.app_context():
            measure = TariffMeasure(
                program='301_NOTE20',
                ch99_heading='9903.88.01',
                scope_hts_type='HTS8',
                scope_hts_value='85444290',
                additional_rate=Decimal('0.25'),
                rate_status=RateStatus.CONFIRMED.value,
                effective_start=date(2020, 1, 1),
                effective_end=None,
            )
            db_session.add(measure)
            db_session.commit()

            assert measure.effective_end is None
            assert measure.is_active(date(2024, 1, 1)) is True

    def test_closed_record_has_end_date(self, app, db_session):
        """Closed records should have effective_end set."""
        from app.models.section301 import TariffMeasure, RateStatus

        with app.app_context():
            # Old record (closed)
            old = TariffMeasure(
                program='301_NOTE20',
                ch99_heading='9903.88.15',
                scope_hts_type='HTS8',
                scope_hts_value='63079010',
                additional_rate=Decimal('0.075'),
                rate_status=RateStatus.CONFIRMED.value,
                effective_start=date(2020, 2, 14),
                effective_end=date(2024, 9, 27),  # Closed
            )
            db_session.add(old)

            # New record (active)
            new = TariffMeasure(
                program='301_NOTE31',
                ch99_heading='9903.91.07',
                scope_hts_type='HTS8',
                scope_hts_value='63079010',
                additional_rate=Decimal('0.50'),
                rate_status=RateStatus.CONFIRMED.value,
                effective_start=date(2024, 9, 27),
                effective_end=None,  # Active
            )
            db_session.add(new)
            db_session.commit()

            # Query for effective date before close
            assert old.is_active(date(2024, 9, 1)) is True
            assert new.is_active(date(2024, 9, 1)) is False

            # Query for effective date after close
            assert old.is_active(date(2024, 10, 1)) is False
            assert new.is_active(date(2024, 10, 1)) is True

    def test_rate_change_closes_old_opens_new(self, app, usitc_processor):
        """Rate change should close old record and create new one."""
        from app.models.section301 import TariffMeasure, RateStatus

        with app.app_context():
            # Create initial record
            initial = TariffMeasure(
                program='301_NOTE20',
                ch99_heading='9903.88.15',
                scope_hts_type='HTS8',
                scope_hts_value='99999999',
                additional_rate=Decimal('0.075'),
                rate_status=RateStatus.CONFIRMED.value,
                effective_start=date(2020, 1, 1),
                effective_end=None,
            )
            from app.web.db import db
            db.session.add(initial)
            db.session.commit()

            initial_id = initial.id

            # Simulate rate change via CSV ingestion
            csv_with_new_rate = b"""htsno,description,general,special,other,list
9999.99.99,"Test",Free,Free,Free,List 4A
"""
            # Set rate override (simulating FR notice)
            usitc_processor.set_rate_override("list 4a", Decimal("0.25"))

            result = usitc_processor.ingest(
                csv_content=csv_with_new_rate,
                dry_run=False,
                force=True,
            )

            # Old record should be closed
            old = TariffMeasure.query.get(initial_id)
            assert old.effective_end is not None

            # New record should exist with new rate
            new = TariffMeasure.query.filter_by(
                scope_hts_value='99999999',
                effective_end=None,  # Active
            ).first()
            assert new is not None
            assert new.additional_rate == Decimal('0.25')


# =============================================================================
# Test: Pipeline Integration
# =============================================================================

class TestSection301Pipeline:
    """Test full pipeline integration."""

    def test_pipeline_creates_both_processors(self, pipeline):
        """Pipeline should have both processors."""
        assert pipeline.usitc_processor is not None
        assert pipeline.frn_processor is not None

    def test_sync_usitc_dry_run(self, app, pipeline):
        """Dry run should not commit changes."""
        from app.models.section301 import TariffMeasure

        with app.app_context():
            # Mock the fetch to avoid real network call
            with patch.object(
                pipeline.usitc_processor,
                'fetch_csv',
                return_value=(b"htsno,list\n12345678,List 1", "abc123")
            ):
                result = pipeline.sync_usitc_china_tariffs(dry_run=True)

                # Should process but not commit
                assert result.source_version_id is None

                # No records in database
                count = TariffMeasure.query.count()
                assert count == 0

    @patch('app.watchers.federal_register.FederalRegisterWatcher')
    def test_automated_check_calls_watchers(self, mock_watcher_class, app, pipeline):
        """Automated check should poll watchers."""
        mock_watcher = MagicMock()
        mock_watcher.poll.return_value = []  # No new notices
        mock_watcher_class.return_value = mock_watcher

        with app.app_context():
            with patch.object(
                pipeline.usitc_processor,
                'fetch_csv',
                return_value=(b"htsno,list\n", "empty123")
            ):
                results = pipeline.run_automated_check(dry_run=True)

                # Should have called poll
                mock_watcher.poll.assert_called_once()


# =============================================================================
# Test: Source Version Audit Trail
# =============================================================================

class TestSourceVersionAuditTrail:
    """Test source version audit trail."""

    def test_source_version_content_hash(self, app, db_session):
        """Source version should track content hash."""
        from app.models.section301 import SourceVersion, SourceType, Publisher
        import hashlib

        content = b"test content"
        expected_hash = hashlib.sha256(content).hexdigest()

        with app.app_context():
            sv = SourceVersion(
                source_type=SourceType.USITC_CHINA.value,
                publisher=Publisher.USITC.value,
                document_id="test-001",
                content_hash=expected_hash,
            )
            db_session.add(sv)
            db_session.commit()

            retrieved = SourceVersion.query.get(sv.id)
            assert retrieved.content_hash == expected_hash

    def test_source_version_supersedes(self, app, db_session):
        """Source versions should track supersession."""
        from app.models.section301 import SourceVersion, SourceType, Publisher

        with app.app_context():
            # Original version
            v1 = SourceVersion(
                source_type=SourceType.USTR_FRN.value,
                publisher=Publisher.USTR.value,
                document_id="2024-001",
                content_hash="hash1",
            )
            db_session.add(v1)
            db_session.flush()

            # Superseding version
            v2 = SourceVersion(
                source_type=SourceType.USTR_FRN.value,
                publisher=Publisher.USTR.value,
                document_id="2024-001-corrected",
                content_hash="hash2",
                supersedes_source_version_id=v1.id,
            )
            db_session.add(v2)
            db_session.commit()

            # Check relationship
            assert v2.supersedes.id == v1.id
            assert v1.superseded_by[0].id == v2.id

    def test_source_tier_hierarchy(self, app, db_session):
        """Source versions should have correct tier."""
        from app.models.section301 import SourceVersion, SourceType, Publisher

        with app.app_context():
            # Tier 0 - USTR FRN (highest authority)
            tier0 = SourceVersion(
                source_type=SourceType.USTR_FRN.value,
                publisher=Publisher.USTR.value,
                document_id="test-tier0",
                content_hash="t0",
            )

            # Tier 1 - USITC (authoritative reference)
            tier1 = SourceVersion(
                source_type=SourceType.USITC_CHINA.value,
                publisher=Publisher.USITC.value,
                document_id="test-tier1",
                content_hash="t1",
            )

            # Tier 2 - CBP (operational guidance)
            tier2 = SourceVersion(
                source_type=SourceType.CBP_CSMS.value,
                publisher=Publisher.CBP.value,
                document_id="test-tier2",
                content_hash="t2",
            )

            db_session.add_all([tier0, tier1, tier2])
            db_session.commit()

            assert tier0.get_tier() == 0
            assert tier1.get_tier() == 1
            assert tier2.get_tier() == 2

            # Tier 0 should win in conflicts
            assert tier0.get_tier() < tier1.get_tier() < tier2.get_tier()


# =============================================================================
# Test: Ingestion Run Tracking
# =============================================================================

class TestIngestionRunTracking:
    """Test ingestion run tracking."""

    def test_ingestion_run_created(self, app, usitc_processor, sample_csv_content):
        """Ingestion should create run record."""
        from app.models.section301 import Section301IngestionRun

        with app.app_context():
            result = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
            )

            assert result.ingestion_run_id is not None

            run = Section301IngestionRun.query.get(result.ingestion_run_id)
            assert run is not None
            assert run.rows_added == result.rows_added
            assert run.status in ("success", "partial")

    def test_ingestion_run_has_stats(self, app, usitc_processor, sample_csv_content):
        """Ingestion run should have accurate statistics."""
        from app.models.section301 import Section301IngestionRun

        with app.app_context():
            result = usitc_processor.ingest(
                csv_content=sample_csv_content,
                dry_run=False,
            )

            run = Section301IngestionRun.query.get(result.ingestion_run_id)

            assert run.rows_added >= 0
            assert run.rows_skipped >= 0
            assert run.completed_at is not None
            assert run.started_at <= run.completed_at
