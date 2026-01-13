#!/usr/bin/env python
"""
Run Watchers - Poll regulatory sources for new documents.

This script runs as a standalone process (not inside Flask web).
Schedule via cron, Railway scheduler, or Heroku scheduler.

Usage:
    # Poll Federal Register (default)
    python scripts/run_watchers.py

    # Poll specific source with date range
    python scripts/run_watchers.py --source federal_register --since 2025-01-01

    # Poll all sources
    python scripts/run_watchers.py --all

Scheduling:
    # Every 6 hours via cron
    0 */6 * * * cd /path/to/lanes && python scripts/run_watchers.py

    # Railway cron
    railway cron "0 */6 * * *" python scripts/run_watchers.py
"""

import sys
import os
import click
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.web import create_app
from app.web.db import db
from app.models import RegulatoryRun
from app.watchers.base import enqueue_discovered_documents

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


@click.command()
@click.option('--source', '-s', default='federal_register',
              type=click.Choice(['federal_register', 'cbp_csms', 'usitc', 'all']),
              help='Source to poll')
@click.option('--since', '-d', default=None,
              help='Poll since date (YYYY-MM-DD). Default: 7 days ago')
@click.option('--dry-run', is_flag=True,
              help='Discover documents but don\'t enqueue jobs')
@click.option('--export-manifest', is_flag=True,
              help='Export JSON manifest after run')
@click.option('--all', 'poll_all', is_flag=True,
              help='Poll all configured sources')
def main(source: str, since: str, dry_run: bool, export_manifest: bool, poll_all: bool):
    """
    Poll regulatory sources for new documents.

    Discovers new documents and creates IngestJobs for processing.
    """
    app = create_app()

    with app.app_context():
        logger.info("=" * 60)
        logger.info("REGULATORY WATCHER RUN")
        logger.info("=" * 60)

        # Parse since date
        since_date = None
        if since:
            try:
                since_date = date.fromisoformat(since)
            except ValueError:
                click.echo(f"Invalid date format: {since}. Use YYYY-MM-DD", err=True)
                sys.exit(1)
        else:
            since_date = date.today() - timedelta(days=7)

        logger.info(f"Polling since: {since_date}")

        # Create run record
        run = RegulatoryRun(
            trigger="cron" if os.environ.get("RAILWAY_RUN_ID") else "manual",
            status="running",
            started_at=datetime.utcnow(),
            since_date=since_date,
        )

        if not dry_run:
            db.session.add(run)
            db.session.commit()

        # Determine sources to poll
        sources_to_poll = []
        if poll_all or source == 'all':
            sources_to_poll = ['federal_register', 'cbp_csms', 'usitc']
        else:
            sources_to_poll = [source]

        run.sources_polled = {s: True for s in sources_to_poll}

        total_stats = {
            "queued": 0,
            "skipped": 0,
            "errors": 0,
            "discovered": 0,
        }

        for src in sources_to_poll:
            logger.info(f"\n--- Polling {src} ---")

            try:
                if src == 'federal_register':
                    docs = poll_federal_register(since_date)
                elif src == 'cbp_csms':
                    docs = poll_cbp_csms(since_date)
                elif src == 'usitc':
                    docs = poll_usitc(since_date)
                else:
                    logger.warning(f"Unknown source: {src}")
                    continue

                total_stats["discovered"] += len(docs)
                logger.info(f"Discovered {len(docs)} documents from {src}")

                if dry_run:
                    logger.info("DRY RUN - Not enqueueing jobs")
                    for doc in docs[:5]:  # Show first 5
                        logger.info(f"  - {doc.external_id}: {doc.title[:60]}...")
                    if len(docs) > 5:
                        logger.info(f"  ... and {len(docs) - 5} more")
                else:
                    if docs:
                        stats = enqueue_discovered_documents(run.id, docs)
                        total_stats["queued"] += stats.get("queued", 0)
                        total_stats["skipped"] += stats.get("skipped", 0)
                        total_stats["errors"] += stats.get("errors", 0)

            except Exception as e:
                logger.exception(f"Error polling {src}: {e}")
                total_stats["errors"] += 1
                run.add_warning(f"Error polling {src}: {str(e)}")

        # Update run record
        if not dry_run:
            run.summary_counts = total_stats
            run.status = "success" if total_stats["errors"] == 0 else "partial"
            run.completed_at = datetime.utcnow()
            db.session.commit()

            logger.info("\n" + "=" * 60)
            logger.info("RUN COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Run ID: {run.id}")
            logger.info(f"Status: {run.status}")
            logger.info(f"Discovered: {total_stats['discovered']}")
            logger.info(f"Queued: {total_stats['queued']}")
            logger.info(f"Skipped (already processed): {total_stats['skipped']}")
            logger.info(f"Errors: {total_stats['errors']}")

            # Export manifest if requested
            if export_manifest:
                manifest_path = export_run_manifest(run)
                logger.info(f"Manifest exported to: {manifest_path}")

        else:
            logger.info("\n" + "=" * 60)
            logger.info("DRY RUN COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Would have discovered: {total_stats['discovered']}")


