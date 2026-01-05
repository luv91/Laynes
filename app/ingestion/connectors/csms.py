"""
CSMS Connector - CBP Cargo Systems Messaging Service (v10.0 Phase 2)

Fetches official CBP CSMS bulletins from content.govdelivery.com.
These are Tier-A documents that can be used for verified assertions.

CSMS bulletins contain:
- Section 232 scope updates
- Rate changes
- HTS code additions/removals
- Effective date announcements
"""

import re
from datetime import datetime
from typing import Optional, Set

from app.ingestion.connectors.base import BaseConnector


class CSMSConnector(BaseConnector):
    """
    Trusted connector for CBP CSMS bulletins.

    Tier: A (write-allowed)
    Domains: content.govdelivery.com, www.cbp.gov
    """

    TRUSTED_DOMAINS: Set[str] = {
        'content.govdelivery.com',
        'www.cbp.gov',
        'cbp.gov',
    }
    SOURCE_TYPE: str = "CSMS"
    TIER: str = "A"
    CONNECTOR_NAME: str = "csms_connector"

    # CSMS number pattern: CSMS #XXXXXXXX or CSMS#XXXXXXXX
    CSMS_PATTERN = re.compile(r'CSMS\s*#?\s*(\d{8})', re.IGNORECASE)

    # Effective date patterns
    DATE_PATTERNS = [
        re.compile(r'effective\s+(?:on\s+)?(\w+\s+\d{1,2},?\s+\d{4})', re.IGNORECASE),
        re.compile(r'effective\s+(?:date|as of)[:\s]+(\d{1,2}/\d{1,2}/\d{4})', re.IGNORECASE),
        re.compile(r'(\w+\s+\d{1,2},?\s+\d{4})\s+effective', re.IGNORECASE),
    ]

    def extract_canonical_id(self, content: str, url: str) -> Optional[str]:
        """Extract CSMS bulletin number."""
        match = self.CSMS_PATTERN.search(content)
        if match:
            return f"CSMS#{match.group(1)}"

        # Try to extract from URL
        url_match = re.search(r'(\d{8})', url)
        if url_match:
            return f"CSMS#{url_match.group(1)}"

        return None

    def extract_effective_date(self, content: str) -> Optional[datetime]:
        """Extract effective date from CSMS bulletin."""
        for pattern in self.DATE_PATTERNS:
            match = pattern.search(content)
            if match:
                date_str = match.group(1)
                # Try to parse the date
                for fmt in ['%B %d, %Y', '%B %d %Y', '%m/%d/%Y']:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
        return None

    def extract_232_updates(self, content: str) -> dict:
        """
        Extract Section 232 scope updates from CSMS bulletin.

        Returns dict with:
        - materials: List of materials mentioned
        - action: 'add', 'remove', 'update'
        - hts_codes: List of HTS codes affected
        """
        text_lower = content.lower()

        materials = []
        if 'copper' in text_lower:
            materials.append('copper')
        if 'steel' in text_lower:
            materials.append('steel')
        if 'aluminum' in text_lower:
            materials.append('aluminum')

        action = None
        if 'add' in text_lower or 'include' in text_lower or 'subject to' in text_lower:
            action = 'add'
        elif 'remove' in text_lower or 'exclude' in text_lower:
            action = 'remove'
        elif 'update' in text_lower or 'change' in text_lower:
            action = 'update'

        hts_codes = self._find_hts_codes(content)

        return {
            'materials': materials,
            'action': action,
            'hts_codes': hts_codes,
        }
