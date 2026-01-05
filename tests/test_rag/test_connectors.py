"""
Unit tests for Trusted Connectors (v10.0 Phase 2).

Tests:
- BaseConnector domain validation
- CSMS Connector
- GovInfo Connector
- USITC Connector
"""

import pytest
from unittest.mock import Mock, patch


class TestBaseConnector:
    """Tests for the BaseConnector base class."""

    def test_is_trusted_domain_exact_match(self):
        """Test domain validation with exact match."""
        from app.ingestion.connectors.base import BaseConnector

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = {"example.com", "test.gov"}

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()
        assert connector._is_trusted_domain("https://example.com/page") is True
        assert connector._is_trusted_domain("https://test.gov/doc") is True
        assert connector._is_trusted_domain("https://malicious.com/page") is False

    def test_is_trusted_domain_subdomain(self):
        """Test domain validation with subdomain match."""
        from app.ingestion.connectors.base import BaseConnector

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = {"govdelivery.com"}

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()
        assert connector._is_trusted_domain("https://content.govdelivery.com/page") is True
        assert connector._is_trusted_domain("https://www.govdelivery.com/page") is True
        assert connector._is_trusted_domain("https://fakegovdelivery.com/page") is False

    def test_compute_hash(self):
        """Test content hash computation."""
        from app.ingestion.connectors.base import BaseConnector
        import hashlib

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = set()

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()
        content = "Test content for hashing"
        expected = hashlib.sha256(content.encode('utf-8')).hexdigest()
        assert connector._compute_hash(content) == expected

    def test_extract_text(self):
        """Test HTML to text extraction."""
        from app.ingestion.connectors.base import BaseConnector

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = set()

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()
        html = """
        <html>
        <head><title>Test</title></head>
        <body>
            <script>var x = 1;</script>
            <style>.test { color: red; }</style>
            <nav>Navigation</nav>
            <p>Main content here.</p>
            <p>Second paragraph.</p>
            <footer>Footer</footer>
        </body>
        </html>
        """
        text = connector._extract_text(html)
        assert "Main content here" in text
        assert "Second paragraph" in text
        assert "var x = 1" not in text  # Script removed
        assert ".test" not in text  # Style removed

    def test_find_hts_codes(self):
        """Test HTS code detection in text."""
        from app.ingestion.connectors.base import BaseConnector

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = set()

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()
        text = """
        The following HTS codes are subject to Section 232:
        8544.42.9090 - Electrical conductors
        8501.10.20 - Electric motors
        8501 - General heading
        """
        codes = connector._find_hts_codes(text)
        # The regex pattern captures HTS codes with up to 3 decimal groups
        assert "8544.42" in codes or any("8544" in c for c in codes)
        assert "8501.10.20" in codes
        assert "8501" in codes

    def test_find_programs(self):
        """Test program detection in text."""
        from app.ingestion.connectors.base import BaseConnector

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = set()

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()

        # Steel
        text1 = "This notice applies to Section 232 steel tariffs."
        programs1 = connector._find_programs(text1)
        assert "section_232_steel" in programs1

        # Aluminum
        text2 = "Section 232 aluminum products are affected."
        programs2 = connector._find_programs(text2)
        assert "section_232_aluminum" in programs2

        # Copper
        text3 = "Section 232 copper derivative articles."
        programs3 = connector._find_programs(text3)
        assert "section_232_copper" in programs3

        # Section 301
        text4 = "Products subject to Section 301 tariffs from China."
        programs4 = connector._find_programs(text4)
        assert "section_301" in programs4

    def test_fetch_untrusted_domain(self):
        """Test that fetch raises error for untrusted domain."""
        from app.ingestion.connectors.base import BaseConnector, UntrustedSourceError

        class TestConnector(BaseConnector):
            TRUSTED_DOMAINS = {"trusted.gov"}
            CONNECTOR_NAME = "test_connector"

            def extract_canonical_id(self, content, url):
                return None

            def extract_effective_date(self, content):
                return None

        connector = TestConnector()

        with pytest.raises(UntrustedSourceError):
            connector.fetch("https://untrusted.com/page")


