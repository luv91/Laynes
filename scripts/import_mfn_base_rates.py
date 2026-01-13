#!/usr/bin/env python3
"""
MFN Base Rates CSV Import Script

Imports MFN (Column 1 General) duty rates from USITC HTS CSV into the database.
Idempotent: safe to rerun (uses UPSERT).

Usage:
    pipenv run python scripts/import_mfn_base_rates.py

    # Dry run (no DB changes)
    pipenv run python scripts/import_mfn_base_rates.py --dry-run

    # Verify only (check existing data)
    pipenv run python scripts/import_mfn_base_rates.py --verify-only
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import HtsBaseRate

# ============================================
# CONFIGURATION
# ============================================

CSV_PATH = Path(__file__).parent.parent / "data" / "mfn_base_rates_8digit.csv"
BATCH_SIZE = 1000
DEFAULT_EFFECTIVE_DATE = date(2025, 1, 1)  # HTS 2025 edition


# ============================================
# IMPORT FUNCTION
# ============================================

def import_mfn_base_rates(dry_run: bool = False) -> dict:
    """
    Import MFN base rates from CSV into database.

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
        "skipped_no_rate": 0,
        "skipped_complex_rate": 0,
        "rate_stats": {
            "free": 0,
            "ad_valorem": 0,
            "complex": 0,
        },
        "errors": [],
    }

    print(f"Reading CSV: {CSV_PATH}")
    print("=" * 60)

    if not CSV_PATH.exists():
        stats["errors"].append(f"CSV not found: {CSV_PATH}")
        return stats

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Total rows to process: {len(rows)}")

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No database changes will be made")

    for i, row in enumerate(rows):
        stats["total_processed"] += 1

        # Extract fields
        hts_8digit = row.get("hts_8digit", "").strip()
        description = row.get("description", "").strip()[:512]  # Truncate to field limit
        general_rate_raw = row.get("general_rate_raw", "").strip()
        general_ad_valorem = row.get("general_ad_valorem_rate", "").strip()

        # Skip if missing HTS code
        if not hts_8digit:
            stats["errors"].append(f"Row {i+2}: Missing HTS code")
            continue

        # Parse rate - prefer the parsed ad_valorem, fall back to raw
        column1_rate = None

        if general_ad_valorem:
            try:
                column1_rate = Decimal(general_ad_valorem)
                if general_rate_raw.lower() == "free":
                    stats["rate_stats"]["free"] += 1
                else:
                    stats["rate_stats"]["ad_valorem"] += 1
            except (InvalidOperation, ValueError):
                pass

        # If no parsed rate available and raw exists, it's a complex rate
        if column1_rate is None:
            if general_rate_raw:
                stats["skipped_complex_rate"] += 1
                stats["rate_stats"]["complex"] += 1
            else:
                stats["skipped_no_rate"] += 1
            continue

        # Format HTS code with dots for storage (e.g., 76151071 -> 7615.10.71)
        hts_formatted = f"{hts_8digit[:4]}.{hts_8digit[4:6]}.{hts_8digit[6:8]}"

        if not dry_run:
            # Check if exists (by hts_code and effective_date)
            existing = HtsBaseRate.query.filter_by(
                hts_code=hts_formatted,
                effective_date=DEFAULT_EFFECTIVE_DATE
            ).first()

            if existing:
                # Update existing record
                existing.column1_rate = column1_rate
                existing.description = description
                stats["updated"] += 1
            else:
                # Insert new record
                base_rate = HtsBaseRate(
                    hts_code=hts_formatted,
                    column1_rate=column1_rate,
                    description=description,
                    effective_date=DEFAULT_EFFECTIVE_DATE,
                )
                db.session.add(base_rate)
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
    print(f"  Skipped (no rate): {stats['skipped_no_rate']}")
    print(f"  Skipped (complex rate): {stats['skipped_complex_rate']}")

    print("\nRate breakdown:")
    print(f"  Free (0%): {stats['rate_stats']['free']}")
    print(f"  Ad valorem (%): {stats['rate_stats']['ad_valorem']}")
    print(f"  Complex (specific/compound): {stats['rate_stats']['complex']}")

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
    total = HtsBaseRate.query.count()
    print(f"\nTotal rows in hts_base_rates: {total}")

    # Rate distribution
    from sqlalchemy import func

    # Count free rates
    free_count = HtsBaseRate.query.filter(HtsBaseRate.column1_rate == 0).count()
    print(f"\nFree (0%) rates: {free_count}")

    # Count non-zero rates
    duty_count = HtsBaseRate.query.filter(HtsBaseRate.column1_rate > 0).count()
    print(f"Dutiable rates (> 0%): {duty_count}")

    # Sample check - specific HTS codes we care about
    print("\nKey HTS codes for Phoebe's test cases:")
    test_codes = [
        ("7615.10.71", "3.1%"),   # Aluminum cookware
        ("8302.41.60", "3.9%"),   # Base metal door fittings
        ("8544.42.90", "2.6%"),   # Insulated conductors
        ("7317.00.55", None),     # Steel nails (complex rate)
        ("8504.90.96", None),     # Transformer parts
    ]

    for hts, expected in test_codes:
        rate = HtsBaseRate.query.filter_by(hts_code=hts).first()
        if rate:
            pct = f"{float(rate.column1_rate) * 100:.2f}%" if rate.column1_rate else "N/A"
            status = "✅" if expected and pct == expected else "ℹ️"
            print(f"  {hts}: {pct} {status}")
        else:
            print(f"  {hts}: NOT FOUND")

    # Sample rows
    print("\nSample rows:")
    samples = HtsBaseRate.query.order_by(HtsBaseRate.hts_code).limit(5).all()
    for s in samples:
        pct = f"{float(s.column1_rate) * 100:.2f}%" if s.column1_rate else "N/A"
        print(f"  {s.hts_code}: {pct}")


def main():
    parser = argparse.ArgumentParser(description="Import MFN base rates CSV to database")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually write to database")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing data")
    parser.add_argument("--csv", type=str, help="Override CSV path")

    args = parser.parse_args()

    global CSV_PATH
    if args.csv:
        CSV_PATH = Path(args.csv)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        if args.verify_only:
            verify_import()
        else:
            stats = import_mfn_base_rates(dry_run=args.dry_run)
            print_results(stats)

            if not args.dry_run:
                verify_import()


if __name__ == "__main__":
    main()
