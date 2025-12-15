"""
Chat module using LangGraph for conversational RAG.

This module provides the main entry point for building chat instances.
It uses LangGraph with SQLite persistence for conversation memory.

Supports two modes:
- ConversationalRAG: Standard retrieve → answer flow
- AgenticRAG: Planning + tool use for complex queries
"""

import os
import sqlite3
from app.chat.models import ChatArgs
from app.chat.graphs.conversational_rag import ConversationalRAG, build_rag_graph
from app.chat.graphs.agentic_rag import AgenticRAG, build_agentic_graph
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# Checkpointer Setup
# ============================================================================

def _get_checkpointer():
    """
    Get the appropriate checkpointer based on environment.

    Uses SQLite for persistence in production, MemorySaver for testing.
    """
    # Check if we should use persistent storage
    use_sqlite = os.getenv("USE_SQLITE_CHECKPOINTER", "true").lower() == "true"

    if use_sqlite:
        # SQLite database path (same directory as main SQLite DB)
        db_path = os.getenv("CHECKPOINTER_DB_PATH", "instance/langgraph_checkpoints.db")

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

        # Create connection and checkpointer
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteSaver(conn)
    else:
        return MemorySaver()


# Global checkpointer instance
_global_checkpointer = None


def get_checkpointer():
    """Get or create the global checkpointer."""
    global _global_checkpointer
    if _global_checkpointer is None:
        _global_checkpointer = _get_checkpointer()
    return _global_checkpointer


# ============================================================================
# Chat Builders
# ============================================================================

def build_chat(chat_args: ChatArgs, output_format: str = "text"):
    """
    Build a chat instance for the conversation.

    This is the main entry point that replaces the old chain-based approach.
    Returns a ConversationalRAG instance that wraps a LangGraph graph.

    Args:
        chat_args: ChatArgs with conversation_id, mode, scope_filter, pdf_id, etc.
        output_format: "text" (default), "structured", or "trade_compliance"

    Returns:
        ConversationalRAG instance with invoke() and stream() methods.

    Usage:
        # Basic text output
        chat = build_chat(chat_args)
        result = chat.invoke("What is X?")
        print(result["answer"])
        print(result["citations"])  # Source citations

        # Structured JSON output
        chat = build_chat(chat_args, output_format="structured")
        result = chat.invoke("What is X?")
        print(result["structured_output"])  # Full JSON with confidence, follow-ups

        # Trade compliance output
        chat = build_chat(chat_args, output_format="trade_compliance")
        result = chat.invoke("What do I need to import chemical X?")
        print(result["structured_output"]["agencies"])
        print(result["structured_output"]["required_documents"])
    """
    return ConversationalRAG(
        conversation_id=chat_args.conversation_id,
        scope_filter=chat_args.scope_filter,
        pdf_id=chat_args.pdf_id,
        mode=chat_args.mode,
        checkpointer=get_checkpointer(),
        output_format=output_format
    )


def build_chat_graph(chat_args: ChatArgs):
    """
    Build the raw LangGraph graph for more control.

    Use this if you need direct access to the graph for custom invocation.

    Args:
        chat_args: ChatArgs with conversation settings

    Returns:
        Compiled LangGraph graph
    """
    return build_rag_graph(
        checkpointer=get_checkpointer(),
        scope_filter=chat_args.scope_filter,
        pdf_id=chat_args.pdf_id,
        mode=chat_args.mode
    )


# ============================================================================
# Convenience Functions
# ============================================================================

def build_trade_compliance_chat(chat_args: ChatArgs):
    """
    Build a chat optimized for trade compliance queries.

    Returns structured output with HTS codes, agencies, documents, etc.
    """
    return build_chat(chat_args, output_format="trade_compliance")


def build_structured_chat(chat_args: ChatArgs):
    """
    Build a chat that returns structured JSON output.

    Returns output with citations, confidence level, and follow-up questions.
    """
    return build_chat(chat_args, output_format="structured")


# ============================================================================
# Agentic Chat Builders
# ============================================================================

def build_agentic_chat(chat_args: ChatArgs, output_format: str = "text"):
    """
    Build an agentic chat instance with planning and tool use.

    This is for complex queries that require:
    - Multi-step reasoning
    - Multiple document lookups
    - Combining information from different sources

    Args:
        chat_args: ChatArgs with conversation_id, mode, scope_filter, etc.
        output_format: "text" (default), "structured", or "trade_compliance"

    Returns:
        AgenticRAG instance with invoke() and stream() methods.

    Usage:
        chat = build_agentic_chat(chat_args)
        result = chat.invoke("I want to import LED lamps from China. What do I need?")
        print(result["answer"])
        print(result["tool_calls"])  # Shows what tools were used
    """
    return AgenticRAG(
        conversation_id=chat_args.conversation_id,
        scope_filter=chat_args.scope_filter,
        checkpointer=get_checkpointer(),
        output_format=output_format
    )


def build_agentic_trade_chat(chat_args: ChatArgs):
    """
    Build an agentic chat optimized for trade compliance queries.

    Uses planning and tool use to gather:
    - HTS codes
    - Tariff rates
    - Agency requirements
    - Required documentation
    """
    return build_agentic_chat(chat_args, output_format="trade_compliance")
