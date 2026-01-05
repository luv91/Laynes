"""
Integration tests for v10.0 Legal-Grade Tariff Data System.

Tests the full pipeline:
- Document ingestion → Chunking → Storage
- RAG retrieval → Reader LLM → Validator LLM → Write Gate
- Verified Assertion creation and lookup
- Discovery mode trigger
"""

import hashlib
import uuid
from datetime import date, datetime
from unittest.mock import Mock, patch

import pytest


class TestDocumentIngestionPipeline:
    """Integration tests for document ingestion pipeline."""

    def test_full_document_ingestion(self, rag_app):
        """Test ingesting a document through the full pipeline."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk
        from app.ingestion.chunker import DocumentChunker

        with rag_app.app_context():
            # Simulate connector result
            doc_id = str(uuid.uuid4())
            raw_content = """
            CSMS Bulletin #65794272

            Section 232 Steel Tariff Update

            The following HTS codes are subject to Section 232 steel tariffs:

            8544.42.9090 - Electrical conductors, for a voltage exceeding 1,000 V
            8501.10.20 - Electric motors and generators

            Claim code: 9903.78.01

            Effective date: March 15, 2025
            """

            # Create document
            doc = Document(
                id=doc_id,
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                canonical_id="CSMS#65794272",
                url_canonical="https://content.govdelivery.com/accounts/USDHSCBP/bulletins/65794272",
                title="Section 232 Steel Tariff Update",
                sha256_raw=hashlib.sha256(raw_content.encode()).hexdigest(),
                extracted_text=raw_content,
                hts_codes_mentioned=["8544.42.9090", "8501.10.20"],
                programs_mentioned=["section_232_steel"],
            )
            db.session.add(doc)
            db.session.flush()

            # Chunk the document
            chunker = DocumentChunker(min_chunk_size=100, max_chunk_size=500)
            chunks = chunker.chunk_text(raw_content, doc_id)

            # Store chunks
            for chunk in chunks:
                db_chunk = DocumentChunk(
                    id=chunk.id,
                    document_id=doc_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    text_hash=chunk.text_hash,
                )
                db.session.add(db_chunk)

            db.session.commit()

            # Verify document stored
            stored_doc = db.session.query(Document).filter_by(id=doc_id).first()
            assert stored_doc is not None
            assert stored_doc.source == "CSMS"
            assert stored_doc.tier == "A"
            assert "8544.42.9090" in stored_doc.hts_codes_mentioned

            # Verify chunks stored
            stored_chunks = db.session.query(DocumentChunk).filter_by(document_id=doc_id).all()
            assert len(stored_chunks) > 0

            # Verify chunk contains HTS code
            combined_text = " ".join([c.text for c in stored_chunks])
            assert "8544.42.9090" in combined_text


class TestRAGPipelineIntegration:
    """Integration tests for the full RAG pipeline."""

    def test_cache_hit_flow(self, rag_app, test_document_with_chunk):
        """Test the flow when cache hit occurs."""
        from app.web.db import db
        from app.web.db.models.document import VerifiedAssertion
        from app.rag.orchestrator import RAGOrchestrator

        with rag_app.app_context():
            # Create a verified assertion
            assertion_id = str(uuid.uuid4())
            assertion = VerifiedAssertion(
                id=assertion_id,
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                material="steel",
                assertion_type="IN_SCOPE",
                claim_code="9903.78.01",
                effective_start=date.today(),
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="8544.42.9090 is in scope",
                evidence_quote_hash=hashlib.sha256(b"8544.42.9090 is in scope").hexdigest(),
            )
            db.session.add(assertion)
            db.session.commit()

            # Create orchestrator and verify
            with patch('app.rag.orchestrator.ReaderLLM'), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)
                result = orchestrator.verify_scope(
                    hts_code="8544.42.90",
                    program_id="section_232_steel",
                    material="steel",
                )

            # Should hit cache
            assert result.success is True
            assert result.source == "verified_cache"
            assert result.is_verified is True
            assert result.in_scope is True
            assert "9903.78.01" in result.claim_codes


class TestWriteGateIntegration:
    """Integration tests for Write Gate with database."""

    def test_write_gate_full_check(self, rag_app, sample_document_data, sample_chunk_data):
        """Test Write Gate with real database records."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk
        from app.rag.write_gate import WriteGate

        with rag_app.app_context():
            # Create document
            doc = Document(
                id=sample_document_data["id"],
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                url_canonical="https://example.com",
                sha256_raw=sample_document_data["sha256_raw"],
                extracted_text="Section 232 steel tariff applies to HTS 8544.42.9090",
            )
            db.session.add(doc)
            db.session.flush()

            # Create chunk
            chunk = DocumentChunk(
                id=sample_chunk_data["id"],
                document_id=doc.id,
                chunk_index=0,
                text="Section 232 steel tariff applies to HTS 8544.42.9090",
            )
            db.session.add(chunk)
            db.session.commit()

            # Create Write Gate and check
            gate = WriteGate(db.session)

            reader_output = {
                "answer": {"in_scope": True},
                "citations": [
                    {
                        "document_id": doc.id,
                        "chunk_id": chunk.id,
                        "quote": "HTS 8544.42.9090",
                    }
                ],
            }
            validator_output = {"verified": True}

            result = gate.check(reader_output, validator_output)

            assert result.passed is True
            assert len(result.errors) == 0


