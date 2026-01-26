"""
Auto-sync SQLite changes to PostgreSQL.

Called after pipeline processing to replicate local changes to production.
Handles FK ordering, NUL character cleaning, and schema differences.
"""

import os
import sqlite3
import logging
import csv
import hashlib
import json
from datetime import datetime
from typing import Optional, List, Tuple, Set, Dict, Any

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


# ============================================================================
# REVERSE SYNC: PostgreSQL → SQLite
# ============================================================================

# Business key columns for tables that need special handling
BUSINESS_KEY_COLUMNS = {
    'section_301_rates': ['hts_8digit', 'chapter_99_code', 'effective_start'],
    'section_232_rates': ['hts_8digit', 'chapter_99_code', 'effective_start'],
    'ieepa_rates': ['chapter_99_code', 'country_code', 'effective_start'],
}


def get_business_keys_sqlite(
    sqlite_conn: sqlite3.Connection,
    table_name: str,
    key_cols: List[str]
) -> Set[Tuple]:
    """Get business keys from SQLite table."""
    cols_str = ', '.join(key_cols)
    cursor = sqlite_conn.execute(f'SELECT {cols_str} FROM {table_name}')
    return set(tuple(str(v) if v is not None else None for v in row) for row in cursor.fetchall())


def get_business_keys_pg(
    pg_engine: Engine,
    table_name: str,
    key_cols: List[str]
) -> Set[Tuple]:
    """Get business keys from PostgreSQL table."""
    cols_str = ', '.join(key_cols)
    with pg_engine.connect() as conn:
        result = conn.execute(text(f'SELECT {cols_str} FROM {table_name}'))
        return set(tuple(str(v) if v is not None else None for v in row) for row in result.fetchall())


def sync_from_postgresql(tables: Optional[List[str]] = None) -> dict:
    """
    Reverse sync: Pull data from PostgreSQL to SQLite.

    Uses business-key deduplication for tariff tables to handle
    the unique constraint properly.

    Args:
        tables: Optional list of specific tables to sync.
                If None, syncs all tables in SYNC_TABLES.

    Returns:
        Dict with sync results per table
    """
    remote_url = os.environ.get('DATABASE_URL_REMOTE') or os.environ.get('DATABASE_URL')
    if not remote_url:
        logger.warning("No PostgreSQL URL found (DATABASE_URL_REMOTE or DATABASE_URL)")
        return {'error': 'No PostgreSQL URL configured'}

    sqlite_path = get_sqlite_path()

    logger.info(f"Starting reverse sync: PostgreSQL → SQLite ({sqlite_path})")

    try:
        pg_engine = create_engine(remote_url)
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
    except Exception as e:
        logger.error(f"Failed to connect to databases: {e}")
        return {'error': str(e)}

    results = {'tables': {}}
    tables_to_sync = tables or SYNC_TABLES

    try:
        for table_name in tables_to_sync:
            try:
                added, errors = sync_table_from_pg(table_name, pg_engine, sqlite_conn)
                results['tables'][table_name] = {
                    'added': added,
                    'errors': errors
                }
                if added > 0:
                    logger.info(f"Reverse synced {table_name}: +{added} rows")
                elif errors > 0:
                    logger.warning(f"Reverse sync {table_name}: {errors} errors")
            except Exception as e:
                logger.error(f"Failed to reverse sync {table_name}: {e}")
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

    logger.info(f"Reverse sync complete: {total_added} added, {total_errors} errors")

    return results


