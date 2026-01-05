#!/usr/bin/env python
"""
HTS Verifier MCP Server

Provides AI-powered HTS scope verification via Google Gemini.
Uses Google Search grounding for real-time CBP/CSMS lookups.

Two-tier model approach:
- gemini-2.5-flash: Fast, cost-effective for testing/development
- gemini-3-pro-preview: Production with thinking mode

Usage:
    # Run as MCP server
    python -m mcp_servers.hts_verifier

    # Add to Claude Code
    claude mcp add --transport stdio hts-verifier \
      --env GEMINI_API_KEY=$GEMINI_API_KEY \
      -- python -m mcp_servers.hts_verifier
"""

import json
import os
from datetime import datetime
from typing import Optional

# Load environment before importing config
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from mcp.server.fastmcp import FastMCP

from .config import GEMINI_API_KEY, MODELS, THINKING_BUDGET
from .schemas import (
    validate_section_232,
    validate_section_301,
    validate_section_232_v2,
    validate_citations_have_proof,
    validate_citations_contain_hts,
)


# Initialize FastMCP Server
mcp = FastMCP("hts-verifier")

# Initialize Gemini client
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set")

client = genai.Client(api_key=GEMINI_API_KEY)


def extract_grounding_urls(response) -> list:
    """Extract grounding source URLs from Gemini response metadata."""
    grounding_urls = []
    try:
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata
                if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                    for chunk in metadata.grounding_chunks:
                        if hasattr(chunk, 'web') and chunk.web:
                            if hasattr(chunk.web, 'uri'):
                                grounding_urls.append(chunk.web.uri)
    except Exception:
        pass  # Silently handle missing metadata
    return grounding_urls


def parse_json_response(text: str) -> dict:
    """Extract JSON from Gemini response text."""
    try:
        # Find JSON in response
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(text[json_start:json_end])
    except json.JSONDecodeError:
        pass
    return {"raw_response": text}


