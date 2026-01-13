#!/usr/bin/env python3
"""
Migrate Section 232 data from static section_232_materials table to temporal section_232_rates table.

This script backfills historical rate periods for Section 232 tariffs:
- Steel: 25% (Mar 2018 - Mar 2025) → 50% (Mar 2025 - present)
- Aluminum: 10% (Mar 2018 - Mar 2025) → 50% (Mar 2025 - present)
- Copper: 50% (Mar 2025 - present) - added by Proclamation 10896

Design Flaw 6 Fix: Creates temporal rows so get_rate_as_of() queries work for all dates.

Usage:
    pipenv run python scripts/migrate_232_to_temporal.py
    pipenv run python scripts/migrate_232_to_temporal.py --dry-run
"""

import sys
import os
from datetime import date
from decimal import Decimal

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import Section232Rate, Section232Material


# Historical Section 232 rate periods from Presidential Proclamations
SECTION_232_HISTORY = [
    # Steel - Original Proclamation 9705 (March 23, 2018)
    {
        'material': 'steel',
        'rate': Decimal('0.25'),  # 25%
        'start': date(2018, 3, 23),
        'end': date(2025, 3, 11),  # Day before Proclamation 10896
        'source_doc': 'Proclamation 9705 (83 FR 11625)',
    },
    # Steel - Proclamation 10896 doubled rate (March 12, 2025)
    {
        'material': 'steel',
        'rate': Decimal('0.50'),  # 50%
        'start': date(2025, 3, 12),
        'end': None,  # Current
        'source_doc': 'Proclamation 10896 (90 FR 40326)',
    },

    # Aluminum - Original Proclamation 9704 (March 23, 2018)
    {
        'material': 'aluminum',
        'rate': Decimal('0.10'),  # 10%
        'start': date(2018, 3, 23),
        'end': date(2025, 3, 11),  # Day before Proclamation 10896
        'source_doc': 'Proclamation 9704 (83 FR 11619)',
    },
    # Aluminum - Proclamation 10896 increased rate (March 12, 2025)
    {
        'material': 'aluminum',
        'rate': Decimal('0.50'),  # 50%
        'start': date(2025, 3, 12),
        'end': None,  # Current
        'source_doc': 'Proclamation 10896 (90 FR 40326)',
    },

    # Copper - Added by Proclamation 10896 (March 12, 2025)
    # No historical period - copper wasn't covered before March 2025
    {
        'material': 'copper',
        'rate': Decimal('0.50'),  # 50%
        'start': date(2025, 3, 12),
        'end': None,  # Current
        'source_doc': 'Proclamation 10896 - Section 232 Copper Investigation',
    },
]


def migrate_232_to_temporal(dry_run=False):
    """
    Migrate all section_232_materials rows to temporal section_232_rates table.

    For each HTS code in section_232_materials:
    - Look up its material type (steel/aluminum/copper)
    - Create temporal rows for each historical period
    - Preserve article_type, claim_code, disclaim_code from static table
    """
    app = create_app()

    with app.app_context():
        # Check current state
        existing_count = Section232Rate.query.count()
        print(f"Current section_232_rates count: {existing_count}")

        if existing_count > 0 and not dry_run:
            print(f"WARNING: section_232_rates already has {existing_count} rows.")
            response = input("Clear existing data and re-migrate? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                return

            # Clear existing data
            Section232Rate.query.delete()
            db.session.commit()
            print("Cleared existing section_232_rates data.")

        # Get all HTS codes from static table
        materials = Section232Material.query.all()
        print(f"Found {len(materials)} HTS codes in section_232_materials")

        # Group by material for reporting
        material_counts = {'steel': 0, 'aluminum': 0, 'copper': 0}
        rows_created = 0

        for mat in materials:
            material_counts[mat.material] = material_counts.get(mat.material, 0) + 1

            # Find applicable historical periods for this material
            periods = [p for p in SECTION_232_HISTORY if p['material'] == mat.material]

            for period in periods:
                if dry_run:
                    print(f"  [DRY RUN] Would create: {mat.hts_8digit} | {mat.material} | "
                          f"{period['rate']*100:.0f}% | {period['start']} - {period['end'] or 'current'}")
                else:
                    rate = Section232Rate(
                        hts_8digit=mat.hts_8digit,
                        material_type=mat.material,
                        article_type=mat.article_type,
                        chapter_99_claim=mat.claim_code,
                        chapter_99_disclaim=mat.disclaim_code,
                        duty_rate=period['rate'],
                        country_code=None,  # Global rate, not country-specific
                        effective_start=period['start'],
                        effective_end=period['end'],
                        source_doc=period['source_doc'],
                        created_by='migrate_232_to_temporal.py',
                    )
                    db.session.add(rate)
                    rows_created += 1

        if not dry_run:
            db.session.commit()

        # Summary
        print("\n" + "="*60)
        print("MIGRATION SUMMARY")
        print("="*60)
        print(f"HTS codes by material:")
        for mat, count in material_counts.items():
            print(f"  {mat}: {count} codes")

        periods_per_material = {
            'steel': 2,      # 2018-2025, 2025-present
            'aluminum': 2,   # 2018-2025, 2025-present
            'copper': 1,     # 2025-present only
        }

        expected_rows = sum(
            material_counts.get(mat, 0) * periods
            for mat, periods in periods_per_material.items()
        )

        if dry_run:
            print(f"\n[DRY RUN] Would create {expected_rows} temporal rows")
        else:
            print(f"\nCreated {rows_created} temporal rows in section_232_rates")

            # Verify
            final_count = Section232Rate.query.count()
            print(f"Final section_232_rates count: {final_count}")

            # Test a query
            print("\nVerification queries:")

            # Steel before March 2025
            steel_before = Section232Rate.get_rate_as_of(
                hts_8digit='72081000',  # Common steel HTS
                material='steel',
                country_code=None,
                as_of_date=date(2025, 2, 15)
            )
            if steel_before:
                print(f"  Steel (Feb 2025): {steel_before.duty_rate*100:.0f}% - "
                      f"{'PASS' if steel_before.duty_rate == Decimal('0.25') else 'FAIL'}")
            else:
                print(f"  Steel (Feb 2025): No rate found - checking if HTS exists...")
                # Try to find any steel HTS
                any_steel = Section232Rate.query.filter_by(material_type='steel').first()
                if any_steel:
                    print(f"    Found steel HTS: {any_steel.hts_8digit}")

            # Steel after March 2025
            steel_after = Section232Rate.get_rate_as_of(
                hts_8digit='72081000',
                material='steel',
                country_code=None,
                as_of_date=date(2025, 4, 15)
            )
            if steel_after:
                print(f"  Steel (Apr 2025): {steel_after.duty_rate*100:.0f}% - "
                      f"{'PASS' if steel_after.duty_rate == Decimal('0.50') else 'FAIL'}")

            # Aluminum before March 2025
            al_before = Section232Rate.get_rate_as_of(
                hts_8digit='76012000',  # Common aluminum HTS
                material='aluminum',
                country_code=None,
                as_of_date=date(2025, 2, 15)
            )
            if al_before:
                print(f"  Aluminum (Feb 2025): {al_before.duty_rate*100:.0f}% - "
                      f"{'PASS' if al_before.duty_rate == Decimal('0.10') else 'FAIL'}")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("="*60)
        print("DRY RUN MODE - No changes will be made")
        print("="*60)

    migrate_232_to_temporal(dry_run=dry_run)
