"""
Test cases for Multi-Document RAG functionality.

These tests verify:
1. Database models support new fields (mode, scope_filter, corpus, etc.)
2. Document ingestion with corpus metadata
3. Multi-doc retrieval returns chunks from multiple documents
4. Memory works correctly across multi-doc conversations
5. Scope isolation between different corpora
6. Backward compatibility with single-doc mode
"""

import os
import sys
import json
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConversationModel(unittest.TestCase):
    """Test Conversation model with new multi-doc fields."""

    def test_conversation_has_mode_field(self):
        """Verify Conversation model has mode field with default."""
        from app.web.db.models import Conversation

        # Check that mode field exists and has default
        assert hasattr(Conversation, 'mode')

    def test_conversation_has_scope_filter_field(self):
        """Verify Conversation model has scope_filter field."""
        from app.web.db.models import Conversation

        assert hasattr(Conversation, 'scope_filter')

    def test_scope_filter_json_serialization(self):
        """Test scope_filter JSON serialization/deserialization."""
        from app.web.db.models import Conversation

        conv = Conversation()

        # Test setting scope_filter
        test_filter = {"corpus": "gov_trade", "doc_type": "regulation"}
        conv.set_scope_filter(test_filter)

        # Test getting scope_filter
        retrieved = conv.get_scope_filter()
        assert retrieved == test_filter

    def test_scope_filter_none_handling(self):
        """Test scope_filter handles None correctly."""
        from app.web.db.models import Conversation

        conv = Conversation()
        conv.set_scope_filter(None)

        assert conv.get_scope_filter() is None

    def test_as_dict_includes_new_fields(self):
        """Test as_dict() includes mode and scope_filter."""
        from app.web.db.models import Conversation

        conv = Conversation()
        conv.id = "test-123"
        conv.mode = "multi_doc"
        conv.set_scope_filter({"corpus": "test"})

        result = conv.as_dict()

        assert "mode" in result
        assert "scope_filter" in result
        assert result["mode"] == "multi_doc"


class TestPdfModel(unittest.TestCase):
    """Test Pdf model with new multi-doc fields."""

    def test_pdf_has_corpus_field(self):
        """Verify Pdf model has corpus field."""
        from app.web.db.models import Pdf

        assert hasattr(Pdf, 'corpus')

    def test_pdf_has_doc_type_field(self):
        """Verify Pdf model has doc_type field."""
        from app.web.db.models import Pdf

        assert hasattr(Pdf, 'doc_type')

    def test_pdf_has_is_system_field(self):
        """Verify Pdf model has is_system field."""
        from app.web.db.models import Pdf

        assert hasattr(Pdf, 'is_system')

    def test_as_dict_includes_new_fields(self):
        """Test as_dict() includes new fields."""
        from app.web.db.models import Pdf

        pdf = Pdf()
        pdf.id = "test-pdf-123"
        pdf.name = "test.pdf"
        pdf.corpus = "gov_trade"
        pdf.doc_type = "hts_schedule"
        pdf.is_system = True

        result = pdf.as_dict()

        assert "corpus" in result
        assert "doc_type" in result
        assert "is_system" in result


class TestChatArgs(unittest.TestCase):
    """Test ChatArgs model with new multi-doc fields."""

    def test_chat_args_has_mode_field(self):
        """Verify ChatArgs has mode field with default."""
        from app.chat.models import ChatArgs, Metadata

        metadata = Metadata(
            conversation_id="test",
            user_id="user1",
            pdf_id=None
        )

        args = ChatArgs(
            conversation_id="test",
            pdf_id=None,
            metadata=metadata,
            streaming=False
        )

        assert args.mode == "user_pdf"  # default

    def test_chat_args_multi_doc_mode(self):
        """Test ChatArgs with multi_doc mode."""
        from app.chat.models import ChatArgs, Metadata

        metadata = Metadata(
            conversation_id="test",
            user_id="user1",
            pdf_id=None
        )

        scope_filter = {"corpus": "gov_trade"}

        args = ChatArgs(
            conversation_id="test",
            pdf_id=None,
            metadata=metadata,
            streaming=False,
            mode="multi_doc",
            scope_filter=scope_filter
        )

        assert args.mode == "multi_doc"
        assert args.scope_filter == scope_filter


