#!/usr/bin/env python3
"""
v21.0: Migrate Annex II Exclusions to V2 Table

Migrates existing 47 rows from ieepa_annex_ii_exclusions to the new
ieepa_reciprocal_product_exclusions table with added prefix_len column.

Also adds new categories for:
- AGRICULTURAL: Agricultural products (Nov 2025)
- Additional semiconductor/pharmaceutical codes

Usage:
    python scripts/migrate_annex_ii_to_v2.py             # Migrate exclusions
    python scripts/migrate_annex_ii_to_v2.py --dry-run   # Preview only
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import (
    IeepaAnnexIIExclusion,
    IeepaReciprocalProductExclusions
)


# =============================================================================
# Category Mapping
# =============================================================================

CATEGORY_MAP = {
    'pharmaceutical': 'PHARMACEUTICAL',
    'chemical': 'CHEMICAL',
    'semiconductor': 'SEMICONDUCTOR',
    'energy': 'ENERGY',
    'lumber': 'LUMBER',
    'critical_mineral': 'CRITICAL_MINERAL',
}


# =============================================================================
# Migration Functions
# =============================================================================

def migrate_existing_exclusions(dry_run: bool = False) -> dict:
    """
    Migrate rows from old table to new V2 table.

    Adds:
    - prefix_len: Calculated from hts_code length
    - Normalized category names
    - Default ch99_code: 9903.01.32
    - dataset_tag: 'v21.0_migration'

    Returns:
        Stats dict with counts
    """
    stats = {
        'source_count': 0,
        'migrated': 0,
        'skipped_duplicate': 0,
        'target_before': 0,
    }

    # Count source rows
    stats['source_count'] = IeepaAnnexIIExclusion.query.count()
    stats['target_before'] = IeepaReciprocalProductExclusions.query.count()

    # Get all source rows
    source_rows = IeepaAnnexIIExclusion.query.all()

    for row in source_rows:
        # Calculate prefix length
        prefix_len = len(row.hts_code)

        # Map category
        category = CATEGORY_MAP.get(row.category, row.category.upper() if row.category else 'UNKNOWN')

        # Check if already exists
        existing = IeepaReciprocalProductExclusions.query.filter_by(
            hts_prefix=row.hts_code,
            prefix_len=prefix_len,
            category=category
        ).first()

        if existing:
            stats['skipped_duplicate'] += 1
            continue

        # Create new row
        if not dry_run:
            new_row = IeepaReciprocalProductExclusions(
                hts_prefix=row.hts_code,
                prefix_len=prefix_len,
                description=row.description,
                category=category,
                ch99_code='9903.01.32',  # Standard Annex II exemption code
                effective_start=row.effective_date or date(2025, 4, 5),
                effective_end=row.expiration_date or date(9999, 12, 31),
                legal_authority='EO 14257, Annex II',
                source_doc_id=None,
                dataset_tag='v21.0_migration',
            )
            db.session.add(new_row)

        stats['migrated'] += 1

    if not dry_run:
        db.session.commit()

    return stats


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Migrate Annex II exclusions to V2 table'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying database'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA Annex II Migration to V2 Table")
    print("=" * 60)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        # Show source data summary
        print(f"\nSource table: ieepa_annex_ii_exclusions")
        source_count = IeepaAnnexIIExclusion.query.count()
        print(f"Source rows: {source_count}")

        print(f"\nTarget table: ieepa_reciprocal_product_exclusions")
        target_count = IeepaReciprocalProductExclusions.query.count()
        print(f"Target rows (before): {target_count}")

        # Show category breakdown
        from sqlalchemy import func
        cats = db.session.query(
            IeepaAnnexIIExclusion.category,
            func.count(IeepaAnnexIIExclusion.id)
        ).group_by(IeepaAnnexIIExclusion.category).all()

        print("\nSource categories:")
        for cat, cnt in cats:
            mapped = CATEGORY_MAP.get(cat, cat.upper() if cat else 'UNKNOWN')
            print(f"  {cat} -> {mapped}: {cnt}")

        # Perform migration
        if args.dry_run:
            print("\n[DRY RUN] Previewing changes (no database modifications)")
        else:
            print("\nMigrating to V2 table...")

        stats = migrate_existing_exclusions(dry_run=args.dry_run)

        # Print results
        print("\n" + "=" * 60)
        print("Migration Results:")
        print("=" * 60)
        print(f"  Source count:      {stats['source_count']}")
        print(f"  Target (before):   {stats['target_before']}")
        print(f"  Migrated:          {stats['migrated']}")
        print(f"  Skipped (dup):     {stats['skipped_duplicate']}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made to database")
        else:
            final_count = IeepaReciprocalProductExclusions.query.count()
            print(f"\n  Target (after):    {final_count}")
            print("\n[SUCCESS] Migration complete")


if __name__ == "__main__":
    main()
