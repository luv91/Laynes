"""
MCP Gemini Response Parsing Tests

Tests for:
1. parse_json_response() with various inputs
2. Schema validation (Pydantic)
3. Edge cases: malformed JSON, missing fields, wrong types
4. extract_grounding_urls() with various response structures

Usage:
    pipenv run pytest tests/test_mcp_parsing.py -v
"""

import pytest
import json
from typing import Optional
from pydantic import BaseModel, ConfigDict, ValidationError


# ============================================================================
# Pydantic Schema Definitions (for validation)
# ============================================================================

class MetalScope(BaseModel):
    """Schema for individual metal scope result.

    Uses strict mode to prevent string->bool coercion.
    E.g., "yes" should NOT become True.
    """
    model_config = ConfigDict(strict=True)

    in_scope: bool
    claim_code: Optional[str] = None
    disclaim_code: Optional[str] = None
    source: Optional[str] = None


class Section232Result(BaseModel):
    """Schema for Section 232 verification result.

    Uses strict mode to catch Gemini output type mismatches.
    """
    model_config = ConfigDict(strict=True)

    hts_code: str
    copper: MetalScope
    steel: MetalScope
    aluminum: MetalScope
    notes: Optional[str] = None


class Section301Result(BaseModel):
    """Schema for Section 301 verification result."""
    model_config = ConfigDict(strict=True)

    hts_code: str
    included: bool
    list_name: Optional[str] = None
    chapter_99_code: Optional[str] = None
    duty_rate: Optional[float] = None
    source: Optional[str] = None
    exclusions: Optional[str] = None
    notes: Optional[str] = None


# ============================================================================
# Import the actual parsing function
# ============================================================================

# Import from MCP server
from mcp_servers.hts_verifier import parse_json_response, extract_grounding_urls


# ============================================================================
# parse_json_response Tests
# ============================================================================

class TestParseJsonResponse:
    """Tests for parse_json_response function."""

    def test_valid_json_only(self):
        """Test parsing when response is pure JSON."""
        text = '{"hts_code": "8544.42.9090", "copper": {"in_scope": true}}'
        result = parse_json_response(text)

        assert result["hts_code"] == "8544.42.9090"
        assert result["copper"]["in_scope"] is True

    def test_json_with_preamble(self):
        """Test parsing when JSON is preceded by text."""
        text = """Based on my search, here is the result:

{"hts_code": "8544.42.9090", "copper": {"in_scope": true, "claim_code": "9903.78.01"}}"""
        result = parse_json_response(text)

        assert result["hts_code"] == "8544.42.9090"
        assert result["copper"]["in_scope"] is True
        assert result["copper"]["claim_code"] == "9903.78.01"

    def test_json_with_postamble(self):
        """Test parsing when JSON is followed by text."""
        text = """{"hts_code": "8544.42.9090", "copper": {"in_scope": true}}

I hope this helps with your tariff classification."""
        result = parse_json_response(text)

        assert result["hts_code"] == "8544.42.9090"

    def test_json_with_preamble_and_postamble(self):
        """Test parsing when JSON is surrounded by text."""
        text = """Here is the analysis:

{"hts_code": "8544.42.9090", "copper": {"in_scope": true}, "steel": {"in_scope": false}}

Based on official CBP sources."""
        result = parse_json_response(text)

        assert result["hts_code"] == "8544.42.9090"
        assert result["copper"]["in_scope"] is True
        assert result["steel"]["in_scope"] is False

    def test_nested_json(self):
        """Test parsing nested JSON structure."""
        text = """{
    "hts_code": "8544.42.9090",
    "copper": {
        "in_scope": true,
        "claim_code": "9903.78.01",
        "disclaim_code": "9903.78.02",
        "source": "CBP CSMS #65936570"
    },
    "steel": {
        "in_scope": true,
        "claim_code": "9903.80.01",
        "disclaim_code": "9903.80.02",
        "source": "Steel List Aug 2025"
    },
    "aluminum": {
        "in_scope": false,
        "claim_code": null,
        "disclaim_code": null,
        "source": null
    },
    "notes": "Wire is copper derivative"
}"""
        result = parse_json_response(text)

        assert result["hts_code"] == "8544.42.9090"
        assert result["copper"]["in_scope"] is True
        assert result["copper"]["claim_code"] == "9903.78.01"
        assert result["aluminum"]["in_scope"] is False
        assert result["aluminum"]["claim_code"] is None

    def test_invalid_json_returns_raw(self):
        """Test that invalid JSON returns raw_response fallback."""
        text = "This is not JSON at all, just plain text."
        result = parse_json_response(text)

        assert "raw_response" in result
        assert result["raw_response"] == text

    def test_partial_json_returns_raw(self):
        """Test that partial/broken JSON returns raw_response."""
        text = '{"hts_code": "8544.42.9090", "copper": {"in_scope": true'  # Missing closing braces
        result = parse_json_response(text)

        assert "raw_response" in result

    def test_empty_string(self):
        """Test handling of empty string."""
        result = parse_json_response("")

        assert "raw_response" in result
        assert result["raw_response"] == ""

    def test_json_with_markdown_code_block(self):
        """Test parsing JSON inside markdown code block."""
        text = """Here's the result:

```json
{"hts_code": "8544.42.9090", "copper": {"in_scope": true}}
```

That's the analysis."""
        result = parse_json_response(text)

        # Should still find the JSON inside the code block
        assert result["hts_code"] == "8544.42.9090"

    def test_multiple_json_objects_takes_outer(self):
        """Test that when multiple JSON objects exist, the outer one is parsed."""
        text = """Result: {"outer": true, "inner": {"nested": false}}"""
        result = parse_json_response(text)

        # Should get the full outer object
        assert result["outer"] is True
        assert result["inner"]["nested"] is False

    def test_json_with_arrays(self):
        """Test JSON containing arrays."""
        text = '{"sources": ["cbp.gov", "federalregister.gov"], "count": 2}'
        result = parse_json_response(text)

        assert result["sources"] == ["cbp.gov", "federalregister.gov"]
        assert result["count"] == 2

    def test_unicode_in_json(self):
        """Test JSON with unicode characters."""
        text = '{"note": "Section 232 tariffs \u2013 copper", "valid": true}'
        result = parse_json_response(text)

        assert "232" in result["note"]
        assert result["valid"] is True

    def test_json_with_special_chars(self):
        """Test JSON with special characters in strings."""
        text = '{"source": "CBP CSMS #65936570 (Aug 15, 2025)", "valid": true}'
        result = parse_json_response(text)

        assert "#65936570" in result["source"]


