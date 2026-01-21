#!/usr/bin/env python
"""
Migrate pipeline data from local SQLite to production PostgreSQL.

Usage:
    # Dry run (preview only)
    DATABASE_URL="postgresql://..." python scripts/migrate_sqlite_to_postgres.py --dry-run

    # Execute migration
    DATABASE_URL="postgresql://..." python scripts/migrate_sqlite_to_postgres.py

    # Migrate specific tables only
    DATABASE_URL="postgresql://..." python scripts/migrate_sqlite_to_postgres.py --tables official_documents,ingest_jobs

Tables migrated (in FK order):
    1. official_documents (316 rows)
    2. document_chunks (3674 rows)
    3. ingest_jobs (269 rows)
    4. candidate_changes (113 rows)
"""

import os
import sys
import sqlite3
import argparse
import json
from datetime import datetime, date
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras

# Tables to migrate in FK-safe order
PIPELINE_TABLES = [
    'official_documents',
    'document_chunks',
    'ingest_jobs',
    'candidate_changes',
]

# SQLite database path
SQLITE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'instance', 'sqlite.db'
)


def get_sqlite_connection():
    """Get SQLite connection with row factory."""
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_connection(db_url):
    """Get PostgreSQL connection from DATABASE_URL."""
    # Parse the URL
    result = urlparse(db_url)
    return psycopg2.connect(
        host=result.hostname,
        port=result.port or 5432,
        user=result.username,
        password=result.password,
        database=result.path[1:],  # Remove leading /
    )


def export_table(sqlite_conn, table_name, limit=None):
    """Export table rows from SQLite."""
    cursor = sqlite_conn.cursor()
    query = f"SELECT * FROM {table_name}"
    if limit:
        query += f" LIMIT {limit}"

    try:
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return columns, [dict(row) for row in rows]
    except sqlite3.OperationalError as e:
        print(f"  Warning: Could not export {table_name}: {e}")
        return [], []


def convert_value(value, column_name, skip_blobs=False):
    """Convert SQLite value to PostgreSQL compatible value."""
    if value is None:
        return None

    # Handle JSON columns
    if column_name in ('metadata_json', 'validation_errors'):
        if isinstance(value, str):
            try:
                return json.dumps(json.loads(value))  # Validate and normalize
            except:
                return value
        return json.dumps(value) if value else None

    # Handle BLOB (raw_bytes) - skip if too large or skip_blobs enabled
    if column_name == 'raw_bytes':
        if skip_blobs:
            return None  # Skip blob data
        if isinstance(value, bytes):
            return psycopg2.Binary(value)

    # Handle dates stored as strings
    if column_name.endswith('_date') or column_name.endswith('_at'):
        if isinstance(value, str):
            # Try parsing common date formats
            for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return value

    return value


def check_exists(pg_cursor, table_name, row_id):
    """Check if row already exists in PostgreSQL."""
    pg_cursor.execute(
        f"SELECT 1 FROM {table_name} WHERE id = %s",
        (row_id,)
    )
    return pg_cursor.fetchone() is not None


def insert_row(pg_cursor, table_name, columns, row_dict, dry_run=False, skip_blobs=False):
    """Insert single row into PostgreSQL."""
    # Convert values
    converted = {}
    for col in columns:
        if col in row_dict:
            converted[col] = convert_value(row_dict[col], col, skip_blobs=skip_blobs)

    if dry_run:
        return True

    # Build INSERT statement
    col_names = ', '.join(converted.keys())
    placeholders = ', '.join(['%s' for _ in converted.keys()])
    values = list(converted.values())

    try:
        pg_cursor.execute(
            f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})",
            values
        )
        return True
    except Exception as e:
        # Check if it's a duplicate key error
        if 'duplicate key' in str(e).lower() or 'unique constraint' in str(e).lower():
            return False  # Skip duplicates silently
        raise


