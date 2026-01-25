"""
Section 301 Ingestion Processor

Automated ingestion pipeline for Section 301 data that:
1. Fetches data from official sources (USITC China Tariffs CSV, USTR FRN)
2. Creates SourceVersion records for audit trail
3. Applies SCD Type 2 logic (close old records, insert new ones)
4. Populates TariffMeasure table

Integrates with existing watchers (FederalRegisterWatcher, USITCWatcher)
and the TariffUpdatePipeline.

Data Sources:
- USITC China Tariffs CSV: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=China%20Tariffs
- USTR Federal Register Notices
- CBP CSMS Bulletins (via email or web)

Version: 1.0.0 (Phase 3)
"""

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any

import requests

from app.models.section301 import (
    SourceVersion,
    TariffMeasure,
    ExclusionClaim,
    HtsCodeHistory,
    Section301IngestionRun,
    SourceType,
    Publisher,
    RateStatus,
    HtsType,
)
from app.web.db import db

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class IngestionResult:
    """Result of an ingestion run."""
    success: bool = False
    source_version_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None

    # Statistics
    rows_processed: int = 0
    rows_added: int = 0
    rows_changed: int = 0
    rows_closed: int = 0
    rows_skipped: int = 0
    rows_error: int = 0

    # Details
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source_version_id": self.source_version_id,
            "ingestion_run_id": self.ingestion_run_id,
            "rows_processed": self.rows_processed,
            "rows_added": self.rows_added,
            "rows_changed": self.rows_changed,
            "rows_closed": self.rows_closed,
            "rows_skipped": self.rows_skipped,
            "rows_error": self.rows_error,
            "error_message": self.error_message,
            "warnings": self.warnings,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": (self.completed_at - self.started_at).total_seconds()
                if self.completed_at else None,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Ingestion {'succeeded' if self.success else 'failed'}: "
            f"processed {self.rows_processed}, added {self.rows_added}, "
            f"changed {self.rows_changed}, closed {self.rows_closed}, "
            f"skipped {self.rows_skipped}"
        )


# =============================================================================
# USITC China Tariffs CSV Processor
# =============================================================================

