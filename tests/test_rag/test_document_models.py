"""
Unit tests for Document Store Models (v10.0 Phase 2 & 4).

Tests:
- Document model creation and methods
- DocumentChunk model creation and methods
- VerifiedAssertion model creation and methods
"""

import hashlib
from datetime import date, datetime, timedelta

import pytest


class TestDocument:
    """Tests for the Document model."""

    def test_document_creation(self, rag_app, sample_document_data):
        """Test creating a document."""
        from app.web.db import db
        from app.web.db.models.document import Document

        with rag_app.app_context():
            doc = Document(
                id=sample_document_data["id"],
                source=sample_document_data["source"],
                tier=sample_document_data["tier"],
                connector_name=sample_document_data["connector_name"],
                canonical_id=sample_document_data["canonical_id"],
                url_canonical=sample_document_data["url_canonical"],
                title=sample_document_data["title"],
                sha256_raw=sample_document_data["sha256_raw"],
                extracted_text=sample_document_data["extracted_text"],
            )
            db.session.add(doc)
            db.session.commit()

            # Verify saved
            saved = db.session.query(Document).filter_by(id=doc.id).first()
            assert saved is not None
            assert saved.source == "CSMS"
            assert saved.tier == "A"
            assert saved.connector_name == "csms_connector"

    def test_document_is_tier_a(self, rag_app, sample_document_data):
        """Test is_tier_a method."""
        from app.web.db import db
        from app.web.db.models.document import Document

        with rag_app.app_context():
            doc = Document(
                id=sample_document_data["id"],
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                url_canonical="https://example.com",
                sha256_raw="abc123",
            )
            assert doc.is_tier_a() is True

            doc.tier = "B"
            assert doc.is_tier_a() is False

            doc.tier = "C"
            assert doc.is_tier_a() is False

    def test_document_compute_hash(self, rag_app, sample_document_data):
        """Test compute_hash method."""
        from app.web.db.models.document import Document

        with rag_app.app_context():
            doc = Document(
                id=sample_document_data["id"],
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                url_canonical="https://example.com",
                sha256_raw="abc123",
            )

            content = "Test content for hashing"
            expected_hash = hashlib.sha256(content.encode()).hexdigest()
            assert doc.compute_hash(content) == expected_hash

    def test_document_as_dict(self, rag_app, sample_document_data):
        """Test as_dict method."""
        from app.web.db.models.document import Document

        with rag_app.app_context():
            doc = Document(
                id=sample_document_data["id"],
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                canonical_id="CSMS#123",
                url_canonical="https://example.com",
                title="Test Title",
                sha256_raw="abc123",
                hts_codes_mentioned=["8544.42.9090"],
                programs_mentioned=["section_232_steel"],
            )

            result = doc.as_dict()
            assert result["id"] == sample_document_data["id"]
            assert result["source"] == "CSMS"
            assert result["tier"] == "A"
            assert result["title"] == "Test Title"
            assert result["hts_codes_mentioned"] == ["8544.42.9090"]

    def test_document_unique_constraint(self, rag_app, sample_document_data):
        """Test that source + canonical_id is unique."""
        from app.web.db import db
        from app.web.db.models.document import Document
        from sqlalchemy.exc import IntegrityError
        import uuid

        with rag_app.app_context():
            # Create first document
            doc1 = Document(
                id=str(uuid.uuid4()),
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                canonical_id="CSMS#123",
                url_canonical="https://example.com/1",
                sha256_raw="abc123",
            )
            db.session.add(doc1)
            db.session.commit()

            # Try to create duplicate
            doc2 = Document(
                id=str(uuid.uuid4()),
                source="CSMS",  # Same source
                tier="A",
                connector_name="csms_connector",
                canonical_id="CSMS#123",  # Same canonical_id
                url_canonical="https://example.com/2",
                sha256_raw="def456",
            )
            db.session.add(doc2)

            with pytest.raises(IntegrityError):
                db.session.commit()


