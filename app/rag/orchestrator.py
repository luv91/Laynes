"""
RAG Orchestrator (v10.0 Phase 3)

Coordinates the full RAG pipeline:
1. Check verified_assertion cache (Layer 1)
2. Retrieve chunks from Pinecone (Layer 2)
3. Reader LLM analyzes chunks
4. Validator LLM verifies Reader output
5. Write Gate checks mechanical proofs
6. Store verified_assertion or queue for review

This is the main entry point for scope verification.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.rag.reader_llm import ReaderLLM, ReaderOutput
from app.rag.validator_llm import ValidatorLLM, ValidatorOutput
from app.rag.write_gate import WriteGate, WriteGateResult


@dataclass
class RAGResult:
    """Result from the RAG pipeline."""
    success: bool
    source: str  # 'verified_cache', 'rag_verified', 'rag_pending', 'discovery_needed'
    is_verified: bool

    # The answer
    in_scope: Optional[bool] = None
    claim_codes: List[str] = field(default_factory=list)
    disclaim_codes: List[str] = field(default_factory=list)
    confidence: str = "low"

    # Evidence
    evidence_quote: Optional[str] = None
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None

    # Pipeline outputs
    reader_output: Optional[Dict[str, Any]] = None
    validator_output: Optional[Dict[str, Any]] = None
    write_gate_result: Optional[Dict[str, Any]] = None

    # Metadata
    verified_assertion_id: Optional[str] = None
    review_queue_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source": self.source,
            "is_verified": self.is_verified,
            "in_scope": self.in_scope,
            "claim_codes": self.claim_codes,
            "disclaim_codes": self.disclaim_codes,
            "confidence": self.confidence,
            "evidence_quote": self.evidence_quote[:200] + "..." if self.evidence_quote and len(self.evidence_quote) > 200 else self.evidence_quote,
            "document_id": self.document_id,
            "verified_assertion_id": self.verified_assertion_id,
            "review_queue_id": self.review_queue_id,
            "error": self.error,
        }


class RAGOrchestrator:
    """
    Orchestrates the RAG verification pipeline.

    Flow:
    1. Check verified_assertion (fast path)
    2. If miss, retrieve chunks from Pinecone
    3. Reader LLM answers from chunks
    4. Validator LLM verifies
    5. Write Gate checks proofs
    6. Store or queue

    Usage:
        orchestrator = RAGOrchestrator(session)
        result = orchestrator.verify_scope(
            hts_code="8544.42.9090",
            program_id="section_232",
            material="copper"
        )
    """

    def __init__(
        self,
        session: Session,
        reader_model: str = "gpt-4o-mini",
        validator_model: str = "gpt-4o-mini"
    ):
        """Initialize orchestrator with database session and LLM models."""
        self.session = session
        self.reader = ReaderLLM(model=reader_model)
        self.validator = ValidatorLLM(model=validator_model)
        self.write_gate = WriteGate(session)

    def _normalize_hts(self, hts_code: str) -> str:
        """Normalize HTS code to digits only."""
        return hts_code.replace(".", "").replace("-", "").strip()

    def _check_verified_cache(
        self,
        hts_code_norm: str,
        program_id: str,
        material: Optional[str]
    ) -> Optional[RAGResult]:
        """
        Layer 1: Check for existing verified assertion.

        Returns RAGResult if found, None if cache miss.
        """
        from app.web.db.models.document import VerifiedAssertion

        query = self.session.query(VerifiedAssertion).filter(
            VerifiedAssertion.hts_code_norm == hts_code_norm,
            VerifiedAssertion.program_id == program_id,
            VerifiedAssertion.effective_end.is_(None)  # Current only
        )

        if material:
            query = query.filter(VerifiedAssertion.material == material)

        assertion = query.first()

        if assertion:
            return RAGResult(
                success=True,
                source="verified_cache",
                is_verified=True,
                in_scope=assertion.assertion_type == "IN_SCOPE",
                claim_codes=[assertion.claim_code] if assertion.claim_code else [],
                disclaim_codes=[assertion.disclaim_code] if assertion.disclaim_code else [],
                confidence="high",
                evidence_quote=assertion.evidence_quote,
                document_id=assertion.document_id,
                chunk_id=assertion.chunk_id,
                verified_assertion_id=assertion.id,
            )

        return None

    def _retrieve_chunks(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Layer 2: Retrieve relevant chunks from Pinecone.

        Filters by tier='A' to only get official documents.
        """
        try:
            from app.chat.vector_stores.tariff_search import TariffVectorSearch

            vector_search = TariffVectorSearch()

            # Build query
            material_str = material if material else "scope"
            query = f"HTS {hts_code} {program_id} {material_str}"

            # Search with tier filter
            results = vector_search.search_similar(
                query=query,
                hts_code=hts_code,
                query_type=program_id,
                material=material,
                top_k=top_k
            )

            # Convert to chunk dicts
            chunks = []
            for match in results:
                chunks.append({
                    "document_id": match.get("metadata", {}).get("document_id"),
                    "chunk_id": match.get("id"),
                    "text": match.get("metadata", {}).get("chunk_text", ""),
                    "source": match.get("metadata", {}).get("source_type"),
                    "score": match.get("score"),
                })

            return chunks

        except Exception:
            return []

    def _store_verified_assertion(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str],
        reader_output: ReaderOutput,
        validator_output: ValidatorOutput
    ) -> str:
        """Store a verified assertion in the truth table."""
        from app.web.db.models.document import VerifiedAssertion

        hts_code_norm = self._normalize_hts(hts_code)
        answer = reader_output.answer

        # Get primary citation
        primary_citation = reader_output.citations[0] if reader_output.citations else None

        assertion_id = str(uuid.uuid4())
        evidence_quote = primary_citation.quote if primary_citation else ""

        assertion = VerifiedAssertion(
            id=assertion_id,
            program_id=program_id,
            hts_code_norm=hts_code_norm,
            hts_digits=len(hts_code_norm),
            material=material,
            assertion_type="IN_SCOPE" if answer.in_scope else "OUT_OF_SCOPE",
            claim_code=answer.claim_codes[0] if answer.claim_codes else None,
            disclaim_code=answer.disclaim_codes[0] if answer.disclaim_codes else None,
            effective_start=date.today(),
            effective_end=None,
            document_id=primary_citation.document_id if primary_citation else None,
            chunk_id=primary_citation.chunk_id if primary_citation else None,
            evidence_quote=evidence_quote,
            evidence_quote_hash=hashlib.sha256(evidence_quote.encode()).hexdigest(),
            reader_output=reader_output.to_dict(),
            validator_output=validator_output.to_dict(),
            verified_at=datetime.utcnow(),
            verified_by="write_gate",
        )

        self.session.add(assertion)
        self.session.commit()

        return assertion_id

    def _queue_for_review(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str],
        reader_output: Optional[ReaderOutput],
        validator_output: Optional[ValidatorOutput],
        write_gate_result: Optional[WriteGateResult],
        reason: str
    ) -> str:
        """Queue failed verification for review."""
        from app.web.db.models.tariff_tables import NeedsReviewQueue

        queue_id = str(uuid.uuid4())

        entry = NeedsReviewQueue(
            id=queue_id,
            hts_code=hts_code,
            query_type=program_id,
            material=material,
            reader_output=reader_output.to_dict() if reader_output else None,
            validator_output=validator_output.to_dict() if validator_output else None,
            block_reason=reason,
            block_details={
                "write_gate": write_gate_result.to_dict() if write_gate_result else None,
            },
            status="pending",
            priority=0,
            created_at=datetime.utcnow(),
        )

        self.session.add(entry)
        self.session.commit()

        return queue_id

    def verify_scope(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str] = None,
        force_rag: bool = False
    ) -> RAGResult:
        """
        Main entry point for scope verification.

        Args:
            hts_code: The HTS code to verify
            program_id: The tariff program (section_232, section_301, etc.)
            material: Material type for 232 (copper, steel, aluminum)
            force_rag: If True, skip verified cache and run RAG

        Returns:
            RAGResult with verification status and evidence
        """
        hts_code_norm = self._normalize_hts(hts_code)

        # Layer 1: Check verified assertion cache
        if not force_rag:
            cached = self._check_verified_cache(hts_code_norm, program_id, material)
            if cached:
                return cached

        # Layer 2: Retrieve chunks from corpus
        chunks = self._retrieve_chunks(hts_code, program_id, material)

        if not chunks:
            # No chunks found - need discovery mode
            queue_id = self._queue_for_review(
                hts_code, program_id, material,
                None, None, None,
                "no_chunks_found"
            )
            return RAGResult(
                success=False,
                source="discovery_needed",
                is_verified=False,
                error="No relevant documents found in corpus",
                review_queue_id=queue_id,
            )

        # Layer 3: Reader LLM
        reader_output = self.reader.read(hts_code, program_id, material, chunks)

        if not reader_output.success:
            queue_id = self._queue_for_review(
                hts_code, program_id, material,
                reader_output, None, None,
                f"reader_failed: {reader_output.error}"
            )
            return RAGResult(
                success=False,
                source="rag_pending",
                is_verified=False,
                error=reader_output.error,
                reader_output=reader_output.to_dict(),
                review_queue_id=queue_id,
            )

        # Layer 4: Validator LLM
        validator_output = self.validator.validate(reader_output.to_dict(), chunks)

        if not validator_output.success:
            queue_id = self._queue_for_review(
                hts_code, program_id, material,
                reader_output, validator_output, None,
                f"validator_failed: {validator_output.error}"
            )
            return RAGResult(
                success=False,
                source="rag_pending",
                is_verified=False,
                error=validator_output.error,
                reader_output=reader_output.to_dict(),
                validator_output=validator_output.to_dict(),
                review_queue_id=queue_id,
            )

        # Layer 5: Write Gate
        write_gate_result = self.write_gate.check(
            reader_output.to_dict(),
            validator_output.to_dict()
        )

        # If all checks pass, store verified assertion
        if write_gate_result.passed and validator_output.verified:
            assertion_id = self._store_verified_assertion(
                hts_code, program_id, material,
                reader_output, validator_output
            )

            primary_citation = reader_output.citations[0] if reader_output.citations else None

            return RAGResult(
                success=True,
                source="rag_verified",
                is_verified=True,
                in_scope=reader_output.answer.in_scope,
                claim_codes=reader_output.answer.claim_codes,
                disclaim_codes=reader_output.answer.disclaim_codes,
                confidence=reader_output.answer.confidence,
                evidence_quote=primary_citation.quote if primary_citation else None,
                document_id=primary_citation.document_id if primary_citation else None,
                chunk_id=primary_citation.chunk_id if primary_citation else None,
                reader_output=reader_output.to_dict(),
                validator_output=validator_output.to_dict(),
                write_gate_result=write_gate_result.to_dict(),
                verified_assertion_id=assertion_id,
            )

        # Write Gate failed - queue for review
        queue_id = self._queue_for_review(
            hts_code, program_id, material,
            reader_output, validator_output, write_gate_result,
            "write_gate_failed"
        )

        return RAGResult(
            success=False,
            source="rag_pending",
            is_verified=False,
            in_scope=reader_output.answer.in_scope if reader_output.answer else None,
            claim_codes=reader_output.answer.claim_codes if reader_output.answer else [],
            confidence="low",
            reader_output=reader_output.to_dict(),
            validator_output=validator_output.to_dict(),
            write_gate_result=write_gate_result.to_dict(),
            review_queue_id=queue_id,
            error="; ".join(write_gate_result.errors),
        )
