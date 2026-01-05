"""
Unit tests for Write Gate (v10.0 Phase 3).

Tests:
- Document existence checks
- Chunk existence checks
- Tier A validation
- Quote verification
- Validator passed checks
- Multiple sources check
"""

import pytest
from unittest.mock import Mock, patch


class TestWriteGate:
    """Tests for the WriteGate class."""

    def test_check_document_exists_found(self, test_document, rag_app):
        """Test document exists check when document is found."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_document_exists(test_document["id"])

            assert check.passed is True
            assert check.check_name == "document_exists"
            assert test_document["id"] in check.message

    def test_check_document_exists_not_found(self, rag_app):
        """Test document exists check when document not found."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_document_exists("nonexistent-doc-id")

            assert check.passed is False
            assert "not found" in check.message

    def test_check_chunk_exists_found(self, test_document_with_chunk, rag_app):
        """Test chunk exists check when chunk is found."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_chunk_exists(test_document_with_chunk["chunk_id"])

            assert check.passed is True
            assert check.check_name == "chunk_exists"

    def test_check_chunk_exists_not_found(self, rag_app):
        """Test chunk exists check when chunk not found."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_chunk_exists("nonexistent-chunk-id")

            assert check.passed is False
            assert "not found" in check.message

    def test_check_tier_a_passed(self, test_document, rag_app):
        """Test tier A check with Tier A document."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_tier_a(test_document["id"])

            assert check.passed is True
            assert check.check_name == "tier_a_only"
            assert "Tier A" in check.message

    def test_check_tier_a_failed(self, rag_app, sample_document_data):
        """Test tier A check with non-Tier A document."""
        from app.web.db import db
        from app.web.db.models.document import Document
        from app.rag.write_gate import WriteGate
        import uuid

        with rag_app.app_context():
            # Create Tier B document
            doc = Document(
                id=str(uuid.uuid4()),
                source="USTR",
                tier="B",  # Not Tier A
                connector_name="ustr_connector",
                url_canonical="https://example.com",
                sha256_raw="abc123",
            )
            db.session.add(doc)
            db.session.commit()

            gate = WriteGate(db.session)
            check = gate._check_tier_a(doc.id)

            assert check.passed is False
            assert "Tier B" in check.message

    def test_check_quote_exists_found(self, test_document_with_chunk, rag_app):
        """Test quote exists when quote is in chunk."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            # Quote that exists in the chunk text
            quote = "steel tariffs"  # Part of the chunk text
            check = gate._check_quote_exists(
                test_document_with_chunk["chunk_id"],
                quote
            )

            assert check.passed is True
            assert check.check_name == "quote_exists"

    def test_check_quote_exists_not_found(self, test_document_with_chunk, rag_app):
        """Test quote exists when quote is not in chunk."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_quote_exists(
                test_document_with_chunk["chunk_id"],
                "This quote does not exist in the chunk"
            )

            assert check.passed is False
            assert "not found verbatim" in check.message

    def test_check_quote_exists_empty(self, test_document_with_chunk, rag_app):
        """Test quote exists with empty quote."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_quote_exists(
                test_document_with_chunk["chunk_id"],
                ""
            )

            assert check.passed is False
            assert "empty" in check.message.lower()

    def test_check_validator_passed_true(self, rag_app):
        """Test validator passed check with verified=true."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            validator_output = {
                "verified": True,
                "failures": [],
            }
            check = gate._check_validator_passed(validator_output)

            assert check.passed is True
            assert check.check_name == "validator_passed"

    def test_check_validator_passed_false(self, rag_app):
        """Test validator passed check with verified=false."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            validator_output = {
                "verified": False,
                "failures": [{"reason": "Quote not found"}],
            }
            check = gate._check_validator_passed(validator_output)

            assert check.passed is False
            assert "failed" in check.message.lower()

    def test_check_validator_passed_no_output(self, rag_app):
        """Test validator passed check with no output."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            check = gate._check_validator_passed(None)

            assert check.passed is False
            assert "No validator output" in check.message

    def test_check_multiple_sources_passed(self, rag_app):
        """Test multiple sources check with enough sources."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            citations = [
                {"document_id": "doc-001"},
                {"document_id": "doc-002"},
            ]
            check = gate._check_multiple_sources(citations, min_citations=2)

            assert check.passed is True
            assert check.severity == "warning"  # This is a warning, not error

    def test_check_multiple_sources_failed(self, rag_app):
        """Test multiple sources check with not enough sources."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            citations = [
                {"document_id": "doc-001"},
            ]
            check = gate._check_multiple_sources(citations, min_citations=2)

            assert check.passed is False
            assert check.severity == "warning"


class TestWriteGateCheck:
    """Tests for the full check method."""

    def test_check_no_citations(self, rag_app):
        """Test check with no citations."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)
            reader_output = {
                "answer": {"in_scope": True},
                "citations": [],
            }
            validator_output = {"verified": True}

            result = gate.check(reader_output, validator_output)

            assert result.passed is False
            assert "No citations" in str(result.errors)

    def test_check_all_pass(self, test_document_with_chunk, rag_app):
        """Test check when all checks pass."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)

            # Use text that exists in the test chunk
            reader_output = {
                "answer": {"in_scope": True},
                "citations": [
                    {
                        "document_id": test_document_with_chunk["document_id"],
                        "chunk_id": test_document_with_chunk["chunk_id"],
                        "quote": "steel tariffs",  # Must be in chunk text
                    }
                ],
            }
            validator_output = {"verified": True}

            result = gate.check(reader_output, validator_output)

            assert result.passed is True
            assert len(result.errors) == 0

    def test_check_document_not_found(self, test_document_with_chunk, rag_app):
        """Test check when document not found."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            gate = WriteGate(db.session)

            reader_output = {
                "answer": {"in_scope": True},
                "citations": [
                    {
                        "document_id": "nonexistent-doc",
                        "chunk_id": test_document_with_chunk["chunk_id"],
                        "quote": "test quote",
                    }
                ],
            }
            validator_output = {"verified": True}

            result = gate.check(reader_output, validator_output)

            assert result.passed is False
            assert any("not found" in err.lower() for err in result.errors)


