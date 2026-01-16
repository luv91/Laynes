"""
Document Pipeline

Orchestrates the full document processing workflow:
fetch → render → chunk → extract → validate → commit

Can run synchronously or process jobs from queue.
"""

import json
import logging
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any

from app.web.db import db
from app.models.document_store import OfficialDocument
from app.models.evidence import EvidencePacket
from app.models.ingest_job import IngestJob
from app.workers.fetch_worker import FetchWorker
from app.workers.render_worker import RenderWorker
from app.workers.chunk_worker import ChunkWorker
from app.workers.extraction_worker import ExtractionWorker, CandidateChange
from app.workers.validation_worker import ValidationWorker, ValidationResult
from app.workers.write_gate import WriteGate, WriteDecision
from app.workers.commit_engine import CommitEngine

logger = logging.getLogger(__name__)


def structured_log(level: str, event: str, **kwargs) -> None:
    """
    Emit structured log message with context.

    PRC-6: Logs include job_id, doc_id, run_id in JSON format.

    Usage:
        structured_log("INFO", "job_started", job_id="abc", source="federal_register")
    """
    log_data = {
        "event": event,
        "timestamp": datetime.utcnow().isoformat(),
        **kwargs
    }

    # Format as JSON for machine parsing
    message = json.dumps(log_data)

    if level == "DEBUG":
        logger.debug(message)
    elif level == "INFO":
        logger.info(message)
    elif level == "WARNING":
        logger.warning(message)
    elif level == "ERROR":
        logger.error(message)
    else:
        logger.info(message)


