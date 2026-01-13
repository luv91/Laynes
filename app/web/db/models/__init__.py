from .user import User
from .pdf import Pdf
from .conversation import Conversation
from .message import Message
from .corpus import Corpus
from .base import BaseModel as Model
from .tariff_tables import (
    TariffProgram,
    Section301Inclusion,
    Section301Exclusion,
    Section232Material,
    ProgramCode,
    DutyRule,
    ProductHistory,
    Section301Rate,
    Section232Rate,
    IeepaRate,
)

# Import pipeline models to register them with SQLAlchemy
from app.models import (
    OfficialDocument,
    DocumentChunk,
    EvidencePacket,
    IngestJob,
    RegulatoryRun,
    RegulatoryRunDocument,
    RegulatoryRunChange,
    TariffAuditLog,
    CandidateChangeRecord,
)