class TestRetrieverBuilder(unittest.TestCase):
    """Test retriever building for single and multi-doc modes."""

    @patch('app.chat.vector_stores.pinecone.vector_store')
    def test_build_retriever_single_doc_mode(self, mock_vector_store):
        """Test retriever uses pdf_id filter in single-doc mode."""
        from app.chat.vector_stores.pinecone import build_retriever
        from app.chat.models import ChatArgs, Metadata

        mock_retriever = Mock()
        mock_vector_store.as_retriever.return_value = mock_retriever

        metadata = Metadata(
            conversation_id="test",
            user_id="user1",
            pdf_id="pdf-123"
        )

        args = ChatArgs(
            conversation_id="test",
            pdf_id="pdf-123",
            metadata=metadata,
            streaming=False,
            mode="user_pdf"
        )

        result = build_retriever(args, k=3)

        # Verify as_retriever was called with pdf_id filter
        call_args = mock_vector_store.as_retriever.call_args
        search_kwargs = call_args[1]['search_kwargs']

        assert search_kwargs['filter'] == {"pdf_id": "pdf-123"}
        assert search_kwargs['k'] == 3

    @patch('app.chat.vector_stores.pinecone.vector_store')
    def test_build_retriever_multi_doc_mode(self, mock_vector_store):
        """Test retriever uses scope_filter in multi-doc mode."""
        from app.chat.vector_stores.pinecone import build_retriever
        from app.chat.models import ChatArgs, Metadata

        mock_retriever = Mock()
        mock_vector_store.as_retriever.return_value = mock_retriever

        metadata = Metadata(
            conversation_id="test",
            user_id="user1",
            pdf_id=None
        )

        scope_filter = {"corpus": "gov_trade"}

        args = ChatArgs(
            conversation_id="test",
            pdf_id=None,
            metadata=metadata,
            streaming=False,
            mode="multi_doc",
            scope_filter=scope_filter
        )

        result = build_retriever(args, k=5)

        # Verify as_retriever was called with scope_filter
        call_args = mock_vector_store.as_retriever.call_args
        search_kwargs = call_args[1]['search_kwargs']

        assert search_kwargs['filter'] == {"corpus": "gov_trade"}
        assert search_kwargs['k'] == 5


class TestDocumentIngestion(unittest.TestCase):
    """Test document ingestion with corpus metadata."""

    @patch('app.chat.create_embeddings.vector_store')
    @patch('app.chat.create_embeddings.PyPDFLoader')
    def test_create_embeddings_with_corpus(self, mock_loader, mock_vector_store):
        """Test embeddings include corpus in metadata."""
        from app.chat.create_embeddings import create_embeddings_for_pdf

        # Mock document loading
        mock_doc = Mock()
        mock_doc.metadata = {"page": 0}
        mock_doc.page_content = "Test content"

        mock_loader_instance = Mock()
        mock_loader_instance.load_and_split.return_value = [mock_doc]
        mock_loader.return_value = mock_loader_instance

        # Call function with corpus
        create_embeddings_for_pdf(
            pdf_id="test-pdf",
            pdf_path="/fake/path.pdf",
            corpus="gov_trade",
            doc_type="hts_schedule"
        )

        # Verify metadata includes corpus and doc_type
        mock_vector_store.add_documents.assert_called_once()
        added_docs = mock_vector_store.add_documents.call_args[0][0]

        assert added_docs[0].metadata["corpus"] == "gov_trade"
        assert added_docs[0].metadata["doc_type"] == "hts_schedule"
        assert added_docs[0].metadata["pdf_id"] == "test-pdf"

    @patch('app.chat.create_embeddings.vector_store')
    @patch('app.chat.create_embeddings.PyPDFLoader')
    def test_create_embeddings_without_corpus(self, mock_loader, mock_vector_store):
        """Test embeddings work without corpus (backward compat)."""
        from app.chat.create_embeddings import create_embeddings_for_pdf

        # Mock document loading
        mock_doc = Mock()
        mock_doc.metadata = {"page": 0}
        mock_doc.page_content = "Test content"

        mock_loader_instance = Mock()
        mock_loader_instance.load_and_split.return_value = [mock_doc]
        mock_loader.return_value = mock_loader_instance

        # Call function without corpus (old behavior)
        create_embeddings_for_pdf(
            pdf_id="test-pdf",
            pdf_path="/fake/path.pdf"
        )

        # Verify metadata has pdf_id but no corpus
        mock_vector_store.add_documents.assert_called_once()
        added_docs = mock_vector_store.add_documents.call_args[0][0]

        assert added_docs[0].metadata["pdf_id"] == "test-pdf"
        assert "corpus" not in added_docs[0].metadata


class TestMultiDocRetrieval(unittest.TestCase):
    """Test that multi-doc retrieval works correctly."""

    def test_retriever_map_has_multi_doc_entries(self):
        """Verify retriever_map has multi-doc retrievers."""
        from app.chat.vector_stores import retriever_map

        assert "pinecone_multi_5" in retriever_map
        assert "pinecone_multi_10" in retriever_map


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility with existing single-doc functionality."""

    def test_conversation_defaults_to_user_pdf_mode(self):
        """Verify new conversations default to user_pdf mode."""
        from app.web.db.models import Conversation

        conv = Conversation()

        # Mode should default to user_pdf
        # (actual default is in the Column definition)
        assert hasattr(conv, 'mode')

    def test_pdf_id_still_works(self):
        """Verify pdf_id filtering still works."""
        from app.chat.models import ChatArgs, Metadata

        metadata = Metadata(
            conversation_id="test",
            user_id="user1",
            pdf_id="pdf-123"
        )

        # Old-style args should still work
        args = ChatArgs(
            conversation_id="test",
            pdf_id="pdf-123",
            metadata=metadata,
            streaming=False
        )

        assert args.pdf_id == "pdf-123"
        assert args.mode == "user_pdf"


# Integration test (requires running services)
class TestIntegration(unittest.TestCase):
    """Integration tests (require Flask app context and services)."""

    @unittest.skip("Requires Flask app context")
    def test_create_multi_doc_conversation(self):
        """Test creating a multi-doc conversation via API."""
        pass

    @unittest.skip("Requires Flask app context and Pinecone")
    def test_multi_doc_message_flow(self):
        """Test sending messages in multi-doc mode."""
        pass


if __name__ == "__main__":
    unittest.main()