@mcp.tool()
def verify_hts_scope(
    hts_code: str,
    material: str = "all",
    use_production_model: bool = False,
    force_search: bool = False,
    use_v2_schema: bool = True
) -> dict:
    """
    Verify Section 232 material scope for an HTS code using Gemini search.

    This tool searches official CBP sources to determine if an HTS code
    is subject to Section 232 tariffs for copper, steel, and/or aluminum.

    v9.2: Now uses evidence-first approach with citations containing verbatim quotes.

    Args:
        hts_code: The HTS code to verify (e.g., "8544.42.9090")
        material: Specific material to check ("copper", "steel", "aluminum", "all")
        use_production_model: If True, use Gemini Pro with thinking; else use Flash (free)
        force_search: If True, this is a forced refresh (tracked in metadata)
        use_v2_schema: If True (default), use v9.2 evidence-first schema with citations

    Returns:
        dict containing:
            - scope: Scope information with citations[] containing verbatim quotes
            - metadata: Model used, timestamp, grounding URLs, force_search flag
            - validation: Schema validation + business validation results
    """
    # Select model based on flag
    model_id = MODELS["production"] if use_production_model else MODELS["test"]

    # Configure Google Search grounding
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    # Build generation config
    config_kwargs = {
        "tools": [google_search_tool],
    }

    # Add thinking mode for production model
    if use_production_model and "pro" in model_id.lower():
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=THINKING_BUDGET["high"]
        )

    config = types.GenerateContentConfig(**config_kwargs)

    # Build material-specific query
    if material == "all":
        material_query = "copper, steel, and/or aluminum"
    else:
        material_query = material

    # Construct the verification prompt (v9.2 evidence-first with citations)
    if use_v2_schema:
        prompt = f"""You are verifying U.S. Section 232 tariff scope using OFFICIAL sources.

TASK:
Determine whether HTS code {hts_code} is in scope for Section 232 derivative tariffs
for each metal: copper, steel, aluminum.

SOURCE REQUIREMENTS:
- Use Google Search grounding.
- Prefer official domains: cbp.gov, federalregister.gov, usitc.gov.
- Do NOT rely on blogs or secondary summaries unless no official source exists.

EVIDENCE REQUIREMENTS:
For EACH metal (copper/steel/aluminum):
- Set in_scope to:
  - true ONLY if you found explicit evidence the HTS is listed for that metal
  - false ONLY if you found explicit evidence it is excluded/not covered
  - null if you cannot confirm either way

If in_scope is true:
- claim_code must be provided
- citations must include at least ONE citation where:
  - source_url is present
  - quoted_text is VERBATIM from the source and includes the HTS code (or the 8-digit HTS)

If you cannot extract a verbatim quote:
- set quoted_text to null (do NOT paraphrase)

OUTPUT RULES:
- Output ONLY valid JSON.
- No markdown.
- No commentary outside JSON.

Return JSON with this exact structure:
{{
  "hts_code": "{hts_code}",
  "query_type": "section_232",
  "results": {{
    "copper": {{
      "in_scope": true|false|null,
      "claim_code": "9903.xx.xx"|null,
      "disclaim_code": "9903.xx.xx"|null,
      "citations": [
        {{
          "source_url": "https://...",
          "source_title": "title of the page/document",
          "source_document": "CSMS #... or Federal Register citation or document name",
          "effective_date": "YYYY-MM-DD"|null,
          "location_hint": "table row / heading / bullet number",
          "evidence_type": "table|paragraph|bullet|scope_statement",
          "quoted_text": "verbatim quote max 400 chars"|null
        }}
      ]
    }},
    "steel": {{ ... same fields ... }},
    "aluminum": {{ ... same fields ... }}
  }},
  "notes": "optional short notes"|null
}}
"""
    else:
        # Legacy v9.1 prompt (for backwards compatibility)
        prompt = f"""You are a U.S. Customs and Border Protection (CBP) tariff expert specializing in Section 232 duties.

TASK: Determine if HTS code {hts_code} is subject to Section 232 tariffs for {material_query}.

SEARCH FOR:
1. Official CBP CSMS (Cargo Systems Messaging Service) bulletins mentioning this HTS code
2. The "LIST OF STEEL HTS SUBJECT TO SECTION 232" (effective August 18, 2025 or later)
3. The aluminum derivative products list
4. The copper derivative products list (effective March 12, 2025 or later)
5. Federal Register notices about Section 232 inclusions/exclusions

IMPORTANT CONTEXT:
- HTS 8544.42.xx (insulated copper wire/cable) is typically in scope for copper AND often steel
- "In scope" means the HTS IS on the official list - the product MAY contain that metal
- Check the full 8-digit or 10-digit HTS, not just the chapter

For EACH metal (copper, steel, aluminum), determine:
1. Is this HTS code on the official Section 232 list for that metal?
2. What is the Chapter 99 claim code? (e.g., 9903.80.01 for steel, 9903.85.01 for aluminum, 9903.78.01 for copper)
3. What is your source document?

Return your answer as JSON:
{{
    "hts_code": "{hts_code}",
    "copper": {{
        "in_scope": true/false,
        "claim_code": "9903.78.01 or null",
        "disclaim_code": "9903.78.02",
        "source": "Document name and date"
    }},
    "steel": {{
        "in_scope": true/false,
        "claim_code": "9903.80.01 or 9903.81.xx or null",
        "disclaim_code": "9903.80.02 or 9903.81.xx",
        "source": "Document name and date"
    }},
    "aluminum": {{
        "in_scope": true/false,
        "claim_code": "9903.85.01 or 9903.85.xx or null",
        "disclaim_code": "9903.85.xx",
        "source": "Document name and date"
    }},
    "notes": "Any additional context about this HTS code"
}}

Only return "in_scope": true if you find EXPLICIT evidence in official sources.
"""

    try:
        # Call Gemini
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config
        )

        # Store raw response for caching
        raw_response_text = response.text

        # Extract grounding URLs
        grounding_urls = extract_grounding_urls(response)

        # Parse response
        scope_data = parse_json_response(raw_response_text)

        # Validate against schema (v2 or legacy)
        if use_v2_schema:
            is_valid, validated_result, validation_error = validate_section_232_v2(scope_data)

            # Business validation for v2 (only if schema is valid)
            business_errors = []
            business_warnings = []
            if is_valid and validated_result:
                business_errors = validate_citations_have_proof(validated_result)
                business_warnings = validate_citations_contain_hts(validated_result)
        else:
            is_valid, validated_result, validation_error = validate_section_232(scope_data)
            business_errors = []
            business_warnings = []

        # Get thinking budget if used
        thinking_budget_used = THINKING_BUDGET["high"] if use_production_model and "pro" in model_id.lower() else None

        return {
            "success": True,
            "scope": scope_data,
            "raw_response": raw_response_text,  # For caching in v9.0
            "metadata": {
                "model": model_id,
                "timestamp": datetime.utcnow().isoformat(),
                "grounding_urls": grounding_urls,
                "force_search": force_search,
                "material_queried": material,
                "thinking_budget": thinking_budget_used,
                "query_type": "section_232",
                "schema_version": "v2" if use_v2_schema else "v1"
            },
            "validation": {
                "is_valid": is_valid,
                "error": validation_error,
                "business_errors": business_errors,
                "business_warnings": business_warnings
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "metadata": {
                "model": model_id,
                "timestamp": datetime.utcnow().isoformat(),
                "force_search": force_search
            }
        }


@mcp.tool()
def verify_section_301(
    hts_code: str,
    use_production_model: bool = False,
    force_search: bool = False
) -> dict:
    """
    Verify Section 301 inclusion and list assignment for an HTS code.

    Searches USTR sources to determine which Section 301 list (1, 2, 3, 4A, 4B)
    an HTS code is on and the applicable Chapter 99 code.

    Args:
        hts_code: The HTS code to verify (e.g., "8544.42.9090")
        use_production_model: If True, use Gemini Pro with thinking; else use Flash (free)
        force_search: If True, this is a forced refresh

    Returns:
        dict containing inclusion status, list assignment, Chapter 99 code, and duty rate
    """
    model_id = MODELS["production"] if use_production_model else MODELS["test"]

    # Configure Google Search grounding
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    config = types.GenerateContentConfig(
        tools=[google_search_tool]
    )

    prompt = f"""You are a U.S. trade expert specializing in Section 301 tariffs on Chinese goods.

TASK: Determine if HTS code {hts_code} is subject to Section 301 tariffs on imports from China.

SEARCH FOR:
1. USTR Section 301 List 1 (effective July 6, 2018) - 25%
2. USTR Section 301 List 2 (effective August 23, 2018) - 25%
3. USTR Section 301 List 3 (effective various dates) - up to 25%
4. USTR Section 301 List 4A (effective September 1, 2019) - 7.5%
5. USTR Section 301 List 4B (never implemented, suspended)
6. Any exclusions or exemptions for this HTS code

The Chapter 99 codes are:
- List 1: 9903.88.01 (25%)
- List 2: 9903.88.02 (25%)
- List 3: 9903.88.03 (25%) or 9903.88.04
- List 4A: 9903.88.15 (7.5%)

Return your answer as JSON:
{{
    "hts_code": "{hts_code}",
    "included": true/false,
    "list_name": "list_1" | "list_2" | "list_3" | "list_4a" | null,
    "chapter_99_code": "9903.88.xx",
    "duty_rate": 0.25,
    "source": "USTR document reference",
    "exclusions": "Any active exclusions, or null",
    "notes": "Additional context"
}}
"""

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config
        )

        # Store raw response for caching
        raw_response_text = response.text

        grounding_urls = extract_grounding_urls(response)
        result_data = parse_json_response(raw_response_text)

        # Validate against schema
        is_valid, validated_result, validation_error = validate_section_301(result_data)

        return {
            "success": True,
            "result": result_data,
            "raw_response": raw_response_text,  # For caching in v9.0
            "metadata": {
                "model": model_id,
                "timestamp": datetime.utcnow().isoformat(),
                "grounding_urls": grounding_urls,
                "force_search": force_search,
                "query_type": "section_301"  # For cache keying
            },
            "validation": {
                "is_valid": is_valid,
                "error": validation_error
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "metadata": {
                "model": model_id,
                "timestamp": datetime.utcnow().isoformat(),
                "force_search": force_search
            }
        }


@mcp.tool()
def test_gemini_connection() -> dict:
    """
    Test the Gemini API connection with a simple query.

    Use this to verify the API key is working before running verification queries.

    Returns:
        dict with connection status and model info
    """
    try:
        # Simple test query
        response = client.models.generate_content(
            model=MODELS["test"],
            contents="What is 2+2? Reply with just the number."
        )

        return {
            "success": True,
            "test_model": MODELS["test"],
            "production_model": MODELS["production"],
            "response": response.text.strip(),
            "api_key_set": bool(GEMINI_API_KEY),
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "api_key_set": bool(GEMINI_API_KEY),
            "timestamp": datetime.utcnow().isoformat()
        }


# =============================================================================
# v10.0 Phase 5: Discovery Mode + RAG Integration
# =============================================================================

@mcp.tool()
def discover_official_sources(
    hts_code: str,
    program_id: str = "section_232",
    material: str = "all"
) -> dict:
    """
    Discovery Mode: Find official document URLs (NOT conclusions).

    v10.0: Gemini returns URLs/identifiers ONLY - no conclusions trusted.
    The system will fetch these documents via trusted connectors and
    run them through the RAG pipeline.

    Args:
        hts_code: The HTS code to find sources for
        program_id: The tariff program (section_232, section_301)
        material: Material type (copper, steel, aluminum, all)

    Returns:
        dict containing official source URLs to fetch
    """
    model_id = MODELS["test"]

    # Configure Google Search grounding
    google_search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    config = types.GenerateContentConfig(
        tools=[google_search_tool]
    )

    # Discovery prompt - returns URLs only, NO conclusions
    prompt = f"""You are finding OFFICIAL government sources for tariff verification.

TASK:
Find official documents that would contain scope information for HTS code {hts_code}
regarding {program_id} {'for ' + material if material != 'all' else ''}.

SEARCH FOR:
1. CBP CSMS bulletins mentioning this HTS code
2. Federal Register notices about {program_id}
3. USITC HTS schedule entries
4. Official proclamations or Executive Orders

RETURN ONLY URLs - DO NOT MAKE SCOPE DETERMINATIONS.

Return JSON with this exact structure:
{{
    "hts_code": "{hts_code}",
    "program_id": "{program_id}",
    "official_sources": [
        {{
            "source_type": "CSMS" | "FEDERAL_REGISTER" | "USITC" | "USTR",
            "url": "https://...",
            "title": "document title if known",
            "why_relevant": "brief description of why this document is relevant",
            "expected_to_contain": ["keywords expected in document"]
        }}
    ],
    "search_notes": "any notes about the search"
}}

CRITICAL:
- Return URLS ONLY
- Do NOT return scope conclusions
- Do NOT say whether the HTS is in scope
- Only return official government URLs
"""

    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config
        )

        raw_response_text = response.text
        grounding_urls = extract_grounding_urls(response)
        result_data = parse_json_response(raw_response_text)

        return {
            "success": True,
            "mode": "discovery",
            "sources": result_data.get("official_sources", []),
            "grounding_urls": grounding_urls,
            "metadata": {
                "model": model_id,
                "timestamp": datetime.utcnow().isoformat(),
                "hts_code": hts_code,
                "program_id": program_id,
            },
            "warning": "These are source URLs only. Scope must be verified via RAG pipeline."
        }

    except Exception as e:
        return {
            "success": False,
            "mode": "discovery",
            "error": str(e),
            "metadata": {
                "model": model_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }


@mcp.tool()
def verify_with_rag(
    hts_code: str,
    program_id: str = "section_232",
    material: Optional[str] = None,
    force_rag: bool = False
) -> dict:
    """
    v10.0: Verify HTS scope using the RAG pipeline.

    This is the preferred verification method that uses:
    1. Verified assertion cache (fast path)
    2. RAG over official document corpus
    3. Reader LLM + Validator LLM
    4. Write Gate (mechanical proof checks)

    Args:
        hts_code: The HTS code to verify
        program_id: The tariff program (section_232, section_301)
        material: Material type for 232 (copper, steel, aluminum)
        force_rag: If True, skip verified cache and run full RAG

    Returns:
        dict with verified scope information and evidence
    """
    try:
        # Import here to avoid circular imports and allow standalone MCP usage
        from app.web import create_app
        from app.web.db import db
        from app.rag import RAGOrchestrator

        app = create_app()
        with app.app_context():
            orchestrator = RAGOrchestrator(db.session)
            result = orchestrator.verify_scope(
                hts_code=hts_code,
                program_id=program_id,
                material=material,
                force_rag=force_rag
            )

            return {
                "success": result.success,
                "source": result.source,
                "is_verified": result.is_verified,
                "scope": {
                    "in_scope": result.in_scope,
                    "claim_codes": result.claim_codes,
                    "disclaim_codes": result.disclaim_codes,
                    "confidence": result.confidence,
                },
                "evidence": {
                    "quote": result.evidence_quote,
                    "document_id": result.document_id,
                    "chunk_id": result.chunk_id,
                },
                "metadata": {
                    "verified_assertion_id": result.verified_assertion_id,
                    "review_queue_id": result.review_queue_id,
                    "timestamp": datetime.utcnow().isoformat(),
                },
                "error": result.error,
            }

    except ImportError as e:
        return {
            "success": False,
            "error": f"RAG pipeline not available: {str(e)}",
            "fallback": "Use verify_hts_scope for Gemini-based verification"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "metadata": {
                "timestamp": datetime.utcnow().isoformat()
            }
        }


# Entry point for running as MCP server
if __name__ == "__main__":
    mcp.run()
