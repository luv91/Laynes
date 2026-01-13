"""
Tariff Data Verifier using OpenAI GPT-4

Verifies extracted tariff data by finding exact quotes in the source document.
Part of the Write Gate system for automated temporal table updates.

Uses OpenAI GPT-4o for verification (different model than extractor for cross-validation).
"""

import json
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# OpenAI API Configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
VERIFICATION_MODEL = "gpt-4o"  # GPT-4o for verification


@dataclass
class FieldEvidence:
    """Evidence for a single extracted field."""
    found: bool
    quote: Optional[str] = None
    location: Optional[str] = None
    confidence: float = 0.0


@dataclass
class VerificationResult:
    """Result of verifying an extraction against the source document."""

    # Overall verification
    verified: bool = False
    confidence: float = 0.0

    # Per-field evidence
    evidence: Dict[str, FieldEvidence] = field(default_factory=dict)

    # Summary
    missing_fields: List[str] = field(default_factory=list)
    verified_fields: List[str] = field(default_factory=list)
    verifier_notes: Optional[str] = None

    # Metadata
    success: bool = True
    error: Optional[str] = None
    raw_response: Optional[str] = None
    model: str = VERIFICATION_MODEL
    verified_at: datetime = field(default_factory=datetime.utcnow)

    def as_dict(self) -> Dict[str, Any]:
        evidence_dict = {}
        for field_name, ev in self.evidence.items():
            evidence_dict[field_name] = {
                "found": ev.found,
                "quote": ev.quote,
                "location": ev.location,
                "confidence": ev.confidence,
            }

        return {
            "verified": self.verified,
            "confidence": self.confidence,
            "evidence": evidence_dict,
            "missing_fields": self.missing_fields,
            "verified_fields": self.verified_fields,
            "verifier_notes": self.verifier_notes,
            "success": self.success,
            "error": self.error,
            "model": self.model,
            "verified_at": self.verified_at.isoformat(),
        }


