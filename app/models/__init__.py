"""
Regulatory Update Pipeline - Document and Evidence Models

These models support the document processing pipeline:
- OfficialDocument: Raw documents from official sources
- DocumentChunk: Chunks for RAG retrieval
- EvidencePacket: Audit-grade proof of extractions
- IngestJob: Processing queue management
- RegulatoryRun: Polling cycle tracking
- TariffAuditLog: Change audit trail
- CandidateChangeRecord: Pending review items

Section 301 Trade Compliance Models (v1.0):
- SourceVersion: Audit backbone for data sources
- TariffMeasure: Temporal tariff rates (SCD Type 2)
- HtsCodeHistory: HTS code validity tracking
- ExclusionClaim: Product exclusions with verification
- Section301IngestionRun: Ingestion pipeline tracking
"""

from app.models.document_store import OfficialDocument, DocumentChunk
from app.models.evidence import EvidencePacket
from app.models.ingest_job import IngestJob
from app.models.regulatory_run import (
    RegulatoryRun,
    RegulatoryRunDocument,
    RegulatoryRunChange,
    TariffAuditLog,
    CandidateChangeRecord,
)
from app.models.section301 import (
    SourceVersion,
    TariffMeasure,
    HtsCodeHistory,
    ExclusionClaim,
    Section301IngestionRun,
    SourceType,
    Publisher,
    RateStatus,
    ConfidenceStatus,
    HtsValidationStatus,
    HtsType,
)

__all__ = [
    # Document Pipeline
    'OfficialDocument',
    'DocumentChunk',
    'EvidencePacket',
    'IngestJob',
    'RegulatoryRun',
    'RegulatoryRunDocument',
    'RegulatoryRunChange',
    'TariffAuditLog',
    'CandidateChangeRecord',
    # Section 301 Models
    'SourceVersion',
    'TariffMeasure',
    'HtsCodeHistory',
    'ExclusionClaim',
    'Section301IngestionRun',
    # Section 301 Enums
    'SourceType',
    'Publisher',
    'RateStatus',
    'ConfidenceStatus',
    'HtsValidationStatus',
    'HtsType',
]
