"""
Pytest fixtures for v10.0 Legal-Grade Tariff Data System tests.

Provides:
- RAG-specific fixtures for Document, DocumentChunk, VerifiedAssertion
- Mock fixtures for Reader LLM, Validator LLM
- Sample data fixtures for testing
"""

import hashlib
import os
import uuid
from datetime import date, datetime
from unittest.mock import Mock, patch

import pytest

# Set testing environment
os.environ["TESTING"] = "true"
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"


# ============================================================================
# Sample Data Fixtures
# ============================================================================

@pytest.fixture
def sample_document_data():
    """Sample document data for testing."""
    return {
        "id": str(uuid.uuid4()),
        "source": "CSMS",
        "tier": "A",
        "connector_name": "csms_connector",
        "canonical_id": "CSMS#65794272",
        "url_canonical": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/65794272",
        "title": "Section 232 Steel Scope Update",
        "published_at": datetime.utcnow(),
        "effective_start": date.today(),
        "sha256_raw": hashlib.sha256(b"test content").hexdigest(),
        "raw_content": "<html><body>Test content about steel tariffs and HTS codes 8544.42.9090</body></html>",
        "extracted_text": "Test content about steel tariffs and HTS codes 8544.42.9090. Section 232 applies to these products. The applicable claim code is 9903.78.01.",
        "hts_codes_mentioned": ["8544.42.9090"],
        "programs_mentioned": ["section_232_steel"],
    }


@pytest.fixture
def sample_chunk_data(sample_document_data):
    """Sample chunk data for testing."""
    return {
        "id": str(uuid.uuid4()),
        "document_id": sample_document_data["id"],
        "chunk_index": 0,
        "text": "Test content about steel tariffs and HTS codes 8544.42.9090. Section 232 applies to these products.",
        "char_start": 0,
        "char_end": 100,
        "text_hash": hashlib.sha256(b"Test content about steel tariffs").hexdigest(),
        "embedding_id": "pinecone_vec_123",
        "metadata": {"page": 1, "section": "main"},
    }


@pytest.fixture
def sample_verified_assertion_data(sample_document_data, sample_chunk_data):
    """Sample verified assertion data for testing."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": "section_232_steel",
        "hts_code_norm": "85444290",
        "hts_digits": 8,
        "material": "steel",
        "assertion_type": "IN_SCOPE",
        "claim_code": "9903.78.01",
        "disclaim_code": None,
        "effective_start": date.today(),
        "effective_end": None,
        "document_id": sample_document_data["id"],
        "chunk_id": sample_chunk_data["id"],
        "evidence_quote": "Section 232 applies to HTS 8544.42.9090",
        "evidence_quote_hash": hashlib.sha256(b"Section 232 applies to HTS 8544.42.9090").hexdigest(),
    }


@pytest.fixture
def sample_chunks():
    """Sample chunks for Reader/Validator LLM testing."""
    return [
        {
            "document_id": "doc-001",
            "chunk_id": "chunk-001",
            "text": """CSMS #65794272 - Section 232 Steel Scope

The following HTS codes are subject to Section 232 steel tariffs:
8544.42.9090 - Electrical conductors, copper
9903.78.01 - Claim code for Section 232 steel exclusions

Effective date: March 15, 2025""",
            "source": "CSMS",
            "score": 0.95,
        },
        {
            "document_id": "doc-002",
            "chunk_id": "chunk-002",
            "text": """Federal Register Notice 90 FR 40326

Section 232 Tariffs - Steel and Aluminum Products

HTS headings 8501 through 8544 are covered under the steel provisions.
Products classified under 8544.42.9090 require claim code 9903.78.01.""",
            "source": "FEDERAL_REGISTER",
            "score": 0.89,
        }
    ]


@pytest.fixture
def sample_reader_output():
    """Sample Reader LLM output for testing."""
    return {
        "success": True,
        "answer": {
            "in_scope": True,
            "program": "section_232_steel",
            "hts_code": "8544.42.9090",
            "claim_codes": ["9903.78.01"],
            "disclaim_codes": [],
            "confidence": "high",
        },
        "citations": [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "quote": "8544.42.9090 - Electrical conductors, copper",
                "why_this_supports": "HTS code is explicitly listed in the CSMS bulletin",
            }
        ],
        "missing_info": [],
        "contradictions": [],
        "error": None,
    }


@pytest.fixture
def sample_validator_output():
    """Sample Validator LLM output for testing."""
    return {
        "success": True,
        "verified": True,
        "failures": [],
        "required_fixes": [],
        "confidence": "high",
        "error": None,
    }


# ============================================================================
# Mock LLM Fixtures
# ============================================================================

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for Reader/Validator LLM testing."""
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = """{
        "answer": {
            "in_scope": true,
            "program": "section_232_steel",
            "hts_code": "8544.42.9090",
            "claim_codes": ["9903.78.01"],
            "disclaim_codes": [],
            "confidence": "high"
        },
        "citations": [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "quote": "8544.42.9090 - Electrical conductors",
                "why_this_supports": "HTS code is listed"
            }
        ],
        "missing_info": [],
        "contradictions": []
    }"""

    mock_client = Mock()
    mock_client.chat.completions.create.return_value = mock_response

    return mock_client


