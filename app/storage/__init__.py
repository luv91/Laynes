"""
Storage Abstraction Layer

Provides a unified interface for document blob storage.
Supports local filesystem (default) and S3 (future).

Usage:
    from app.storage import get_storage

    storage = get_storage()
    uri = storage.put("federal_register/2024-12345/doc.xml", raw_bytes, "application/xml")
    content = storage.get(uri)

Environment Variables:
    STORAGE_BACKEND: "local" (default) or "s3"
    STORAGE_PATH: Base path for local storage (default: "storage/documents")

For S3 (future):
    S3_BUCKET: Bucket name
    AWS_ACCESS_KEY_ID: AWS credentials
    AWS_SECRET_ACCESS_KEY: AWS credentials
    AWS_REGION: AWS region
"""

import os
from typing import TYPE_CHECKING

from .base import StorageBackend
from .local import LocalStorage

if TYPE_CHECKING:
    pass

# Singleton instance (lazy initialization)
_storage_instance: StorageBackend = None


def get_storage() -> StorageBackend:
    """
    Get the configured storage backend (singleton).

    Returns:
        StorageBackend instance

    Raises:
        ValueError: If unknown backend configured
    """
    global _storage_instance

    if _storage_instance is not None:
        return _storage_instance

    backend = os.environ.get("STORAGE_BACKEND", "local")

    if backend == "local":
        base_path = os.environ.get("STORAGE_PATH", "storage/documents")
        _storage_instance = LocalStorage(base_path)

    elif backend == "s3":
        # Future: Import and initialize S3Storage
        # from .s3 import S3Storage
        # _storage_instance = S3Storage(
        #     bucket=os.environ["S3_BUCKET"],
        #     aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        #     aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        #     region=os.environ.get("AWS_REGION", "us-east-1"),
        # )
        raise ValueError("S3 backend not yet implemented. Set STORAGE_BACKEND=local")

    else:
        raise ValueError(f"Unknown storage backend: {backend}")

    return _storage_instance


def reset_storage() -> None:
    """Reset the storage singleton (for testing)."""
    global _storage_instance
    _storage_instance = None


__all__ = ["StorageBackend", "LocalStorage", "get_storage", "reset_storage"]