def sync_table_from_pg(
    table_name: str,
    pg_engine: Engine,
    sqlite_conn: sqlite3.Connection
) -> Tuple[int, int]:
    """
    Sync a single table from PostgreSQL to SQLite.

    Uses business-key deduplication for tariff tables.
    """
    # Get common columns
    exclude_cols = EXCLUDE_COLUMNS.get(table_name, [])
    common_cols = get_common_columns(table_name, sqlite_conn, pg_engine, exclude_cols)

    if not common_cols:
        logger.warning(f"No common columns found for {table_name}")
        return 0, 0

    # Determine deduplication strategy
    use_business_key = table_name in BUSINESS_KEY_COLUMNS
    key_cols = BUSINESS_KEY_COLUMNS.get(table_name, ['id'])

    if use_business_key:
        existing_keys = get_business_keys_sqlite(sqlite_conn, table_name, key_cols)
    else:
        cursor = sqlite_conn.execute(f'SELECT id FROM {table_name}')
        existing_keys = set(row[0] for row in cursor.fetchall())

    # Fetch rows from PostgreSQL
    cols_str = ', '.join(common_cols)
    with pg_engine.connect() as pg_conn:
        result = pg_conn.execute(text(f'SELECT {cols_str} FROM {table_name}'))
        pg_rows = result.fetchall()

    new_count = 0
    error_count = 0

    # Get max id in SQLite for new rows
    cursor = sqlite_conn.execute(f'SELECT MAX(id) FROM {table_name}')
    max_id = cursor.fetchone()[0] or 0

    for row in pg_rows:
        row_dict = {col: clean_text(val) for col, val in zip(common_cols, row)}

        # Check if row exists
        if use_business_key:
            key = tuple(str(row_dict.get(k)) if row_dict.get(k) is not None else None for k in key_cols)
            if key in existing_keys:
                continue
        else:
            if row_dict.get('id') in existing_keys:
                continue

        # Generate new id to avoid conflicts
        max_id += 1
        row_dict['id'] = max_id

        placeholders = ', '.join(['?' for _ in common_cols])
        values = [row_dict.get(c) for c in common_cols]

        try:
            sqlite_conn.execute(
                f'INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})',
                values
            )
            sqlite_conn.commit()
            new_count += 1
            if use_business_key:
                existing_keys.add(key)
        except Exception as e:
            error_count += 1
            sqlite_conn.rollback()
            if error_count <= 5:
                logger.warning(f"Error inserting to {table_name}: {str(e)[:100]}")

    return new_count, error_count


# ============================================================================
# CSV EXPORT
# ============================================================================


def export_to_csv(
    table_name: str,
    output_dir: str = 'data/current',
    source: str = 'postgresql'
) -> dict:
    """
    Export a table to CSV for archival/backup.

    Args:
        table_name: Name of table to export
        output_dir: Directory to write CSV files
        source: 'postgresql' or 'sqlite'

    Returns:
        Dict with export results including path and checksum
    """
    os.makedirs(output_dir, exist_ok=True)

    # Connect to source database
    if source == 'postgresql':
        db_url = os.environ.get('DATABASE_URL_REMOTE') or os.environ.get('DATABASE_URL')
        if not db_url:
            return {'error': 'No PostgreSQL URL configured'}
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT * FROM {table_name}'))
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        engine.dispose()
    else:
        sqlite_path = get_sqlite_path()
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(f'SELECT * FROM {table_name}')
        columns = [d[0] for d in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()

    if not rows:
        return {'error': f'No rows found in {table_name}'}

    # Write CSV
    output_path = os.path.join(output_dir, f'{table_name}.csv')
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            # Convert any non-serializable types
            clean_row = {}
            for k, v in row.items():
                if v is None:
                    clean_row[k] = ''
                elif isinstance(v, (datetime,)):
                    clean_row[k] = v.isoformat()
                else:
                    clean_row[k] = str(v) if not isinstance(v, (str, int, float)) else v
            writer.writerow(clean_row)

    # Calculate checksum
    with open(output_path, 'rb') as f:
        content_hash = hashlib.sha256(f.read()).hexdigest()

    result = {
        'table': table_name,
        'path': output_path,
        'row_count': len(rows),
        'columns': list(columns),
        'sha256': content_hash,
        'exported_at': datetime.utcnow().isoformat(),
        'source': source
    }

    logger.info(f"Exported {table_name}: {len(rows)} rows to {output_path}")

    return result


def update_manifest(
    export_results: List[dict],
    output_dir: str = 'data/current'
) -> str:
    """
    Update or create manifest.json with export metadata.

    Args:
        export_results: List of export result dicts from export_to_csv()
        output_dir: Directory containing the CSV files

    Returns:
        Path to manifest.json
    """
    manifest_path = os.path.join(output_dir, 'manifest.json')

    manifest = {
        'generated_at': datetime.utcnow().isoformat(),
        'source_version': f"sync_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        'files': {}
    }

    for result in export_results:
        if 'error' not in result:
            filename = os.path.basename(result['path'])
            manifest['files'][filename] = {
                'row_count': result['row_count'],
                'sha256': result['sha256'],
                'columns': result['columns'],
                'exported_at': result['exported_at'],
                'source': result.get('source', 'postgresql')
            }

    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Updated manifest: {manifest_path}")

    return manifest_path


def export_all_tariff_tables(output_dir: str = 'data/current') -> dict:
    """
    Export all tariff-related tables to CSV with manifest.

    Returns:
        Dict with export results and manifest path
    """
    tables = ['section_301_rates', 'section_232_rates', 'ieepa_rates']
    results = []

    for table in tables:
        try:
            result = export_to_csv(table, output_dir)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to export {table}: {e}")
            results.append({'table': table, 'error': str(e)})

    manifest_path = update_manifest(results, output_dir)

    return {
        'exports': results,
        'manifest': manifest_path
    }
