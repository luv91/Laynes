"""
CBP CSMS Watcher

Monitors the CBP Cargo Systems Messaging Service (CSMS) for new bulletins
related to Section 232 tariffs and ACE filing requirements.

CSMS provides operational guidance that often contains:
- New HTS codes for 232 programs
- Effective dates for tariff changes
- ACE reporting requirements
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import List, Optional
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from app.watchers.base import BaseWatcher, DiscoveredDocument

logger = logging.getLogger(__name__)


class CBPCSMSWatcher(BaseWatcher):
    """
    Watches CBP CSMS archive for tariff-related bulletins.

    CSMS bulletins provide operational filing instructions for:
    - Section 232 reporting codes (steel, aluminum, copper)
    - Implementation dates and deadlines
    - ACE system updates

    Note: CBP restructured their CSMS system in 2025. The new structure:
    - Main info: https://www.cbp.gov/trade/automated/cargo-systems-messaging-service
    - Archive PDFs: https://www.cbp.gov/document/guidance/csms-archive
    - Legacy system (may timeout): https://csms.cbp.gov/csms.asp

    We now check the archive page for new PDF releases and can download
    the monthly compiled bulletins.
    """

    SOURCE_NAME = "cbp_csms"
    POLL_INTERVAL_HOURS = 12
    BASE_URL = "https://www.cbp.gov"

    # New archive structure (2025+)
    ARCHIVE_URL = "https://www.cbp.gov/document/guidance/csms-archive"
    INFO_URL = "https://www.cbp.gov/trade/automated/cargo-systems-messaging-service"

    # Legacy URL (may be slow/unavailable)
    LEGACY_URL = "https://csms.cbp.gov/csms.asp?display_page=1"

    # Keywords to filter relevant bulletins
    KEYWORDS = [
        "section 232",
        "section 301",
        "steel",
        "aluminum",
        "copper",
        "tariff",
        "9903",
        "chapter 99",
        "htsus",
        "duty",
    ]

    def poll(self, since_date: Optional[date] = None) -> List[DiscoveredDocument]:
        """
        Poll CSMS archive for new bulletins.

        CBP restructured their CSMS system in 2025. We now:
        1. Check the archive page for PDF compilations
        2. Look for new monthly archive PDFs

        Note: Individual bulletins are no longer directly scrapeable.
        The archive PDFs contain compiled bulletins.
        """
        if since_date is None:
            since_date = self.get_last_poll_date()

        discovered = []

        try:
            # Fetch new archive page (has PDF links)
            response = requests.get(
                self.ARCHIVE_URL,
                timeout=30,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; RegulatoryBot/1.0)'}
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find CSMS archive PDF links
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text(strip=True)

                # Look for CSMS archive PDFs
                if 'csms' in href.lower() and '.pdf' in href.lower():
                    # Extract date range from text (e.g., "January 2021 - November 2025")
                    date_match = re.search(
                        r'(\w+)\s+(\d{4})\s*[-–]\s*(\w+)\s+(\d{4})',
                        text
                    )

                    if date_match:
                        end_month = date_match.group(3)
                        end_year = int(date_match.group(4))

                        # Check if this archive includes recent bulletins
                        archive_end = self._parse_month_year(end_month, end_year)
                        if archive_end and (since_date is None or archive_end >= since_date):
                            full_url = urljoin(self.BASE_URL, href)

                            # Create unique ID from date range
                            start_month = date_match.group(1)
                            start_year = date_match.group(2)
                            external_id = f"CSMS_archive_{start_year}_{end_year}"

                            discovered.append(DiscoveredDocument(
                                source=self.SOURCE_NAME,
                                external_id=external_id,
                                title=f"CSMS Archive: {text}",
                                html_url=full_url,
                                publication_date=archive_end,
                                discovered_by=f"{self.SOURCE_NAME}_watcher",
                                metadata={
                                    "type": "archive_pdf",
                                    "start_month": start_month,
                                    "start_year": start_year,
                                    "end_month": end_month,
                                    "end_year": str(end_year),
                                }
                            ))

        except Exception as e:
            logger.error(f"CSMS archive fetch failed: {e}")
            raise

        # Deduplicate
        discovered = self.deduplicate(discovered)

        logger.info(f"CSMS watcher found {len(discovered)} archive documents")
        return discovered

    def _parse_month_year(self, month_name: str, year: int) -> Optional[date]:
        """Parse a month name and year into a date (last day of month)."""
        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        month_num = month_map.get(month_name.lower())
        if month_num:
            # Return last day of month
            if month_num == 12:
                return date(year, 12, 31)
            else:
                return date(year, month_num + 1, 1) - timedelta(days=1)
        return None

    def _extract_date(self, link_element) -> Optional[date]:
        """
        Try to extract publication date from element context.

        Looks for date patterns in parent/sibling elements.
        """
        # Common date patterns
        date_patterns = [
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY
            r'(\d{4})-(\d{2})-(\d{2})',       # YYYY-MM-DD
            r'(\w+)\s+(\d{1,2}),?\s+(\d{4})', # Month DD, YYYY
        ]

        # Check parent row/cell for date
        parent = link_element.parent
        for _ in range(3):  # Check up to 3 levels
            if parent is None:
                break

            parent_text = parent.get_text()

            # Try MM/DD/YYYY
            match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', parent_text)
            if match:
                try:
                    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    return date(year, month, day)
                except (ValueError, TypeError):
                    pass

            # Try YYYY-MM-DD
            match = re.search(r'(\d{4})-(\d{2})-(\d{2})', parent_text)
            if match:
                try:
                    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    return date(year, month, day)
                except (ValueError, TypeError):
                    pass

            parent = parent.parent

        return None

    def _is_tariff_related(self, text: str) -> bool:
        """Check if bulletin text contains tariff-related keywords."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.KEYWORDS)

    def fetch_bulletin_content(self, url: str) -> Optional[str]:
        """
        Fetch the full content of a CSMS bulletin.

        Args:
            url: Full URL to the bulletin page

        Returns:
            Text content of the bulletin, or None if failed
        """
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Try to find the main content area
            content_div = soup.find('div', class_='field-items') or \
                         soup.find('article') or \
                         soup.find('main')

            if content_div:
                return content_div.get_text(separator='\n', strip=True)

            return soup.get_text(separator='\n', strip=True)

        except Exception as e:
            logger.error(f"Failed to fetch bulletin {url}: {e}")
            return None

    def fetch_attachments(self, url: str) -> List[dict]:
        """
        Find and return attachment URLs from a CSMS bulletin page.

        Many CSMS bulletins have PDF or DOCX attachments with HTS lists.

        Args:
            url: Full URL to the bulletin page

        Returns:
            List of dicts with 'url', 'filename', 'type' keys
        """
        attachments = []

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find attachment links (PDF, DOCX, XLSX)
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                href_lower = href.lower()

                if any(ext in href_lower for ext in ['.pdf', '.docx', '.xlsx', '.doc', '.xls']):
                    full_url = urljoin(self.BASE_URL, href)
                    filename = href.split('/')[-1]

                    # Determine type
                    if '.pdf' in href_lower:
                        file_type = 'pdf'
                    elif '.doc' in href_lower:
                        file_type = 'docx'
                    elif '.xls' in href_lower:
                        file_type = 'xlsx'
                    else:
                        file_type = 'unknown'

                    attachments.append({
                        'url': full_url,
                        'filename': filename,
                        'type': file_type,
                    })

        except Exception as e:
            logger.error(f"Failed to fetch attachments from {url}: {e}")

        return attachments
