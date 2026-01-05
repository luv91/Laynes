"""
Unit tests for Reader LLM (v10.0 Phase 3).

Tests:
- Prompt building
- Response parsing
- Citation extraction
- Error handling
"""

import pytest
from unittest.mock import Mock, patch


class TestReaderLLM:
    """Tests for the ReaderLLM class."""

    def test_build_chunks_context(self):
        """Test building context from chunks."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        chunks = [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "text": "HTS 8544.42.9090 is subject to Section 232.",
                "source": "CSMS",
            },
            {
                "document_id": "doc-002",
                "chunk_id": "chunk-002",
                "text": "Claim code 9903.78.01 applies.",
                "source": "FEDERAL_REGISTER",
            },
        ]

        context = reader._build_chunks_context(chunks)

        assert "CHUNK 1" in context
        assert "CHUNK 2" in context
        assert "doc-001" in context
        assert "chunk-001" in context
        assert "8544.42.9090" in context
        assert "9903.78.01" in context

    def test_build_user_prompt(self):
        """Test building the user prompt."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        chunks = [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "text": "Test content",
                "source": "CSMS",
            }
        ]

        prompt = reader._build_user_prompt(
            hts_code="8544.42.9090",
            program_id="section_232_steel",
            material="steel",
            chunks=chunks
        )

        assert "8544.42.9090" in prompt
        assert "section_232_steel" in prompt
        assert "steel" in prompt
        assert "QUESTION:" in prompt
        assert "DOCUMENT CHUNKS:" in prompt

    def test_parse_valid_response(self):
        """Test parsing a valid LLM response."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        response_text = """{
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
                    "quote": "HTS 8544.42.9090 is in scope",
                    "why_this_supports": "Explicitly listed"
                }
            ],
            "missing_info": [],
            "contradictions": []
        }"""

        output = reader._parse_response(response_text)

        assert output.success is True
        assert output.answer is not None
        assert output.answer.in_scope is True
        assert output.answer.program == "section_232_steel"
        assert output.answer.hts_code == "8544.42.9090"
        assert len(output.citations) == 1
        assert output.citations[0].document_id == "doc-001"
        assert output.citations[0].quote == "HTS 8544.42.9090 is in scope"

    def test_parse_response_no_json(self):
        """Test parsing response with no JSON."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        response_text = "This is not JSON, just plain text."

        output = reader._parse_response(response_text)

        assert output.success is False
        assert output.error is not None
        assert "No JSON found" in output.error

    def test_parse_response_invalid_json(self):
        """Test parsing response with invalid JSON."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        response_text = '{"answer": invalid json here}'

        output = reader._parse_response(response_text)

        assert output.success is False
        assert output.error is not None
        assert "JSON parse error" in output.error

    def test_parse_response_with_markdown(self):
        """Test parsing response with markdown wrapper."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        response_text = """```json
{
    "answer": {
        "in_scope": false,
        "program": "section_232_steel",
        "hts_code": "8544.42.9090",
        "claim_codes": [],
        "disclaim_codes": [],
        "confidence": "low"
    },
    "citations": [],
    "missing_info": ["No relevant documents found"],
    "contradictions": []
}
```"""

        output = reader._parse_response(response_text)

        assert output.success is True
        assert output.answer.in_scope is False
        assert "No relevant documents found" in output.missing_info

    def test_read_no_chunks(self):
        """Test read with no chunks provided."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI'):
            reader = ReaderLLM()

        output = reader.read(
            hts_code="8544.42.9090",
            program_id="section_232_steel",
            material="steel",
            chunks=[]
        )

        assert output.success is False
        assert output.error == "No chunks provided"

    def test_read_with_mock_openai(self, mock_openai_client):
        """Test read with mocked OpenAI client."""
        from app.rag.reader_llm import ReaderLLM

        with patch('app.rag.reader_llm.OpenAI', return_value=mock_openai_client):
            reader = ReaderLLM()
            reader.client = mock_openai_client

        chunks = [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "text": "HTS 8544.42.9090 is subject to Section 232 steel.",
                "source": "CSMS",
            }
        ]

        output = reader.read(
            hts_code="8544.42.9090",
            program_id="section_232_steel",
            material="steel",
            chunks=chunks
        )

        assert output.success is True
        # Verify OpenAI was called
        mock_openai_client.chat.completions.create.assert_called_once()


class TestReaderAnswer:
    """Tests for the ReaderAnswer dataclass."""

    def test_reader_answer_creation(self):
        """Test creating a ReaderAnswer."""
        from app.rag.reader_llm import ReaderAnswer

        answer = ReaderAnswer(
            in_scope=True,
            program="section_232_steel",
            hts_code="8544.42.9090",
            claim_codes=["9903.78.01"],
            disclaim_codes=["9903.78.02"],
            confidence="high",
        )

        assert answer.in_scope is True
        assert answer.program == "section_232_steel"
        assert answer.hts_code == "8544.42.9090"
        assert "9903.78.01" in answer.claim_codes
        assert answer.confidence == "high"

    def test_reader_answer_null_scope(self):
        """Test ReaderAnswer with null in_scope."""
        from app.rag.reader_llm import ReaderAnswer

        answer = ReaderAnswer(
            in_scope=None,
            program="section_232_steel",
            hts_code="8544.42.9090",
            confidence="low",
        )

        assert answer.in_scope is None
        assert answer.confidence == "low"


class TestCitation:
    """Tests for the Citation dataclass."""

    def test_citation_creation(self):
        """Test creating a Citation."""
        from app.rag.reader_llm import Citation

        citation = Citation(
            document_id="doc-001",
            chunk_id="chunk-001",
            quote="HTS 8544.42.9090 is in scope",
            why_this_supports="Explicitly listed in CSMS bulletin",
        )

        assert citation.document_id == "doc-001"
        assert citation.chunk_id == "chunk-001"
        assert citation.quote == "HTS 8544.42.9090 is in scope"
        assert "CSMS" in citation.why_this_supports


class TestReaderOutput:
    """Tests for the ReaderOutput dataclass."""

    def test_reader_output_to_dict(self):
        """Test ReaderOutput to_dict method."""
        from app.rag.reader_llm import ReaderOutput, ReaderAnswer, Citation

        output = ReaderOutput(
            success=True,
            answer=ReaderAnswer(
                in_scope=True,
                program="section_232_steel",
                hts_code="8544.42.9090",
                claim_codes=["9903.78.01"],
                disclaim_codes=[],
                confidence="high",
            ),
            citations=[
                Citation(
                    document_id="doc-001",
                    chunk_id="chunk-001",
                    quote="Test quote",
                    why_this_supports="Test reason",
                )
            ],
            missing_info=[],
            contradictions=[],
        )

        result = output.to_dict()

        assert result["success"] is True
        assert result["answer"]["in_scope"] is True
        assert result["answer"]["program"] == "section_232_steel"
        assert len(result["citations"]) == 1
        assert result["citations"][0]["quote"] == "Test quote"

    def test_reader_output_error_to_dict(self):
        """Test failed ReaderOutput to_dict."""
        from app.rag.reader_llm import ReaderOutput

        output = ReaderOutput(
            success=False,
            answer=None,
            error="API error occurred",
        )

        result = output.to_dict()

        assert result["success"] is False
        assert result["answer"] is None
        assert result["error"] == "API error occurred"
