"""
GovInfo Connector - Federal Register Notices (v10.0 Phase 2)

Fetches official Federal Register notices from federalregister.gov.
These are Tier-A documents that can be used for verified assertions.

Federal Register notices contain:
- Executive Orders
- Proclamations (Section 232, Section 301)
- Rate changes and scope modifications
- Official HTS annexes
"""

import re
from datetime import datetime
from typing import Optional, Set

from app.ingestion.connectors.base import BaseConnector


class GovInfoConnector(BaseConnector):
    """
    Trusted connector for Federal Register notices.

    Tier: A (write-allowed)
    Domains: federalregister.gov, www.federalregister.gov, api.govinfo.gov
    """

    TRUSTED_DOMAINS: Set[str] = {
        'federalregister.gov',
        'www.federalregister.gov',
        'api.govinfo.gov',
        'govinfo.gov',
    }
    SOURCE_TYPE: str = "FEDERAL_REGISTER"
    TIER: str = "A"
    CONNECTOR_NAME: str = "govinfo_connector"

    # Federal Register citation pattern: XX FR XXXXX
    FR_PATTERN = re.compile(r'(\d{1,3})\s*FR\s*(\d+)', re.IGNORECASE)

    # Document number pattern
    DOC_PATTERN = re.compile(r'Document\s*(?:Number|No\.?|#)?\s*[:\s]*(\d{4}-\d+)', re.IGNORECASE)

    # Executive Order pattern
    EO_PATTERN = re.compile(r'Executive\s+Order\s+(\d+)', re.IGNORECASE)

    # Proclamation pattern
    PROC_PATTERN = re.compile(r'Proclamation\s+(\d+)', re.IGNORECASE)

    # Date patterns
    DATE_PATTERNS = [
        re.compile(r'effective\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})', re.IGNORECASE),
        re.compile(r'(?:signed|dated)\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})', re.IGNORECASE),
        re.compile(r'Publication\s+Date[:\s]+(\d{2}/\d{2}/\d{4})', re.IGNORECASE),
    ]

    def extract_canonical_id(self, content: str, url: str) -> Optional[str]:
        """Extract Federal Register citation or document number."""
        # Try FR citation first
        fr_match = self.FR_PATTERN.search(content)
        if fr_match:
            return f"{fr_match.group(1)} FR {fr_match.group(2)}"

        # Try document number
        doc_match = self.DOC_PATTERN.search(content)
        if doc_match:
            return f"FR-{doc_match.group(1)}"

        # Try EO number
        eo_match = self.EO_PATTERN.search(content)
        if eo_match:
            return f"EO-{eo_match.group(1)}"

        # Try Proclamation number
        proc_match = self.PROC_PATTERN.search(content)
        if proc_match:
            return f"PROC-{proc_match.group(1)}"

        # Extract from URL
        url_match = re.search(r'/documents?/(\d{4}-\d+)', url)
        if url_match:
            return f"FR-{url_match.group(1)}"

        return None

    def extract_effective_date(self, content: str) -> Optional[datetime]:
        """Extract effective date from Federal Register notice."""
        for pattern in self.DATE_PATTERNS:
            match = pattern.search(content)
            if match:
                date_str = match.group(1)
                for fmt in ['%B %d, %Y', '%B %d %Y', '%m/%d/%Y']:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
        return None

    def extract_annex_hts_codes(self, content: str) -> dict:
        """
        Extract HTS codes from annex sections (common in 232/301 notices).

        Returns dict with:
        - steel_hts: List of steel HTS codes
        - aluminum_hts: List of aluminum HTS codes
        - copper_hts: List of copper HTS codes
        - other_hts: Other HTS codes
        """
        text_lower = content.lower()
        all_hts = self._find_hts_codes(content)

        result = {
            'steel_hts': [],
            'aluminum_hts': [],
            'copper_hts': [],
            'other_hts': [],
        }

        # Simple heuristic: look at context around HTS codes
        for hts in all_hts:
            # Find context (100 chars before)
            idx = content.find(hts)
            if idx > 0:
                context = content[max(0, idx - 100):idx].lower()
                if 'steel' in context:
                    result['steel_hts'].append(hts)
                elif 'aluminum' in context:
                    result['aluminum_hts'].append(hts)
                elif 'copper' in context:
                    result['copper_hts'].append(hts)
                else:
                    result['other_hts'].append(hts)
            else:
                result['other_hts'].append(hts)

        return result
