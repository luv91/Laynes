"""
v9.3 Evidence Quote Vector Indexing Tests

Tests for the v9.3 functionality:
1. index_evidence_quotes() method
2. Evidence quote metadata structure
3. search_similar() with new filters
4. EvidenceQuote persistence from search_cache

Usage:
    pipenv run pytest tests/test_vector_indexing.py -v
"""

import os
import sys
import pytest
import hashlib
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# Sample v9.2 Response Data
# ============================================================================

SAMPLE_V92_RESPONSE = {
    "hts_code": "8544.42.9090",
    "query_type": "section_232",
    "results": {
        "copper": {
            "in_scope": True,
            "claim_code": "9903.78.01",
            "disclaim_code": "9903.78.02",
            "citations": [
                {
                    "source_url": "https://www.cbp.gov/csms/65936570",
                    "source_title": "CBP CSMS #65936570",
                    "source_document": "CSMS #65936570",
                    "effective_date": "2025-08-18",
                    "location_hint": "Table row: 8544.42.90",
                    "evidence_type": "table",
                    "quoted_text": "8544.42.90 - Insulated copper wire for voltages exceeding 80V"
                }
            ]
        },
        "steel": {
            "in_scope": True,
            "claim_code": "9903.80.01",
            "disclaim_code": None,
            "citations": [
                {
                    "source_url": "https://www.federalregister.gov/documents/2025/08/15/steel-232",
                    "source_title": "Federal Register Steel 232 Update",
                    "source_document": "FR-2025-08-15",
                    "effective_date": "2025-08-18",
                    "location_hint": "Appendix A, Table 1",
                    "evidence_type": "table",
                    "quoted_text": "8544.42 - Electrical conductors with steel components"
                }
            ]
        },
        "aluminum": {
            "in_scope": None,  # Unknown
            "claim_code": None,
            "disclaim_code": None,
            "citations": []  # No citations for unknown
        }
    },
    "notes": "Test response"
}

SAMPLE_GROUNDING_URLS = [
    "https://www.cbp.gov/csms/65936570",
    "https://www.federalregister.gov/documents/2025/08/15/steel-232",
    "https://ustr.gov/section-301"
]


# ============================================================================
# TariffVectorSearch Tests
# ============================================================================

