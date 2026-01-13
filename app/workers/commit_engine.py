"""
Commit Engine

Writes validated tariff changes to temporal truth tables with:
- Supersession: Close old rate, insert new rate, link via supersedes_id
- Atomic transactions: All-or-nothing within a single candidate
- Audit logging: Every change recorded in tariff_audit_log
- Run tracking: Changes linked to regulatory_runs
"""

import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any, Tuple
from uuid import uuid4

from app.web.db import db
from app.web.db.models.tariff_tables import Section301Rate, Section232Rate, IeepaRate
from app.models import (
    OfficialDocument,
    IngestJob,
    EvidencePacket,
    RegulatoryRunChange,
    TariffAuditLog,
    CandidateChangeRecord,
)
from app.workers.extraction_worker import CandidateChange

logger = logging.getLogger(__name__)


class CommitEngine:
    """
    Writes validated changes to temporal truth tables with supersession.

    Supersession logic:
    1. Find existing active row(s) that overlap the new effective window
    2. Close them by setting effective_end = new.effective_start
    3. Insert the new row with supersedes_id link
    4. Write audit log + run_changes record

    All operations are atomic per candidate.
    """

    def commit_candidate(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Commit a single validated candidate change.

        Args:
            candidate: The extracted change to commit
            evidence: Evidence packet linking to source document
            doc: Source document
            job: Processing job
            run_id: Optional regulatory run ID for tracking

        Returns:
            Tuple of (success, record_id, error_message)
        """
        program = self._detect_program(candidate)

        try:
            if program == "section_301":
                return self._commit_301(candidate, evidence, doc, job, run_id)
            elif program in ("section_232_steel", "section_232_aluminum", "section_232_copper"):
                return self._commit_232(candidate, evidence, doc, job, run_id, program)
            elif program in ("ieepa_fentanyl", "ieepa_reciprocal"):
                return self._commit_ieepa(candidate, evidence, doc, job, run_id, program)
            else:
                logger.warning(f"Unknown program for candidate: {program}")
                return False, None, f"Unknown program: {program}"

        except Exception as e:
            logger.exception(f"Commit failed for {candidate.hts_code}: {e}")
            db.session.rollback()
            return False, None, str(e)

    def _detect_program(self, candidate: CandidateChange) -> str:
        """Detect the tariff program from the candidate data."""
        ch99 = candidate.new_chapter_99_code or ""

        # Section 301 codes
        if ch99.startswith("9903.88") or ch99.startswith("9903.91"):
            return "section_301"

        # Section 232 codes
        if ch99.startswith("9903.80") or ch99.startswith("9903.81"):
            return "section_232_steel"
        if ch99.startswith("9903.85"):
            return "section_232_aluminum"
        if ch99.startswith("9903.78"):
            return "section_232_copper"

        # IEEPA codes
        if ch99.startswith("9903.01") or "fentanyl" in str(candidate.program or "").lower():
            return "ieepa_fentanyl"
        if ch99.startswith("9903.02") or "reciprocal" in str(candidate.program or "").lower():
            return "ieepa_reciprocal"

        # Default to 301 if we have a 9903 code
        if ch99.startswith("9903"):
            return "section_301"

        return "unknown"

    def _commit_301(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Commit Section 301 rate with supersession.

        Supports both:
        - Single-rate commits (using candidate.rate + candidate.effective_date)
        - Multi-row schedule commits (using candidate.rate_schedule)
        """

        hts_8digit = candidate.hts_code.replace(".", "")[:8]
        chapter_99_code = candidate.new_chapter_99_code

        # Check if we have a rate schedule (multiple staged rates)
        if candidate.rate_schedule and len(candidate.rate_schedule) > 0:
            return self._commit_301_schedule(
                candidate, evidence, doc, job, run_id, hts_8digit, chapter_99_code
            )

        # Single-rate path (backwards compatible)
        duty_rate = Decimal(str(candidate.rate)) if candidate.rate else Decimal("0")
        effective_date = candidate.effective_date

        if not effective_date:
            return False, None, "Missing effective_date"

        with db.session.begin_nested():
            # Find existing active row(s) for this HTS code
            existing = Section301Rate.query.filter(
                Section301Rate.hts_8digit == hts_8digit,
                Section301Rate.effective_end.is_(None)  # Currently active
            ).all()

            supersedes_id = None
            action = "INSERT"

            # Close any overlapping active rates
            for old_rate in existing:
                # Only close if the new rate actually supersedes (same or overlapping coverage)
                if old_rate.effective_start <= effective_date:
                    old_rate.effective_end = effective_date
                    supersedes_id = old_rate.id
                    action = "SUPERSEDE"
                    logger.info(
                        f"Superseding 301 rate {old_rate.id}: "
                        f"{old_rate.hts_8digit} @ {old_rate.duty_rate} "
                        f"(effective_end set to {effective_date})"
                    )

            # Insert new rate
            new_rate = Section301Rate(
                hts_8digit=hts_8digit,
                hts_10digit=candidate.hts_code.replace(".", "") if len(candidate.hts_code.replace(".", "")) > 8 else None,
                chapter_99_code=chapter_99_code,
                duty_rate=duty_rate,
                effective_start=effective_date,
                effective_end=None,
                list_name=candidate.list_name if hasattr(candidate, "list_name") else None,
                sector=candidate.sector if hasattr(candidate, "sector") else None,
                source_doc=doc.external_id,
                supersedes_id=supersedes_id,
                created_by="system",
            )
            db.session.add(new_rate)
            db.session.flush()

            # Update superseded_by on old rate
            if supersedes_id:
                old_rate = Section301Rate.query.get(supersedes_id)
                if old_rate:
                    old_rate.superseded_by_id = new_rate.id

            # Write audit log
            self._write_audit_log(
                table_name="section_301_rates",
                record_id=str(new_rate.id),
                action=action,
                old_values=existing[0].as_dict() if existing else None,
                new_values=new_rate.as_dict(),
                doc=doc,
                evidence=evidence,
                job=job,
                run_id=run_id,
            )

            # Write run change record
            if run_id:
                self._write_run_change(
                    run_id=run_id,
                    program="section_301",
                    hts_8digit=hts_8digit,
                    chapter_99_code=chapter_99_code,
                    duty_rate=duty_rate,
                    effective_start=effective_date,
                    action=action,
                    reason=f"From {doc.source} {doc.external_id}",
                    doc=doc,
                    evidence=evidence,
                    target_record_id=str(new_rate.id),
                    supersedes_record_id=str(supersedes_id) if supersedes_id else None,
                )

        db.session.commit()
        logger.info(f"Committed 301 rate: {hts_8digit} @ {duty_rate} ({action})")
        return True, str(new_rate.id), None

    def _commit_301_schedule(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str],
        hts_8digit: str,
        chapter_99_code: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Commit a scheduled series of Section 301 rates.

        Creates multiple temporal rows from rate_schedule, chained via supersedes_id.
        Example: 25% Jan 2025 → 50% Jan 2026 creates two linked rows.
        """
        schedule = candidate.rate_schedule
        if not schedule:
            return False, None, "Empty rate_schedule"

        created_ids = []
        previous_rate = None

        with db.session.begin_nested():
            # First, find and close any existing active rates
            existing = Section301Rate.query.filter(
                Section301Rate.hts_8digit == hts_8digit,
                Section301Rate.effective_end.is_(None)
            ).all()

            first_effective = schedule[0].effective_start
            supersedes_id = None

            for old_rate in existing:
                if old_rate.effective_start <= first_effective:
                    old_rate.effective_end = first_effective
                    supersedes_id = old_rate.id
                    logger.info(
                        f"Superseding 301 rate {old_rate.id} with schedule: "
                        f"{old_rate.hts_8digit} @ {old_rate.duty_rate}"
                    )

            # Create each segment in the schedule
            for i, segment in enumerate(schedule):
                new_rate = Section301Rate(
                    hts_8digit=hts_8digit,
                    hts_10digit=candidate.hts_code.replace(".", "") if len(candidate.hts_code.replace(".", "")) > 8 else None,
                    chapter_99_code=chapter_99_code,
                    duty_rate=segment.rate,
                    effective_start=segment.effective_start,
                    effective_end=segment.effective_end,  # Already computed in extraction
                    list_name=candidate.list_name if hasattr(candidate, "list_name") else None,
                    sector=candidate.sector if hasattr(candidate, "sector") else None,
                    source_doc=doc.external_id,
                    supersedes_id=supersedes_id if i == 0 else previous_rate.id if previous_rate else None,
                    created_by="system",
                )
                db.session.add(new_rate)
                db.session.flush()

                # Link previous rate to this one
                if previous_rate:
                    previous_rate.superseded_by_id = new_rate.id

                created_ids.append(str(new_rate.id))

                # Write audit log for each segment
                self._write_audit_log(
                    table_name="section_301_rates",
                    record_id=str(new_rate.id),
                    action="INSERT_SCHEDULE" if i == 0 else "INSERT_SCHEDULE_SEGMENT",
                    old_values=None,
                    new_values=new_rate.as_dict(),
                    doc=doc,
                    evidence=evidence,
                    job=job,
                    run_id=run_id,
                )

                # Write run change record
                if run_id:
                    self._write_run_change(
                        run_id=run_id,
                        program="section_301",
                        hts_8digit=hts_8digit,
                        chapter_99_code=chapter_99_code,
                        duty_rate=segment.rate,
                        effective_start=segment.effective_start,
                        action="INSERT_SCHEDULE" if i == 0 else "INSERT_SCHEDULE_SEGMENT",
                        reason=f"From {doc.source} {doc.external_id} (segment {i+1}/{len(schedule)})",
                        doc=doc,
                        evidence=evidence,
                        target_record_id=str(new_rate.id),
                        supersedes_record_id=str(supersedes_id) if i == 0 and supersedes_id else None,
                    )

                previous_rate = new_rate

            # Update superseded_by on original superseded rate
            if supersedes_id and created_ids:
                old_rate = Section301Rate.query.get(supersedes_id)
                if old_rate:
                    old_rate.superseded_by_id = int(created_ids[0])

        db.session.commit()
        logger.info(
            f"Committed 301 rate schedule: {hts_8digit} with {len(schedule)} segments "
            f"({[float(s.rate) for s in schedule]})"
        )
        return True, ",".join(created_ids), None

    def _commit_232(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str],
        program: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Commit Section 232 rate with supersession.

        Note: Section 232 rarely has staged rates, but supports it for completeness.
        """

        hts_8digit = candidate.hts_code.replace(".", "")[:8]

        # Determine material type from program
        material_type = program.replace("section_232_", "")

        chapter_99_claim = candidate.new_chapter_99_code
        country_code = getattr(candidate, "country_code", None)
        article_type = getattr(candidate, "article_type", None)

        # Check for rate schedule (rare for 232, but supported)
        if candidate.rate_schedule and len(candidate.rate_schedule) > 0:
            return self._commit_232_schedule(
                candidate, evidence, doc, job, run_id, program,
                hts_8digit, material_type, chapter_99_claim, country_code, article_type
            )

        duty_rate = Decimal(str(candidate.rate)) if candidate.rate else Decimal("0")
        effective_date = candidate.effective_date

        if not effective_date:
            return False, None, "Missing effective_date"

        with db.session.begin_nested():
            # Find existing active row(s)
            query = Section232Rate.query.filter(
                Section232Rate.hts_8digit == hts_8digit,
                Section232Rate.material_type == material_type,
                Section232Rate.effective_end.is_(None)
            )
            if country_code:
                query = query.filter(Section232Rate.country_code == country_code)
            else:
                query = query.filter(Section232Rate.country_code.is_(None))

            existing = query.all()
            supersedes_id = None
            action = "INSERT"

            for old_rate in existing:
                if old_rate.effective_start <= effective_date:
                    old_rate.effective_end = effective_date
                    supersedes_id = old_rate.id
                    action = "SUPERSEDE"

            # Insert new rate
            new_rate = Section232Rate(
                hts_8digit=hts_8digit,
                material_type=material_type,
                chapter_99_claim=chapter_99_claim,
                duty_rate=duty_rate,
                country_code=country_code,
                article_type=article_type,
                effective_start=effective_date,
                effective_end=None,
                source_doc=doc.external_id,
                created_by="system",
            )
            db.session.add(new_rate)
            db.session.flush()

            # Write audit log
            self._write_audit_log(
                table_name="section_232_rates",
                record_id=str(new_rate.id),
                action=action,
                old_values=existing[0].as_dict() if existing else None,
                new_values=new_rate.as_dict(),
                doc=doc,
                evidence=evidence,
                job=job,
                run_id=run_id,
            )

            if run_id:
                self._write_run_change(
                    run_id=run_id,
                    program=program,
                    hts_8digit=hts_8digit,
                    chapter_99_code=chapter_99_claim,
                    duty_rate=duty_rate,
                    effective_start=effective_date,
                    action=action,
                    reason=f"From {doc.source} {doc.external_id}",
                    doc=doc,
                    evidence=evidence,
                    target_record_id=str(new_rate.id),
                    supersedes_record_id=str(supersedes_id) if supersedes_id else None,
                    material_type=material_type,
                )

        db.session.commit()
        logger.info(f"Committed 232 rate: {hts_8digit} ({material_type}) @ {duty_rate} ({action})")
        return True, str(new_rate.id), None

    def _commit_232_schedule(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str],
        program: str,
        hts_8digit: str,
        material_type: str,
        chapter_99_claim: str,
        country_code: Optional[str],
        article_type: Optional[str],
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Commit a scheduled series of Section 232 rates (rare but supported)."""
        schedule = candidate.rate_schedule
        if not schedule:
            return False, None, "Empty rate_schedule"

        created_ids = []
        previous_rate = None

        with db.session.begin_nested():
            # Find and close existing active rates
            query = Section232Rate.query.filter(
                Section232Rate.hts_8digit == hts_8digit,
                Section232Rate.material_type == material_type,
                Section232Rate.effective_end.is_(None)
            )
            if country_code:
                query = query.filter(Section232Rate.country_code == country_code)

            existing = query.all()
            first_effective = schedule[0].effective_start
            supersedes_id = None

            for old_rate in existing:
                if old_rate.effective_start <= first_effective:
                    old_rate.effective_end = first_effective
                    supersedes_id = old_rate.id

            for i, segment in enumerate(schedule):
                new_rate = Section232Rate(
                    hts_8digit=hts_8digit,
                    material_type=material_type,
                    chapter_99_claim=chapter_99_claim,
                    duty_rate=segment.rate,
                    country_code=country_code,
                    article_type=article_type,
                    effective_start=segment.effective_start,
                    effective_end=segment.effective_end,
                    source_doc=doc.external_id,
                    created_by="system",
                )
                db.session.add(new_rate)
                db.session.flush()

                if previous_rate:
                    previous_rate.superseded_by_id = new_rate.id

                created_ids.append(str(new_rate.id))
                previous_rate = new_rate

        db.session.commit()
        logger.info(f"Committed 232 rate schedule: {hts_8digit} with {len(schedule)} segments")
        return True, ",".join(created_ids), None

    def _commit_ieepa(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str],
        program: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Commit IEEPA rate with supersession.

        Note: IEEPA rates are typically not staged, but schedule support is included.
        """

        program_type = "fentanyl" if "fentanyl" in program else "reciprocal"
        chapter_99_code = candidate.new_chapter_99_code
        country_code = getattr(candidate, "country_code", None)
        variant = getattr(candidate, "variant", None)

        # Check for rate schedule (very rare for IEEPA, but supported)
        if candidate.rate_schedule and len(candidate.rate_schedule) > 0:
            return self._commit_ieepa_schedule(
                candidate, evidence, doc, job, run_id, program,
                program_type, chapter_99_code, country_code, variant
            )

        duty_rate = Decimal(str(candidate.rate)) if candidate.rate else Decimal("0")
        effective_date = candidate.effective_date

        if not effective_date:
            return False, None, "Missing effective_date"

        with db.session.begin_nested():
            # Find existing active row(s)
            query = IeepaRate.query.filter(
                IeepaRate.program_type == program_type,
                IeepaRate.chapter_99_code == chapter_99_code,
                IeepaRate.effective_end.is_(None)
            )
            if country_code:
                query = query.filter(IeepaRate.country_code == country_code)
            else:
                query = query.filter(IeepaRate.country_code.is_(None))

            existing = query.all()
            action = "INSERT"

            for old_rate in existing:
                if old_rate.effective_start <= effective_date:
                    old_rate.effective_end = effective_date
                    action = "SUPERSEDE"

            # Insert new rate
            new_rate = IeepaRate(
                program_type=program_type,
                country_code=country_code,
                chapter_99_code=chapter_99_code,
                duty_rate=duty_rate,
                variant=variant,
                effective_start=effective_date,
                effective_end=None,
                source_doc=doc.external_id,
                created_by="system",
            )
            db.session.add(new_rate)
            db.session.flush()

            self._write_audit_log(
                table_name="ieepa_rates",
                record_id=str(new_rate.id),
                action=action,
                old_values=existing[0].as_dict() if existing else None,
                new_values=new_rate.as_dict(),
                doc=doc,
                evidence=evidence,
                job=job,
                run_id=run_id,
            )

            if run_id:
                self._write_run_change(
                    run_id=run_id,
                    program=program,
                    hts_8digit="",  # IEEPA doesn't use HTS-specific rates
                    chapter_99_code=chapter_99_code,
                    duty_rate=duty_rate,
                    effective_start=effective_date,
                    action=action,
                    reason=f"From {doc.source} {doc.external_id}",
                    doc=doc,
                    evidence=evidence,
                    target_record_id=str(new_rate.id),
                    country_scope=country_code,
                )

        db.session.commit()
        logger.info(f"Committed IEEPA rate: {program_type} @ {duty_rate} ({action})")
        return True, str(new_rate.id), None

    def _commit_ieepa_schedule(
        self,
        candidate: CandidateChange,
        evidence: EvidencePacket,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str],
        program: str,
        program_type: str,
        chapter_99_code: str,
        country_code: Optional[str],
        variant: Optional[str],
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Commit a scheduled series of IEEPA rates (very rare but supported)."""
        schedule = candidate.rate_schedule
        if not schedule:
            return False, None, "Empty rate_schedule"

        created_ids = []
        previous_rate = None

        with db.session.begin_nested():
            # Find and close existing active rates
            query = IeepaRate.query.filter(
                IeepaRate.program_type == program_type,
                IeepaRate.chapter_99_code == chapter_99_code,
                IeepaRate.effective_end.is_(None)
            )
            if country_code:
                query = query.filter(IeepaRate.country_code == country_code)

            existing = query.all()
            first_effective = schedule[0].effective_start

            for old_rate in existing:
                if old_rate.effective_start <= first_effective:
                    old_rate.effective_end = first_effective

            for i, segment in enumerate(schedule):
                new_rate = IeepaRate(
                    program_type=program_type,
                    country_code=country_code,
                    chapter_99_code=chapter_99_code,
                    duty_rate=segment.rate,
                    variant=variant,
                    effective_start=segment.effective_start,
                    effective_end=segment.effective_end,
                    source_doc=doc.external_id,
                    created_by="system",
                )
                db.session.add(new_rate)
                db.session.flush()

                if previous_rate:
                    previous_rate.superseded_by_id = new_rate.id

                created_ids.append(str(new_rate.id))
                previous_rate = new_rate

        db.session.commit()
        logger.info(f"Committed IEEPA rate schedule: {program_type} with {len(schedule)} segments")
        return True, ",".join(created_ids), None

    def _write_audit_log(
        self,
        table_name: str,
        record_id: str,
        action: str,
        old_values: Optional[Dict],
        new_values: Dict,
        doc: OfficialDocument,
        evidence: EvidencePacket,
        job: IngestJob,
        run_id: Optional[str],
    ):
        """Write to tariff_audit_log."""
        audit = TariffAuditLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            old_values=old_values,
            new_values=new_values,
            source_doc_id=doc.id,
            evidence_id=evidence.id if evidence else None,
            job_id=job.id if job else None,
            run_id=run_id,
            performed_by="system",
        )
        db.session.add(audit)

    def _write_run_change(
        self,
        run_id: str,
        program: str,
        hts_8digit: str,
        chapter_99_code: str,
        duty_rate: Decimal,
        effective_start: date,
        action: str,
        reason: str,
        doc: OfficialDocument,
        evidence: EvidencePacket,
        target_record_id: str,
        supersedes_record_id: Optional[str] = None,
        country_scope: Optional[str] = None,
        material_type: Optional[str] = None,
    ):
        """Write to regulatory_run_changes."""
        change = RegulatoryRunChange(
            run_id=run_id,
            program=program,
            country_scope=country_scope,
            material_type=material_type,
            hts_8digit=hts_8digit,
            chapter_99_code=chapter_99_code,
            duty_rate=duty_rate,
            effective_start=effective_start,
            change_action=action,
            reason=reason,
            source_doc_id=doc.id,
            evidence_id=evidence.id if evidence else None,
            target_record_id=target_record_id,
            supersedes_record_id=supersedes_record_id,
        )
        db.session.add(change)

    def store_for_review(
        self,
        candidate: CandidateChange,
        doc: OfficialDocument,
        job: IngestJob,
        run_id: Optional[str],
        reason: str,
        validation_errors: Optional[Dict] = None,
    ) -> str:
        """
        Store a candidate change for human review.

        Used when:
        - Chapter 99 code can't be resolved
        - Validation fails
        - WriteGate rejects the change

        Returns the CandidateChangeRecord ID.
        """
        record = CandidateChangeRecord(
            job_id=job.id if job else None,
            document_id=doc.id if doc else None,
            run_id=run_id,
            hts_code=candidate.hts_code,
            chapter_99_code=candidate.new_chapter_99_code,
            duty_rate=Decimal(str(candidate.rate)) if candidate.rate else None,
            effective_date=candidate.effective_date,
            program=candidate.program if hasattr(candidate, "program") else None,
            evidence_quote=candidate.evidence_quote if hasattr(candidate, "evidence_quote") else None,
            evidence_line_start=candidate.evidence_line_start if hasattr(candidate, "evidence_line_start") else None,
            evidence_line_end=candidate.evidence_line_end if hasattr(candidate, "evidence_line_end") else None,
            extraction_method=candidate.extraction_method if hasattr(candidate, "extraction_method") else None,
            review_reason=reason,
            validation_errors=validation_errors,
            status="pending",
        )
        db.session.add(record)
        db.session.commit()

        logger.info(f"Stored for review: {candidate.hts_code} - {reason}")
        return record.id
