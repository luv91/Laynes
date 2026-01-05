"""
Document Store Models (v10.0 Phase 2)

Official document corpus for legal-grade tariff verification.
Only Tier-A documents (CSMS, Federal Register, USITC) can be used
to create verified assertions.

Tables:
- Document: Official documents fetched via trusted connectors
- DocumentChunk: Chunked text for RAG retrieval
- EvidenceQuoteV2: Verbatim quotes with document/chunk pointers

Part of the Legal-Grade Tariff Data System:
- Phase 1: Stop caching LLM conclusions (completed)
- Phase 2: Document Store + Chunking (this file)
- Phase 3: Reader LLM + Validator LLM
- Phase 4: Verified Assertions
- Phase 5: Discovery Mode
"""

import hashlib
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, UniqueConstraint, Text
from app.web.db import db
from app.web.db.models.base import BaseModel


class Document(BaseModel):
    """
    Official document store (Tier A only for write path).

    Stores documents fetched via trusted connectors:
    - CSMS bulletins (content.govdelivery.com)
    - Federal Register notices (federalregister.gov)
    - USITC HTS schedule (hts.usitc.gov)

    Key properties:
    - tier: 'A' (official), 'B' (signals), 'C' (discovery hints)
    - connector_name: Which connector fetched this document
    - sha256_raw: Content hash for integrity/change detection
    """
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint('source', 'canonical_id', name='uq_document_source_canonical'),
        db.Index('idx_document_source_tier', 'source', 'tier'),
        db.Index('idx_document_hts_mentions', 'hts_codes_mentioned'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Source identification
    source = db.Column(db.String(20), nullable=False)  # 'CSMS', 'FEDERAL_REGISTER', 'USITC'
    tier = db.Column(db.String(1), nullable=False, default='A')  # 'A', 'B', 'C'
    connector_name = db.Column(db.String(50), nullable=False)  # 'csms_connector', 'govinfo_connector'

    # Document identification
    canonical_id = db.Column(db.String(100), nullable=True, index=True)  # CSMS#65794272, FR citation
    url_canonical = db.Column(db.Text, nullable=False)
    title = db.Column(db.Text, nullable=True)

    # Dates
    published_at = db.Column(db.DateTime, nullable=True)
    effective_start = db.Column(db.Date, nullable=True)  # When regulation takes effect
    effective_end = db.Column(db.Date, nullable=True)  # When superseded

    # Content
    sha256_raw = db.Column(db.String(64), nullable=False)  # Content hash
    raw_content = db.Column(db.Text, nullable=True)  # Raw HTML/text
    extracted_text = db.Column(db.Text, nullable=True)  # Clean text

    # Metadata
    fetch_log = db.Column(JSON, nullable=True)  # {retrieved_at, status_code, headers}
    hts_codes_mentioned = db.Column(JSON, nullable=True)  # List of HTS codes found in doc
    programs_mentioned = db.Column(JSON, nullable=True)  # ['section_232', 'section_301']

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    # Relationships
    chunks = db.relationship('DocumentChunk', backref='document', cascade='all, delete-orphan')

    def compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content.encode()).hexdigest()

    def is_tier_a(self) -> bool:
        """Check if document is Tier A (write-allowed)."""
        return self.tier == 'A'

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "tier": self.tier,
            "connector_name": self.connector_name,
            "canonical_id": self.canonical_id,
            "url_canonical": self.url_canonical,
            "title": self.title,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "sha256_raw": self.sha256_raw,
            "hts_codes_mentioned": self.hts_codes_mentioned,
            "programs_mentioned": self.programs_mentioned,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "chunk_count": len(self.chunks) if self.chunks else 0,
        }


