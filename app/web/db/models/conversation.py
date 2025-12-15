import uuid
import json
from app.web.db import db
from .base import BaseModel


class Conversation(BaseModel):
    id: str = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_on = db.Column(db.DateTime, server_default=db.func.now())

    retriever: str = db.Column(db.String)
    memory: str = db.Column(db.String)
    llm: str = db.Column(db.String)

    # New fields for multi-doc support
    mode: str = db.Column(db.String, default="user_pdf")  # "user_pdf" | "multi_doc"
    scope_filter: str = db.Column(db.Text, nullable=True)  # JSON string for filter
    corpus_name: str = db.Column(db.String(80), nullable=True)  # Track which corpus was used

    # pdf_id is now nullable for multi_doc mode
    pdf_id: str = db.Column(db.String(), db.ForeignKey("pdf.id"), nullable=True)
    pdf = db.relationship("Pdf", back_populates="conversations")

    user_id: str = db.Column(db.String(), db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", back_populates="conversations")

    messages = db.relationship(
        "Message", back_populates="conversation", order_by="Message.created_on"
    )

    def get_scope_filter(self):
        """Parse scope_filter JSON string to dict"""
        if self.scope_filter:
            return json.loads(self.scope_filter)
        return None

    def set_scope_filter(self, filter_dict):
        """Set scope_filter from dict"""
        if filter_dict:
            self.scope_filter = json.dumps(filter_dict)
        else:
            self.scope_filter = None

    def as_dict(self):
        return {
            "id": self.id,
            "pdf_id": self.pdf_id,
            "mode": self.mode,
            "scope_filter": self.get_scope_filter(),
            "corpus_name": self.corpus_name,
            "messages": [m.as_dict() for m in self.messages],
        }
