"""
Extraction Worker

Extracts tariff changes from documents using:
1. Deterministic XML table parsing (for <GPOTABLE>)
2. LLM-based RAG extraction (for unstructured content)

Output: CandidateChange objects for validation.
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any

from app.web.db import db
from app.models.document_store import OfficialDocument, DocumentChunk
from app.models.ingest_job import IngestJob
from app.workers.chapter99_resolver import Chapter99Resolver

logger = logging.getLogger(__name__)

# LLM extraction prompt for tariff changes
TARIFF_EXTRACTION_PROMPT = """You are an expert at extracting tariff rate changes from regulatory documents.

Analyze the following text from a Federal Register or CBP document and extract any tariff changes.

For each tariff change found, provide a JSON object with these fields:
- hts_code: The 8 or 10 digit HTS code (e.g., "8544.42.90")
- chapter_99_code: The Chapter 99 heading if mentioned (e.g., "9903.88.01")
- rate: The duty rate as a decimal (e.g., 0.25 for 25%)
- effective_date: The effective date in YYYY-MM-DD format
- description: Brief product description
- program: The tariff program (section_301, section_232_steel, section_232_aluminum, ieepa_fentanyl, etc.)
- evidence_quote: The exact text that supports this change (verbatim quote from the document)

Return a JSON array of changes. If no tariff changes are found, return an empty array [].

IMPORTANT:
- Only extract actual tariff rate changes, not general discussions
- Include the exact quote from the document as evidence
- Rates should be decimals (0.25 for 25%, 1.00 for 100%)
- Only include changes with specific HTS codes and rates

TEXT TO ANALYZE:
{text}