class USITCChinaTariffsProcessor:
    """
    Processes the USITC "China Tariffs" machine-readable CSV.

    This is a Tier 1 source that contains:
    - All HTS codes subject to Section 301
    - List assignments (List 1, 2, 3, 4A, 4B)
    - Chapter 99 headings

    CSV URL: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=China%20Tariffs
    """

    CSV_URL = "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=China%20Tariffs"

    # Rate mapping from List to rate (as of latest FR notices)
    # These can be overridden by specific FR notices
    DEFAULT_RATES = {
        "list 1": Decimal("0.25"),     # 25%
        "list 2": Decimal("0.25"),     # 25%
        "list 3": Decimal("0.25"),     # 25%
        "list 4a": Decimal("0.075"),   # 7.5% (some raised to 25%/50%/100% in 2024)
        "list 4b": Decimal("0.075"),   # 7.5%
    }

    # Note 20 original lists
    NOTE_20_LISTS = {"list 1", "list 2", "list 3", "list 4a", "list 4b"}

    def __init__(self):
        self._rate_overrides: Dict[str, Decimal] = {}

    def fetch_csv(self) -> Tuple[bytes, str]:
        """
        Fetch the China Tariffs CSV from USITC.

        Returns:
            Tuple of (content bytes, content hash)
        """
        logger.info(f"Fetching USITC China Tariffs CSV from {self.CSV_URL}")

        response = requests.get(self.CSV_URL, timeout=120)
        response.raise_for_status()

        content = response.content
        content_hash = hashlib.sha256(content).hexdigest()

        logger.info(f"Downloaded {len(content)} bytes, hash: {content_hash[:16]}...")

        return content, content_hash

    def check_for_changes(self, content_hash: str) -> bool:
        """
        Check if this CSV has already been ingested.

        Returns True if this is new content, False if already processed.
        """
        existing = SourceVersion.query.filter_by(
            source_type=SourceType.USITC_CHINA.value,
            content_hash=content_hash,
        ).first()

        return existing is None

    def ingest(
        self,
        csv_content: Optional[bytes] = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> IngestionResult:
        """
        Ingest USITC China Tariffs CSV into TariffMeasure table.

        Args:
            csv_content: Optional pre-fetched CSV content
            dry_run: If True, don't commit changes
            force: If True, process even if content hash matches

        Returns:
            IngestionResult with statistics
        """
        result = IngestionResult()

        try:
            # Fetch CSV if not provided
            if csv_content is None:
                csv_content, content_hash = self.fetch_csv()
            else:
                content_hash = hashlib.sha256(csv_content).hexdigest()

            # Check for changes
            if not force and not self.check_for_changes(content_hash):
                result.success = True
                result.rows_skipped = 1
                result.warnings.append(f"Content unchanged (hash: {content_hash[:16]})")
                result.completed_at = datetime.utcnow()
                return result

            # Create source version
            source_version = SourceVersion(
                source_type=SourceType.USITC_CHINA.value,
                publisher=Publisher.USITC.value,
                document_id=f"china_tariffs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                content_hash=content_hash,
                title="USITC China Tariffs CSV",
                notes=f"Automated ingestion from {self.CSV_URL}",
            )

            if not dry_run:
                db.session.add(source_version)
                db.session.flush()
                result.source_version_id = source_version.id

            # Create ingestion run
            ingestion_run = Section301IngestionRun(
                source_type=SourceType.USITC_CHINA.value,
                source_version_id=source_version.id if not dry_run else None,
                triggered_by="usitc_processor",
            )

            if not dry_run:
                db.session.add(ingestion_run)
                db.session.flush()
                result.ingestion_run_id = ingestion_run.id

            # Parse and process CSV
            reader = csv.DictReader(io.StringIO(csv_content.decode('utf-8')))

            for row in reader:
                result.rows_processed += 1

                try:
                    processed = self._process_row(
                        row, source_version.id if not dry_run else None, dry_run
                    )

                    if processed == "added":
                        result.rows_added += 1
                    elif processed == "changed":
                        result.rows_changed += 1
                    elif processed == "skipped":
                        result.rows_skipped += 1

                except Exception as e:
                    result.rows_error += 1
                    logger.warning(f"Error processing row {result.rows_processed}: {e}")

            # Update ingestion run
            if not dry_run:
                ingestion_run.rows_added = result.rows_added
                ingestion_run.rows_changed = result.rows_changed
                ingestion_run.rows_closed = result.rows_closed
                ingestion_run.rows_skipped = result.rows_skipped
                ingestion_run.completed_at = datetime.utcnow()
                ingestion_run.status = "success" if result.rows_error == 0 else "partial"

                db.session.commit()

            result.success = True

        except Exception as e:
            logger.error(f"USITC ingestion failed: {e}")
            result.error_message = str(e)
            result.success = False

            if not dry_run:
                db.session.rollback()

        result.completed_at = datetime.utcnow()
        return result

    def _process_row(
        self,
        row: Dict[str, str],
        source_version_id: Optional[str],
        dry_run: bool,
    ) -> str:
        """
        Process a single CSV row.

        Returns: "added", "changed", or "skipped"
        """
        # Expected columns: htsno, description, general, special, other, ...
        # The China Tariffs CSV has specific columns for List assignments

        hts_code = row.get("htsno", "").replace(".", "").strip()
        if not hts_code or len(hts_code) < 8:
            return "skipped"

        # Determine HTS type
        hts_type = HtsType.HTS10.value if len(hts_code) == 10 else HtsType.HTS8.value
        hts_8 = hts_code[:8]

        # Get list assignment (column names vary)
        list_name = None
        for col in ["list", "list_name", "china_tariff_list"]:
            if col in row and row[col]:
                list_name = row[col].lower().strip()
                break

        if not list_name:
            return "skipped"

        # Determine Chapter 99 heading from list
        ch99_heading = self._get_ch99_heading(list_name)
        if not ch99_heading:
            return "skipped"

        # Determine program (Note 20 or Note 31)
        program = "301_NOTE20" if list_name in self.NOTE_20_LISTS else "301_NOTE31"

        # Get rate
        rate = self._rate_overrides.get(list_name) or self.DEFAULT_RATES.get(list_name)

        # Check for existing measure (SCD Type 2)
        existing = TariffMeasure.query.filter_by(
            program=program,
            scope_hts_type=hts_type,
            scope_hts_value=hts_code,
        ).filter(
            TariffMeasure.effective_end.is_(None)  # Currently active
        ).first()

        if existing:
            # Check if anything changed
            if existing.additional_rate == rate and existing.ch99_heading == ch99_heading:
                return "skipped"

            # Close old record (SCD Type 2)
            if not dry_run:
                existing.effective_end = date.today()
                result = "changed"
        else:
            result = "added"

        # Insert new record
        if not dry_run:
            measure = TariffMeasure(
                program=program,
                ch99_heading=ch99_heading,
                scope_hts_type=hts_type,
                scope_hts_value=hts_code,
                additional_rate=rate,
                rate_status=RateStatus.CONFIRMED.value,
                legal_basis=f"USITC China Tariffs, {list_name}",
                effective_start=date.today(),
                effective_end=None,
                list_name=list_name,
                source_version_id=source_version_id,
            )
            db.session.add(measure)

        return result

    def _get_ch99_heading(self, list_name: str) -> Optional[str]:
        """Map list name to Chapter 99 heading."""
        # Original Note 20 codes
        ch99_map = {
            "list 1": "9903.88.01",
            "list 2": "9903.88.02",
            "list 3": "9903.88.03",
            "list 4a": "9903.88.15",
            "list 4b": "9903.88.16",
            # Note 31 (2024 Review) codes
            "list 4a facemasks": "9903.91.07",
            "list 4a medical": "9903.91.04",
            "list 4a ev": "9903.91.05",
            "list 4a battery": "9903.91.06",
            "list 4a solar": "9903.91.03",
            "list 4a semiconductor": "9903.91.20",
        }
        return ch99_map.get(list_name)

    def set_rate_override(self, list_name: str, rate: Decimal):
        """Set a rate override from a more authoritative source (USTR FRN)."""
        self._rate_overrides[list_name.lower()] = rate


# =============================================================================
# Federal Register Notice Processor
# =============================================================================

class FederalRegisterSection301Processor:
    """
    Processes USTR Federal Register Notices for Section 301 updates.

    This is a Tier 0 source (binding legal authority) that:
    - Announces rate changes
    - Specifies effective dates
    - Provides legal basis for tariff modifications

    Integrates with existing FederalRegisterWatcher.
    """

    # Patterns for extracting Section 301 info
    CH99_PATTERN = re.compile(r'9903\.\d{2}\.\d{2}')
    RATE_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*(?:percent|%)', re.IGNORECASE)
    DATE_PATTERN = re.compile(
        r'(?:effective|beginning|starting)\s+(?:on\s+)?'
        r'(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})',
        re.IGNORECASE
    )
    HTS_PATTERN = re.compile(r'\d{4}\.\d{2}(?:\.\d{2,4})?')

    def process_frn_document(
        self,
        document_text: str,
        document_number: str,
        publication_date: Optional[date] = None,
        effective_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> IngestionResult:
        """
        Process a Federal Register Notice for Section 301 updates.

        Args:
            document_text: Full text of the FR notice (XML or plain text)
            document_number: FR document number (e.g., "2024-29462")
            publication_date: Date published in FR
            effective_date: Effective date from FR metadata
            dry_run: If True, don't commit changes

        Returns:
            IngestionResult
        """
        result = IngestionResult()

        try:
            # Check if we've processed this document
            content_hash = hashlib.sha256(document_text.encode()).hexdigest()

            existing = SourceVersion.query.filter_by(
                source_type=SourceType.USTR_FRN.value,
                document_id=document_number,
            ).first()

            if existing and existing.content_hash == content_hash:
                result.success = True
                result.rows_skipped = 1
                result.warnings.append(f"Document {document_number} already processed")
                result.completed_at = datetime.utcnow()
                return result

            # Create source version (Tier 0)
            source_version = SourceVersion(
                source_type=SourceType.USTR_FRN.value,
                publisher=Publisher.USTR.value,
                document_id=document_number,
                content_hash=content_hash,
                published_at=datetime.combine(publication_date, datetime.min.time())
                    if publication_date else None,
                effective_start=effective_date,
                title=f"USTR FR Notice {document_number}",
                supersedes_source_version_id=existing.id if existing else None,
            )

            if not dry_run:
                db.session.add(source_version)
                db.session.flush()
                result.source_version_id = source_version.id

            # Extract Section 301 data from document
            extracted = self._extract_section_301_data(document_text, effective_date)

            if not extracted["hts_codes"]:
                result.warnings.append("No HTS codes found in document")
                result.success = True
                result.completed_at = datetime.utcnow()
                return result

            # Process extracted data
            for hts_code in extracted["hts_codes"]:
                result.rows_processed += 1

                try:
                    status = self._upsert_tariff_measure(
                        hts_code=hts_code,
                        rate=extracted["rate"],
                        ch99_heading=extracted["ch99_heading"],
                        effective_date=extracted["effective_date"] or date.today(),
                        legal_basis=f"FR {document_number}",
                        source_version_id=source_version.id if not dry_run else None,
                        dry_run=dry_run,
                    )

                    if status == "added":
                        result.rows_added += 1
                    elif status == "changed":
                        result.rows_changed += 1
                    elif status == "closed":
                        result.rows_closed += 1
                    else:
                        result.rows_skipped += 1

                except Exception as e:
                    result.rows_error += 1
                    logger.warning(f"Error processing HTS {hts_code}: {e}")

            if not dry_run:
                db.session.commit()

            result.success = True

        except Exception as e:
            logger.error(f"FRN processing failed: {e}")
            result.error_message = str(e)
            result.success = False

            if not dry_run:
                db.session.rollback()

        result.completed_at = datetime.utcnow()
        return result

    def _extract_section_301_data(
        self,
        document_text: str,
        default_effective_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Extract Section 301 tariff data from FR notice text.

        Returns dict with:
        - hts_codes: List of HTS codes
        - rate: Decimal rate (e.g., 0.25 for 25%)
        - ch99_heading: Chapter 99 heading
        - effective_date: Effective date
        """
        result = {
            "hts_codes": [],
            "rate": None,
            "ch99_heading": None,
            "effective_date": default_effective_date,
        }

        # Extract Chapter 99 codes
        ch99_matches = self.CH99_PATTERN.findall(document_text)
        if ch99_matches:
            result["ch99_heading"] = ch99_matches[0]

        # Extract rate
        rate_matches = self.RATE_PATTERN.findall(document_text)
        if rate_matches:
            # Use the most common rate mentioned
            from collections import Counter
            rate_counts = Counter(rate_matches)
            most_common_rate = rate_counts.most_common(1)[0][0]
            result["rate"] = Decimal(most_common_rate) / 100  # Convert percent to decimal

        # Extract HTS codes
        hts_matches = self.HTS_PATTERN.findall(document_text)
        result["hts_codes"] = list(set(hts_matches))

        # Extract effective date if not provided
        if not result["effective_date"]:
            date_matches = self.DATE_PATTERN.findall(document_text)
            if date_matches:
                try:
                    from dateutil.parser import parse
                    result["effective_date"] = parse(date_matches[0]).date()
                except Exception:
                    pass

        return result

    def _upsert_tariff_measure(
        self,
        hts_code: str,
        rate: Optional[Decimal],
        ch99_heading: Optional[str],
        effective_date: date,
        legal_basis: str,
        source_version_id: Optional[str],
        dry_run: bool,
    ) -> str:
        """
        Insert or update a tariff measure using SCD Type 2.

        Returns: "added", "changed", "closed", or "skipped"
        """
        hts_normalized = hts_code.replace(".", "").strip()
        hts_type = HtsType.HTS10.value if len(hts_normalized) == 10 else HtsType.HTS8.value

        # Check for existing active measure
        existing = TariffMeasure.query.filter_by(
            scope_hts_type=hts_type,
            scope_hts_value=hts_normalized,
        ).filter(
            TariffMeasure.effective_end.is_(None)
        ).first()

        if existing:
            # Check if rate or CH99 changed
            if existing.additional_rate == rate and existing.ch99_heading == ch99_heading:
                return "skipped"

            # Close old record
            if not dry_run:
                existing.effective_end = effective_date

            status = "changed"
        else:
            status = "added"

        # Insert new record
        if not dry_run:
            measure = TariffMeasure(
                program="301_NOTE31" if ch99_heading and ch99_heading.startswith("9903.91") else "301_NOTE20",
                ch99_heading=ch99_heading or "9903.88.03",
                scope_hts_type=hts_type,
                scope_hts_value=hts_normalized,
                additional_rate=rate,
                rate_status=RateStatus.CONFIRMED.value if rate else RateStatus.PENDING.value,
                legal_basis=legal_basis,
                effective_start=effective_date,
                effective_end=None,
                source_version_id=source_version_id,
            )
            db.session.add(measure)

        return status


# =============================================================================
# Main Section 301 Ingestion Pipeline
# =============================================================================

class Section301IngestionPipeline:
    """
    Orchestrates Section 301 data ingestion from all sources.

    Integrates with existing TariffUpdatePipeline and watchers.

    Usage:
        pipeline = Section301IngestionPipeline()

        # Full sync from USITC
        result = pipeline.sync_usitc_china_tariffs()

        # Process specific FR notice
        result = pipeline.process_federal_register_notice(doc_number="2024-29462")

        # Run automated check (integrates with existing pipeline)
        result = pipeline.run_automated_check()
    """

    def __init__(self):
        self.usitc_processor = USITCChinaTariffsProcessor()
        self.frn_processor = FederalRegisterSection301Processor()

    def sync_usitc_china_tariffs(
        self,
        dry_run: bool = False,
        force: bool = False,
    ) -> IngestionResult:
        """
        Sync Section 301 data from USITC China Tariffs CSV.

        This should be run weekly or when notified of changes.
        """
        logger.info("Starting USITC China Tariffs sync")
        return self.usitc_processor.ingest(dry_run=dry_run, force=force)

    def process_federal_register_notice(
        self,
        doc_number: str,
        dry_run: bool = False,
    ) -> IngestionResult:
        """
        Process a specific Federal Register notice.

        Args:
            doc_number: FR document number (e.g., "2024-29462")
            dry_run: If True, don't commit changes
        """
        from app.watchers.federal_register import FederalRegisterWatcher

        logger.info(f"Processing FR notice {doc_number}")

        watcher = FederalRegisterWatcher()

        try:
            # Fetch document metadata
            metadata = watcher.get_document_metadata(doc_number)

            pub_date = None
            if metadata.get("publication_date"):
                pub_date = date.fromisoformat(metadata["publication_date"])

            eff_date = None
            if metadata.get("effective_on"):
                eff_date = date.fromisoformat(metadata["effective_on"])

            # Fetch full text
            xml_text = watcher.get_document_xml(doc_number)
            if not xml_text:
                return IngestionResult(
                    success=False,
                    error_message=f"Could not fetch XML for {doc_number}",
                )

            return self.frn_processor.process_frn_document(
                document_text=xml_text,
                document_number=doc_number,
                publication_date=pub_date,
                effective_date=eff_date,
                dry_run=dry_run,
            )

        except Exception as e:
            logger.error(f"Failed to process FR notice {doc_number}: {e}")
            return IngestionResult(
                success=False,
                error_message=str(e),
            )

    def run_automated_check(
        self,
        lookback_days: int = 7,
        dry_run: bool = False,
    ) -> Dict[str, IngestionResult]:
        """
        Run automated check for new Section 301 data.

        Polls Federal Register for new notices and syncs USITC CSV.

        Args:
            lookback_days: Check notices from last N days
            dry_run: If True, don't commit changes

        Returns:
            Dict mapping source to IngestionResult
        """
        from datetime import timedelta
        from app.watchers.federal_register import FederalRegisterWatcher

        results = {}

        # Check Federal Register for new 301 notices
        logger.info(f"Checking Federal Register (last {lookback_days} days)")
        watcher = FederalRegisterWatcher()
        since_date = date.today() - timedelta(days=lookback_days)

        try:
            discovered = watcher.poll(since_date)

            # Filter to Section 301 notices only
            section_301_docs = [
                doc for doc in discovered
                if self._is_section_301_notice(doc)
            ]

            logger.info(f"Found {len(section_301_docs)} Section 301 notices")

            # Process each notice
            frn_results = []
            for doc in section_301_docs:
                result = self.process_federal_register_notice(
                    doc_number=doc.external_id,
                    dry_run=dry_run,
                )
                frn_results.append(result)

            # Aggregate FRN results
            results["federal_register"] = self._aggregate_results(frn_results)

        except Exception as e:
            logger.error(f"Federal Register check failed: {e}")
            results["federal_register"] = IngestionResult(
                success=False,
                error_message=str(e),
            )

        # Sync USITC China Tariffs
        logger.info("Syncing USITC China Tariffs CSV")
        results["usitc_china_tariffs"] = self.sync_usitc_china_tariffs(dry_run=dry_run)

        return results

    def _is_section_301_notice(self, doc) -> bool:
        """Check if a discovered document is a Section 301 notice."""
        title = (doc.title or "").lower()
        keywords = ["section 301", "china tariff", "9903.88", "9903.91", "trade representative"]
        return any(kw in title for kw in keywords)

    def _aggregate_results(self, results: List[IngestionResult]) -> IngestionResult:
        """Aggregate multiple ingestion results into one."""
        agg = IngestionResult(success=True)

        for r in results:
            agg.rows_processed += r.rows_processed
            agg.rows_added += r.rows_added
            agg.rows_changed += r.rows_changed
            agg.rows_closed += r.rows_closed
            agg.rows_skipped += r.rows_skipped
            agg.rows_error += r.rows_error
            agg.warnings.extend(r.warnings)

            if not r.success:
                agg.success = False
                if r.error_message:
                    agg.warnings.append(r.error_message)

        agg.completed_at = datetime.utcnow()
        return agg


# =============================================================================
# Convenience Functions
# =============================================================================

_pipeline: Optional[Section301IngestionPipeline] = None


def get_section301_pipeline() -> Section301IngestionPipeline:
    """Get singleton pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = Section301IngestionPipeline()
    return _pipeline


def sync_section_301_data(dry_run: bool = False) -> Dict[str, Any]:
    """
    Entry point for "sync section 301 data" command.

    Returns summary of what was synced.
    """
    pipeline = get_section301_pipeline()
    results = pipeline.run_automated_check(dry_run=dry_run)

    return {
        "summary": "; ".join(f"{k}: {v.summary()}" for k, v in results.items()),
        "results": {k: v.as_dict() for k, v in results.items()},
    }
