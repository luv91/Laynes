"""
Prompts for RAG and agentic workflows.

Exports all prompt templates for easy importing.
"""

from .trade_compliance import (
    CONDENSE_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    STRUCTURED_ANSWER_PROMPT,
    TRADE_COMPLIANCE_PROMPT,
    PLANNER_PROMPT,
    REFLECTION_PROMPT,
    PLANNING_PROMPT,
)

__all__ = [
    "CONDENSE_SYSTEM_PROMPT",
    "ANSWER_SYSTEM_PROMPT",
    "STRUCTURED_ANSWER_PROMPT",
    "TRADE_COMPLIANCE_PROMPT",
    "PLANNER_PROMPT",
    "REFLECTION_PROMPT",
    "PLANNING_PROMPT",
]
