"""
Pydantic Schemas for Gemini Response Validation

These schemas validate the JSON output from Gemini searches
to catch type mismatches, missing fields, and malformed data.

Uses strict mode to prevent silent coercion (e.g., "yes" -> True).

v9.2: Added Citation model and evidence-first schemas with citations[].
"""

from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict


# ============================================================================
# Citation Schema (v9.2 - Evidence-First)
# ============================================================================

class Citation(BaseModel):
    """Specific quoted evidence from source document.

    Each citation contains verbatim text that proves the HTS is in/out of scope.
    This is the "proof" - not just a vague source reference.

    Example:
        {
            "source_url": "https://content.govdelivery.com/...",
            "source_title": "CBP CSMS #65936570",
            "source_document": "CSMS #65936570",
            "effective_date": "2025-08-18",
            "location_hint": "Table row: 8544.42.90",
            "evidence_type": "table",
            "quoted_text": "8544.42.90 - Insulated copper wire..."
        }
    """
    model_config = ConfigDict(strict=True)

    source_url: str  # Required - where the evidence was found
    source_title: Optional[str] = None  # Page/document title
    source_document: Optional[str] = None  # "CSMS #65936570", "Federal Register 89 FR 12345"
    effective_date: Optional[str] = None  # "2025-08-18" - when regulation took effect
    location_hint: Optional[str] = None  # "Table row: 8544.42.90", "Section 3, bullet 5"
    evidence_type: Optional[str] = None  # "table" | "paragraph" | "bullet" | "scope_statement"
    quoted_text: Optional[str] = None  # Verbatim quote, max 400 chars - the PROOF


# ============================================================================
# Section 232 Schemas (v9.1 - Legacy, kept for backwards compatibility)
# ============================================================================

class MetalScope(BaseModel):
    """Schema for individual metal (copper/steel/aluminum) scope result.

    Uses strict mode to prevent string->bool coercion.

    Note: This is the v9.1 legacy schema. For new code, use MetalScopeV2.
    """
    model_config = ConfigDict(strict=True)

    in_scope: bool
    claim_code: Optional[str] = None
    disclaim_code: Optional[str] = None
    source: Optional[str] = None


class Section232Result(BaseModel):
    """Schema for Section 232 verification result.

    Note: This is the v9.1 legacy schema. For new code, use Section232ResultV2.

    Expected structure from Gemini:
    {
        "hts_code": "8544.42.9090",
        "copper": {"in_scope": true, "claim_code": "9903.78.01", ...},
        "steel": {"in_scope": true, "claim_code": "9903.80.01", ...},
        "aluminum": {"in_scope": false, ...},
        "notes": "Optional additional context"
    }
    """
    model_config = ConfigDict(strict=True)

    hts_code: str
    copper: MetalScope
    steel: MetalScope
    aluminum: MetalScope
    notes: Optional[str] = None


# ============================================================================
# Section 232 Schemas V2 (v9.2 - Evidence-First with Citations)
# ============================================================================

class MetalScopeV2(BaseModel):
    """Schema for individual metal scope result WITH citations.

    Key differences from v9.1:
    - in_scope is Optional (null = unknown/insufficient evidence)
    - citations[] array replaces vague "source" string
    - source kept for backwards compatibility (deprecated)

    Example:
        {
            "in_scope": true,
            "claim_code": "9903.78.01",
            "disclaim_code": "9903.78.02",
            "citations": [
                {
                    "source_url": "https://...",
                    "quoted_text": "8544.42.90 - Insulated copper wire..."
                }
            ]
        }
    """
    model_config = ConfigDict(strict=True)

    in_scope: Optional[bool] = None  # true/false/null - null means insufficient evidence
    claim_code: Optional[str] = None
    disclaim_code: Optional[str] = None
    citations: List[Citation] = []  # The proof - verbatim quotes with URLs
    source: Optional[str] = None  # Deprecated - kept for backwards compat


class Section232ResultV2(BaseModel):
    """Schema for Section 232 with nested results structure and citations.

    This is the v9.2 evidence-first schema.

    Expected structure from Gemini:
    {
        "hts_code": "8544.42.9090",
        "query_type": "section_232",
        "results": {
            "copper": {"in_scope": true, "claim_code": "9903.78.01", "citations": [...]},
            "steel": {"in_scope": true, "claim_code": "9903.80.01", "citations": [...]},
            "aluminum": {"in_scope": null, "citations": [...]}
        },
        "notes": null
    }
    """
    model_config = ConfigDict(strict=True)

    hts_code: str
    query_type: str = "section_232"
    results: Dict[str, MetalScopeV2]  # {"copper": {...}, "steel": {...}, "aluminum": {...}}
    notes: Optional[str] = None


