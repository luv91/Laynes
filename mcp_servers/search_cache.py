"""
Search Cache Service (v9.0 → v10.0)

Implements the 3-tier cache check before calling Gemini:
1. PostgreSQL - Exact match on (hts_code, query_type, material)
2. Pinecone - Semantic match on similar queries
3. Gemini - Live search with Google Search grounding

Also handles persisting results after successful searches.

v9.2 Update: Evidence-First Citations
- Extracts citations[] from Gemini response
- Persists EvidenceQuote records for each citation

v9.3 Update: Evidence Quote Vector Indexing
- Indexes quoted_text as high-signal chunks in Pinecone

v10.0 BREAKING CHANGE: Stop Caching LLM Conclusions as Truth
- Gemini responses are NO LONGER treated as authoritative
- All responses go to NeedsReviewQueue for verification
- Cache only returns VERIFIED results (is_verified=True)
- Unverified responses return with reason="unverified_llm_response"

This breaks the "cache Gemini conclusion" anti-pattern that led to
incorrect scope determinations being treated as truth.

Next steps (Phase 2+):
- Write Gate: Mechanical proof checks (quote exists in stored doc)
- Validator LLM: Semantic verification of Reader output
- Verified Assertions: Proof-carrying facts with document links
"""

import hashlib
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

# Import will work when running as part of the app
# For MCP server standalone, these need Flask app context
try:
    from app.web.db import db
    from app.web.db.models.tariff_tables import (
        GeminiSearchResult,
        GroundingSource,
        SearchAuditLog,
        EvidenceQuote,  # v9.2
        NeedsReviewQueue,  # v10.0 - Phase 1: Stop caching LLM conclusions
    )
    from app.chat.vector_stores.tariff_search import (
        TariffVectorSearch,
        extract_domain,
        classify_source_type,
        get_reliability_score
    )
    HAS_APP_CONTEXT = True
except ImportError:
    HAS_APP_CONTEXT = False

# Cache configuration
CACHE_TTL_DAYS = 30  # Results expire after 30 days unless verified
PINECONE_SIMILARITY_THRESHOLD = 0.85  # Minimum score for vector cache hit


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def parse_date_string(date_str: Optional[str]):
    """Parse a date string like '2025-08-18' to a date object."""
    if not date_str:
        return None
    try:
        from datetime import date
        parts = date_str.split('-')
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        pass
    return None


def persist_evidence_quotes(
    session: Session,
    search_result_id: str,
    hts_code: str,
    query_type: str,
    result_json: Dict,
    grounding_urls: List[str]
) -> int:
    """
    Extract and persist evidence quotes from v9.2 Gemini response.

    Parses the results.{metal}.citations[] structure and creates
    EvidenceQuote records for each citation.

    Args:
        session: SQLAlchemy session
        search_result_id: UUID of the parent GeminiSearchResult
        hts_code: HTS code being verified
        query_type: Query type (e.g., 'section_232')
        result_json: Parsed JSON from Gemini (v9.2 format)
        grounding_urls: List of grounding URLs from Google Search

    Returns:
        Number of EvidenceQuote records created
    """
    if not HAS_APP_CONTEXT:
        return 0

    # Check for v9.2 structure: results.{metal}
    results = result_json.get("results", {})
    if not results:
        # Not a v9.2 response, skip
        return 0

    count = 0
    grounding_url_set = set(grounding_urls)

    for metal, scope_data in results.items():
        if not isinstance(scope_data, dict):
            continue

        in_scope = scope_data.get("in_scope")
        claim_code = scope_data.get("claim_code")
        disclaim_code = scope_data.get("disclaim_code")
        citations = scope_data.get("citations", [])

        for citation in citations:
            if not isinstance(citation, dict):
                continue

            source_url = citation.get("source_url", "")
            quoted_text = citation.get("quoted_text")

            # Extract domain
            domain = extract_domain(source_url) if source_url else None

            # Compute quote hash for deduplication
            quote_hash = None
            if quoted_text:
                quote_hash = hashlib.sha256(quoted_text.encode()).hexdigest()

            # Check if URL was in grounding metadata
            url_in_grounding = source_url in grounding_url_set if source_url else False

            # Parse effective date
            effective_date = parse_date_string(citation.get("effective_date"))

            evidence_quote = EvidenceQuote(
                id=generate_uuid(),
                search_result_id=search_result_id,
                program_id=query_type,
                material=metal,
                hts_code=hts_code,
                in_scope=in_scope,
                claim_code=claim_code,
                disclaim_code=disclaim_code,
                source_url=source_url,
                source_domain=domain,
                source_title=citation.get("source_title"),
                source_document=citation.get("source_document"),
                effective_date=effective_date,
                location_hint=citation.get("location_hint"),
                evidence_type=citation.get("evidence_type"),
                quoted_text=quoted_text,
                quote_hash=quote_hash,
                quote_verified=False,
                url_in_grounding_metadata=url_in_grounding,
                created_at=datetime.utcnow()
            )
            session.add(evidence_quote)
            count += 1

    return count


