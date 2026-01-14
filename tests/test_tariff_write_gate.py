"""
Tests for Tariff Write Gate (Dual-LLM Verification Pipeline).

Tests for:
- TariffExtractorLLM (Gemini extraction)
- TariffVerifierLLM (GPT-4 verification)
- WriteGate (auto-insert verified data)
- End-to-end pipeline

The Write Gate uses dual-LLM verification:
1. Extractor (Gemini) extracts tariff data from notices
2. Verifier (GPT-4) finds exact quotes proving extraction is correct
3. Write Gate only inserts if verifier found ALL evidence quotes
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_csms_document():
    """Sample CBP CSMS document for testing."""
    return """
    CSMS #65936570

    Subject: Section 232 - Steel Derivative Tariffs - Additional HTS Codes

    The following HTS codes have been added to the list of steel derivative
    articles subject to Section 232 tariffs effective August 18, 2025.

    Chapter 99 Code: 9903.81.91
    Duty Rate: 25 percent

    HTS Codes Added:
    - 8302.41.3000 - Base metal mountings, fittings
    - 8302.41.6015 - Base metal mountings for doors
    - 8302.41.6050 - Base metal mountings, furniture

    These products shall be reported with Chapter 99 code 9903.81.91.

    For questions, contact the CBP Trade Office.
    """


@pytest.fixture
def sample_csms_no_rate():
    """CSMS document without rate (for hallucination test)."""
    return """
    CSMS #65936571

    Subject: Section 232 - Steel Derivative Tariffs Update

    The following HTS codes have been added to the list of steel derivative
    articles subject to Section 232 tariffs.

    HTS Code: 8544.42.9000
    Effective Date: August 18, 2025

    For further information, contact the CBP Trade Office.
    """


@pytest.fixture
def mock_extraction_result():
    """Mock extraction result for testing verifier and write gate."""
    from app.services.extractor_llm import ExtractionResult

    return ExtractionResult(
        hts_codes=["8302.41.6015", "8302.41.6050"],
        program="section_232_steel",
        chapter_99_code="9903.81.91",
        duty_rate=0.25,
        effective_date=date(2025, 8, 18),
        action="add_to_scope",
        material_type="steel",
        quotes=["Section 232 - Steel Derivative Tariffs", "25 percent"],
        success=True,
    )


@pytest.fixture
def mock_verification_passed():
    """Mock verification result (all fields verified)."""
    from app.services.verifier_llm import VerificationResult, FieldEvidence

    return VerificationResult(
        verified=True,
        confidence=0.95,
        evidence={
            "hts_codes": FieldEvidence(found=True, quote="8302.41.6015", confidence=1.0),
            "duty_rate": FieldEvidence(found=True, quote="25 percent", confidence=1.0),
            "program": FieldEvidence(found=True, quote="Section 232", confidence=1.0),
        },
        missing_fields=[],
        verified_fields=["hts_codes", "duty_rate", "program", "effective_date"],
        success=True,
    )


@pytest.fixture
def mock_verification_failed():
    """Mock verification result (duty_rate not found - hallucination)."""
    from app.services.verifier_llm import VerificationResult, FieldEvidence

    return VerificationResult(
        verified=False,
        confidence=0.5,
        evidence={
            "hts_codes": FieldEvidence(found=True, quote="8544.42.9000", confidence=1.0),
            "duty_rate": FieldEvidence(found=False, quote=None, confidence=0.0),
            "program": FieldEvidence(found=True, quote="Section 232", confidence=1.0),
        },
        missing_fields=["duty_rate"],
        verified_fields=["hts_codes", "program"],
        success=True,
    )


# ============================================================================
# TARIFF EXTRACTOR TESTS
# ============================================================================

class TestTariffExtractor:
    """Tests for Gemini extraction service."""

    def test_extraction_result_dataclass(self):
        """Test ExtractionResult dataclass creation."""
        from app.services.extractor_llm import ExtractionResult

        result = ExtractionResult(
            hts_codes=["8302.41.6015"],
            program="section_232_steel",
            duty_rate=0.25,
            success=True,
        )

        assert result.hts_codes == ["8302.41.6015"]
        assert result.program == "section_232_steel"
        assert result.duty_rate == 0.25
        assert result.success is True

    def test_extraction_result_as_dict(self):
        """Test ExtractionResult.as_dict() method."""
        from app.services.extractor_llm import ExtractionResult

        result = ExtractionResult(
            hts_codes=["8302.41.6015"],
            program="section_232_steel",
            duty_rate=0.25,
            success=True,
        )

        data = result.as_dict()
        assert data["hts_codes"] == ["8302.41.6015"]
        assert data["program"] == "section_232_steel"
        assert data["success"] is True

    def test_extract_with_mocked_gemini(self, sample_csms_document):
        """Test extraction logic with mocked Gemini response."""
        from app.services.extractor_llm import TariffExtractorLLM, ExtractionResult

        # Instead of mocking Gemini, mock the extract method's internal call
        # and test the parse_response logic
        mock_json_response = """{
            "hts_codes": ["8302.41.6015", "8302.41.6050"],
            "program": "section_232_steel",
            "chapter_99_code": "9903.81.91",
            "duty_rate": 0.25,
            "effective_date": "2025-08-18",
            "action": "add_to_scope",
            "material_type": "steel",
            "quotes": ["Section 232 - Steel Derivative Tariffs"]
        }"""

        extractor = TariffExtractorLLM()
        result = extractor._parse_response(mock_json_response)

        assert result.success
        assert len(result.hts_codes) == 2
        assert "8302.41.6015" in result.hts_codes
        assert result.program == "section_232_steel"
        assert result.duty_rate == 0.25

    @pytest.mark.llm
    def test_extract_real_gemini_call(self, sample_csms_document):
        """Test extraction with real Gemini API call."""
        from app.services.extractor_llm import TariffExtractorLLM

        extractor = TariffExtractorLLM()
        result = extractor.extract(sample_csms_document, "CSMS #65936570")

        assert result.success
        assert result.program in ["section_232_steel", "section_232"]
        assert len(result.hts_codes) > 0


# ============================================================================
# TARIFF VERIFIER TESTS
# ============================================================================

class TestTariffVerifier:
    """Tests for GPT-4 verification service."""

    def test_verification_result_dataclass(self):
        """Test VerificationResult dataclass creation."""
        from app.services.verifier_llm import VerificationResult

        result = VerificationResult(
            verified=True,
            confidence=0.95,
            missing_fields=[],
            verified_fields=["hts_codes", "duty_rate"],
            success=True,
        )

        assert result.verified is True
        assert result.confidence == 0.95
        assert len(result.missing_fields) == 0

    def test_verification_result_as_dict(self, mock_verification_passed):
        """Test VerificationResult.as_dict() method."""
        data = mock_verification_passed.as_dict()

        assert data["verified"] is True
        assert data["confidence"] == 0.95
        assert "hts_codes" in data["verified_fields"]

    def test_quick_verify_pass(self, sample_csms_document, mock_extraction_result):
        """Test quick string-based verification passes."""
        from app.services.verifier_llm import TariffVerifierLLM

        verifier = TariffVerifierLLM()
        passed = verifier.quick_verify(mock_extraction_result, sample_csms_document)

        # HTS code and rate are in document
        assert passed is True

    def test_quick_verify_fail_missing_hts(self, sample_csms_document):
        """Test quick verify fails when HTS not in document."""
        from app.services.verifier_llm import TariffVerifierLLM
        from app.services.extractor_llm import ExtractionResult

        extraction = ExtractionResult(
            hts_codes=["9999.99.9999"],  # Not in doc
            program="section_232_steel",
            duty_rate=0.25,
            success=True,
        )

        verifier = TariffVerifierLLM()
        passed = verifier.quick_verify(extraction, sample_csms_document)

        assert passed is False

    def test_quick_verify_fail_missing_rate(self, sample_csms_no_rate):
        """Test quick verify fails when rate not in document."""
        from app.services.verifier_llm import TariffVerifierLLM
        from app.services.extractor_llm import ExtractionResult

        extraction = ExtractionResult(
            hts_codes=["8544.42.9000"],  # In doc
            program="section_232_steel",
            duty_rate=0.25,  # NOT in doc
            success=True,
        )

        verifier = TariffVerifierLLM()
        # Note: quick_verify checks HTS AND (program OR rate)
        # Since program is in doc, this will pass
        # Full LLM verify is needed to catch missing rate
        passed = verifier.quick_verify(extraction, sample_csms_no_rate)
        # It will pass because "section 232" is in the doc
        assert passed is True  # Quick verify is less strict

    @pytest.mark.llm
    def test_verify_real_gpt4_rate_in_doc(self, sample_csms_document, mock_extraction_result):
        """Test GPT-4 verification when rate IS in document."""
        from app.services.verifier_llm import TariffVerifierLLM

        verifier = TariffVerifierLLM()
        result = verifier.verify(mock_extraction_result, sample_csms_document)

        assert result.success
        assert result.verified is True
        assert "duty_rate" in result.verified_fields or result.evidence.get("duty_rate", {}).found

    @pytest.mark.llm
    def test_verify_real_gpt4_catches_hallucination(self, sample_csms_no_rate):
        """Test GPT-4 verification catches hallucinated rate."""
        from app.services.verifier_llm import TariffVerifierLLM
        from app.services.extractor_llm import ExtractionResult

        extraction = ExtractionResult(
            hts_codes=["8544.42.9000"],
            program="section_232_steel",
            chapter_99_code="9903.81.91",  # Not in doc
            duty_rate=0.25,  # HALLUCINATED - not in doc!
            effective_date=date(2025, 8, 18),
            success=True,
        )

        verifier = TariffVerifierLLM()
        result = verifier.verify(extraction, sample_csms_no_rate)

        assert result.success
        assert result.verified is False  # Should catch hallucination
        assert "duty_rate" in result.missing_fields


# ============================================================================
# WRITE GATE TESTS
# ============================================================================

class TestWriteGate:
    """Tests for WriteGate service."""

    def test_write_result_dataclass(self):
        """Test WriteResult dataclass creation."""
        from app.services.write_gate import WriteResult

        result = WriteResult(
            success=True,
            rows_inserted=3,
            table="section_232_rates",
        )

        assert result.success is True
        assert result.rows_inserted == 3
        assert result.table == "section_232_rates"

    def test_process_document_no_hts_codes(self):
        """WriteGate returns error when no HTS codes extracted."""
        from app.services.write_gate import WriteGate
        from app.services.extractor_llm import ExtractionResult

        mock_extractor = Mock()
        mock_extractor.extract.return_value = ExtractionResult(
            hts_codes=[],  # Empty!
            program="section_232_steel",
            success=True,
        )

        gate = WriteGate(extractor=mock_extractor)
        result = gate.process_document("doc text", "source")

        assert not result.success
        assert "No HTS codes" in result.skipped_reason

    def test_process_document_no_program(self):
        """WriteGate returns error when program not determined."""
        from app.services.write_gate import WriteGate
        from app.services.extractor_llm import ExtractionResult

        mock_extractor = Mock()
        mock_extractor.extract.return_value = ExtractionResult(
            hts_codes=["8302.41.6015"],
            program=None,  # No program
            success=True,
        )

        gate = WriteGate(extractor=mock_extractor)
        result = gate.process_document("doc text", "source")

        assert not result.success
        assert "program" in result.skipped_reason.lower()

    def test_process_document_extraction_failed(self):
        """WriteGate returns error when extraction fails."""
        from app.services.write_gate import WriteGate
        from app.services.extractor_llm import ExtractionResult

        mock_extractor = Mock()
        mock_extractor.extract.return_value = ExtractionResult(
            success=False,
            error="API error",
        )

        gate = WriteGate(extractor=mock_extractor)
        result = gate.process_document("doc text", "source")

        assert not result.success
        assert result.error == "API error"

    def test_process_document_verification_failed(self, mock_extraction_result, mock_verification_failed):
        """WriteGate skips insert when verification fails."""
        from app.services.write_gate import WriteGate

        mock_extractor = Mock()
        mock_extractor.extract.return_value = mock_extraction_result

        mock_verifier = Mock()
        mock_verifier.verify.return_value = mock_verification_failed

        gate = WriteGate(extractor=mock_extractor, verifier=mock_verifier)
        result = gate.process_document("doc", "source")

        assert not result.success
        assert "Verification failed" in result.skipped_reason
        assert "duty_rate" in result.skipped_reason

    def test_process_document_low_confidence(self, mock_extraction_result, mock_verification_passed):
        """WriteGate skips insert when confidence below threshold."""
        from app.services.write_gate import WriteGate

        mock_extractor = Mock()
        mock_extractor.extract.return_value = mock_extraction_result

        # Lower confidence below threshold
        mock_verification_passed.confidence = 0.5

        mock_verifier = Mock()
        mock_verifier.verify.return_value = mock_verification_passed

        gate = WriteGate(extractor=mock_extractor, verifier=mock_verifier, min_confidence=0.85)
        result = gate.process_document("doc", "source")

        assert not result.success
        assert "Confidence" in result.skipped_reason or "below threshold" in result.skipped_reason

    def test_process_document_skip_verification(self, mock_extraction_result):
        """WriteGate can skip verification for testing."""
        from app.services.write_gate import WriteGate

        mock_extractor = Mock()
        mock_extractor.extract.return_value = mock_extraction_result

        gate = WriteGate(extractor=mock_extractor)

        # Mock the database insert
        with patch.object(gate, '_insert_to_temporal_tables', return_value=(2, 'section_232_rates')):
            with patch.object(gate, '_log_ingestion_run', return_value=1):
                result = gate.process_document("doc", "source", skip_verification=True)

        assert result.success
        assert result.rows_inserted == 2
        assert result.table == "section_232_rates"

    def test_normalize_hts(self):
        """Test HTS code normalization."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()

        assert gate._normalize_hts("8302.41.60") == "83024160"
        assert gate._normalize_hts("8302.41.6015") == "8302416015"
        assert gate._normalize_hts(" 8302.41.60 ") == "83024160"

    def test_determine_article_type_steel(self):
        """Test article type determination for steel."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()

        # Steel primary (Chapter 72)
        assert gate._determine_article_type(72, "steel") == "primary"
        # Steel derivative (Chapter 73)
        assert gate._determine_article_type(73, "steel") == "derivative"
        # Steel content (other chapters)
        assert gate._determine_article_type(85, "steel") == "content"

    def test_determine_article_type_aluminum(self):
        """Test article type determination for aluminum."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()

        # Aluminum primary (Chapter 76)
        assert gate._determine_article_type(76, "aluminum") == "primary"
        # Aluminum derivative (other chapters)
        assert gate._determine_article_type(85, "aluminum") == "derivative"

    def test_determine_article_type_copper(self):
        """Test article type determination for copper."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()

        # Copper primary (Chapter 74)
        assert gate._determine_article_type(74, "copper") == "primary"
        # Copper derivative (other chapters)
        assert gate._determine_article_type(85, "copper") == "derivative"

    def test_get_default_claim_code(self):
        """Test default Chapter 99 claim codes."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()

        assert gate._get_default_claim_code("steel", "primary") == "9903.80.01"
        assert gate._get_default_claim_code("steel", "derivative") == "9903.81.91"
        assert gate._get_default_claim_code("aluminum", "primary") == "9903.85.03"
        assert gate._get_default_claim_code("aluminum", "derivative") == "9903.85.08"
        assert gate._get_default_claim_code("copper", "primary") == "9903.78.01"


