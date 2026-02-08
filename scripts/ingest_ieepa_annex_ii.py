#!/usr/bin/env python3
"""
v21.0: IEEPA Annex II Ingestion Script

Ingests HTS exclusions from EO 14257 Annex II into the ieepa_annex_ii_exclusions table.

Features:
- Parses HTS codes from CSV source file
- Validates prefix lengths (4, 6, 8, 10 digits only)
- Normalizes to digits-only format (removes dots)
- Upserts into existing table (add/update, never delete)
- No-shrink guard: fails if new dataset has >10% fewer rows than existing
- Logs detailed ingestion stats

Usage:
    python scripts/ingest_ieepa_annex_ii.py                    # Ingest from CSV
    python scripts/ingest_ieepa_annex_ii.py --dry-run          # Preview without changes
    python scripts/ingest_ieepa_annex_ii.py --force-shrink     # Allow >10% row reduction
"""

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Flask app context needed for database access
from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import IeepaAnnexIIExclusion


# ==============================================================================
# Configuration
# ==============================================================================

SHRINK_THRESHOLD = 0.10  # 10% - fail if new set has >10% fewer rows

VALID_PREFIX_LENGTHS = {4, 6, 8, 10}

DEFAULT_CSV_PATH = project_root / "data" / "annex_ii_exemptions.csv"


# ==============================================================================
# Validation Functions
# ==============================================================================

def normalize_hts_code(hts_code: str) -> str:
    """
    Normalize HTS code to digits-only format.

    Examples:
        "2709.00" -> "270900"
        "2711.11" -> "271111"
        "8541" -> "8541"
    """
    return hts_code.replace(".", "").strip()


def validate_prefix_length(hts_code: str) -> bool:
    """
    Validate that HTS code has a valid prefix length (4, 6, 8, or 10 digits).
    """
    normalized = normalize_hts_code(hts_code)
    return len(normalized) in VALID_PREFIX_LENGTHS and normalized.isdigit()


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    if not date_str:
        return date.today()
    return date.fromisoformat(date_str.strip())


# ==============================================================================
# CSV Parsing
# ==============================================================================

