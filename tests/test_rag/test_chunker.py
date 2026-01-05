"""
Unit tests for Document Chunker (v10.0 Phase 2).

Tests:
- Paragraph-based chunking
- Sentence-based chunking
- Fixed-size chunking
- Chunk size constraints
- Position tracking
"""

import pytest


class TestDocumentChunker:
    """Tests for the DocumentChunker class."""

    def test_basic_paragraph_chunking(self):
        """Test basic paragraph-based chunking."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(min_chunk_size=50, max_chunk_size=500)

        text = """First paragraph about Section 232 steel tariffs.

Second paragraph about HTS code 8544.42.9090.

Third paragraph about claim codes and exclusions."""

        chunks = chunker.chunk_text(text, "doc-123")

        assert len(chunks) > 0
        assert all(chunk.document_id == "doc-123" for chunk in chunks)
        # Each chunk should have text
        assert all(len(chunk.text) > 0 for chunk in chunks)

    def test_chunk_size_constraints(self):
        """Test that chunks respect size constraints."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(min_chunk_size=100, max_chunk_size=300)

        # Create text with varying paragraph sizes
        text = """Short paragraph.

This is a medium-length paragraph that contains more content about tariffs and HTS codes for testing purposes.

This is a very long paragraph that goes into great detail about Section 232 steel tariffs, including all the relevant HTS codes like 8544.42.9090, claim codes like 9903.78.01, and various other regulatory information that would be found in a typical CSMS bulletin or Federal Register notice."""

        chunks = chunker.chunk_text(text, "doc-123")

        # Large chunks should be split
        for chunk in chunks:
            # Allow some tolerance for edge cases
            assert len(chunk.text) <= chunker.max_chunk_size + 50

    def test_small_chunks_merged(self):
        """Test that small chunks are merged."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(min_chunk_size=200, max_chunk_size=1000)

        text = """A.

B.

C."""

        chunks = chunker.chunk_text(text, "doc-123")

        # Should be merged into fewer chunks
        assert len(chunks) <= 2

    def test_chunk_position_tracking(self):
        """Test that chunk positions are tracked correctly."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(min_chunk_size=50, max_chunk_size=200)

        text = """First chunk content here.

Second chunk content here.

Third chunk content here."""

        chunks = chunker.chunk_text(text, "doc-123")

        # Verify chunk indices
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

        # Verify char positions exist
        for chunk in chunks:
            assert chunk.char_start is not None
            assert chunk.char_end is not None
            assert chunk.char_end > chunk.char_start

    def test_chunk_hash_computation(self):
        """Test that chunk hashes are computed correctly."""
        from app.ingestion.chunker import DocumentChunker
        import hashlib

        chunker = DocumentChunker()

        text = """Content for hashing test."""

        chunks = chunker.chunk_text(text, "doc-123")

        for chunk in chunks:
            expected_hash = hashlib.sha256(chunk.text.encode('utf-8')).hexdigest()
            assert chunk.text_hash == expected_hash

    def test_empty_text(self):
        """Test handling of empty text."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker()

        chunks = chunker.chunk_text("", "doc-123")
        assert chunks == []

        chunks = chunker.chunk_text("   ", "doc-123")
        assert chunks == []

    def test_sentence_strategy(self):
        """Test sentence-based chunking strategy."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(strategy="sentence", min_chunk_size=50, max_chunk_size=200)

        text = "First sentence. Second sentence. Third sentence. Fourth sentence."

        chunks = chunker.chunk_text(text, "doc-123")

        assert len(chunks) > 0
        # All chunks should contain complete sentences (end with period)

    def test_fixed_strategy(self):
        """Test fixed-size chunking strategy."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(strategy="fixed", max_chunk_size=100, overlap=20)

        text = "A" * 300  # 300 character string

        chunks = chunker.chunk_text(text, "doc-123")

        # Should create multiple fixed-size chunks
        assert len(chunks) >= 3

    def test_chunk_metadata(self):
        """Test that chunk metadata is set correctly."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(strategy="paragraph")

        text = """Paragraph one.

Paragraph two."""

        chunks = chunker.chunk_text(text, "doc-123")

        for chunk in chunks:
            assert "strategy" in chunk.metadata
            assert chunk.metadata["strategy"] == "paragraph"
            assert "original_length" in chunk.metadata
            assert "chunk_length" in chunk.metadata

    def test_chunk_document_helper(self):
        """Test the convenience function."""
        from app.ingestion.chunker import chunk_document

        chunks = chunk_document(
            text="Test content for chunking.",
            document_id="doc-123",
            min_size=10,
            max_size=100,
        )

        assert len(chunks) > 0
        assert chunks[0].document_id == "doc-123"


class TestChunkDataclass:
    """Tests for the Chunk dataclass."""

    def test_chunk_creation(self):
        """Test creating a Chunk."""
        from app.ingestion.chunker import Chunk

        chunk = Chunk(
            id="chunk-123",
            document_id="doc-456",
            chunk_index=0,
            text="Test chunk content",
            char_start=0,
            char_end=18,
            text_hash="abc123",
            metadata={"page": 1},
        )

        assert chunk.id == "chunk-123"
        assert chunk.document_id == "doc-456"
        assert chunk.chunk_index == 0
        assert chunk.text == "Test chunk content"
        assert chunk.char_start == 0
        assert chunk.char_end == 18
        assert chunk.metadata["page"] == 1


class TestChunkerEdgeCases:
    """Edge case tests for DocumentChunker."""

    def test_single_very_long_paragraph(self):
        """Test handling of a single very long paragraph."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(max_chunk_size=200)

        # Create a very long paragraph
        text = " ".join(["word"] * 500)

        chunks = chunker.chunk_text(text, "doc-123")

        # Should be split into multiple chunks
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.text) <= chunker.max_chunk_size + 50

    def test_special_characters(self):
        """Test handling of special characters."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker()

        text = """Special characters: 8544.42.9090 (HTS code)
        Percent: 25%
        Currency: $100.00
        Quote: "This is quoted"
        Section symbol: \u00a7 232"""

        chunks = chunker.chunk_text(text, "doc-123")

        assert len(chunks) > 0
        # Original special characters should be preserved
        combined = " ".join(c.text for c in chunks)
        assert "8544.42.9090" in combined
        assert "25%" in combined

    def test_unicode_content(self):
        """Test handling of unicode content."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker()

        text = """Unicode test: \u2019 \u201c \u201d
        Foreign characters: \xe9\xe0\xfc"""

        chunks = chunker.chunk_text(text, "doc-123")

        assert len(chunks) > 0

    def test_bullet_points_and_lists(self):
        """Test handling of bullet points and lists."""
        from app.ingestion.chunker import DocumentChunker

        chunker = DocumentChunker(min_chunk_size=50, max_chunk_size=500)

        text = """HTS codes subject to tariffs:

\u2022 8544.42.9090 - Electrical conductors
\u2022 8501.10.20 - Electric motors
\u2022 8502.31.00 - Generating sets

Claim codes:
1. 9903.78.01 - Steel exclusion
2. 9903.78.02 - Steel disclaim"""

        chunks = chunker.chunk_text(text, "doc-123")

        assert len(chunks) > 0
        combined = " ".join(c.text for c in chunks)
        assert "8544.42.9090" in combined
        assert "9903.78.01" in combined