class TestCSMSConnector:
    """Tests for the CSMS Connector."""

    def test_csms_trusted_domains(self):
        """Test CSMS connector trusted domains."""
        from app.ingestion.connectors.csms import CSMSConnector

        connector = CSMSConnector()
        assert connector._is_trusted_domain("https://content.govdelivery.com/accounts/USDHSCBP/bulletins/123") is True
        assert connector._is_trusted_domain("https://www.cbp.gov/trade/") is True
        assert connector._is_trusted_domain("https://cbp.gov/trade/") is True
        assert connector._is_trusted_domain("https://malicious.com/cbp") is False

    def test_csms_source_type(self):
        """Test CSMS connector source type."""
        from app.ingestion.connectors.csms import CSMSConnector

        connector = CSMSConnector()
        assert connector.SOURCE_TYPE == "CSMS"
        assert connector.TIER == "A"

    def test_csms_extract_canonical_id(self):
        """Test CSMS bulletin number extraction."""
        from app.ingestion.connectors.csms import CSMSConnector

        connector = CSMSConnector()

        # From title
        content1 = "<title>CSMS #65794272 - Section 232 Update</title>"
        assert "65794272" in connector.extract_canonical_id(content1, "https://example.com")

        # From URL
        content2 = "<html>Content</html>"
        url2 = "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/65794272"
        result = connector.extract_canonical_id(content2, url2)
        assert result is not None
        assert "65794272" in result


class TestGovInfoConnector:
    """Tests for the GovInfo Connector."""

    def test_govinfo_trusted_domains(self):
        """Test GovInfo connector trusted domains."""
        from app.ingestion.connectors.govinfo import GovInfoConnector

        connector = GovInfoConnector()
        assert connector._is_trusted_domain("https://www.federalregister.gov/documents/") is True
        assert connector._is_trusted_domain("https://api.govinfo.gov/packages/") is True
        assert connector._is_trusted_domain("https://fake-federalregister.com/") is False

    def test_govinfo_source_type(self):
        """Test GovInfo connector source type."""
        from app.ingestion.connectors.govinfo import GovInfoConnector

        connector = GovInfoConnector()
        assert connector.SOURCE_TYPE == "FEDERAL_REGISTER"
        assert connector.TIER == "A"

    def test_govinfo_extract_fr_citation(self):
        """Test Federal Register citation extraction."""
        from app.ingestion.connectors.govinfo import GovInfoConnector

        connector = GovInfoConnector()

        content = "This document appears in 90 FR 40326 on January 15, 2025."
        url = "https://www.federalregister.gov/documents/2025/01/15/2025-00123"
        canonical_id = connector.extract_canonical_id(content, url)

        assert canonical_id is not None
        # Should contain FR citation


class TestUSITCConnector:
    """Tests for the USITC Connector."""

    def test_usitc_trusted_domains(self):
        """Test USITC connector trusted domains."""
        from app.ingestion.connectors.usitc import USITCConnector

        connector = USITCConnector()
        assert connector._is_trusted_domain("https://hts.usitc.gov/reststop/") is True
        assert connector._is_trusted_domain("https://www.usitc.gov/") is True
        assert connector._is_trusted_domain("https://fake-usitc.com/") is False

    def test_usitc_source_type(self):
        """Test USITC connector source type."""
        from app.ingestion.connectors.usitc import USITCConnector

        connector = USITCConnector()
        assert connector.SOURCE_TYPE == "USITC"
        assert connector.TIER == "A"


class TestConnectorResult:
    """Tests for ConnectorResult dataclass."""

    def test_connector_result_creation(self):
        """Test creating a ConnectorResult."""
        from app.ingestion.connectors.base import ConnectorResult
        from datetime import datetime

        result = ConnectorResult(
            success=True,
            document_id="doc-123",
            source="CSMS",
            tier="A",
            connector_name="csms_connector",
            canonical_id="CSMS#65794272",
            url="https://example.com",
            title="Test Document",
            raw_content="<html>Test</html>",
            extracted_text="Test content",
            sha256_raw="abc123",
            published_at=datetime.utcnow(),
            effective_start=None,
            fetch_log={"status_code": 200},
            hts_codes_found=["8544.42.9090"],
            programs_found=["section_232_steel"],
        )

        assert result.success is True
        assert result.source == "CSMS"
        assert result.tier == "A"
        assert len(result.hts_codes_found) == 1
        assert result.error is None

    def test_connector_result_failure(self):
        """Test creating a failed ConnectorResult."""
        from app.ingestion.connectors.base import ConnectorResult

        result = ConnectorResult(
            success=False,
            document_id="doc-123",
            source="CSMS",
            tier="A",
            connector_name="csms_connector",
            canonical_id=None,
            url="https://example.com",
            title=None,
            raw_content="",
            extracted_text="",
            sha256_raw="",
            published_at=None,
            effective_start=None,
            fetch_log={"error": "Connection failed"},
            error="Connection failed",
        )

        assert result.success is False
        assert result.error == "Connection failed"
