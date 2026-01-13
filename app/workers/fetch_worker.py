"""
Fetch Worker

Downloads raw documents from official sources and stores them
with content hashing for change detection.
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional
import requests

from app.web.db import db
from app.models.document_store import OfficialDocument
from app.models.ingest_job import IngestJob

logger = logging.getLogger(__name__)


class FetchWorker:
    """
    Downloads and stores raw documents.

    Responsibilities:
    - Fetch document from URL (prefer XML > HTML > PDF)
    - Compute SHA256 content hash
    - Check for duplicate content
    - Store in official_documents table
    """

    TIMEOUT = 60  # seconds

    def process_job(self, job: IngestJob) -> Optional[OfficialDocument]:
        """
        Fetch document for an ingest job.

        Args:
            job: IngestJob with URL to fetch

        Returns:
            OfficialDocument if successful, None if failed
        """
        job.status = "fetching"
        db.session.commit()

        try:
            url = job.url
            if not url:
                raise ValueError("No URL in job")

            # Detect content type from URL
            content_type = self._detect_content_type(url)

            # Fetch content
            response = requests.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()
            raw_bytes = response.content

            # Compute hash
            content_hash = hashlib.sha256(raw_bytes).hexdigest()

            # Check for duplicate
            existing = OfficialDocument.query.filter_by(
                content_hash=content_hash
            ).first()

            if existing:
                logger.info(f"Document already exists with hash {content_hash[:16]}...")
                job.document_id = existing.id
                job.content_hash = content_hash
                job.status = "fetched"
                db.session.commit()
                return existing

            # Create new document
            doc = OfficialDocument(
                source=job.source,
                external_id=job.external_id,
                content_hash=content_hash,
                content_type=content_type,
                content_size=len(raw_bytes),
                raw_bytes=raw_bytes,
                status="fetched",
                fetched_at=datetime.utcnow(),
            )

            # Set URLs based on content type
            if content_type == "text/xml":
                doc.xml_url = url
            elif content_type == "application/pdf":
                doc.pdf_url = url
            else:
                doc.html_url = url

            db.session.add(doc)
            db.session.flush()

            # Update job
            job.document_id = doc.id
            job.content_hash = content_hash
            job.status = "fetched"
            db.session.commit()

            logger.info(f"Fetched document {job.external_id}: {len(raw_bytes)} bytes")
            return doc

        except Exception as e:
            logger.error(f"Fetch failed for {job.external_id}: {e}")
            job.mark_failed(str(e))
            db.session.commit()
            return None

    def _detect_content_type(self, url: str) -> str:
        """Detect content type from URL."""
        url_lower = url.lower()
        if ".xml" in url_lower:
            return "text/xml"
        elif ".pdf" in url_lower:
            return "application/pdf"
        elif ".docx" in url_lower:
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            return "text/html"

    def fetch_with_metadata(self, job: IngestJob, metadata: dict) -> Optional[OfficialDocument]:
        """
        Fetch document and apply metadata.

        Args:
            job: IngestJob with URL
            metadata: Dict with title, publication_date, effective_date, etc.

        Returns:
            OfficialDocument if successful
        """
        doc = self.process_job(job)

        if doc:
            doc.title = metadata.get("title")

            if metadata.get("publication_date"):
                from datetime import date
                if isinstance(metadata["publication_date"], str):
                    doc.publication_date = date.fromisoformat(metadata["publication_date"])
                else:
                    doc.publication_date = metadata["publication_date"]

            if metadata.get("effective_date"):
                from datetime import date
                if isinstance(metadata["effective_date"], str):
                    doc.effective_date = date.fromisoformat(metadata["effective_date"])
                else:
                    doc.effective_date = metadata["effective_date"]

            doc.metadata_json = metadata
            db.session.commit()

        return doc
