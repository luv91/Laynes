#!/usr/bin/env python3
"""
Import 2024 Four-Year Review rates into Section301Rate temporal table.

This is Phase 1 Quick Fix:
1. Creates the section_301_rates table if needed
2. Migrates existing List 1-4A data from section_301_inclusions
3. Imports new 2024 review rates from CSV
4. Sets effective_end dates on superseded rates

Usage:
    pipenv run python scripts/import_2024_review_rates.py

    # Dry run (no DB changes)
    pipenv run python scripts/import_2024_review_rates.py --dry-run

    # Skip legacy migration (only import new rates)
    pipenv run python scripts/import_2024_review_rates.py --skip-legacy
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import Section301Inclusion, Section301Rate


# List effective dates (from original Federal Register notices)
LIST_EFFECTIVE_DATES = {
    "list_1": date(2018, 7, 6),
    "list_2": date(2018, 8, 23),
    "list_3": date(2018, 9, 24),
    "list_4a": date(2020, 2, 14),  # After exclusions restored
    "list_4b": date(2019, 9, 1),   # Original (fully excluded later)
}

# Product group to sector mapping
SECTOR_MAP = {
    "Facemasks": "medical",
    "Electric Vehicles": "ev",
    "Lithium-ion Electrical Vehicle Batteries": "battery",
    "Lithium-ion Non-electrical Vehicle Batteries": "battery",
    "Battery Parts (Non-lithium-ion Batteries)": "battery",
    "Medical Gloves": "medical",
    "Syringes and Needles": "medical",
    "Semiconductors": "semiconductor",
    "Solar Cells (whether or not assembled into modules)": "solar",
    "Steel and Aluminum Products": "metals",
    "Other Critical Minerals": "critical_minerals",
    "Natural Graphite": "critical_minerals",
    "Permanent Magnets": "critical_minerals",
}


def create_tables():
    """Create section_301_rates table if it doesn't exist."""
    # SQLAlchemy will create missing tables
    db.create_all()
    print("Ensured section_301_rates table exists")


def migrate_legacy_data(dry_run: bool = False) -> dict:
    """
    Migrate existing section_301_inclusions to section_301_rates.

    All legacy rows become active rates with their original effective dates.
    """
    stats = {"migrated": 0, "skipped": 0, "errors": 0}

    print("\nMigrating legacy Section 301 inclusions...")

    inclusions = Section301Inclusion.query.all()
    print(f"Found {len(inclusions)} existing inclusions to migrate")

    for inc in inclusions:
        # Check if already migrated
        existing = Section301Rate.query.filter_by(
            hts_8digit=inc.hts_8digit,
            chapter_99_code=inc.chapter_99_code,
        ).first()

        if existing:
            stats["skipped"] += 1
            continue

        # Determine effective date from list
        effective_date = LIST_EFFECTIVE_DATES.get(inc.list_name, date(2018, 7, 6))

        # Create new rate record
        # Determine role: exclusion codes (9903.88.69, 9903.88.70) have role='exclude'
        role = 'exclude' if inc.chapter_99_code in ('9903.88.69', '9903.88.70') else 'impose'

        if not dry_run:
            rate = Section301Rate(
                hts_8digit=inc.hts_8digit,
                chapter_99_code=inc.chapter_99_code,
                duty_rate=inc.duty_rate,
                effective_start=effective_date,
                effective_end=None,  # Currently active
                list_name=inc.list_name,
                source_doc=inc.source_doc,
                created_by="legacy_migration",
                role=role,
            )
            db.session.add(rate)

        stats["migrated"] += 1

    if not dry_run:
        db.session.commit()

    print(f"  Migrated: {stats['migrated']}")
    print(f"  Skipped (already exists): {stats['skipped']}")

    return stats