class TestIndexEvidenceQuotes:
    """Tests for index_evidence_quotes() method."""

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_index_evidence_quotes_creates_vectors(self, mock_openai, mock_pinecone):
        """Each citation with quoted_text creates a Pinecone vector."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        # Setup mocks
        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        # Create instance and call method
        vector_search = TariffVectorSearch()
        vector_search.index = mock_index  # Force index to be set

        count = vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json=SAMPLE_V92_RESPONSE,
            grounding_urls=SAMPLE_GROUNDING_URLS
        )

        # Should have created 2 vectors (copper and steel have quotes, aluminum has none)
        assert count == 2
        mock_index.upsert.assert_called_once()

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_chunk_type_is_evidence_quote(self, mock_openai, mock_pinecone):
        """Indexed chunks have chunk_type='evidence_quote'."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        # Setup mocks
        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json=SAMPLE_V92_RESPONSE,
            grounding_urls=SAMPLE_GROUNDING_URLS
        )

        # Get the vectors that were upserted
        call_args = mock_index.upsert.call_args
        vectors = call_args.kwargs.get('vectors') or call_args[1].get('vectors')

        for vector in vectors:
            assert vector["metadata"]["chunk_type"] == "evidence_quote"

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_metadata_includes_decision_fields(self, mock_openai, mock_pinecone):
        """Metadata includes in_scope, claim_code, material."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json=SAMPLE_V92_RESPONSE,
            grounding_urls=SAMPLE_GROUNDING_URLS
        )

        call_args = mock_index.upsert.call_args
        vectors = call_args.kwargs.get('vectors') or call_args[1].get('vectors')

        # Find the copper vector
        copper_vector = next(v for v in vectors if v["metadata"]["material"] == "copper")

        assert copper_vector["metadata"]["in_scope"] is True
        assert copper_vector["metadata"]["claim_code"] == "9903.78.01"
        assert copper_vector["metadata"]["material"] == "copper"
        assert copper_vector["metadata"]["hts_code"] == "8544.42.9090"

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_url_in_grounding_metadata_flag(self, mock_openai, mock_pinecone):
        """url_in_grounding_metadata is True when URL matches grounding sources."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json=SAMPLE_V92_RESPONSE,
            grounding_urls=SAMPLE_GROUNDING_URLS  # Contains the CBP URL
        )

        call_args = mock_index.upsert.call_args
        vectors = call_args.kwargs.get('vectors') or call_args[1].get('vectors')

        # Copper vector has URL in grounding
        copper_vector = next(v for v in vectors if v["metadata"]["material"] == "copper")
        assert copper_vector["metadata"]["url_in_grounding_metadata"] is True

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_citations_without_quoted_text_skipped(self, mock_openai, mock_pinecone):
        """Citations with quoted_text=null are not indexed."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        # Response with a citation that has no quoted_text
        response_with_no_quote = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://www.cbp.gov/test",
                            "quoted_text": None  # No quote
                        }
                    ]
                }
            }
        }

        count = vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json=response_with_no_quote,
            grounding_urls=[]
        )

        # Should have created 0 vectors
        assert count == 0
        mock_index.upsert.assert_not_called()

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_reliability_score_from_domain(self, mock_openai, mock_pinecone):
        """reliability_score computed correctly from source domain."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json=SAMPLE_V92_RESPONSE,
            grounding_urls=[]
        )

        call_args = mock_index.upsert.call_args
        vectors = call_args.kwargs.get('vectors') or call_args[1].get('vectors')

        # CBP domain should have reliability 1.0
        copper_vector = next(v for v in vectors if v["metadata"]["material"] == "copper")
        assert copper_vector["metadata"]["reliability_score"] == 1.0
        assert copper_vector["metadata"]["source_domain"] == "www.cbp.gov"

        # Federal Register should also have 1.0
        steel_vector = next(v for v in vectors if v["metadata"]["material"] == "steel")
        assert steel_vector["metadata"]["reliability_score"] == 1.0

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_empty_results_returns_zero(self, mock_openai, mock_pinecone):
        """Empty or missing results returns 0 and doesn't upsert."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_pinecone.return_value.Index.return_value = mock_index

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        # Empty results
        count = vector_search.index_evidence_quotes(
            search_result_id="test-uuid-123",
            hts_code="8544.42.9090",
            query_type="section_232",
            result_json={"hts_code": "8544.42.9090"},  # No results key
            grounding_urls=[]
        )

        assert count == 0
        mock_index.upsert.assert_not_called()


class TestSearchSimilarFilters:
    """Tests for search_similar() with new v9.3 filters."""

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_search_filters_by_chunk_type(self, mock_openai, mock_pinecone):
        """search_similar() can filter by chunk_type='evidence_quote'."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_index.query.return_value = MagicMock(matches=[])
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.search_similar(
            query="Section 232 copper for HTS 8544.42.9090",
            chunk_type="evidence_quote"
        )

        # Verify the filter was passed
        call_args = mock_index.query.call_args
        filter_dict = call_args.kwargs.get('filter') or call_args[1].get('filter')
        assert filter_dict["chunk_type"] == "evidence_quote"

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_search_filters_by_material(self, mock_openai, mock_pinecone):
        """search_similar() can filter by material='copper'."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_index.query.return_value = MagicMock(matches=[])
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.search_similar(
            query="Section 232 copper for HTS 8544.42.9090",
            material="copper"
        )

        call_args = mock_index.query.call_args
        filter_dict = call_args.kwargs.get('filter') or call_args[1].get('filter')
        assert filter_dict["material"] == "copper"

    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_search_combines_multiple_filters(self, mock_openai, mock_pinecone):
        """search_similar() combines multiple filters correctly."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        mock_index = MagicMock()
        mock_index.query.return_value = MagicMock(matches=[])
        mock_pinecone.return_value.Index.return_value = mock_index

        mock_embedding = MagicMock()
        mock_embedding.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.return_value.embeddings.create.return_value = mock_embedding

        vector_search = TariffVectorSearch()
        vector_search.index = mock_index

        vector_search.search_similar(
            query="Section 232 copper for HTS 8544.42.9090",
            hts_code="8544.42.9090",
            query_type="section_232",
            chunk_type="evidence_quote",
            material="copper"
        )

        call_args = mock_index.query.call_args
        filter_dict = call_args.kwargs.get('filter') or call_args[1].get('filter')
        assert filter_dict["hts_code"] == "8544.42.9090"
        assert filter_dict["query_type"] == "section_232"
        assert filter_dict["chunk_type"] == "evidence_quote"
        assert filter_dict["material"] == "copper"


# ============================================================================
# EvidenceQuote Persistence Tests
# ============================================================================

