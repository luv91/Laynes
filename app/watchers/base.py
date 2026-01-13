"""
Base Watcher class and common types for the Regulatory Update Pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredDocument:
    """
    A document discovered by a watcher that needs to be processed.

    This is the output of the watcher layer - it represents a document
    that has been detected but not yet fetched or processed.
    """
    # Source identification
    source: str  # 'federal_register', 'cbp_csms', 'usitc'
    external_id: str  # Document number, bulletin ID, etc.

    # URLs for fetching
    pdf_url: Optional[str] = None
    xml_url: Optional[str] = None
    html_url: Optional[str] = None

    # Metadata
    title: str = ""
    publication_date: Optional[date] = None
    effective_date: Optional[date] = None

    # Source-specific metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Discovery tracking
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    discovered_by: str = ""

    def preferred_url(self) -> Optional[str]:
        """Return the preferred URL for fetching (XML > HTML > PDF)."""
        return self.xml_url or self.html_url or self.pdf_url


class BaseWatcher(ABC):
    """
    Abstract base class for document watchers.

    Watchers are responsible for:
    1. Polling official sources on a schedule
    2. Detecting new documents since last check
    3. Returning DiscoveredDocument objects for processing

    Watchers do NOT:
    - Fetch document content (that's the fetch worker)
    - Parse document content (that's the render/extract workers)
    - Write to the database (that's the write gate)
    """

    # Watcher configuration
    SOURCE_NAME: str = "unknown"
    POLL_INTERVAL_HOURS: int = 6
    MAX_RESULTS_PER_POLL: int = 100

    def __init__(self, db_session=None):
        """
        Initialize watcher with optional database session.

        Args:
            db_session: SQLAlchemy session for storing last poll state
        """
        self.db = db_session
        self.last_poll_key = f"{self.SOURCE_NAME}_last_poll"

    @abstractmethod
    def poll(self, since_date: Optional[date] = None) -> List[DiscoveredDocument]:
        """
        Poll the source for new documents.

        Args:
            since_date: Only return documents published after this date.
                       If None, uses the stored last_poll_date.

        Returns:
            List of DiscoveredDocument objects for processing.
        """
        pass

    def get_last_poll_date(self) -> date:
        """
        Get the date of the last successful poll from the database.

        Override this if you need custom storage logic.
        """
        if self.db:
            from app.web.db.models.tariff_tables import IngestionRun
            last_run = IngestionRun.query.filter_by(
                operator=f"watcher_{self.SOURCE_NAME}",
                status='success'
            ).order_by(IngestionRun.ingestion_timestamp.desc()).first()

            if last_run:
                return last_run.ingestion_timestamp.date()

        # Default: 30 days ago
        from datetime import timedelta
        return date.today() - timedelta(days=30)

    def update_last_poll(self):
        """
        Update the last poll timestamp in the database.
        """
        if self.db:
            from app.web.db.models.tariff_tables import IngestionRun
            run = IngestionRun(
                operator=f"watcher_{self.SOURCE_NAME}",
                table_affected="ingest_jobs",
                status="success",
                notes=f"Watcher poll completed at {datetime.utcnow()}"
            )
            self.db.add(run)
            self.db.commit()

    def run(self) -> List[DiscoveredDocument]:
        """
        Execute a full poll cycle.

        1. Get last poll date
        2. Poll for new documents
        3. Update last poll timestamp
        4. Return discovered documents
        """
        try:
            since_date = self.get_last_poll_date()
            logger.info(f"{self.SOURCE_NAME} watcher: Polling since {since_date}")

            documents = self.poll(since_date)

            logger.info(f"{self.SOURCE_NAME} watcher: Found {len(documents)} new documents")

            self.update_last_poll()

            return documents

        except Exception as e:
            logger.error(f"{self.SOURCE_NAME} watcher error: {e}")
            raise

    @staticmethod
    def deduplicate(documents: List[DiscoveredDocument]) -> List[DiscoveredDocument]:
        """
        Remove duplicate documents based on external_id.
        """
        seen = set()
        unique = []
        for doc in documents:
            if doc.external_id not in seen:
                seen.add(doc.external_id)
                unique.append(doc)
        return unique


def enqueue_discovered_documents(run_id: str, docs: List[DiscoveredDocument]) -> Dict[str, Any]:
    """
    Create IngestJobs and RegulatoryRunDocuments for discovered documents.

    This is the bridge between watchers and the processing pipeline.

    Args:
        run_id: ID of the RegulatoryRun this discovery is part of
        docs: List of DiscoveredDocument objects from watcher

    Returns:
        Dict with counts: {queued, skipped, errors}
    """
    from app.web.db import db
    from app.models import IngestJob, RegulatoryRun, RegulatoryRunDocument

    stats = {"queued": 0, "skipped": 0, "errors": 0}

    for doc in docs:
        try:
            # Check for existing job with same source + external_id
            # (We'll check content_hash after fetch)
            existing_job = IngestJob.query.filter_by(
                source=doc.source,
                external_id=doc.external_id,
            ).order_by(IngestJob.revision_number.desc()).first()

            # Skip if already committed and not reprocessing
            if existing_job and existing_job.status == "committed":
                # Record in run but mark as skipped
                run_doc = RegulatoryRunDocument(
                    run_id=run_id,
                    source=doc.source,
                    external_id=doc.external_id,
                    document_id=existing_job.document_id,
                    publication_date=doc.publication_date,
                    effective_date=doc.effective_date,
                    title=doc.title,
                    url_xml=doc.xml_url,
                    url_pdf=doc.pdf_url,
                    url_html=doc.html_url,
                    status="skipped",
                )
                db.session.add(run_doc)
                stats["skipped"] += 1
                continue

            # Create new ingest job
            job = IngestJob(
                source=doc.source,
                external_id=doc.external_id,
                url=doc.preferred_url(),
                discovered_at=doc.discovered_at,
                discovered_by=doc.discovered_by,
                status="queued",
                revision_number=(existing_job.revision_number + 1) if existing_job else 1,
                parent_job_id=existing_job.id if existing_job else None,
                processing_reason="content_change" if existing_job else "initial",
            )
            db.session.add(job)
            db.session.flush()  # Get job ID

            # Record in run
            run_doc = RegulatoryRunDocument(
                run_id=run_id,
                source=doc.source,
                external_id=doc.external_id,
                ingest_job_id=job.id,
                publication_date=doc.publication_date,
                effective_date=doc.effective_date,
                title=doc.title,
                url_xml=doc.xml_url,
                url_pdf=doc.pdf_url,
                url_html=doc.html_url,
                status="discovered",
            )
            db.session.add(run_doc)
            stats["queued"] += 1

        except Exception as e:
            logger.error(f"Error enqueueing {doc.source}/{doc.external_id}: {e}")
            stats["errors"] += 1

    db.session.commit()

    logger.info(
        f"Enqueued {stats['queued']} jobs, skipped {stats['skipped']}, "
        f"{stats['errors']} errors"
    )

    return stats
