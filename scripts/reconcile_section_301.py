#!/usr/bin/env python3
"""
Reconcile section_301_rates between PostgreSQL and SQLite.

This script fixes the 26-row discrepancy where PostgreSQL has more rows than SQLite.
Strategy: PostgreSQL is the source of truth (has more complete data).
Pull missing rows from PostgreSQL -> SQLite.

Usage:
    python scripts/reconcile_section_301.py [--dry-run]
"""

import os
import sys
import argparse
import sqlite3
import logging
from typing import Set, Tuple, Dict, List, Any

from sqlalchemy import create_engine, text

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Business key columns for section_301_rates
BUSINESS_KEY_COLS = ['hts_8digit', 'chapter_99_code', 'effective_start']

# All columns to sync (excluding auto-generated ones)
SYNC_COLUMNS = [
    'id', 'hts_8digit', 'hts_10digit', 'chapter_99_code', 'duty_rate',
    'effective_start', 'effective_end', 'list_name', 'sector', 'product_group',
    'description', 'source_doc', 'source_doc_id', 'supersedes_id',
    'superseded_by_id', 'role', 'created_by'
]


def get_pg_connection():
    """Get PostgreSQL connection from environment."""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL environment variable not set")
    return create_engine(db_url)


def get_sqlite_connection():
    """Get SQLite connection."""
    sqlite_path = os.environ.get('SQLITE_PATH', 'instance/sqlite.db')
    if not os.path.exists(sqlite_path):
        # Try alternative paths
        for alt_path in ['instance/lanes.db', 'lanes.db']:
            if os.path.exists(alt_path):
                sqlite_path = alt_path
                break
    logger.info(f"Using SQLite database: {sqlite_path}")
    return sqlite3.connect(sqlite_path)


def get_business_keys(conn, is_pg: bool = True) -> Set[Tuple]:
    """Get all business keys from a database."""
    keys = set()

    if is_pg:
        with conn.connect() as pg_conn:
            result = pg_conn.execute(text("""
                SELECT hts_8digit, chapter_99_code, effective_start
                FROM section_301_rates
            """))
            for row in result.fetchall():
                # Convert effective_start to string for consistent comparison
                eff_start = str(row[2]) if row[2] else None
                keys.add((row[0], row[1], eff_start))
    else:
        cursor = conn.execute("""
            SELECT hts_8digit, chapter_99_code, effective_start
            FROM section_301_rates
        """)
        for row in cursor.fetchall():
            eff_start = str(row[2]) if row[2] else None
            keys.add((row[0], row[1], eff_start))

    return keys


def get_row_count(conn, is_pg: bool = True) -> int:
    """Get row count from a database."""
    if is_pg:
        with conn.connect() as pg_conn:
            result = pg_conn.execute(text("SELECT COUNT(*) FROM section_301_rates"))
            return result.fetchone()[0]
    else:
        cursor = conn.execute("SELECT COUNT(*) FROM section_301_rates")
        return cursor.fetchone()[0]


def fetch_rows_by_keys(pg_engine, keys: Set[Tuple]) -> List[Dict]:
    """Fetch full rows from PostgreSQL by business keys."""
    if not keys:
        return []

    rows = []
    cols_str = ', '.join(SYNC_COLUMNS)

    with pg_engine.connect() as conn:
        for hts_8digit, chapter_99_code, effective_start in keys:
            query = text(f"""
                SELECT {cols_str}
                FROM section_301_rates
                WHERE hts_8digit = :hts_8digit
                AND chapter_99_code = :chapter_99_code
                AND (effective_start = :effective_start
                     OR (effective_start IS NULL AND :effective_start IS NULL))
            """)
            result = conn.execute(query, {
                'hts_8digit': hts_8digit,
                'chapter_99_code': chapter_99_code,
                'effective_start': effective_start
            })
            row = result.fetchone()
            if row:
                rows.append(dict(zip(SYNC_COLUMNS, row)))

    return rows


def convert_value(val):
    """Convert value to SQLite-compatible type."""
    if val is None:
        return None
    # Handle Decimal types
    from decimal import Decimal
    if isinstance(val, Decimal):
        return float(val)
    # Handle date/datetime types
    from datetime import date, datetime
    if isinstance(val, (date, datetime)):
        return str(val)
    return val