class DocumentPipeline:
    """
    Orchestrates the full document processing pipeline.

    Pipeline stages:
    1. FETCH: Download document, compute hash, store raw bytes
    2. RENDER: Convert to canonical line-numbered text
    3. CHUNK: Split into semantic chunks for RAG
    4. EXTRACT: Extract tariff changes (XML tables + LLM)
    5. VALIDATE: Verify extractions against source
    6. COMMIT: Pass write gate, store with evidence

    Usage:
        pipeline = DocumentPipeline()

        # Process a single job
        result = pipeline.process_job(job)

        # Process from URL directly
        result = pipeline.process_url(
            source="federal_register",
            external_id="2024-21217",
            url="https://..."
        )

        # Process all queued jobs
        pipeline.process_queue(max_jobs=10)
    """

    def __init__(self):
        self.fetch_worker = FetchWorker()
        self.render_worker = RenderWorker()
        self.chunk_worker = ChunkWorker()
        self.extraction_worker = ExtractionWorker()
        self.validation_worker = ValidationWorker()
        self.write_gate = WriteGate()
        self.commit_engine = CommitEngine()

    def process_job(self, job: IngestJob) -> dict:
        """
        Process a single ingest job through the full pipeline.

        Args:
            job: IngestJob to process

        Returns:
            Dict with processing results
        """
        result = {
            "job_id": str(job.id),
            "status": "started",
            "document_id": None,
            "chunks_created": 0,
            "changes_extracted": 0,
            "changes_validated": 0,
            "changes_committed": 0,
            "errors": [],
            "warnings": [],
        }

        # PRC-6: Structured logging with job context
        job_context = {
            "job_id": str(job.id),
            "external_id": job.external_id,
            "source": job.source,
        }

        try:
            # Stage 1: Fetch
            structured_log("INFO", "stage_started", stage="fetch", **job_context)
            doc = self.fetch_worker.process_job(job)

            if not doc:
                # Check if this was an already processed duplicate
                if job.status == "already_processed":
                    structured_log("INFO", "job_already_processed", **job_context)
                    result["status"] = "already_processed"
                    return result
                structured_log("ERROR", "fetch_failed", **job_context)
                result["status"] = "failed"
                result["errors"].append("Fetch failed - see job error_message")
                return result

            result["document_id"] = str(doc.id)
            job_context["doc_id"] = str(doc.id)
            structured_log("INFO", "fetch_complete", content_hash=doc.content_hash, **job_context)

            # Stage 2: Render
            structured_log("INFO", "stage_started", stage="render", **job_context)
            if not self.render_worker.process(doc, job):
                structured_log("ERROR", "render_failed", **job_context)
                result["status"] = "failed"
                result["errors"].append("Render failed")
                return result
            structured_log("INFO", "render_complete", **job_context)

            # Stage 3: Chunk
            structured_log("INFO", "stage_started", stage="chunk", **job_context)
            chunk_count = self.chunk_worker.process(doc, job)
            result["chunks_created"] = chunk_count
            structured_log("INFO", "chunk_complete", chunks_created=chunk_count, **job_context)

            # Stage 4: Extract
            structured_log("INFO", "stage_started", stage="extract", **job_context)
            candidates = self.extraction_worker.extract_from_document(doc, job)
            result["changes_extracted"] = len(candidates)
            structured_log("INFO", "extract_complete", changes_extracted=len(candidates), **job_context)

            if not candidates:
                structured_log("INFO", "no_changes_extracted", **job_context)
                job.status = "completed_no_changes"
                db.session.commit()
                result["status"] = "completed_no_changes"
                return result

            # Stage 5 & 6: Validate and Commit
            structured_log("INFO", "stage_started", stage="validate_commit", **job_context)
            committed = self._validate_and_commit(candidates, doc, job, result)
            result["changes_committed"] = committed

            # Final status
            if committed > 0:
                job.status = "committed"
                job.changes_committed = committed
                result["status"] = "committed"
            elif result["changes_validated"] > 0:
                job.status = "needs_review"
                result["status"] = "needs_review"
            else:
                job.status = "validation_failed"
                result["status"] = "validation_failed"

            job.completed_at = datetime.utcnow()
            db.session.commit()

            structured_log(
                "INFO", "pipeline_complete",
                status=result["status"],
                changes_committed=committed,
                changes_extracted=len(candidates),
                changes_validated=result.get("changes_validated", 0),
                needs_review=result.get("needs_review", 0),
                **job_context
            )

        except Exception as e:
            structured_log(
                "ERROR", "pipeline_error",
                error=str(e),
                error_type=type(e).__name__,
                **job_context
            )
            logger.exception(f"[{job.external_id}] Pipeline error: {e}")
            job.mark_failed(str(e))
            db.session.commit()
            result["status"] = "failed"
            result["errors"].append(str(e))

        return result

    def _validate_and_commit(self, candidates: List[CandidateChange],
                            doc: OfficialDocument,
                            job: IngestJob,
                            result: dict,
                            run_id: Optional[str] = None) -> int:
        """
        Validate candidates and commit approved ones.

        Returns number of committed changes.
        """
        committed = 0
        needs_review = 0

        # Context for structured logging
        commit_context = {
            "job_id": str(job.id),
            "doc_id": str(doc.id),
            "run_id": run_id,
        }

        for candidate in candidates:
            # Validate
            validation = self.validation_worker.validate(candidate, doc)

            if validation.is_valid:
                result["changes_validated"] = result.get("changes_validated", 0) + 1

                # Write gate check
                decision = self.write_gate.check(candidate, validation, doc)

                if decision.approved:
                    # Save evidence packet
                    if decision.evidence_packet:
                        db.session.add(decision.evidence_packet)
                        db.session.flush()  # Get evidence ID

                    # Commit to tariff tables using CommitEngine
                    success, record_id, error = self.commit_engine.commit_candidate(
                        candidate=candidate,
                        evidence=decision.evidence_packet,
                        doc=doc,
                        job=job,
                        run_id=run_id,
                    )

                    if success:
                        committed += 1
                        structured_log(
                            "INFO", "commit_success",
                            hts_code=candidate.hts_code,
                            record_id=record_id,
                            program=candidate.program,
                            has_schedule=candidate.has_staged_rates(),
                            **commit_context
                        )
                    else:
                        # Failed to commit - store for review
                        self.commit_engine.store_for_review(
                            candidate=candidate,
                            doc=doc,
                            job=job,
                            run_id=run_id,
                            reason=f"Commit failed: {error}",
                        )
                        needs_review += 1
                        structured_log(
                            "WARNING", "commit_failed",
                            hts_code=candidate.hts_code,
                            error=error,
                            **commit_context
                        )
                        result["warnings"].append(f"Commit failed for {candidate.hts_code}: {error}")

                    if decision.warnings:
                        result["warnings"].extend(decision.warnings)
                else:
                    # Write gate rejected - store for review
                    self.commit_engine.store_for_review(
                        candidate=candidate,
                        doc=doc,
                        job=job,
                        run_id=run_id,
                        reason=f"Write gate rejected: {decision.reason}",
                    )
                    needs_review += 1
                    structured_log(
                        "WARNING", "write_gate_rejected",
                        hts_code=candidate.hts_code,
                        reason=decision.reason,
                        **commit_context
                    )
                    result["warnings"].append(
                        f"Write gate rejected {candidate.hts_code}: {decision.reason}"
                    )
            else:
                # Validation failed - store for review
                self.commit_engine.store_for_review(
                    candidate=candidate,
                    doc=doc,
                    job=job,
                    run_id=run_id,
                    reason=f"Validation failed: {validation.reason}",
                    validation_errors={"reason": validation.reason},
                )
                needs_review += 1
                structured_log(
                    "WARNING", "validation_failed",
                    hts_code=candidate.hts_code,
                    reason=validation.reason,
                    **commit_context
                )
                result["warnings"].append(
                    f"Validation failed for {candidate.hts_code}: {validation.reason}"
                )

        result["needs_review"] = needs_review
        return committed

    def process_url(self, source: str, external_id: str, url: str,
                   metadata: dict = None) -> dict:
        """
        Process a document directly from URL.

        Creates an IngestJob and processes it.

        Args:
            source: Source identifier (federal_register, cbp_csms, etc.)
            external_id: External document ID
            url: URL to fetch
            metadata: Optional metadata dict

        Returns:
            Processing result dict
        """
        # Create job
        job = IngestJob(
            source=source,
            external_id=external_id,
            url=url,
            discovered_at=datetime.utcnow(),
            discovered_by="manual",
            status="queued",
        )
        db.session.add(job)
        db.session.commit()

        # Process
        return self.process_job(job)

    def process_queue(self, max_jobs: int = 10,
                     source_filter: str = None) -> List[dict]:
        """
        Process queued jobs from the database.

        Uses DB locking to prevent duplicate processing.

        Args:
            max_jobs: Maximum jobs to process
            source_filter: Optional source to filter by

        Returns:
            List of processing results
        """
        results = []

        for _ in range(max_jobs):
            # Claim next job
            job = IngestJob.claim_next(source_filter)

            if not job:
                logger.info("No more queued jobs")
                break

            result = self.process_job(job)
            results.append(result)

        return results

    def reprocess_document(self, doc_id: str) -> dict:
        """
        Reprocess an existing document.

        Useful when extraction logic is updated.

        Args:
            doc_id: OfficialDocument ID

        Returns:
            Processing result dict
        """
        doc = OfficialDocument.query.get(doc_id)
        if not doc:
            return {"status": "error", "message": "Document not found"}

        # Create reprocessing job
        job = IngestJob(
            source=doc.source,
            external_id=doc.external_id,
            url=doc.xml_url or doc.pdf_url or doc.html_url,
            document_id=doc.id,
            content_hash=doc.content_hash,
            discovered_at=datetime.utcnow(),
            discovered_by="reprocess",
            processing_reason="reparse",
            status="fetched",  # Skip fetch since we have the doc
        )
        db.session.add(job)
        db.session.commit()

        # Skip fetch stage
        result = {
            "job_id": str(job.id),
            "document_id": str(doc.id),
            "status": "started",
            "chunks_created": 0,
            "changes_extracted": 0,
            "changes_validated": 0,
            "changes_committed": 0,
            "errors": [],
            "warnings": [],
        }

        try:
            # Render (in case format changed)
            self.render_worker.process(doc, job)

            # Chunk
            result["chunks_created"] = self.chunk_worker.process(doc, job)

            # Extract
            candidates = self.extraction_worker.extract_from_document(doc, job)
            result["changes_extracted"] = len(candidates)

            # Validate and commit
            committed = self._validate_and_commit(candidates, doc, job, result)
            result["changes_committed"] = committed
            result["status"] = "committed" if committed > 0 else "no_changes"

            job.status = result["status"]
            job.completed_at = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            logger.exception(f"Reprocess error: {e}")
            job.mark_failed(str(e))
            db.session.commit()
            result["status"] = "failed"
            result["errors"].append(str(e))

        return result


# Convenience function for CLI usage
def run_pipeline():
    """
    Run the pipeline from command line.

    Usage:
        python -c "from app.workers.pipeline import run_pipeline; run_pipeline()"
    """
    from app.web import create_app
    app = create_app()

    with app.app_context():
        pipeline = DocumentPipeline()
        results = pipeline.process_queue(max_jobs=50)

        print(f"\nProcessed {len(results)} jobs:")
        for r in results:
            print(f"  {r['job_id']}: {r['status']} "
                  f"({r['changes_committed']}/{r['changes_extracted']} committed)")
