"""
Unit tests for the standardized API response format.

Tests the response envelope structure for all output formats:
- text (default)
- structured
- trade_compliance
"""

import pytest
import json
from unittest.mock import Mock, patch


class TestAPIResponseFormat:
    """Test the standardized API response envelope."""

    def test_response_has_required_fields(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test that response contains all required fields."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "What is the HTS code?"},
                content_type="application/json"
            )

            assert response.status_code == 200
            data = response.get_json()

            # Check all required fields exist
            required_fields = [
                "success", "error", "message_id", "role", "mode",
                "output_format", "answer", "citations", "structured_output",
                "tool_calls", "condensed_question"
            ]
            for field in required_fields:
                assert field in data, f"Missing field: {field}"

    def test_successful_response_structure(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test successful response has correct structure."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "What is the HTS code?"},
                content_type="application/json"
            )

            data = response.get_json()

            assert data["success"] is True
            assert data["error"] is None
            assert data["role"] == "assistant"

    def test_error_response_on_missing_input(self, logged_in_client, test_conversation, app):
        """Test error response when input is missing."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={},  # Missing input
                content_type="application/json"
            )

            assert response.status_code == 400
            data = response.get_json()
            assert data["success"] is False
            assert data["error"]["code"] == "MISSING_INPUT"

    def test_message_id_is_uuid(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test message_id is a valid UUID."""
        import uuid
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "Test question"},
                content_type="application/json"
            )

            data = response.get_json()
            # Verify it's a valid UUID format
            try:
                uuid.UUID(data["message_id"])
                is_valid = True
            except ValueError:
                is_valid = False
            assert is_valid, "message_id is not a valid UUID"


class TestOutputFormats:
    """Test different output format options."""

    def test_default_text_format(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test default output format is 'text'."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "What is the HTS code?"},
                content_type="application/json"
            )

            data = response.get_json()
            assert data["output_format"] == "text"

    def test_structured_format_requested(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test requesting structured output format."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "What is the HTS code?", "output_format": "structured"},
                content_type="application/json"
            )

            data = response.get_json()
            assert data["output_format"] == "structured"

    def test_trade_compliance_format_requested(self, logged_in_client, test_conversation, app):
        """Test requesting trade_compliance output format."""
        mock_response = {
            "answer": "LED lamps require compliance",
            "citations": [],
            "structured_output": {"hts_codes": ["8539.50.00"]},
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
                    json={"input": "Import requirements", "output_format": "trade_compliance"},
                    content_type="application/json"
                )

                data = response.get_json()
                assert data["output_format"] == "trade_compliance"


class TestCitationsFormat:
    """Test citations handling in responses."""

    def test_citations_included_in_response(self, logged_in_client, test_conversation, app):
        """Test that citations from chat are included in response."""
        mock_response = {
            "answer": "The answer",
            "citations": [
                {"index": 1, "pdf_id": "doc-001", "doc_type": "hts", "page": 5, "snippet": "..."}
            ],
            "structured_output": None,
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
                    json={"input": "Question?"},
                    content_type="application/json"
                )

                data = response.get_json()
                assert len(data["citations"]) == 1
                assert data["citations"][0]["pdf_id"] == "doc-001"

    def test_empty_citations_array_when_none(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test empty array when no citations."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "Question?"},
                content_type="application/json"
            )

            data = response.get_json()
            assert isinstance(data["citations"], list)


class TestStructuredOutputFormat:
    """Test structured_output field handling."""

    def test_structured_output_included(self, logged_in_client, test_conversation, app):
        """Test structured output is passed through."""
        mock_response = {
            "answer": "The answer",
            "citations": [],
            "structured_output": {
                "confidence": "high",
                "follow_up_questions": ["What about X?"]
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
                    json={"input": "Question?"},
                    content_type="application/json"
                )

                data = response.get_json()
                assert data["structured_output"]["confidence"] == "high"

    def test_trade_compliance_structured_output(self, logged_in_client, test_conversation, app):
        """Test trade compliance structured output format."""
        mock_response = {
            "answer": "LED compliance info",
            "citations": [],
            "structured_output": {
                "hts_codes": ["8539.50.00"],
                "agencies": ["DOE", "FCC"],
                "required_documents": [{"agency": "DOE", "document_name": "Cert"}],
                "tariff_info": {"duty_rate": "3.9%"},
                "risk_flags": ["Section 301"]
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
                    json={"input": "Import LED from China", "output_format": "trade_compliance"},
                    content_type="application/json"
                )

                data = response.get_json()
                so = data["structured_output"]
                assert "8539.50.00" in so["hts_codes"]
                assert "DOE" in so["agencies"]


class TestAgenticMode:
    """Test agentic mode with use_agent flag."""

    def test_use_agent_flag(self, logged_in_client, test_conversation, app):
        """Test use_agent=True routes to agentic chat."""
        mock_response = {
            "answer": "Found via agent",
            "citations": [],
            "structured_output": None,
            "documents": [],
            "condensed_question": "query",
            "tool_calls": ["lookup_hts: LED lamps"]
        }
        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        conv_id = test_conversation["id"]
        with app.app_context():
            with patch('app.web.views.conversation_views.build_agentic_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "What HTS code?", "use_agent": True},
                    content_type="application/json"
                )

                data = response.get_json()
                assert len(data["tool_calls"]) > 0


class TestModeInResponse:
    """Test mode field in response."""

    def test_multi_doc_mode_in_response(self, logged_in_client, test_conversation, mock_all_chat_builders, app):
        """Test mode field reflects conversation mode."""
        conv_id = test_conversation["id"]
        with app.app_context():
            response = logged_in_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"input": "Question?"},
                content_type="application/json"
            )

            data = response.get_json()
            assert data["mode"] == "multi_doc"

    def test_user_pdf_mode_in_response(self, logged_in_client, app, test_user):
        """Test user_pdf mode in response."""
        from app.web.db.models import Conversation

        mock_response = {
            "answer": "Answer",
            "citations": [],
            "structured_output": None,
            "documents": [],
            "condensed_question": "query",
            "tool_calls": []
        }
        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        with app.app_context():
            # Create user_pdf mode conversation
            conv = Conversation.create(
                user_id=test_user["id"],
                mode="user_pdf"
            )
            conv_id = conv.id

            with patch('app.web.views.conversation_views.build_chat', return_value=mock_chat):
                response = logged_in_client.post(
                    f"/api/conversations/{conv_id}/messages",
                    json={"input": "Question?"},
                    content_type="application/json"
                )

                data = response.get_json()
                assert data["mode"] == "user_pdf"
