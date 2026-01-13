"""
Tariff Data Extractor using Gemini LLM

Extracts structured tariff data from official notices (CBP CSMS, Federal Register, USTR).
Part of the Write Gate system for automated temporal table updates.

Uses Google Gemini with Search Grounding for extraction.
"""

import json
import os
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Gemini API Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EXTRACTION_MODEL = "gemini-2.5-flash"  # Fast, cost-effective for extraction


@dataclass
class ExtractionResult:
    """Result of extracting tariff data from a document."""

    # Extracted data
    hts_codes: List[str] = field(default_factory=list)
    program: Optional[str] = None  # section_301, section_232_steel, ieepa_reciprocal
    chapter_99_code: Optional[str] = None
    duty_rate: Optional[float] = None
    effective_date: Optional[date] = None
    action: Optional[str] = None  # add_to_scope, remove_from_scope, rate_change

    # Program-specific fields
    list_name: Optional[str] = None  # For 301: list_1, list_2, list_3, list_4a
    material_type: Optional[str] = None  # For 232: steel, aluminum, copper
    country_code: Optional[str] = None  # For IEEPA

    # Evidence
    quotes: List[str] = field(default_factory=list)  # Verbatim quotes from source

    # Metadata
    success: bool = True
    error: Optional[str] = None
    raw_response: Optional[str] = None  # Full LLM response for debugging
    model: str = EXTRACTION_MODEL
    extracted_at: datetime = field(default_factory=datetime.utcnow)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hts_codes": self.hts_codes,
            "program": self.program,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": self.duty_rate,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "action": self.action,
            "list_name": self.list_name,
            "material_type": self.material_type,
            "country_code": self.country_code,
            "quotes": self.quotes,
            "success": self.success,
            "error": self.error,
            "model": self.model,
            "extracted_at": self.extracted_at.isoformat(),
        }


class TariffExtractorLLM:
    """
    Extract structured tariff data from official notices using Gemini.

    Uses Google Gemini for extraction, with Search Grounding capability
    for cross-referencing official sources.

    Usage:
        extractor = TariffExtractorLLM()
        result = extractor.extract(document_text, source="CSMS #65936570")
        if result.success:
            print(f"Found {len(result.hts_codes)} HTS codes")
    """

    def __init__(self, model: str = EXTRACTION_MODEL):
        self.model = model
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Gemini client."""
        if self._client is None:
            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY environment variable is not set")
            from google import genai
            self._client = genai.Client(api_key=GEMINI_API_KEY)
        return self._client

    def extract(self, document_text: str, source: str) -> ExtractionResult:
        """
        Extract tariff changes from document text.

        Args:
            document_text: Full text of the official notice
            source: Source identifier (e.g., "CSMS #65936570", "FR 2024-12345")

        Returns:
            ExtractionResult with extracted tariff data
        """
        try:
            prompt = self._build_extraction_prompt(document_text, source)

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )

            raw_response = response.text
            result = self._parse_response(raw_response)
            result.raw_response = raw_response

            logger.info(
                f"Extracted {len(result.hts_codes)} HTS codes from {source} "
                f"(program={result.program})"
            )

            return result

        except Exception as e:
            logger.error(f"Extraction failed for {source}: {e}")
            return ExtractionResult(
                success=False,
                error=str(e),
                model=self.model,
            )

    def _build_extraction_prompt(self, document_text: str, source: str) -> str:
        """Build the extraction prompt for Gemini."""
        return f"""You are a U.S. customs tariff expert. Extract structured tariff information from this official government notice.

DOCUMENT SOURCE: {source}

DOCUMENT TEXT:
---
{document_text[:15000]}
---

INSTRUCTIONS:
1. Identify ALL HTS codes mentioned (format: XXXX.XX.XXXX or XXXXXXXX)
2. Determine which tariff program this relates to:
   - section_301: USTR Section 301 tariffs on Chinese goods
   - section_232_steel: Section 232 steel tariffs
   - section_232_aluminum: Section 232 aluminum tariffs
   - section_232_copper: Section 232 copper tariffs
   - ieepa_fentanyl: IEEPA fentanyl-related tariffs
   - ieepa_reciprocal: IEEPA reciprocal tariffs
