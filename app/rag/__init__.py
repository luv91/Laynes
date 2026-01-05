"""
RAG Pipeline Module (v10.0 Phase 3)

Implements the two-LLM verification pattern:
1. Reader LLM: Answers from retrieved chunks with exact citations
2. Validator LLM: Independently verifies Reader's claims
3. Write Gate: Mechanical proof checks (quote exists in chunk)
4. Orchestrator: Coordinates the full pipeline

Usage:
    from app.rag import RAGOrchestrator

    orchestrator = RAGOrchestrator(session)
    result = orchestrator.verify_scope(
        hts_code="8544.42.9090",
        program_id="section_232",
        material="copper"
    )
"""

from app.rag.reader_llm import ReaderLLM, ReaderOutput
from app.rag.validator_llm import ValidatorLLM, ValidatorOutput
from app.rag.write_gate import WriteGate, WriteGateResult
from app.rag.orchestrator import RAGOrchestrator, RAGResult

__all__ = [
    'ReaderLLM',
    'ReaderOutput',
    'ValidatorLLM',
    'ValidatorOutput',
    'WriteGate',
    'WriteGateResult',
    'RAGOrchestrator',
    'RAGResult',
]