JSON OUTPUT:"""


@dataclass
class RateScheduleEntry:
    """Single rate entry in a staged schedule."""
    rate: Decimal
    effective_start: date
    effective_end: Optional[date] = None


@dataclass
class CandidateChange:
    """
    A proposed tariff change extracted from a document.

    This is the output of extraction - needs validation before commit.
    """
    document_id: str
    hts_code: str
    description: str = ""

    # Chapter 99 codes
    old_chapter_99_code: Optional[str] = None
    new_chapter_99_code: str = ""

    # Rate schedule (supports staged implementations)
    rate_schedule: List[RateScheduleEntry] = field(default_factory=list)

    # Simple rate (for single-rate changes)
    rate: Optional[Decimal] = None
    effective_date: Optional[date] = None

    # Program
    program: str = ""  # section_301, section_232_steel, etc.
    product_group: str = ""

    # Evidence
    evidence_quote: str = ""
    evidence_chunk_id: Optional[str] = None
    evidence_line_start: int = 0
    evidence_line_end: int = 0

    # Extraction method
    extraction_method: str = ""  # xml_table, llm_rag

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "document_id": self.document_id,
            "hts_code": self.hts_code,
            "description": self.description,
            "old_chapter_99_code": self.old_chapter_99_code,
            "new_chapter_99_code": self.new_chapter_99_code,
            "rate": float(self.rate) if self.rate else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "program": self.program,
            "product_group": self.product_group,
            "evidence_quote": self.evidence_quote[:200] + "..." if len(self.evidence_quote) > 200 else self.evidence_quote,
            "evidence_line_start": self.evidence_line_start,
            "evidence_line_end": self.evidence_line_end,
            "extraction_method": self.extraction_method,
        }

        # Include rate_schedule if present
        if self.rate_schedule:
            result["rate_schedule"] = [
                {
                    "rate": float(entry.rate),
                    "effective_start": entry.effective_start.isoformat(),
                    "effective_end": entry.effective_end.isoformat() if entry.effective_end else None,
                }
                for entry in self.rate_schedule
            ]

        return result

    def has_staged_rates(self) -> bool:
        """Check if this candidate has multiple staged rate segments."""
        return len(self.rate_schedule) > 1


class ExtractionWorker:
    """
    Extracts tariff changes from documents.

    Two modes:
    1. DETERMINISTIC: Parse XML <GPOTABLE> elements directly
    2. RAG: Use LLM to extract from unstructured text

    Always tracks evidence (line numbers, quotes) for validation.
    """

    def __init__(self):
        self.chapter99_resolver = Chapter99Resolver()

    def extract_from_document(self, doc: OfficialDocument,
                             job: IngestJob = None) -> List[CandidateChange]:
        """
        Extract all tariff changes from a document.

        Args:
            doc: OfficialDocument with raw_bytes and canonical_text
            job: Optional IngestJob for status tracking

        Returns:
            List of CandidateChange objects
        """
        if job:
            job.status = "extracting"
            db.session.commit()

        candidates = []

        try:
            # Step 1: Try deterministic XML extraction first
            if doc.content_type and "xml" in doc.content_type:
                xml_candidates = self._extract_from_xml(doc)
                candidates.extend(xml_candidates)
                logger.info(f"XML extraction: {len(xml_candidates)} candidates")

            # Step 2: RAG extraction for narrative content
            rag_candidates = self._extract_from_rag(doc)
            candidates.extend(rag_candidates)
            logger.info(f"RAG extraction: {len(rag_candidates)} candidates")

            # Deduplicate
            candidates = self._deduplicate_candidates(candidates)

            doc.status = "extracted"
            if job:
                job.status = "extracted"
                job.changes_extracted = len(candidates)

            db.session.commit()

            return candidates

        except Exception as e:
            logger.error(f"Extraction failed for {doc.external_id}: {e}")
            if job:
                job.mark_failed(f"Extraction error: {e}")
            db.session.commit()
            return []

    def _extract_from_xml(self, doc: OfficialDocument) -> List[CandidateChange]:
        """
        Deterministic extraction from XML tables.

        Parses <GPOTABLE> elements directly - no LLM needed.
        Uses Chapter99Resolver to determine the correct Chapter 99 code.
        """
        candidates = []

        try:
            root = ET.fromstring(doc.raw_bytes)
        except ET.ParseError:
            return []

        # Build line index for evidence tracking
        line_index = self._build_line_index(doc.canonical_text or "")

        # Get document-level context for Chapter 99 resolution
        doc_context = self._get_document_context(root)

        for table in root.iter("GPOTABLE"):
            current_product_group = None

            # Get table-specific context (heading, preceding text)
            table_context = self._get_table_context(table, root)
            full_context = f"{doc_context}\n{table_context}"

            # Resolve Chapter 99 code for this table
            resolution = self.chapter99_resolver.resolve(full_context)

            # Get staged rates if any
            staged_rates = self.chapter99_resolver.get_staged_rates(full_context)

            for row in table.findall(".//ROW"):
                entries = row.findall("ENT")

                if not entries:
                    continue

                # Check for product group header
                first_entry = entries[0]
                e_tag = first_entry.find("E")
                if e_tag is not None and e_tag.get("T") == "02":
                    current_product_group = e_tag.text.strip() if e_tag.text else None
                    continue

                # Parse data row
                if len(entries) >= 3:
                    hts_code = self._get_text(entries[0])
                    description = self._get_text(entries[1]) if len(entries) > 1 else ""

                    # Skip if not a valid HTS
                    if not self._is_valid_hts(hts_code):
                        continue

                    # Resolve Chapter 99 for this specific HTS (may refine based on HTS chapter)
                    hts_resolution = self.chapter99_resolver.resolve_for_hts(hts_code, full_context)
                    if hts_resolution:
                        resolution = hts_resolution

                    # Parse rates (may be staged)
                    rates = self._parse_rates(entries[2] if len(entries) > 2 else None)
                    timings = self._parse_timings(entries[3] if len(entries) > 3 else None)

                    # Find evidence lines
                    line_start, line_end = self._find_evidence_lines(line_index, hts_code)

                    # Build rate schedule if multiple rates/timings exist
                    if len(rates) > 1 and len(timings) >= len(rates):
                        # Multiple staged rates - create ONE candidate with rate_schedule
                        rate_schedule = []
                        for i, (rate, timing) in enumerate(zip(rates, timings)):
                            effective_start = self._timing_to_date(timing)
                            # effective_end = next segment's start (or None for last)
                            effective_end = None
                            if i + 1 < len(timings):
                                effective_end = self._timing_to_date(timings[i + 1])

                            rate_schedule.append(RateScheduleEntry(
                                rate=Decimal(str(rate / 100)),
                                effective_start=effective_start,
                                effective_end=effective_end,
                            ))

                        # Use first rate/date for the simple fields (for backwards compat)
                        first_effective = self._timing_to_date(timings[0]) if timings else None

                        candidate = CandidateChange(
                            document_id=doc.id,
                            hts_code=hts_code,
                            description=description[:200],
                            rate=Decimal(str(rates[0] / 100)),
                            effective_date=first_effective,
                            rate_schedule=rate_schedule,
                            product_group=current_product_group or "",
                            evidence_line_start=line_start,
                            evidence_line_end=line_end,
                            extraction_method="xml_table",
                        )

                        # Add Chapter 99 resolution if available
                        if resolution:
                            candidate.new_chapter_99_code = resolution.get("chapter_99_code", "")
                            candidate.program = resolution.get("program", "")

                        candidates.append(candidate)

                    elif len(rates) >= 1:
                        # Single rate - create candidate with simple fields only
                        effective = self._timing_to_date(timings[0]) if timings else None

                        candidate = CandidateChange(
                            document_id=doc.id,
                            hts_code=hts_code,
                            description=description[:200],
                            rate=Decimal(str(rates[0] / 100)),
                            effective_date=effective,
                            product_group=current_product_group or "",
                            evidence_line_start=line_start,
                            evidence_line_end=line_end,
                            extraction_method="xml_table",
                        )

                        # Add Chapter 99 resolution if available
                        if resolution:
                            candidate.new_chapter_99_code = resolution.get("chapter_99_code", "")
                            candidate.program = resolution.get("program", "")

                        candidates.append(candidate)

        return candidates

    def _get_document_context(self, root) -> str:
        """Extract document-level context for Chapter 99 resolution."""
        context_parts = []

        # Get title/subject elements
        for tag in ["SUBJECT", "AGENCY", "ACTION", "SUMMARY", "PREAMB"]:
            for elem in root.iter(tag):
                text = self._get_all_text(elem)
                if text:
                    context_parts.append(text)

        # Get any 9903 codes mentioned in the document
        full_text = self._get_all_text(root)
        if "9903" in full_text:
            context_parts.append(full_text[:5000])  # First 5000 chars with 9903 codes

        return "\n".join(context_parts[:10])  # Limit context size

    def _get_table_context(self, table, root) -> str:
        """Extract context immediately surrounding a table."""
        context_parts = []

        # Get preceding siblings (headings, paragraphs)
        parent = None
        for elem in root.iter():
            if table in list(elem):
                parent = elem
                break

        if parent is not None:
            children = list(parent)
            table_idx = children.index(table)

            # Get up to 5 preceding elements
            for i in range(max(0, table_idx - 5), table_idx):
                text = self._get_all_text(children[i])
                if text:
                    context_parts.append(text)

        # Get table caption/title if present
        for ttl in table.iter("TTITLE"):
            context_parts.append(self._get_all_text(ttl))

        return "\n".join(context_parts)

    def _get_all_text(self, elem) -> str:
        """Recursively get all text content from an element."""
        if elem is None:
            return ""
        texts = []
        if elem.text:
            texts.append(elem.text.strip())
        for child in elem:
            texts.append(self._get_all_text(child))
            if child.tail:
                texts.append(child.tail.strip())
        return " ".join(filter(None, texts))

    def _extract_from_rag(self, doc: OfficialDocument) -> List[CandidateChange]:
        """
        LLM-based extraction for narrative content.

        Uses document chunks and prompts LLM to extract changes.
        Only runs if OPENAI_API_KEY is configured.
        """
        candidates = []

        # Check if OpenAI is configured
        if not os.environ.get("OPENAI_API_KEY"):
            logger.debug("OPENAI_API_KEY not set, skipping LLM extraction")
            return []

        try:
            from langchain_openai import ChatOpenAI

            # Get narrative chunks (non-table content)
            chunks = DocumentChunk.query.filter_by(
                document_id=doc.id,
            ).filter(
                DocumentChunk.chunk_type.in_(['narrative', 'text', 'paragraph'])
            ).all()

            if not chunks:
                # Fallback: get all chunks if no narrative chunks tagged
                chunks = DocumentChunk.query.filter_by(document_id=doc.id).limit(20).all()

            if not chunks:
                logger.debug(f"No chunks found for document {doc.id}")
                return []

            # Initialize LLM
            llm = ChatOpenAI(
                model_name="gpt-4o-mini",  # Fast and cheap for extraction
                temperature=0,  # Deterministic for extraction
            )

            for chunk in chunks:
                if not chunk.text or len(chunk.text.strip()) < 100:
                    continue  # Skip very short chunks

                try:
                    # Format the prompt
                    prompt = TARIFF_EXTRACTION_PROMPT.format(text=chunk.text[:8000])

                    # Call LLM
                    response = llm.invoke(prompt)
                    response_text = response.content if hasattr(response, 'content') else str(response)

                    # Parse JSON response
                    # Handle potential markdown code blocks
                    json_text = response_text.strip()
                    if json_text.startswith("```"):
                        json_text = json_text.split("```")[1]
                        if json_text.startswith("json"):
                            json_text = json_text[4:]
                    json_text = json_text.strip()

                    if not json_text or json_text == "[]":
                        continue

                    extracted = json.loads(json_text)

                    if not isinstance(extracted, list):
                        extracted = [extracted]

                    for item in extracted:
                        if not isinstance(item, dict):
                            continue

                        hts_code = item.get("hts_code", "")
                        if not hts_code or not self._is_valid_hts(hts_code):
                            continue

                        # Parse rate
                        rate_val = item.get("rate")
                        if rate_val is None:
                            continue
                        try:
                            rate = Decimal(str(rate_val))
                        except (ValueError, TypeError):
                            continue

                        # Parse effective date
                        eff_date = None
                        eff_str = item.get("effective_date")
                        if eff_str:
                            try:
                                eff_date = date.fromisoformat(eff_str)
                            except (ValueError, TypeError):
                                pass

                        candidate = CandidateChange(
                            document_id=str(doc.id),
                            hts_code=hts_code,
                            description=item.get("description", "")[:200],
                            new_chapter_99_code=item.get("chapter_99_code", ""),
                            rate=rate,
                            effective_date=eff_date,
                            program=item.get("program", ""),
                            evidence_quote=item.get("evidence_quote", "")[:500],
                            evidence_chunk_id=str(chunk.id) if chunk.id else None,
                            extraction_method="llm_rag",
                        )

                        # Try to resolve Chapter 99 if not provided
                        if not candidate.new_chapter_99_code and candidate.program:
                            resolution = self.chapter99_resolver.resolve(chunk.text)
                            if resolution:
                                candidate.new_chapter_99_code = resolution.get("chapter_99_code", "")

                        candidates.append(candidate)

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse LLM response as JSON: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"LLM extraction failed for chunk {chunk.id}: {e}")
                    continue

            logger.info(f"LLM RAG extraction found {len(candidates)} candidates")

        except ImportError:
            logger.warning("langchain_openai not installed, skipping LLM extraction")
        except Exception as e:
            logger.error(f"LLM RAG extraction failed: {e}")

        return candidates

    def _build_line_index(self, canonical_text: str) -> Dict[int, str]:
        """Build searchable index of line numbers to content."""
        index = {}
        for line in canonical_text.split('\n'):
            match = re.match(r'L(\d+):\s*(.*)', line)
            if match:
                line_num = int(match.group(1))
                content = match.group(2)
                index[line_num] = content
        return index

    def _find_evidence_lines(self, line_index: Dict[int, str],
                            hts_code: str) -> tuple:
        """Find lines containing the HTS code."""
        clean_hts = hts_code.replace(".", "")

        for line_num, content in line_index.items():
            if clean_hts in content.replace(".", "").replace(" ", ""):
                return (line_num, line_num)

        return (0, 0)

    def _get_text(self, elem) -> str:
        """Extract all text from an element."""
        if elem is None:
            return ""
        text = elem.text or ""
        for child in elem:
            text += " " + (child.text or "") + " " + (child.tail or "")
        return text.strip()

    def _is_valid_hts(self, code: str) -> bool:
        """Check if code looks like a valid HTS (not Chapter 99)."""
        if not code:
            return False
        clean = code.replace(".", "").replace(" ", "")
        if not clean.isdigit():
            return False
        if clean.startswith("99"):
            return False  # Chapter 99 codes
        if len(clean) < 6:
            return False
        return True

    def _parse_rates(self, elem) -> List[float]:
        """Parse rates from element (may have multiple for staged changes)."""
        if elem is None:
            return []

        rates = []
        text = elem.text or ""

        # Get main text
        if text.strip():
            try:
                rates.append(float(text.strip()))
            except ValueError:
                pass

        # Get LI elements (sub-items for staged rates)
        for li in elem.findall("LI"):
            if li.text:
                try:
                    rates.append(float(li.text.strip()))
                except ValueError:
                    pass

        return rates

    def _parse_timings(self, elem) -> List[int]:
        """Parse timing years from element."""
        if elem is None:
            return []

        timings = []
        text = elem.text or ""

        if text.strip():
            try:
                timings.append(int(text.strip()))
            except ValueError:
                pass

        for li in elem.findall("LI"):
            if li.text:
                try:
                    timings.append(int(li.text.strip()))
                except ValueError:
                    pass

        return timings

    def _timing_to_date(self, year: int) -> date:
        """Convert year to effective date."""
        if year == 2024:
            return date(2024, 9, 27)  # Sept 27, 2024 per FR notice
        else:
            return date(year, 1, 1)

    def _deduplicate_candidates(self, candidates: List[CandidateChange]) -> List[CandidateChange]:
        """Remove duplicate candidates."""
        seen = set()
        unique = []

        for c in candidates:
            key = (c.hts_code, str(c.rate), str(c.effective_date))
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique
