"""
Auto-sync SQLite changes to PostgreSQL.

Called after pipeline processing to replicate local changes to production.
Handles FK ordering, NUL character cleaning, and schema differences.
"""

import os
import sqlite3
import logging
from typing import Optional, List, Tuple, Set

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Tables to sync in FK dependency order (parents first)
SYNC_TABLES = [
    'official_documents',  # Parent - sync first (no FK dependencies)
    'ingest_jobs',         # References documents via document_id
    'candidate_changes',   # References jobs via job_id
    'section_301_rates',   # No FK to above tables
    'section_232_rates',   # No FK to above tables
    'ieepa_rates',         # No FK to above tables
    'tariff_audit_log',    # For audit trail
    'evidence_packets',    # References documents
]

# Columns to exclude per table (schema differences or local-only)
EXCLUDE_COLUMNS = {
    'official_documents': ['raw_bytes', 'storage_uri', 'created_at', 'updated_at'],
    'ingest_jobs': ['created_at', 'updated_at'],
    'candidate_changes': ['created_at', 'updated_at'],
    'document_chunks': ['created_at'],
    'evidence_packets': ['created_at', 'updated_at'],
    'tariff_audit_log': ['created_at'],
}


def is_sync_enabled() -> bool:
    """Check if auto-sync is enabled."""
    if not os.environ.get('AUTO_SYNC_ENABLED', '').lower() in ('true', '1', 'yes'):
        return False
    if not os.environ.get('DATABASE_URL_REMOTE'):
        return False
    return True


def get_sqlite_path() -> str:
    """Get SQLite database path from DATABASE_URL or default."""
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///instance/sqlite.db')
    if db_url.startswith('sqlite:///'):
        return db_url.replace('sqlite:///', '')
    # If DATABASE_URL is PostgreSQL, use default SQLite path
    return 'instance/sqlite.db'


def clean_text(val):
    """Remove NUL characters that PostgreSQL rejects."""
    if isinstance(val, str):
        return val.replace('\x00', '')
    return val


