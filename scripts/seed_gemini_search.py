"""
Seed Gemini search results for all supported HTS codes.

For each HTS in section_232_materials:
1. Call verify_hts_scope() with production model (gemini-3-pro-preview)
2. Persist result to gemini_search_results
3. Persist citations to evidence_quotes
4. Index quoted_text in Pinecone

Usage:
    cd lanes
    pipenv run python scripts/seed_gemini_search.py
    pipenv run python scripts/seed_gemini_search.py --hts 8544.42.90  # Single HTS
    pipenv run python scripts/seed_gemini_search.py --force  # Refresh all (bypass cache)
    pipenv run python scripts/seed_gemini_search.py --dry-run  # Show what would be seeded
"""

import argparse
import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import (
    Section232Material,
    GeminiSearchResult,
    EvidenceQuote,
    GroundingSource,
)
from mcp_servers.hts_verifier import verify_hts_scope
from mcp_servers.search_cache import persist_search_result


def format_hts_code(hts_8digit: str) -> str:
    """
    Format 8-digit HTS code to dotted format.

    Example: "85444290" -> "8544.42.90"
    """
    hts = hts_8digit.replace(".", "")  # Remove any existing dots
    if len(hts) >= 8:
        return f"{hts[:4]}.{hts[4:6]}.{hts[6:8]}"
    return hts_8digit


def get_supported_hts_codes(app) -> list:
    """Get all unique HTS codes from section_232_materials."""
    with app.app_context():
        materials = db.session.query(
            Section232Material.hts_8digit
        ).distinct().all()
        return [m.hts_8digit for m in materials]


def seed_hts_code(app, hts_code: str, force: bool = False) -> dict:
    """
    Run Gemini search and persist results for one HTS code.

    Uses production model (gemini-3-pro-preview) with thinking mode.

    Args:
        app: Flask app
        hts_code: Formatted HTS code (e.g., "8544.42.90")
        force: If True, bypass cache and refresh

    Returns:
        dict with success status and details
    """
    with app.app_context():
        # Check if already cached (unless force)
        if not force:
            existing = db.session.query(GeminiSearchResult).filter(
                GeminiSearchResult.hts_code == hts_code,
                GeminiSearchResult.query_type == "section_232"
            ).first()

            if existing and not existing.is_expired():
                return {
                    "success": True,
                    "cached": True,
                    "hts_code": hts_code,
                    "message": f"Already cached (searched {existing.searched_at})"
                }

        # Call Gemini with PRODUCTION model
        print(f"    Calling Gemini (gemini-3-pro-preview) for {hts_code}...")
        result = verify_hts_scope(
            hts_code=hts_code,
            material="all",
            use_production_model=True,  # Use production model
            force_search=force,
            use_v2_schema=True
        )

        if not result.get("success"):
            return {
                "success": False,
                "hts_code": hts_code,
                "error": result.get("error", "Unknown error")
            }

        # Persist to PostgreSQL + Pinecone
        search_result_id = persist_search_result(
            session=db.session,
            hts_code=hts_code,
            query_type="section_232",
            material=None,  # "all" stored as None
            result_json=result.get("scope", {}),
            raw_response=result.get("raw_response", ""),
            model_used=result["metadata"]["model"],
            thinking_budget=result["metadata"].get("thinking_budget"),
            grounding_urls=result["metadata"].get("grounding_urls", []),
            force_search=force
        )

        # Count what was created
        evidence_count = db.session.query(EvidenceQuote).filter(
            EvidenceQuote.search_result_id == search_result_id
        ).count()

        grounding_count = db.session.query(GroundingSource).filter(
            GroundingSource.search_result_id == search_result_id
        ).count()

        return {
            "success": True,
            "cached": False,
            "hts_code": hts_code,
            "search_result_id": search_result_id,
            "model": result["metadata"]["model"],
            "evidence_quotes": evidence_count,
            "grounding_sources": grounding_count,
            "validation": result.get("validation", {})
        }


def show_current_stats(app):
    """Show current database statistics."""
    with app.app_context():
        search_count = db.session.query(GeminiSearchResult).count()
        evidence_count = db.session.query(EvidenceQuote).count()
        grounding_count = db.session.query(GroundingSource).count()

        print("\nCurrent Database Stats:")
        print(f"  - Gemini search results: {search_count}")
        print(f"  - Evidence quotes: {evidence_count}")
        print(f"  - Grounding sources: {grounding_count}")


def main():
    parser = argparse.ArgumentParser(description='Seed Gemini search results for all HTS codes')
    parser.add_argument('--hts', type=str, help='Seed a single HTS code (e.g., "8544.42.90")')
    parser.add_argument('--force', action='store_true', help='Bypass cache and refresh all')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be seeded without calling Gemini')
    parser.add_argument('--delay', type=float, default=2.0, help='Delay between API calls (seconds)')

    args = parser.parse_args()

    # Create Flask app
    app = create_app()

    print("=" * 60)
    print("Seed Gemini Search Results (v9.3)")
    print("Model: gemini-3-pro-preview (production with thinking)")
    print("=" * 60)

    show_current_stats(app)

    # Get HTS codes to seed
    if args.hts:
        # Single HTS code
        hts_codes = [args.hts]
        print(f"\nSeeding single HTS code: {args.hts}")
    else:
        # All supported HTS codes
        raw_codes = get_supported_hts_codes(app)
        hts_codes = [format_hts_code(code) for code in raw_codes]
        print(f"\nFound {len(hts_codes)} supported HTS codes:")
        for code in hts_codes:
            print(f"  - {code}")

    if args.dry_run:
        print("\n[DRY RUN] Would seed the above HTS codes.")
        print("Run without --dry-run to actually call Gemini.")
        return

    print(f"\nSeeding {len(hts_codes)} HTS codes...")
    if args.force:
        print("(Force mode: bypassing cache)")
    print()

    # Seed each HTS code
    results = {"success": 0, "cached": 0, "failed": 0}

    for i, hts_code in enumerate(hts_codes, 1):
        print(f"[{i}/{len(hts_codes)}] {hts_code}")

        try:
            result = seed_hts_code(app, hts_code, force=args.force)

            if result.get("success"):
                if result.get("cached"):
                    print(f"    ⏭️  Skipped (already cached)")
                    results["cached"] += 1
                else:
                    print(f"    ✅ Seeded successfully")
                    print(f"       - Evidence quotes: {result.get('evidence_quotes', 0)}")
                    print(f"       - Grounding sources: {result.get('grounding_sources', 0)}")
                    if result.get("validation", {}).get("business_errors"):
                        print(f"       ⚠️  Business errors: {result['validation']['business_errors']}")
                    results["success"] += 1
            else:
                print(f"    ❌ Failed: {result.get('error', 'Unknown error')}")
                results["failed"] += 1

        except Exception as e:
            print(f"    ❌ Exception: {str(e)}")
            results["failed"] += 1

        # Delay between API calls (except for last one)
        if i < len(hts_codes) and not result.get("cached"):
            time.sleep(args.delay)

    # Summary
    print("\n" + "=" * 60)
    print("Seeding Complete!")
    print("=" * 60)
    print(f"  ✅ Newly seeded: {results['success']}")
    print(f"  ⏭️  Already cached: {results['cached']}")
    print(f"  ❌ Failed: {results['failed']}")

    show_current_stats(app)
    print("\nDone!")


if __name__ == "__main__":
    main()