# ============================================================================
# Schema Validation Tests
# ============================================================================

class TestSchemaValidation:
    """Tests for Pydantic schema validation of Gemini output."""

    def test_valid_section_232_result(self):
        """Test that valid Section 232 result passes validation."""
        data = {
            "hts_code": "8544.42.9090",
            "copper": {
                "in_scope": True,
                "claim_code": "9903.78.01",
                "disclaim_code": "9903.78.02",
                "source": "CBP CSMS"
            },
            "steel": {
                "in_scope": True,
                "claim_code": "9903.80.01",
                "disclaim_code": "9903.80.02",
                "source": "Steel List"
            },
            "aluminum": {
                "in_scope": False,
                "claim_code": None,
                "disclaim_code": None,
                "source": None
            },
            "notes": "Test note"
        }

        result = Section232Result(**data)

        assert result.hts_code == "8544.42.9090"
        assert result.copper.in_scope is True
        assert result.aluminum.in_scope is False

    def test_missing_required_field_fails(self):
        """Test that missing required field raises ValidationError."""
        data = {
            # Missing hts_code
            "copper": {"in_scope": True},
            "steel": {"in_scope": False},
            "aluminum": {"in_scope": False}
        }

        with pytest.raises(ValidationError):
            Section232Result(**data)

    def test_wrong_type_for_in_scope(self):
        """Test that wrong type for in_scope raises ValidationError."""
        data = {
            "hts_code": "8544.42.9090",
            "copper": {
                "in_scope": "yes",  # Should be bool, not string
                "claim_code": "9903.78.01"
            },
            "steel": {"in_scope": False},
            "aluminum": {"in_scope": False}
        }

        with pytest.raises(ValidationError):
            Section232Result(**data)

    def test_string_true_coercion(self):
        """Test that Pydantic won't coerce 'true' string to True boolean."""
        data = {
            "hts_code": "8544.42.9090",
            "copper": {
                "in_scope": "true",  # String, not boolean
            },
            "steel": {"in_scope": False},
            "aluminum": {"in_scope": False}
        }

        with pytest.raises(ValidationError):
            Section232Result(**data)

    def test_section_301_valid_result(self):
        """Test valid Section 301 result validation."""
        data = {
            "hts_code": "8544.42.9090",
            "included": True,
            "list_name": "list_3",
            "chapter_99_code": "9903.88.03",
            "duty_rate": 0.25,
            "source": "USTR List 3"
        }

        result = Section301Result(**data)

        assert result.included is True
        assert result.list_name == "list_3"
        assert result.duty_rate == 0.25

    def test_section_301_minimal_valid(self):
        """Test Section 301 with only required fields."""
        data = {
            "hts_code": "8544.42.9090",
            "included": False
        }

        result = Section301Result(**data)

        assert result.included is False
        assert result.list_name is None


