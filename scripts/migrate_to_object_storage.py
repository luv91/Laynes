#!/usr/bin/env python
"""
Migrate existing raw_bytes to object storage.

Moves document blobs from the database to local filesystem storage.
After migration, raw_bytes is set to NULL and storage_uri points to the file.

Usage:
    # Preview (dry run)
    python scripts/migrate_to_object_storage.py --dry-run

    # Execute migration
    python scripts/migrate_to_object_storage.py

    # Limit number of documents to migrate
    python scripts/migrate_to_object_storage.py --limit 100
"""

import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.web import create_app
from app.web.db import db
from app.models.document_store import OfficialDocument
from app.storage import get_storage


def migrate_documents(dry_run: bool = True, limit: int = None) -> dict:
    """
    Migrate existing documents from raw_bytes to object storage.

    Args:
        dry_run: If True, only preview without making changes
        limit: Maximum number of documents to migrate

    Returns:
        Stats dict with migrated, skipped, errors counts
    """
    stats = {"migrated": 0, "skipped": 0, "errors": 0, "total_bytes": 0}

    storage = get_storage()
    print(f"Storage backend: {storage.SCHEME}")
    print(f"Base path: {storage.base_path if hasattr(storage, 'base_path') else 'N/A'}")
    print()

    # Query documents with raw_bytes but no storage_uri
    query = OfficialDocument.query.filter(
        OfficialDocument.raw_bytes.isnot(None),
        db.or_(
            OfficialDocument.storage_uri.is_(None),
            OfficialDocument.storage_uri == ""
        )
    )

    if limit:
        query = query.limit(limit)

    docs = query.all()
    total = len(docs)

    print(f"Found {total} documents to migrate")
    print("=" * 60)

    for i, doc in enumerate(docs, 1):
        try:
            content_type = doc.content_type or "application/octet-stream"
            size = len(doc.raw_bytes) if doc.raw_bytes else 0

            print(f"\n[{i}/{total}] {doc.source}/{doc.external_id}")
            print(f"  Content type: {content_type}")
            print(f"  Size: {size:,} bytes")

            if not doc.raw_bytes:
                print("  SKIP: No raw_bytes")
                stats["skipped"] += 1
                continue

            if not doc.content_hash:
                print("  SKIP: No content_hash")
                stats["skipped"] += 1
                continue

            if dry_run:
                # Preview only
                ext = doc._get_extension(content_type) if hasattr(doc, '_get_extension') else ".bin"
                safe_external_id = doc.external_id.replace("/", "_")
                key = f"{doc.source}/{safe_external_id}/{doc.content_hash[:16]}{ext}"
                print(f"  Would migrate to: local://{key}")
                stats["migrated"] += 1
                stats["total_bytes"] += size
            else:
                # Actually migrate
                storage_uri = doc.store_content(doc.raw_bytes, content_type)
                db.session.commit()
                print(f"  Migrated to: {storage_uri}")
                stats["migrated"] += 1
                stats["total_bytes"] += size

        except Exception as e:
            print(f"  ERROR: {e}")
            stats["errors"] += 1
            if not dry_run:
                db.session.rollback()

    return stats


def main():
    parser = argparse.ArgumentParser(description='Migrate raw_bytes to object storage')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview without making changes')
    parser.add_argument('--limit', type=int, default=None,
                        help='Maximum documents to migrate')
    args = parser.parse_args()

    print("=" * 60)
    print("Object Storage Migration")
    print("=" * 60)
    print(f"Mode: {'DRY RUN (preview only)' if args.dry_run else 'EXECUTE'}")
    if args.limit:
        print(f"Limit: {args.limit} documents")
    print()

    app = create_app()
    with app.app_context():
        stats = migrate_documents(dry_run=args.dry_run, limit=args.limit)

    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"Migrated: {stats['migrated']}")
    print(f"Skipped: {stats['skipped']}")
    print(f"Errors: {stats['errors']}")
    print(f"Total bytes: {stats['total_bytes']:,}")

    if args.dry_run:
        print("\nThis was a DRY RUN - no data was actually migrated.")
        print("Run without --dry-run to execute the migration.")


if __name__ == '__main__':
    main()
