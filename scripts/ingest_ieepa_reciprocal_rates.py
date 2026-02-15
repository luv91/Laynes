#!/usr/bin/env python3
"""
v21.0: IEEPA Reciprocal Rate Schedule Ingestion Script

Ingests country-specific rates into the ieepa_reciprocal_rate_schedule table.

Features:
- Baseline default (NULL country_code) at 10%
- MFN ceiling partners with per-partner Chapter 99 codes
- Temporal versioning for rate changes (e.g., China 34% -> 10%)
- EXEMPT countries (USMCA, Column 2)
- SUSPENDED_TO_BASELINE for negotiated pause

Data Sources (per Gap #1 priority):
1. Federal Register / Executive Orders (PRIMARY)
2. CSMS Messages
3. CBP Tariff Overview PDF
4. Yale Budget Lab (verification)

Usage:
    python scripts/ingest_ieepa_reciprocal_rates.py             # Ingest rates
    python scripts/ingest_ieepa_reciprocal_rates.py --dry-run   # Preview only
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
from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule


# =============================================================================
# Rate Schedule Data
# =============================================================================

# Baseline rate (applies to all countries not specifically listed)
BASELINE_RATE = {
    'country_code': None,  # NULL = default for all countries
    'country_group': 'BASELINE',
    'regime_type': 'BASELINE_10',
    'rate_pct': Decimal('10.00'),
    'ceiling_pct': None,
    'ch99_code': '9903.01.25',
    'ch99_mfn_zero': None,
    'ch99_mfn_topup': None,
    'effective_start': date(2025, 4, 5),
    'effective_end': date(9999, 12, 31),
    'legal_authority': 'EO 14257',
    'fr_citation': None,
    'deal_name': None,
    'dataset_tag': 'v21.0_initial',
}

# USMCA partners - exempt
USMCA_RATES = [
    {
        'country_code': 'CA',
        'country_group': 'USMCA',
        'regime_type': 'EXEMPT',
        'rate_pct': Decimal('0'),
        'ch99_code': '9903.01.26',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },
    {
        'country_code': 'MX',
        'country_group': 'USMCA',
        'regime_type': 'EXEMPT',
        'rate_pct': Decimal('0'),
        'ch99_code': '9903.01.26',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },
]

# Column 2 countries - exempt (use existing high tariffs)
COLUMN2_RATES = [
    {
        'country_code': 'CU',
        'country_group': 'COLUMN_2',
        'regime_type': 'EXEMPT',
        'rate_pct': Decimal('0'),
        'ch99_code': '9903.01.29',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },
    {
        'country_code': 'KP',
        'country_group': 'COLUMN_2',
        'regime_type': 'EXEMPT',
        'rate_pct': Decimal('0'),
        'ch99_code': '9903.01.29',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },
    {
        'country_code': 'BY',
        'country_group': 'COLUMN_2',
        'regime_type': 'EXEMPT',
        'rate_pct': Decimal('0'),
        'ch99_code': '9903.01.29',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },
    {
        'country_code': 'RU',
        'country_group': 'COLUMN_2',
        'regime_type': 'EXEMPT',
        'rate_pct': Decimal('0'),
        'ch99_code': '9903.01.29',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },
]

# MFN ceiling partners - EU (27 countries)
EU_COUNTRY_CODES = [
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
    'DE', 'GR', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
    'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE'
]

EU_MFN_CEILING_RATES = [
    {
        'country_code': cc,
        'country_group': 'EU',
        'regime_type': 'MFN_CEILING',
        'rate_pct': None,  # Calculated: min(ceiling, max(0, ceiling - base_mfn))
        'ceiling_pct': Decimal('15.00'),
        'ch99_code': None,  # Determined by MFN comparison
        'ch99_mfn_zero': '9903.02.19',  # MFN >= 15%: no additional duty
        'ch99_mfn_topup': '9903.02.20',  # MFN < 15%: top-up to 15%
        'effective_start': date(2025, 8, 7),  # EU deal effective Aug 7
        'legal_authority': 'EO 14326, EU Deal',
        'fr_citation': 'FR 90 FR 37963',
        'dataset_tag': 'v21.0_initial',
    }
    for cc in EU_COUNTRY_CODES
]

# Japan - MFN ceiling with Japan-specific codes
JAPAN_RATES = [
    {
        'country_code': 'JP',
        'country_group': 'JAPAN',
        'regime_type': 'MFN_CEILING',
        'rate_pct': None,
        'ceiling_pct': Decimal('15.00'),  # 15% ceiling (EO 14345)
        'ch99_code': None,
        'ch99_mfn_zero': '9903.02.72',
        'ch99_mfn_topup': '9903.02.73',
        'effective_start': date(2025, 8, 7),  # Retroactive to Aug 7
        'legal_authority': 'EO 14345',
        'dataset_tag': 'v21.0_initial',
    },
]

# Korea - MFN ceiling
KOREA_RATES = [
    {
        'country_code': 'KR',
        'country_group': 'KOREA',
        'regime_type': 'MFN_CEILING',
        'rate_pct': None,
        'ceiling_pct': Decimal('15.00'),  # 15% ceiling (Korea deal)
        'ch99_code': None,
        'ch99_mfn_zero': '9903.02.79',
        'ch99_mfn_topup': '9903.02.80',
        'effective_start': date(2025, 11, 14),
        'legal_authority': 'EO 14XXX, Korea Deal',
        'dataset_tag': 'v21.0_initial',
    },
]

# Switzerland - MFN ceiling
SWITZERLAND_RATES = [
    {
        'country_code': 'CH',
        'country_group': 'SWITZERLAND',
        'regime_type': 'MFN_CEILING',
        'rate_pct': None,
        'ceiling_pct': Decimal('15.00'),  # 15% ceiling (EO 14346)
        'ch99_code': None,
        'ch99_mfn_zero': '9903.02.82',
        'ch99_mfn_topup': '9903.02.83',
        'effective_start': date(2025, 11, 14),
        'legal_authority': 'EO 14346',
        'dataset_tag': 'v21.0_initial',
    },
]

# Liechtenstein - MFN ceiling (follows Switzerland)
LIECHTENSTEIN_RATES = [
    {
        'country_code': 'LI',
        'country_group': 'LIECHTENSTEIN',
        'regime_type': 'MFN_CEILING',
        'rate_pct': None,
        'ceiling_pct': Decimal('15.00'),  # 15% ceiling (EO 14346)
        'ch99_code': None,
        'ch99_mfn_zero': '9903.02.87',
        'ch99_mfn_topup': '9903.02.88',
        'effective_start': date(2025, 11, 14),
        'legal_authority': 'EO 14346',
        'dataset_tag': 'v21.0_initial',
    },
]

# UK - suspended to baseline
UK_RATES = [
    {
        'country_code': 'GB',
        'country_group': 'UK',
        'regime_type': 'SUSPENDED_TO_BASELINE',
        'rate_pct': Decimal('10.00'),
        'ceiling_pct': None,
        'ch99_code': '9903.01.25',
        'ch99_mfn_zero': None,
        'ch99_mfn_topup': None,
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257, UK exemption',
        'dataset_tag': 'v21.0_initial',
    },
]

# China - temporal versioning (3 eras)
CHINA_RATES = [
    # Era 1: 34% (April 9 - May 13)
    {
        'country_code': 'CN',
        'country_group': 'CHINA',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('34.00'),
        'ceiling_pct': None,
        'ch99_code': '9903.01.63',
        'ch99_mfn_zero': None,
        'ch99_mfn_topup': None,
        'effective_start': date(2025, 4, 9),
        'effective_end': date(2025, 5, 14),  # Day AFTER last valid day
        'legal_authority': 'EO 14257',
        'dataset_tag': 'v21.0_initial',
    },
    # Era 2: Suspended to 10% (May 14 - Nov 9)
    {
        'country_code': 'CN',
        'country_group': 'CHINA',
        'regime_type': 'SUSPENDED_TO_BASELINE',
        'rate_pct': Decimal('10.00'),
        'ceiling_pct': None,
        'ch99_code': '9903.01.25',
        'ch99_mfn_zero': None,
        'ch99_mfn_topup': None,
        'effective_start': date(2025, 5, 14),
        'effective_end': date(2025, 11, 10),
        'legal_authority': 'EO 14298, China 90-day suspension',
        'dataset_tag': 'v21.0_initial',
    },
    # Era 3: Extended 10% (Nov 10, 2025 - Nov 10, 2026)
    {
        'country_code': 'CN',
        'country_group': 'CHINA',
        'regime_type': 'SUSPENDED_TO_BASELINE',
        'rate_pct': Decimal('10.00'),
        'ceiling_pct': None,
        'ch99_code': '9903.01.25',
        'ch99_mfn_zero': None,
        'ch99_mfn_topup': None,
        'effective_start': date(2025, 11, 10),
        'effective_end': date(2026, 11, 11),  # Day AFTER last valid day
        'legal_authority': 'EO 14XXX, China extended suspension',
        'dataset_tag': 'v21.0_initial',
    },
]

# High-rate countries (select examples from Annex I)
HIGH_RATE_COUNTRIES = [
    # Vietnam - 20% (EO 14326 Annex I)
    {
        'country_code': 'VN',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('20.00'),
        'ch99_code': '9903.02.69',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # Thailand - 19% (EO 14326 Annex I)
    {
        'country_code': 'TH',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('19.00'),
        'ch99_code': '9903.02.61',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # India - 25% (or interim deal rate)
    {
        'country_code': 'IN',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('25.00'),
        'ch99_code': '9903.02.26',  # India (9903.02.34 is Lesotho)
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # Taiwan - 20% (EO 14326 Annex I)
    {
        'country_code': 'TW',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('20.00'),
        'ch99_code': '9903.02.60',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # Indonesia - 19% (EO 14326 Annex I)
    {
        'country_code': 'ID',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('19.00'),
        'ch99_code': '9903.02.27',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # Bangladesh - 20% (EO 14326 Annex I)
    {
        'country_code': 'BD',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('20.00'),
        'ch99_code': '9903.02.05',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # Malaysia - 19% (EO 14326 Annex I)
    {
        'country_code': 'MY',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('19.00'),
        'ch99_code': '9903.02.39',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
    # Argentina - 10% (baseline)
    {
        'country_code': 'AR',
        'country_group': 'ANNEX_I',
        'regime_type': 'BASELINE_10',
        'rate_pct': Decimal('10.00'),
        'ch99_code': '9903.01.25',
        'effective_start': date(2025, 4, 5),
        'legal_authority': 'EO 14257',
        'dataset_tag': 'v21.0_initial',
    },
    # Brazil - 10% (Annex I rate, ch99 9903.02.09)
    {
        'country_code': 'BR',
        'country_group': 'ANNEX_I',
        'regime_type': 'FIXED_RATE',
        'rate_pct': Decimal('10.00'),
        'ch99_code': '9903.02.09',
        'effective_start': date(2025, 8, 7),
        'legal_authority': 'EO 14326, Annex I',
        'dataset_tag': 'v21.0_initial',
    },
]


def fill_defaults(rate_dict):
    """Fill in default values for rate dictionary."""
    defaults = {
        'ceiling_pct': None,
        'ch99_code': None,
        'ch99_mfn_zero': None,
        'ch99_mfn_topup': None,
        'effective_end': date(9999, 12, 31),
        'fr_citation': None,
        'deal_name': None,
        'source_doc_id': None,
    }
    result = defaults.copy()
    result.update(rate_dict)
    return result


# Combine all rates
ALL_RATES = (
    [BASELINE_RATE] +
    USMCA_RATES +
    COLUMN2_RATES +
    EU_MFN_CEILING_RATES +
    JAPAN_RATES +
    KOREA_RATES +
    SWITZERLAND_RATES +
    LIECHTENSTEIN_RATES +
    UK_RATES +
    CHINA_RATES +
    HIGH_RATE_COUNTRIES
)

# Apply defaults
ALL_RATES = [fill_defaults(r) for r in ALL_RATES]


# =============================================================================
# Ingestion Functions
# =============================================================================

def ingest_rates(dry_run: bool = False) -> dict:
    """
    Ingest rate schedule into database.

    Uses upsert logic - update existing, add new.
    IMPORTANT: This script is authoritative for the countries it covers.
    It deletes any expansion-script rows (v21.1+) for those countries first,
    so the resolver picks these v21.0 rows (MFN_CEILING, temporal China, etc.)
    instead of generic FIXED_RATE rows from the expansion.

    Returns:
        Stats dict with counts
    """
    stats = {
        'total_rates': len(ALL_RATES),
        'inserted': 0,
        'updated': 0,
        'unchanged': 0,
        'existing_before': 0,
        'expansion_deleted': 0,
    }

    stats['existing_before'] = IeepaReciprocalRateSchedule.query.count()

    # Collect all country codes this script is authoritative for
    authoritative_countries = set()
    for rate_data in ALL_RATES:
        cc = rate_data.get('country_code')
        if cc is not None:
            authoritative_countries.add(cc)

    # Delete expansion rows for authoritative countries.
    # These are rows with dataset_tag != 'v21.0_initial' that would
    # overshadow this script's MFN_CEILING / SUSPENDED / temporal rows.
    if authoritative_countries:
        expansion_rows = IeepaReciprocalRateSchedule.query.filter(
            IeepaReciprocalRateSchedule.country_code.in_(authoritative_countries),
            IeepaReciprocalRateSchedule.dataset_tag != 'v21.0_initial'
        ).all()

        if expansion_rows:
            print(f"\n  Removing {len(expansion_rows)} expansion row(s) for "
                  f"authoritative countries: {sorted(authoritative_countries)}")
            for row in expansion_rows:
                print(f"    Deleting: {row.country_code} | "
                      f"{row.regime_type} | {row.rate_pct}% | "
                      f"tag={row.dataset_tag}")
                if not dry_run:
                    db.session.delete(row)
            stats['expansion_deleted'] = len(expansion_rows)

    for rate_data in ALL_RATES:
        # Check for existing record by country_code + effective_start + dataset_tag
        existing = IeepaReciprocalRateSchedule.query.filter_by(
            country_code=rate_data['country_code'],
            effective_start=rate_data['effective_start'],
            dataset_tag=rate_data['dataset_tag']
        ).first()

        if existing:
            # Check if update needed
            needs_update = False
            for key, value in rate_data.items():
                current = getattr(existing, key, None)
                # Compare carefully for Decimal/None
                if current != value:
                    needs_update = True
                    break

            if needs_update:
                if not dry_run:
                    for key, value in rate_data.items():
                        setattr(existing, key, value)
                stats['updated'] += 1
            else:
                stats['unchanged'] += 1
        else:
            # Insert new rate
            if not dry_run:
                new_rate = IeepaReciprocalRateSchedule(**rate_data)
                db.session.add(new_rate)
            stats['inserted'] += 1

    if not dry_run:
        db.session.commit()

    return stats


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Ingest IEEPA Reciprocal rate schedule into database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying database'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA Reciprocal Rate Schedule Ingestion v21.0")
    print("=" * 60)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        # Summary
        print(f"\nTotal rates to ingest: {len(ALL_RATES)}")

        # Breakdown by regime type
        regime_counts = {}
        for r in ALL_RATES:
            rt = r['regime_type']
            regime_counts[rt] = regime_counts.get(rt, 0) + 1

        print("\nBy regime type:")
        for rt, cnt in sorted(regime_counts.items()):
            print(f"  {rt}: {cnt}")

        # Show key examples
        print("\nKey countries:")
        key_countries = ['CN', 'JP', 'KR', 'CH', 'VN', 'GB', 'IT']
        for cc in key_countries:
            rates = [r for r in ALL_RATES if r['country_code'] == cc]
            for r in rates:
                print(f"  {cc}: {r['regime_type']} - {r.get('rate_pct') or r.get('ceiling_pct')}% ({r['effective_start']} to {r['effective_end']})")

        # Perform ingestion
        if args.dry_run:
            print("\n[DRY RUN] Previewing changes (no database modifications)")
        else:
            print("\nIngesting to database...")

        stats = ingest_rates(dry_run=args.dry_run)

        # Print results
        print("\n" + "=" * 60)
        print("Ingestion Results:")
        print("=" * 60)
        print(f"  Total rates:       {stats['total_rates']}")
        print(f"  Existing before:   {stats['existing_before']}")
        print(f"  Expansion deleted: {stats['expansion_deleted']}")
        print(f"  Inserted:          {stats['inserted']}")
        print(f"  Updated:           {stats['updated']}")
        print(f"  Unchanged:         {stats['unchanged']}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made to database")
        else:
            final_count = IeepaReciprocalRateSchedule.query.count()
            print(f"\n  Final row count:   {final_count}")
            print("\n[SUCCESS] Ingestion complete")


if __name__ == "__main__":
    main()