# ============================================================================
# extract_grounding_urls Tests
# ============================================================================

class TestExtractGroundingUrls:
    """Tests for extract_grounding_urls function."""

    def test_empty_response(self):
        """Test with response that has no grounding metadata."""
        class MockResponse:
            candidates = []

        result = extract_grounding_urls(MockResponse())
        assert result == []

    def test_no_candidates(self):
        """Test with response that has no candidates."""
        class MockResponse:
            candidates = None

        result = extract_grounding_urls(MockResponse())
        assert result == []

    def test_candidates_no_metadata(self):
        """Test with candidates but no grounding_metadata."""
        class MockCandidate:
            grounding_metadata = None

        class MockResponse:
            candidates = [MockCandidate()]

        result = extract_grounding_urls(MockResponse())
        assert result == []

    def test_metadata_no_chunks(self):
        """Test with metadata but no grounding_chunks."""
        class MockMetadata:
            grounding_chunks = None

        class MockCandidate:
            grounding_metadata = MockMetadata()

        class MockResponse:
            candidates = [MockCandidate()]

        result = extract_grounding_urls(MockResponse())
        assert result == []

    def test_single_grounding_url(self):
        """Test extracting single grounding URL."""
        class MockWeb:
            uri = "https://www.cbp.gov/trade/section-232"

        class MockChunk:
            web = MockWeb()

        class MockMetadata:
            grounding_chunks = [MockChunk()]

        class MockCandidate:
            grounding_metadata = MockMetadata()

        class MockResponse:
            candidates = [MockCandidate()]

        result = extract_grounding_urls(MockResponse())

        assert len(result) == 1
        assert result[0] == "https://www.cbp.gov/trade/section-232"

    def test_multiple_grounding_urls(self):
        """Test extracting multiple grounding URLs."""
        class MockWeb1:
            uri = "https://www.cbp.gov/trade/section-232"

        class MockWeb2:
            uri = "https://www.federalregister.gov/docs/232"

        class MockChunk1:
            web = MockWeb1()

        class MockChunk2:
            web = MockWeb2()

        class MockMetadata:
            grounding_chunks = [MockChunk1(), MockChunk2()]

        class MockCandidate:
            grounding_metadata = MockMetadata()

        class MockResponse:
            candidates = [MockCandidate()]

        result = extract_grounding_urls(MockResponse())

        assert len(result) == 2
        assert "cbp.gov" in result[0]
        assert "federalregister.gov" in result[1]

    def test_chunk_without_web(self):
        """Test handling chunks without web attribute."""
        class MockChunk:
            web = None

        class MockMetadata:
            grounding_chunks = [MockChunk()]

        class MockCandidate:
            grounding_metadata = MockMetadata()

        class MockResponse:
            candidates = [MockCandidate()]

        result = extract_grounding_urls(MockResponse())
        assert result == []

    def test_exception_handling(self):
        """Test that exceptions are handled gracefully."""
        class MockResponse:
            @property
            def candidates(self):
                raise Exception("Unexpected error")

        result = extract_grounding_urls(MockResponse())
        assert result == []


# ============================================================================
# Integration: Parse + Validate
# ============================================================================

