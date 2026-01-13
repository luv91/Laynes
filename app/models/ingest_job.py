"""
Ingest Job Model

Manages the document processing queue with:
- Job versioning (allow reprocessing when content changes)
- Status tracking through pipeline stages
- Error handling and retry logic
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4

from app.web.db import db
from app.web.db.models.base import BaseModel


class IngestJob(BaseModel):
    """
    Tracks document ingestion through the pipeline.

    Job lifecycle:
    queued → fetching → fetched → rendering → rendered
    → chunking → chunked → extracting → extracted
    → validating → validated → committing → committed
    OR → needs_review → reviewed → committed
    OR → failed

    Key design:
    - UNIQUE(source, external_id, content_hash) allows reprocessing
      when document content changes
    - parent_job_id links to previous processing attempts
    """
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        db.UniqueConstraint('source', 'external_id', 'content_hash', name='uq_ingest_job'),
        db.Index('idx_ingest_job_status', 'status', 'created_at'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Source identification
    source = db.Column(db.String(50), nullable=False, index=True)  # federal_register, cbp_csms, usitc
    external_id = db.Column(db.String(100), nullable=False, index=True)
    url = db.Column(db.String(500))

    # Versioning
    revision_number = db.Column(db.Integer, default=1)
    source_updated_at = db.Column(db.DateTime)  # From API metadata
    content_hash = db.Column(db.String(64), index=True)  # Hash of fetched content
    parent_job_id = db.Column(db.String(36), db.ForeignKey("ingest_jobs.id"))

    # Processing attempt tracking
    attempt_number = db.Column(db.Integer, default=1)
    processing_reason = db.Column(db.String(100))  # initial, correction, reparse, attachment_change

    # Discovery
    discovered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    discovered_by = db.Column(db.String(50))  # watcher name

    # Status
    status = db.Column(db.String(50), nullable=False, default="queued", index=True)
    # Valid statuses: queued, fetching, fetched, rendering, rendered,
    # chunking, chunked, extracting, extracted, validating, validated,
    # committing, committed, needs_review, reviewed, failed

    # Processing references
    document_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"))

    # Error handling
    error_message = db.Column(db.Text)
    retry_count = db.Column(db.Integer, default=0)
    max_retries = db.Column(db.Integer, default=3)

    # Worker tracking
    claimed_by = db.Column(db.String(100))  # Worker ID that claimed this job
    claimed_at = db.Column(db.DateTime)

    # Results
    changes_extracted = db.Column(db.Integer, default=0)
    changes_validated = db.Column(db.Integer, default=0)
    changes_committed = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # Relationships
    document = db.relationship("OfficialDocument", backref="ingest_jobs")
    parent_job = db.relationship("IngestJob", remote_side=[id], backref="child_jobs")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "revision_number": self.revision_number,
            "content_hash": self.content_hash,
            "status": self.status,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "changes_extracted": self.changes_extracted,
            "changes_validated": self.changes_validated,
            "changes_committed": self.changes_committed,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def can_retry(self) -> bool:
        """Check if job can be retried."""
        return self.retry_count < self.max_retries

    def mark_failed(self, error_message: str):
        """Mark job as failed with error message."""
        self.status = "failed"
        self.error_message = error_message
        self.retry_count += 1
        self.updated_at = datetime.utcnow()

    def mark_completed(self):
        """Mark job as successfully completed."""
        self.status = "committed"
        self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    @classmethod
    def create_or_get(cls, source: str, external_id: str, content_hash: str,
                      url: str = None, discovered_by: str = None) -> "IngestJob":
        """
        Create a new job or return existing one with same content hash.

        If a job exists with different content_hash, creates a new job
        with parent_job_id pointing to the previous one.

        Returns:
            IngestJob instance (may be existing or new)
        """
        # Check for exact match (same content)
        existing = cls.query.filter_by(
            source=source,
            external_id=external_id,
            content_hash=content_hash,
        ).first()

        if existing:
            return existing

        # Check for previous version (different content)
        previous = cls.query.filter_by(
            source=source,
            external_id=external_id,
        ).order_by(cls.revision_number.desc()).first()

        # Create new job
        job = cls(
            source=source,
            external_id=external_id,
            content_hash=content_hash,
            url=url,
            discovered_by=discovered_by,
            status="queued",
        )

        if previous:
            job.parent_job_id = previous.id
            job.revision_number = previous.revision_number + 1
            job.processing_reason = "content_change"
        else:
            job.processing_reason = "initial"

        return job

    @classmethod
    def claim_next(cls, worker_id: str) -> Optional["IngestJob"]:
        """
        Claim the next available job for processing.

        Uses FOR UPDATE SKIP LOCKED for PostgreSQL, simple query for SQLite.

        Args:
            worker_id: Identifier for the claiming worker

        Returns:
            IngestJob if one was claimed, None otherwise
        """
        from sqlalchemy import text

        # Check if using PostgreSQL (supports FOR UPDATE SKIP LOCKED)
        db_url = str(db.engine.url)
        is_postgres = 'postgresql' in db_url

        if is_postgres:
            # Use raw SQL for SKIP LOCKED (PostgreSQL only)
            result = db.session.execute(text("""
                SELECT id FROM ingest_jobs
                WHERE status = 'queued'
                ORDER BY discovered_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                return None
            job_id = row[0]
        else:
            # SQLite fallback - simple query (single-worker safe)
            job = cls.query.filter_by(status='queued').order_by(
                cls.discovered_at.asc()
            ).first()
            if not job:
                return None
            job_id = job.id

        # Update the claimed job
        job = cls.query.get(job_id)
        if job:
            job.status = "fetching"
            job.claimed_by = worker_id
            job.claimed_at = datetime.utcnow()
            db.session.commit()

        return job
