"""
Write Gate (v10.0 Phase 3)

Mechanical proof checks before writing to verified_assertion.
Even without regex/rules, we need deterministic verification:

1. Document exists - document_id exists in document table
2. Chunk exists - chunk_id exists in document_chunk table
3. Tier A only - document.tier == 'A'
4. Quote exists - quote is exact substring of chunk.text
5. Validator passed - verified == true from Validator LLM
6. (Optional) Multiple sources - at least 2 citations for high-confidence

If ALL pass: Write to verified_assertion
If ANY fail: Write to needs_review_queue
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session


@dataclass
class WriteGateCheck:
    """Result of a single Write Gate check."""
    check_name: str
    passed: bool
    message: str
    severity: str = "error"  # error, warning


@dataclass
class WriteGateResult:
    """Full result from Write Gate."""
    passed: bool
    checks: List[WriteGateCheck] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {
                    "check_name": c.check_name,
                    "passed": c.passed,
                    "message": c.message,
                    "severity": c.severity,
                }
                for c in self.checks
            ],
            "errors": self.errors,
            "warnings": self.warnings,
        }


class WriteGate:
    """
    Mechanical proof checks for verified assertions.

    All checks are deterministic (no LLM involvement).
    This is the final gate before writing to truth tables.
    """

    def __init__(self, session: Session):
        """Initialize with database session."""
        self.session = session

    def _check_document_exists(self, document_id: str) -> WriteGateCheck:
        """Check that document exists in database."""
        from app.web.db.models.document import Document

        doc = self.session.query(Document).filter(
            Document.id == document_id
        ).first()

        if doc:
            return WriteGateCheck(
                check_name="document_exists",
                passed=True,
                message=f"Document {document_id} exists"
            )
        return WriteGateCheck(
            check_name="document_exists",
            passed=False,
            message=f"Document {document_id} not found in database"
        )

    def _check_chunk_exists(self, chunk_id: str) -> WriteGateCheck:
        """Check that chunk exists in database."""
        from app.web.db.models.document import DocumentChunk

        chunk = self.session.query(DocumentChunk).filter(
            DocumentChunk.id == chunk_id
        ).first()

        if chunk:
            return WriteGateCheck(
                check_name="chunk_exists",
                passed=True,
                message=f"Chunk {chunk_id} exists"
            )
        return WriteGateCheck(
            check_name="chunk_exists",
            passed=False,
            message=f"Chunk {chunk_id} not found in database"
        )

    def _check_tier_a(self, document_id: str) -> WriteGateCheck:
        """Check that document is Tier A."""
        from app.web.db.models.document import Document

        doc = self.session.query(Document).filter(
            Document.id == document_id
        ).first()

        if not doc:
            return WriteGateCheck(
                check_name="tier_a_only",
                passed=False,
                message=f"Document {document_id} not found"
            )

        if doc.tier == 'A':
            return WriteGateCheck(
                check_name="tier_a_only",
                passed=True,
                message=f"Document is Tier A ({doc.source})"
            )
        return WriteGateCheck(
            check_name="tier_a_only",
            passed=False,
            message=f"Document is Tier {doc.tier}, not Tier A"
        )

    def _check_quote_exists(self, chunk_id: str, quote: str) -> WriteGateCheck:
        """Check that quote is exact substring of chunk text."""
        from app.web.db.models.document import DocumentChunk

        if not quote:
            return WriteGateCheck(
                check_name="quote_exists",
                passed=False,
                message="Quote is empty"
            )

        chunk = self.session.query(DocumentChunk).filter(
            DocumentChunk.id == chunk_id
        ).first()

        if not chunk:
            return WriteGateCheck(
                check_name="quote_exists",
                passed=False,
                message=f"Chunk {chunk_id} not found"
            )

        if quote in chunk.text:
            return WriteGateCheck(
                check_name="quote_exists",
                passed=True,
                message="Quote found verbatim in chunk"
            )
        return WriteGateCheck(
            check_name="quote_exists",
            passed=False,
            message="Quote not found verbatim in chunk text"
        )

    def _check_validator_passed(self, validator_output: Dict[str, Any]) -> WriteGateCheck:
        """Check that Validator LLM returned verified=true."""
        if not validator_output:
            return WriteGateCheck(
                check_name="validator_passed",
                passed=False,
                message="No validator output provided"
            )

        if validator_output.get("verified") is True:
            return WriteGateCheck(
                check_name="validator_passed",
                passed=True,
                message="Validator confirmed all citations"
            )
        return WriteGateCheck(
            check_name="validator_passed",
            passed=False,
            message=f"Validator failed: {validator_output.get('failures', [])}"
        )

    def _check_multiple_sources(
        self,
        citations: List[Dict[str, Any]],
        min_citations: int = 2
    ) -> WriteGateCheck:
        """Check for multiple citation sources (optional, returns warning)."""
        unique_docs = set()
        for c in citations:
            doc_id = c.get("document_id")
            if doc_id:
                unique_docs.add(doc_id)

        if len(unique_docs) >= min_citations:
            return WriteGateCheck(
                check_name="multiple_sources",
                passed=True,
                message=f"Found {len(unique_docs)} unique document sources",
                severity="warning"
            )
        return WriteGateCheck(
            check_name="multiple_sources",
            passed=False,
            message=f"Only {len(unique_docs)} source(s), recommend {min_citations}+",
            severity="warning"  # Not an error
        )

    def check(
        self,
        reader_output: Dict[str, Any],
        validator_output: Dict[str, Any],
        require_multiple_sources: bool = False
    ) -> WriteGateResult:
        """
        Run all Write Gate checks.

        Args:
            reader_output: Output from Reader LLM
            validator_output: Output from Validator LLM
            require_multiple_sources: If True, require 2+ sources

        Returns:
            WriteGateResult with all check results
        """
        checks = []
        errors = []
        warnings = []

        # Get citations from reader output
        citations = reader_output.get("citations", [])

        if not citations:
            return WriteGateResult(
                passed=False,
                checks=[WriteGateCheck(
                    check_name="has_citations",
                    passed=False,
                    message="No citations provided"
                )],
                errors=["No citations to verify"]
            )

        # Check each citation
        for i, citation in enumerate(citations):
            doc_id = citation.get("document_id")
            chunk_id = citation.get("chunk_id")
            quote = citation.get("quote", "")

            # Document exists
            if doc_id:
                check = self._check_document_exists(doc_id)
                checks.append(check)
                if not check.passed:
                    errors.append(f"Citation {i}: {check.message}")

                # Tier A check
                tier_check = self._check_tier_a(doc_id)
                checks.append(tier_check)
                if not tier_check.passed:
                    errors.append(f"Citation {i}: {tier_check.message}")

            # Chunk exists
            if chunk_id:
                chunk_check = self._check_chunk_exists(chunk_id)
                checks.append(chunk_check)
                if not chunk_check.passed:
                    errors.append(f"Citation {i}: {chunk_check.message}")

                # Quote exists in chunk
                quote_check = self._check_quote_exists(chunk_id, quote)
                checks.append(quote_check)
                if not quote_check.passed:
                    errors.append(f"Citation {i}: {quote_check.message}")

        # Validator passed
        validator_check = self._check_validator_passed(validator_output)
        checks.append(validator_check)
        if not validator_check.passed:
            errors.append(validator_check.message)

        # Multiple sources (optional)
        multi_check = self._check_multiple_sources(citations)
        checks.append(multi_check)
        if not multi_check.passed:
            if require_multiple_sources:
                errors.append(multi_check.message)
            else:
                warnings.append(multi_check.message)

        # Determine overall pass/fail
        passed = len(errors) == 0

        return WriteGateResult(
            passed=passed,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    def compute_evidence_hash(self, quote: str, document_id: str, chunk_id: str) -> str:
        """Compute hash for evidence deduplication."""
        content = f"{quote}|{document_id}|{chunk_id}"
        return hashlib.sha256(content.encode()).hexdigest()