class TariffVerifierLLM:
    """
    Verify extracted tariff data by finding exact quotes in the source document.

    Uses OpenAI GPT-4o (different from Gemini extractor) for dual-LLM verification.
    The verifier's job is NOT to "know" if extraction is correct -
    it SEARCHES the document for evidence that PROVES each extracted value.

    Usage:
        verifier = TariffVerifierLLM()
        result = verifier.verify(extraction, document_text)
        if result.verified:
            print("All fields verified with quotes")
    """

    def __init__(self, model: str = VERIFICATION_MODEL):
        self.model = model
        self._client = None

    @property
    def client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY environment variable is not set")
            from openai import OpenAI
            self._client = OpenAI(api_key=OPENAI_API_KEY)
        return self._client

    def verify(self, extraction, document_text: str) -> VerificationResult:
        """
        Verify each extracted field by finding exact quotes in the source document.

        The verifier searches the document for evidence that proves each extracted
        value is correct. It does NOT rely on external knowledge.

        Args:
            extraction: ExtractionResult from TariffExtractorLLM
            document_text: Original document text to verify against

        Returns:
            VerificationResult with evidence for each field
        """
        try:
            prompt = self._build_verification_prompt(extraction, document_text)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for factual verification
            )

            raw_response = response.choices[0].message.content
            result = self._parse_response(raw_response)
            result.raw_response = raw_response

            logger.info(
                f"Verification complete: verified={result.verified}, "
                f"confidence={result.confidence:.2f}, "
                f"missing={result.missing_fields}"
            )

            return result

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return VerificationResult(
                success=False,
                error=str(e),
                model=self.model,
            )

    def _build_verification_prompt(self, extraction, document_text: str) -> str:
        """Build the verification prompt for GPT-4."""
        # Build extraction summary
        extraction_summary = f"""
HTS Codes: {extraction.hts_codes}
Program: {extraction.program}
Chapter 99 Code: {extraction.chapter_99_code}
Duty Rate: {extraction.duty_rate}
Effective Date: {extraction.effective_date}
Action: {extraction.action}
"""
        if extraction.list_name:
            extraction_summary += f"List Name: {extraction.list_name}\n"
        if extraction.material_type:
            extraction_summary += f"Material Type: {extraction.material_type}\n"
        if extraction.country_code:
            extraction_summary += f"Country Code: {extraction.country_code}\n"

        return f"""You are a verification agent. Your ONLY job is to FIND EXACT QUOTES in the document that prove each extracted field is correct.

IMPORTANT: You are NOT judging whether the extraction is "reasonable" or "likely correct".
You are SEARCHING the document for TEXT that CONTAINS the extracted values.

EXTRACTION TO VERIFY:
{extraction_summary}

SOURCE DOCUMENT:
---
{document_text[:15000]}
---

VERIFICATION TASK:
For EACH field in the extraction, you must:
1. SEARCH the document for text that contains this exact value
2. If found, extract the EXACT QUOTE (verbatim, word-for-word, max 200 chars)
3. Note the approximate location (beginning/middle/end of document)

FIELD-BY-FIELD VERIFICATION:

1. HTS Codes: Search for each HTS code (try both formats: XXXX.XX.XXXX and XXXXXXXX)
2. Chapter 99 Code: Search for "9903.XX.XX" pattern
3. Duty Rate: Search for percentage (e.g., "25%", "25 percent", "twenty-five percent")
4. Effective Date: Search for date mentions
5. Program Reference: Search for "Section 232", "Section 301", "IEEPA", etc.
6. Action Type: Look for "added", "removed", "excluded", "subject to", etc.

OUTPUT FORMAT (JSON):
{{
    "verified": true/false,
    "confidence": 0.0-1.0,
    "evidence": {{
        "hts_codes": {{
            "found": true/false,
            "quote": "exact text from document containing the HTS code",
            "location": "paragraph 3",
            "confidence": 0.0-1.0
        }},
        "chapter_99_code": {{
            "found": true/false,
            "quote": "exact text mentioning the code",
            "location": "paragraph 5",
            "confidence": 0.0-1.0
        }},
        "duty_rate": {{
            "found": true/false,
            "quote": "exact text mentioning the rate",
            "location": "paragraph 7",
            "confidence": 0.0-1.0
        }},
        "effective_date": {{
            "found": true/false,
            "quote": "exact text with the date",
            "location": "header",
            "confidence": 0.0-1.0
        }},
        "program": {{
            "found": true/false,
            "quote": "exact text mentioning the program",
            "location": "title",
            "confidence": 0.0-1.0
        }},
        "action": {{
            "found": true/false,
            "quote": "exact text indicating the action",
            "location": "paragraph 2",
            "confidence": 0.0-1.0
        }}
    }},
    "missing_fields": ["list of fields with no quote found"],
    "verified_fields": ["list of fields with quotes found"],
    "verifier_notes": "any additional observations about verification"
}}

CRITICAL RULES:
1. Set verified=true ONLY if you found quotes for ALL critical fields (hts_codes, program, duty_rate or effective_date)
2. If you CANNOT find a quote for a field, set found=false and quote=null (do NOT paraphrase)
3. Quotes must be VERBATIM from the document (copy-paste exact text)
4. If the document doesn't contain tariff information, set verified=false with notes explaining why
5. confidence should reflect how certain you are that the quote proves the extraction
"""

    def _parse_response(self, text: str) -> VerificationResult:
        """Parse GPT-4 response into VerificationResult."""
        try:
            data = json.loads(text)

            # Parse evidence
            evidence = {}
            evidence_data = data.get("evidence", {})

            for field_name, ev_data in evidence_data.items():
                if isinstance(ev_data, dict):
                    evidence[field_name] = FieldEvidence(
                        found=ev_data.get("found", False),
                        quote=ev_data.get("quote"),
                        location=ev_data.get("location"),
                        confidence=ev_data.get("confidence", 0.0),
                    )

            return VerificationResult(
                verified=data.get("verified", False),
                confidence=data.get("confidence", 0.0),
                evidence=evidence,
                missing_fields=data.get("missing_fields", []),
                verified_fields=data.get("verified_fields", []),
                verifier_notes=data.get("verifier_notes"),
                success=True,
                model=self.model,
            )

        except json.JSONDecodeError as e:
            return VerificationResult(
                success=False,
                error=f"JSON parse error: {e}",
                raw_response=text,
            )

    def quick_verify(self, extraction, document_text: str) -> bool:
        """
        Quick verification: just check if HTS codes and rates are in document.

        Performs string matching without LLM call for fast validation.

        Args:
            extraction: ExtractionResult from TariffExtractorLLM
            document_text: Original document text

        Returns:
            True if basic fields are found in document
        """
        doc_lower = document_text.lower()

        # Check HTS codes
        hts_found = False
        for hts in extraction.hts_codes:
            # Try both formats
            hts_plain = hts.replace(".", "")
            if hts.lower() in doc_lower or hts_plain in doc_lower:
                hts_found = True
                break

        # Check program
        program_keywords = {
            "section_301": ["section 301", "301"],
            "section_232_steel": ["section 232", "232", "steel"],
            "section_232_aluminum": ["section 232", "232", "aluminum"],
            "section_232_copper": ["section 232", "232", "copper"],
            "ieepa_fentanyl": ["ieepa", "fentanyl"],
            "ieepa_reciprocal": ["ieepa", "reciprocal"],
        }

        program_found = False
        if extraction.program and extraction.program in program_keywords:
            keywords = program_keywords[extraction.program]
            program_found = any(kw in doc_lower for kw in keywords)

        # Check duty rate
        rate_found = False
        if extraction.duty_rate is not None:
            rate_pct = int(extraction.duty_rate * 100)
            rate_patterns = [
                f"{rate_pct}%",
                f"{rate_pct} percent",
                f"{rate_pct}percent",
            ]
            rate_found = any(p in doc_lower for p in rate_patterns)

        return hts_found and (program_found or rate_found)


# Singleton instance
_verifier = None


def get_tariff_verifier() -> TariffVerifierLLM:
    """Get the singleton TariffVerifierLLM instance."""
    global _verifier
    if _verifier is None:
        _verifier = TariffVerifierLLM()
    return _verifier