def poll_federal_register(since_date: date):
    """Poll Federal Register for new documents."""
    from app.watchers.federal_register import FederalRegisterWatcher

    watcher = FederalRegisterWatcher()
    return watcher.poll(since_date)


def poll_cbp_csms(since_date: date):
    """Poll CBP CSMS for new messages."""
    from app.watchers.cbp_csms import CBPCSMSWatcher

    watcher = CBPCSMSWatcher()
    try:
        docs = watcher.poll(since_date)
        return docs
    except Exception as e:
        logger.error(f"CBP CSMS watcher failed: {e}")
        return []


def poll_usitc(since_date: date):
    """Poll USITC for HTS updates."""
    from app.watchers.usitc import USITCWatcher

    watcher = USITCWatcher()
    try:
        docs = watcher.poll(since_date)
        return docs
    except Exception as e:
        logger.error(f"USITC watcher failed: {e}")
        return []


def export_run_manifest(run: RegulatoryRun) -> str:
    """Export run manifest to JSON file and optionally upload to S3."""
    from app.models import RegulatoryRunDocument, RegulatoryRunChange

    # Create manifest directory
    manifest_dir = Path("data/regulatory_runs")
    manifest_dir.mkdir(parents=True, exist_ok=True)

    # Build manifest
    docs = RegulatoryRunDocument.query.filter_by(run_id=run.id).all()
    changes = RegulatoryRunChange.query.filter_by(run_id=run.id).all()

    manifest = {
        "run": run.as_dict(),
        "documents": [d.as_dict() for d in docs],
        "changes": [c.as_dict() for c in changes],
        "exported_at": datetime.utcnow().isoformat(),
    }

    # Write to file
    date_str = run.started_at.strftime("%Y-%m-%d")
    filename = f"{date_str}_run_{run.id[:8]}.json"
    filepath = manifest_dir / filename

    with open(filepath, 'w') as f:
        json.dump(manifest, f, indent=2, default=str)

    # Also write to latest.json
    latest_path = manifest_dir / "latest.json"
    with open(latest_path, 'w') as f:
        json.dump(manifest, f, indent=2, default=str)

    # Upload to S3 if configured
    s3_url = upload_manifest_to_s3(filepath, filename)

    # Update run record
    run.manifest_path = s3_url or str(filepath)
    run.manifest_exported_at = datetime.utcnow()
    db.session.commit()

    return run.manifest_path


def upload_manifest_to_s3(local_path: Path, filename: str) -> str:
    """
    Upload manifest to S3 if AWS credentials are configured.

    Returns S3 URL if successful, None otherwise.
    """
    bucket = os.environ.get("MANIFEST_S3_BUCKET")
    if not bucket:
        logger.debug("MANIFEST_S3_BUCKET not set, skipping S3 upload")
        return None

    try:
        import boto3
        from botocore.exceptions import ClientError

        s3 = boto3.client('s3')

        # S3 key: regulatory_runs/YYYY/MM/filename
        date_parts = filename.split("_")[0].split("-")
        if len(date_parts) >= 2:
            s3_key = f"regulatory_runs/{date_parts[0]}/{date_parts[1]}/{filename}"
        else:
            s3_key = f"regulatory_runs/{filename}"

        s3.upload_file(
            str(local_path),
            bucket,
            s3_key,
            ExtraArgs={'ContentType': 'application/json'}
        )

        s3_url = f"s3://{bucket}/{s3_key}"
        logger.info(f"Uploaded manifest to {s3_url}")
        return s3_url

    except ImportError:
        logger.warning("boto3 not installed, skipping S3 upload")
        return None
    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Manifest upload failed: {e}")
        return None


if __name__ == "__main__":
    main()