@pytest.fixture
def mock_validator_client():
    """Mock OpenAI client for Validator LLM testing."""
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = """{
        "verified": true,
        "failures": [],
        "required_fixes": [],
        "confidence": "high"
    }"""

    mock_client = Mock()
    mock_client.chat.completions.create.return_value = mock_response

    return mock_client


# ============================================================================
# Database Model Fixtures
# ============================================================================

@pytest.fixture
def rag_app():
    """Create Flask application for RAG testing."""
    from app.web import create_app
    from app.web.db import db

    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SECRET_KEY": "test-secret-key",
    })

    with app.app_context():
        # Import models to register them
        from app.web.db.models.document import Document, DocumentChunk, VerifiedAssertion
        from app.web.db.models.tariff_tables import NeedsReviewQueue

        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def rag_db_session(rag_app):
    """Database session for RAG tests."""
    from app.web.db import db
    with rag_app.app_context():
        yield db.session


@pytest.fixture
def test_document(rag_app, sample_document_data):
    """Create a test document in the database."""
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
        return {"id": doc.id, "source": doc.source, "tier": doc.tier}


@pytest.fixture
def test_document_with_chunk(rag_app, sample_document_data, sample_chunk_data):
    """Create a test document with a chunk in the database."""
    from app.web.db import db
    from app.web.db.models.document import Document, DocumentChunk

    with rag_app.app_context():
        # Create document
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
        db.session.flush()

        # Create chunk
        chunk = DocumentChunk(
            id=sample_chunk_data["id"],
            document_id=doc.id,
            chunk_index=sample_chunk_data["chunk_index"],
            text=sample_chunk_data["text"],
            char_start=sample_chunk_data["char_start"],
            char_end=sample_chunk_data["char_end"],
        )
        db.session.add(chunk)
        db.session.commit()

        return {
            "document_id": doc.id,
            "chunk_id": chunk.id,
            "chunk_text": chunk.text,
        }


# ============================================================================
# Connector Fixtures
# ============================================================================

@pytest.fixture
def mock_requests_session():
    """Mock requests session for connector testing."""
    with patch('requests.Session') as mock_session_class:
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """<!DOCTYPE html>
<html>
<head><title>CSMS #65794272 - Section 232 Update</title></head>
<body>
<h1>CSMS Bulletin #65794272</h1>
<p>Effective March 15, 2025</p>
<p>The following HTS codes are subject to Section 232 steel tariffs:</p>
<ul>
<li>8544.42.9090</li>
<li>8501.10.20</li>
</ul>
<p>Claim code: 9903.78.01</p>
</body>
</html>"""
        mock_response.headers = {"Content-Type": "text/html"}
        mock_session.get.return_value = mock_response
        mock_session.headers = {}
        mock_session_class.return_value = mock_session

        yield mock_session


# ============================================================================
# Write Gate Fixtures
# ============================================================================

@pytest.fixture
def valid_write_gate_input(sample_chunks):
    """Valid input for Write Gate testing."""
    reader_output = {
        "success": True,
        "answer": {
            "in_scope": True,
            "program": "section_232_steel",
            "hts_code": "8544.42.9090",
            "claim_codes": ["9903.78.01"],
            "confidence": "high",
        },
        "citations": [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "quote": "8544.42.9090 - Electrical conductors, copper",
                "why_this_supports": "HTS code explicitly listed",
            }
        ],
    }

    validator_output = {
        "verified": True,
        "failures": [],
        "confidence": "high",
    }

    return {
        "reader_output": reader_output,
        "validator_output": validator_output,
        "chunks": sample_chunks,
    }