# ============================================================================
# Section 301 Schemas
# ============================================================================

class Section301Result(BaseModel):
    """Schema for Section 301 verification result.

    Expected structure from Gemini:
    {
        "hts_code": "8544.42.9090",
        "included": true,
        "list_name": "list_3",
        "chapter_99_code": "9903.88.03",
        "duty_rate": 0.25,
        "source": "USTR List 3",
        "exclusions": null,
        "notes": "Optional context"
    }
    """
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
# Validation Functions
# ============================================================================

def validate_section_232(parsed_json: dict) -> tuple[bool, Optional[Section232Result], Optional[str]]:
    """
    Validate parsed JSON against Section 232 schema.

    Args:
        parsed_json: Dictionary parsed from Gemini response

    Returns:
        (is_valid, validated_result, error_message)
        - On success: (True, Section232Result, None)
        - On failure: (False, None, error_string)
    """
    # Check for parse failure marker
    if "raw_response" in parsed_json and len(parsed_json) == 1:
        return False, None, "JSON parsing failed - raw response returned"

    try:
        result = Section232Result(**parsed_json)
        return True, result, None
    except Exception as e:
        return False, None, str(e)


def validate_section_301(parsed_json: dict) -> tuple[bool, Optional[Section301Result], Optional[str]]:
    """
    Validate parsed JSON against Section 301 schema.

    Args:
        parsed_json: Dictionary parsed from Gemini response

    Returns:
        (is_valid, validated_result, error_message)
    """
    if "raw_response" in parsed_json and len(parsed_json) == 1:
        return False, None, "JSON parsing failed - raw response returned"

    try:
        result = Section301Result(**parsed_json)
        return True, result, None
    except Exception as e:
        return False, None, str(e)


# ============================================================================
# V2 Validation Functions (v9.2 - Evidence-First)
# ============================================================================

def validate_section_232_v2(parsed_json: dict) -> tuple[bool, Optional[Section232ResultV2], Optional[str]]:
    """
    Validate parsed JSON against Section 232 V2 schema (with citations).

    Args:
        parsed_json: Dictionary parsed from Gemini response

    Returns:
        (is_valid, validated_result, error_message)
    """
    if "raw_response" in parsed_json and len(parsed_json) == 1:
        return False, None, "JSON parsing failed - raw response returned"

    try:
        result = Section232ResultV2(**parsed_json)
        return True, result, None
    except Exception as e:
        return False, None, str(e)


def validate_citations_have_proof(result: Section232ResultV2) -> List[str]:
    """
    Business validation: if in_scope=true, must have proof.

    Rules:
    1. If in_scope=true, claim_code must be provided
    2. If in_scope=true, must have at least one citation with URL + quoted_text
    3. Warning (not error) if quoted_text doesn't contain the HTS code

    Args:
        result: Validated Section232ResultV2 object

    Returns:
        List of validation error strings (empty if valid)
    """
    errors = []

    for metal, scope in result.results.items():
        if scope.in_scope is True:
            # Rule 1: Must have claim_code
            if not scope.claim_code:
                errors.append(f"{metal}: in_scope=true but no claim_code")

            # Rule 2: Must have at least one citation with URL + quoted_text
            valid_citations = [
                c for c in scope.citations
                if c.source_url and c.quoted_text
            ]
            if not valid_citations:
                errors.append(f"{metal}: in_scope=true but no citation with source_url + quoted_text")

    return errors


def validate_citations_contain_hts(result: Section232ResultV2) -> List[str]:
    """
    Check if quoted_text contains the HTS code (warning, not error).

    This is a softer check - the quote should ideally contain the HTS,
    but sometimes the source uses slightly different formatting.

    Args:
        result: Validated Section232ResultV2 object

    Returns:
        List of warning strings
    """
    warnings = []

    # Normalize HTS for matching
    hts_10 = result.hts_code  # "8544.42.9090"
    hts_8_dotted = result.hts_code[:10]  # "8544.42.90"
    hts_8_nodot = result.hts_code.replace(".", "")[:8]  # "85444290"

    for metal, scope in result.results.items():
        if scope.in_scope is True:
            for i, citation in enumerate(scope.citations):
                if citation.quoted_text:
                    quote_normalized = citation.quoted_text.replace(".", "").replace(" ", "")
                    quote_original = citation.quoted_text

                    # Check various HTS formats
                    hts_found = (
                        hts_10 in quote_original or
                        hts_8_dotted in quote_original or
                        hts_8_nodot in quote_normalized
                    )

                    if not hts_found:
                        warnings.append(
                            f"{metal}.citations[{i}]: quoted_text does not contain HTS code "
                            f"(expected {hts_8_dotted} or similar)"
                        )

    return warnings
