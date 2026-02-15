"""
Chapter 99 Code Resolver

Resolves Chapter 99 codes from Federal Register table context.

The Problem:
Federal Register annex tables often don't include Chapter 99 codes per row.
The code is typically in:
- The heading immediately before the table
- The annex title
- Narrative text nearby ("USTR is inserting new heading 9903.91.07...")

Without proper resolution, we'll extract HTS + rate but won't know the correct
ACE filing code - which means we can still "miss" an update in practice.
"""

import re
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class Chapter99Resolver:
    """
    Resolves Chapter 99 codes from table context.

    Used during extraction to:
    1. Find the Chapter 99 code that applies to a table
    2. Determine the tariff program (301, 232, IEEPA)
    3. Extract additional metadata (list name, sector, etc.)
    """

    # Regex pattern for Chapter 99 codes
    CHAPTER_99_PATTERN = r'9903\.(\d{2})\.(\d{2,4})'

    # Program mappings based on Chapter 99 prefix
    PROGRAM_MAPPINGS = {
        # Section 301 - Original lists (2018-2020)
        "9903.88.01": {"program": "section_301", "list": "list_1", "rate": 0.25},
        "9903.88.02": {"program": "section_301", "list": "list_2", "rate": 0.25},
        "9903.88.03": {"program": "section_301", "list": "list_3", "rate": 0.25},
        "9903.88.04": {"program": "section_301", "list": "list_3_200b", "rate": 0.10},
        "9903.88.15": {"program": "section_301", "list": "list_4a", "rate": 0.075},

        # Section 301 - Four-Year Review (2024) - U.S. Note 31 subdivisions
        # (b) = 9903.91.01 @ 25%, (c) = 9903.91.02 @ 50%, (d) = 9903.91.03 @ 100%
        "9903.91.01": {"program": "section_301", "list": "four_year_review_b", "sector": "strategic", "rate": 0.25},
        "9903.91.02": {"program": "section_301", "list": "four_year_review_c", "sector": "semiconductor", "rate": 0.50},
        "9903.91.03": {"program": "section_301", "list": "four_year_review_d", "sector": "ev_medical", "rate": 1.00},
        "9903.91.07": {"program": "section_301", "list": "strategic_medical", "sector": "medical", "rate": 0.50},
        "9903.91.11": {"program": "section_301", "list": "strategic_battery", "sector": "battery", "rate": 0.25},
        "9903.91.12": {"program": "section_301", "list": "strategic_battery", "sector": "battery", "rate": 0.25},

        # Section 232 - Steel
        "9903.80.01": {"program": "section_232", "material": "steel", "article": "primary", "rate": 0.25},
        "9903.81.90": {"program": "section_232", "material": "steel", "article": "derivative_ch73", "rate": 0.25},
        "9903.81.91": {"program": "section_232", "material": "steel", "article": "derivative_other", "rate": 0.25},

        # Section 232 - Aluminum
        "9903.85.01": {"program": "section_232", "material": "aluminum", "article": "unwrought", "rate": 0.10},
        "9903.85.03": {"program": "section_232", "material": "aluminum", "article": "primary", "rate": 0.10},
        "9903.85.07": {"program": "section_232", "material": "aluminum", "article": "derivative_ch76", "rate": 0.10},
        "9903.85.08": {"program": "section_232", "material": "aluminum", "article": "derivative_other", "rate": 0.10},

        # Section 232 - Copper
        "9903.78.01": {"program": "section_232", "material": "copper", "article": "all", "rate": 0.25},

        # IEEPA - Fentanyl (only 9903.01.24)
        "9903.01.24": {"program": "ieepa_fentanyl", "variant": "taxable", "rate": 0.20},

        # IEEPA - Reciprocal (9903.01.25-35 exception codes + 9903.02.* country codes)
        "9903.01.25": {"program": "ieepa_reciprocal", "variant": "baseline", "rate": 0.10},
        "9903.01.26": {"program": "ieepa_reciprocal", "variant": "usmca_exempt", "rate": 0.00},
        "9903.01.27": {"program": "ieepa_reciprocal", "variant": "donation_exempt", "rate": 0.00},
        "9903.01.28": {"program": "ieepa_reciprocal", "variant": "in_transit", "rate": 0.00},
        "9903.01.29": {"program": "ieepa_reciprocal", "variant": "column2_exempt", "rate": 0.00},
        "9903.01.30": {"program": "ieepa_reciprocal", "variant": "info_material", "rate": 0.00},
        "9903.01.32": {"program": "ieepa_reciprocal", "variant": "annex_ii_exempt", "rate": 0.00},
        "9903.01.33": {"program": "ieepa_reciprocal", "variant": "s232_exempt", "rate": 0.00},
        "9903.01.34": {"program": "ieepa_reciprocal", "variant": "us_content", "rate": 0.00},
        "9903.01.35": {"program": "ieepa_reciprocal", "variant": "repair", "rate": 0.00},
    }

    # Prefix mappings for unknown specific codes
    PREFIX_MAPPINGS = {
        "9903.88": {"program": "section_301", "list": "original"},
        "9903.91": {"program": "section_301", "list": "four_year_review"},
        "9903.80": {"program": "section_232", "material": "steel", "article": "primary"},
        "9903.81": {"program": "section_232", "material": "steel", "article": "derivative"},
        "9903.85": {"program": "section_232", "material": "aluminum"},
        "9903.78": {"program": "section_232", "material": "copper"},
        "9903.01": {"program": "ieepa_reciprocal"},  # 9903.01.24 (fentanyl) handled by exact match
        "9903.02": {"program": "ieepa_reciprocal"},
    }

    # Keywords that indicate specific programs
    PROGRAM_KEYWORDS = {
        "section_301": ["section 301", "301", "china", "ustr", "trade representative"],
        "section_232": ["section 232", "232", "steel", "aluminum", "copper"],
        "ieepa_fentanyl": ["ieepa", "fentanyl", "emergency powers"],
        "ieepa_reciprocal": ["ieepa", "reciprocal"],
    }

    # Sector keywords for 301 classifications
    SECTOR_KEYWORDS = {
        "medical": ["medical", "ppe", "facemask", "face mask", "syringe", "needle", "surgical"],
        "semiconductor": ["semiconductor", "chip", "wafer", "integrated circuit", "diode", "transistor"],
        "ev": ["electric vehicle", "ev", "8703.60", "8703.80"],
        "battery": ["battery", "lithium", "accumulator", "8507"],
        "critical_minerals": ["mineral", "graphite", "permanent magnet", "rare earth"],
        "solar": ["solar", "photovoltaic", "8541.40"],
    }

    def resolve(self, context: str, table_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Extract Chapter 99 code + program from table context.

        Args:
            context: Text surrounding the table (heading, title, nearby paragraphs)
            table_text: Optional text from the table itself

        Returns:
            Dict with resolution details, or None if unresolvable
            {
                "chapter_99_code": "9903.91.07",
                "program": "section_301",
                "list": "strategic_medical",
                "sector": "medical",
                "rate": 0.50,
                "confidence": 0.95,
                "resolution_method": "exact_code_match"
            }
        """
        # Combine all available text
        full_text = f"{context or ''}\n{table_text or ''}".lower()

        # Step 1: Look for exact Chapter 99 code in context
        codes = self._find_chapter_99_codes(full_text)

        if codes:
            # Use the most specific (longest) code found
            best_code = max(codes, key=len)
            result = self._resolve_from_code(best_code)
            if result:
                result["resolution_method"] = "exact_code_match"
                result["confidence"] = 0.95
                return result

        # Step 2: Try to infer from program keywords
        program = self._infer_program(full_text)
        if program:
            result = {"program": program}

            # Try to determine sector for 301
            if program == "section_301":
                sector = self._infer_sector(full_text)
                if sector:
                    result["sector"] = sector

            # Try to determine material for 232
            if program == "section_232":
                material = self._infer_material(full_text)
                if material:
                    result["material"] = material

            result["resolution_method"] = "keyword_inference"
            result["confidence"] = 0.70
            return result

        # Step 3: Check for rate patterns
        rate = self._extract_rate(full_text)
        if rate is not None:
            result = {
                "rate": rate,
                "resolution_method": "rate_extraction",
                "confidence": 0.50,
            }
            return result

        # Could not resolve
        logger.warning(f"Could not resolve Chapter 99 code from context (length={len(full_text)})")
        return None

    def _find_chapter_99_codes(self, text: str) -> List[str]:
        """Find all Chapter 99 codes in text."""
        pattern = re.compile(self.CHAPTER_99_PATTERN)
        matches = pattern.findall(text)

        # Reconstruct full codes
        codes = [f"9903.{m[0]}.{m[1]}" for m in matches]

        # Normalize to standard format
        normalized = []
        for code in codes:
            parts = code.split(".")
            if len(parts) == 3:
                # Pad middle part to 2 digits, last part to 2-4 digits
                normalized.append(f"9903.{parts[1][:2]}.{parts[2]}")

        return list(set(normalized))

    def _resolve_from_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Resolve program details from a specific Chapter 99 code."""
        # Try exact match first
        if code in self.PROGRAM_MAPPINGS:
            return dict(chapter_99_code=code, **self.PROGRAM_MAPPINGS[code])

        # Try prefix match
        prefix = code[:7]  # "9903.XX"
        if prefix in self.PREFIX_MAPPINGS:
            return dict(chapter_99_code=code, **self.PREFIX_MAPPINGS[prefix])

        # Try shorter prefix
        prefix = code[:6]  # "9903.X"
        for known_prefix, mapping in self.PREFIX_MAPPINGS.items():
            if known_prefix.startswith(prefix):
                return dict(chapter_99_code=code, **mapping)

        return None

    def _infer_program(self, text: str) -> Optional[str]:
        """Infer program from keywords in text."""
        text_lower = text.lower()

        # Count keyword matches for each program
        scores = {}
        for program, keywords in self.PROGRAM_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[program] = score

        if scores:
            return max(scores, key=scores.get)
        return None

    def _infer_sector(self, text: str) -> Optional[str]:
        """Infer sector from keywords (for Section 301)."""
        text_lower = text.lower()

        scores = {}
        for sector, keywords in self.SECTOR_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[sector] = score

        if scores:
            return max(scores, key=scores.get)
        return None

    def _infer_material(self, text: str) -> Optional[str]:
        """Infer material type from keywords (for Section 232)."""
        text_lower = text.lower()

        if "copper" in text_lower:
            return "copper"
        if "aluminum" in text_lower or "aluminium" in text_lower:
            return "aluminum"
        if "steel" in text_lower or "iron" in text_lower:
            return "steel"

        return None

    def _extract_rate(self, text: str) -> Optional[float]:
        """Extract rate from text patterns like "25 percent" or "25%"."""
        patterns = [
            r'(\d+(?:\.\d+)?)\s*(?:percent|pct|%)',
            r'rate\s*(?:of\s*)?(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*ad\s*valorem',
        ]

        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                rate = float(match.group(1))
                if rate <= 100:  # Sanity check
                    return rate / 100.0  # Convert to decimal

        return None

    def resolve_for_hts(self, hts_code: str, context: str) -> Optional[Dict[str, Any]]:
        """
        Resolve Chapter 99 code for a specific HTS code.

        Uses HTS chapter to help determine the correct code.
        """
        hts_chapter = hts_code[:2]

        # First try standard resolution
        result = self.resolve(context)
        if result and result.get("chapter_99_code"):
            return result

        # Use HTS chapter to refine resolution
        if result and result.get("program") == "section_232":
            material = result.get("material")

            if material == "steel":
                # Determine if primary or derivative
                if hts_chapter in ("72", "73"):
                    if hts_chapter == "73":
                        # Could be primary or derivative in Ch 73
                        result["chapter_99_code"] = "9903.81.90"
                        result["article"] = "derivative_ch73"
                    else:
                        result["chapter_99_code"] = "9903.80.01"
                        result["article"] = "primary"
                else:
                    result["chapter_99_code"] = "9903.81.91"
                    result["article"] = "derivative_other"

            elif material == "aluminum":
                if hts_chapter == "76":
                    result["chapter_99_code"] = "9903.85.03"
                    result["article"] = "primary"
                else:
                    result["chapter_99_code"] = "9903.85.08"
                    result["article"] = "derivative_other"

            elif material == "copper":
                result["chapter_99_code"] = "9903.78.01"

        return result

    def get_staged_rates(self, context: str) -> List[Dict[str, Any]]:
        """
        Extract staged rate schedules from context.

        Handles cases like Four-Year Review:
        "25% effective January 1, 2025"
        "50% effective January 1, 2026"

        Returns list of {rate, effective_date} dicts.
        """
        rates = []

        # Pattern: rate + effective date
        pattern = r'(\d+(?:\.\d+)?)\s*(?:percent|pct|%)[^.]*?(?:effective|beginning|starting|on)\s+(\w+\s+\d+,?\s*\d{4})'

        for match in re.finditer(pattern, context.lower()):
            rate_str = match.group(1)
            date_str = match.group(2)

            try:
                rate = float(rate_str) / 100.0

                # Parse date
                from dateutil import parser
                effective_date = parser.parse(date_str).date()

                rates.append({
                    "rate": rate,
                    "effective_date": effective_date,
                })
            except Exception as e:
                logger.debug(f"Could not parse staged rate: {e}")

        return sorted(rates, key=lambda x: x["effective_date"])
