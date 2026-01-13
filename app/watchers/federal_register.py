"""
Federal Register Watcher

Polls the Federal Register API for new tariff-related notices:
- Section 301 modifications (USTR)
- IEEPA notices (Executive Orders)
- Tariff modifications

API Documentation: https://www.federalregister.gov/developers/documentation/api/v1
"""

import logging
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import quote
import requests

from app.watchers.base import BaseWatcher, DiscoveredDocument

logger = logging.getLogger(__name__)


class FederalRegisterWatcher(BaseWatcher):
    """
    Watches Federal Register API for tariff-related notices.

    The Federal Register provides a JSON API that we poll for:
    - Section 301 China tariff modifications
    - IEEPA emergency tariff notices
    - USTR tariff announcements

    Key advantages of this source:
    - Structured JSON API (no scraping needed)
    - XML full text available with <GPOTABLE> structured tables
    - Machine-readable document metadata
    """

    SOURCE_NAME = "federal_register"
    POLL_INTERVAL_HOURS = 6
    BASE_URL = "https://www.federalregister.gov/api/v1"

    # Agencies to monitor
    AGENCIES = [
        "office-of-the-united-states-trade-representative",
        "international-trade-administration",
        "customs-and-border-protection",
    ]

    # Search queries - each returns documents matching these terms
    SEARCH_QUERIES = [
        # Section 301
        {"term": "section 301", "type": "NOTICE"},
        {"term": "9903.88", "type": None},  # Original 301 codes
        {"term": "9903.91", "type": None},  # 2024 review codes
        {"term": "China tariff modification", "type": "NOTICE"},

        # IEEPA
        {"term": "IEEPA", "type": "NOTICE"},
        {"term": "fentanyl tariff", "type": None},
        {"term": "reciprocal tariff", "type": None},

        # Section 232
        {"term": "section 232", "type": "NOTICE"},
        {"term": "steel aluminum tariff", "type": None},

        # General
        {"term": "tariff modification", "type": "NOTICE"},
        {"term": "9903", "type": None},  # All Chapter 99 codes
    ]

    def poll(self, since_date: Optional[date] = None) -> List[DiscoveredDocument]:
        """
        Poll Federal Register API for new documents.

        Args:
            since_date: Only return documents published after this date

        Returns:
            List of DiscoveredDocument objects
        """
        if since_date is None:
            since_date = self.get_last_poll_date()

        discovered = []
        seen_ids = set()

        for query in self.SEARCH_QUERIES:
            try:
                docs = self._search(
                    term=query["term"],
                    since_date=since_date,
                    doc_type=query.get("type")
                )

                for doc in docs:
                    if doc.external_id not in seen_ids:
                        seen_ids.add(doc.external_id)
                        discovered.append(doc)

            except Exception as e:
                logger.warning(f"FR search failed for '{query['term']}': {e}")

        logger.info(f"Federal Register watcher found {len(discovered)} documents")
        return discovered

    def _search(self, term: str, since_date: date,
                doc_type: Optional[str] = None) -> List[DiscoveredDocument]:
        """
        Execute a single search query against the FR API.

        Args:
            term: Search term
            since_date: Only return documents after this date
            doc_type: Optional document type filter (NOTICE, RULE, etc.)

        Returns:
            List of DiscoveredDocument objects
        """
        params = {
            "conditions[term]": term,
            "conditions[publication_date][gte]": since_date.isoformat(),
            "order": "newest",
            "per_page": self.MAX_RESULTS_PER_POLL,
        }

        if doc_type:
            params["conditions[type][]"] = doc_type

        url = f"{self.BASE_URL}/documents.json"
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = []

        for doc in data.get("results", []):
            # Parse dates
            pub_date = None
            if doc.get("publication_date"):
                pub_date = date.fromisoformat(doc["publication_date"])

            eff_date = None
            if doc.get("effective_on"):
                eff_date = date.fromisoformat(doc["effective_on"])

            # Check relevance - skip unrelated documents
            if not self._is_tariff_related(doc):
                continue

            results.append(DiscoveredDocument(
                source=self.SOURCE_NAME,
                external_id=doc["document_number"],
                title=doc.get("title", ""),
                publication_date=pub_date,
                effective_date=eff_date,
                pdf_url=doc.get("pdf_url"),
                xml_url=doc.get("full_text_xml_url"),
                html_url=doc.get("html_url"),
                discovered_by=f"{self.SOURCE_NAME}_watcher",
                metadata={
                    "type": doc.get("type"),
                    "agencies": [a.get("name") for a in doc.get("agencies", [])],
                    "abstract": doc.get("abstract"),
                    "action": doc.get("action"),
                    "docket_ids": doc.get("docket_ids", []),
                    "cfr_references": doc.get("cfr_references", []),
                }
            ))

        return results

    def _is_tariff_related(self, doc: dict) -> bool:
        """
        Filter documents to only include tariff-related ones.

        Checks title, abstract, and agencies for tariff keywords.
        """
        tariff_keywords = [
            "tariff", "duty", "section 301", "section 232",
            "ieepa", "hts", "harmonized", "9903",
            "china", "trade representative", "customs"
        ]

        # Check title
        title = (doc.get("title") or "").lower()
        if any(kw in title for kw in tariff_keywords):
            return True

        # Check abstract
        abstract = (doc.get("abstract") or "").lower()
        if any(kw in abstract for kw in tariff_keywords):
            return True

        # Check agencies
        for agency in doc.get("agencies", []):
            agency_name = (agency.get("name") or "").lower()
            if "trade" in agency_name or "customs" in agency_name:
                return True

        return False

    def get_document_xml(self, document_number: str) -> Optional[str]:
        """
        Fetch the full XML text for a specific document.

        Args:
            document_number: The FR document number (e.g., "2024-21217")

        Returns:
            XML content as string, or None if not available
        """
        # Get document metadata first
        url = f"{self.BASE_URL}/documents/{document_number}.json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()
        xml_url = data.get("full_text_xml_url")

        if not xml_url:
            return None

        # Fetch XML content
        xml_response = requests.get(xml_url, timeout=60)
        xml_response.raise_for_status()

        return xml_response.text

    def get_document_metadata(self, document_number: str) -> dict:
        """
        Get full metadata for a specific document.

        Args:
            document_number: The FR document number

        Returns:
            Document metadata dict
        """
        url = f"{self.BASE_URL}/documents/{document_number}.json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
