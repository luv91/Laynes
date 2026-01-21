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

            # Special handling for Federal Register - use API instead of HTML scraping
            if job.source == "federal_register":
                return self._fetch_federal_register(job)

            # Detect content type from URL
            content_type = self._detect_content_type(url)

            # Fetch content
            response = requests.get(url, timeout=self.TIMEOUT)
            response.raise_for_status()
            raw_bytes = response.content

            # Compute hash
            content_hash = hashlib.sha256(raw_bytes).hexdigest()

            # Check if another job already processed this exact content
            existing_job = IngestJob.query.filter_by(
                source=job.source,
                external_id=job.external_id,
                content_hash=content_hash
            ).filter(IngestJob.id != job.id).first()

            if existing_job:
                # Another job already processed this exact content
                logger.info(
                    f"Job {job.external_id} already processed by job {existing_job.id} "
                    f"with same content hash {content_hash[:16]}... "
                    f"existing status: {existing_job.status}"
                )
                # Mark job as already processed (don't set content_hash to avoid constraint)
                job.status = "already_processed"
                job.document_id = existing_job.document_id
                db.session.commit()
                # Always return None to skip further processing
                # The existing job already handled this document
                return None

            # Check for duplicate document (same content from different source/external_id)
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
                status="fetched",
                fetched_at=datetime.utcnow(),
            )
            # Store content in object storage (local filesystem)
            doc.store_content(raw_bytes, content_type)

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

    def _fetch_federal_register(self, job: IngestJob) -> Optional[OfficialDocument]:
        """
        Fetch Federal Register document using API (not HTML scraping).

        Federal Register blocks HTML scraping with CAPTCHA. Use their API instead:
        https://www.federalregister.gov/developers/documentation/api/v1

        Args:
            job: IngestJob with external_id = document number (e.g., "2025-12052")

        Returns:
            OfficialDocument with full text content
        """
        doc_number = job.external_id
        api_url = f"https://www.federalregister.gov/api/v1/documents/{doc_number}.json"

        logger.info(f"Fetching Federal Register {doc_number} via API: {api_url}")

        # Fetch API JSON
        response = requests.get(api_url, timeout=self.TIMEOUT)
        response.raise_for_status()
        api_data = response.json()

        # Get full text - prefer raw_text_url, fallback to abstract
        full_text = None
        raw_text_url = api_data.get("raw_text_url")

        if raw_text_url:
            try:
                text_response = requests.get(raw_text_url, timeout=self.TIMEOUT)
                text_response.raise_for_status()
                full_text = text_response.text
            except Exception as e:
                logger.warning(f"Could not fetch raw_text for {doc_number}: {e}")

        # Fallback to abstract + body_html if raw_text not available
        if not full_text:
            abstract = api_data.get("abstract", "")
            body = api_data.get("body_html", "")
            full_text = f"{abstract}\n\n{body}" if body else abstract

        if not full_text:
            raise ValueError(f"No text content available for {doc_number}")

        raw_bytes = full_text.encode("utf-8")
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Check for duplicate
        existing = OfficialDocument.query.filter_by(content_hash=content_hash).first()
        if existing:
            logger.info(f"Document already exists with hash {content_hash[:16]}...")
            job.document_id = existing.id
            job.content_hash = content_hash
            job.status = "fetched"
            db.session.commit()
            return existing

        # Create document with metadata from API
        doc = OfficialDocument(
            source=job.source,
            external_id=doc_number,
            content_hash=content_hash,
            content_type="text/plain",  # Raw text from API
            content_size=len(raw_bytes),
            status="fetched",
            fetched_at=datetime.utcnow(),
            title=api_data.get("title"),
            html_url=api_data.get("html_url"),
            xml_url=api_data.get("full_text_xml_url"),
        )
        # Store content in object storage (local filesystem)
        doc.store_content(raw_bytes, "text/plain")

        # Set publication date
        if api_data.get("publication_date"):
            from datetime import date as date_type
            try:
                doc.publication_date = date_type.fromisoformat(api_data["publication_date"])
            except ValueError:
                pass

        # Store useful metadata
        doc.metadata_json = {
            "document_number": doc_number,
            "type": api_data.get("type"),
            "agencies": [a.get("name") for a in api_data.get("agencies", [])],
            "citation": api_data.get("citation"),
            "cfr_references": api_data.get("cfr_references", []),
            "significant": api_data.get("significant"),
        }

        db.session.add(doc)
        db.session.flush()

        job.document_id = doc.id
        job.content_hash = content_hash
        job.status = "fetched"
        db.session.commit()

        logger.info(f"Fetched Federal Register {doc_number}: {len(raw_bytes)} bytes, title: {doc.title[:50] if doc.title else 'N/A'}...")
        return doc
