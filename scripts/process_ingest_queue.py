#!/usr/bin/env python
"""
Process Ingest Queue - Drain queued ingest jobs through the pipeline.

This script runs as a standalone worker process (not inside Flask web).
Schedule to run frequently (every 5-10 minutes) or run continuously.

Usage:
    # Process up to 50 jobs
    python scripts/process_ingest_queue.py

    # Process specific number of jobs
    python scripts/process_ingest_queue.py --max-jobs 100

    # Filter by source
    python scripts/process_ingest_queue.py --source federal_register

    # Run continuously (daemon mode)
    python scripts/process_ingest_queue.py --daemon --interval 60

Scheduling:
    # Every 10 minutes via cron
    */10 * * * * cd /path/to/lanes && python scripts/process_ingest_queue.py

    # As a Railway worker
    worker: python scripts/process_ingest_queue.py --daemon --interval 60
"""

import sys
import os
import time
import signal
import click
import logging
from datetime import datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.web import create_app
from app.web.db import db
from app.workers.pipeline import DocumentPipeline
from app.models import IngestJob
from app.sync import sync_to_postgresql, is_sync_enabled

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info("Shutdown signal received, finishing current job...")
    shutdown_requested = True


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


@click.command()
@click.option('--max-jobs', '-n', default=50, type=int,
              help='Maximum jobs to process per run (default: 50)')
@click.option('--source', '-s', default=None,
              help='Filter by source (federal_register, cbp_csms, etc.)')
@click.option('--daemon', '-d', is_flag=True,
              help='Run continuously in daemon mode')
@click.option('--interval', '-i', default=60, type=int,
              help='Seconds between queue checks in daemon mode (default: 60)')
@click.option('--reprocess', is_flag=True,
              help='Reprocess failed jobs')
def main(max_jobs: int, source: Optional[str], daemon: bool, interval: int, reprocess: bool):
    """
    Process queued ingest jobs through the document pipeline.

    Fetches, renders, chunks, extracts, validates, and commits tariff changes.
    """
    app = create_app()

    with app.app_context():
        logger.info("=" * 60)
        logger.info("INGEST QUEUE PROCESSOR")
        logger.info("=" * 60)
        logger.info(f"Max jobs per run: {max_jobs}")
        logger.info(f"Source filter: {source or 'all'}")
        logger.info(f"Daemon mode: {daemon}")

        if daemon:
            run_daemon(app, max_jobs, source, interval, reprocess)
        else:
            run_once(max_jobs, source, reprocess)


def run_once(max_jobs: int, source: Optional[str], reprocess: bool):
    """Process jobs once and exit."""
    # Get queue depth
    queue_depth = get_queue_depth(source, reprocess)
    logger.info(f"Queue depth: {queue_depth}")

    if queue_depth == 0:
        logger.info("No jobs in queue. Exiting.")
        return

    # Create pipeline
    pipeline = DocumentPipeline()

    # Process jobs
    if reprocess:
        results = reprocess_failed_jobs(pipeline, max_jobs, source)
    else:
        results = pipeline.process_queue(max_jobs=max_jobs, source_filter=source)

    # Summary
    print_summary(results)

    # Auto-sync to PostgreSQL if enabled
    run_auto_sync(results)


def run_daemon(app, max_jobs: int, source: Optional[str], interval: int, reprocess: bool):
    """Run continuously, processing jobs as they arrive."""
    global shutdown_requested

    logger.info(f"Starting daemon mode (interval: {interval}s)")
    logger.info("Press Ctrl+C to stop gracefully")

    while not shutdown_requested:
        try:
            with app.app_context():
                queue_depth = get_queue_depth(source, reprocess)

                if queue_depth > 0:
                    logger.info(f"Queue depth: {queue_depth}. Processing...")
                    pipeline = DocumentPipeline()

                    if reprocess:
                        results = reprocess_failed_jobs(pipeline, max_jobs, source)
                    else:
                        results = pipeline.process_queue(max_jobs=max_jobs, source_filter=source)

                    print_summary(results)

                    # Auto-sync to PostgreSQL if enabled
                    run_auto_sync(results)
                else:
                    logger.debug("Queue empty. Waiting...")

        except Exception as e:
            logger.exception(f"Error in daemon loop: {e}")

        # Wait for next cycle (check shutdown flag every second)
        for _ in range(interval):
            if shutdown_requested:
                break
            time.sleep(1)

    logger.info("Daemon shutdown complete")


def get_queue_depth(source: Optional[str], include_failed: bool = False) -> int:
    """Get number of jobs waiting in queue."""
    query = IngestJob.query

    if include_failed:
        query = query.filter(IngestJob.status.in_(["queued", "failed"]))
    else:
        query = query.filter_by(status="queued")

    if source:
        query = query.filter_by(source=source)

    return query.count()