class TestParseAndValidate:
    """Tests for combined parsing and validation workflow."""

    def test_parse_then_validate_success(self):
        """Test full workflow: parse JSON then validate with Pydantic."""
        gemini_response = """Based on my search, here is the result:

{
    "hts_code": "8544.42.9090",
    "copper": {
        "in_scope": true,
        "claim_code": "9903.78.01",
        "disclaim_code": "9903.78.02",
        "source": "CBP CSMS #65936570"
    },
    "steel": {
        "in_scope": true,
        "claim_code": "9903.80.01",
        "disclaim_code": "9903.80.02",
        "source": "Steel List Aug 2025"
    },
    "aluminum": {
        "in_scope": false,
        "claim_code": null,
        "disclaim_code": null,
        "source": null
    },
    "notes": "HTS 8544.42.9090 is insulated copper wire"
}

This is based on official CBP sources."""

        # Step 1: Parse
        parsed = parse_json_response(gemini_response)

        assert "raw_response" not in parsed  # Successfully parsed as JSON

        # Step 2: Validate
        validated = Section232Result(**parsed)

        assert validated.hts_code == "8544.42.9090"
        assert validated.copper.in_scope is True
        assert validated.copper.claim_code == "9903.78.01"

    def test_parse_success_validate_fail(self):
        """Test when JSON is valid but schema doesn't match."""
        gemini_response = """{
    "hts_code": "8544.42.9090",
    "copper": {
        "in_scope": "yes",
        "claim_code": "9903.78.01"
    },
    "steel": {"in_scope": false},
    "aluminum": {"in_scope": false}
}"""

        # Step 1: Parse succeeds
        parsed = parse_json_response(gemini_response)

        assert "raw_response" not in parsed
        assert parsed["copper"]["in_scope"] == "yes"  # String, not bool

        # Step 2: Validate fails
        with pytest.raises(ValidationError) as exc_info:
            Section232Result(**parsed)

        # Check the error mentions in_scope
        assert "in_scope" in str(exc_info.value)

    def test_parse_fail_returns_raw(self):
        """Test that parse failure doesn't break workflow."""
        gemini_response = "I couldn't find any information about that HTS code."

        parsed = parse_json_response(gemini_response)

        assert "raw_response" in parsed
        assert parsed["raw_response"] == gemini_response

        # Can't validate raw response
        with pytest.raises(ValidationError):
            Section232Result(**parsed)


# ============================================================================
# Suggested Validation Function
# ============================================================================

def validate_section_232_response(parsed_json: dict) -> tuple[bool, Optional[Section232Result], Optional[str]]:
    """
    Validate parsed JSON against Section 232 schema.

    Returns:
        (is_valid, validated_result, error_message)
    """
    if "raw_response" in parsed_json:
        return False, None, "JSON parsing failed - raw response returned"

    try:
        result = Section232Result(**parsed_json)
        return True, result, None
    except ValidationError as e:
        return False, None, str(e)


class TestValidationHelper:
    """Tests for the validation helper function."""

    def test_validation_helper_success(self):
        """Test helper returns validated result on success."""
        data = {
            "hts_code": "8544.42.9090",
            "copper": {"in_scope": True},
            "steel": {"in_scope": False},
            "aluminum": {"in_scope": False}
        }

        is_valid, result, error = validate_section_232_response(data)

        assert is_valid is True
        assert result.hts_code == "8544.42.9090"
        assert error is None

    def test_validation_helper_parse_failure(self):
        """Test helper handles parse failure."""
        data = {"raw_response": "No JSON found"}

        is_valid, result, error = validate_section_232_response(data)

        assert is_valid is False
        assert result is None
        assert "parsing failed" in error.lower()

    def test_validation_helper_schema_failure(self):
        """Test helper handles schema validation failure."""
        data = {
            "hts_code": "8544.42.9090",
            "copper": {"in_scope": "yes"},  # Wrong type
            "steel": {"in_scope": False},
            "aluminum": {"in_scope": False}
        }

        is_valid, result, error = validate_section_232_response(data)

        assert is_valid is False
        assert result is None
        assert "in_scope" in error


# ============================================================================
# v9.2 Citation Schema Tests
# ============================================================================

from mcp_servers.schemas import (
    Citation,
    MetalScopeV2,
    Section232ResultV2,
    validate_section_232_v2,
    validate_citations_have_proof,
    validate_citations_contain_hts,
)


