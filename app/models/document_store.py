"""
Document Store Models

Stores raw official documents with full audit trail:
- OfficialDocument: The raw document with content hash
- DocumentChunk: Chunks for RAG retrieval with embeddings
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from app.web.db import db
from app.web.db.models.base import BaseModel


class OfficialDocument(BaseModel):
    """
    Stores raw official documents with audit trail.

    Each document is stored with:
    - Raw bytes (original file)
    - Content hash (SHA256 for change detection)
    - Canonical text (line-numbered for evidence citations)
    - Metadata from source
    """
    __tablename__ = "official_documents"
    __table_args__ = (
        db.UniqueConstraint('source', 'external_id', 'content_hash', name='uq_official_doc'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Source identification
    source = db.Column(db.String(50), nullable=False, index=True)  # federal_register, cbp_csms, usitc
    external_id = db.Column(db.String(100), nullable=False, index=True)  # document_number, bulletin_id

    # URLs
    pdf_url = db.Column(db.String(500))
    xml_url = db.Column(db.String(500))
    html_url = db.Column(db.String(500))

    # Raw content
    raw_bytes = db.Column(db.LargeBinary)  # Original file bytes
    content_hash = db.Column(db.String(64), nullable=False, index=True)  # SHA256
    content_type = db.Column(db.String(50))  # application/pdf, text/xml, etc.
    content_size = db.Column(db.Integer)  # Size in bytes

    # Rendered content
    canonical_text = db.Column(db.Text)  # Line-numbered plain text for evidence

    # Metadata
    title = db.Column(db.String(500))
    publication_date = db.Column(db.Date)
    effective_date = db.Column(db.Date)
    metadata_json = db.Column(db.JSON)  # Source-specific metadata

    # Processing status
    status = db.Column(db.String(50), default="fetched", index=True)
    # fetched → rendered → chunked → extracted → validated → committed

    # Relationships
    parent_document_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"))

    # Timestamps
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    rendered_at = db.Column(db.DateTime)
    processed_at = db.Column(db.DateTime)

    # Relationship to chunks
    chunks = db.relationship("DocumentChunk", backref="document", lazy="dynamic",
                            cascade="all, delete-orphan")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "pdf_url": self.pdf_url,
            "xml_url": self.xml_url,
            "html_url": self.html_url,
            "content_hash": self.content_hash,
            "content_type": self.content_type,
            "content_size": self.content_size,
            "title": self.title,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "status": self.status,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "chunk_count": self.chunks.count() if self.chunks else 0,
        }


class DocumentChunk(BaseModel):
    """
    Chunks of documents for RAG retrieval.

    Each chunk represents a semantically coherent portion of a document
    that can be retrieved for context during extraction/validation.
    """
    __tablename__ = "document_chunks"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id = db.Column(db.String(36), db.ForeignKey("official_documents.id", ondelete="CASCADE"),
                           nullable=False, index=True)

    # Position in document
    chunk_index = db.Column(db.Integer, nullable=False)
    page_start = db.Column(db.Integer)
    page_end = db.Column(db.Integer)
    line_start = db.Column(db.Integer)
    line_end = db.Column(db.Integer)

    # Content
    text = db.Column(db.Text, nullable=False)
    token_count = db.Column(db.Integer)

    # Chunk classification
    chunk_type = db.Column(db.String(50))  # narrative, table, annex, heading
    section_heading = db.Column(db.String(200))

    # Embedding (stored as array or reference to vector DB)
    embedding_model = db.Column(db.String(50))  # text-embedding-3-small, etc.
    embedding_id = db.Column(db.String(100))  # ID in Pinecone/vector DB

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "text": self.text[:500] + "..." if len(self.text) > 500 else self.text,
            "token_count": self.token_count,
            "chunk_type": self.chunk_type,
            "section_heading": self.section_heading,
        }

    def get_line_range(self) -> str:
        """Return line range for evidence citation."""
        if self.line_start and self.line_end:
            return f"L{self.line_start:04d}-L{self.line_end:04d}"
        return ""
