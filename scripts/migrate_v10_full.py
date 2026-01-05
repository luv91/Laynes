"""
Migration script for v10.0 Legal-Grade Tariff Data System.

Creates all tables for Phases 1-5:
- needs_review_queue (Phase 1)
- documents (Phase 2)
- document_chunks (Phase 2)
- verified_assertions (Phase 4)

Usage:
    cd lanes
    pipenv run python scripts/migrate_v10_full.py

To reset all v10 tables:
    pipenv run python scripts/migrate_v10_full.py --reset
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
from app.web.db.models.tariff_tables import NeedsReviewQueue
from app.web.db.models.document import Document, DocumentChunk, VerifiedAssertion


def create_v10_tables(app, reset=False):
    """Create all v10.0 tables."""
    with app.app_context():
        if reset:
            print("Dropping existing v10 tables...")
            # Drop in correct order (children first)
            VerifiedAssertion.__table__.drop(db.engine, checkfirst=True)
            DocumentChunk.__table__.drop(db.engine, checkfirst=True)
            Document.__table__.drop(db.engine, checkfirst=True)
            NeedsReviewQueue.__table__.drop(db.engine, checkfirst=True)
            print("Tables dropped.")

        print("\nCreating v10.0 tables...")

        # Phase 1: Review Queue
        print("  - needs_review_queue (Phase 1)")
        NeedsReviewQueue.__table__.create(db.engine, checkfirst=True)

        # Phase 2: Document Store
        print("  - documents (Phase 2)")
        Document.__table__.create(db.engine, checkfirst=True)
        print("  - document_chunks (Phase 2)")
        DocumentChunk.__table__.create(db.engine, checkfirst=True)

        # Phase 4: Verified Assertions
        print("  - verified_assertions (Phase 4)")
        VerifiedAssertion.__table__.create(db.engine, checkfirst=True)

        print("\nAll tables created successfully!")


def show_stats(app):
    """Show current table statistics."""
    with app.app_context():
        print("\n" + "=" * 50)
        print("v10.0 Legal-Grade System Statistics")
        print("=" * 50)

        try:
            # Review Queue
            pending = db.session.query(NeedsReviewQueue).filter(
                NeedsReviewQueue.status == 'pending'
            ).count()
            print(f"\nReview Queue:")
            print(f"  - Pending reviews: {pending}")

            # Documents
            docs = db.session.query(Document).count()
            tier_a = db.session.query(Document).filter(Document.tier == 'A').count()
            print(f"\nDocument Store:")
            print(f"  - Total documents: {docs}")
            print(f"  - Tier A (official): {tier_a}")

            # Chunks
            chunks = db.session.query(DocumentChunk).count()
            print(f"  - Total chunks: {chunks}")

            # Verified Assertions
            assertions = db.session.query(VerifiedAssertion).count()
            current = db.session.query(VerifiedAssertion).filter(
                VerifiedAssertion.effective_end.is_(None)
            ).count()
            print(f"\nVerified Assertions:")
            print(f"  - Total assertions: {assertions}")
            print(f"  - Current (active): {current}")

        except Exception as e:
            print(f"  (Tables may not exist yet: {e})")


def main():
    parser = argparse.ArgumentParser(description='v10.0 Full Migration')
    parser.add_argument('--reset', action='store_true',
                        help='Drop and recreate all v10 tables')
    parser.add_argument('--stats', action='store_true',
                        help='Show statistics only')

    args = parser.parse_args()

    # Create Flask app
    app = create_app()

    print("=" * 60)
    print("v10.0 Legal-Grade Tariff Data System Migration")
    print("=" * 60)
    print("\nPhases included:")
    print("  Phase 1: Stop Caching Gemini Conclusions")
    print("  Phase 2: Document Store + Chunking")
    print("  Phase 3: Reader LLM + Validator LLM (code only)")
    print("  Phase 4: Verified Assertions Store")
    print("  Phase 5: Discovery Mode (integration)")

    if args.stats:
        show_stats(app)
    else:
        create_v10_tables(app, reset=args.reset)
        show_stats(app)

    print("\nDone!")


if __name__ == "__main__":
    main()
