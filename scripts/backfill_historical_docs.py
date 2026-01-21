#!/usr/bin/env python3
"""
Backfill Historical Documents

Re-discovers and processes historical regulatory documents that may have been
missed or lost due to the --reset flag bug (fixed in v17.0).

This script:
1. Polls regulatory sources for documents since a specified date
2. Skips documents already in the ingest queue
3. Creates new IngestJobs for missing documents
4. Optionally processes them through the pipeline

Usage:
    # Discover missing documents (dry run)
    pipenv run python scripts/backfill_historical_docs.py --since 2024-01-01 --dry-run

    # Discover and queue missing documents
    pipenv run python scripts/backfill_historical_docs.py --since 2024-01-01

    # Discover, queue, and process documents
    pipenv run python scripts/backfill_historical_docs.py --since 2024-01-01 --process

v17.0: Created as part of DB-as-source-of-truth architecture
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def backfill_federal_register(since_date: date, dry_run: bool = False, process: bool = False) -> dict:
    """
    Backfill Federal Register documents.

    Args:
        since_date: Start date for searching
        dry_run: If True, only report what would be done
        process: If True, also process the documents through the pipeline

    Returns:
        Dict with counts of discovered, queued, and processed documents
    """
    from app.web import create_app
    from app.web.db import db
    from app.models.ingest_job import IngestJob
    from app.watchers.federal_register import FederalRegisterWatcher

    app = create_app()
    result = {"source": "federal_register", "discovered": 0, "already_queued": 0, "queued": 0, "processed": 0}

    with app.app_context():
        print(f"\n=== Federal Register Backfill (since {since_date}) ===")

        # Poll for documents
        watcher = FederalRegisterWatcher()
        documents = watcher.poll(since_date)
        result["discovered"] = len(documents)
        print(f"  Discovered {len(documents)} documents")

        for doc in documents:
            # Check if already in queue
            existing = IngestJob.query.filter_by(
                source="federal_register",
                external_id=doc.external_id
            ).first()

            if existing:
                result["already_queued"] += 1
                print(f"  [SKIP] {doc.external_id}: Already in queue (status: {existing.status})")
                continue

            if dry_run:
                print(f"  [DRY RUN] Would queue: {doc.external_id} - {doc.title[:50]}...")
                result["queued"] += 1
                continue

            # Create new job
            job = IngestJob(
                source="federal_register",
                external_id=doc.external_id,
                url=doc.xml_url or doc.pdf_url or doc.html_url,
                discovered_at=datetime.utcnow(),
                discovered_by="backfill_historical_docs.py",
                processing_reason="backfill",
                status="queued",
            )
            db.session.add(job)
            result["queued"] += 1
            print(f"  [QUEUED] {doc.external_id}: {doc.title[:50]}...")

        db.session.commit()

        # Optionally process
        if process and not dry_run and result["queued"] > 0:
            print(f"\n  Processing {result['queued']} queued jobs...")
            from app.workers.pipeline import DocumentPipeline
            pipeline = DocumentPipeline()

            jobs = IngestJob.query.filter_by(
                source="federal_register",
                discovered_by="backfill_historical_docs.py",
                status="queued"
            ).all()

            for job in jobs:
                try:
                    pipeline_result = pipeline.process_job(job)
                    if pipeline_result.get("status") in ["committed", "completed_no_changes"]:
                        result["processed"] += 1
                        print(f"    [OK] {job.external_id}: {pipeline_result.get('status')}")
                    else:
                        print(f"    [WARN] {job.external_id}: {pipeline_result.get('status')}")
                except Exception as e:
                    print(f"    [ERROR] {job.external_id}: {e}")

    return result


def backfill_cbp_csms(since_date: date, dry_run: bool = False, process: bool = False) -> dict:
    """
    Backfill CBP CSMS documents from email.

    Note: This requires GMAIL_CSMS_EMAIL and GMAIL_CSMS_APP_PASSWORD environment variables.
    """
    from app.web import create_app
    from app.web.db import db
    from app.models.ingest_job import IngestJob

    app = create_app()
    result = {"source": "email_csms", "discovered": 0, "already_queued": 0, "queued": 0, "processed": 0}

    with app.app_context():
        print(f"\n=== CBP CSMS Email Backfill (since {since_date}) ===")

        # Check if watcher is available
        try:
            from app.watchers.email_csms import EmailCSMSWatcher
        except ImportError:
            print("  [SKIP] EmailCSMSWatcher not available")
            return result

        # Check environment variables
        if not os.environ.get("GMAIL_CSMS_EMAIL") or not os.environ.get("GMAIL_CSMS_APP_PASSWORD"):
            print("  [SKIP] GMAIL_CSMS_EMAIL or GMAIL_CSMS_APP_PASSWORD not set")
            return result

        # Poll for documents
        watcher = EmailCSMSWatcher()
        documents = watcher.poll(since_date)
        result["discovered"] = len(documents)
        print(f"  Discovered {len(documents)} CSMS bulletins")

        for doc in documents:
            # Check if already in queue
            existing = IngestJob.query.filter_by(
                source="email_csms",
                external_id=doc.external_id
            ).first()

            if existing:
                result["already_queued"] += 1
                print(f"  [SKIP] CSMS #{doc.external_id}: Already in queue (status: {existing.status})")
                continue

            if dry_run:
                print(f"  [DRY RUN] Would queue: CSMS #{doc.external_id} - {doc.title[:50] if doc.title else 'No title'}...")
                result["queued"] += 1
                continue

            # Create new job
            job = IngestJob(
                source="email_csms",
                external_id=doc.external_id,
                url=doc.html_url,
                discovered_at=datetime.utcnow(),
                discovered_by="backfill_historical_docs.py",
                processing_reason="backfill",
                status="queued",
            )
            db.session.add(job)
            result["queued"] += 1
            print(f"  [QUEUED] CSMS #{doc.external_id}")

        db.session.commit()

    return result


def main():
    parser = argparse.ArgumentParser(description="Backfill historical regulatory documents")
    parser.add_argument("--since", required=True, type=str,
                       help="Start date for backfill (YYYY-MM-DD)")
    parser.add_argument("--source", type=str, choices=["federal_register", "email_csms", "all"],
                       default="all", help="Source to backfill (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Only report what would be done, don't make changes")
    parser.add_argument("--process", action="store_true",
                       help="Process queued documents through the pipeline")

    args = parser.parse_args()

    # Parse date
    try:
        since_date = datetime.strptime(args.since, "%Y-%m-%d").date()
    except ValueError:
        print(f"ERROR: Invalid date format '{args.since}'. Use YYYY-MM-DD.")
        return

    print("=" * 60)
    print("BACKFILL HISTORICAL DOCUMENTS")
    print("=" * 60)
    print(f"Since: {since_date}")
    print(f"Source: {args.source}")
    print(f"Dry run: {args.dry_run}")
    print(f"Process: {args.process}")
    print("=" * 60)

    results = []

    if args.source in ["federal_register", "all"]:
        results.append(backfill_federal_register(since_date, args.dry_run, args.process))

    if args.source in ["email_csms", "all"]:
        results.append(backfill_cbp_csms(since_date, args.dry_run, args.process))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total_discovered = 0
    total_queued = 0
    total_processed = 0

    for r in results:
        print(f"\n{r['source']}:")
        print(f"  Discovered: {r['discovered']}")
        print(f"  Already queued: {r['already_queued']}")
        print(f"  Newly queued: {r['queued']}")
        if r.get("processed"):
            print(f"  Processed: {r['processed']}")

        total_discovered += r["discovered"]
        total_queued += r["queued"]
        total_processed += r.get("processed", 0)

    print(f"\nTOTAL: {total_discovered} discovered, {total_queued} queued, {total_processed} processed")

    if args.dry_run:
        print("\n[DRY RUN] No changes were made. Remove --dry-run to queue documents.")


if __name__ == "__main__":
    main()
