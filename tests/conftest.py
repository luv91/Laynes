"""
Pytest fixtures for Lanes tests.

Provides:
- Flask app and test client fixtures
- Database fixtures with in-memory SQLite
- Mock fixtures for external services (OpenAI, Pinecone)
- Sample data fixtures
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch

# Set testing environment before importing app
os.environ["TESTING"] = "true"
os.environ["USE_SQLITE_CHECKPOINTER"] = "false"
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

# Add the lanes directory to the Python path
lanes_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if lanes_dir not in sys.path:
    sys.path.insert(0, lanes_dir)


# ============================================================================
# Flask App Fixtures
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
        "SECRET_KEY": "test-secret-key",
        "WTF_CSRF_ENABLED": False,
    })

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Database session for direct DB access in tests."""
    from app.web.db import db
    with app.app_context():
        yield db.session


# ============================================================================
# User and Auth Fixtures
# ============================================================================

@pytest.fixture
def test_user(app):
    """Create a test user and return a dict with user info."""
    from app.web.db.models import User

    with app.app_context():
        user = User.create(
            email="test@example.com",
            password="testpassword123"
        )
        # Return dict to avoid detached instance issues
        return {"id": user.id, "email": user.email}


@pytest.fixture
def auth_headers(test_user):
    """Headers with authentication for API requests."""
    # For session-based auth, we need to login first
    # This is a simplified version - adjust based on your auth implementation
    return {"Content-Type": "application/json"}


@pytest.fixture
def logged_in_client(client, test_user, app):
    """Client with logged-in user session."""
    with app.app_context():
        with client.session_transaction() as session:
            session["user_id"] = test_user["id"]
    return client


# ============================================================================
# Model Fixtures
# ============================================================================

@pytest.fixture
def test_corpus(app):
    """Create a test corpus."""
    from app.web.db.models import Corpus

    with app.app_context():
        corpus = Corpus.create(
            name="test_corpus",
            description="Test corpus for unit tests",
            is_active=True,
            version="v1"
        )
        return corpus


@pytest.fixture
def test_conversation(app, test_user):
    """Create a test conversation in multi_doc mode."""
    from app.web.db.models import Conversation

    with app.app_context():
        conversation = Conversation.create(
            user_id=test_user["id"],
            mode="multi_doc",
            corpus_name="test_corpus"
        )
        conversation.set_scope_filter({"corpus": "test_corpus"})
        conversation.save()
        # Return dict to avoid detached instance issues
        return {"id": conversation.id, "mode": conversation.mode}


@pytest.fixture
def test_pdf(app, test_user):
    """Create a test PDF."""
    from app.web.db.models import Pdf

    with app.app_context():
        pdf = Pdf.create(
            name="test.pdf",
            user_id=test_user["id"],
            corpus="test_corpus",
            doc_type="test_document"
        )
        # Return dict to avoid detached instance issues
        return {"id": pdf.id, "name": pdf.name}


# ============================================================================
# Mock Fixtures for External Services
# ============================================================================

@pytest.fixture
def mock_chat_response():
    """Standard mock response from chat builder."""
    return {
        "answer": "The HTS code for LED lamps is 8539.50.00 [Source: mock-hts-001]",
        "citations": [
            {
                "index": 1,
                "pdf_id": "mock-hts-001",
                "doc_type": "hts_schedule",
                "page": 1,
                "snippet": "8539.50.00 - Light-emitting diode (LED) lamps..."
            }
        ],
        "structured_output": None,
        "documents": [],
        "condensed_question": "What is the HTS code for LED lamps?",
        "tool_calls": []
    }


@pytest.fixture
def mock_structured_response():
    """Mock response with structured output."""
    return {
        "answer": "The HTS code for LED lamps is 8539.50.00",
        "citations": [
            {
                "index": 1,
                "pdf_id": "mock-hts-001",
                "doc_type": "hts_schedule",
                "page": 1,
                "snippet": "8539.50.00 - Light-emitting diode (LED) lamps..."
            }
        ],
        "structured_output": {
            "answer": "The HTS code for LED lamps is 8539.50.00",
            "confidence": "high",
            "follow_up_questions": [
                "What is the duty rate for this HTS code?",
                "Are there any tariffs from China?"
            ]
        },
        "documents": [],
        "condensed_question": "What is the HTS code for LED lamps?",
        "tool_calls": []
    }


@pytest.fixture
def mock_trade_compliance_response():
    """Mock response for trade compliance output."""
    return {
        "answer": "LED lamps from China require DOE and FCC compliance.",
        "citations": [
            {
                "index": 1,
                "pdf_id": "mock-hts-001",
                "doc_type": "hts_schedule",
                "page": 1,
                "snippet": "8539.50.00 - Light-emitting diode (LED) lamps..."
            },
            {
                "index": 2,
                "pdf_id": "mock-tariff-001",
                "doc_type": "tariff_notice",
                "page": 1,
                "snippet": "Section 301 List 3: Additional 25% tariff..."
            }
        ],
        "structured_output": {
            "hts_codes": ["8539.50.00"],
            "agencies": ["DOE", "FCC"],
            "required_documents": [
                {
                    "agency": "DOE",
                    "document_name": "Certificate of Compliance",
                    "description": "Energy efficiency certification"
                },
                {
                    "agency": "FCC",
                    "document_name": "Declaration of Conformity",
                    "description": "Electronic emissions compliance"
                }
            ],
            "tariff_info": {
                "duty_rate": "3.9%",
                "special_programs": ["Section 301"],
                "country_specific": "China: additional 25% tariff"
            },
            "risk_flags": ["Section 301 tariffs apply"]
        },
        "documents": [],
        "condensed_question": "Import requirements for LED lamps from China",
        "tool_calls": []
    }


@pytest.fixture
def mock_chat_builder(mock_chat_response):
    """Mock the build_chat function."""
    mock_chat = Mock()
    mock_chat.invoke.return_value = mock_chat_response
    mock_chat.stream.return_value = iter([{"answer": "Streaming response..."}])

    with patch('app.chat.chat.build_chat', return_value=mock_chat) as mock_builder:
        yield mock_builder, mock_chat


@pytest.fixture
def mock_all_chat_builders(mock_chat_response):
    """Mock all chat builder functions."""
    mock_chat = Mock()
    mock_chat.invoke.return_value = mock_chat_response
    mock_chat.stream.return_value = iter([{"answer": "Streaming response..."}])

    with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat) as mock_build, \
         patch('app.web.views.conversation_views.build_trade_compliance_chat', return_value=mock_chat) as mock_trade, \
         patch('app.web.views.conversation_views.build_agentic_chat', return_value=mock_chat) as mock_agent:
        yield {
            "build_chat": mock_build,
            "build_trade_compliance_chat": mock_trade,
            "build_agentic_chat": mock_agent,
            "chat_instance": mock_chat
        }


# ============================================================================
# Helper Fixtures
# ============================================================================

@pytest.fixture
def sample_trade_query():
    """Sample trade compliance query for testing."""
    return {
        "input": "I want to import LED lamps from China. What do I need?",
        "output_format": "trade_compliance"
    }


@pytest.fixture
def sample_structured_query():
    """Sample query for structured output."""
    return {
        "input": "What is the HTS code for LED lamps?",
        "output_format": "structured"
    }


@pytest.fixture
def sample_text_query():
    """Sample basic text query."""
    return {
        "input": "What is the HTS code for LED lamps?",
        "output_format": "text"
    }