def check_postgres_cache(
    session: Session,
    hts_code: str,
    query_type: str,
    material: Optional[str] = None,
    require_verified: bool = True
) -> Optional[Dict]:
    """
    Check PostgreSQL for cached search result.

    Layer 1 of the cache - exact match lookup.

    v10.0 BREAKING CHANGE: By default, only returns VERIFIED results.
    Unverified LLM responses are NOT treated as authoritative.

    Args:
        session: SQLAlchemy session
        hts_code: HTS code to look up
        query_type: Query type ('section_232', 'section_301', etc.)
        material: Optional material type
        require_verified: If True (default), only return verified results.
                         Set to False for debugging/admin purposes only.

    Returns:
        Cached result dict or None if not found/expired/unverified
    """
    if not HAS_APP_CONTEXT:
        return None

    result = session.query(GeminiSearchResult).filter(
        GeminiSearchResult.hts_code == hts_code,
        GeminiSearchResult.query_type == query_type,
        GeminiSearchResult.material == material
    ).first()

    if not result:
        return None

    # Check if expired
    if result.is_expired():
        return None

    # v10.0: Only return verified results as authoritative
    # Unverified LLM responses should NOT be trusted
    if require_verified and not result.is_verified:
        return {
            "hit": False,
            "source": "postgres",
            "reason": "unverified_llm_response",
            "search_result_id": result.id,
            "message": "Found cached LLM response but it has not been verified. "
                      "Use force_search=True to refresh or wait for verification."
        }

    return {
        "hit": True,
        "source": "postgres",
        "data": result.result_json,
        "search_result_id": result.id,
        "searched_at": result.searched_at.isoformat() if result.searched_at else None,
        "model_used": result.model_used,
        "is_verified": result.is_verified
    }


def check_pinecone_cache(
    hts_code: str,
    query_type: str,
    material: Optional[str] = None
) -> Optional[Dict]:
    """
    Check Pinecone for semantically similar cached content.

    Layer 2 of the cache - vector similarity lookup.

    Args:
        hts_code: HTS code to look up
        query_type: Query type
        material: Optional material type

    Returns:
        Cached result dict or None if no good match found
    """
    try:
        vector_search = TariffVectorSearch()

        # Build semantic query
        material_str = material if material and material != "all" else "scope"
        query = f"Section 232 {material_str} for HTS {hts_code}"

        # Search with filters
        matches = vector_search.search_similar(
            query=query,
            hts_code=hts_code,
            query_type=query_type,
            top_k=3
        )

        if matches and matches[0]["score"] >= PINECONE_SIMILARITY_THRESHOLD:
            best_match = matches[0]
            return {
                "hit": True,
                "source": "pinecone",
                "data": best_match["metadata"],
                "confidence": best_match["score"],
                "chunk_text": best_match["metadata"].get("chunk_text")
            }

    except Exception:
        # Silently fail - fall through to Gemini
        pass

    return None


