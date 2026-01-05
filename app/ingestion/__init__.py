"""
Document Ingestion Module (v10.0 Phase 2)

Provides trusted connectors for fetching official government documents.
Only Tier-A connectors can produce documents that feed into verified assertions.

Connectors:
- CSMSConnector: CBP CSMS bulletins
- GovInfoConnector: Federal Register notices
- USITCConnector: HTS schedule data

Usage:
    from app.ingestion import CSMSConnector, ingest_document

    connector = CSMSConnector()
    doc = connector.fetch("https://content.govdelivery.com/...")
    ingest_document(doc, session)
"""

from app.ingestion.connectors.base import BaseConnector, ConnectorResult
from app.ingestion.connectors.csms import CSMSConnector
from app.ingestion.connectors.govinfo import GovInfoConnector
from app.ingestion.connectors.usitc import USITCConnector
from app.ingestion.chunker import DocumentChunker, chunk_document

__all__ = [
    'BaseConnector',
    'ConnectorResult',
    'CSMSConnector',
    'GovInfoConnector',
    'USITCConnector',
    'DocumentChunker',
    'chunk_document',
]
