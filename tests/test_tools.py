"""
Unit tests for trade tools.

Tests:
- Tool list contains all expected tools
- Tool function signatures
- Tool error handling (mocked)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from langchain_core.documents import Document

from app.chat.tools import (
    search_documents,
    lookup_hts_code,
    check_tariffs,
    check_agency_requirements,
    TRADE_TOOLS,
    get_vector_store,
    reset_vector_store,
)
from app.chat.tools.trade_tools import _vector_store


class TestTradeToolsList:
    """Test the TRADE_TOOLS list."""

    def test_trade_tools_count(self):
        """Test that TRADE_TOOLS has 4 tools."""
        assert len(TRADE_TOOLS) == 4

    def test_trade_tools_names(self):
        """Test tool names in TRADE_TOOLS."""
        tool_names = [t.name for t in TRADE_TOOLS]
        assert "search_documents" in tool_names
        assert "lookup_hts_code" in tool_names
        assert "check_tariffs" in tool_names
        assert "check_agency_requirements" in tool_names

    def test_tools_have_descriptions(self):
        """Test that all tools have descriptions."""
        for tool in TRADE_TOOLS:
            assert tool.description is not None
            assert len(tool.description) > 0


class TestToolMetadata:
    """Test tool metadata and signatures."""

    def test_search_documents_params(self):
        """Test search_documents parameter schema."""
        schema = search_documents.args_schema.model_json_schema()
        properties = schema.get("properties", {})

        assert "query" in properties
        assert "doc_type" in properties
        assert "max_results" in properties

    def test_lookup_hts_code_params(self):
        """Test lookup_hts_code parameter schema."""
        schema = lookup_hts_code.args_schema.model_json_schema()
        properties = schema.get("properties", {})

        assert "product_description" in properties

    def test_check_tariffs_params(self):
        """Test check_tariffs parameter schema."""
        schema = check_tariffs.args_schema.model_json_schema()
        properties = schema.get("properties", {})

        assert "hts_code" in properties
        assert "country_of_origin" in properties

    def test_check_agency_requirements_params(self):
        """Test check_agency_requirements parameter schema."""
        schema = check_agency_requirements.args_schema.model_json_schema()
        properties = schema.get("properties", {})

        assert "product_type" in properties
        assert "agencies" in properties


class TestToolFunctions:
    """Test tool functions with mocked vector store."""

    @pytest.fixture(autouse=True)
    def reset_store(self):
        """Reset vector store before each test."""
        reset_vector_store()
        yield
        reset_vector_store()

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        mock_store = Mock()
        mock_retriever = Mock()
        mock_store.as_retriever.return_value = mock_retriever
        return mock_store, mock_retriever

    def test_search_documents_no_results(self, mock_vector_store):
        """Test search_documents when no documents found."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = []

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = search_documents.invoke({"query": "test query"})

        assert "No relevant documents found" in result

    def test_search_documents_with_results(self, mock_vector_store):
        """Test search_documents with results."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = [
            Document(
                page_content="LED lamps HTS code 8539.50.00",
                metadata={"pdf_id": "hts-001", "doc_type": "hts_schedule", "page": 10}
            )
        ]

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = search_documents.invoke({"query": "LED lamps HTS"})

        assert "hts-001" in result
        assert "hts_schedule" in result

    def test_lookup_hts_code_no_results(self, mock_vector_store):
        """Test lookup_hts_code when no HTS code found."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = []

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = lookup_hts_code.invoke({"product_description": "magic beans"})

        assert "No HTS code found" in result
        assert "magic beans" in result

    def test_lookup_hts_code_with_results(self, mock_vector_store):
        """Test lookup_hts_code with results."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = [
            Document(
                page_content="8539.50.00 Light-emitting diode (LED) lamps",
                metadata={"pdf_id": "hts-schedule", "doc_type": "hts_schedule"}
            )
        ]

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = lookup_hts_code.invoke({"product_description": "LED lamps"})

        assert "8539.50.00" in result
        assert "hts-schedule" in result

    def test_check_tariffs_no_results(self, mock_vector_store):
        """Test check_tariffs when no tariff info found."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = []

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = check_tariffs.invoke({
                "hts_code": "8539.50.00",
                "country_of_origin": "China"
            })

        assert "No specific tariff information found" in result
        assert "8539.50.00" in result
        assert "China" in result

    def test_check_tariffs_with_results(self, mock_vector_store):
        """Test check_tariffs with results."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = [
            Document(
                page_content="Duty rate 3.9% plus Section 301 tariffs 25%",
                metadata={"pdf_id": "tariff-notice-301", "doc_type": "tariff_notice"}
            )
        ]

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = check_tariffs.invoke({
                "hts_code": "8539.50.00",
                "country_of_origin": "China"
            })

        assert "3.9%" in result
        assert "tariff-notice-301" in result

    def test_check_agency_requirements_no_results(self, mock_vector_store):
        """Test check_agency_requirements when no requirements found."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = []

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = check_agency_requirements.invoke({"product_type": "alien artifacts"})

        assert "No agency requirements found" in result

    def test_check_agency_requirements_with_results(self, mock_vector_store):
        """Test check_agency_requirements with results."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = [
            Document(
                page_content="DOE energy efficiency certification required for LED lamps",
                metadata={"pdf_id": "doe-regs", "doc_type": "agency_regulation"}
            ),
            Document(
                page_content="FCC Part 15 compliance for electronic devices",
                metadata={"pdf_id": "fcc-regs", "doc_type": "agency_regulation"}
            )
        ]

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            result = check_agency_requirements.invoke({
                "product_type": "LED lamps",
                "agencies": ["DOE", "FCC"]
            })

        assert "doe-regs" in result
        assert "fcc-regs" in result

    def test_search_documents_with_doc_type_filter(self, mock_vector_store):
        """Test search_documents applies doc_type filter."""
        mock_store, mock_retriever = mock_vector_store
        mock_retriever.invoke.return_value = []

        with patch('app.chat.tools.trade_tools.get_vector_store', return_value=mock_store):
            search_documents.invoke({
                "query": "test",
                "doc_type": "hts_schedule",
                "max_results": 3
            })

        # Check that as_retriever was called with filter
        mock_store.as_retriever.assert_called_once()
        call_kwargs = mock_store.as_retriever.call_args[1]
        assert call_kwargs["search_kwargs"]["filter"]["doc_type"] == "hts_schedule"
        assert call_kwargs["search_kwargs"]["k"] == 3
