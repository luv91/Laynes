"""
Reader LLM (v10.0 Phase 3)

Answers user questions using ONLY retrieved chunks from our corpus.
Returns structured output with exact citations.

Key constraints:
- Answer ONLY from provided chunks (no external knowledge)
- Cite exact quotes with document/chunk IDs
- Return null for confidence if cannot determine

Output schema:
{
    "answer": {
        "in_scope": true | false | null,
        "program": "section_232_copper",
        "claim_codes": ["9903.78.01"],
        "confidence": "high" | "medium" | "low"
    },
    "citations": [
        {
            "document_id": "uuid",
            "chunk_id": "uuid",
            "quote": "verbatim text",
            "why_this_supports": "explanation"
        }
    ],
    "missing_info": [],
    "contradictions": []
}
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openai import OpenAI


@dataclass
class Citation:
    """A citation from the Reader LLM."""
    document_id: str
    chunk_id: str
    quote: str
    why_this_supports: str


@dataclass
class ReaderAnswer:
    """The answer portion of Reader output."""
    in_scope: Optional[bool]
    program: str
    hts_code: str
    claim_codes: List[str] = field(default_factory=list)
    disclaim_codes: List[str] = field(default_factory=list)
    confidence: str = "low"


@dataclass
class ReaderOutput:
    """Full output from Reader LLM."""
    success: bool
    answer: Optional[ReaderAnswer]
    citations: List[Citation] = field(default_factory=list)
    missing_info: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    raw_response: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "answer": {
                "in_scope": self.answer.in_scope if self.answer else None,
                "program": self.answer.program if self.answer else None,
                "hts_code": self.answer.hts_code if self.answer else None,
                "claim_codes": self.answer.claim_codes if self.answer else [],
                "disclaim_codes": self.answer.disclaim_codes if self.answer else [],
                "confidence": self.answer.confidence if self.answer else "low",
            } if self.answer else None,
            "citations": [
                {
                    "document_id": c.document_id,
                    "chunk_id": c.chunk_id,
                    "quote": c.quote,
                    "why_this_supports": c.why_this_supports,
                }
                for c in self.citations
            ],
            "missing_info": self.missing_info,
            "contradictions": self.contradictions,
            "error": self.error,
        }


class ReaderLLM:
    """
    Reader LLM for answering scope questions from retrieved chunks.

    Uses OpenAI GPT-4 for interpretation with strict instructions
    to only use provided context.
    """

    SYSTEM_PROMPT = """You are a tariff scope analyst. Your job is to determine whether an HTS code is in scope for a tariff program.

CRITICAL RULES:
1. ONLY use the provided document chunks to answer. Do NOT use external knowledge.
2. If the answer is not clearly stated in the chunks, return in_scope: null.
3. For every claim, provide an EXACT verbatim quote from the chunks.
4. Include the document_id and chunk_id for each citation.
5. If you find contradictory information, list it in contradictions[].
6. If you need more information, list it in missing_info[].

You must return valid JSON only. No markdown, no explanation outside JSON."""

    def __init__(self, model: str = "gpt-4o-mini"):
        """Initialize Reader LLM with OpenAI client."""
        self.model = model
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _build_chunks_context(self, chunks: List[Dict[str, Any]]) -> str:
        """Build context string from chunks."""
        context_parts = []
        for i, chunk in enumerate(chunks):
            context_parts.append(f"""--- CHUNK {i + 1} ---
Document ID: {chunk.get('document_id', 'unknown')}
Chunk ID: {chunk.get('chunk_id', 'unknown')}
Source: {chunk.get('source', 'unknown')}
Text:
{chunk.get('text', '')}
---""")
        return "\n\n".join(context_parts)

    def _build_user_prompt(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str],
        chunks: List[Dict[str, Any]]
    ) -> str:
        """Build the user prompt with question and context."""
        material_str = f" for {material}" if material else ""
        chunks_context = self._build_chunks_context(chunks)

        return f"""QUESTION:
Is HTS code {hts_code} in scope for {program_id}{material_str}?

DOCUMENT CHUNKS:
{chunks_context}

Analyze the chunks and return JSON with this exact structure:
{{
    "answer": {{
        "in_scope": true | false | null,
        "program": "{program_id}",
        "hts_code": "{hts_code}",
        "claim_codes": ["list of applicable Chapter 99 claim codes"],
        "disclaim_codes": ["list of applicable disclaim codes"],
        "confidence": "high" | "medium" | "low"
    }},
    "citations": [
        {{
            "document_id": "the document ID from the chunk",
            "chunk_id": "the chunk ID",
            "quote": "EXACT verbatim quote that supports the answer (max 300 chars)",
            "why_this_supports": "brief explanation"
        }}
    ],
    "missing_info": ["list of information needed but not found"],
    "contradictions": ["list of contradictory statements found"]
}}

IMPORTANT:
- in_scope MUST be null if you cannot determine from the chunks
- quotes MUST be EXACT verbatim text from the chunks
- If HTS {hts_code} or its 8-digit prefix is listed, it's in_scope: true
- If you find evidence it's NOT listed (gap proof), it's in_scope: false"""

    def _parse_response(self, response_text: str) -> ReaderOutput:
        """Parse LLM response into structured output."""
        try:
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)
            else:
                return ReaderOutput(
                    success=False,
                    answer=None,
                    raw_response=response_text,
                    error="No JSON found in response"
                )

            # Parse answer
            answer_data = data.get("answer", {})
            answer = ReaderAnswer(
                in_scope=answer_data.get("in_scope"),
                program=answer_data.get("program", ""),
                hts_code=answer_data.get("hts_code", ""),
                claim_codes=answer_data.get("claim_codes", []),
                disclaim_codes=answer_data.get("disclaim_codes", []),
                confidence=answer_data.get("confidence", "low"),
            )

            # Parse citations
            citations = []
            for c in data.get("citations", []):
                citations.append(Citation(
                    document_id=c.get("document_id", ""),
                    chunk_id=c.get("chunk_id", ""),
                    quote=c.get("quote", ""),
                    why_this_supports=c.get("why_this_supports", ""),
                ))

            return ReaderOutput(
                success=True,
                answer=answer,
                citations=citations,
                missing_info=data.get("missing_info", []),
                contradictions=data.get("contradictions", []),
                raw_response=response_text,
            )

        except json.JSONDecodeError as e:
            return ReaderOutput(
                success=False,
                answer=None,
                raw_response=response_text,
                error=f"JSON parse error: {str(e)}"
            )

    def read(
        self,
        hts_code: str,
        program_id: str,
        material: Optional[str],
        chunks: List[Dict[str, Any]]
    ) -> ReaderOutput:
        """
        Read chunks and answer scope question.

        Args:
            hts_code: The HTS code to check
            program_id: The tariff program (section_232, section_301, etc.)
            material: Material type for 232 (copper, steel, aluminum)
            chunks: List of chunk dicts with text, document_id, chunk_id

        Returns:
            ReaderOutput with answer and citations
        """
        if not chunks:
            return ReaderOutput(
                success=False,
                answer=None,
                error="No chunks provided"
            )

        user_prompt = self._build_user_prompt(hts_code, program_id, material, chunks)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=2000,
            )

            response_text = response.choices[0].message.content
            return self._parse_response(response_text)

        except Exception as e:
            return ReaderOutput(
                success=False,
                answer=None,
                error=str(e)
            )
