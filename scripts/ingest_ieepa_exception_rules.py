#!/usr/bin/env python3
"""
v21.0: IEEPA Reciprocal Exception Rules Ingestion Script

Ingests the 12 exception rules into the ieepa_reciprocal_exception_rules table.

Exception rules are checked in priority order and override normal country rates.
The first matching rule determines the result.

Bug fixes applied:
- Bug #1: requires_vessel_final_mode BOOLEAN column
- Bug #3: ch99_code nullable (TIB uses country's code)
- Bug A: transit_entry_start DATE column (distinct from effective_start)
- Bug B: requires_flag 'country_would_exceed_baseline' for Aug in-transit

Usage:
    python scripts/ingest_ieepa_exception_rules.py             # Ingest rules
    python scripts/ingest_ieepa_exception_rules.py --dry-run   # Preview only
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
from app.web.db.models.tariff_tables import IeepaReciprocalExceptionRules


# =============================================================================
# Exception Rules Data (12 rules per design doc)
# =============================================================================

EXCEPTION_RULES = [
    # Priority 1: Transshipment - CBP enforcement override
    {
        'rule_code': 'TRANSSHIPMENT',
        'priority': 1,
        'ch99_code': '9903.02.01',
        'rate_override': 40.00,
        'country_set': None,  # Applies to all countries
        'requires_flag': 'cbp_transshipment_determination',
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'FULL',
        'creates_split': False,
        'effective_start': date(2025, 8, 7),
        'effective_end': date(9999, 12, 31),
        'description': '40% in lieu of country rate; CBP-directed, no mitigation',
        'legal_authority': 'EO 14326 Sec.3',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 2: Section 232 subject - exempt from IEEPA reciprocal
    {
        'rule_code': 'S232_SUBJECT',
        'priority': 2,
        'ch99_code': '9903.01.33',
        'rate_override': 0,
        'country_set': None,  # Applies to all countries
        'requires_flag': 'is_232_subject',
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Products subject to Section 232 (steel, aluminum, copper) exempt from IEEPA reciprocal',
        'legal_authority': 'EO 14257, 232 exemption',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 3: Column 2 countries - exempt
    {
        'rule_code': 'COLUMN2',
        'priority': 3,
        'ch99_code': '9903.01.29',
        'rate_override': 0,
        'country_set': ['CU', 'KP', 'BY', 'RU'],  # Cuba, North Korea, Belarus, Russia
        'requires_flag': None,
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Column 2 countries (high tariff already) exempt from IEEPA reciprocal',
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 4: USMCA - CA/MX exempt
    {
        'rule_code': 'USMCA',
        'priority': 4,
        'ch99_code': '9903.01.26',
        'rate_override': 0,
        'country_set': ['CA', 'MX'],
        'requires_flag': None,
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'USMCA partners exempt from IEEPA reciprocal',
        'legal_authority': 'EO 14257, Annex III',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 5: Donations - exempt
    {
        'rule_code': 'DONATION',
        'priority': 5,
        'ch99_code': '9903.01.27',
        'rate_override': 0,
        'country_set': None,
        'requires_flag': 'is_donation',
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Charitable donations exempt from IEEPA reciprocal',
        'legal_authority': 'EO 14257, GN 3(c)(viii)',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 6: TIB - report only, ch99_code comes from country rate (NULL here per Bug #3)
    {
        'rule_code': 'TIB_REPORT_ONLY',
        'priority': 6,
        'ch99_code': None,  # Bug #3 fix: NULL, code from country rate
        'rate_override': 0,
        'country_set': None,
        'requires_flag': 'tib_claim',
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'TIB entries must report reciprocal code; no duty unless bond violated',
        'legal_authority': 'EO 14257, TIB provisions',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 7: Information materials - exempt
    {
        'rule_code': 'INFO_MATERIAL',
        'priority': 7,
        'ch99_code': '9903.01.30',
        'rate_override': 0,
        'country_set': None,
        'requires_flag': 'is_info_material',
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Books, films, sound recordings exempt per Berman Amendment',
        'legal_authority': 'EO 14257, GN 3(c)(ix)',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 8: US content split - deduct US content from value
    {
        'rule_code': 'US_CONTENT_SPLIT',
        'priority': 8,
        'ch99_code': None,  # Uses country code for foreign portion
        'rate_override': None,  # Rate from country schedule
        'country_set': None,
        'requires_flag': None,
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': 20.00,  # Min 20% US content to qualify
        'value_basis': 'NON_US_CONTENT',
        'creates_split': True,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Products with >20% US content: duty only on foreign portion',
        'legal_authority': 'EO 14257, GN 3(c)(iii)',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 9: Chapter 98 repair - duty on repair value only
    {
        'rule_code': 'CH98_REPAIR',
        'priority': 9,
        'ch99_code': None,  # Uses country code
        'rate_override': None,  # Rate from country schedule
        'country_set': None,
        'requires_flag': 'chapter98_claim',
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'REPAIR_VALUE',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Chapter 98 repairs: duty on repair value only (not full FOB)',
        'legal_authority': 'EO 14257, Chapter 98 provisions',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 10: In-transit April window
    {
        'rule_code': 'IN_TRANSIT_APR',
        'priority': 10,
        'ch99_code': '9903.01.28',
        'rate_override': 0,
        'country_set': None,  # Applies to ALL countries
        'requires_flag': None,
        'transit_load_before': date(2025, 4, 5),
        'transit_entry_start': date(2025, 4, 5),   # Bug A fix: entry window starts here
        'transit_enter_before': date(2025, 6, 16),  # Extended per CSMS #65201773
        'requires_vessel_final_mode': True,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),  # Rule queryable from here
        'effective_end': date(2025, 6, 16),   # Rule expires after window
        'description': 'Loaded before Apr 5 on final mode, entered Apr 5 - Jun 15: exempt',
        'legal_authority': 'EO 14257, CSMS #65201773',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 11: In-transit August window
    {
        'rule_code': 'IN_TRANSIT_AUG',
        'priority': 11,
        'ch99_code': '9903.01.25',
        'rate_override': 10.00,  # Stays at baseline 10%
        'country_set': None,
        'requires_flag': 'country_would_exceed_baseline',  # Bug B fix: skip baseline countries
        'transit_load_before': date(2025, 8, 7),
        'transit_entry_start': date(2025, 8, 7),   # Bug A fix: entry window starts here
        'transit_enter_before': date(2025, 10, 5),
        'requires_vessel_final_mode': True,
        'min_us_content_pct': None,
        'value_basis': 'FULL',
        'creates_split': False,
        'effective_start': date(2025, 8, 7),  # Rule queryable from here
        'effective_end': date(2025, 10, 5),   # Rule expires after window
        'description': 'Loaded before Aug 7, entered Aug 7 - Oct 4: baseline 10% (only for countries > baseline)',
        'legal_authority': 'EO 14326, CSMS #65829726',
        'dataset_tag': 'v21.0_initial',
    },

    # Priority 12: Annex II product exclusion
    {
        'rule_code': 'ANNEX_II_EXEMPT',
        'priority': 12,
        'ch99_code': '9903.01.32',
        'rate_override': 0,
        'country_set': None,
        'requires_flag': 'is_annex_ii_exempt',  # Checked via product exclusions table
        'transit_load_before': None,
        'transit_entry_start': None,
        'transit_enter_before': None,
        'requires_vessel_final_mode': False,
        'min_us_content_pct': None,
        'value_basis': 'ZERO',
        'creates_split': False,
        'effective_start': date(2025, 4, 5),
        'effective_end': date(9999, 12, 31),
        'description': 'Annex II products (pharmaceutical, semiconductor, critical mineral, energy) exempt',
        'legal_authority': 'EO 14257, Annex II',
        'dataset_tag': 'v21.0_initial',
    },
]


# =============================================================================
# Ingestion Functions
# =============================================================================

def ingest_exception_rules(dry_run: bool = False) -> dict:
    """
    Ingest exception rules into database.

    Uses upsert logic - update existing rules, add new ones.

    Returns:
        Stats dict with counts
    """
    stats = {
        'total_rules': len(EXCEPTION_RULES),
        'inserted': 0,
        'updated': 0,
        'unchanged': 0,
        'existing_before': 0,
    }

    stats['existing_before'] = IeepaReciprocalExceptionRules.query.count()

    for rule_data in EXCEPTION_RULES:
        existing = IeepaReciprocalExceptionRules.query.filter_by(
            rule_code=rule_data['rule_code']
        ).first()

        if existing:
            # Check if update needed
            needs_update = False
            for key, value in rule_data.items():
                if getattr(existing, key, None) != value:
                    needs_update = True
                    break

            if needs_update:
                if not dry_run:
                    for key, value in rule_data.items():
                        setattr(existing, key, value)
                stats['updated'] += 1
            else:
                stats['unchanged'] += 1
        else:
            # Insert new rule
            if not dry_run:
                new_rule = IeepaReciprocalExceptionRules(**rule_data)
                db.session.add(new_rule)
            stats['inserted'] += 1

    if not dry_run:
        db.session.commit()

    return stats


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Ingest IEEPA Reciprocal exception rules into database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying database'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA Reciprocal Exception Rules Ingestion v21.0")
    print("=" * 60)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        # Preview rules
        print(f"\nRules to ingest: {len(EXCEPTION_RULES)}")
        print("\nRule summary:")
        for rule in EXCEPTION_RULES:
            print(f"  P{rule['priority']:02d}: {rule['rule_code']:20s} - {rule['description'][:50]}")

        # Perform ingestion
        if args.dry_run:
            print("\n[DRY RUN] Previewing changes (no database modifications)")
        else:
            print("\nIngesting to database...")

        stats = ingest_exception_rules(dry_run=args.dry_run)

        # Print results
        print("\n" + "=" * 60)
        print("Ingestion Results:")
        print("=" * 60)
        print(f"  Total rules:      {stats['total_rules']}")
        print(f"  Existing before:  {stats['existing_before']}")
        print(f"  Inserted:         {stats['inserted']}")
        print(f"  Updated:          {stats['updated']}")
        print(f"  Unchanged:        {stats['unchanged']}")

        if args.dry_run:
            print("\n[DRY RUN] No changes made to database")
        else:
            final_count = IeepaReciprocalExceptionRules.query.count()
            print(f"\n  Final row count:  {final_count}")
            print("\n[SUCCESS] Ingestion complete")


if __name__ == "__main__":
    main()
