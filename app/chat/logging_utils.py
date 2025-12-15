"""
Logging utilities for LangGraph RAG system.

Provides structured JSON logging for:
- Graph node execution
- Tool calls
- Retrieval operations
- Performance metrics

Usage:
    from app.chat.logging_utils import log_graph_event, GraphLogger

    # Simple logging
    log_graph_event("retrieve", {
        "run_id": "...",
        "query": "...",
        "num_docs": 5
    })

    # Context manager for timing
    with GraphLogger(run_id, conversation_id) as logger:
        logger.log_node("condense", {"original": q, "condensed": cq})
        logger.log_retrieve(query, docs)
        logger.log_generate(answer)
"""

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from functools import wraps


# Configure logger
logger = logging.getLogger("graph_runs")
logger.setLevel(logging.INFO)

# JSON formatter for structured logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        if isinstance(record.msg, dict):
            return json.dumps(record.msg)
        return super().format(record)


# Add handler if not already present
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)


# ============================================================================
# Simple Logging Functions
# ============================================================================

def log_graph_event(event_type: str, payload: Dict[str, Any]) -> None:
    """
    Log a graph event with structured data.

    Args:
        event_type: Type of event (e.g., "condense", "retrieve", "generate", "tool_call")
        payload: Event data including run_id, conversation_id, etc.
    """
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        **payload
    }
    logger.info(event)


def log_node_execution(
    node_name: str,
    run_id: str,
    conversation_id: str,
    inputs: Optional[Dict] = None,
    outputs: Optional[Dict] = None,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None
) -> None:
    """Log a graph node execution."""
    log_graph_event("node_execution", {
        "node": node_name,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "inputs": _truncate_dict(inputs) if inputs else None,
        "outputs": _truncate_dict(outputs) if outputs else None,
        "duration_ms": duration_ms,
        "error": error
    })


def log_tool_call(
    tool_name: str,
    run_id: str,
    conversation_id: str,
    inputs: Dict,
    output: Any,
    duration_ms: float
) -> None:
    """Log a tool invocation."""
    log_graph_event("tool_call", {
        "tool": tool_name,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "inputs": inputs,
        "output_preview": str(output)[:200] if output else None,
        "duration_ms": duration_ms
    })


def log_retrieval(
    run_id: str,
    conversation_id: str,
    query: str,
    num_docs: int,
    doc_ids: List[str],
    duration_ms: float
) -> None:
    """Log a retrieval operation."""
    log_graph_event("retrieval", {
        "run_id": run_id,
        "conversation_id": conversation_id,
        "query": query[:200],
        "num_docs": num_docs,
        "doc_ids": doc_ids[:10],  # Limit to first 10
        "duration_ms": duration_ms
    })


# ============================================================================
# GraphLogger Class
# ============================================================================

class GraphLogger:
    """
    Context manager for logging graph runs.

    Usage:
        with GraphLogger(run_id, conversation_id) as logger:
            logger.log_node("condense", {"question": q})
            # ... do work ...
            logger.log_node("generate", {"answer": a})
    """

    def __init__(self, run_id: str = None, conversation_id: str = None, user_id: str = None):
        self.run_id = run_id or str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.start_time = None
        self.events: List[Dict] = []

    def __enter__(self):
        self.start_time = time.time()
        log_graph_event("run_start", {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id
        })
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        log_graph_event("run_end", {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "duration_ms": round(duration_ms, 2),
            "error": str(exc_val) if exc_val else None,
            "num_events": len(self.events)
        })

    def log_node(self, node_name: str, data: Dict = None) -> None:
        """Log a node execution."""
        event = {
            "node": node_name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": _truncate_dict(data) if data else None
        }
        self.events.append(event)
        log_node_execution(
            node_name=node_name,
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            inputs=data
        )

    def log_condense(self, original: str, condensed: str) -> None:
        """Log question condensing."""
        self.log_node("condense", {
            "original_question": original[:200],
            "condensed_question": condensed[:200],
            "was_modified": original != condensed
        })

    def log_retrieve(self, query: str, docs: List, duration_ms: float = None) -> None:
        """Log retrieval operation."""
        doc_ids = [d.metadata.get("pdf_id", "unknown") for d in docs] if docs else []
        self.log_node("retrieve", {
            "query": query[:200],
            "num_docs": len(docs) if docs else 0,
            "doc_ids": doc_ids[:10],
            "duration_ms": duration_ms
        })

    def log_generate(self, answer: str, citations: List = None) -> None:
        """Log answer generation."""
        self.log_node("generate", {
            "answer_length": len(answer) if answer else 0,
            "num_citations": len(citations) if citations else 0
        })

    def log_tool(self, tool_name: str, inputs: Dict, output: Any, duration_ms: float) -> None:
        """Log a tool call."""
        event = {
            "tool": tool_name,
            "inputs": inputs,
            "duration_ms": duration_ms
        }
        self.events.append(event)
        log_tool_call(
            tool_name=tool_name,
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            inputs=inputs,
            output=output,
            duration_ms=duration_ms
        )


# ============================================================================
# Decorator for Node Timing
# ============================================================================

def timed_node(node_name: str):
    """
    Decorator to time and log node execution.

    Usage:
        @timed_node("retrieve")
        def retrieve_documents_node(state, config):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(state, config=None, *args, **kwargs):
            start = time.time()
            error = None

            # Extract run info from config
            run_meta = (config or {}).get("configurable", {})
            run_id = run_meta.get("run_id", "unknown")
            conversation_id = run_meta.get("conversation_id", "unknown")

            try:
                result = func(state, config, *args, **kwargs)
                return result
            except Exception as e:
                error = str(e)
                raise
            finally:
                duration_ms = (time.time() - start) * 1000
                log_node_execution(
                    node_name=node_name,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    duration_ms=round(duration_ms, 2),
                    error=error
                )

        return wrapper
    return decorator


# ============================================================================
# Helper Functions
# ============================================================================

def _truncate_dict(d: Dict, max_str_len: int = 200) -> Dict:
    """Truncate string values in dict for logging."""
    if not d:
        return d

    result = {}
    for key, value in d.items():
        if isinstance(value, str) and len(value) > max_str_len:
            result[key] = value[:max_str_len] + "..."
        elif isinstance(value, list) and len(value) > 10:
            result[key] = value[:10]
        elif isinstance(value, dict):
            result[key] = _truncate_dict(value, max_str_len)
        else:
            result[key] = value
    return result


def generate_run_id() -> str:
    """Generate a new run ID."""
    return str(uuid.uuid4())


def get_run_config(run_id: str, conversation_id: str, user_id: str = None) -> Dict:
    """
    Create a config dict for LangGraph invocation.

    Usage:
        config = get_run_config(run_id, conversation_id)
        result = graph.invoke(input, config=config)
    """
    return {
        "configurable": {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "thread_id": conversation_id  # For checkpointer
        }
    }
