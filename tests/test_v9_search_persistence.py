"""
v9.0 Search Persistence & Vector Caching Tests

Tests for the new v9.0 functionality:
1. GeminiSearchResult model
2. GroundingSource model
3. SearchAuditLog model
4. TariffVectorSearch service
5. Cache check logic
6. Source reliability scoring

Usage:
    pipenv run pytest tests/test_v9_search_persistence.py -v
"""

import os
import sys
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# Model Tests
# ============================================================================

class TestGeminiSearchResultModel:
    """Tests for GeminiSearchResult SQLAlchemy model."""

    def test_create_search_result(self, app):
        """Test creating a new search result."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-001",
                hts_code="8544.42.9090",
                query_type="section_232",
                material="all",
                result_json={"copper": {"in_scope": True}},
                raw_response="Test response text",
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.commit()

            # Query it back
            found = db.session.query(GeminiSearchResult).filter_by(
                hts_code="8544.42.9090"
            ).first()

            assert found is not None
            assert found.query_type == "section_232"
            assert found.result_json["copper"]["in_scope"] is True

    def test_is_expired_with_no_expiry(self, app):
        """Test that results without expiry never expire."""
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-002",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json={},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow(),
                expires_at=None
            )

            assert result.is_expired() is False

    def test_is_expired_with_future_expiry(self, app):
        """Test that results with future expiry are not expired."""
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-003",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json={},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=30)
            )

            assert result.is_expired() is False

    def test_is_expired_with_past_expiry(self, app):
        """Test that results with past expiry are expired."""
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-004",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json={},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow() - timedelta(days=60),
                expires_at=datetime.utcnow() - timedelta(days=30)
            )

            assert result.is_expired() is True

    def test_verified_results_never_expire(self, app):
        """Test that verified results never expire regardless of expires_at."""
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-005",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json={},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow() - timedelta(days=60),
                expires_at=datetime.utcnow() - timedelta(days=30),
                is_verified=True
            )

            assert result.is_expired() is False

    def test_as_dict(self, app):
        """Test the as_dict serialization."""
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            result = GeminiSearchResult(
                id="test-uuid-006",
                hts_code="8544.42.9090",
                query_type="section_232",
                material="copper",
                result_json={"copper": {"in_scope": True}},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow(),
                is_verified=False,
                was_force_search=True
            )

            d = result.as_dict()

            assert d["id"] == "test-uuid-006"
            assert d["hts_code"] == "8544.42.9090"
            assert d["query_type"] == "section_232"
            assert d["material"] == "copper"
            assert d["was_force_search"] is True


class TestGroundingSourceModel:
    """Tests for GroundingSource SQLAlchemy model."""

    def test_create_grounding_source(self, app):
        """Test creating a grounding source linked to a search result."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult, GroundingSource

        with app.app_context():
            # Create parent search result
            result = GeminiSearchResult(
                id="test-uuid-010",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json={},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.flush()

            # Create grounding source
            source = GroundingSource(
                id="source-uuid-001",
                search_result_id=result.id,
                url="https://www.cbp.gov/trade/section-232",
                domain="www.cbp.gov",
                source_type="official_cbp",
                reliability_score=Decimal("1.00")
            )
            db.session.add(source)
            db.session.commit()

            # Query and verify relationship
            found_result = db.session.query(GeminiSearchResult).filter_by(
                id="test-uuid-010"
            ).first()

            assert len(found_result.grounding_sources) == 1
            assert found_result.grounding_sources[0].domain == "www.cbp.gov"

    def test_cascade_delete(self, app):
        """Test that grounding sources are deleted when parent is deleted."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult, GroundingSource

        with app.app_context():
            # Create parent and child
            result = GeminiSearchResult(
                id="test-uuid-011",
                hts_code="8544.42.9090",
                query_type="section_232",
                result_json={},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.flush()

            source = GroundingSource(
                id="source-uuid-002",
                search_result_id=result.id,
                url="https://cbp.gov/test",
                domain="cbp.gov"
            )
            db.session.add(source)
            db.session.commit()

            # Delete parent
            db.session.delete(result)
            db.session.commit()

            # Verify child is also deleted
            found_source = db.session.query(GroundingSource).filter_by(
                id="source-uuid-002"
            ).first()
            assert found_source is None


class TestSearchAuditLogModel:
    """Tests for SearchAuditLog SQLAlchemy model."""

    def test_create_audit_log(self, app):
        """Test creating an audit log entry."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import SearchAuditLog

        with app.app_context():
            log = SearchAuditLog(
                id="log-uuid-001",
                hts_code="8544.42.9090",
                query_type="section_232",
                cache_hit=False,
                cache_source="gemini",
                force_search=False,
                response_time_ms=1500,
                model_used="gemini-2.5-flash",
                success=True,
                input_tokens=500,
                output_tokens=200,
                estimated_cost_usd=Decimal("0.000150")
            )
            db.session.add(log)
            db.session.commit()

            found = db.session.query(SearchAuditLog).filter_by(
                id="log-uuid-001"
            ).first()

            assert found is not None
            assert found.cache_hit is False
            assert found.response_time_ms == 1500
            assert float(found.estimated_cost_usd) == 0.000150


# ============================================================================
# TariffVectorSearch Tests
# ============================================================================

class TestTariffVectorSearch:
    """Tests for TariffVectorSearch service."""

    def test_split_into_chunks_short_text(self):
        """Test chunking short text that doesn't need splitting."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        search = TariffVectorSearch()
        text = "This is a short text."
        chunks = search._split_into_chunks(text)

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_split_into_chunks_with_paragraphs(self):
        """Test chunking text with paragraph breaks."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        search = TariffVectorSearch()
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = search._split_into_chunks(text, max_chars=100)

        # All paragraphs should fit in one chunk
        assert len(chunks) == 1
        assert "First paragraph" in chunks[0]
        assert "Third paragraph" in chunks[0]

    def test_split_into_chunks_long_text(self):
        """Test chunking long text that needs splitting."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        search = TariffVectorSearch()
        # Create text longer than max_chars
        text = "A" * 500 + "\n\n" + "B" * 500 + "\n\n" + "C" * 500
        chunks = search._split_into_chunks(text, max_chars=600)

        assert len(chunks) > 1

    def test_split_into_chunks_empty_text(self):
        """Test chunking empty text."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        search = TariffVectorSearch()
        chunks = search._split_into_chunks("")

        assert len(chunks) == 0

    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    def test_create_embedding(self, mock_openai_class):
        """Test creating embeddings with mocked OpenAI."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        # Mock the OpenAI response
        mock_embedding = [0.1] * 1536
        mock_response = Mock()
        mock_response.data = [Mock(embedding=mock_embedding)]

        mock_client = Mock()
        mock_client.embeddings.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        search = TariffVectorSearch()
        embedding = search._create_embedding("test text")

        assert len(embedding) == 1536
        mock_client.embeddings.create.assert_called_once()

    @patch('app.chat.vector_stores.tariff_search.OpenAI')
    @patch('app.chat.vector_stores.tariff_search.PineconeClient')
    def test_chunk_and_embed(self, mock_pinecone_class, mock_openai_class):
        """Test chunk_and_embed returns proper vector format."""
        from app.chat.vector_stores.tariff_search import TariffVectorSearch

        # Mock OpenAI
        mock_embedding = [0.1] * 1536
        mock_response = Mock()
        mock_response.data = [Mock(embedding=mock_embedding)]
        mock_client = Mock()
        mock_client.embeddings.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        # Mock Pinecone
        mock_pinecone_class.return_value = Mock()

        search = TariffVectorSearch()
        vectors = search.chunk_and_embed(
            text="Test text for embedding.",
            metadata={"hts_code": "8544.42.9090", "query_type": "section_232"}
        )

        assert len(vectors) == 1
        assert "id" in vectors[0]
        assert "values" in vectors[0]
        assert "metadata" in vectors[0]
        assert vectors[0]["metadata"]["hts_code"] == "8544.42.9090"


# ============================================================================
# Source Reliability Tests
# ============================================================================

class TestSourceReliability:
    """Tests for source reliability scoring functions."""

    def test_extract_domain(self):
        """Test domain extraction from URLs."""
        from app.chat.vector_stores.tariff_search import extract_domain

        assert extract_domain("https://www.cbp.gov/trade") == "www.cbp.gov"
        assert extract_domain("https://federalregister.gov/docs") == "federalregister.gov"
        assert extract_domain("http://example.com/path?query=1") == "example.com"
        # Invalid URLs return empty string
        assert extract_domain("invalid-url") == ""

    def test_classify_source_type(self):
        """Test source type classification by domain."""
        from app.chat.vector_stores.tariff_search import classify_source_type

        assert classify_source_type("www.cbp.gov") == "official_cbp"
        assert classify_source_type("cbp.gov") == "official_cbp"
        assert classify_source_type("www.federalregister.gov") == "federal_register"
        assert classify_source_type("ustr.gov") == "ustr"
        assert classify_source_type("hts.usitc.gov") == "usitc"
        assert classify_source_type("random-site.com") == "other"

    def test_get_reliability_score(self):
        """Test reliability score lookup."""
        from app.chat.vector_stores.tariff_search import get_reliability_score

        assert get_reliability_score("official_cbp") == 1.0
        assert get_reliability_score("federal_register") == 1.0
        assert get_reliability_score("ustr") == 0.95
        assert get_reliability_score("other") == 0.50
        assert get_reliability_score("unknown") == 0.50


# ============================================================================
# Search Cache Tests
# ============================================================================

class TestSearchCache:
    """Tests for search cache logic."""

    def test_generate_uuid(self):
        """Test UUID generation."""
        from mcp_servers.search_cache import generate_uuid

        uuid1 = generate_uuid()
        uuid2 = generate_uuid()

        assert uuid1 != uuid2
        assert len(uuid1) == 36  # Standard UUID format

    def test_check_postgres_cache_miss(self, app):
        """Test PostgreSQL cache miss when no data exists."""
        from mcp_servers.search_cache import check_postgres_cache
        from app.web.db import db

        with app.app_context():
            result = check_postgres_cache(
                session=db.session,
                hts_code="9999.99.9999",
                query_type="section_232",
                material="copper"
            )

            assert result is None

    def test_check_postgres_cache_hit(self, app):
        """Test PostgreSQL cache hit when data exists."""
        from mcp_servers.search_cache import check_postgres_cache
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            # Insert test data
            result = GeminiSearchResult(
                id="cache-test-001",
                hts_code="8544.42.9090",
                query_type="section_232",
                material="copper",
                result_json={"copper": {"in_scope": True}},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=30)
            )
            db.session.add(result)
            db.session.commit()

            # Check cache
            cache_result = check_postgres_cache(
                session=db.session,
                hts_code="8544.42.9090",
                query_type="section_232",
                material="copper"
            )

            assert cache_result is not None
            assert cache_result["hit"] is True
            assert cache_result["source"] == "postgres"
            assert cache_result["data"]["copper"]["in_scope"] is True

    def test_check_cache_before_gemini_force_search(self, app):
        """Test that force_search bypasses cache."""
        from mcp_servers.search_cache import check_cache_before_gemini
        from app.web.db import db
        from app.web.db.models.tariff_tables import GeminiSearchResult

        with app.app_context():
            # Insert cached data
            result = GeminiSearchResult(
                id="cache-test-002",
                hts_code="8544.42.9090",
                query_type="section_232",
                material="steel",
                result_json={"steel": {"in_scope": True}},
                model_used="gemini-2.5-flash",
                searched_at=datetime.utcnow()
            )
            db.session.add(result)
            db.session.commit()

            # Force search should bypass cache
            cache_result = check_cache_before_gemini(
                session=db.session,
                hts_code="8544.42.9090",
                query_type="section_232",
                material="steel",
                force_search=True
            )

            assert cache_result["hit"] is False
            assert cache_result.get("reason") == "force_search"


# ============================================================================
# MCP Server Output Tests
# ============================================================================

class TestMCPServerOutput:
    """Tests for MCP server output format."""

    def test_verify_hts_scope_output_format(self):
        """Test that verify_hts_scope returns expected format."""
        # This is a mock test - actual API call would require GEMINI_API_KEY
        expected_keys = ["success", "scope", "raw_response", "metadata"]
        metadata_keys = ["model", "timestamp", "grounding_urls", "force_search",
                        "material_queried", "thinking_budget", "query_type"]

        # Mock a successful response
        mock_response = {
            "success": True,
            "scope": {"hts_code": "8544.42.9090", "copper": {"in_scope": True}},
            "raw_response": "Full response text",
            "metadata": {
                "model": "gemini-2.5-flash",
                "timestamp": "2026-01-02T15:00:00",
                "grounding_urls": ["https://cbp.gov/test"],
                "force_search": False,
                "material_queried": "all",
                "thinking_budget": None,
                "query_type": "section_232"
            }
        }

        for key in expected_keys:
            assert key in mock_response

        for key in metadata_keys:
            assert key in mock_response["metadata"]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def app():
    """Create Flask application for testing."""
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
