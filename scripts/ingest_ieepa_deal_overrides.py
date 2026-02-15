#!/usr/bin/env python3
"""
v21.0: IEEPA Reciprocal Deal Overrides Ingestion Script

Ingests country + product-specific rate overrides from bilateral deals.

Examples:
- India interim deal: 18% on certain goods
- Argentina coffee: Reduced rates
- Taiwan arrangements

Usage:
    python scripts/ingest_ieepa_deal_overrides.py             # Ingest overrides
    python scripts/ingest_ieepa_deal_overrides.py --dry-run   # Preview only
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from decimal import Decimal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import IeepaReciprocalDealOverrides


# =============================================================================
# Deal Overrides Data
# =============================================================================

# India interim deal - 18% on certain goods
INDIA_DEAL_OVERRIDES = [
    # Pharmaceuticals - reduced rate
    {
        'country_code': 'IN',
        'hts_prefix': '3004',
        'prefix_len': 4,
        'override_rate': Decimal('18.00'),
        'ch99_code': '9903.02.26',  # India (9903.02.34 is Lesotho)
        'deal_name': 'India Interim Deal',
        'effective_start': date(2025, 11, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'India Interim Agreement',
        'dataset_tag': 'v21.0_initial',
    },
    # Textiles - reduced rate
    {
        'country_code': 'IN',
        'hts_prefix': '5208',
        'prefix_len': 4,
        'override_rate': Decimal('18.00'),
        'ch99_code': '9903.02.26',
        'deal_name': 'India Interim Deal',
        'effective_start': date(2025, 11, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'India Interim Agreement',
        'dataset_tag': 'v21.0_initial',
    },
    # Apparel - reduced rate
    {
        'country_code': 'IN',
        'hts_prefix': '6110',
        'prefix_len': 4,
        'override_rate': Decimal('18.00'),
        'ch99_code': '9903.02.26',
        'deal_name': 'India Interim Deal',
        'effective_start': date(2025, 11, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'India Interim Agreement',
        'dataset_tag': 'v21.0_initial',
    },
]

# Argentina deal - reduced rates on agricultural products
ARGENTINA_DEAL_OVERRIDES = [
    # Coffee - reduced rate
    {
        'country_code': 'AR',
        'hts_prefix': '0901',
        'prefix_len': 4,
        'override_rate': Decimal('5.00'),
        'ch99_code': '9903.01.25',
        'deal_name': 'Argentina Agricultural Deal',
        'effective_start': date(2025, 10, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'Argentina Deal Announcement',
        'dataset_tag': 'v21.0_initial',
    },
    # Wine - reduced rate
    {
        'country_code': 'AR',
        'hts_prefix': '2204',
        'prefix_len': 4,
        'override_rate': Decimal('5.00'),
        'ch99_code': '9903.01.25',
        'deal_name': 'Argentina Agricultural Deal',
        'effective_start': date(2025, 10, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'Argentina Deal Announcement',
        'dataset_tag': 'v21.0_initial',
    },
    # Beef - reduced rate
    {
        'country_code': 'AR',
        'hts_prefix': '0201',
        'prefix_len': 4,
        'override_rate': Decimal('5.00'),
        'ch99_code': '9903.01.25',
        'deal_name': 'Argentina Agricultural Deal',
        'effective_start': date(2025, 10, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'Argentina Deal Announcement',
        'dataset_tag': 'v21.0_initial',
    },
]

# Taiwan deal - tech products
TAIWAN_DEAL_OVERRIDES = [
    # Semiconductors - keep exempt (Annex II)
    {
        'country_code': 'TW',
        'hts_prefix': '8542',
        'prefix_len': 4,
        'override_rate': Decimal('0'),
        'ch99_code': '9903.01.32',  # Annex II exemption
        'deal_name': 'Taiwan Tech Agreement',
        'effective_start': date(2025, 9, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'Taiwan Tech Agreement',
        'dataset_tag': 'v21.0_initial',
    },
    # Computers - reduced
    {
        'country_code': 'TW',
        'hts_prefix': '8471',
        'prefix_len': 4,
        'override_rate': Decimal('10.00'),
        'ch99_code': '9903.01.25',
        'deal_name': 'Taiwan Tech Agreement',
        'effective_start': date(2025, 9, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'Taiwan Tech Agreement',
        'dataset_tag': 'v21.0_initial',
    },
]

# UK deal - machinery reduced
UK_DEAL_OVERRIDES = [
    # Machinery - reduced
    {
        'country_code': 'GB',
        'hts_prefix': '8481',
        'prefix_len': 4,
        'override_rate': Decimal('5.00'),
        'ch99_code': '9903.01.25',
        'deal_name': 'UK Trade Deal',
        'effective_start': date(2025, 12, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'UK Trade Agreement',
        'dataset_tag': 'v21.0_initial',
    },
    # Autos - reduced
    {
        'country_code': 'GB',
        'hts_prefix': '8703',
        'prefix_len': 4,
        'override_rate': Decimal('5.00'),
        'ch99_code': '9903.01.25',
        'deal_name': 'UK Trade Deal',
        'effective_start': date(2025, 12, 1),
        'effective_end': date(9999, 12, 31),
        'legal_authority': 'UK Trade Agreement',
        'dataset_tag': 'v21.0_initial',
    },
]

# Combine all overrides
ALL_OVERRIDES = (
    INDIA_DEAL_OVERRIDES +
    ARGENTINA_DEAL_OVERRIDES +
    TAIWAN_DEAL_OVERRIDES +
    UK_DEAL_OVERRIDES
)


# =============================================================================
# Ingestion Functions
# =============================================================================

def ingest_overrides(dry_run: bool = False) -> dict:
    """
    Ingest deal overrides into database.

    Uses upsert logic - update existing, add new.

    Returns:
        Stats dict with counts
    """
    stats = {
        'total_overrides': len(ALL_OVERRIDES),
        'inserted': 0,
        'updated': 0,
        'unchanged': 0,
        'existing_before': 0,
    }

    stats['existing_before'] = IeepaReciprocalDealOverrides.query.count()

    for override_data in ALL_OVERRIDES:
        # Check for existing record
        existing = IeepaReciprocalDealOverrides.query.filter_by(
            country_code=override_data['country_code'],
            hts_prefix=override_data['hts_prefix'],
            deal_name=override_data['deal_name']
        ).first()

        if existing:
            # Check if update needed
            needs_update = False
            for key, value in override_data.items():
                if getattr(existing, key, None) != value:
                    needs_update = True
                    break

            if needs_update:
                if not dry_run:
                    for key, value in override_data.items():
                        setattr(existing, key, value)
                stats['updated'] += 1
            else:
                stats['unchanged'] += 1
        else:
            # Insert new override
            if not dry_run:
                new_override = IeepaReciprocalDealOverrides(**override_data)
                db.session.add(new_override)
            stats['inserted'] += 1

    if not dry_run:
        db.session.commit()

    return stats


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Ingest IEEPA Reciprocal deal overrides into database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying database'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA Reciprocal Deal Overrides Ingestion v21.0")
    print("=" * 60)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        # Summary
        print(f"\nTotal overrides to ingest: {len(ALL_OVERRIDES)}")

        # Breakdown by deal
        deal_counts = {}
        for o in ALL_OVERRIDES:
            deal = o['deal_name']
            deal_counts[deal] = deal_counts.get(deal, 0) + 1

        print("\nBy deal:")
        for deal, cnt in sorted(deal_counts.items()):
            print(f"  {deal}: {cnt}")

        # Show all overrides
        print("\nOverrides:")
        for o in ALL_OVERRIDES:
            print(f"  {o['country_code']} / {o['hts_prefix']} -> {o['override_rate']}% ({o['deal_name']})")

        # Perform ingestion
        if args.dry_run:
            print("\n[DRY RUN] Previewing changes (no database modifications)")
        else:
            print("\nIngesting to database...")

        stats = ingest_overrides(dry_run=args.dry_run)

        # Print results
        print("\n" + "=" * 60)
        print("Ingestion Results:")
        print("=" * 60)
        print(f"  Total overrides:   {stats['total_overrides']}")
        print(f"  Existing before:   {stats['existing_before']}")
        print(f"  Inserted:          {stats['inserted']}")
        print(f"  Updated:           {stats['updated']}")
        print(f"  Unchanged:         {stats['unchanged']}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made to database")
        else:
            final_count = IeepaReciprocalDealOverrides.query.count()
            print(f"\n  Final row count:   {final_count}")
            print("\n[SUCCESS] Ingestion complete")


if __name__ == "__main__":
    main()
