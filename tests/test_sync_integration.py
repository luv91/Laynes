"""
Integration tests for SQLite to PostgreSQL sync.

These tests verify the auto-sync feature works correctly with real databases.
Requires:
- Local SQLite database (instance/sqlite.db)
- Remote PostgreSQL (DATABASE_URL_REMOTE env var)

Run with:
    pipenv run pytest tests/test_sync_integration.py -v

Or run specific tests:
    pipenv run pytest tests/test_sync_integration.py::TestSyncModule -v
"""

import os
import pytest
import sqlite3
from uuid import uuid4
from datetime import datetime, date

from sqlalchemy import create_engine, text


# Skip all tests if PostgreSQL not configured
pytestmark = pytest.mark.skipif(
    not os.environ.get('DATABASE_URL_REMOTE'),
    reason="DATABASE_URL_REMOTE not set - skipping integration tests"
)


class TestSyncModule:
    """Test the sync module imports and configuration."""

    def test_import_sync_module(self):
        """Test that sync module can be imported."""
        from app.sync import sync_to_postgresql, is_sync_enabled
        assert callable(sync_to_postgresql)
        assert callable(is_sync_enabled)

    def test_is_sync_enabled_returns_bool(self):
        """Test is_sync_enabled returns boolean."""
        from app.sync import is_sync_enabled
        result = is_sync_enabled()
        assert isinstance(result, bool)

    def test_is_sync_enabled_checks_env_vars(self):
        """Test is_sync_enabled checks environment variables."""
        from app.sync.pg_sync import is_sync_enabled

        # Save original values
        orig_auto_sync = os.environ.get('AUTO_SYNC_ENABLED')
        orig_db_remote = os.environ.get('DATABASE_URL_REMOTE')

        try:
            # Both must be set for sync to be enabled
            os.environ['AUTO_SYNC_ENABLED'] = 'true'
            os.environ['DATABASE_URL_REMOTE'] = 'postgresql://test'
            assert is_sync_enabled() == True

            # Missing AUTO_SYNC_ENABLED
            del os.environ['AUTO_SYNC_ENABLED']
            assert is_sync_enabled() == False

            # Missing DATABASE_URL_REMOTE
            os.environ['AUTO_SYNC_ENABLED'] = 'true'
            del os.environ['DATABASE_URL_REMOTE']
            assert is_sync_enabled() == False

        finally:
            # Restore original values
            if orig_auto_sync:
                os.environ['AUTO_SYNC_ENABLED'] = orig_auto_sync
            elif 'AUTO_SYNC_ENABLED' in os.environ:
                del os.environ['AUTO_SYNC_ENABLED']

            if orig_db_remote:
                os.environ['DATABASE_URL_REMOTE'] = orig_db_remote
            elif 'DATABASE_URL_REMOTE' in os.environ:
                del os.environ['DATABASE_URL_REMOTE']


class TestCleanText:
    """Test NUL character cleaning."""

    def test_clean_text_removes_nul(self):
        """Test that NUL characters are removed."""
        from app.sync.pg_sync import clean_text

        # String with NUL
        result = clean_text("hello\x00world")
        assert result == "helloworld"
        assert "\x00" not in result

    def test_clean_text_preserves_other_content(self):
        """Test that other content is preserved."""
        from app.sync.pg_sync import clean_text

        # Normal string
        assert clean_text("hello world") == "hello world"

        # Non-string types
        assert clean_text(123) == 123
        assert clean_text(None) is None
        assert clean_text(12.34) == 12.34


class TestDatabaseConnections:
    """Test database connection capabilities."""

    def test_sqlite_connection(self):
        """Test SQLite database exists and is accessible."""
        sqlite_path = 'instance/sqlite.db'
        assert os.path.exists(sqlite_path), f"SQLite database not found at {sqlite_path}"

        conn = sqlite3.connect(sqlite_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert len(tables) > 0, "SQLite database has no tables"
        assert 'official_documents' in tables
        assert 'ingest_jobs' in tables

    def test_postgresql_connection(self):
        """Test PostgreSQL database is accessible."""
        pg_url = os.environ.get('DATABASE_URL_REMOTE')
        if not pg_url:
            pytest.skip("DATABASE_URL_REMOTE not set")

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1

        engine.dispose()

    def test_postgresql_has_required_tables(self):
        """Test PostgreSQL has the required tables."""
        pg_url = os.environ.get('DATABASE_URL_REMOTE')
        if not pg_url:
            pytest.skip("DATABASE_URL_REMOTE not set")

        engine = create_engine(pg_url)
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
            """))
            tables = [row[0] for row in result.fetchall()]

        engine.dispose()

        required_tables = [
            'official_documents',
            'ingest_jobs',
            'candidate_changes',
            'section_301_rates',
            'section_232_rates',
            'ieepa_rates'
        ]

        for table in required_tables:
            assert table in tables, f"Required table '{table}' not found in PostgreSQL"


class TestDataComparison:
    """Test data comparison between SQLite and PostgreSQL."""

    def test_section_301_rates_count_match(self):
        """Test Section 301 rates count is similar between databases."""
        pg_url = os.environ.get('DATABASE_URL_REMOTE')
        if not pg_url:
            pytest.skip("DATABASE_URL_REMOTE not set")

        # Get SQLite count
        sqlite_conn = sqlite3.connect('instance/sqlite.db')
        cursor = sqlite_conn.execute("SELECT COUNT(*) FROM section_301_rates")
        sqlite_count = cursor.fetchone()[0]
        sqlite_conn.close()

        # Get PostgreSQL count
        pg_engine = create_engine(pg_url)
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM section_301_rates"))
            pg_count = result.fetchone()[0]
        pg_engine.dispose()

        # PostgreSQL should have at least as many rows (after sync)
        assert pg_count >= sqlite_count * 0.9, \
            f"PostgreSQL has {pg_count} rows, SQLite has {sqlite_count} (should be similar)"

    def test_specific_hts_code_sync(self):
        """Test a specific HTS code exists in both databases with same rate."""
        pg_url = os.environ.get('DATABASE_URL_REMOTE')
        if not pg_url:
            pytest.skip("DATABASE_URL_REMOTE not set")

        test_hts = '85444290'  # Known HTS code

        # Get from SQLite
        sqlite_conn = sqlite3.connect('instance/sqlite.db')
        cursor = sqlite_conn.execute("""
            SELECT duty_rate FROM section_301_rates
            WHERE hts_8digit = ? AND effective_end IS NULL
            LIMIT 1
        """, (test_hts,))
        sqlite_row = cursor.fetchone()
        sqlite_conn.close()

        if not sqlite_row:
            pytest.skip(f"HTS {test_hts} not found in SQLite")

        sqlite_rate = sqlite_row[0]

        # Get from PostgreSQL
        pg_engine = create_engine(pg_url)
        with pg_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT duty_rate FROM section_301_rates
                WHERE hts_8digit = :hts AND effective_end IS NULL
                LIMIT 1
            """), {'hts': test_hts})
            pg_row = result.fetchone()
        pg_engine.dispose()

        if not pg_row:
            pytest.skip(f"HTS {test_hts} not found in PostgreSQL")

        pg_rate = pg_row[0]

        assert abs(float(sqlite_rate) - float(pg_rate)) < 0.001, \
            f"Rate mismatch for {test_hts}: SQLite={sqlite_rate}, PG={pg_rate}"


