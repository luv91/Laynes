"""
Unit tests for Validator LLM (v10.0 Phase 3).

Tests:
- Validation prompt building
- Response parsing
- Quick (mechanical) validation
- Full LLM validation
"""

import pytest
from unittest.mock import Mock, patch


class TestValidatorLLM:
    """Tests for the ValidatorLLM class."""

    def test_build_validation_prompt(self):
        """Test building the validation prompt."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
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
                    "quote": "HTS 8544.42.9090 is in scope",
                    "why_this_supports": "Explicitly listed",
                }
            ],
        }

        chunks = [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "text": "HTS 8544.42.9090 is in scope for Section 232.",
            }
        ]

        prompt = validator._build_validation_prompt(reader_output, chunks)

        assert "READER OUTPUT TO VALIDATE" in prompt
        assert "ORIGINAL CHUNKS" in prompt
        assert "VALIDATION TASK" in prompt
        assert "8544.42.9090" in prompt

    def test_parse_valid_response(self):
        """Test parsing a valid validator response."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        response_text = """{
            "verified": true,
            "failures": [],
            "required_fixes": [],
            "confidence": "high"
        }"""

        output = validator._parse_response(response_text)

        assert output.success is True
        assert output.verified is True
        assert len(output.failures) == 0
        assert output.confidence == "high"

    def test_parse_response_with_failures(self):
        """Test parsing response with validation failures."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        response_text = """{
            "verified": false,
            "failures": [
                {
                    "citation_index": 0,
                    "reason": "Quote not found verbatim in chunk",
                    "severity": "error"
                },
                {
                    "citation_index": 1,
                    "reason": "Quote does not support claim",
                    "severity": "warning"
                }
            ],
            "required_fixes": ["Fix citation 0"],
            "confidence": "low"
        }"""

        output = validator._parse_response(response_text)

        assert output.success is True
        assert output.verified is False
        assert len(output.failures) == 2
        assert output.failures[0].citation_index == 0
        assert output.failures[0].severity == "error"
        assert output.failures[1].severity == "warning"

    def test_parse_response_no_json(self):
        """Test parsing response with no JSON."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        response_text = "This is not JSON"

        output = validator._parse_response(response_text)

        assert output.success is False
        assert output.verified is False
        assert "No JSON found" in output.error

    def test_validate_no_reader_output(self):
        """Test validate with no reader output."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        output = validator.validate(None, [])

        assert output.success is False
        assert output.verified is False
        assert "No reader output" in output.error


class TestQuickValidate:
    """Tests for the quick_validate mechanical validation."""

    def test_quick_validate_success(self):
        """Test quick validate with valid citations."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
            "answer": {
                "in_scope": True,
                "claim_codes": ["9903.78.01"],
            },
            "citations": [
                {
                    "document_id": "doc-001",
                    "chunk_id": "chunk-001",
                    "quote": "HTS 8544.42.9090 is in scope",
                }
            ],
        }

        chunks = [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "text": "HTS 8544.42.9090 is in scope for Section 232 steel.",
            }
        ]

        output = validator.quick_validate(reader_output, chunks)

        assert output.success is True
        assert output.verified is True
        assert len(output.failures) == 0

    def test_quick_validate_missing_document_id(self):
        """Test quick validate with missing document_id."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
            "answer": {"in_scope": True},
            "citations": [
                {
                    "chunk_id": "chunk-001",
                    "quote": "Test quote",
                }
            ],
        }

        chunks = [{"chunk_id": "chunk-001", "text": "Test quote in text"}]

        output = validator.quick_validate(reader_output, chunks)

        assert output.verified is False
        assert any(f.reason == "Missing document_id" for f in output.failures)

    def test_quick_validate_missing_chunk_id(self):
        """Test quick validate with missing chunk_id."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
            "answer": {"in_scope": True},
            "citations": [
                {
                    "document_id": "doc-001",
                    "quote": "Test quote",
                }
            ],
        }

        chunks = [{"document_id": "doc-001", "text": "Test quote in text"}]

        output = validator.quick_validate(reader_output, chunks)

        assert output.verified is False
        assert any(f.reason == "Missing chunk_id" for f in output.failures)

    def test_quick_validate_empty_quote(self):
        """Test quick validate with empty quote."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
            "answer": {"in_scope": True},
            "citations": [
                {
                    "document_id": "doc-001",
                    "chunk_id": "chunk-001",
                    "quote": "",
                }
            ],
        }

        chunks = [{"chunk_id": "chunk-001", "text": "Chunk text"}]

        output = validator.quick_validate(reader_output, chunks)

        assert output.verified is False
        assert any(f.reason == "Empty quote" for f in output.failures)

    def test_quick_validate_quote_not_in_chunk(self):
        """Test quick validate with quote not found in chunk."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
            "answer": {"in_scope": True},
            "citations": [
                {
                    "document_id": "doc-001",
                    "chunk_id": "chunk-001",
                    "quote": "This quote is not in the chunk",
                }
            ],
        }

        chunks = [
            {
                "document_id": "doc-001",
                "chunk_id": "chunk-001",
                "text": "Completely different chunk content here.",
            }
        ]

        output = validator.quick_validate(reader_output, chunks)

        assert output.verified is False
        assert any("Quote not found verbatim" in f.reason for f in output.failures)

    def test_quick_validate_in_scope_true_no_citations(self):
        """Test quick validate with in_scope=true but no citations."""
        from app.rag.validator_llm import ValidatorLLM

        with patch('app.rag.validator_llm.OpenAI'):
            validator = ValidatorLLM()

        reader_output = {
            "answer": {"in_scope": True},
            "citations": [],
        }

        chunks = []

        output = validator.quick_validate(reader_output, chunks)

        assert output.verified is False
        assert any("in_scope=true but no citations" in f.reason for f in output.failures)


class TestValidationFailure:
    """Tests for the ValidationFailure dataclass."""

    def test_validation_failure_creation(self):
        """Test creating a ValidationFailure."""
        from app.rag.validator_llm import ValidationFailure

        failure = ValidationFailure(
            citation_index=0,
            reason="Quote not found in chunk",
            severity="error",
        )

        assert failure.citation_index == 0
        assert failure.reason == "Quote not found in chunk"
        assert failure.severity == "error"

    def test_validation_failure_warning(self):
        """Test ValidationFailure with warning severity."""
        from app.rag.validator_llm import ValidationFailure

        failure = ValidationFailure(
            citation_index=1,
            reason="Quote does not contain HTS code",
            severity="warning",
        )

        assert failure.severity == "warning"


class TestValidatorOutput:
    """Tests for the ValidatorOutput dataclass."""

    def test_validator_output_to_dict(self):
        """Test ValidatorOutput to_dict method."""
        from app.rag.validator_llm import ValidatorOutput, ValidationFailure

        output = ValidatorOutput(
            success=True,
            verified=False,
            failures=[
                ValidationFailure(
                    citation_index=0,
                    reason="Test failure",
                    severity="error",
                )
            ],
            required_fixes=["Fix citation"],
            confidence="low",
        )

        result = output.to_dict()

        assert result["success"] is True
        assert result["verified"] is False
        assert len(result["failures"]) == 1
        assert result["failures"][0]["reason"] == "Test failure"
        assert result["confidence"] == "low"

    def test_validator_output_error_to_dict(self):
        """Test failed ValidatorOutput to_dict."""
        from app.rag.validator_llm import ValidatorOutput

        output = ValidatorOutput(
            success=False,
            verified=False,
            error="API error",
        )

        result = output.to_dict()

        assert result["success"] is False
        assert result["verified"] is False
        assert result["error"] == "API error"
