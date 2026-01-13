"""
USITC HTS Watcher

Monitors the US International Trade Commission for HTS updates:
- Annual HTS editions
- Interim modifications
- Base rate changes

The USITC provides the official Harmonized Tariff Schedule which
includes MFN Column 1 base duty rates.
"""

import logging
from datetime import date, datetime
from typing import List, Optional, Dict
import requests

from app.watchers.base import BaseWatcher, DiscoveredDocument

logger = logging.getLogger(__name__)


class USITCWatcher(BaseWatcher):
    """
    Watches USITC for HTS updates.

    Two modes of operation:
    1. Bulk sync: Check for new annual HTS edition releases
    2. On-demand: Verify specific HTS codes via RESTStop API

    RESTStop API: https://hts.usitc.gov/reststop/
    """

    SOURCE_NAME = "usitc"
    POLL_INTERVAL_HOURS = 24  # Daily check
    BASE_URL = "https://hts.usitc.gov"
    RESTSTOP_URL = "https://hts.usitc.gov/reststop"

    # Known HTS edition URLs pattern
    # The USITC publishes CSV editions at predictable URLs
    HTS_EDITIONS = {
        2026: "https://hts.usitc.gov/current",  # Current year
        2025: "https://hts.usitc.gov/view/2025",
    }

    def poll(self, since_date: Optional[date] = None) -> List[DiscoveredDocument]:
        """
        Check for new HTS edition or updates.

        For USITC, we primarily check if a new edition has been released.
        Detailed rate verification happens on-demand via RESTStop.
        """
        if since_date is None:
            since_date = self.get_last_poll_date()

        discovered = []

        # Check for current year edition
        current_year = date.today().year

        try:
            # Check if we can access the current year's HTS
            edition_url = f"{self.BASE_URL}/current"
            response = requests.head(edition_url, timeout=10, allow_redirects=True)

            if response.status_code == 200:
                discovered.append(DiscoveredDocument(
                    source=self.SOURCE_NAME,
                    external_id=f"HTS_{current_year}_edition",
                    title=f"Harmonized Tariff Schedule {current_year} Edition",
                    html_url=edition_url,
                    discovered_by=f"{self.SOURCE_NAME}_watcher",
                    metadata={
                        "edition_year": current_year,
                        "type": "annual_edition",
                    }
                ))

        except Exception as e:
            logger.warning(f"USITC edition check failed: {e}")

        logger.info(f"USITC watcher found {len(discovered)} updates")
        return discovered

    def verify_hts_code(self, hts_code: str) -> Optional[Dict]:
        """
        Verify a specific HTS code via the RESTStop API.

        This is used for on-demand verification of rates, not for
        bulk discovery.

        Args:
            hts_code: HTS code to look up (e.g., "8544.42.90")

        Returns:
            Dict with HTS data, or None if not found
        """
        try:
            # Clean up HTS code
            clean_code = hts_code.replace(".", "")

            url = f"{self.RESTSTOP_URL}/search"
            params = {"keyword": clean_code}

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                # Find exact match
                for item in data:
                    item_code = item.get("htsno", "").replace(".", "")
                    if item_code.startswith(clean_code) or clean_code.startswith(item_code):
                        return {
                            "hts_code": item.get("htsno"),
                            "description": item.get("description"),
                            "general_rate": item.get("general"),
                            "special_rate": item.get("special"),
                            "column2_rate": item.get("other"),
                            "footnotes": item.get("footnotes", []),
                            "unit": item.get("units"),
                        }

            return None

        except Exception as e:
            logger.error(f"USITC RESTStop lookup failed for {hts_code}: {e}")
            return None

    def get_chapter_notes(self, chapter: int) -> Optional[str]:
        """
        Get the notes for a specific HTS chapter.

        Useful for understanding special rules that apply to certain products.

        Args:
            chapter: Chapter number (1-99)

        Returns:
            Chapter notes text, or None if not found
        """
        try:
            url = f"{self.RESTSTOP_URL}/chapter/{chapter}/notes"
            response = requests.get(url, timeout=30)

            if response.status_code == 200:
                return response.text

            return None

        except Exception as e:
            logger.error(f"Failed to fetch chapter {chapter} notes: {e}")
            return None

    def download_csv_edition(self, year: int = None) -> Optional[bytes]:
        """
        Download the CSV edition of the HTS for a given year.

        The USITC provides CSV exports of the full HTS schedule.

        Args:
            year: Edition year (defaults to current year)

        Returns:
            CSV content as bytes, or None if not available
        """
        if year is None:
            year = date.today().year

        try:
            # The CSV download URL varies - this is a common pattern
            url = f"{self.BASE_URL}/api/hts/{year}/csv"

            response = requests.get(url, timeout=120)  # Large file

            if response.status_code == 200:
                return response.content

            # Try alternate URL pattern
            url = f"{self.BASE_URL}/view/{year}/export/csv"
            response = requests.get(url, timeout=120)

            if response.status_code == 200:
                return response.content

            return None

        except Exception as e:
            logger.error(f"Failed to download HTS CSV for {year}: {e}")
            return None