def check_cache_before_gemini(
    session: Session,
    hts_code: str,
    query_type: str,
    material: Optional[str] = None,
    force_search: bool = False
) -> Dict:
    """
    Multi-tier cache check before calling Gemini.

    Args:
        session: SQLAlchemy session
        hts_code: HTS code to verify
        query_type: Type of query
        material: Optional material filter
        force_search: If True, skip cache and go directly to Gemini

    Returns:
        {"hit": True, "source": "postgres"|"pinecone", "data": {...}} on cache hit
        {"hit": False} on cache miss
    """
    if force_search:
        return {"hit": False, "reason": "force_search"}

    # Layer 1: PostgreSQL
    pg_result = check_postgres_cache(session, hts_code, query_type, material)
    if pg_result:
        return pg_result

    # Layer 2: Pinecone
    pc_result = check_pinecone_cache(hts_code, query_type, material)
    if pc_result:
        return pc_result

    # Layer 3: No cache hit - must call Gemini
    return {"hit": False}


def persist_search_result(
    session: Session,
    hts_code: str,
    query_type: str,
    material: Optional[str],
    result_json: Dict,
    raw_response: str,
    model_used: str,
    thinking_budget: Optional[int],
    grounding_urls: list,
    force_search: bool = False
) -> str:
    """
    Save search result to PostgreSQL and queue for review.

    v10.0 BREAKING CHANGE: Results are NO LONGER treated as truth.
    All Gemini responses go to NeedsReviewQueue for verification.

    The result is stored in GeminiSearchResult with is_verified=False,
    and a NeedsReviewQueue entry is created. Only after passing through
    the Write Gate + Validator LLM can results become verified.

    Args:
        session: SQLAlchemy session
        hts_code: The HTS code searched
        query_type: Type of query
        material: Material if applicable
        result_json: Parsed JSON result
        raw_response: Raw text response
        model_used: Which model was used
        thinking_budget: Thinking budget if used
        grounding_urls: List of source URLs
        force_search: Whether this was a force search

    Returns:
        UUID of the created search result
    """
    if not HAS_APP_CONTEXT:
        return generate_uuid()

    # Check if we're replacing an existing result
    existing = session.query(GeminiSearchResult).filter(
        GeminiSearchResult.hts_code == hts_code,
        GeminiSearchResult.query_type == query_type,
        GeminiSearchResult.material == material
    ).first()

    if existing:
        # Delete old Pinecone vectors
        try:
            vector_search = TariffVectorSearch()
            vector_search.delete_by_search_result(existing.id)
        except Exception:
            pass

        # Delete old record (cascade deletes grounding sources)
        session.delete(existing)
        session.flush()

    # Create new search result
    result_id = generate_uuid()
    expires_at = datetime.utcnow() + timedelta(days=CACHE_TTL_DAYS)

    search_result = GeminiSearchResult(
        id=result_id,
        hts_code=hts_code,
        query_type=query_type,
        material=material,
        result_json=result_json,
        raw_response=raw_response,
        model_used=model_used,
        thinking_budget=thinking_budget,
        searched_at=datetime.utcnow(),
        expires_at=expires_at,
        was_force_search=force_search,
        is_verified=False  # v10.0: Explicitly NOT verified
    )
    session.add(search_result)

    # Create grounding source records
    grounding_source_records = []
    for url in grounding_urls:
        domain = extract_domain(url)
        source_type = classify_source_type(domain) if domain else "other"
        reliability = get_reliability_score(source_type)

        source = GroundingSource(
            id=generate_uuid(),
            search_result_id=result_id,
            url=url,
            domain=domain,
            source_type=source_type,
            reliability_score=reliability
        )
        session.add(source)
        grounding_source_records.append({
            "url": url,
            "domain": domain,
            "fetched_content": None  # Content fetching is optional/future
        })

    # v9.2: Persist evidence quotes from citations[]
    persist_evidence_quotes(
        session=session,
        search_result_id=result_id,
        hts_code=hts_code,
        query_type=query_type,
        result_json=result_json,
        grounding_urls=grounding_urls
    )

    # v10.0: Queue for review - DO NOT TRUST LLM CONCLUSIONS
    # This is the key change: results are NOT authoritative until verified
    review_entry = NeedsReviewQueue(
        id=generate_uuid(),
        hts_code=hts_code,
        query_type=query_type,
        material=material,
        search_result_id=result_id,
        block_reason="unverified_llm_response",
        block_details={
            "model_used": model_used,
            "grounding_url_count": len(grounding_urls),
            "has_citations": bool(result_json.get("results", {})),
            "searched_at": datetime.utcnow().isoformat(),
            "note": "Gemini response requires verification via Write Gate + Validator LLM"
        },
        status="pending",
        priority=1 if force_search else 0,  # Force searches get higher priority
        created_at=datetime.utcnow()
    )
    session.add(review_entry)

    session.commit()

    # Index in Pinecone (for discovery, NOT as truth)
    try:
        vector_search = TariffVectorSearch()
        vector_search.index_search_result(
            search_result_id=result_id,
            hts_code=hts_code,
            query_type=query_type,
            material=material,
            raw_response=raw_response,
            model_used=model_used,
            grounding_sources=grounding_source_records
        )

        # v9.3: Index evidence quotes as high-signal chunks
        vector_search.index_evidence_quotes(
            search_result_id=result_id,
            hts_code=hts_code,
            query_type=query_type,
            result_json=result_json,
            grounding_urls=grounding_urls
        )
    except Exception:
        # Pinecone indexing is best-effort
        pass

    return result_id


