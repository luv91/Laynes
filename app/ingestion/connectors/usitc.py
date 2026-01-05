"""
USITC Connector - Harmonized Tariff Schedule (v10.0 Phase 2)

Fetches official HTS data from hts.usitc.gov.
These are Tier-A documents that can be used for verified assertions.

USITC data contains:
- Official HTS code listings
- Chapter 99 codes (additional duties)
- Rate information
- Notes and annexes
"""

import re
from datetime import datetime
from typing import Optional, Set

from app.ingestion.connectors.base import BaseConnector


class USITCConnector(BaseConnector):
    """
    Trusted connector for USITC HTS schedule.

    Tier: A (write-allowed)
    Domains: hts.usitc.gov, usitc.gov
    """

    TRUSTED_DOMAINS: Set[str] = {
        'hts.usitc.gov',
        'usitc.gov',
        'www.usitc.gov',
    }
    SOURCE_TYPE: str = "USITC"
    TIER: str = "A"
    CONNECTOR_NAME: str = "usitc_connector"

    # Chapter pattern
    CHAPTER_PATTERN = re.compile(r'Chapter\s+(\d{1,2})', re.IGNORECASE)

    # Note/Annex pattern
    NOTE_PATTERN = re.compile(r'Note\s+(\d+)(?:\(([a-z])\))?', re.IGNORECASE)

    # Revision date pattern
    REVISION_PATTERN = re.compile(
        r'(?:revised|revision|effective)\s*(?:date)?[:\s]*(\d{1,2}/\d{1,2}/\d{4})',
        re.IGNORECASE
    )

    def extract_canonical_id(self, content: str, url: str) -> Optional[str]:
        """Extract chapter or section identifier."""
        # Try to extract chapter
        chapter_match = self.CHAPTER_PATTERN.search(content)
        if chapter_match:
            chapter_num = chapter_match.group(1).zfill(2)
            return f"HTS-CH{chapter_num}"

        # Try to extract note
        note_match = self.NOTE_PATTERN.search(content)
        if note_match:
            note_num = note_match.group(1)
            sub = note_match.group(2) if note_match.group(2) else ""
            return f"HTS-NOTE{note_num}{sub.upper()}"

        # Extract from URL
        if 'chapter' in url.lower():
            ch_match = re.search(r'chapter[_-]?(\d+)', url, re.IGNORECASE)
            if ch_match:
                return f"HTS-CH{ch_match.group(1).zfill(2)}"

        if '9903' in content:
            return "HTS-CH99"

        return None

    def extract_effective_date(self, content: str) -> Optional[datetime]:
        """Extract revision/effective date from HTS data."""
        match = self.REVISION_PATTERN.search(content)
        if match:
            date_str = match.group(1)
            try:
                return datetime.strptime(date_str, '%m/%d/%Y')
            except ValueError:
                pass
        return None

    def extract_chapter_99_codes(self, content: str) -> list:
        """
        Extract all Chapter 99 codes (9903.xx.xx format).

        These are the additional duty codes for Section 232, 301, IEEPA, etc.
        """
        return list(set(self.CHAPTER_99_PATTERN.findall(content)))

    def extract_hts_ranges(self, content: str) -> list:
        """
        Extract HTS code ranges (e.g., "8501.10.20 through 8504.40.95").

        Returns list of (start, end) tuples.
        """
        range_pattern = re.compile(
            r'(\d{4}(?:\.\d{2}){1,3})\s+(?:through|to|-)\s+(\d{4}(?:\.\d{2}){1,3})',
            re.IGNORECASE
        )
        return range_pattern.findall(content)
