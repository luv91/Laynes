"""
Local Filesystem Storage Backend

Stores document blobs on local filesystem with S3-compatible interface.
"""

import os
from pathlib import Path
from typing import Optional

from .base import StorageBackend


class LocalStorage(StorageBackend):
    """
    Local filesystem storage (S3-compatible interface).

    Documents are stored in a directory structure:
        storage/documents/
            federal_register/
                2024-12345/
                    abc123def456.xml
            cbp_csms/
                67400472/
                    notice.html
    """

    SCHEME = "local"

    def __init__(self, base_path: str = "storage/documents"):
        """
        Initialize local storage.

        Args:
            base_path: Base directory for storing documents.
                       Relative paths are resolved from the app root.
        """
        # Resolve relative paths from app root (lanes/)
        if not os.path.isabs(base_path):
            app_root = Path(__file__).parent.parent.parent  # app/storage/local.py -> lanes/
            base_path = app_root / base_path

        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, content_type: str) -> str:
        """
        Store bytes to local filesystem.

        Args:
            key: Storage key (e.g., "federal_register/2024-12345/abc123.xml")
            data: Raw bytes to store
            content_type: MIME type (stored in metadata, not used for local)

        Returns:
            URI string (e.g., "local://federal_register/2024-12345/abc123.xml")
        """
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{self.SCHEME}://{key}"

    def get(self, uri: str) -> bytes:
        """
        Retrieve bytes from local filesystem.

        Args:
            uri: Full URI (e.g., "local://federal_register/2024-12345/abc123.xml")

        Returns:
            Raw bytes

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        key = self.get_key_from_uri(uri)
        path = self.base_path / key

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {uri}")

        return path.read_bytes()

    def delete(self, uri: str) -> bool:
        """
        Delete file from local filesystem.

        Args:
            uri: Full URI

        Returns:
            True if deleted, False if didn't exist
        """
        key = self.get_key_from_uri(uri)
        path = self.base_path / key

        if path.exists():
            path.unlink()
            # Clean up empty parent directories
            self._cleanup_empty_dirs(path.parent)
            return True
        return False

    def exists(self, uri: str) -> bool:
        """
        Check if file exists on local filesystem.

        Args:
            uri: Full URI

        Returns:
            True if exists
        """
        key = self.get_key_from_uri(uri)
        return (self.base_path / key).exists()

    def _cleanup_empty_dirs(self, path: Path) -> None:
        """Remove empty parent directories up to base_path."""
        try:
            while path != self.base_path and path.exists():
                if any(path.iterdir()):
                    break  # Directory not empty
                path.rmdir()
                path = path.parent
        except (OSError, PermissionError):
            pass  # Ignore cleanup errors

    def get_local_path(self, uri: str) -> Path:
        """
        Get the actual filesystem path for a URI.

        Useful for debugging or direct file access.

        Args:
            uri: Full URI

        Returns:
            Path object
        """
        key = self.get_key_from_uri(uri)
        return self.base_path / key