class TestWriteGateResult:
    """Tests for the WriteGateResult dataclass."""

    def test_write_gate_result_to_dict(self):
        """Test WriteGateResult to_dict method."""
        from app.rag.write_gate import WriteGateResult, WriteGateCheck

        result = WriteGateResult(
            passed=True,
            checks=[
                WriteGateCheck(
                    check_name="document_exists",
                    passed=True,
                    message="Document found",
                ),
                WriteGateCheck(
                    check_name="tier_a_only",
                    passed=True,
                    message="Document is Tier A",
                ),
            ],
            errors=[],
            warnings=["Only 1 source"],
        )

        output = result.to_dict()

        assert output["passed"] is True
        assert len(output["checks"]) == 2
        assert output["checks"][0]["check_name"] == "document_exists"
        assert len(output["errors"]) == 0
        assert len(output["warnings"]) == 1

    def test_write_gate_result_failed(self):
        """Test failed WriteGateResult."""
        from app.rag.write_gate import WriteGateResult, WriteGateCheck

        result = WriteGateResult(
            passed=False,
            checks=[
                WriteGateCheck(
                    check_name="quote_exists",
                    passed=False,
                    message="Quote not found",
                ),
            ],
            errors=["Citation 0: Quote not found"],
            warnings=[],
        )

        assert result.passed is False
        assert len(result.errors) == 1


class TestComputeEvidenceHash:
    """Tests for evidence hash computation."""

    def test_compute_evidence_hash(self, rag_app):
        """Test computing evidence hash."""
        from app.web.db import db
        from app.rag.write_gate import WriteGate
        import hashlib

        with rag_app.app_context():
            gate = WriteGate(db.session)

            quote = "HTS 8544.42.9090 is in scope"
            document_id = "doc-001"
            chunk_id = "chunk-001"

            result = gate.compute_evidence_hash(quote, document_id, chunk_id)

            # Verify it's a valid SHA-256 hash
            assert len(result) == 64
            assert all(c in '0123456789abcdef' for c in result)

            # Verify consistency
            result2 = gate.compute_evidence_hash(quote, document_id, chunk_id)
            assert result == result2

            # Verify different inputs produce different hashes
            result3 = gate.compute_evidence_hash("Different quote", document_id, chunk_id)
            assert result != result3