def insert_rows_to_sqlite(sqlite_conn, rows: List[Dict], dry_run: bool = False) -> int:
    """Insert rows into SQLite."""
    if not rows:
        return 0

    inserted = 0
    cursor = sqlite_conn.cursor()

    # Get existing max id to avoid conflicts
    cursor.execute("SELECT MAX(id) FROM section_301_rates")
    max_id = cursor.fetchone()[0] or 0

    for row in rows:
        # Generate new id to avoid conflicts
        max_id += 1
        row['id'] = max_id

        cols = [c for c in SYNC_COLUMNS if c in row]
        placeholders = ', '.join(['?' for _ in cols])
        cols_str = ', '.join(cols)
        values = [convert_value(row.get(c)) for c in cols]

        if dry_run:
            logger.info(f"  [DRY-RUN] Would insert: HTS={row['hts_8digit']}, "
                       f"CH99={row['chapter_99_code']}, start={row['effective_start']}")
        else:
            try:
                cursor.execute(
                    f"INSERT INTO section_301_rates ({cols_str}) VALUES ({placeholders})",
                    values
                )
                inserted += 1
            except sqlite3.IntegrityError as e:
                logger.warning(f"  Skipping duplicate: {row['hts_8digit']} - {e}")

    if not dry_run:
        sqlite_conn.commit()

    return inserted


def reconcile(dry_run: bool = False):
    """Main reconciliation function."""
    logger.info("=" * 60)
    logger.info("SECTION 301 DATA RECONCILIATION")
    logger.info("=" * 60)

    # Connect to databases
    pg_engine = get_pg_connection()
    sqlite_conn = get_sqlite_connection()

    try:
        # Get current counts
        pg_count = get_row_count(pg_engine, is_pg=True)
        sqlite_count = get_row_count(sqlite_conn, is_pg=False)

        logger.info(f"\nCurrent row counts:")
        logger.info(f"  PostgreSQL: {pg_count}")
        logger.info(f"  SQLite:     {sqlite_count}")
        logger.info(f"  Difference: {pg_count - sqlite_count}")

        if pg_count == sqlite_count:
            logger.info("\nDatabases are already in sync!")
            return

        # Get business keys from both databases
        logger.info("\nFetching business keys...")
        pg_keys = get_business_keys(pg_engine, is_pg=True)
        sqlite_keys = get_business_keys(sqlite_conn, is_pg=False)

        logger.info(f"  PostgreSQL keys: {len(pg_keys)}")
        logger.info(f"  SQLite keys:     {len(sqlite_keys)}")

        # Find missing rows
        missing_in_sqlite = pg_keys - sqlite_keys
        missing_in_pg = sqlite_keys - pg_keys

        logger.info(f"\nDiscrepancy analysis:")
        logger.info(f"  Rows in PG but not SQLite: {len(missing_in_sqlite)}")
        logger.info(f"  Rows in SQLite but not PG: {len(missing_in_pg)}")

        if missing_in_sqlite:
            logger.info(f"\nFetching {len(missing_in_sqlite)} missing rows from PostgreSQL...")
            rows_to_insert = fetch_rows_by_keys(pg_engine, missing_in_sqlite)

            logger.info(f"Inserting {len(rows_to_insert)} rows into SQLite...")
            inserted = insert_rows_to_sqlite(sqlite_conn, rows_to_insert, dry_run=dry_run)

            if dry_run:
                logger.info(f"\n[DRY-RUN] Would have inserted {len(rows_to_insert)} rows")
            else:
                logger.info(f"\nInserted {inserted} rows into SQLite")

        if missing_in_pg:
            logger.warning(f"\nWARNING: {len(missing_in_pg)} rows exist in SQLite but not PostgreSQL")
            logger.warning("These may need manual review:")
            for key in list(missing_in_pg)[:5]:
                logger.warning(f"  HTS={key[0]}, CH99={key[1]}, start={key[2]}")
            if len(missing_in_pg) > 5:
                logger.warning(f"  ... and {len(missing_in_pg) - 5} more")

        # Verify final counts
        if not dry_run:
            final_sqlite_count = get_row_count(sqlite_conn, is_pg=False)
            logger.info(f"\nFinal row counts:")
            logger.info(f"  PostgreSQL: {pg_count}")
            logger.info(f"  SQLite:     {final_sqlite_count}")

            if pg_count == final_sqlite_count:
                logger.info("\n SUCCESS: Databases are now in sync!")
            else:
                logger.warning(f"\n WARNING: Still {pg_count - final_sqlite_count} rows difference")

    finally:
        sqlite_conn.close()
        pg_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description='Reconcile section_301_rates between PostgreSQL and SQLite')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()

    reconcile(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
