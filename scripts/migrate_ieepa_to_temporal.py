#!/usr/bin/env python3
"""
Migrate IEEPA rates from hardcoded IEEPA_CODES to temporal ieepa_rates table.

This script backfills historical rate periods for IEEPA tariffs:
- Fentanyl (EO 14195, 14257, 14357): Rate changes over 2025
- Reciprocal (EO 14257): Multiple variants and countries

Design Flaw 6 Fix: Creates temporal rows so get_rate_as_of() queries work for all dates.

Usage:
    pipenv run python scripts/migrate_ieepa_to_temporal.py
    pipenv run python scripts/migrate_ieepa_to_temporal.py --dry-run
"""

import sys
import os
from datetime import date
from decimal import Decimal

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import IeepaRate


# Countries subject to IEEPA Fentanyl
FENTANYL_COUNTRIES = ['CN', 'HK', 'MO']  # China, Hong Kong, Macau

# Countries subject to IEEPA Reciprocal (as of EO 14257)
RECIPROCAL_COUNTRIES = [
    'CN',  # China - 145% total (10% base + 135% additional)
    'HK',  # Hong Kong
    'MO',  # Macau
    'GB',  # UK
    'JP',  # Japan
    'VN',  # Vietnam
    'IN',  # India
    'TW',  # Taiwan
    'KR',  # South Korea
]

# Historical IEEPA rate periods from Executive Orders
IEEPA_HISTORY = [
    # =========================================================================
    # FENTANYL PROGRAM
    # =========================================================================

    # Phase 1: EO 14195 - Original 10% Fentanyl tariff (Feb 4, 2025)
    # Note: Initially applied to CN, HK, MO
    *[{
        'program_type': 'fentanyl',
        'country_code': country,
        'chapter_99_code': '9903.01.24',
        'duty_rate': Decimal('0.10'),  # 10%
        'variant': None,
        'rate_type': 'ad_valorem',
        'effective_start': date(2025, 2, 4),
        'effective_end': date(2025, 4, 8),  # Day before EO 14257
        'source_doc': 'EO 14195 - Imposing Duties to Address the Synthetic Opioid Supply Chain',
    } for country in FENTANYL_COUNTRIES],

    # Phase 2: EO 14257 doubled Fentanyl for China (Apr 9, 2025)
    # China specifically gets 20%, others stay at 10%
    {
        'program_type': 'fentanyl',
        'country_code': 'CN',
        'chapter_99_code': '9903.01.24',
        'duty_rate': Decimal('0.20'),  # 20% (doubled)
        'variant': None,
        'rate_type': 'ad_valorem',
        'effective_start': date(2025, 4, 9),
        'effective_end': date(2025, 11, 14),  # Day before EO 14357
        'source_doc': 'EO 14257 - Regulating Imports with a Reciprocal Tariff',
    },
    # HK and MO stayed at 10% during this period
    *[{
        'program_type': 'fentanyl',
        'country_code': country,
        'chapter_99_code': '9903.01.24',
        'duty_rate': Decimal('0.10'),  # 10% (unchanged)
        'variant': None,
        'rate_type': 'ad_valorem',
        'effective_start': date(2025, 4, 9),
        'effective_end': date(2025, 11, 14),
        'source_doc': 'EO 14257 - Fentanyl rate for HK/MO unchanged',
    } for country in ['HK', 'MO']],

    # Phase 3: EO 14357 reduced Fentanyl back to 10% (Nov 15, 2025)
    *[{
        'program_type': 'fentanyl',
        'country_code': country,
        'chapter_99_code': '9903.01.24',
        'duty_rate': Decimal('0.10'),  # 10% (reduced)
        'variant': None,
        'rate_type': 'ad_valorem',
        'effective_start': date(2025, 11, 15),
        'effective_end': None,  # Current
        'source_doc': 'EO 14357 - Fentanyl tariff rate adjustment',
    } for country in FENTANYL_COUNTRIES],

    # =========================================================================
    # RECIPROCAL PROGRAM
    # =========================================================================

    # Standard Reciprocal Rate (10% for most countries)
    *[{
        'program_type': 'reciprocal',
        'country_code': country,
        'chapter_99_code': '9903.01.25',
        'duty_rate': Decimal('0.10'),  # 10% base reciprocal
        'variant': 'standard',
        'rate_type': 'ad_valorem',
        'effective_start': date(2025, 4, 9),
        'effective_end': None,  # Current
        'source_doc': 'EO 14257 - Reciprocal Tariff (standard rate)',
    } for country in RECIPROCAL_COUNTRIES],

    # Annex II Exempt (energy, pharma, semiconductors, minerals, lumber)
    # Rate is 0% - exemption applies
    *[{
        'program_type': 'reciprocal',
        'country_code': country,
        'chapter_99_code': '9903.01.32',
        'duty_rate': Decimal('0.00'),  # Exempt
        'variant': 'annex_ii_exempt',
        'rate_type': 'exempt',
        'effective_start': date(2025, 4, 9),
        'effective_end': None,  # Current
        'source_doc': 'EO 14257 Annex II - Energy/Pharma/Semiconductor Exemptions',
    } for country in RECIPROCAL_COUNTRIES],

    # Section 232 Exempt (steel/aluminum already covered by 232)
    # Rate is 0% for reciprocal portion
    *[{
        'program_type': 'reciprocal',
        'country_code': country,
        'chapter_99_code': '9903.01.33',
        'duty_rate': Decimal('0.00'),  # Exempt (232 takes precedence)
        'variant': 'section_232_exempt',
        'rate_type': 'exempt',
        'effective_start': date(2025, 4, 9),
        'effective_end': None,  # Current
        'source_doc': 'EO 14257 - Section 232 exemption (Note 16)',
    } for country in RECIPROCAL_COUNTRIES],

    # US Content Exempt (>= 20% US content)
    # Rate is 0% when US content threshold met
    *[{
        'program_type': 'reciprocal',
        'country_code': country,
        'chapter_99_code': '9903.01.34',
        'duty_rate': Decimal('0.00'),  # Exempt
        'variant': 'us_content_exempt',
        'rate_type': 'exempt',
        'effective_start': date(2025, 4, 9),
        'effective_end': None,  # Current
        'source_doc': 'EO 14257 - US Content exemption (>= 20%)',
    } for country in RECIPROCAL_COUNTRIES],
]


