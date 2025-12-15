import uuid
from app.web.db import db
from .base import BaseModel


class Pdf(BaseModel):
    id: str = db.Column(
        db.String(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: str = db.Column(db.String(80), nullable=False)

    # New fields for multi-doc support
    is_system: bool = db.Column(db.Boolean, default=False)  # True for pre-loaded docs
    corpus: str = db.Column(db.String(80), nullable=True)   # e.g., "gov_trade"
    doc_type: str = db.Column(db.String(80), nullable=True) # e.g., "hts_schedule"

    # user_id is now nullable for system documents
    user_id: str = db.Column(db.String(), db.ForeignKey("user.id"), nullable=True)
    user = db.relationship("User", back_populates="pdfs")

    conversations = db.relationship(
        "Conversation",
        back_populates="pdf",
        order_by="desc(Conversation.created_on)",
    )

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "is_system": self.is_system,
            "corpus": self.corpus,
            "doc_type": self.doc_type,
        }