def parse_csv(csv_path: Path) -> list:
    """
    Parse Annex II exclusions from CSV file.

    Expected columns:
        hts_prefix, description, exemption_code, category, source, effective_date

    Returns:
        List of dicts with normalized data ready for insertion
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    rows = []
    validation_errors = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader, start=2):  # Start at 2 to account for header
            hts_prefix = row.get('hts_prefix', '').strip()

            if not hts_prefix:
                continue  # Skip empty rows

            # Validate prefix length
            if not validate_prefix_length(hts_prefix):
                validation_errors.append(
                    f"Line {i}: Invalid HTS prefix '{hts_prefix}' - must be 4/6/8/10 digits"
                )
                continue

            # Normalize and create record
            normalized_code = normalize_hts_code(hts_prefix)

            rows.append({
                'hts_code': normalized_code,
                'description': row.get('description', '').strip(),
                'category': row.get('category', '').strip(),
                'source_doc': row.get('source', '').strip(),
                'effective_date': parse_date(row.get('effective_date', '')),
            })

    if validation_errors:
        print("Validation warnings:")
        for err in validation_errors:
            print(f"  - {err}")

    return rows


# ==============================================================================
# No-Shrink Guard
# ==============================================================================

def check_shrink_safety(existing_count: int, new_count: int, force: bool = False) -> None:
    """
    Verify that the new dataset doesn't significantly reduce row count.

    Prevents accidental data loss by failing if:
    - New dataset has >10% fewer rows than existing
    - Use --force-shrink to override
    """
    if existing_count == 0:
        return  # No existing data, no shrink possible

    if new_count >= existing_count:
        return  # Growing or stable, always OK

    shrink_ratio = (existing_count - new_count) / existing_count

    if shrink_ratio > SHRINK_THRESHOLD:
        if force:
            print(f"WARNING: Force-shrink enabled. Allowing {shrink_ratio:.1%} row reduction.")
        else:
            raise ValueError(
                f"ABORT: New dataset has {new_count} rows vs existing {existing_count} "
                f"(shrink ratio {shrink_ratio:.1%} > threshold {SHRINK_THRESHOLD:.0%}). "
                f"Manual review required - use --force-shrink to override."
            )


# ==============================================================================
# Database Operations
# ==============================================================================

def upsert_exclusions(parsed_rows: list, dry_run: bool = False) -> dict:
    """
    Upsert Annex II exclusions into database.

    - Add new rows
    - Update existing rows if data changed
    - Never delete existing rows

    Returns:
        Stats dict with counts
    """
    stats = {
        'total_parsed': len(parsed_rows),
        'inserted': 0,
        'updated': 0,
        'unchanged': 0,
        'existing_before': 0,
    }

    # Count existing rows
    stats['existing_before'] = IeepaAnnexIIExclusion.query.count()

    for row in parsed_rows:
        # Check for existing record by hts_code + category
        existing = IeepaAnnexIIExclusion.query.filter_by(
            hts_code=row['hts_code'],
            category=row['category']
        ).first()

        if existing:
            # Check if update needed
            needs_update = (
                existing.description != row['description'] or
                existing.source_doc != row['source_doc'] or
                existing.effective_date != row['effective_date']
            )

            if needs_update:
                if not dry_run:
                    existing.description = row['description']
                    existing.source_doc = row['source_doc']
                    existing.effective_date = row['effective_date']
                stats['updated'] += 1
            else:
                stats['unchanged'] += 1
        else:
            # Insert new record
            if not dry_run:
                new_record = IeepaAnnexIIExclusion(
                    hts_code=row['hts_code'],
                    description=row['description'],
                    category=row['category'],
                    source_doc=row['source_doc'],
                    effective_date=row['effective_date'],
                    expiration_date=None  # Active exclusions have no expiration
                )
                db.session.add(new_record)
            stats['inserted'] += 1

    if not dry_run:
        db.session.commit()

    return stats


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Ingest IEEPA Annex II exclusions into database'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f'Path to CSV file (default: {DEFAULT_CSV_PATH})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying database'
    )
    parser.add_argument(
        '--force-shrink',
        action='store_true',
        help='Allow >10%% row reduction (override safety check)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA Annex II Ingestion Script v21.0")
    print("=" * 60)

    # Parse CSV
    print(f"\nParsing CSV: {args.csv}")
    parsed_rows = parse_csv(args.csv)
    print(f"Parsed {len(parsed_rows)} valid rows")

    # Print category breakdown
    categories = {}
    for row in parsed_rows:
        cat = row['category'] or 'unknown'
        categories[cat] = categories.get(cat, 0) + 1

    print("\nCategory breakdown:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")

    # Create Flask app context for database access
    app = create_app()

    with app.app_context():
        # Get existing count
        existing_count = IeepaAnnexIIExclusion.query.count()
        print(f"\nExisting rows in database: {existing_count}")

        # Check shrink safety
        check_shrink_safety(existing_count, len(parsed_rows), args.force_shrink)

        # Perform upsert
        if args.dry_run:
            print("\n[DRY RUN] Previewing changes (no database modifications)")
        else:
            print("\nUpserting to database...")

        stats = upsert_exclusions(parsed_rows, dry_run=args.dry_run)

        # Print results
        print("\n" + "=" * 60)
        print("Ingestion Results:")
        print("=" * 60)
        print(f"  Total parsed:     {stats['total_parsed']}")
        print(f"  Existing before:  {stats['existing_before']}")
        print(f"  Inserted:         {stats['inserted']}")
        print(f"  Updated:          {stats['updated']}")
        print(f"  Unchanged:        {stats['unchanged']}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made to database")
        else:
            final_count = IeepaAnnexIIExclusion.query.count()
            print(f"\n  Final row count:  {final_count}")
            print("\n[SUCCESS] Ingestion complete")


if __name__ == "__main__":
    main()