class TestCitationSchema:
    """Tests for v9.2 Citation schema."""

    def test_valid_citation_full(self):
        """Test valid citation with all fields."""
        data = {
            "source_url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ee1cba",
            "source_title": "CBP CSMS #65936570",
            "source_document": "CSMS #65936570",
            "effective_date": "2025-08-18",
            "location_hint": "Table row: 8544.42.90",
            "evidence_type": "table",
            "quoted_text": "8544.42.90 - Insulated copper wire and cable"
        }
        citation = Citation(**data)

        assert citation.source_url == data["source_url"]
        assert citation.quoted_text == data["quoted_text"]
        assert citation.evidence_type == "table"

    def test_citation_minimal(self):
        """Test citation with only required field (source_url)."""
        data = {
            "source_url": "https://cbp.gov/page"
        }
        citation = Citation(**data)

        assert citation.source_url == "https://cbp.gov/page"
        assert citation.quoted_text is None
        assert citation.source_title is None

    def test_citation_with_null_quoted_text(self):
        """Test citation where verbatim quote couldn't be extracted."""
        data = {
            "source_url": "https://cbp.gov/page",
            "source_title": "Some page",
            "quoted_text": None  # Gemini couldn't extract exact quote
        }
        citation = Citation(**data)

        assert citation.quoted_text is None

    def test_citation_missing_source_url_fails(self):
        """Test that citation without source_url fails."""
        data = {
            "source_title": "Some page",
            "quoted_text": "Some quote"
            # Missing source_url
        }
        with pytest.raises(ValidationError):
            Citation(**data)


class TestMetalScopeV2Schema:
    """Tests for v9.2 MetalScopeV2 schema with citations."""

    def test_valid_metal_scope_v2(self):
        """Test valid MetalScopeV2 with citations."""
        data = {
            "in_scope": True,
            "claim_code": "9903.78.01",
            "disclaim_code": "9903.78.02",
            "citations": [
                {
                    "source_url": "https://cbp.gov/copper-list",
                    "quoted_text": "8544.42.90 - Insulated copper wire"
                }
            ]
        }
        scope = MetalScopeV2(**data)

        assert scope.in_scope is True
        assert scope.claim_code == "9903.78.01"
        assert len(scope.citations) == 1
        assert scope.citations[0].quoted_text == "8544.42.90 - Insulated copper wire"

    def test_metal_scope_v2_null_in_scope(self):
        """Test MetalScopeV2 with null in_scope (unknown/insufficient evidence)."""
        data = {
            "in_scope": None,  # Unknown
            "claim_code": None,
            "citations": []
        }
        scope = MetalScopeV2(**data)

        assert scope.in_scope is None

    def test_metal_scope_v2_multiple_citations(self):
        """Test MetalScopeV2 with multiple citations."""
        data = {
            "in_scope": True,
            "claim_code": "9903.80.01",
            "citations": [
                {
                    "source_url": "https://cbp.gov/csms/1",
                    "quoted_text": "8544.42.90 steel"
                },
                {
                    "source_url": "https://federalregister.gov/doc",
                    "quoted_text": "8544.42.90 listed"
                }
            ]
        }
        scope = MetalScopeV2(**data)

        assert len(scope.citations) == 2

    def test_metal_scope_v2_empty_citations(self):
        """Test MetalScopeV2 with no citations."""
        data = {
            "in_scope": False,
            "citations": []
        }
        scope = MetalScopeV2(**data)

        assert len(scope.citations) == 0


class TestSection232ResultV2Schema:
    """Tests for v9.2 Section232ResultV2 with nested results structure."""

    def test_valid_section_232_result_v2(self):
        """Test valid Section232ResultV2."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov/copper",
                            "quoted_text": "8544.42.90 copper wire"
                        }
                    ]
                },
                "steel": {
                    "in_scope": True,
                    "claim_code": "9903.80.01",
                    "citations": []
                },
                "aluminum": {
                    "in_scope": None,
                    "citations": []
                }
            },
            "notes": "Test notes"
        }
        result = Section232ResultV2(**data)

        assert result.hts_code == "8544.42.9090"
        assert result.results["copper"].in_scope is True
        assert result.results["aluminum"].in_scope is None
        assert len(result.results["copper"].citations) == 1

    def test_section_232_v2_validation_function(self):
        """Test validate_section_232_v2 function."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {"in_scope": True, "claim_code": "9903.78.01", "citations": []},
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": None, "citations": []}
            }
        }

        is_valid, result, error = validate_section_232_v2(data)

        assert is_valid is True
        assert result.hts_code == "8544.42.9090"
        assert error is None

    def test_section_232_v2_validation_raw_response(self):
        """Test validate_section_232_v2 with raw_response (parse failure)."""
        data = {"raw_response": "Failed to parse"}

        is_valid, result, error = validate_section_232_v2(data)

        assert is_valid is False
        assert result is None
        assert "parsing failed" in error.lower()