def import_2024_review(csv_path: Path, dry_run: bool = False) -> dict:
    """
    Import 2024 Four-Year Review rates from CSV.

    For each new rate:
    1. Check if there's an existing rate for the same HTS
    2. If yes, set effective_end on the old rate
    3. Insert new rate with supersedes_id pointing to old rate
    """
    stats = {
        "inserted": 0,
        "superseded": 0,
        "skipped_duplicate": 0,
        "errors": 0,
        "by_product_group": defaultdict(int),
    }

    print(f"\nImporting 2024 review rates from {csv_path}...")

    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}")
        stats["errors"] += 1
        return stats

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Found {len(rows)} rows to import")

    for row in rows:
        hts_8digit = row['hts_8digit']
        hts_10digit = row['hts_code'] if len(row['hts_code'].replace(".", "")) > 8 else None
        chapter_99_code = row['chapter_99_code']
        rate = Decimal(row['rate'])
        effective_date = date.fromisoformat(row['effective_date'])
        product_group = row['product_group']
        description = row.get('description', '')
        source_doc = row.get('source_doc', '2024-21217')

        # Check for exact duplicate
        existing_exact = Section301Rate.query.filter_by(
            hts_8digit=hts_8digit,
            chapter_99_code=chapter_99_code,
            effective_start=effective_date,
        ).first()

        if existing_exact:
            stats["skipped_duplicate"] += 1
            continue

        # Find any existing rate for this HTS that this supersedes
        # (rate effective before this one, still active)
        supersedes_rate = Section301Rate.query.filter(
            Section301Rate.hts_8digit == hts_8digit,
            Section301Rate.effective_start < effective_date,
            Section301Rate.effective_end.is_(None),
        ).order_by(Section301Rate.effective_start.desc()).first()

        # Determine role: exclusion codes have role='exclude'
        role = 'exclude' if chapter_99_code in ('9903.88.69', '9903.88.70') else 'impose'

        if not dry_run:
            # Create new rate
            new_rate = Section301Rate(
                hts_8digit=hts_8digit,
                hts_10digit=hts_10digit,
                chapter_99_code=chapter_99_code,
                duty_rate=rate,
                effective_start=effective_date,
                effective_end=None,  # Currently active
                list_name="four_year_review_2024",
                sector=SECTOR_MAP.get(product_group, "other"),
                product_group=product_group,
                description=description[:500] if description else None,
                source_doc=source_doc,
                created_by="2024_review_import",
                role=role,
            )

            # Set supersession if applicable
            if supersedes_rate:
                new_rate.supersedes_id = supersedes_rate.id

                # Set effective_end on superseded rate
                supersedes_rate.effective_end = effective_date
                supersedes_rate.superseded_by_id = None  # Will update after insert

                stats["superseded"] += 1

            db.session.add(new_rate)
            db.session.flush()  # Get ID for superseded_by_id update

            if supersedes_rate:
                supersedes_rate.superseded_by_id = new_rate.id

        stats["inserted"] += 1
        stats["by_product_group"][product_group] += 1

    if not dry_run:
        db.session.commit()
        print("Database commit complete")

    print(f"\n  Inserted: {stats['inserted']}")
    print(f"  Superseded old rates: {stats['superseded']}")
    print(f"  Skipped duplicates: {stats['skipped_duplicate']}")

    print("\n  By product group:")
    for pg, count in sorted(stats["by_product_group"].items()):
        print(f"    {pg}: {count}")

    return stats


def verify_import():
    """Verify the import by checking key HTS codes."""
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # Total counts
    total_rates = Section301Rate.query.count()
    active_rates = Section301Rate.query.filter(Section301Rate.effective_end.is_(None)).count()
    superseded_rates = Section301Rate.query.filter(Section301Rate.effective_end.isnot(None)).count()

    print(f"\nTotal rates in section_301_rates: {total_rates}")
    print(f"  Active (effective_end NULL): {active_rates}")
    print(f"  Superseded (has effective_end): {superseded_rates}")

    # Check key HTS codes
    print("\nKey HTS codes for facemasks:")
    test_codes = [
        ("63079098", "Facemasks - should have 50% as of today"),
    ]

    today = date.today()

    for hts_8, desc in test_codes:
        rates = Section301Rate.query.filter_by(hts_8digit=hts_8).order_by(Section301Rate.effective_start).all()

        print(f"\n  HTS {hts_8} ({desc}):")
        for r in rates:
            active_marker = "✓ ACTIVE" if r.is_active() else ""
            end = r.effective_end.isoformat() if r.effective_end else "NULL"
            print(f"    {r.chapter_99_code} @ {float(r.duty_rate)*100:.1f}% | {r.effective_start} - {end} {active_marker}")

        # Get rate as of today
        current = Section301Rate.get_rate_as_of(hts_8, today)
        if current:
            print(f"    => As of {today}: {current.chapter_99_code} @ {float(current.duty_rate)*100:.1f}%")
        else:
            print(f"    => As of {today}: NO RATE FOUND")

    # Check date-based queries
    print("\nDate-based verification (HTS 63079098):")
    dates_to_check = [
        date(2020, 3, 1),   # Should be list_4a @ 7.5%
        date(2024, 10, 1),  # Should be 9903.91.01 @ 25%
        date(2025, 6, 1),   # Should be 9903.91.01 @ 25% (or 9903.91.04 for disposable)
        date(2026, 2, 1),   # Should be 9903.91.07 @ 50%
    ]

    for check_date in dates_to_check:
        rate = Section301Rate.get_rate_as_of("63079098", check_date)
        if rate:
            print(f"  {check_date}: {rate.chapter_99_code} @ {float(rate.duty_rate)*100:.1f}%")
        else:
            print(f"  {check_date}: NO RATE")


def main():
    parser = argparse.ArgumentParser(description="Import 2024 Four-Year Review rates")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to database")
    parser.add_argument("--skip-legacy", action="store_true", help="Skip legacy data migration")
    parser.add_argument("--csv", type=str, help="Override CSV path")

    args = parser.parse_args()

    # Default CSV path
    csv_path = Path(args.csv) if args.csv else Path(__file__).parent.parent / "data" / "section_301_2024_review.csv"

    # Create Flask app context
    app = create_app()

    with app.app_context():
        if args.dry_run:
            print("=" * 60)
            print("DRY RUN MODE - No database changes will be made")
            print("=" * 60)

        # Step 1: Ensure table exists
        create_tables()

        # Step 2: Migrate legacy data (if not skipping)
        if not args.skip_legacy:
            migrate_legacy_data(dry_run=args.dry_run)

        # Step 3: Import 2024 review
        import_2024_review(csv_path, dry_run=args.dry_run)

        # Step 4: Verify
        if not args.dry_run:
            verify_import()


if __name__ == "__main__":
    main()
