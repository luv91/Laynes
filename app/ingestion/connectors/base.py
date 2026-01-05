"""
Base Connector for Trusted Document Ingestion (v10.0 Phase 2)

All trusted connectors inherit from BaseConnector and implement:
- Domain validation (only fetch from trusted domains)
- Content hashing (SHA-256 for integrity)
- Audit logging (fetch timestamps, headers, status)
- Text extraction (HTML to clean text)

Tier system:
- Tier A: Write-allowed (CSMS, Federal Register, USITC)
- Tier B: Signals only (USTR press, White House)
- Tier C: Discovery hints only (law firms, blogs)
"""

import hashlib
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class UntrustedSourceError(Exception):
    """Raised when attempting to fetch from an untrusted domain."""
    pass


class FetchError(Exception):
    """Raised when document fetch fails."""
    pass


@dataclass
class ConnectorResult:
    """Result from a connector fetch operation."""
    success: bool
    document_id: str
    source: str
    tier: str
    connector_name: str
    canonical_id: Optional[str]
    url: str
    title: Optional[str]
    raw_content: str
    extracted_text: str
    sha256_raw: str
    published_at: Optional[datetime]
    effective_start: Optional[datetime]
    fetch_log: Dict[str, Any]
    hts_codes_found: List[str] = field(default_factory=list)
    programs_found: List[str] = field(default_factory=list)
    error: Optional[str] = None


class BaseConnector(ABC):
    """
    Abstract base class for trusted document connectors.

    Subclasses must implement:
    - TRUSTED_DOMAINS: Set of allowed domains
    - SOURCE_TYPE: Source identifier ('CSMS', 'FEDERAL_REGISTER', 'USITC')
    - TIER: Document tier ('A', 'B', 'C')
    - extract_canonical_id(): Extract document identifier from content
    - extract_effective_date(): Extract effective date if present
    """

    TRUSTED_DOMAINS: Set[str] = set()
    SOURCE_TYPE: str = "UNKNOWN"
    TIER: str = "C"
    CONNECTOR_NAME: str = "base_connector"

    # HTS code pattern: 4-10 digits with optional dots
    HTS_PATTERN = re.compile(r'\b(\d{4}(?:\.\d{2}){0,3})\b')

    # Chapter 99 pattern
    CHAPTER_99_PATTERN = re.compile(r'\b(9903\.\d{2}\.\d{2})\b')

    def __init__(self, timeout: int = 30):
        """Initialize connector with request timeout."""
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LanesTariffBot/1.0 (Legal-Grade Tariff Verification)'
        })

    def _is_trusted_domain(self, url: str) -> bool:
        """Check if URL domain is in the trusted list."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Check exact match or subdomain match
            for trusted in self.TRUSTED_DOMAINS:
                if domain == trusted or domain.endswith('.' + trusted):
                    return True
            return False
        except Exception:
            return False

    def _compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _extract_text(self, html: str) -> str:
        """Extract clean text from HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()

        # Get text
        text = soup.get_text(separator='\n')

        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines()]
        text = '\n'.join(line for line in lines if line)

        return text

    def _extract_title(self, html: str) -> Optional[str]:
        """Extract title from HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text().strip()
        h1_tag = soup.find('h1')
        if h1_tag:
            return h1_tag.get_text().strip()
        return None

    def _find_hts_codes(self, text: str) -> List[str]:
        """Find HTS codes mentioned in text."""
        matches = self.HTS_PATTERN.findall(text)
        # Deduplicate and sort
        return sorted(set(matches))

    def _find_programs(self, text: str) -> List[str]:
        """Find tariff programs mentioned in text."""
        programs = []
        text_lower = text.lower()

        if 'section 232' in text_lower or '232' in text_lower:
            if 'steel' in text_lower:
                programs.append('section_232_steel')
            if 'aluminum' in text_lower:
                programs.append('section_232_aluminum')
            if 'copper' in text_lower:
                programs.append('section_232_copper')

        if 'section 301' in text_lower:
            programs.append('section_301')

        if 'ieepa' in text_lower or 'reciprocal' in text_lower:
            programs.append('ieepa_reciprocal')

        if 'fentanyl' in text_lower:
            programs.append('ieepa_fentanyl')

        return list(set(programs))

    @abstractmethod
    def extract_canonical_id(self, content: str, url: str) -> Optional[str]:
        """Extract canonical document identifier (e.g., CSMS number)."""
        pass

    @abstractmethod
    def extract_effective_date(self, content: str) -> Optional[datetime]:
        """Extract effective date from document content."""
        pass

    def fetch(self, url: str) -> ConnectorResult:
        """
        Fetch document from URL with full audit trail.

        Args:
            url: The URL to fetch

        Returns:
            ConnectorResult with document data and metadata

        Raises:
            UntrustedSourceError: If domain is not in trusted list
            FetchError: If fetch fails
        """
        # Validate domain
        if not self._is_trusted_domain(url):
            raise UntrustedSourceError(
                f"Domain not in {self.CONNECTOR_NAME} allowlist: {urlparse(url).netloc}"
            )

        document_id = str(uuid.uuid4())
        fetch_start = datetime.utcnow()

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            raw_content = response.text
            sha256_raw = self._compute_hash(raw_content)
            extracted_text = self._extract_text(raw_content)
            title = self._extract_title(raw_content)

            # Extract metadata
            canonical_id = self.extract_canonical_id(raw_content, url)
            effective_date = self.extract_effective_date(raw_content)
            hts_codes = self._find_hts_codes(extracted_text)
            programs = self._find_programs(extracted_text)

            fetch_log = {
                'retrieved_at': fetch_start.isoformat(),
                'response_time_ms': int((datetime.utcnow() - fetch_start).total_seconds() * 1000),
                'status_code': response.status_code,
                'content_type': response.headers.get('Content-Type'),
                'content_length': len(raw_content),
            }

            return ConnectorResult(
                success=True,
                document_id=document_id,
                source=self.SOURCE_TYPE,
                tier=self.TIER,
                connector_name=self.CONNECTOR_NAME,
                canonical_id=canonical_id,
                url=url,
                title=title,
                raw_content=raw_content,
                extracted_text=extracted_text,
                sha256_raw=sha256_raw,
                published_at=datetime.utcnow(),  # Will be refined by subclass
                effective_start=effective_date,
                fetch_log=fetch_log,
                hts_codes_found=hts_codes,
                programs_found=programs,
            )

        except requests.exceptions.RequestException as e:
            return ConnectorResult(
                success=False,
                document_id=document_id,
                source=self.SOURCE_TYPE,
                tier=self.TIER,
                connector_name=self.CONNECTOR_NAME,
                canonical_id=None,
                url=url,
                title=None,
                raw_content="",
                extracted_text="",
                sha256_raw="",
                published_at=None,
                effective_start=None,
                fetch_log={
                    'retrieved_at': fetch_start.isoformat(),
                    'error': str(e),
                },
                error=str(e),
            )