class TestBusinessValidation:
    """Tests for v9.2 business validation functions."""

    def test_validate_citations_have_proof_success(self):
        """Test validation passes when in_scope=True has proof."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov/copper",
                            "quoted_text": "8544.42.90 copper wire"
                        }
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": None, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        errors = validate_citations_have_proof(result)

        assert len(errors) == 0

    def test_validate_citations_have_proof_missing_claim_code(self):
        """Test validation fails when in_scope=True but no claim_code."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": None,  # Missing!
                    "citations": [
                        {"source_url": "https://cbp.gov", "quoted_text": "8544.42.90"}
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        errors = validate_citations_have_proof(result)

        assert len(errors) == 1
        assert "copper" in errors[0]
        assert "claim_code" in errors[0]

    def test_validate_citations_have_proof_missing_citation(self):
        """Test validation fails when in_scope=True but no valid citation."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": []  # No citations!
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        errors = validate_citations_have_proof(result)

        assert len(errors) == 1
        assert "copper" in errors[0]
        assert "citation" in errors[0].lower()

    def test_validate_citations_have_proof_citation_no_quote(self):
        """Test validation fails when citation has URL but no quoted_text."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov",
                            "quoted_text": None  # No quote!
                        }
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        errors = validate_citations_have_proof(result)

        assert len(errors) == 1

    def test_validate_citations_have_proof_null_in_scope_ok(self):
        """Test that in_scope=None doesn't require proof."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {"in_scope": None, "citations": []},
                "steel": {"in_scope": None, "citations": []},
                "aluminum": {"in_scope": None, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        errors = validate_citations_have_proof(result)

        assert len(errors) == 0

    def test_validate_citations_have_proof_false_in_scope_ok(self):
        """Test that in_scope=False doesn't require proof."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {"in_scope": False, "citations": []},
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        errors = validate_citations_have_proof(result)

        assert len(errors) == 0


class TestCitationHtsValidation:
    """Tests for validate_citations_contain_hts function."""

    def test_quote_contains_hts_10_digit(self):
        """Test warning not raised when quote contains 10-digit HTS."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov",
                            "quoted_text": "HTS 8544.42.9090 is included"
                        }
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        warnings = validate_citations_contain_hts(result)

        assert len(warnings) == 0

    def test_quote_contains_hts_8_digit(self):
        """Test warning not raised when quote contains 8-digit HTS."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov",
                            "quoted_text": "8544.42.90 - Copper wire"
                        }
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        warnings = validate_citations_contain_hts(result)

        assert len(warnings) == 0

    def test_quote_missing_hts_warning(self):
        """Test warning raised when quote doesn't contain HTS."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov",
                            "quoted_text": "Copper wire is included in the list"  # No HTS!
                        }
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        warnings = validate_citations_contain_hts(result)

        assert len(warnings) == 1
        assert "copper" in warnings[0]
        assert "8544.42.90" in warnings[0]

    def test_quote_hts_without_dots(self):
        """Test no warning when quote has HTS without dots."""
        data = {
            "hts_code": "8544.42.9090",
            "query_type": "section_232",
            "results": {
                "copper": {
                    "in_scope": True,
                    "claim_code": "9903.78.01",
                    "citations": [
                        {
                            "source_url": "https://cbp.gov",
                            "quoted_text": "Code 85444290 is listed"  # No dots
                        }
                    ]
                },
                "steel": {"in_scope": False, "citations": []},
                "aluminum": {"in_scope": False, "citations": []}
            }
        }
        result = Section232ResultV2(**data)
        warnings = validate_citations_contain_hts(result)

        assert len(warnings) == 0