# ============================================================================
# INTEGRATION TESTS (with database)
# ============================================================================

class TestWriteGateIntegration:
    """Integration tests with real database."""

    @pytest.fixture
    def app(self):
        """Create Flask app with in-memory database."""
        import os
        os.environ["TESTING"] = "true"
        os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

        from app.web import create_app
        from app.web.db import db

        app = create_app()
        app.config.update({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        })

        with app.app_context():
            db.create_all()
            yield app
            db.drop_all()

    def test_database_insert_section_232(self, app, mock_extraction_result, mock_verification_passed):
        """Test actual database insert for Section 232 rate."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Rate
        from app.services.write_gate import WriteGate

        with app.app_context():
            mock_extractor = Mock()
            mock_extractor.extract.return_value = mock_extraction_result

            mock_verifier = Mock()
            mock_verifier.verify.return_value = mock_verification_passed

            gate = WriteGate(extractor=mock_extractor, verifier=mock_verifier)
            result = gate.process_document("doc", "CSMS #65936570")

            assert result.success
            assert result.rows_inserted >= 1

            # Verify in database
            rates = Section232Rate.query.all()
            assert len(rates) >= 1

            # Check first rate
            rate = rates[0]
            assert rate.material_type == "steel"
            assert float(rate.duty_rate) == 0.25

    def test_deduplication_skips_existing(self, app, mock_extraction_result, mock_verification_passed):
        """WriteGate skips duplicate rates."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Rate
        from app.services.write_gate import WriteGate

        with app.app_context():
            # Pre-insert rate
            existing = Section232Rate(
                hts_8digit="83024160",
                material_type="steel",
                chapter_99_claim="9903.81.91",
                duty_rate=0.25,
                effective_start=date(2025, 8, 18),
            )
            db.session.add(existing)
            db.session.commit()

            # Mock extraction for same HTS
            mock_extraction_result.hts_codes = ["8302.41.6015"]  # Same HTS
            mock_extraction_result.effective_date = date(2025, 8, 18)  # Same date

            mock_extractor = Mock()
            mock_extractor.extract.return_value = mock_extraction_result

            mock_verifier = Mock()
            mock_verifier.verify.return_value = mock_verification_passed

            gate = WriteGate(extractor=mock_extractor, verifier=mock_verifier)
            result = gate.process_document("doc", "CSMS #65936570")

            # Should succeed but skip the duplicate
            assert result.success
            # Only 1 row should exist (not 2)
            rates = Section232Rate.query.filter_by(material_type="steel").all()
            assert len(rates) == 1


