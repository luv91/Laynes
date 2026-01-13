"""
Write Gate: Auto-insert verified extractions into temporal tables.

Part of the dual-LLM verification pipeline:
1. Extractor (Gemini) extracts tariff data from notices
2. Verifier (GPT-4) finds exact quotes proving extraction is correct
3. Write Gate only inserts if verifier found ALL evidence quotes

Manual trigger: User says "check for tariff updates"
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from app.services.extractor_llm import TariffExtractorLLM, ExtractionResult, get_tariff_extractor
from app.services.verifier_llm import TariffVerifierLLM, VerificationResult, get_tariff_verifier

logger = logging.getLogger(__name__)

# Minimum confidence to auto-insert
MIN_CONFIDENCE_THRESHOLD = 0.85


@dataclass
class WriteResult:
    """Result of processing a document through the Write Gate."""

    # Overall status
    success: bool = False
    rows_inserted: int = 0

    # Which table was written to
    table: Optional[str] = None

    # The extraction and verification
    extraction: Optional[ExtractionResult] = None
    verification: Optional[VerificationResult] = None

    # Audit info
    document_source: Optional[str] = None
    ingestion_run_id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Errors
    error: Optional[str] = None
    skipped_reason: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "rows_inserted": self.rows_inserted,
            "table": self.table,
            "extraction": self.extraction.as_dict() if self.extraction else None,
            "verification": self.verification.as_dict() if self.verification else None,
            "document_source": self.document_source,
            "ingestion_run_id": self.ingestion_run_id,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }


class WriteGate:
    """
    Auto-insert verified extractions into temporal tables.

    Uses dual-LLM verification:
    1. Gemini extracts structured tariff data from document
    2. GPT-4 verifies by finding exact quotes in source document
    3. Only writes to database if verification passes

    Usage:
        gate = WriteGate()
        result = gate.process_document(document_text, source="CSMS #65936570")
        if result.success:
            print(f"Inserted {result.rows_inserted} rows")
    """

    def __init__(
        self,
        extractor: Optional[TariffExtractorLLM] = None,
        verifier: Optional[TariffVerifierLLM] = None,
        min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
    ):
        self.extractor = extractor or get_tariff_extractor()
        self.verifier = verifier or get_tariff_verifier()
        self.min_confidence = min_confidence

    def process_document(
        self,
        document_text: str,
        source: str,
        skip_verification: bool = False,
    ) -> WriteResult:
        """
        Process a document through extraction → verification → write.

        Args:
            document_text: Full text of the official notice
            source: Source identifier (e.g., "CSMS #65936570", "FR 2025-10524")
            skip_verification: If True, skip LLM verification (use for testing only)

        Returns:
            WriteResult with status and details
        """
        logger.info(f"WriteGate processing document: {source}")

        # Step 1: Extract
        extraction = self.extractor.extract(document_text, source)

        if not extraction.success:
            return WriteResult(
                success=False,
                error=extraction.error,
                extraction=extraction,
                document_source=source,
            )

        if not extraction.hts_codes:
            return WriteResult(
                success=False,
                skipped_reason="No HTS codes found in document",
                extraction=extraction,
                document_source=source,
            )

        if not extraction.program:
            return WriteResult(
                success=False,
                skipped_reason="Could not determine tariff program",
                extraction=extraction,
                document_source=source,
            )

        # Step 2: Verify (unless skipped)
        verification = None
        if not skip_verification:
            verification = self.verifier.verify(extraction, document_text)

            if not verification.success:
                return WriteResult(
                    success=False,
                    error=verification.error,
                    extraction=extraction,
                    verification=verification,
                    document_source=source,
                )

            if not verification.verified:
                missing = ", ".join(verification.missing_fields)
                return WriteResult(
                    success=False,
                    skipped_reason=f"Verification failed: missing evidence for {missing}",
                    extraction=extraction,
                    verification=verification,
                    document_source=source,
                )

            if verification.confidence < self.min_confidence:
                return WriteResult(
                    success=False,
                    skipped_reason=f"Confidence {verification.confidence:.2f} below threshold {self.min_confidence}",
                    extraction=extraction,
                    verification=verification,
                    document_source=source,
                )

        # Step 3: Write to temporal tables
        try:
            rows, table = self._insert_to_temporal_tables(extraction, source, verification)

            # Log ingestion run
            ingestion_id = self._log_ingestion_run(extraction, source, rows, table)

            logger.info(f"WriteGate inserted {rows} rows into {table} from {source}")

            return WriteResult(
                success=True,
                rows_inserted=rows,
                table=table,
                extraction=extraction,
                verification=verification,
                document_source=source,
                ingestion_run_id=ingestion_id,
            )

        except Exception as e:
            logger.error(f"WriteGate database error: {e}")
            return WriteResult(
                success=False,
                error=f"Database error: {str(e)}",
                extraction=extraction,
                verification=verification,
                document_source=source,
            )

    def _insert_to_temporal_tables(
        self,
        extraction: ExtractionResult,
        source: str,
        verification: Optional[VerificationResult],
    ) -> tuple:
        """
        Insert verified data into appropriate temporal table.

        Returns:
            Tuple of (rows_inserted, table_name)
        """
        from app.web.db import db
        from app.web.db.models.tariff_tables import (
            Section301Rate,
            Section232Rate,
            IeepaRate,
        )

        rows_inserted = 0
        table_name = None

        program = extraction.program

        if program == "section_301":
            table_name = "section_301_rates"
            for hts_code in extraction.hts_codes:
                hts_8 = self._normalize_hts(hts_code)[:8]

                # Check for existing rate to avoid duplicates
                existing = Section301Rate.query.filter_by(
                    hts_8digit=hts_8,
                    chapter_99_code=extraction.chapter_99_code,
                    effective_start=extraction.effective_date,
                ).first()

                if existing:
                    logger.debug(f"Skipping duplicate 301 rate for {hts_8}")
                    continue

                rate = Section301Rate(
                    hts_8digit=hts_8,
                    hts_10digit=self._normalize_hts(hts_code) if len(hts_code.replace(".", "")) == 10 else None,
                    chapter_99_code=extraction.chapter_99_code,
                    duty_rate=extraction.duty_rate,
                    effective_start=extraction.effective_date or date.today(),
                    effective_end=None,  # Currently active
                    list_name=extraction.list_name,
                    source_doc=source,
                    role="impose" if extraction.action != "remove_from_scope" else "exclude",
                    created_by="write_gate",
                )
                db.session.add(rate)
                rows_inserted += 1

        elif program.startswith("section_232"):
            table_name = "section_232_rates"
            material = extraction.material_type or program.split("_")[-1]  # steel, aluminum, copper

            for hts_code in extraction.hts_codes:
                hts_8 = self._normalize_hts(hts_code)[:8]

                # Check for existing rate
                existing = Section232Rate.query.filter_by(
                    hts_8digit=hts_8,
                    material_type=material,
                    effective_start=extraction.effective_date,
                ).first()

                if existing:
                    logger.debug(f"Skipping duplicate 232 rate for {hts_8}/{material}")
                    continue

                # Determine article type based on chapter
                chapter = int(hts_8[:2]) if hts_8[:2].isdigit() else 0
                article_type = self._determine_article_type(chapter, material)

                # Determine claim code
                claim_code = extraction.chapter_99_code or self._get_default_claim_code(material, article_type)

                rate = Section232Rate(
                    hts_8digit=hts_8,
                    material_type=material,
                    chapter_99_claim=claim_code,
                    chapter_99_disclaim=None,
                    duty_rate=extraction.duty_rate or 0.50,  # Default 50%
                    country_code=None,  # Global rate
                    article_type=article_type,
                    effective_start=extraction.effective_date or date.today(),
                    effective_end=None,
                    source_doc=source,
                    created_by="write_gate",
                )
                db.session.add(rate)
                rows_inserted += 1

        elif program.startswith("ieepa"):
            table_name = "ieepa_rates"
            program_type = program.split("_")[1]  # fentanyl, reciprocal

            # Check for existing rate
            existing = IeepaRate.query.filter_by(
                program_type=program_type,
                country_code=extraction.country_code,
                chapter_99_code=extraction.chapter_99_code,
                effective_start=extraction.effective_date,
            ).first()

            if not existing:
                rate = IeepaRate(
                    program_type=program_type,
                    country_code=extraction.country_code,
                    chapter_99_code=extraction.chapter_99_code,
                    duty_rate=extraction.duty_rate,
                    variant=None,
                    effective_start=extraction.effective_date or date.today(),
                    effective_end=None,
                    source_doc=source,
                    created_by="write_gate",
                )
                db.session.add(rate)
                rows_inserted += 1
            else:
                logger.debug(f"Skipping duplicate IEEPA rate for {program_type}/{extraction.country_code}")

        if rows_inserted > 0:
            db.session.commit()

        return rows_inserted, table_name

    def _log_ingestion_run(
        self,
        extraction: ExtractionResult,
        source: str,
        rows: int,
        table: str,
    ) -> Optional[int]:
        """Log the ingestion to ingestion_runs for audit."""
        from app.web.db import db
        from app.web.db.models.tariff_tables import IngestionRun

        try:
            run = IngestionRun(
                operator="write_gate",
                table_affected=table,
                records_added=rows,
                records_updated=0,
                records_deleted=0,
                status="success" if rows > 0 else "skipped",
                notes=f"Extracted from {source}: {len(extraction.hts_codes)} HTS codes, program={extraction.program}",
            )
            db.session.add(run)
            db.session.commit()
            return run.id
        except Exception as e:
            logger.warning(f"Failed to log ingestion run: {e}")
            return None

    def _normalize_hts(self, hts_code: str) -> str:
        """Remove dots and spaces from HTS code."""
        return hts_code.replace(".", "").replace(" ", "").strip()

    def _determine_article_type(self, chapter: int, material: str) -> str:
        """Determine article type based on HTS chapter and material."""
        if material == "steel":
            if chapter == 72:
                return "primary"
            elif chapter == 73:
                return "derivative"
            else:
                return "content"
        elif material == "aluminum":
            if chapter == 76:
                return "primary"
            else:
                return "derivative"
        elif material == "copper":
            if chapter == 74:
                return "primary"
            else:
                return "derivative"
        return "content"

    def _get_default_claim_code(self, material: str, article_type: str) -> str:
        """Get default Chapter 99 claim code for Section 232."""
        # Based on U.S. Note 16 to Chapter 99
        codes = {
            ("steel", "primary"): "9903.80.01",
            ("steel", "derivative"): "9903.81.91",
            ("steel", "content"): "9903.81.91",
            ("aluminum", "primary"): "9903.85.03",
            ("aluminum", "derivative"): "9903.85.08",
            ("aluminum", "content"): "9903.85.08",
            ("copper", "primary"): "9903.78.01",
            ("copper", "derivative"): "9903.78.01",
            ("copper", "content"): "9903.78.01",
        }
        return codes.get((material, article_type), "9903.80.01")

    def process_batch(
        self,
        documents: List[Dict[str, str]],
        skip_verification: bool = False,
    ) -> List[WriteResult]:
        """
        Process multiple documents.

        Args:
            documents: List of dicts with 'text' and 'source' keys
            skip_verification: If True, skip LLM verification

        Returns:
            List of WriteResult objects
        """
        results = []
        for doc in documents:
            result = self.process_document(
                document_text=doc["text"],
                source=doc.get("source", "unknown"),
                skip_verification=skip_verification,
            )
            results.append(result)
        return results


# Singleton instance
_write_gate = None


def get_write_gate() -> WriteGate:
    """Get the singleton WriteGate instance."""
    global _write_gate
    if _write_gate is None:
        _write_gate = WriteGate()
    return _write_gate


def check_for_tariff_updates(lookback_hours: int = 24) -> Dict[str, Any]:
    """
    Manually triggered: Check for new tariff notices.

    This is the entry point when user says "check for tariff updates".

    Args:
        lookback_hours: Check notices from last N hours (default 24)

    Returns:
        Summary of what was found and processed
    """
    from datetime import timedelta
    from app.watchers.cbp_csms import CBPCSMSWatcher
    from app.watchers.federal_register import FederalRegisterWatcher

    logger.info(f"Checking for tariff updates (lookback: {lookback_hours} hours)")

    since_date = date.today() - timedelta(hours=lookback_hours)

    results = {
        "lookback_hours": lookback_hours,
        "since_date": since_date.isoformat(),
        "notices_found": 0,
        "processed": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": [],
        "details": [],
    }

    gate = get_write_gate()

    # Poll watchers
    watchers = [
        ("cbp_csms", CBPCSMSWatcher()),
        ("federal_register", FederalRegisterWatcher()),
    ]

    for watcher_name, watcher in watchers:
        try:
            discovered = watcher.poll(since_date)
            results["notices_found"] += len(discovered)

            for doc in discovered:
                # Fetch document content
                content = watcher.fetch_bulletin_content(doc.preferred_url()) if hasattr(watcher, 'fetch_bulletin_content') else None

                if not content:
                    logger.warning(f"Could not fetch content for {doc.external_id}")
                    continue

                # Process through Write Gate
                result = gate.process_document(
                    document_text=content,
                    source=doc.external_id,
                )

                results["processed"] += 1

                if result.success:
                    results["inserted"] += result.rows_inserted
                    results["details"].append({
                        "source": doc.external_id,
                        "rows": result.rows_inserted,
                        "table": result.table,
                    })
                else:
                    results["skipped"] += 1
                    if result.error:
                        results["errors"].append({
                            "source": doc.external_id,
                            "error": result.error,
                        })

        except Exception as e:
            logger.error(f"Error polling {watcher_name}: {e}")
            results["errors"].append({
                "watcher": watcher_name,
                "error": str(e),
            })

    logger.info(
        f"Tariff update check complete: found {results['notices_found']} notices, "
        f"inserted {results['inserted']} rows, skipped {results['skipped']}"
    )

    return results
