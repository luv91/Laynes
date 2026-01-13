"""
Evidence Packet Model

Stores audit-grade proof that database changes are supported by official text.
Each evidence packet links:
- A specific database change (HTS code, rate, effective date)
- To a specific quote in an official document
- With verification that the quote exists verbatim
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Dict, Any
from uuid import uuid4

from app.web.db import db
from app.web.db.models.base import BaseModel


class EvidencePacket(BaseModel):
    """
    Stores proof that a DB change is supported by official text.

    This is the audit trail that answers:
    - "Where did this rate come from?"
    - "What document proves this HTS is covered?"
    - "Can we verify this claim?"

    Verification levels:
    - quote_verified=False: LLM extracted this quote (not yet verified)
    - quote_verified=True: Quote confirmed to exist verbatim in source
    - human_verified=True: Human reviewed and approved
    """
    __tablename__ = "evidence_packets"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Source document reference
    document_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"),
                           nullable=False, index=True)
    document_hash = db.Column(db.String(64), nullable=False)  # SHA256 at extraction time
    chunk_id = db.Column(db.String(36), db.ForeignKey("document_chunks.id"))

    # Location in document
    page_number = db.Column(db.Integer)
    line_start = db.Column(db.Integer)
    line_end = db.Column(db.Integer)

    # Evidence content
    quote_text = db.Column(db.Text, nullable=False)  # Exact verbatim quote
    quote_hash = db.Column(db.String(64))  # SHA256 of quote for deduplication
    context_before = db.Column(db.Text)  # Lines before quote
    context_after = db.Column(db.Text)  # Lines after quote

    # What the quote proves
    proves_hts_code = db.Column(db.String(12), index=True)
    proves_chapter_99 = db.Column(db.String(12))
    proves_rate = db.Column(db.Numeric(5, 4))  # As decimal (0.50 = 50%)
    proves_effective_date = db.Column(db.Date)
    proves_program = db.Column(db.String(50))  # section_301, section_232_steel, etc.

    # Verification status
    quote_verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.String(50))  # 'write_gate', 'validator_llm', 'human:email'
    verified_at = db.Column(db.DateTime)
    verification_method = db.Column(db.String(50))  # 'substring', 'fuzzy', 'manual'
    confidence_score = db.Column(db.Float)  # 0.0 to 1.0

    # Human review
    human_verified = db.Column(db.Boolean, default=False)
    human_reviewer = db.Column(db.String(100))
    human_notes = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    document = db.relationship("OfficialDocument", backref="evidence_packets")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "document_hash": self.document_hash,
            "page_number": self.page_number,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "quote_text": self.quote_text[:200] + "..." if len(self.quote_text) > 200 else self.quote_text,
            "proves_hts_code": self.proves_hts_code,
            "proves_chapter_99": self.proves_chapter_99,
            "proves_rate": float(self.proves_rate) if self.proves_rate else None,
            "proves_effective_date": self.proves_effective_date.isoformat() if self.proves_effective_date else None,
            "proves_program": self.proves_program,
            "quote_verified": self.quote_verified,
            "verified_by": self.verified_by,
            "confidence_score": self.confidence_score,
            "human_verified": self.human_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def get_citation(self) -> str:
        """
        Return a formatted citation for this evidence.

        Example: "FR 2024-21217, Lines L2847-L2852"
        """
        parts = []

        if self.document:
            parts.append(f"{self.document.source.upper()} {self.document.external_id}")

        if self.line_start and self.line_end:
            parts.append(f"Lines L{self.line_start:04d}-L{self.line_end:04d}")
        elif self.page_number:
            parts.append(f"Page {self.page_number}")

        return ", ".join(parts)

    @classmethod
    def create_from_extraction(cls, document, extraction: dict) -> "EvidencePacket":
        """
        Create an evidence packet from an extraction result.

        Args:
            document: OfficialDocument instance
            extraction: Dict with hts_code, rate, chapter_99, quote, lines, etc.

        Returns:
            EvidencePacket instance (not yet committed)
        """
        import hashlib

        quote = extraction.get("evidence_quote", "")
        quote_hash = hashlib.sha256(quote.encode()).hexdigest() if quote else None

        return cls(
            document_id=document.id,
            document_hash=document.content_hash,
            line_start=extraction.get("line_start"),
            line_end=extraction.get("line_end"),
            quote_text=quote,
            quote_hash=quote_hash,
            proves_hts_code=extraction.get("hts_code"),
            proves_chapter_99=extraction.get("chapter_99_code"),
            proves_rate=Decimal(str(extraction.get("rate", 0))) if extraction.get("rate") else None,
            proves_effective_date=extraction.get("effective_date"),
            proves_program=extraction.get("program"),
            quote_verified=False,  # Will be verified by write gate
        )