class TestEvidenceQuotePersistence:
    """Tests for EvidenceQuote persistence from search_cache."""

    def test_persist_evidence_quotes_creates_records(self, app):
        """persist_evidence_quotes creates EvidenceQuote records."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult, EvidenceQuote
        from mcp_servers.search_cache import persist_evidence_quotes

        with app.app_context():
            # First create a parent search result
            result = GeminiSearchResult(
                id="test-uuid-parent",
                hts_code="8544.42.9090",
                query_type="section_232",
                material="all",
                result_json=SAMPLE_V92_RESPONSE,
                raw_response="Test",
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.commit()

            # Now persist evidence quotes
            count = persist_evidence_quotes(
                session=db.session,
                search_result_id="test-uuid-parent",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                grounding_urls=SAMPLE_GROUNDING_URLS
            )

            db.session.commit()

            # Should have created 2 quotes (copper and steel have citations)
            assert count == 2

            quotes = db.session.query(EvidenceQuote).filter_by(
                search_result_id="test-uuid-parent"
            ).all()

            assert len(quotes) == 2

    def test_quote_hash_is_computed(self, app):
        """quote_hash is computed correctly from quoted_text."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult, EvidenceQuote
        from mcp_servers.search_cache import persist_evidence_quotes

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-hash",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.commit()

            persist_evidence_quotes(
                session=db.session,
                search_result_id="test-uuid-hash",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                grounding_urls=[]
            )
            db.session.commit()

            quote = db.session.query(EvidenceQuote).filter_by(
                search_result_id="test-uuid-hash",
                material="copper"
            ).first()

            # Verify hash matches
            expected_hash = hashlib.sha256(
                "8544.42.90 - Insulated copper wire for voltages exceeding 80V".encode()
            ).hexdigest()

            assert quote.quote_hash == expected_hash

    def test_url_in_grounding_metadata_computed(self, app):
        """url_in_grounding_metadata is True when URL matches grounding sources."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult, EvidenceQuote
        from mcp_servers.search_cache import persist_evidence_quotes

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-grounding",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.commit()

            persist_evidence_quotes(
                session=db.session,
                search_result_id="test-uuid-grounding",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                grounding_urls=SAMPLE_GROUNDING_URLS  # Contains the CBP URL
            )
            db.session.commit()

            # Copper quote has URL in grounding
            copper_quote = db.session.query(EvidenceQuote).filter_by(
                search_result_id="test-uuid-grounding",
                material="copper"
            ).first()

            assert copper_quote.url_in_grounding_metadata is True

    def test_effective_date_parsed(self, app):
        """effective_date is parsed from string to date."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult, EvidenceQuote
        from mcp_servers.search_cache import persist_evidence_quotes
        from datetime import date

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-date",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.commit()

            persist_evidence_quotes(
                session=db.session,
                search_result_id="test-uuid-date",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=SAMPLE_V92_RESPONSE,
                grounding_urls=[]
            )
            db.session.commit()

            quote = db.session.query(EvidenceQuote).filter_by(
                search_result_id="test-uuid-date",
                material="copper"
            ).first()

            assert quote.effective_date == date(2025, 8, 18)

    def test_non_v92_response_returns_zero(self, app):
        """Non-v9.2 response (no results key) returns 0."""
        from app.web.db import db
        from mcp_servers.search_cache import persist_evidence_quotes

        with app.app_context():
            # Legacy response without results structure
            legacy_response = {
                "hts_code": "8544.42.9090",
                "copper": {"in_scope": True, "source": "CSMS bulletin"}
            }

            count = persist_evidence_quotes(
                session=db.session,
                search_result_id="test-uuid-legacy",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json=legacy_response,
                grounding_urls=[]
            )

            assert count == 0


# ============================================================================
# Helper Function Tests
# ============================================================================

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_extract_domain(self):
        """extract_domain extracts domain from URL."""
        from app.chat.vector_stores.tariff_search import extract_domain

        assert extract_domain("https://www.cbp.gov/path/to/page") == "www.cbp.gov"
        assert extract_domain("https://federalregister.gov/") == "federalregister.gov"
        # Empty URL returns empty string (urlparse behavior)
        assert extract_domain("") == ""

    def test_classify_source_type(self):
        """classify_source_type returns correct type for known domains."""
        from app.chat.vector_stores.tariff_search import classify_source_type

        assert classify_source_type("www.cbp.gov") == "official_cbp"
        assert classify_source_type("cbp.gov") == "official_cbp"
        assert classify_source_type("www.federalregister.gov") == "federal_register"
        assert classify_source_type("www.ustr.gov") == "ustr"
        assert classify_source_type("random-blog.com") == "other"

    def test_get_reliability_score(self):
        """get_reliability_score returns correct scores."""
        from app.chat.vector_stores.tariff_search import get_reliability_score

        assert get_reliability_score("official_cbp") == 1.0
        assert get_reliability_score("federal_register") == 1.0
        assert get_reliability_score("ustr") == 0.95
        assert get_reliability_score("other") == 0.50
        assert get_reliability_score("unknown") == 0.50
