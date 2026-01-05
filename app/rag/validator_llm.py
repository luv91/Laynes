"""
Validator LLM (v10.0 Phase 3)

Independently verifies that Reader's claims are supported by cited quotes.
Uses a different model/prompt to reduce correlated mistakes.

Key responsibilities:
- Verify each citation quote exists in the chunks
- Confirm the quote actually supports the claim
- Flag unsupported or weakly supported claims
- Detect missing evidence for strong claims

Output schema:
{
    "verified": true | false,
    "failures": [
        {"citation_index": 0, "reason": "quote not found in chunk"}
    ],
    "required_fixes": [],
    "confidence": "high" | "medium" | "low"
}
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openai import OpenAI


@dataclass
class ValidationFailure:
    """A single validation failure."""
    citation_index: int
    reason: str
    severity: str = "error"  # error, warning


@dataclass
class ValidatorOutput:
    """Full output from Validator LLM."""
    success: bool
    verified: bool
    failures: List[ValidationFailure] = field(default_factory=list)
    required_fixes: List[str] = field(default_factory=list)
    confidence: str = "low"
    raw_response: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "verified": self.verified,
            "failures": [
                {
                    "citation_index": f.citation_index,
                    "reason": f.reason,
                    "severity": f.severity,
                }
                for f in self.failures
            ],
            "required_fixes": self.required_fixes,
            "confidence": self.confidence,
            "error": self.error,
        }


class ValidatorLLM:
    """
    Validator LLM for verifying Reader's claims.

    Uses a different model (or temperature) than Reader to reduce
    correlated mistakes.
    """

    SYSTEM_PROMPT = """You are a fact-checker for tariff scope determinations. Your job is to verify that claims are properly supported by evidence.

CRITICAL RULES:
1. For each citation, verify the quote is an EXACT substring of the provided chunk text.
2. Verify the quote actually supports the claim (not just tangentially related).
3. If in_scope is true, there MUST be at least one citation showing the HTS code is listed.
4. If in_scope is false, there should be evidence of exclusion or gap proof.
5. Flag any claims that are not supported by the cited evidence.

You must return valid JSON only. No markdown, no explanation outside JSON."""

    def __init__(self, model: str = "gpt-4o-mini"):
        """Initialize Validator LLM."""
        self.model = model
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _build_validation_prompt(
        self,
        reader_output: Dict[str, Any],
        chunks: List[Dict[str, Any]]
    ) -> str:
        """Build prompt for validation."""
        # Format chunks for reference
        chunks_text = ""
        for i, chunk in enumerate(chunks):
            chunks_text += f"""--- CHUNK {i + 1} ---
Document ID: {chunk.get('document_id', 'unknown')}
Chunk ID: {chunk.get('chunk_id', 'unknown')}
Text:
{chunk.get('text', '')}
---

"""

        # Format reader output
        reader_json = json.dumps(reader_output, indent=2)

        return f"""READER OUTPUT TO VALIDATE:
{reader_json}

ORIGINAL CHUNKS:
{chunks_text}

VALIDATION TASK:
1. For each citation, verify the "quote" is an EXACT substring of the corresponding chunk's text.
2. Verify the quote supports the claim being made (in_scope value).
3. Check if the HTS code appears in the cited evidence.
4. Return validation result.

Return JSON with this exact structure:
{{
    "verified": true | false,
    "failures": [
        {{
            "citation_index": 0,
            "reason": "explanation of what's wrong",
            "severity": "error" | "warning"
        }}
    ],
    "required_fixes": ["list of things that must be fixed"],
    "confidence": "high" | "medium" | "low"
}}

RULES:
- verified=true ONLY if ALL citations are valid and support the claim
- If quote is not found verbatim, that's an error
- If quote doesn't contain HTS code when claiming in_scope=true, that's a warning
- If in_scope=true but no valid citations, that's an error"""

    def _parse_response(self, response_text: str) -> ValidatorOutput:
        """Parse LLM response into structured output."""
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)
            else:
                return ValidatorOutput(
                    success=False,
                    verified=False,
                    raw_response=response_text,
                    error="No JSON found in response"
                )

            failures = []
            for f in data.get("failures", []):
                failures.append(ValidationFailure(
                    citation_index=f.get("citation_index", 0),
                    reason=f.get("reason", ""),
                    severity=f.get("severity", "error"),
                ))

            return ValidatorOutput(
                success=True,
                verified=data.get("verified", False),
                failures=failures,
                required_fixes=data.get("required_fixes", []),
                confidence=data.get("confidence", "low"),
                raw_response=response_text,
            )

        except json.JSONDecodeError as e:
            return ValidatorOutput(
                success=False,
                verified=False,
                raw_response=response_text,
                error=f"JSON parse error: {str(e)}"
            )

    def validate(
        self,
        reader_output: Dict[str, Any],
        chunks: List[Dict[str, Any]]
    ) -> ValidatorOutput:
        """
        Validate Reader's output against the original chunks.

        Args:
            reader_output: The Reader LLM's output dict
            chunks: The original chunks that Reader analyzed

        Returns:
            ValidatorOutput with verification result
        """
        if not reader_output:
            return ValidatorOutput(
                success=False,
                verified=False,
                error="No reader output provided"
            )

        prompt = self._build_validation_prompt(reader_output, chunks)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # Zero temperature for deterministic validation
                max_tokens=1500,
            )

            response_text = response.choices[0].message.content
            return self._parse_response(response_text)

        except Exception as e:
            return ValidatorOutput(
                success=False,
                verified=False,
                error=str(e)
            )

    def quick_validate(
        self,
        reader_output: Dict[str, Any],
        chunks: List[Dict[str, Any]]
    ) -> ValidatorOutput:
        """
        Quick validation without LLM - just mechanical checks.

        Checks:
        - Each citation has document_id and chunk_id
        - Quote is present (non-empty)
        - Quote appears in the referenced chunk

        This is faster but less thorough than full validation.
        """
        failures = []

        citations = reader_output.get("citations", [])
        answer = reader_output.get("answer", {})

        # Build chunk lookup
        chunk_lookup = {}
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if chunk_id:
                chunk_lookup[chunk_id] = chunk.get("text", "")

        for i, citation in enumerate(citations):
            doc_id = citation.get("document_id")
            chunk_id = citation.get("chunk_id")
            quote = citation.get("quote", "")

            if not doc_id:
                failures.append(ValidationFailure(
                    citation_index=i,
                    reason="Missing document_id",
                    severity="error"
                ))

            if not chunk_id:
                failures.append(ValidationFailure(
                    citation_index=i,
                    reason="Missing chunk_id",
                    severity="error"
                ))

            if not quote:
                failures.append(ValidationFailure(
                    citation_index=i,
                    reason="Empty quote",
                    severity="error"
                ))
            elif chunk_id in chunk_lookup:
                # Check if quote exists in chunk
                if quote not in chunk_lookup[chunk_id]:
                    failures.append(ValidationFailure(
                        citation_index=i,
                        reason="Quote not found verbatim in chunk",
                        severity="error"
                    ))

        # Check if in_scope=true has citations
        if answer.get("in_scope") is True and not citations:
            failures.append(ValidationFailure(
                citation_index=-1,
                reason="in_scope=true but no citations provided",
                severity="error"
            ))

        verified = len([f for f in failures if f.severity == "error"]) == 0

        return ValidatorOutput(
            success=True,
            verified=verified,
            failures=failures,
            confidence="high" if verified else "low",
        )