def log_search_request(
    session: Session,
    hts_code: str,
    query_type: str,
    material: Optional[str],
    cache_hit: bool,
    cache_source: Optional[str],
    force_search: bool,
    response_time_ms: Optional[int],
    model_used: Optional[str],
    success: bool,
    error_message: Optional[str] = None,
    search_result_id: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    requested_by: Optional[str] = None
):
    """
    Log a search request to the audit log.

    Called for every search, whether cache hit or miss.

    Args:
        session: SQLAlchemy session
        Various search metadata...
    """
    if not HAS_APP_CONTEXT:
        return

    # Estimate cost based on tokens (Gemini pricing)
    estimated_cost = None
    if input_tokens and output_tokens and model_used:
        if "gemini-3-pro" in model_used:
            # ~$0.0375/1K input, $0.15/1K output
            estimated_cost = (input_tokens * 0.0000375) + (output_tokens * 0.00015)
        elif "gemini-2.5-flash" in model_used:
            # Much cheaper - ~$0.00015/1K input, $0.0006/1K output (estimated)
            estimated_cost = (input_tokens * 0.00000015) + (output_tokens * 0.0000006)

    audit_log = SearchAuditLog(
        id=generate_uuid(),
        hts_code=hts_code,
        query_type=query_type,
        material=material,
        requested_at=datetime.utcnow(),
        requested_by=requested_by,
        cache_hit=cache_hit,
        cache_source=cache_source,
        force_search=force_search,
        response_time_ms=response_time_ms,
        model_used=model_used,
        success=success,
        error_message=error_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost,
        search_result_id=search_result_id
    )
    session.add(audit_log)
    session.commit()