def migrate_ieepa_to_temporal(dry_run=False):
    """
    Populate ieepa_rates table with historical rate periods.

    Creates temporal rows for all IEEPA programs:
    - Fentanyl: 3 periods (10% → 20% → 10%) for CN, single 10% for HK/MO
    - Reciprocal: 4 variants per country (standard, annex_ii, 232, us_content)
    """
    app = create_app()

    with app.app_context():
        # Check current state
        existing_count = IeepaRate.query.count()
        print(f"Current ieepa_rates count: {existing_count}")

        if existing_count > 0 and not dry_run:
            print(f"WARNING: ieepa_rates already has {existing_count} rows.")
            response = input("Clear existing data and re-migrate? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                return

            # Clear existing data
            IeepaRate.query.delete()
            db.session.commit()
            print("Cleared existing ieepa_rates data.")

        rows_created = 0
        program_counts = {'fentanyl': 0, 'reciprocal': 0}

        for period in IEEPA_HISTORY:
            program_counts[period['program_type']] = program_counts.get(period['program_type'], 0) + 1

            if dry_run:
                print(f"  [DRY RUN] Would create: {period['program_type']} | {period['country_code']} | "
                      f"{period['chapter_99_code']} | {period['duty_rate']*100:.0f}% | "
                      f"{period.get('variant', 'N/A')} | "
                      f"{period['effective_start']} - {period['effective_end'] or 'current'}")
            else:
                rate = IeepaRate(
                    program_type=period['program_type'],
                    country_code=period['country_code'],
                    chapter_99_code=period['chapter_99_code'],
                    duty_rate=period['duty_rate'],
                    variant=period.get('variant'),
                    rate_type=period.get('rate_type', 'ad_valorem'),
                    effective_start=period['effective_start'],
                    effective_end=period['effective_end'],
                    source_doc=period['source_doc'],
                    created_by='migrate_ieepa_to_temporal.py',
                )
                db.session.add(rate)
                rows_created += 1

        if not dry_run:
            db.session.commit()

        # Summary
        print("\n" + "="*60)
        print("MIGRATION SUMMARY")
        print("="*60)
        print(f"Rows by program:")
        for prog, count in program_counts.items():
            print(f"  {prog}: {count} rows")

        if dry_run:
            print(f"\n[DRY RUN] Would create {len(IEEPA_HISTORY)} temporal rows")
        else:
            print(f"\nCreated {rows_created} temporal rows in ieepa_rates")

            # Verify
            final_count = IeepaRate.query.count()
            print(f"Final ieepa_rates count: {final_count}")

            # Test queries
            print("\nVerification queries:")

            # Fentanyl September 2025 (should be 20% for CN)
            fent_sep = IeepaRate.get_rate_as_of(
                program_type='fentanyl',
                country_code='CN',
                as_of_date=date(2025, 9, 1)
            )
            if fent_sep:
                expected = Decimal('0.20')
                result = 'PASS' if fent_sep.duty_rate == expected else 'FAIL'
                print(f"  Fentanyl CN (Sep 2025): {fent_sep.duty_rate*100:.0f}% - {result}")
            else:
                print(f"  Fentanyl CN (Sep 2025): No rate found - FAIL")

            # Fentanyl December 2025 (should be 10% for CN)
            fent_dec = IeepaRate.get_rate_as_of(
                program_type='fentanyl',
                country_code='CN',
                as_of_date=date(2025, 12, 1)
            )
            if fent_dec:
                expected = Decimal('0.10')
                result = 'PASS' if fent_dec.duty_rate == expected else 'FAIL'
                print(f"  Fentanyl CN (Dec 2025): {fent_dec.duty_rate*100:.0f}% - {result}")
            else:
                print(f"  Fentanyl CN (Dec 2025): No rate found - FAIL")

            # Fentanyl March 2025 (should be 10% - before EO 14257)
            fent_mar = IeepaRate.get_rate_as_of(
                program_type='fentanyl',
                country_code='CN',
                as_of_date=date(2025, 3, 1)
            )
            if fent_mar:
                expected = Decimal('0.10')
                result = 'PASS' if fent_mar.duty_rate == expected else 'FAIL'
                print(f"  Fentanyl CN (Mar 2025): {fent_mar.duty_rate*100:.0f}% - {result}")
            else:
                print(f"  Fentanyl CN (Mar 2025): No rate found - FAIL")

            # Reciprocal Standard
            recip = IeepaRate.get_rate_as_of(
                program_type='reciprocal',
                country_code='CN',
                as_of_date=date(2025, 5, 1),
                variant='standard'
            )
            if recip:
                expected = Decimal('0.10')
                result = 'PASS' if recip.duty_rate == expected else 'FAIL'
                print(f"  Reciprocal CN standard (May 2025): {recip.duty_rate*100:.0f}% - {result}")
            else:
                print(f"  Reciprocal CN standard (May 2025): No rate found - FAIL")

            # Reciprocal Annex II Exempt
            annex = IeepaRate.get_rate_as_of(
                program_type='reciprocal',
                country_code='CN',
                as_of_date=date(2025, 5, 1),
                variant='annex_ii_exempt'
            )
            if annex:
                expected = Decimal('0.00')
                result = 'PASS' if annex.duty_rate == expected else 'FAIL'
                print(f"  Reciprocal CN annex_ii (May 2025): {annex.duty_rate*100:.0f}% - {result}")
            else:
                print(f"  Reciprocal CN annex_ii (May 2025): No rate found - FAIL")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("="*60)
        print("DRY RUN MODE - No changes will be made")
        print("="*60)

    migrate_ieepa_to_temporal(dry_run=dry_run)