class TestNeedsReviewQueueIntegration:
    """Integration tests for needs_review_queue."""

    def test_queue_entry_creation(self, rag_app):
        """Test creating a needs_review entry."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import NeedsReviewQueue

        with rag_app.app_context():
            entry = NeedsReviewQueue(
                id=str(uuid.uuid4()),
                hts_code="8544.42.9090",
                query_type="section_232_steel",
                material="steel",
                reader_output={"answer": {"in_scope": None}},
                validator_output=None,
                block_reason="no_chunks_found",
                block_details={"message": "No relevant documents"},
                status="pending",
                priority=0,
            )
            db.session.add(entry)
            db.session.commit()

            # Verify stored
            stored = db.session.query(NeedsReviewQueue).filter_by(
                hts_code="8544.42.9090"
            ).first()
            assert stored is not None
            assert stored.block_reason == "no_chunks_found"
            assert stored.status == "pending"


class TestEndToEndScenarios:
    """End-to-end scenario tests."""

    def test_in_scope_determination(self, rag_app):
        """Test determining HTS code is IN_SCOPE."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk, VerifiedAssertion

        with rag_app.app_context():
            # Setup: Create document and chunk
            doc_id = str(uuid.uuid4())
            chunk_id = str(uuid.uuid4())

            doc = Document(
                id=doc_id,
                source="CSMS",
                tier="A",
                connector_name="csms_connector",
                url_canonical="https://cbp.gov/csms/123",
                sha256_raw="abc123",
                extracted_text="HTS 8544.42.9090 is subject to Section 232 steel tariffs. Claim code 9903.78.01.",
            )
            db.session.add(doc)

            chunk = DocumentChunk(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=0,
                text="HTS 8544.42.9090 is subject to Section 232 steel tariffs. Claim code 9903.78.01.",
            )
            db.session.add(chunk)

            # Create verified assertion
            assertion = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                assertion_type="IN_SCOPE",
                claim_code="9903.78.01",
                effective_start=date.today(),
                document_id=doc_id,
                chunk_id=chunk_id,
                evidence_quote="HTS 8544.42.9090 is subject to Section 232 steel tariffs",
                evidence_quote_hash=hashlib.sha256(b"HTS 8544.42.9090 is subject to Section 232 steel tariffs").hexdigest(),
                verified_by="write_gate",
            )
            db.session.add(assertion)
            db.session.commit()

            # Verify: Look up the assertion
            found = db.session.query(VerifiedAssertion).filter(
                VerifiedAssertion.hts_code_norm == "85444290",
                VerifiedAssertion.program_id == "section_232_steel",
                VerifiedAssertion.effective_end.is_(None),
            ).first()

            assert found is not None
            assert found.assertion_type == "IN_SCOPE"
            assert found.claim_code == "9903.78.01"
            assert found.is_current() is True

    def test_out_of_scope_determination(self, rag_app):
        """Test determining HTS code is OUT_OF_SCOPE (gap proof)."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk, VerifiedAssertion

        with rag_app.app_context():
            # Setup: Create document proving gap
            doc_id = str(uuid.uuid4())
            chunk_id = str(uuid.uuid4())

            doc = Document(
                id=doc_id,
                source="FEDERAL_REGISTER",
                tier="A",
                connector_name="govinfo_connector",
                url_canonical="https://federalregister.gov/documents/2025/01/15/2025-00123",
                sha256_raw="def456",
                extracted_text="Steel list covers HTS 8501 through 8504. Headings 8505 through 8543 are NOT covered.",
            )
            db.session.add(doc)

            chunk = DocumentChunk(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=0,
                text="Steel list covers HTS 8501 through 8504. Headings 8505 through 8543 are NOT covered.",
            )
            db.session.add(chunk)

            # Create OUT_OF_SCOPE assertion for HTS in gap
            assertion = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",
                hts_code_norm="85200000",  # In the gap
                hts_digits=8,
                assertion_type="OUT_OF_SCOPE",
                disclaim_code="9903.78.02",
                effective_start=date.today(),
                document_id=doc_id,
                chunk_id=chunk_id,
                evidence_quote="Headings 8505 through 8543 are NOT covered",
                evidence_quote_hash=hashlib.sha256(b"Headings 8505 through 8543 are NOT covered").hexdigest(),
                verified_by="write_gate",
            )
            db.session.add(assertion)
            db.session.commit()

            # Verify
            found = db.session.query(VerifiedAssertion).filter(
                VerifiedAssertion.hts_code_norm == "85200000",
                VerifiedAssertion.program_id == "section_232_steel",
            ).first()

            assert found is not None
            assert found.assertion_type == "OUT_OF_SCOPE"
            assert found.disclaim_code == "9903.78.02"


class TestMigrationIntegration:
    """Tests for database migration and table creation."""

    def test_all_tables_created(self, rag_app):
        """Test that all v10.0 tables are created."""
        from app.web.db import db
        from sqlalchemy import inspect

        with rag_app.app_context():
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()

            # Core tables
            assert "documents" in tables
            assert "document_chunks" in tables
            assert "verified_assertions" in tables
            assert "needs_review_queue" in tables

    def test_table_relationships(self, rag_app, test_document_with_chunk):
        """Test that table relationships work correctly."""
        from app.web.db import db
        from app.web.db.models.document import Document, DocumentChunk

        with rag_app.app_context():
            # Get document with chunks
            doc = db.session.query(Document).filter_by(
                id=test_document_with_chunk["document_id"]
            ).first()

            assert doc is not None
            assert len(doc.chunks) > 0
            assert doc.chunks[0].document_id == doc.id
