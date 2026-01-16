"""
Write Gate

Final checkpoint before database write.
All deterministic checks MUST pass before data is committed.

This is the last line of defense against bad data.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from app.web.db import db
from app.models.document_store import OfficialDocument
from app.models.evidence import EvidencePacket
from app.models.ingest_job import IngestJob
from app.workers.extraction_worker import CandidateChange
from app.workers.validation_worker import ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class WriteDecision:
    """Decision from the write gate."""
    approved: bool
    reason: Optional[str] = None
    evidence_packet: Optional[EvidencePacket] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class WriteGate:
    """
    Final checkpoint before database write.

    Deterministic checks that MUST pass:
    1. Source is Tier A (federalregister.gov, cbp.gov, usitc.gov)
    2. Document hash is stored
    3. Evidence quote exists in canonical_text
    4. Evidence contains HTS code
    5. Evidence contains rate or Chapter 99 code
    """

    # Tier A sources - only these can write to the database
    TIER_A_SOURCES = [
        "federal_register",
        "cbp_csms",
        "usitc",
        "email_csms",  # CBP bulletins received via email (same authority as cbp_csms)
    ]

    # Tier A domains for URL verification
    TIER_A_DOMAINS = [
        "federalregister.gov",
        "govinfo.gov",
        "cbp.gov",
        "usitc.gov",
        "ustr.gov",
        "govdelivery.com",  # CBP emails link to GovDelivery bulletins
    ]

    def check(self, candidate: CandidateChange,
             validation: ValidationResult,
             doc: OfficialDocument = None) -> WriteDecision:
        """
        Determine if change can be committed.

        Args:
            candidate: The proposed change
            validation: Result from validation worker
            doc: The source document

        Returns:
            WriteDecision with approval status and evidence
        """
        # Get document if not provided
        if doc is None:
            doc = OfficialDocument.query.get(candidate.document_id)

        if not doc:
            return WriteDecision(
                approved=False,
                reason="Source document not found"
            )

        warnings = []

        # Check 1: Tier A source
        if doc.source not in self.TIER_A_SOURCES:
            return WriteDecision(
                approved=False,
                reason=f"Source '{doc.source}' is not Tier A. "
                       f"Allowed: {', '.join(self.TIER_A_SOURCES)}"
            )

        # Verify URL domain if available
        url = doc.xml_url or doc.pdf_url or doc.html_url
        if url:
            if not self._is_tier_a_domain(url):
                return WriteDecision(
                    approved=False,
                    reason=f"URL domain is not Tier A: {url}"
                )

        # Check 2: Document hash exists
        if not doc.content_hash:
            return WriteDecision(
                approved=False,
                reason="Document hash not stored - cannot verify integrity"
            )

        # Check 3: Canonical text exists
        if not doc.canonical_text:
            return WriteDecision(
                approved=False,
                reason="Document has no canonical text for evidence verification"
            )

        # Check 4: HTS code in document
        hts_clean = candidate.hts_code.replace(".", "")
        hts_in_doc = (
            candidate.hts_code in doc.canonical_text or
            hts_clean in doc.canonical_text.replace(".", "")
        )

        if not hts_in_doc:
            return WriteDecision(
                approved=False,
                reason=f"HTS code {candidate.hts_code} not found in document"
            )

        # Check 5: Rate or Chapter 99 code in document
        rate_or_code_found = False

        if candidate.rate is not None:
            rate_percent = str(int(candidate.rate * 100))
            if rate_percent in doc.canonical_text:
                rate_or_code_found = True

        if candidate.new_chapter_99_code:
            if candidate.new_chapter_99_code in doc.canonical_text:
                rate_or_code_found = True

        if not rate_or_code_found:
            return WriteDecision(
                approved=False,
                reason="Neither rate nor Chapter 99 code found in document"
            )

        # Check 6: Evidence quote (if provided)
        if candidate.evidence_quote:
            if candidate.evidence_quote not in doc.canonical_text:
                # Try normalized match
                normalized = " ".join(candidate.evidence_quote.split())
                if normalized not in " ".join(doc.canonical_text.split()):
                    warnings.append(
                        "Evidence quote not found verbatim - "
                        "using line number evidence instead"
                    )

        # Check 7: Validation passed
        if not validation.is_valid:
            return WriteDecision(
                approved=False,
                reason=f"Validation failed: {validation.reason}"
            )

        # Check 8: Minimum confidence
        if validation.confidence < 0.5:
            return WriteDecision(
                approved=False,
                reason=f"Confidence too low: {validation.confidence:.2f} (min 0.5)"
            )

        # All checks passed - create evidence packet
        evidence = self._create_evidence_packet(candidate, doc, validation)

        return WriteDecision(
            approved=True,
            evidence_packet=evidence,
            warnings=warnings
        )

    def _is_tier_a_domain(self, url: str) -> bool:
        """Check if URL is from a Tier A domain."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.TIER_A_DOMAINS)

    def _create_evidence_packet(self, candidate: CandidateChange,
                               doc: OfficialDocument,
                               validation: ValidationResult) -> EvidencePacket:
        """Create audit-grade evidence packet."""
        # Find line numbers for evidence
        line_start, line_end = self._find_evidence_lines(
            doc.canonical_text,
            candidate
        )

        # Use corrected lines from validation if available
        if validation.corrected_lines:
            line_start, line_end = validation.corrected_lines

        # Get context lines
        context_before, context_after = self._get_context(
            doc.canonical_text,
            line_start,
            line_end,
            context_lines=20
        )

        # Create evidence packet
        evidence = EvidencePacket(
            document_id=doc.id,
            document_hash=doc.content_hash,
            line_start=line_start,
            line_end=line_end,
            quote_text=candidate.evidence_quote or self._extract_quote(
                doc.canonical_text, line_start, line_end
            ),
            context_before=context_before,
            context_after=context_after,
            proves_hts_code=candidate.hts_code,
            proves_chapter_99=candidate.new_chapter_99_code,
            proves_rate=candidate.rate,
            proves_effective_date=candidate.effective_date,
            verified_by="write_gate",
            verified_at=datetime.utcnow(),
            confidence_score=validation.confidence,
        )

        return evidence

    def _find_evidence_lines(self, canonical_text: str,
                            candidate: CandidateChange) -> tuple:
        """Find the line numbers containing the evidence."""
        # Use stored line numbers if available
        if candidate.evidence_line_start > 0:
            return (candidate.evidence_line_start, candidate.evidence_line_end)

        # Search for HTS code
        lines = canonical_text.split('\n')
        hts_clean = candidate.hts_code.replace(".", "")

        for i, line in enumerate(lines):
            match = re.match(r'L(\d+):\s*(.*)', line)
            if match:
                line_num = int(match.group(1))
                content = match.group(2)

                if hts_clean in content.replace(".", "").replace(" ", ""):
                    # Found HTS code, look for rate/chapter_99 nearby
                    start = max(0, i - 5)
                    end = min(len(lines), i + 5)

                    return (line_num, line_num)

        return (0, 0)

    def _get_context(self, canonical_text: str,
                    line_start: int, line_end: int,
                    context_lines: int = 20) -> tuple:
        """Get context lines before and after evidence."""
        lines = canonical_text.split('\n')

        # Build line number to index mapping
        line_to_idx = {}
        for i, line in enumerate(lines):
            match = re.match(r'L(\d+):', line)
            if match:
                line_to_idx[int(match.group(1))] = i

        # Find indices
        start_idx = line_to_idx.get(line_start, 0)
        end_idx = line_to_idx.get(line_end, start_idx)

        # Get context
        context_start = max(0, start_idx - context_lines)
        context_end = min(len(lines), end_idx + context_lines + 1)

        before = '\n'.join(lines[context_start:start_idx])
        after = '\n'.join(lines[end_idx + 1:context_end])

        return (before, after)

    def _extract_quote(self, canonical_text: str,
                      line_start: int, line_end: int) -> str:
        """Extract quote text from line range."""
        lines = canonical_text.split('\n')
        quote_lines = []

        for line in lines:
            match = re.match(r'L(\d+):\s*(.*)', line)
            if match:
                line_num = int(match.group(1))
                if line_start <= line_num <= line_end:
                    quote_lines.append(match.group(2))

        return '\n'.join(quote_lines)

    def approve_and_commit(self, candidate: CandidateChange,
                          validation: ValidationResult,
                          job: IngestJob = None) -> WriteDecision:
        """
        Check and commit if approved.

        This is a convenience method that:
        1. Runs the gate check
        2. If approved, saves the evidence packet
        3. Updates job status

        Returns:
            WriteDecision with commit status
        """
        decision = self.check(candidate, validation)

        if decision.approved and decision.evidence_packet:
            try:
                db.session.add(decision.evidence_packet)
                db.session.flush()

                logger.info(
                    f"Write gate approved: HTS {candidate.hts_code} "
                    f"from doc {candidate.document_id}"
                )

                if job:
                    job.status = "committed"
                    job.changes_committed = (job.changes_committed or 0) + 1

                db.session.commit()

            except Exception as e:
                db.session.rollback()
                logger.error(f"Commit failed: {e}")
                return WriteDecision(
                    approved=False,
                    reason=f"Database commit failed: {e}"
                )

        return decision