3. Find the Chapter 99 code (9903.XX.XX)
4. Find the duty rate (as decimal, e.g., 0.25 for 25%)
5. Find the effective date
6. Determine the action type:
   - add_to_scope: New HTS codes being added to a program
   - remove_from_scope: HTS codes being removed/excluded
   - rate_change: Duty rate being modified
   - effective_date_change: Only effective date is changing
7. Extract VERBATIM QUOTES that support each extraction (max 200 chars each)

For Section 301, also identify:
- list_name: list_1, list_2, list_3, list_4a

For Section 232, also identify:
- material_type: steel, aluminum, copper
- Whether it's a primary article (Chapter 72-73 for steel, 76 for aluminum) or derivative

For IEEPA, also identify:
- country_code: CN, MX, CA, etc.

OUTPUT FORMAT (JSON only, no markdown):
{{
    "hts_codes": ["8544.42.9090", "8544.30.0000"],
    "program": "section_232_copper",
    "chapter_99_code": "9903.78.01",
    "duty_rate": 0.25,
    "effective_date": "2026-03-12",
    "action": "add_to_scope",
    "list_name": null,
    "material_type": "copper",
    "country_code": null,
    "quotes": [
        "HTS 8544.42.9090 shall be subject to...",
        "effective March 12, 2026...",
        "duty rate of 25 percent..."
    ]
}}

If the document doesn't contain tariff-related information, return:
{{
    "hts_codes": [],
    "program": null,
    "error": "Document does not contain tariff information"
}}

IMPORTANT: Extract ONLY what is explicitly stated in the document. Do NOT infer or guess.
"""

    def _parse_response(self, text: str) -> ExtractionResult:
        """Parse Gemini response into ExtractionResult."""
        try:
            # Find JSON in response
            json_start = text.find('{')
            json_end = text.rfind('}') + 1

            if json_start < 0 or json_end <= json_start:
                return ExtractionResult(
                    success=False,
                    error="No JSON found in response",
                    raw_response=text,
                )

            data = json.loads(text[json_start:json_end])

            # Check for extraction error
            if data.get("error"):
                return ExtractionResult(
                    success=False,
                    error=data["error"],
                    raw_response=text,
                )

            # Parse effective date
            effective_date = None
            if data.get("effective_date"):
                try:
                    effective_date = datetime.strptime(
                        data["effective_date"], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass

            return ExtractionResult(
                hts_codes=data.get("hts_codes", []),
                program=data.get("program"),
                chapter_99_code=data.get("chapter_99_code"),
                duty_rate=data.get("duty_rate"),
                effective_date=effective_date,
                action=data.get("action"),
                list_name=data.get("list_name"),
                material_type=data.get("material_type"),
                country_code=data.get("country_code"),
                quotes=data.get("quotes", []),
                success=True,
                model=self.model,
            )

        except json.JSONDecodeError as e:
            return ExtractionResult(
                success=False,
                error=f"JSON parse error: {e}",
                raw_response=text,
            )

    def extract_batch(self, documents: List[Dict[str, str]]) -> List[ExtractionResult]:
        """
        Extract from multiple documents.

        Args:
            documents: List of dicts with 'text' and 'source' keys

        Returns:
            List of ExtractionResult objects
        """
        results = []
        for doc in documents:
            result = self.extract(
                document_text=doc["text"],
                source=doc.get("source", "unknown")
            )
            results.append(result)
        return results


# Singleton instance
_extractor = None


def get_tariff_extractor() -> TariffExtractorLLM:
    """Get the singleton TariffExtractorLLM instance."""
    global _extractor
    if _extractor is None:
        _extractor = TariffExtractorLLM()
    return _extractor
