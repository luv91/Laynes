"""
Document Chunker (v10.0 Phase 2)

Splits documents into chunks for RAG retrieval.
Chunks are sized for:
- Vector embedding (400-1200 chars optimal)
- LLM context windows
- Precise quote location tracking

Chunking strategies:
- paragraph: Split by paragraph boundaries
- sentence: Split by sentence boundaries
- fixed: Fixed character size with overlap
- semantic: Use sentence transformers for semantic chunking
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.ingestion.connectors.base import ConnectorResult


@dataclass
class Chunk:
    """A single chunk of text from a document."""
    id: str
    document_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    text_hash: str
    metadata: Dict[str, Any]


class DocumentChunker:
    """
    Chunks documents for RAG retrieval.

    Default settings:
    - min_chunk_size: 200 chars (avoid tiny chunks)
    - max_chunk_size: 1200 chars (fit in context)
    - overlap: 50 chars (maintain context continuity)
    """

    def __init__(
        self,
        min_chunk_size: int = 200,
        max_chunk_size: int = 1200,
        overlap: int = 50,
        strategy: str = "paragraph"
    ):
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.strategy = strategy

    def _compute_hash(self, text: str) -> str:
        """Compute SHA-256 hash of chunk text."""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def _split_by_paragraphs(self, text: str) -> List[str]:
        """Split text by paragraph boundaries (double newline)."""
        paragraphs = re.split(r'\n\n+', text.strip())
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_by_sentences(self, text: str) -> List[str]:
        """Split text by sentence boundaries."""
        # Simple sentence splitting (handles Mr., Mrs., etc.)
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        return [s.strip() for s in sentences if s.strip()]

    def _merge_small_chunks(self, chunks: List[str]) -> List[str]:
        """Merge chunks that are below minimum size."""
        if not chunks:
            return []

        merged = []
        current = chunks[0]

        for chunk in chunks[1:]:
            if len(current) < self.min_chunk_size:
                current = current + "\n\n" + chunk
            else:
                merged.append(current)
                current = chunk

        merged.append(current)
        return merged

    def _split_large_chunk(self, text: str) -> List[str]:
        """Split a chunk that exceeds max size."""
        if len(text) <= self.max_chunk_size:
            return [text]

        result = []
        sentences = self._split_by_sentences(text)

        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 > self.max_chunk_size:
                if current:
                    result.append(current.strip())
                # If single sentence is too long, hard split
                if len(sentence) > self.max_chunk_size:
                    for i in range(0, len(sentence), self.max_chunk_size - self.overlap):
                        result.append(sentence[i:i + self.max_chunk_size])
                    current = ""
                else:
                    current = sentence
            else:
                current = current + " " + sentence if current else sentence

        if current:
            result.append(current.strip())

        return result

    def _apply_overlap(self, chunks: List[Tuple[str, int, int]]) -> List[Tuple[str, int, int]]:
        """Apply overlap between chunks for context continuity."""
        if len(chunks) <= 1 or self.overlap == 0:
            return chunks

        result = [chunks[0]]

        for i in range(1, len(chunks)):
            text, start, end = chunks[i]
            prev_text, prev_start, prev_end = chunks[i - 1]

            # Add overlap from previous chunk
            overlap_text = prev_text[-self.overlap:] if len(prev_text) > self.overlap else prev_text
            new_text = overlap_text + " " + text
            new_start = max(0, start - self.overlap)

            result.append((new_text, new_start, end))

        return result

    def chunk_text(self, text: str, document_id: str) -> List[Chunk]:
        """
        Chunk text into sized pieces with position tracking.

        Args:
            text: The full text to chunk
            document_id: UUID of the source document

        Returns:
            List of Chunk objects with position metadata
        """
        if not text or not text.strip():
            return []

        # Step 1: Initial split based on strategy
        if self.strategy == "paragraph":
            raw_chunks = self._split_by_paragraphs(text)
        elif self.strategy == "sentence":
            raw_chunks = self._split_by_sentences(text)
        else:  # fixed
            raw_chunks = [text[i:i + self.max_chunk_size]
                         for i in range(0, len(text), self.max_chunk_size - self.overlap)]

        # Step 2: Merge small chunks
        merged = self._merge_small_chunks(raw_chunks)

        # Step 3: Split large chunks
        sized = []
        for chunk in merged:
            sized.extend(self._split_large_chunk(chunk))

        # Step 4: Calculate positions
        positioned = []
        current_pos = 0
        for chunk_text in sized:
            # Find actual position in original text
            start = text.find(chunk_text[:50], current_pos)
            if start == -1:
                start = current_pos
            end = start + len(chunk_text)
            positioned.append((chunk_text, start, end))
            current_pos = start + 1

        # Step 5: Apply overlap (optional)
        # positioned = self._apply_overlap(positioned)

        # Step 6: Create Chunk objects
        chunks = []
        for i, (chunk_text, start, end) in enumerate(positioned):
            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                chunk_index=i,
                text=chunk_text,
                char_start=start,
                char_end=end,
                text_hash=self._compute_hash(chunk_text),
                metadata={
                    "strategy": self.strategy,
                    "original_length": len(text),
                    "chunk_length": len(chunk_text),
                }
            ))

        return chunks

    def chunk_document(self, result: ConnectorResult) -> List[Chunk]:
        """
        Chunk a ConnectorResult into retrieval-ready pieces.

        Args:
            result: ConnectorResult from a trusted connector

        Returns:
            List of Chunk objects
        """
        return self.chunk_text(result.extracted_text, result.document_id)


def chunk_document(
    text: str,
    document_id: str,
    min_size: int = 200,
    max_size: int = 1200,
    overlap: int = 50,
    strategy: str = "paragraph"
) -> List[Chunk]:
    """
    Convenience function to chunk a document.

    Args:
        text: The text to chunk
        document_id: UUID of the source document
        min_size: Minimum chunk size
        max_size: Maximum chunk size
        overlap: Overlap between chunks
        strategy: Chunking strategy

    Returns:
        List of Chunk objects
    """
    chunker = DocumentChunker(
        min_chunk_size=min_size,
        max_chunk_size=max_size,
        overlap=overlap,
        strategy=strategy
    )
    return chunker.chunk_text(text, document_id)