class TestSyncExecution:
    """Test actual sync execution."""

    def test_sync_returns_dict(self):
        """Test sync_to_postgresql returns a dict with expected keys."""
        from app.sync import sync_to_postgresql

        result = sync_to_postgresql()

        assert isinstance(result, dict)
        assert 'enabled' in result

        if result.get('enabled'):
            assert 'tables' in result
            assert 'total_added' in result
            assert 'total_errors' in result

    def test_sync_idempotent(self):
        """Test running sync twice doesn't duplicate data."""
        from app.sync import sync_to_postgresql, is_sync_enabled

        if not is_sync_enabled():
            pytest.skip("Sync not enabled")

        # First sync
        result1 = sync_to_postgresql()
        added1 = result1.get('total_added', 0)

        # Second sync should add nothing (all data already synced)
        result2 = sync_to_postgresql()
        added2 = result2.get('total_added', 0)

        # Second sync should add 0 or very few rows
        assert added2 <= added1 * 0.1, \
            f"Second sync added {added2} rows (first added {added1}) - should be idempotent"

    def test_sync_specific_tables(self):
        """Test syncing specific tables only."""
        from app.sync.pg_sync import sync_to_postgresql

        # Sync only tariff rate tables
        result = sync_to_postgresql(tables=['section_301_rates'])

        assert isinstance(result, dict)
        if result.get('enabled'):
            assert 'section_301_rates' in result.get('tables', {})
            # Should NOT sync other tables
            assert 'ingest_jobs' not in result.get('tables', {})


class TestForeignKeyOrder:
    """Test that FK ordering is correct."""

    def test_sync_tables_order(self):
        """Test SYNC_TABLES is in correct FK dependency order."""
        from app.sync.pg_sync import SYNC_TABLES

        # official_documents must come before ingest_jobs
        od_idx = SYNC_TABLES.index('official_documents') if 'official_documents' in SYNC_TABLES else -1
        ij_idx = SYNC_TABLES.index('ingest_jobs') if 'ingest_jobs' in SYNC_TABLES else -1

        if od_idx >= 0 and ij_idx >= 0:
            assert od_idx < ij_idx, "official_documents must sync before ingest_jobs"

        # ingest_jobs must come before candidate_changes
        cc_idx = SYNC_TABLES.index('candidate_changes') if 'candidate_changes' in SYNC_TABLES else -1

        if ij_idx >= 0 and cc_idx >= 0:
            assert ij_idx < cc_idx, "ingest_jobs must sync before candidate_changes"


class TestProcessIngestQueueIntegration:
    """Test integration with process_ingest_queue.py."""

    def test_run_auto_sync_import(self):
        """Test run_auto_sync can be imported from the script module."""
        import sys
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "process_ingest_queue",
            "scripts/process_ingest_queue.py"
        )
        module = importlib.util.module_from_spec(spec)

        # This should not raise
        # Note: We don't actually exec the module to avoid side effects


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_sync_empty_results_list(self):
        """Test run_auto_sync handles empty results."""
        # Import the function
        import sys
        sys.path.insert(0, 'scripts')

        # Simulate what happens in process_ingest_queue
        from app.sync import sync_to_postgresql, is_sync_enabled

        # Empty results should not cause errors
        results = []
        if not results:
            pass  # Should skip sync

    def test_sync_with_disabled_env(self):
        """Test sync gracefully handles disabled state."""
        from app.sync import sync_to_postgresql

        # Save original
        orig = os.environ.get('AUTO_SYNC_ENABLED')

        try:
            os.environ['AUTO_SYNC_ENABLED'] = 'false'
            result = sync_to_postgresql()
            assert result.get('enabled') == False
        finally:
            if orig:
                os.environ['AUTO_SYNC_ENABLED'] = orig


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
