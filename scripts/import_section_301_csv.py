#!/usr/bin/env python3
"""
Section 301 CSV Import Script

Imports validated Section 301 HTS codes into the database.
Idempotent: safe to rerun (uses UPSERT).

Usage:
    pipenv run python scripts/import_section_301_csv.py

    # With validation first
    pipenv run python scripts/import_section_301_csv.py --validate

    # Dry run (no DB changes)
    pipenv run python scripts/import_section_301_csv.py --dry-run
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import Section301Inclusion

# ============================================
# CONFIGURATION
# ============================================

CSV_PATH = Path(__file__).parent.parent / "data" / "section_301_hts_codes.csv"
BATCH_SIZE = 1000


# ============================================
# IMPORT FUNCTION
# ============================================

def import_section_301_csv(dry_run: bool = False) -> dict:
    """
    Import Section 301 HTS codes from CSV into database.

    Uses UPSERT (INSERT ON CONFLICT DO UPDATE) for idempotent imports.

    Args:
        dry_run: If True, don't actually commit to database

    Returns:
        dict with import statistics
    """
    stats = {
        "total_processed": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "by_list": defaultdict(int),
        "errors": [],
    }

    print(f"Reading CSV: {CSV_PATH}")
    print("=" * 60)

    if not CSV_PATH.exists():
        stats["errors"].append(f"CSV not found: {CSV_PATH}")
        return stats

    with open(CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Total rows to process: {len(rows)}")

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No database changes will be made")

    batch = []
    for i, row in enumerate(rows):
        stats["total_processed"] += 1

        # Extract and normalize fields
        hts_8digit = row.get("hts_8digit", "").strip()
        list_name = row.get("list_name", "").strip().lower()  # Normalize to lowercase
        chapter_99_code = row.get("chapter_99_code", "").strip()
        rate_str = row.get("rate", "").strip()
        effective_start = row.get("effective_start", "").strip()
        source_pdf = row.get("source_pdf", "").strip()

        # Skip if missing required fields
        if not hts_8digit or not list_name or not chapter_99_code:
            stats["skipped"] += 1
            continue

        # Parse rate
        try:
            duty_rate = Decimal(rate_str)
        except Exception:
            stats["errors"].append(f"Row {i+2}: Invalid rate: {rate_str}")
            stats["skipped"] += 1
            continue

        # Build source_doc with effective_start (as per plan)
        source_doc = source_pdf
        if effective_start:
            source_doc = f"{source_pdf} (effective {effective_start})"

        # Track by list
        stats["by_list"][list_name] += 1

        if not dry_run:
            # Check if exists
            existing = Section301Inclusion.query.filter_by(
                hts_8digit=hts_8digit,
                list_name=list_name
            ).first()

            if existing:
                # Update existing record
                existing.chapter_99_code = chapter_99_code
                existing.duty_rate = duty_rate
                existing.source_doc = source_doc
                stats["updated"] += 1
            else:
                # Insert new record
                inclusion = Section301Inclusion(
                    hts_8digit=hts_8digit,
                    list_name=list_name,
                    chapter_99_code=chapter_99_code,
                    duty_rate=duty_rate,
                    source_doc=source_doc,
                )
                db.session.add(inclusion)
                stats["inserted"] += 1

            # Commit in batches
            if (stats["inserted"] + stats["updated"]) % BATCH_SIZE == 0:
                db.session.commit()
                print(f"  Processed {stats['total_processed']}/{len(rows)} rows...")

    # Final commit
    if not dry_run:
        db.session.commit()
        print(f"\n✅ Database commit complete")

    return stats


def print_results(stats: dict):
    """Print import results."""
    print("\n" + "=" * 60)
    print("IMPORT RESULTS")
    print("=" * 60)

    print(f"\nTotal processed: {stats['total_processed']}")
    print(f"  Inserted: {stats['inserted']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Skipped: {stats['skipped']}")

    print("\nBy list:")
    for list_name in sorted(stats["by_list"].keys()):
        count = stats["by_list"][list_name]
        print(f"  {list_name}: {count}")

    if stats["errors"]:
        print(f"\n❌ Errors ({len(stats['errors'])}):")
        for e in stats["errors"][:10]:
            print(f"  - {e}")


def verify_import():
    """Verify the import by querying the database."""
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # Count total
    total = Section301Inclusion.query.count()
    print(f"\nTotal rows in section_301_inclusions: {total}")

    # Count by list
    from sqlalchemy import func
    results = db.session.query(
        Section301Inclusion.list_name,
        func.count(Section301Inclusion.id)
    ).group_by(Section301Inclusion.list_name).all()

    print("\nBy list:")
    for list_name, count in sorted(results):
        print(f"  {list_name}: {count}")

    # Sample check
    print("\nSample rows:")
    samples = Section301Inclusion.query.limit(3).all()
    for s in samples:
        print(f"  {s.hts_8digit} | {s.list_name} | {s.chapter_99_code} | {s.duty_rate}")

    # Check expected counts
    expected = {"list_1": 1082, "list_2": 285, "list_3": 5807, "list_4a": 3247}
    print("\nExpected vs Actual:")
    all_match = True
    for list_name, expected_count in expected.items():
        actual = next((c for l, c in results if l == list_name), 0)
        status = "✅" if actual == expected_count else "❌"
        print(f"  {list_name}: expected {expected_count}, got {actual} {status}")
        if actual != expected_count:
            all_match = False

    if all_match:
        print("\n✅ All counts match expected values!")
    else:
        print("\n⚠️  Some counts don't match - please investigate")


def main():
    parser = argparse.ArgumentParser(description="Import Section 301 CSV to database")
    parser.add_argument("--validate", action="store_true", help="Run validation before import")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually write to database")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing data")

    args = parser.parse_args()

    # Run validation if requested
    if args.validate:
        print("Running validation first...\n")
        from validate_301_csv import validate_csv, print_results as print_validation_results
        passed, errors, warnings, stats = validate_csv()
        print_validation_results(passed, errors, warnings, stats)
        if not passed:
            print("\n❌ Validation failed. Fix errors before importing.")
            sys.exit(1)
        print("\n" + "-" * 60 + "\n")

    # Create Flask app context
    app = create_app()

    with app.app_context():
        if args.verify_only:
            verify_import()
        else:
            stats = import_section_301_csv(dry_run=args.dry_run)
            print_results(stats)

            if not args.dry_run:
                verify_import()


if __name__ == "__main__":
    main()