def verify_with_caching(
    session: Session,
    hts_code: str,
    query_type: str,
    material: Optional[str] = None,
    force_search: bool = False,
    gemini_callable=None,
    requested_by: Optional[str] = None
) -> Dict:
    """
    Main entry point with full caching logic.

    v10.0 BREAKING CHANGE: Only returns VERIFIED results as authoritative.

    This is the function to call from the MCP server:
    1. Check cache for VERIFIED results (unless force_search)
    2. Call Gemini if needed (cache miss or no verified result)
    3. Persist results and queue for review
    4. Log the request

    Args:
        session: SQLAlchemy session
        hts_code: HTS code to verify
        query_type: Type of verification
        material: Material filter
        force_search: Bypass cache
        gemini_callable: Function to call Gemini (injected for testability)
        requested_by: Who requested this search

    Returns:
        Result dict with scope information.

        If is_verified=True: Result is authoritative (from verified cache)
        If is_verified=False: Result is from Gemini but NOT YET VERIFIED
                              (queued in NeedsReviewQueue)
    """
    start_time = time.time()

    # Check cache unless force_search
    cache_result = check_cache_before_gemini(
        session, hts_code, query_type, material, force_search
    )

    if cache_result.get("hit"):
        # Log cache hit (verified result)
        response_time_ms = int((time.time() - start_time) * 1000)
        log_search_request(
            session=session,
            hts_code=hts_code,
            query_type=query_type,
            material=material,
            cache_hit=True,
            cache_source=cache_result["source"],
            force_search=False,
            response_time_ms=response_time_ms,
            model_used=cache_result.get("model_used"),
            success=True,
            search_result_id=cache_result.get("search_result_id"),
            requested_by=requested_by
        )
        return cache_result

    # Call Gemini (cache miss or force)
    if gemini_callable is None:
        return {"hit": False, "error": "No Gemini callable provided"}

    try:
        gemini_result = gemini_callable(hts_code, material, query_type)
        response_time_ms = int((time.time() - start_time) * 1000)

        if gemini_result.get("success"):
            # Persist result (will be queued for review, NOT treated as truth)
            search_result_id = persist_search_result(
                session=session,
                hts_code=hts_code,
                query_type=query_type,
                material=material,
                result_json=gemini_result.get("scope", {}),
                raw_response=gemini_result.get("raw_response", ""),
                model_used=gemini_result["metadata"]["model"],
                thinking_budget=gemini_result["metadata"].get("thinking_budget"),
                grounding_urls=gemini_result["metadata"].get("grounding_urls", []),
                force_search=force_search
            )

            # Log success
            log_search_request(
                session=session,
                hts_code=hts_code,
                query_type=query_type,
                material=material,
                cache_hit=False,
                cache_source="gemini",
                force_search=force_search,
                response_time_ms=response_time_ms,
                model_used=gemini_result["metadata"]["model"],
                success=True,
                search_result_id=search_result_id,
                requested_by=requested_by
            )

            # v10.0: Return with clear UNVERIFIED warning
            return {
                "hit": False,
                "source": "gemini",
                "data": gemini_result.get("scope", {}),
                "metadata": gemini_result.get("metadata", {}),
                "search_result_id": search_result_id,
                "is_verified": False,  # CRITICAL: Not yet verified
                "verification_status": "pending_review",
                "warning": "This result is from Gemini and has NOT been verified. "
                          "It has been queued for review. Do not treat as authoritative."
            }
        else:
            # Log failure
            log_search_request(
                session=session,
                hts_code=hts_code,
                query_type=query_type,
                material=material,
                cache_hit=False,
                cache_source="gemini",
                force_search=force_search,
                response_time_ms=response_time_ms,
                model_used=gemini_result.get("metadata", {}).get("model"),
                success=False,
                error_message=gemini_result.get("error"),
                requested_by=requested_by
            )

            return {
                "hit": False,
                "source": "gemini",
                "error": gemini_result.get("error"),
                "success": False
            }

    except Exception as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        log_search_request(
            session=session,
            hts_code=hts_code,
            query_type=query_type,
            material=material,
            cache_hit=False,
            cache_source="gemini",
            force_search=force_search,
            response_time_ms=response_time_ms,
            model_used=None,
            success=False,
            error_message=str(e),
            requested_by=requested_by
        )
        return {
            "hit": False,
            "source": "gemini",
            "error": str(e),
            "success": False
        }
