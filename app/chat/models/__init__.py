from typing import Optional, Dict, Any
from pydantic import BaseModel, Extra


class Metadata(BaseModel, extra=Extra.allow):
    conversation_id: str
    user_id: str
    pdf_id: Optional[str] = None  # Now optional for multi_doc mode


class ChatArgs(BaseModel, extra=Extra.allow):
    conversation_id: str
    pdf_id: Optional[str] = None  # Now optional for multi_doc mode
    metadata: Metadata
    streaming: bool

    # New fields for multi-doc support
    mode: str = "user_pdf"  # "user_pdf" | "multi_doc"
    scope_filter: Optional[Dict[str, Any]] = None  # e.g., {"corpus": "gov_trade"}