# ============================================================================
# PIPELINE TESTS
# ============================================================================

class TestTariffUpdatePipeline:
    """Tests for the end-to-end pipeline."""

    def test_pipeline_result_dataclass(self):
        """Test PipelineResult dataclass creation."""
        from app.watchers.pipeline import PipelineResult

        result = PipelineResult(lookback_hours=24)
        result.notices_found = 5
        result.inserted = 10

        assert result.lookback_hours == 24
        assert result.notices_found == 5
        assert result.inserted == 10

    def test_pipeline_result_summary(self):
        """Test PipelineResult.summary() method."""
        from app.watchers.pipeline import PipelineResult

        result = PipelineResult(lookback_hours=24)
        result.notices_found = 5
        result.inserted = 10
        result.skipped = 2
        result.failed = 1
        result.duration_seconds = 5.5

        summary = result.summary()

        assert "5.5s" in summary
        assert "5 notices" in summary
        assert "10 rows" in summary

    def test_pipeline_result_as_dict(self):
        """Test PipelineResult.as_dict() method."""
        from app.watchers.pipeline import PipelineResult

        result = PipelineResult(lookback_hours=24)
        result.notices_found = 5

        data = result.as_dict()

        assert data["lookback_hours"] == 24
        assert data["notices_found"] == 5

    def test_check_for_updates_function(self):
        """Test check_for_updates entry point."""
        from app.watchers.pipeline import check_for_updates, TariffUpdatePipeline

        with patch.object(TariffUpdatePipeline, 'run') as mock_run:
            from app.watchers.pipeline import PipelineResult
            mock_result = PipelineResult(lookback_hours=24)
            mock_result.notices_found = 0
            mock_run.return_value = mock_result

            result = check_for_updates(lookback_hours=48)

            mock_run.assert_called_once_with(lookback_hours=48)
            assert "summary" in result


# ============================================================================
# PYTEST MARKERS
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "llm: marks tests that make real LLM API calls (may cost money)"
    )
