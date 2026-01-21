"""
Abstract Storage Backend

Defines the interface for object storage backends (local filesystem, S3, etc.)
"""

from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):
    """Abstract base class for object storage backends."""

    SCHEME: str = ""  # URI scheme (local, s3, etc.)

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> str:
        """
        Store bytes and return URI.

        Args:
            key: Storage key (e.g., "federal_register/2024-12345/abc123.xml")
            data: Raw bytes to store
            content_type: MIME type (e.g., "application/xml")

        Returns:
            URI string (e.g., "local://federal_register/2024-12345/abc123.xml")
        """
        pass

    @abstractmethod
    def get(self, uri: str) -> bytes:
        """
        Retrieve bytes by URI.

        Args:
            uri: Full URI (e.g., "local://federal_register/2024-12345/abc123.xml")

        Returns:
            Raw bytes

        Raises:
            FileNotFoundError: If object doesn't exist
        """
        pass

    @abstractmethod
    def delete(self, uri: str) -> bool:
        """
        Delete object by URI.

        Args:
            uri: Full URI

        Returns:
            True if deleted, False if didn't exist
        """
        pass

    @abstractmethod
    def exists(self, uri: str) -> bool:
        """
        Check if object exists.

        Args:
            uri: Full URI

        Returns:
            True if exists
        """
        pass

    def get_key_from_uri(self, uri: str) -> str:
        """Extract storage key from URI."""
        prefix = f"{self.SCHEME}://"
        if uri.startswith(prefix):
            return uri[len(prefix):]
        return uri
