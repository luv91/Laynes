from .chat import (
    build_chat,
    build_chat_graph,
    build_agentic_chat,
    build_agentic_trade_chat,
    build_trade_compliance_chat,
    build_structured_chat,
)
from .models import ChatArgs
from .graphs import ConversationalRAG, build_rag_graph, AgenticRAG, build_agentic_graph
from .create_embeddings import create_embeddings_for_pdf
from .score import score_conversation, get_scores

# Output schemas
from .output_schemas import (
    SourceCitation,
    StructuredAnswer,
    TradeComplianceOutput,
    RequiredDocument,
    TariffInfo,
    PlanStep,
    AgentPlan,
    CURRENT_SCHEMA_VERSION,
    validate_schema_version,
)

# Prompts
from .prompts import (
    CONDENSE_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    STRUCTURED_ANSWER_PROMPT,
    TRADE_COMPLIANCE_PROMPT,
    PLANNER_PROMPT,
    REFLECTION_PROMPT,
    PLANNING_PROMPT,
)

# Tools
from .tools import (
    search_documents,
    lookup_hts_code,
    check_tariffs,
    check_agency_requirements,
    TRADE_TOOLS,
)

__all__ = [
    # Standard RAG
    "build_chat",
    "build_chat_graph",
    "ChatArgs",
    "ConversationalRAG",
    "build_rag_graph",
    # Agentic RAG
    "build_agentic_chat",
    "build_agentic_trade_chat",
    "AgenticRAG",
    "build_agentic_graph",
    # Convenience builders
    "build_trade_compliance_chat",
    "build_structured_chat",
    # Document processing
    "create_embeddings_for_pdf",
    # Scoring
    "score_conversation",
    "get_scores",
    # Output schemas
    "SourceCitation",
    "StructuredAnswer",
    "TradeComplianceOutput",
    "RequiredDocument",
    "TariffInfo",
    "PlanStep",
    "AgentPlan",
    "CURRENT_SCHEMA_VERSION",
    "validate_schema_version",
    # Prompts
    "CONDENSE_SYSTEM_PROMPT",
    "ANSWER_SYSTEM_PROMPT",
    "STRUCTURED_ANSWER_PROMPT",
    "TRADE_COMPLIANCE_PROMPT",
    "PLANNER_PROMPT",
    "REFLECTION_PROMPT",
    "PLANNING_PROMPT",
    # Tools
    "search_documents",
    "lookup_hts_code",
    "check_tariffs",
    "check_agency_requirements",
    "TRADE_TOOLS",
]
