"""
Unit tests for RAG Orchestrator (v10.0 Phase 3).

Tests:
- Verified assertion cache lookup
- Chunk retrieval
- Full RAG pipeline coordination
- Error handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date


class TestRAGOrchestrator:
    """Tests for the RAGOrchestrator class."""

    def test_normalize_hts(self, rag_app):
        """Test HTS code normalization."""
        from app.web.db import db
        from app.rag.orchestrator import RAGOrchestrator

        with rag_app.app_context():
            with patch('app.rag.orchestrator.ReaderLLM'), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)

                # With dots (10 digits)
                assert orchestrator._normalize_hts("8544.42.9090") == "8544429090"

                # With dashes (10 digits)
                assert orchestrator._normalize_hts("8544-42-9090") == "8544429090"

                # Already normalized
                assert orchestrator._normalize_hts("85444290") == "85444290"

                # With spaces
                assert orchestrator._normalize_hts(" 8544.42.90 ") == "85444290"

    def test_check_verified_cache_hit(self, test_document_with_chunk, rag_app):
        """Test verified assertion cache hit."""
        from app.web.db import db
        from app.web.db.models.document import VerifiedAssertion
        from app.rag.orchestrator import RAGOrchestrator
        import uuid
        import hashlib

        with rag_app.app_context():
            # Create a verified assertion
            assertion = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                material="steel",
                assertion_type="IN_SCOPE",
                claim_code="9903.78.01",
                effective_start=date.today(),
                effective_end=None,  # Current
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="Test quote",
                evidence_quote_hash=hashlib.sha256(b"Test quote").hexdigest(),
            )
            db.session.add(assertion)
            db.session.commit()

            with patch('app.rag.orchestrator.ReaderLLM'), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)
                result = orchestrator._check_verified_cache(
                    "85444290", "section_232_steel", "steel"
                )

            assert result is not None
            assert result.source == "verified_cache"
            assert result.is_verified is True
            assert result.in_scope is True

    def test_check_verified_cache_miss(self, rag_app):
        """Test verified assertion cache miss."""
        from app.web.db import db
        from app.rag.orchestrator import RAGOrchestrator

        with rag_app.app_context():
            with patch('app.rag.orchestrator.ReaderLLM'), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)
                result = orchestrator._check_verified_cache(
                    "99999999", "section_232_steel", None
                )

            assert result is None


class TestRAGResult:
    """Tests for the RAGResult dataclass."""

    def test_rag_result_to_dict(self):
        """Test RAGResult to_dict method."""
        from app.rag.orchestrator import RAGResult

        result = RAGResult(
            success=True,
            source="rag_verified",
            is_verified=True,
            in_scope=True,
            claim_codes=["9903.78.01"],
            disclaim_codes=[],
            confidence="high",
            evidence_quote="HTS 8544.42.9090 is in scope for Section 232 steel",
            document_id="doc-001",
            verified_assertion_id="assertion-001",
        )

        output = result.to_dict()

        assert output["success"] is True
        assert output["source"] == "rag_verified"
        assert output["is_verified"] is True
        assert output["in_scope"] is True
        assert "9903.78.01" in output["claim_codes"]

    def test_rag_result_truncate_evidence(self):
        """Test that long evidence quotes are truncated."""
        from app.rag.orchestrator import RAGResult

        long_quote = "A" * 500  # 500 characters

        result = RAGResult(
            success=True,
            source="rag_verified",
            is_verified=True,
            evidence_quote=long_quote,
        )

        output = result.to_dict()

        # Should be truncated to 200 chars + "..."
        assert len(output["evidence_quote"]) <= 204
        assert output["evidence_quote"].endswith("...")

    def test_rag_result_failure(self):
        """Test RAGResult for failure case."""
        from app.rag.orchestrator import RAGResult

        result = RAGResult(
            success=False,
            source="discovery_needed",
            is_verified=False,
            error="No relevant documents found",
            review_queue_id="queue-001",
        )

        output = result.to_dict()

        assert output["success"] is False
        assert output["source"] == "discovery_needed"
        assert output["error"] == "No relevant documents found"
        assert output["review_queue_id"] == "queue-001"


class TestVerifyScope:
    """Tests for the verify_scope main entry point."""

    def test_verify_scope_cache_hit(self, test_document_with_chunk, rag_app):
        """Test verify_scope with cache hit."""
        from app.web.db import db
        from app.web.db.models.document import VerifiedAssertion
        from app.rag.orchestrator import RAGOrchestrator
        import uuid
        import hashlib

        with rag_app.app_context():
            # Create a verified assertion
            assertion = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                assertion_type="IN_SCOPE",
                claim_code="9903.78.01",
                effective_start=date.today(),
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="Test quote",
                evidence_quote_hash=hashlib.sha256(b"Test quote").hexdigest(),
            )
            db.session.add(assertion)
            db.session.commit()

            with patch('app.rag.orchestrator.ReaderLLM'), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)
                result = orchestrator.verify_scope(
                    hts_code="8544.42.90",
                    program_id="section_232_steel",
                )

            assert result.success is True
            assert result.source == "verified_cache"
            assert result.is_verified is True

    def test_verify_scope_force_rag(self, test_document_with_chunk, rag_app):
        """Test verify_scope with force_rag=True skips cache."""
        from app.web.db import db
        from app.web.db.models.document import VerifiedAssertion
        from app.rag.orchestrator import RAGOrchestrator
        import uuid
        import hashlib

        with rag_app.app_context():
            # Create a verified assertion
            assertion = VerifiedAssertion(
                id=str(uuid.uuid4()),
                program_id="section_232_steel",
                hts_code_norm="85444290",
                hts_digits=8,
                assertion_type="IN_SCOPE",
                effective_start=date.today(),
                document_id=test_document_with_chunk["document_id"],
                evidence_quote="Test quote",
                evidence_quote_hash=hashlib.sha256(b"Test quote").hexdigest(),
            )
            db.session.add(assertion)
            db.session.commit()

            # Mock the components
            mock_reader = Mock()
            mock_reader.read.return_value = Mock(
                success=False,
                error="Test error",
                to_dict=lambda: {"success": False, "error": "Test error"}
            )

            with patch('app.rag.orchestrator.ReaderLLM', return_value=mock_reader), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)

                # Mock _retrieve_chunks to return empty (triggers discovery_needed)
                with patch.object(orchestrator, '_retrieve_chunks', return_value=[]):
                    result = orchestrator.verify_scope(
                        hts_code="8544.42.90",
                        program_id="section_232_steel",
                        force_rag=True,  # Skip cache
                    )

            # Should not hit cache, should go to discovery_needed
            assert result.source == "discovery_needed"


class TestOrchestratorErrorHandling:
    """Tests for orchestrator error handling."""

    def test_no_chunks_found(self, rag_app):
        """Test handling when no chunks are found."""
        from app.web.db import db
        from app.rag.orchestrator import RAGOrchestrator

        with rag_app.app_context():
            with patch('app.rag.orchestrator.ReaderLLM'), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)

                # Mock _retrieve_chunks to return empty
                with patch.object(orchestrator, '_retrieve_chunks', return_value=[]):
                    result = orchestrator.verify_scope(
                        hts_code="9999.99.9999",
                        program_id="section_232_steel",
                    )

            assert result.success is False
            assert result.source == "discovery_needed"
            assert "No relevant documents" in result.error

    def test_reader_failure(self, rag_app):
        """Test handling when Reader LLM fails."""
        from app.web.db import db
        from app.rag.orchestrator import RAGOrchestrator

        with rag_app.app_context():
            mock_reader = Mock()
            mock_reader.read.return_value = Mock(
                success=False,
                error="Reader failed",
                to_dict=lambda: {"success": False, "error": "Reader failed"}
            )

            with patch('app.rag.orchestrator.ReaderLLM', return_value=mock_reader), \
                 patch('app.rag.orchestrator.ValidatorLLM'), \
                 patch('app.rag.orchestrator.WriteGate'):
                orchestrator = RAGOrchestrator(db.session)

                # Mock _retrieve_chunks to return some chunks
                mock_chunks = [{"document_id": "doc-1", "chunk_id": "chunk-1", "text": "test"}]
                with patch.object(orchestrator, '_retrieve_chunks', return_value=mock_chunks):
                    result = orchestrator.verify_scope(
                        hts_code="8544.42.9090",
                        program_id="section_232_steel",
                    )

            assert result.success is False
            assert result.source == "rag_pending"
            assert "Reader failed" in result.error