class DocumentChunk(BaseModel):
    """
    Chunked text for RAG retrieval.

    Documents are split into chunks of 400-1200 characters for:
    - Vector embedding and indexing in Pinecone
    - Context windows for Reader LLM
    - Precise quote location tracking

    Key properties:
    - embedding_id: Pinecone vector ID for retrieval
    - char_start/char_end: Exact offsets in extracted_text
    """
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint('document_id', 'chunk_index', name='uq_chunk_doc_index'),
        db.Index('idx_chunk_embedding', 'embedding_id'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Link to document
    document_id = db.Column(db.String(36), db.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)

    # Chunk position
    chunk_index = db.Column(db.Integer, nullable=False)
    char_start = db.Column(db.Integer, nullable=True)  # Start offset in extracted_text
    char_end = db.Column(db.Integer, nullable=True)  # End offset in extracted_text

    # Content
    text = db.Column(db.Text, nullable=False)
    text_hash = db.Column(db.String(64), nullable=True)  # SHA-256 of text

    # Vector embedding
    embedding_id = db.Column(db.String(64), nullable=True)  # Pinecone vector ID

    # Chunk metadata (e.g., page, section, table_row)
    chunk_metadata = db.Column(JSON, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def compute_hash(self) -> str:
        """Compute hash of chunk text."""
        return hashlib.sha256(self.text.encode()).hexdigest()

    def contains_quote(self, quote: str) -> bool:
        """Check if quote is an exact substring of this chunk."""
        return quote in self.text

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "text": self.text[:500] + "..." if len(self.text) > 500 else self.text,
            "text_hash": self.text_hash,
            "embedding_id": self.embedding_id,
            "chunk_metadata": self.chunk_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VerifiedAssertion(BaseModel):
    """
    Truth store for verified facts with proof.

    Only assertions with:
    - Tier-A document source
    - Verbatim evidence quote
    - Validator LLM confirmation
    can be stored here.

    Key properties:
    - effective_start/effective_end: Time-bounded validity
    - document_id: Link to source document
    - evidence_quote: Verbatim text that proves this assertion
    """
    __tablename__ = "verified_assertions"
    __table_args__ = (
        UniqueConstraint(
            'program_id', 'hts_code_norm', 'material', 'assertion_type', 'effective_start',
            name='uq_verified_assertion'
        ),
        db.Index('idx_assertion_hts', 'hts_code_norm', 'program_id'),
        db.Index('idx_assertion_effective', 'effective_start', 'effective_end'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # What is being asserted
    program_id = db.Column(db.String(30), nullable=False)  # 'section_232_copper', 'section_301'
    hts_code_norm = db.Column(db.String(10), nullable=False)  # Digits only: 85444290
    hts_digits = db.Column(db.Integer, nullable=False, default=8)  # 8 or 10
    material = db.Column(db.String(20), nullable=True)  # 'copper', 'steel', 'aluminum'
    assertion_type = db.Column(db.String(30), nullable=False)  # 'IN_SCOPE', 'OUT_OF_SCOPE', 'RATE'

    # The assertion
    claim_code = db.Column(db.String(12), nullable=True)  # '9903.78.01'
    disclaim_code = db.Column(db.String(12), nullable=True)  # '9903.78.02'
    duty_rate = db.Column(db.Numeric(5, 4), nullable=True)  # 0.50 for 50%

    # Time bounds
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)  # NULL = current

    # Evidence (the proof)
    document_id = db.Column(db.String(36), db.ForeignKey('documents.id'), nullable=False)
    chunk_id = db.Column(db.String(36), db.ForeignKey('document_chunks.id'), nullable=True)
    evidence_quote = db.Column(db.Text, nullable=False)  # Verbatim excerpt
    evidence_quote_hash = db.Column(db.String(64), nullable=False)

    # LLM outputs (for audit)
    reader_output = db.Column(JSON, nullable=True)  # Full Reader LLM response
    validator_output = db.Column(JSON, nullable=True)  # Full Validator LLM response

    # Verification metadata
    verified_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    verified_by = db.Column(db.String(50), nullable=False, default='write_gate')  # 'write_gate', 'human'

    # Relationships
    document = db.relationship('Document', backref='assertions')
    chunk = db.relationship('DocumentChunk', backref='assertions')

    def is_current(self, as_of: Optional[date] = None) -> bool:
        """Check if assertion is current (effective_end is NULL or future)."""
        check_date = as_of or date.today()
        if self.effective_end is None:
            return self.effective_start <= check_date
        return self.effective_start <= check_date < self.effective_end

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_id": self.program_id,
            "hts_code_norm": self.hts_code_norm,
            "hts_digits": self.hts_digits,
            "material": self.material,
            "assertion_type": self.assertion_type,
            "claim_code": self.claim_code,
            "disclaim_code": self.disclaim_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "evidence_quote": self.evidence_quote[:200] + "..." if len(self.evidence_quote) > 200 else self.evidence_quote,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verified_by": self.verified_by,
            "is_current": self.is_current(),
        }
