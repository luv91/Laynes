#!/usr/bin/env python3
"""
Section 301 Data Migration Script

Migrates existing section_301_rates_temporal.csv data to the new schema:
- Creates SourceVersion record for the migration
- Populates TariffMeasure table from CSV

Usage:
    # Dry run (no changes)
    python scripts/migrate_section301_to_new_schema.py --dry-run

    # Full migration
    python scripts/migrate_section301_to_new_schema.py

    # With verbose output
    python scripts/migrate_section301_to_new_schema.py --verbose

Version: 1.0.0
"""

import argparse
import csv
import hashlib
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def get_csv_hash(file_path: str) -> str:
    """Calculate SHA-256 hash of CSV file content."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def parse_date(date_str: str) -> Optional[date]:
    """Parse date string from CSV."""
    if not date_str or date_str.strip() == '':
        return None
    try:
        return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_rate(rate_str: str) -> Optional[Decimal]:
    """Parse rate from CSV (e.g., '0.075' for 7.5%)."""
    if not rate_str or rate_str.strip() == '':
        return None
    try:
        return Decimal(rate_str.strip())
    except Exception:
        return None


def map_list_to_program(list_name: str) -> str:
    """
    Map list name to program identifier.

    Note 20 lists: list_1, list_2, list_3, list_4a, list_4b
    Note 31 lists: Various newer lists from 2024+ actions
    """
    list_lower = list_name.lower().strip() if list_name else ""

    # Note 20 original lists
    if list_lower in ('list_1', 'list1'):
        return '301_NOTE20'
    if list_lower in ('list_2', 'list2'):
        return '301_NOTE20'
    if list_lower in ('list_3', 'list3'):
        return '301_NOTE20'
    if list_lower in ('list_4a', 'list4a', 'list_4a_facemasks'):
        return '301_NOTE20'
    if list_lower in ('list_4b', 'list4b'):
        return '301_NOTE20'

    # Note 31 (2024 Four-Year Review)
    if 'note_31' in list_lower or 'note31' in list_lower:
        return '301_NOTE31'

    # Default to Note 20 for legacy data
    return '301_NOTE20'


def determine_hts_type(hts_code: str) -> str:
    """Determine if HTS code is 8-digit or 10-digit."""
    clean = hts_code.replace('.', '').strip()
    return 'HTS10' if len(clean) == 10 else 'HTS8'


def normalize_hts(hts_code: str) -> str:
    """Normalize HTS code to digits only."""
    return hts_code.replace('.', '').strip()


def run_migration(
    csv_path: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, int]:
    """
    Run the migration from CSV to new schema.

    Args:
        csv_path: Path to section_301_rates_temporal.csv
        dry_run: If True, don't commit changes
        verbose: If True, print detailed progress

    Returns:
        Statistics dict with counts
    """
    from flask import Flask
    from app.web.db import db
    from app.models.section301 import (
        SourceVersion,
        TariffMeasure,
        Section301IngestionRun,
        SourceType,
        Publisher,
        RateStatus,
    )

    # Initialize Flask app for database context
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{project_root}/instance/lanes.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    stats = {
        'rows_processed': 0,
        'rows_added': 0,
        'rows_skipped': 0,
        'rows_error': 0,
        'unique_hts': set(),
        'unique_ch99': set(),
    }

    with app.app_context():
        # Create tables if they don't exist
        db.create_all()

        # Calculate content hash
        content_hash = get_csv_hash(csv_path)

        # Check if this exact file was already migrated
        existing_source = SourceVersion.query.filter_by(
            content_hash=content_hash,
            source_type=SourceType.MANUAL.value
        ).first()

        if existing_source:
            print(f"[SKIP] This CSV file was already migrated (hash: {content_hash[:16]}...)")
            print(f"       Source version ID: {existing_source.id}")
            return stats

        # Create source version for this migration
        source_version = SourceVersion(
            source_type=SourceType.MANUAL.value,
            publisher=Publisher.MANUAL.value,
            document_id=f"migration_csv_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            content_hash=content_hash,
            raw_artifact_path=csv_path,
            title="Section 301 Temporal CSV Migration",
            notes=f"Migrated from {csv_path}",
        )

        if not dry_run:
            db.session.add(source_version)
            db.session.flush()  # Get the ID

        # Create ingestion run record
        ingestion_run = Section301IngestionRun(
            source_type=SourceType.MANUAL.value,
            source_version_id=source_version.id if not dry_run else None,
            triggered_by="migration_script",
            notes=f"Migration from {csv_path}",
        )

        if not dry_run:
            db.session.add(ingestion_run)

        # Read and process CSV
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                stats['rows_processed'] += 1

                try:
                    # Extract fields
                    hts_8digit = row.get('hts_8digit', '').strip()
                    ch99_code = row.get('chapter_99_code', '').strip()
                    rate_str = row.get('duty_rate', '')
                    effective_start_str = row.get('effective_start', '')
                    effective_end_str = row.get('effective_end', '')
                    list_name = row.get('list_name', '')
                    source_doc = row.get('source', '')
                    role = row.get('role', 'impose').strip()

                    # Skip exclusion rows (they go to ExclusionClaim table)
                    if role == 'exclude':
                        stats['rows_skipped'] += 1
                        if verbose:
                            print(f"  [SKIP] {hts_8digit} - exclusion row")
                        continue

                    # Validate required fields
                    if not hts_8digit or not ch99_code:
                        stats['rows_skipped'] += 1
                        if verbose:
                            print(f"  [SKIP] Row {stats['rows_processed']}: missing HTS or CH99")
                        continue

                    # Parse fields
                    hts_normalized = normalize_hts(hts_8digit)
                    hts_type = determine_hts_type(hts_8digit)
                    rate = parse_rate(rate_str)
                    effective_start = parse_date(effective_start_str)
                    effective_end = parse_date(effective_end_str)
                    program = map_list_to_program(list_name)

                    # Require effective_start
                    if not effective_start:
                        stats['rows_skipped'] += 1
                        if verbose:
                            print(f"  [SKIP] {hts_8digit}: no effective_start")
                        continue

                    # Determine rate status
                    rate_status = RateStatus.CONFIRMED.value if rate else RateStatus.PENDING.value

                    # Check for duplicate
                    existing = TariffMeasure.query.filter_by(
                        program=program,
                        ch99_heading=ch99_code,
                        scope_hts_type=hts_type,
                        scope_hts_value=hts_normalized,
                        effective_start=effective_start,
                    ).first()

                    if existing:
                        stats['rows_skipped'] += 1
                        if verbose:
                            print(f"  [SKIP] {hts_8digit}: duplicate")
                        continue

                    # Create tariff measure
                    measure = TariffMeasure(
                        program=program,
                        ch99_heading=ch99_code,
                        scope_hts_type=hts_type,
                        scope_hts_value=hts_normalized,
                        additional_rate=rate,
                        rate_status=rate_status,
                        legal_basis=f"Source: {source_doc}" if source_doc else None,
                        effective_start=effective_start,
                        effective_end=effective_end,
                        list_name=list_name if list_name else None,
                        source_version_id=source_version.id if not dry_run else None,
                    )

                    if not dry_run:
                        db.session.add(measure)

                    stats['rows_added'] += 1
                    stats['unique_hts'].add(hts_normalized)
                    stats['unique_ch99'].add(ch99_code)

                    if verbose and stats['rows_added'] % 1000 == 0:
                        print(f"  [PROGRESS] {stats['rows_added']} rows added...")

                except Exception as e:
                    stats['rows_error'] += 1
                    if verbose:
                        print(f"  [ERROR] Row {stats['rows_processed']}: {e}")

        # Update ingestion run
        if not dry_run:
            ingestion_run.rows_added = stats['rows_added']
            ingestion_run.rows_skipped = stats['rows_skipped']
            ingestion_run.completed_at = datetime.utcnow()
            ingestion_run.status = 'success' if stats['rows_error'] == 0 else 'partial'

            # Commit all changes
            db.session.commit()
            print(f"\n[COMMITTED] Migration completed successfully.")
        else:
            print(f"\n[DRY RUN] No changes committed.")

    # Convert sets to counts for return
    stats['unique_hts_count'] = len(stats['unique_hts'])
    stats['unique_ch99_count'] = len(stats['unique_ch99'])
    del stats['unique_hts']
    del stats['unique_ch99']

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Section 301 data to new schema'
    )
    parser.add_argument(
        '--csv-path',
        default=str(project_root / 'data' / 'section_301_rates_temporal.csv'),
        help='Path to section_301_rates_temporal.csv'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed progress'
    )

    args = parser.parse_args()

    # Verify CSV exists
    if not os.path.exists(args.csv_path):
        print(f"[ERROR] CSV file not found: {args.csv_path}")
        sys.exit(1)

    print(f"=" * 60)
    print(f"Section 301 Data Migration")
    print(f"=" * 60)
    print(f"CSV Path: {args.csv_path}")
    print(f"Dry Run: {args.dry_run}")
    print(f"Verbose: {args.verbose}")
    print(f"-" * 60)

    stats = run_migration(
        csv_path=args.csv_path,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print(f"\n{'=' * 60}")
    print(f"Migration Statistics")
    print(f"{'=' * 60}")
    print(f"Rows Processed: {stats['rows_processed']}")
    print(f"Rows Added:     {stats['rows_added']}")
    print(f"Rows Skipped:   {stats['rows_skipped']}")
    print(f"Rows Error:     {stats['rows_error']}")
    print(f"Unique HTS:     {stats['unique_hts_count']}")
    print(f"Unique CH99:    {stats['unique_ch99_count']}")


if __name__ == '__main__':
    main()
