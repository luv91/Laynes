"""
Corpus model for managing document collections.

A corpus is a versioned collection of documents used for multi-doc retrieval.
Examples: "trade_compliance_v1", "legal_docs_v2"
"""

import uuid
from app.web.db import db
from .base import BaseModel


class Corpus(BaseModel):
    """
    Represents a collection of documents for multi-doc retrieval.

    Attributes:
        id: Primary key
        name: Unique identifier for the corpus (e.g., "trade_compliance_v1")
        description: Human-readable description
        is_active: Whether this corpus is currently active for new conversations
        version: Version string for tracking updates
        created_at: When the corpus was created
    """
    __tablename__ = "corpus"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    version = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def as_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    @classmethod
    def get_active(cls):
        """Get all active corpora."""
        return cls.query.filter_by(is_active=True).all()

    @classmethod
    def get_by_name(cls, name: str):
        """Get corpus by name."""
        return cls.query.filter_by(name=name).first()

    def __repr__(self):
        return f"<Corpus {self.name} v{self.version}>"
