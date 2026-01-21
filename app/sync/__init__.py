"""
Auto-sync module for SQLite to PostgreSQL replication.

Provides automatic synchronization of local SQLite data to remote PostgreSQL
after pipeline processing completes.
"""

from .pg_sync import sync_to_postgresql, is_sync_enabled

__all__ = ['sync_to_postgresql', 'is_sync_enabled']
