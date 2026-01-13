"""
Chunk Worker

Splits documents into chunks for RAG retrieval.

Chunking strategy:
- Target 300-900 tokens per chunk
- Respect semantic boundaries (paragraphs, sections)
- Track line numbers for evidence citation
"""

import logging
import re
from datetime import datetime
from typing import List, Tuple

from app.web.db import db
from app.models.document_store import OfficialDocument, DocumentChunk
from app.models.ingest_job import IngestJob

logger = logging.getLogger(__name__)


class ChunkWorker:
    """
    Splits rendered documents into chunks for RAG.

    Chunking is semantic-aware:
    - Respects section boundaries (=== HEADING ===)
    - Keeps tables together
    - Tracks line numbers for evidence
    """

    # Token limits (approximate)
    MIN_CHUNK_TOKENS = 100
    TARGET_CHUNK_TOKENS = 500
    MAX_CHUNK_TOKENS = 900

    # Approximate tokens per character (for estimation)
    CHARS_PER_TOKEN = 4

    def process(self, doc: OfficialDocument, job: IngestJob = None) -> int:
        """
        Split document into chunks.

        Args:
            doc: OfficialDocument with canonical_text
            job: Optional IngestJob for status tracking

        Returns:
            Number of chunks created
        """
        if job:
            job.status = "chunking"
            db.session.commit()

        if not doc.canonical_text:
            logger.warning(f"No canonical text for {doc.external_id}")
            return 0

        try:
            # Clear existing chunks
            DocumentChunk.query.filter_by(document_id=doc.id).delete()

            # Split into chunks
            chunks = self._create_chunks(doc.canonical_text)

            # Store chunks
            for i, (text, line_start, line_end, chunk_type, heading) in enumerate(chunks):
                chunk = DocumentChunk(
                    document_id=doc.id,
                    chunk_index=i,
                    text=text,
                    line_start=line_start,
                    line_end=line_end,
                    token_count=self._estimate_tokens(text),
                    chunk_type=chunk_type,
                    section_heading=heading,
                )
                db.session.add(chunk)

            doc.status = "chunked"

            if job:
                job.status = "chunked"

            db.session.commit()

            logger.info(f"Created {len(chunks)} chunks for {doc.external_id}")
            return len(chunks)

        except Exception as e:
            logger.error(f"Chunking failed for {doc.external_id}: {e}")
            if job:
                job.mark_failed(f"Chunk error: {e}")
            db.session.commit()
            return 0

    def _create_chunks(self, text: str) -> List[Tuple[str, int, int, str, str]]:
        """
        Split text into chunks.

        Returns list of (text, line_start, line_end, chunk_type, section_heading) tuples.
        """
        lines = text.split('\n')
        chunks = []

        current_chunk_lines = []
        current_line_start = 1
        current_section = None
        current_type = "narrative"

        for line in lines:
            # Extract line number from format "L0001: content"
            match = re.match(r'L(\d+):\s*(.*)', line)
            if not match:
                continue

            line_num = int(match.group(1))
            content = match.group(2)

            # Check for section heading
            if content.startswith('===') and content.endswith('==='):
                # Flush current chunk
                if current_chunk_lines:
                    chunk_text = '\n'.join(current_chunk_lines)
                    chunks.append((
                        chunk_text,
                        current_line_start,
                        line_num - 1,
                        current_type,
                        current_section,
                    ))
                    current_chunk_lines = []

                # Start new section
                current_section = content.strip('= ')
                current_line_start = line_num
                current_type = "heading"
                continue

            # Check for table row (contains |)
            if ' | ' in content:
                current_type = "table"
            elif not content.startswith('==='):
                if current_type == "table":
                    # End of table, flush
                    if current_chunk_lines:
                        chunk_text = '\n'.join(current_chunk_lines)
                        chunks.append((
                            chunk_text,
                            current_line_start,
                            line_num - 1,
                            "table",
                            current_section,
                        ))
                        current_chunk_lines = []
                        current_line_start = line_num
                    current_type = "narrative"

            # Add line to current chunk
            current_chunk_lines.append(line)

            # Check if chunk is big enough
            current_tokens = self._estimate_tokens('\n'.join(current_chunk_lines))
            if current_tokens >= self.TARGET_CHUNK_TOKENS:
                # Flush chunk
                chunk_text = '\n'.join(current_chunk_lines)
                chunks.append((
                    chunk_text,
                    current_line_start,
                    line_num,
                    current_type,
                    current_section,
                ))
                current_chunk_lines = []
                current_line_start = line_num + 1
                current_type = "narrative"

        # Flush remaining
        if current_chunk_lines:
            chunk_text = '\n'.join(current_chunk_lines)
            # Get last line number
            last_line_match = re.match(r'L(\d+):', current_chunk_lines[-1])
            last_line = int(last_line_match.group(1)) if last_line_match else current_line_start

            chunks.append((
                chunk_text,
                current_line_start,
                last_line,
                current_type,
                current_section,
            ))

        return chunks

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from text length."""
        return len(text) // self.CHARS_PER_TOKEN
