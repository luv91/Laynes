"""
Migration script for v9.0/v9.2 Search Persistence tables.

Creates the following tables:
- gemini_search_results: Cached Gemini search results
- grounding_sources: URLs/sources used for grounding
- search_audit_log: Audit trail for search requests
- evidence_quotes: v9.2 - Normalized citations with verbatim quotes

Usage:
    cd lanes
    pipenv run python scripts/migrate_v9_search_tables.py

To reset search tables (delete all cached data):
    pipenv run python scripts/migrate_v9_search_tables.py --reset

v9.0 Update (Jan 2026):
- Search Persistence & Vector Caching Architecture
- 3-tier cache: PostgreSQL → Pinecone → Gemini
- Tracks grounding URLs, model used, timestamps
- Cost tracking for API usage analytics

v9.2 Update (Jan 2026):
- Evidence-First Citations Architecture
- evidence_quotes table for normalized citations
- Business validation: in_scope=true requires proof
- Quote verification tracking
"""

import os
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import (
    GeminiSearchResult,
    GroundingSource,
    SearchAuditLog,
    EvidenceQuote,
)


def create_search_tables(app, reset=False):
    """Create v9.0/v9.2 search persistence tables."""
    with app.app_context():
        if reset:
            print("Dropping existing search tables...")
            # Drop in correct order (children first)
            EvidenceQuote.__table__.drop(db.engine, checkfirst=True)
            SearchAuditLog.__table__.drop(db.engine, checkfirst=True)
            GroundingSource.__table__.drop(db.engine, checkfirst=True)
            GeminiSearchResult.__table__.drop(db.engine, checkfirst=True)
            print("Tables dropped.")

        print("Creating v9.0/v9.2 search tables...")
        # Create tables (parent first, then children)
        GeminiSearchResult.__table__.create(db.engine, checkfirst=True)
        GroundingSource.__table__.create(db.engine, checkfirst=True)
        SearchAuditLog.__table__.create(db.engine, checkfirst=True)
        EvidenceQuote.__table__.create(db.engine, checkfirst=True)
        print("Tables created successfully!")


def show_table_stats(app):
    """Show current table statistics."""
    with app.app_context():
        try:
            search_count = db.session.query(GeminiSearchResult).count()
            source_count = db.session.query(GroundingSource).count()
            audit_count = db.session.query(SearchAuditLog).count()
            evidence_count = db.session.query(EvidenceQuote).count()

            print("\nSearch Persistence Statistics:")
            print(f"  - Cached search results: {search_count}")
            print(f"  - Grounding sources tracked: {source_count}")
            print(f"  - Evidence quotes (v9.2): {evidence_count}")
            print(f"  - Audit log entries: {audit_count}")

            # Show cache hit rate if we have audit logs
            if audit_count > 0:
                cache_hits = db.session.query(SearchAuditLog).filter(
                    SearchAuditLog.cache_hit == True
                ).count()
                hit_rate = (cache_hits / audit_count) * 100
                print(f"  - Cache hit rate: {hit_rate:.1f}%")

                # Show cost summary
                from sqlalchemy import func
                total_cost = db.session.query(
                    func.sum(SearchAuditLog.estimated_cost_usd)
                ).scalar()
                if total_cost:
                    print(f"  - Total API cost: ${float(total_cost):.4f}")

        except Exception as e:
            print(f"  (Tables may not exist yet: {e})")


def main():
    parser = argparse.ArgumentParser(description='v9.0 Search Tables Migration')
    parser.add_argument('--reset', action='store_true',
                        help='Drop and recreate search tables (WARNING: deletes cached data)')
    parser.add_argument('--stats', action='store_true',
                        help='Show table statistics only')

    args = parser.parse_args()

    # Create Flask app
    app = create_app()

    print("=" * 60)
    print("v9.0 Search Persistence & Vector Caching Migration")
    print("=" * 60)

    if args.stats:
        show_table_stats(app)
    else:
        create_search_tables(app, reset=args.reset)
        show_table_stats(app)

    print("\nDone!")


if __name__ == "__main__":
    main()
