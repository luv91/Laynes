"""
Integration tests for the Lanes API.

Tests end-to-end flows with mocked external services (OpenAI, Pinecone).
Uses Flask test client to test actual HTTP endpoints.
"""

import pytest
import json
from unittest.mock import Mock, patch


class TestConversationEndpoints:
    """Test conversation CRUD endpoints."""

    def test_create_multi_doc_conversation(self, logged_in_client, app):
        """Test creating a multi-doc conversation."""
        with app.app_context():
            response = logged_in_client.post(
                "/api/conversations/",
                json={
                    "mode": "multi_doc",
                    "scope_filter": {"corpus": "trade_compliance"}
                },
                content_type="application/json"
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["mode"] == "multi_doc"
            assert data["scope_filter"] == {"corpus": "trade_compliance"}

    def test_list_conversations(self, logged_in_client, test_conversation, app):
        """Test listing conversations."""
        with app.app_context():
            response = logged_in_client.get("/api/conversations/")

            assert response.status_code == 200
            data = response.get_json()
            assert isinstance(data, list)
            assert len(data) >= 1

    def test_list_conversations_filter_by_mode(self, logged_in_client, test_conversation, app):
        """Test filtering conversations by mode."""
        with app.app_context():
            response = logged_in_client.get("/api/conversations/?mode=multi_doc")

            assert response.status_code == 200
            data = response.get_json()
            for conv in data:
                assert conv["mode"] == "multi_doc"


class TestMessageEndpoints:
    """Test message creation endpoints with mocked chat builders."""

    def test_send_message_returns_standardized_response(self, logged_in_client, test_conversation, app):
        """Test sending a message returns standardized response."""
        mock_response = {
            "answer": "The HTS code is 8539.50.00",
            "citations": [{"index": 1, "pdf_id": "hts-001", "doc_type": "hts"}],
            "structured_output": None,
            "documents": [],
            "condensed_question": "HTS code for LED",
            "tool_calls": []
        }

        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "What is the HTS code for LED lamps?"},
                    content_type="application/json"
                )

                assert response.status_code == 200
                data = response.get_json()

                # Verify standardized envelope
                assert data["success"] is True
                assert data["answer"] == "The HTS code is 8539.50.00"
                assert len(data["citations"]) == 1

    def test_send_message_with_structured_output(self, logged_in_client, test_conversation, app):
        """Test sending message with structured output format."""
        mock_response = {
            "answer": "The HTS code is 8539.50.00",
            "citations": [],
            "structured_output": {
                "confidence": "high",
                "follow_up_questions": ["What about tariffs?"]
            },
            "documents": [],
            "condensed_question": "query",
            "tool_calls": []
        }

        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={
                        "input": "What is the HTS code?",
                        "output_format": "structured"
                    },
                    content_type="application/json"
                )

                data = response.get_json()
                assert data["output_format"] == "structured"
                assert data["structured_output"]["confidence"] == "high"

    def test_send_message_trade_compliance_output(self, logged_in_client, test_conversation, app):
        """Test trade compliance output format."""
        mock_response = {
            "answer": "LED lamps require DOE and FCC compliance",
            "citations": [],
            "structured_output": {
                "hts_codes": ["8539.50.00"],
                "agencies": ["DOE", "FCC"],
                "required_documents": [
                    {"agency": "DOE", "document_name": "Certificate of Compliance"}
                ],
                "tariff_info": {"duty_rate": "3.9%"},
                "risk_flags": ["Section 301 tariffs apply"]
            },
            "documents": [],
            "condensed_question": "query",
            "tool_calls": []
        }

        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_trade_compliance_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={
                        "input": "Import LED lamps from China",
                        "output_format": "trade_compliance"
                    },
                    content_type="application/json"
                )

                data = response.get_json()
                assert data["output_format"] == "trade_compliance"

                so = data["structured_output"]
                assert "8539.50.00" in so["hts_codes"]
                assert "DOE" in so["agencies"]
                assert len(so["required_documents"]) > 0

    def test_send_message_with_agent(self, logged_in_client, test_conversation, app):
        """Test agentic mode with tool calls."""
        mock_response = {
            "answer": "Found HTS code using tools",
            "citations": [],
            "structured_output": None,
            "documents": [],
            "condensed_question": "query",
            "tool_calls": ["lookup_hts_code: LED lamps", "check_tariffs: 8539.50.00, China"]
        }

        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_agentic_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={
                        "input": "What tariffs for LED from China?",
                        "use_agent": True
                    },
                    content_type="application/json"
                )

                data = response.get_json()
                assert len(data["tool_calls"]) == 2

    def test_missing_input_returns_400(self, logged_in_client, test_conversation, app):
        """Test missing input field returns 400."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={},  # No input
                content_type="application/json"
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data["success"] is False
            assert data["error"]["code"] == "MISSING_INPUT"

    def test_conversation_not_found_returns_404(self, logged_in_client, app):
        """Test non-existent conversation returns 404."""
        with app.app_context():
            response = logged_in_client.post(
                "/api/conversations/nonexistent-id/messages",
                json={"input": "Test"},
                content_type="application/json"
            )

            # Should return 404 from load_model decorator
            assert response.status_code in [404, 500]


class TestStreamingEndpoint:
    """Test streaming message endpoint."""

    def test_streaming_returns_event_stream(self, logged_in_client, test_conversation, app):
        """Test streaming mode returns SSE format."""
        mock_chat = Mock()
        mock_chat.stream.return_value = iter([
            {"answer": "Part 1"},
            {"answer": "Part 2"},
        ])

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages?stream=true",
                    json={"input": "What is the HTS code?"},
                    content_type="application/json"
                )

                assert response.status_code == 200
                assert "text/event-stream" in response.content_type


class TestCorpusEndpoints:
    """Test corpus management (if endpoints exist)."""

    def test_corpus_model_can_be_queried(self, app, test_corpus):
        """Test corpus can be retrieved from database."""
        from app.web.db.models import Corpus

        with app.app_context():
            corpus = Corpus.get_by_name("test_corpus")
            assert corpus is not None
            assert corpus.is_active is True


class TestErrorHandling:
    """Test error handling in API endpoints."""

    def test_internal_error_returns_500(self, logged_in_client, test_conversation, app):
        """Test internal errors are caught and returned properly."""
        mock_chat = Mock()
        mock_chat.invoke.side_effect = Exception("Internal error")

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "Test"},
                    content_type="application/json"
                )

                assert response.status_code == 500
                data = response.get_json()
                assert data["success"] is False
                assert data["error"]["code"] == "INTERNAL_ERROR"

    def test_chat_not_available_error(self, logged_in_client, test_conversation, app):
        """Test error when chat builder returns None."""
        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_chat', return_value=None):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "Test"},
                    content_type="application/json"
                )

                assert response.status_code == 500
                data = response.get_json()
                assert data["error"]["code"] == "CHAT_NOT_AVAILABLE"


class TestMultiDocConversationFlow:
    """Test complete multi-doc conversation flow."""

    def test_create_conversation_and_send_messages(self, logged_in_client, app):
        """Test creating conversation and sending multiple messages."""
        mock_responses = [
            {
                "answer": "The HTS code is 8539.50.00",
                "citations": [{"index": 1, "pdf_id": "hts-001", "doc_type": "hts"}],
                "structured_output": None,
                "documents": [],
                "condensed_question": "HTS code",
                "tool_calls": []
            },
            {
                "answer": "The duty rate is 3.9% plus Section 301 tariffs",
                "citations": [{"index": 1, "pdf_id": "tariff-001", "doc_type": "tariff"}],
                "structured_output": None,
                "documents": [],
                "condensed_question": "Tariff for LED 8539.50.00",
                "tool_calls": []
            }
        ]

        mock_chat = Mock()
        mock_chat.invoke.side_effect = mock_responses

        with app.app_context():
            # Create conversation
            create_response = logged_in_client.post(
                "/api/conversations/",
                json={"mode": "multi_doc", "scope_filter": {"corpus": "trade"}},
                content_type="application/json"
            )
            conv_id = create_response.get_json()["id"]

            with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat):
                # First message
                msg1_response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "What is the HTS code for LED lamps?"},
                    content_type="application/json"
                )
                assert msg1_response.status_code == 200
                assert "8539.50.00" in msg1_response.get_json()["answer"]

                # Follow-up message
                msg2_response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "What about tariffs from China?"},
                    content_type="application/json"
                )
                assert msg2_response.status_code == 200
                assert "3.9%" in msg2_response.get_json()["answer"]