def get_common_columns(
    table_name: str,
    sqlite_conn: sqlite3.Connection,
    pg_engine: Engine,
    exclude_cols: Optional[List[str]] = None
) -> List[str]:
    """Get columns that exist in both SQLite and PostgreSQL."""
    exclude_cols = exclude_cols or []

    # Get PostgreSQL columns
    with pg_engine.connect() as pg_conn:
        result = pg_conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = :table
        """), {'table': table_name})
        pg_cols = set(row[0] for row in result.fetchall())

    # Get SQLite columns
    cursor = sqlite_conn.execute(f'PRAGMA table_info({table_name})')
    sqlite_cols = [row[1] for row in cursor.fetchall()]

    # Return common columns (excluding specified)
    return [c for c in sqlite_cols if c in pg_cols and c not in exclude_cols]


def sync_table(
    table_name: str,
    sqlite_conn: sqlite3.Connection,
    pg_engine: Engine,
    exclude_cols: Optional[List[str]] = None
) -> Tuple[int, int]:
    """
    Sync a single table from SQLite to PostgreSQL.

    Args:
        table_name: Name of table to sync
        sqlite_conn: SQLite connection
        pg_engine: PostgreSQL engine
        exclude_cols: Columns to exclude from sync

    Returns:
        Tuple of (added_count, error_count)
    """
    exclude_cols = exclude_cols or EXCLUDE_COLUMNS.get(table_name, [])

    common_cols = get_common_columns(table_name, sqlite_conn, pg_engine, exclude_cols)

    if not common_cols:
        logger.warning(f"No common columns found for {table_name}")
        return 0, 0

    # Check if 'id' column exists
    if 'id' not in common_cols:
        logger.warning(f"Table {table_name} has no 'id' column, skipping")
        return 0, 0

    with pg_engine.connect() as pg_conn:
        # Get existing IDs in PostgreSQL
        try:
            existing_ids = set(
                row[0] for row in pg_conn.execute(
                    text(f'SELECT id FROM {table_name}')
                ).fetchall()
            )
        except Exception as e:
            logger.error(f"Error getting existing IDs from {table_name}: {e}")
            return 0, 0

        # Get all rows from SQLite
        cols_str = ', '.join(common_cols)
        cursor = sqlite_conn.execute(f'SELECT {cols_str} FROM {table_name}')
        rows = cursor.fetchall()

        new_count = 0
        error_count = 0

        for row in rows:
            # Create dict with cleaned values
            row_dict = {col: clean_text(val) for col, val in zip(common_cols, row)}

            # Skip if already exists
            if row_dict['id'] in existing_ids:
                continue

            placeholders = ', '.join([f':{c}' for c in common_cols])
            try:
                pg_conn.execute(
                    text(f'INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})'),
                    row_dict
                )
                pg_conn.commit()  # Commit per row to handle FK failures gracefully
                new_count += 1
            except Exception as e:
                error_count += 1
                pg_conn.rollback()
                if 'duplicate' not in str(e).lower():
                    if error_count <= 5:  # Log first 5 errors
                        logger.warning(f"Error syncing {table_name} row: {str(e)[:100]}")

    return new_count, error_count


def sync_to_postgresql(tables: Optional[List[str]] = None) -> dict:
    """
    Sync SQLite data to PostgreSQL.

    Args:
        tables: Optional list of specific tables to sync.
                If None, syncs all tables in SYNC_TABLES.

    Returns:
        Dict with sync results per table
    """
    if not is_sync_enabled():
        logger.debug("Auto-sync disabled or DATABASE_URL_REMOTE not set")
        return {'enabled': False}

    remote_url = os.environ.get('DATABASE_URL_REMOTE')
    sqlite_path = get_sqlite_path()

    logger.info(f"Starting sync: SQLite ({sqlite_path}) → PostgreSQL")

    # Connect to both databases
    try:
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        pg_engine = create_engine(remote_url)
    except Exception as e:
        logger.error(f"Failed to connect to databases: {e}")
        return {'error': str(e)}

    results = {'enabled': True, 'tables': {}}
    tables_to_sync = tables or SYNC_TABLES

    try:
        for table_name in tables_to_sync:
            try:
                added, errors = sync_table(table_name, sqlite_conn, pg_engine)
                results['tables'][table_name] = {
                    'added': added,
                    'errors': errors
                }
                if added > 0:
                    logger.info(f"Synced {table_name}: +{added} rows")
                elif errors > 0:
                    logger.warning(f"Sync {table_name}: {errors} errors")
            except Exception as e:
                logger.error(f"Failed to sync {table_name}: {e}")
                results['tables'][table_name] = {'error': str(e)}
    finally:
        sqlite_conn.close()
        pg_engine.dispose()

    total_added = sum(
        t.get('added', 0) for t in results['tables'].values()
        if isinstance(t, dict) and 'added' in t
    )
    total_errors = sum(
        t.get('errors', 0) for t in results['tables'].values()
        if isinstance(t, dict) and 'errors' in t
    )

    results['total_added'] = total_added
    results['total_errors'] = total_errors

    logger.info(f"Sync complete: {total_added} added, {total_errors} errors")

    return results


def sync_document_pipeline_data() -> dict:
    """
    Sync only document pipeline tables (for post-ingest sync).

    This is a lighter sync that focuses on:
    - official_documents
    - ingest_jobs
    - candidate_changes
    """
    return sync_to_postgresql(tables=[
        'official_documents',
        'ingest_jobs',
        'candidate_changes'
    ])


def sync_tariff_rates() -> dict:
    """
    Sync only tariff rate tables.

    For when new rates are extracted and committed.
    """
    return sync_to_postgresql(tables=[
        'section_301_rates',
        'section_232_rates',
        'ieepa_rates'
    ])