class TestDocumentChunk:
    """Tests for the DocumentChunk model."""

    def test_chunk_creation(self, test_document_with_chunk, rag_app):
        """Test creating a document chunk."""
        from app.web.db import db
        from app.web.db.models.document import DocumentChunk

        with rag_app.app_context():
            chunk = db.session.query(DocumentChunk).filter_by(
                id=test_document_with_chunk["chunk_id"]
            ).first()

            assert chunk is not None
            assert chunk.document_id == test_document_with_chunk["document_id"]
            assert chunk.chunk_index == 0

    def test_chunk_contains_quote(self, rag_app, sample_document_data, sample_chunk_data):
        """Test contains_quote method."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk

        with rag_app.app_context():
            # Create document first
            doc = Document(
                id=sample_document_data["id"],
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                url_canonical="https://example.com",
                sha256_raw="abc123",
            )
            db.session.add(doc)
            db.session.flush()

            # Create chunk with specific text
            chunk = DocumentChunk(
                id=sample_chunk_data["id"],
                document_id=doc.id,
                chunk_index=0,
                text="The HTS code 8544.42.9090 is in scope for Section 232 steel.",
            )

            # Test contains_quote
            assert chunk.contains_quote("8544.42.9090") is True
            assert chunk.contains_quote("Section 232 steel") is True
            assert chunk.contains_quote("not in text") is False

    def test_chunk_compute_hash(self, rag_app, sample_chunk_data):
        """Test compute_hash method."""
        from app.web.db.models.document import DocumentChunk

        with rag_app.app_context():
            chunk = DocumentChunk(
                id=sample_chunk_data["id"],
                document_id="doc-123",
                chunk_index=0,
                text="Test chunk content",
            )

            expected_hash = hashlib.sha256("Test chunk content".encode()).hexdigest()
            assert chunk.compute_hash() == expected_hash

    def test_chunk_as_dict(self, test_document_with_chunk, rag_app):
        """Test as_dict method."""
        from app.web.db import db
        from app.web.db.models.document import DocumentChunk

        with rag_app.app_context():
            chunk = db.session.query(DocumentChunk).filter_by(
                id=test_document_with_chunk["chunk_id"]
            ).first()

            result = chunk.as_dict()
            assert result["id"] == test_document_with_chunk["chunk_id"]
            assert result["document_id"] == test_document_with_chunk["document_id"]
            assert result["chunk_index"] == 0

    def test_chunk_unique_constraint(self, rag_app, sample_document_data):
        """Test that document_id + chunk_index is unique."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk
        from sqlalchemy.exc import IntegrityError
        import uuid

        with rag_app.app_context():
            # Create document
            doc = Document(
                id=sample_document_data["id"],
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                url_canonical="https://example.com",
                sha256_raw="abc123",
            )
            db.session.add(doc)
            db.session.flush()

            # Create first chunk
            chunk1 = DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                chunk_index=0,
                text="First chunk",
            )
            db.session.add(chunk1)
            db.session.commit()

            # Try to create duplicate chunk index
            chunk2 = DocumentChunk(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                chunk_index=0,  # Same index
                text="Second chunk",
            )
            db.session.add(chunk2)

            with pytest.raises(IntegrityError):
                db.session.commit()


class TestVerifiedAssertion:
    """Tests for the VerifiedAssertion model."""

    def test_assertion_creation(self, test_document_with_chunk, rag_app, sample_verified_assertion_data):
        """Test creating a verified assertion."""
        from app.web.db import db
        from app.web.db.models.document import VerifiedAssertion

        with rag_app.app_context():
            assertion = VerifiedAssertion(
                id=sample_verified_assertion_data["id"],
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                material="steel",
                assertion_type="IN_SCOPE",
                claim_code="9903.78.01",
                effective_start=date.today(),
                document_id=test_document_with_chunk["document_id"],
                chunk_id=test_document_with_chunk["chunk_id"],
                evidence_quote="HTS 8544.42.9090 is in scope",
                evidence_quote_hash=hashlib.sha256(b"HTS 8544.42.9090 is in scope").hexdigest(),
            )
            db.session.add(assertion)
            db.session.commit()

            # Verify saved
            saved = db.session.query(VerifiedAssertion).filter_by(id=assertion.id).first()
            assert saved is not None
            assert saved.program_id == "section_232_steel"
            assert saved.hts_code_norm == "85444290"
            assert saved.assertion_type == "IN_SCOPE"

    def test_assertion_is_current(self, test_document_with_chunk, rag_app):
        """Test is_current method."""
        from app.web.db.models.document import VerifiedAssertion

        with rag_app.app_context():
            # Current assertion (no end date)
            assertion = VerifiedAssertion(
                id="test-123",
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                assertion_type="IN_SCOPE",
                effective_start=date.today() - timedelta(days=30),
                effective_end=None,
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="Test",
                evidence_quote_hash="abc",
            )
            assert assertion.is_current() is True

            # Historical assertion (with end date in past)
            assertion.effective_end = date.today() - timedelta(days=1)
            assert assertion.is_current() is False

            # Future assertion
            assertion.effective_start = date.today() + timedelta(days=1)
            assertion.effective_end = None
            assert assertion.is_current() is False

    def test_assertion_as_dict(self, test_document_with_chunk, rag_app):
        """Test as_dict method."""
        from app.web.db.models.document import VerifiedAssertion

        with rag_app.app_context():
            assertion = VerifiedAssertion(
                id="test-123",
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                material="steel",
                assertion_type="IN_SCOPE",
                claim_code="9903.78.01",
                effective_start=date.today(),
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="HTS 8544.42.9090 is in scope for Section 232",
                evidence_quote_hash="abc123",
                verified_by="write_gate",
            )

            result = assertion.as_dict()
            assert result["program_id"] == "section_232_steel"
            assert result["hts_code_norm"] == "85444290"
            assert result["assertion_type"] == "IN_SCOPE"
            assert result["claim_code"] == "9903.78.01"
            assert result["verified_by"] == "write_gate"
            assert "is_current" in result

    def test_assertion_unique_constraint(self, test_document_with_chunk, rag_app):
        """Test unique constraint on assertion."""
        from app.web.db import db
        from app.web.db.models.document import VerifiedAssertion
        from sqlalchemy.exc import IntegrityError
        import uuid

        with rag_app.app_context():
            # Create first assertion
            assertion1 = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                material="steel",
                assertion_type="IN_SCOPE",
                effective_start=date.today(),
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="Test",
                evidence_quote_hash="abc",
            )
            db.session.add(assertion1)
            db.session.commit()

            # Try to create duplicate
            assertion2 = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",  # Same
                hts_code_norm="85444290",  # Same
                hts_digits=8,
                material="steel",  # Same
                assertion_type="IN_SCOPE",  # Same
                effective_start=date.today(),  # Same
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="Test 2",
                evidence_quote_hash="def",
            )
            db.session.add(assertion2)

            with pytest.raises(IntegrityError):
                db.session.commit()
