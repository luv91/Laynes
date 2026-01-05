"""
Migration script for v10.0 NeedsReviewQueue table.

This is Phase 1 of the Legal-Grade Tariff Data System:
- Stop caching Gemini conclusions as truth
- Queue all LLM responses for review
- Only return verified results as authoritative

Creates the following table:
- needs_review_queue: Queue for unverified LLM responses awaiting review

Usage:
    cd lanes
    pipenv run python scripts/migrate_v10_review_queue.py

To reset the review queue (delete all pending reviews):
    pipenv run python scripts/migrate_v10_review_queue.py --reset

v10.0 Update (Jan 2026):
- Phase 1: Stop Caching Gemini Conclusions
- All Gemini responses go to NeedsReviewQueue
- Cache only returns is_verified=True results
- Breaks the "cache LLM conclusion as truth" anti-pattern
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


def create_review_queue_table(app, reset=False):
    """Create v10.0 needs_review_queue table."""
    with app.app_context():
        if reset:
            print("Dropping existing needs_review_queue table...")
            NeedsReviewQueue.__table__.drop(db.engine, checkfirst=True)
            print("Table dropped.")

        print("Creating v10.0 needs_review_queue table...")
        NeedsReviewQueue.__table__.create(db.engine, checkfirst=True)
        print("Table created successfully!")


def show_queue_stats(app):
    """Show current queue statistics."""
    with app.app_context():
        try:
            total = db.session.query(NeedsReviewQueue).count()
            pending = db.session.query(NeedsReviewQueue).filter(
                NeedsReviewQueue.status == 'pending'
            ).count()
            validated = db.session.query(NeedsReviewQueue).filter(
                NeedsReviewQueue.status == 'validated'
            ).count()
            rejected = db.session.query(NeedsReviewQueue).filter(
                NeedsReviewQueue.status == 'rejected'
            ).count()
            needs_human = db.session.query(NeedsReviewQueue).filter(
                NeedsReviewQueue.status == 'needs_human'
            ).count()

            print("\nReview Queue Statistics:")
            print(f"  - Total entries: {total}")
            print(f"  - Pending review: {pending}")
            print(f"  - Validated: {validated}")
            print(f"  - Rejected: {rejected}")
            print(f"  - Needs human review: {needs_human}")

            if total > 0:
                validation_rate = (validated / total) * 100
                print(f"  - Validation rate: {validation_rate:.1f}%")

        except Exception as e:
            print(f"  (Table may not exist yet: {e})")


def main():
    parser = argparse.ArgumentParser(description='v10.0 Review Queue Migration')
    parser.add_argument('--reset', action='store_true',
                        help='Drop and recreate review queue table (WARNING: deletes queue data)')
    parser.add_argument('--stats', action='store_true',
                        help='Show queue statistics only')

    args = parser.parse_args()

    # Create Flask app
    app = create_app()

    print("=" * 60)
    print("v10.0 Phase 1: Stop Caching Gemini Conclusions")
    print("NeedsReviewQueue Table Migration")
    print("=" * 60)

    if args.stats:
        show_queue_stats(app)
    else:
        create_review_queue_table(app, reset=args.reset)
        show_queue_stats(app)

    print("\nDone!")
    print("\nNote: This is Phase 1 of the Legal-Grade Tariff Data System.")
    print("Next phases will add: Document Store, Reader LLM, Validator LLM, Write Gate")


if __name__ == "__main__":
    main()