def reprocess_failed_jobs(pipeline: DocumentPipeline, max_jobs: int, source: Optional[str]):
    """Reprocess jobs that previously failed."""
    query = IngestJob.query.filter_by(status="failed")

    if source:
        query = query.filter_by(source=source)

    failed_jobs = query.limit(max_jobs).all()
    results = []

    for job in failed_jobs:
        logger.info(f"Reprocessing failed job: {job.id} ({job.source}/{job.external_id})")

        # Reset job state
        job.status = "queued"
        job.error_message = None
        job.retry_count = (job.retry_count or 0) + 1
        db.session.commit()

        # Process
        result = pipeline.process_job(job)
        results.append(result)

        if shutdown_requested:
            break

    return results


def print_summary(results: list):
    """Print processing summary."""
    if not results:
        logger.info("No jobs processed")
        return

    logger.info("\n" + "=" * 60)
    logger.info("PROCESSING SUMMARY")
    logger.info("=" * 60)

    total = len(results)
    committed = sum(1 for r in results if r.get("status") == "committed")
    no_changes = sum(1 for r in results if r.get("status") == "completed_no_changes")
    failed = sum(1 for r in results if r.get("status") == "failed")
    needs_review = sum(1 for r in results if r.get("status") == "needs_review")

    total_extracted = sum(r.get("changes_extracted", 0) for r in results)
    total_committed = sum(r.get("changes_committed", 0) for r in results)

    logger.info(f"Jobs processed: {total}")
    logger.info(f"  - Committed: {committed}")
    logger.info(f"  - No changes: {no_changes}")
    logger.info(f"  - Needs review: {needs_review}")
    logger.info(f"  - Failed: {failed}")
    logger.info(f"")
    logger.info(f"Changes extracted: {total_extracted}")
    logger.info(f"Changes committed: {total_committed}")

    # Show failed jobs
    if failed > 0:
        logger.warning("\nFailed jobs:")
        for r in results:
            if r.get("status") == "failed":
                logger.warning(f"  - {r.get('job_id')}: {r.get('errors', ['Unknown error'])[0]}")


def run_auto_sync(results: list):
    """Run auto-sync to PostgreSQL if enabled and changes were made."""
    if not results:
        return

    # Check if sync is enabled
    if not is_sync_enabled():
        logger.debug("Auto-sync disabled (set AUTO_SYNC_ENABLED=true and DATABASE_URL_REMOTE)")
        return

    # Only sync if there were changes
    total_committed = sum(r.get("changes_committed", 0) for r in results)
    successful_jobs = sum(1 for r in results if r.get("status") in ("committed", "completed_no_changes"))

    if successful_jobs == 0:
        logger.debug("No successful jobs to sync")
        return

    logger.info("")
    logger.info("=" * 60)
    logger.info("AUTO-SYNC: SQLite → PostgreSQL")
    logger.info("=" * 60)

    try:
        sync_results = sync_to_postgresql()

        if sync_results.get('error'):
            logger.error(f"Sync error: {sync_results['error']}")
            return

        total_added = sync_results.get('total_added', 0)
        total_errors = sync_results.get('total_errors', 0)

        logger.info(f"Sync complete: {total_added} rows added, {total_errors} errors")

        # Log per-table details if there were additions
        if total_added > 0:
            for table, stats in sync_results.get('tables', {}).items():
                if isinstance(stats, dict) and stats.get('added', 0) > 0:
                    logger.info(f"  - {table}: +{stats['added']}")

    except Exception as e:
        logger.exception(f"Auto-sync failed: {e}")


@click.command()
@click.option('--job-id', '-j', required=True, help='Job ID to process')
def process_single(job_id: str):
    """Process a single job by ID."""
    app = create_app()

    with app.app_context():
        job = IngestJob.query.get(job_id)
        if not job:
            click.echo(f"Job not found: {job_id}", err=True)
            sys.exit(1)

        logger.info(f"Processing single job: {job_id}")
        logger.info(f"Source: {job.source}")
        logger.info(f"External ID: {job.external_id}")
        logger.info(f"Status: {job.status}")

        pipeline = DocumentPipeline()
        result = pipeline.process_job(job)

        click.echo(f"\nResult: {result.get('status')}")
        click.echo(f"Changes extracted: {result.get('changes_extracted', 0)}")
        click.echo(f"Changes committed: {result.get('changes_committed', 0)}")

        if result.get("errors"):
            click.echo(f"Errors: {result['errors']}")
        if result.get("warnings"):
            click.echo(f"Warnings: {result['warnings']}")


if __name__ == "__main__":
    main()