def migrate_table(sqlite_conn, pg_conn, table_name, dry_run=False, skip_blobs=False):
    """Migrate a single table from SQLite to PostgreSQL."""
    print(f"\n{'='*60}")
    print(f"Migrating: {table_name}")
    if skip_blobs and table_name == 'official_documents':
        print("  (skipping raw_bytes blobs - metadata only)")
    print('='*60)

    pg_cursor = pg_conn.cursor()

    # Export from SQLite
    columns, rows = export_table(sqlite_conn, table_name)
    if not rows:
        print(f"  No rows found in SQLite")
        return 0, 0

    print(f"  SQLite rows: {len(rows)}")

    # Count existing in PostgreSQL
    pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    pg_count = pg_cursor.fetchone()[0]
    print(f"  PostgreSQL rows (before): {pg_count}")

    # Insert rows
    inserted = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(rows):
        row_id = row.get('id')

        # Check if exists
        if row_id and check_exists(pg_cursor, table_name, row_id):
            skipped += 1
            continue

        try:
            if insert_row(pg_cursor, table_name, columns, row, dry_run, skip_blobs=skip_blobs):
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            if errors <= 3:  # Only show first 3 errors
                print(f"  Error inserting row {row_id}: {e}")
            pg_conn.rollback()  # Rollback the failed transaction
            pg_cursor = pg_conn.cursor()  # Get new cursor

        # Progress indicator
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(rows)} rows processed...")

    if not dry_run:
        pg_conn.commit()

    # Final count
    if not dry_run:
        pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        pg_count_after = pg_cursor.fetchone()[0]
        print(f"  PostgreSQL rows (after): {pg_count_after}")

    print(f"  Inserted: {inserted}, Skipped (existing): {skipped}, Errors: {errors}")
    return inserted, skipped


def main():
    parser = argparse.ArgumentParser(description='Migrate SQLite to PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', help='Preview without inserting')
    parser.add_argument('--tables', type=str, help='Comma-separated table names to migrate')
    parser.add_argument('--skip-blobs', action='store_true', help='Skip raw_bytes blobs (metadata only)')
    args = parser.parse_args()

    # Check DATABASE_URL
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        print("Usage: DATABASE_URL='postgresql://...' python scripts/migrate_sqlite_to_postgres.py")
        sys.exit(1)

    if 'sqlite' in db_url.lower():
        print("ERROR: DATABASE_URL points to SQLite, not PostgreSQL")
        print("Set DATABASE_URL to your Railway PostgreSQL connection string")
        sys.exit(1)

    # Check SQLite exists
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite database not found at {SQLITE_PATH}")
        sys.exit(1)

    # Determine tables to migrate
    if args.tables:
        tables = [t.strip() for t in args.tables.split(',')]
    else:
        tables = PIPELINE_TABLES

    print("="*60)
    print("SQLite → PostgreSQL Migration")
    print("="*60)
    print(f"Mode: {'DRY RUN (preview only)' if args.dry_run else 'EXECUTE'}")
    print(f"Skip blobs: {args.skip_blobs}")
    print(f"SQLite: {SQLITE_PATH}")
    print(f"PostgreSQL: {db_url[:50]}...")
    print(f"Tables: {', '.join(tables)}")

    # Get connections directly (no Flask app context)
    sqlite_conn = get_sqlite_connection()
    pg_conn = get_pg_connection(db_url)

    # Summary
    total_inserted = 0
    total_skipped = 0

    for table in tables:
        if table not in PIPELINE_TABLES:
            print(f"\nWarning: {table} not in PIPELINE_TABLES, skipping")
            continue

        inserted, skipped = migrate_table(
            sqlite_conn,
            pg_conn,
            table,
            dry_run=args.dry_run,
            skip_blobs=args.skip_blobs
        )
        total_inserted += inserted
        total_skipped += skipped

    sqlite_conn.close()
    pg_conn.close()

    print("\n" + "="*60)
    print("MIGRATION SUMMARY")
    print("="*60)
    print(f"Total inserted: {total_inserted}")
    print(f"Total skipped: {total_skipped}")

    if args.dry_run:
        print("\nThis was a DRY RUN - no data was actually inserted.")
        print("Run without --dry-run to execute the migration.")


if __name__ == '__main__':
    main()
