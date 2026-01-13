"""
Validation Worker

Validates extracted changes against source documents using:
1. LLM cross-checking (optional, for unstructured content)
2. Deterministic verification (required, for all content)

Output: ValidationResult with confidence score.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.web.db import db
from app.models.document_store import OfficialDocument, DocumentChunk
from app.models.evidence import EvidencePacket
from app.workers.extraction_worker import CandidateChange

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a candidate change."""
    is_valid: bool
    confidence: float = 0.0
    reason: Optional[str] = None

    # Detailed check results
    hts_found: bool = False
    chapter_99_found: bool = False
    rate_found: bool = False
    quote_verified: bool = False

    # Corrected data (if applicable)
    corrected_quote: Optional[str] = None
    corrected_lines: Optional[tuple] = None


class ValidationWorker:
    """
    Validates extracted changes against source documents.

    Two-layer validation:
    1. Deterministic: Verify data exists in canonical text
    2. LLM (optional): Cross-check for ambiguous extractions
    """

    def validate(self, candidate: CandidateChange,
                doc: OfficialDocument = None) -> ValidationResult:
        """
        Validate a candidate change.

        Args:
            candidate: Extracted change to validate
            doc: Optional document (will be fetched if not provided)

        Returns:
            ValidationResult with detailed check results
        """
        # Get document
        if doc is None:
            doc = OfficialDocument.query.get(candidate.document_id)

        if not doc:
            return ValidationResult(
                is_valid=False,
                reason="Document not found"
            )

        if not doc.canonical_text:
            return ValidationResult(
                is_valid=False,
                reason="Document has no canonical text"
            )

        # Run deterministic checks
        result = self._deterministic_validation(candidate, doc)

        # For XML table extractions, deterministic is enough
        if candidate.extraction_method == "xml_table" and result.is_valid:
            result.confidence = 1.0
            return result

        # For LLM extractions, we could add additional cross-checking
        # (placeholder for LLM validation if needed)
        if candidate.extraction_method == "llm_rag":
            result = self._enhance_with_context(candidate, doc, result)

        return result

    def _deterministic_validation(self, candidate: CandidateChange,
                                  doc: OfficialDocument) -> ValidationResult:
        """
        Deterministic validation checks.

        Verifies that extracted data actually appears in the document.
        """
        canonical = doc.canonical_text
        result = ValidationResult(is_valid=True, confidence=0.0)

        checks_passed = 0
        total_checks = 0

        # Check 1: HTS code exists in document
        total_checks += 1
        hts_clean = candidate.hts_code.replace(".", "")
        hts_variants = [
            candidate.hts_code,
            hts_clean,
            f"{hts_clean[:4]}.{hts_clean[4:6]}.{hts_clean[6:]}",
        ]

        for variant in hts_variants:
            if variant in canonical:
                result.hts_found = True
                checks_passed += 1
                break

        if not result.hts_found:
            result.reason = f"HTS code {candidate.hts_code} not found in document"

        # Check 2: Chapter 99 code (if specified)
        if candidate.new_chapter_99_code:
            total_checks += 1
            ch99_clean = candidate.new_chapter_99_code.replace(".", "")
            ch99_variants = [
                candidate.new_chapter_99_code,
                ch99_clean,
            ]

            for variant in ch99_variants:
                if variant in canonical:
                    result.chapter_99_found = True
                    checks_passed += 1
                    break

            if not result.chapter_99_found and not result.reason:
                result.reason = f"Chapter 99 code {candidate.new_chapter_99_code} not found"

        # Check 3: Rate exists (if specified)
        if candidate.rate is not None:
            total_checks += 1
            rate_percent = int(candidate.rate * 100)
            rate_variants = [
                str(rate_percent),
                f"{rate_percent}%",
                f"{rate_percent} percent",
                str(float(candidate.rate)),
            ]

            for variant in rate_variants:
                if variant in canonical:
                    result.rate_found = True
                    checks_passed += 1
                    break

            if not result.rate_found and not result.reason:
                result.reason = f"Rate {rate_percent}% not found in document"

        # Check 4: Evidence quote exists (if provided)
        if candidate.evidence_quote:
            total_checks += 1
            # Try exact match first
            if candidate.evidence_quote in canonical:
                result.quote_verified = True
                checks_passed += 1
            else:
                # Try normalized match (remove extra whitespace)
                normalized_quote = " ".join(candidate.evidence_quote.split())
                normalized_canonical = " ".join(canonical.split())

                if normalized_quote in normalized_canonical:
                    result.quote_verified = True
                    result.corrected_quote = self._find_actual_quote(
                        canonical, normalized_quote
                    )
                    checks_passed += 1
                elif not result.reason:
                    result.reason = "Evidence quote not found verbatim"

        # Calculate confidence
        if total_checks > 0:
            result.confidence = checks_passed / total_checks

        # Determine validity
        # Must have HTS code + at least one of (rate, chapter_99)
        result.is_valid = (
            result.hts_found and
            (result.rate_found or result.chapter_99_found)
        )

        return result

    def _enhance_with_context(self, candidate: CandidateChange,
                             doc: OfficialDocument,
                             base_result: ValidationResult) -> ValidationResult:
        """
        Enhance validation with contextual analysis.

        For LLM extractions, verify the HTS code appears near the rate/code.
        """
        if not base_result.hts_found:
            return base_result

        canonical = doc.canonical_text
        lines = canonical.split('\n')

        # Find lines with HTS code
        hts_lines = []
        hts_clean = candidate.hts_code.replace(".", "")

        for i, line in enumerate(lines):
            line_content = line.split(': ', 1)[1] if ': ' in line else line
            if hts_clean in line_content.replace(".", "").replace(" ", ""):
                hts_lines.append(i)

        if not hts_lines:
            return base_result

        # Check if rate/chapter_99 appears within 10 lines of HTS
        context_window = 10
        rate_str = str(int(candidate.rate * 100)) if candidate.rate else None
        ch99_str = candidate.new_chapter_99_code

        for hts_line in hts_lines:
            start = max(0, hts_line - context_window)
            end = min(len(lines), hts_line + context_window + 1)
            context = '\n'.join(lines[start:end])

            found_in_context = False
            if rate_str and rate_str in context:
                found_in_context = True
            if ch99_str and ch99_str in context:
                found_in_context = True

            if found_in_context:
                # Update evidence lines
                base_result.corrected_lines = (
                    self._get_line_number(lines[start]),
                    self._get_line_number(lines[end - 1])
                )
                base_result.confidence = min(base_result.confidence + 0.1, 1.0)
                break

        return base_result

    def _find_actual_quote(self, canonical: str, normalized_quote: str) -> str:
        """Find the actual quote text from canonical text."""
        # This is a simplified version - could use fuzzy matching
        words = normalized_quote.split()[:5]
        search_start = " ".join(words)

        idx = canonical.find(search_start)
        if idx >= 0:
            end_idx = idx + len(normalized_quote) + 50
            return canonical[idx:end_idx].split('\n')[0]

        return ""

    def _get_line_number(self, line: str) -> int:
        """Extract line number from canonical line format."""
        match = re.match(r'L(\d+):', line)
        if match:
            return int(match.group(1))
        return 0

    def validate_batch(self, candidates: list,
                      doc: OfficialDocument) -> list:
        """
        Validate multiple candidates against the same document.

        More efficient than validating one at a time.
        """
        results = []
        for candidate in candidates:
            result = self.validate(candidate, doc)
            results.append((candidate, result))
        return results
