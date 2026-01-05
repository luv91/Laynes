"""
Tariff Vector Search Service (v9.0 → v9.3)

Provides vector-based caching for Gemini search results and grounding sources.
Uses Pinecone for semantic similarity search to avoid redundant API calls.

This service:
1. Indexes Gemini responses and grounding source content in Pinecone
2. Performs semantic search before calling Gemini
3. Chunks long text into manageable pieces for embedding
4. v9.3: Indexes evidence quotes as high-signal chunks

Part of the 3-tier cache architecture:
- Layer 1: PostgreSQL (exact match on HTS code)
- Layer 2: Pinecone (semantic match on similar queries)  <-- This file
- Layer 3: Gemini (live search when no cache hit)

v9.3 Update: Evidence Quote Vector Indexing
- Each quoted_text from citations[] becomes a dedicated vector
- Metadata includes in_scope, claim_code, material for filtering
- chunk_type="evidence_quote" distinguishes from raw response chunks
"""

import hashlib
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pinecone import Pinecone as PineconeClient
from openai import OpenAI

# Configuration
PINECONE_INDEX_NAME = os.getenv("PINECONE_TARIFF_INDEX", "lanes-tariff-search")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
CHUNK_SIZE = 500  # Max tokens per chunk
CHUNK_OVERLAP = 50  # Token overlap between chunks


class TariffVectorSearch:
    """
    Vector search for tariff documents and Gemini search results.

    Provides semantic caching layer to avoid redundant Gemini searches.
    When a similar query has been performed before, retrieves cached
    chunks instead of calling the expensive API.
    """

    def __init__(self):
        """Initialize Pinecone and OpenAI clients."""
        self.pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Get or create index
        try:
            self.index = self.pc.Index(PINECONE_INDEX_NAME)
        except Exception:
            # Index may not exist yet - will be created on first upsert
            self.index = None

    def _ensure_index(self):
        """Ensure the Pinecone index exists."""
        if self.index is None:
            # Check if index exists
            existing = [idx.name for idx in self.pc.list_indexes()]
            if PINECONE_INDEX_NAME not in existing:
                # Create with correct dimensions for text-embedding-3-small
                self.pc.create_index(
                    name=PINECONE_INDEX_NAME,
                    dimension=EMBEDDING_DIMENSION,
                    metric="cosine",
                    spec={"serverless": {"cloud": "aws", "region": "us-east-1"}}
                )
            self.index = self.pc.Index(PINECONE_INDEX_NAME)

    def _split_into_chunks(self, text: str, max_chars: int = 2000) -> List[str]:
        """
        Split text into chunks by paragraphs or fixed size.

        Uses paragraph breaks where possible, falls back to
        sentence/character splitting for long paragraphs.

        Args:
            text: Full text to chunk
            max_chars: Maximum characters per chunk

        Returns:
            List of text chunks
        """
        if not text:
            return []

        # Split by double newlines first (paragraphs)
        paragraphs = re.split(r'\n\n+', text.strip())
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # If adding this paragraph exceeds max, save current and start new
            if len(current_chunk) + len(para) + 2 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # If single paragraph is too long, split by sentences
                if len(para) > max_chars:
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) + 1 > max_chars:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            # If single sentence is still too long, hard split
                            if len(sent) > max_chars:
                                for i in range(0, len(sent), max_chars - CHUNK_OVERLAP):
                                    chunks.append(sent[i:i + max_chars].strip())
                                current_chunk = ""
                            else:
                                current_chunk = sent
                        else:
                            current_chunk = current_chunk + " " + sent if current_chunk else sent
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _create_embedding(self, text: str) -> List[float]:
        """Create embedding for a single text chunk."""
        response = self.openai.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding

    def chunk_and_embed(self, text: str, metadata: Dict[str, Any]) -> List[Dict]:
        """
        Chunk text and create embeddings for Pinecone.

        Args:
            text: Full text to chunk (e.g., Gemini response + source content)
            metadata: Metadata to attach (hts_code, source_url, etc.)

        Returns:
            List of dicts ready for Pinecone upsert with id, values, metadata
        """
        chunks = self._split_into_chunks(text)

        vectors = []
        for i, chunk in enumerate(chunks):
            # Generate embedding
            embedding = self._create_embedding(chunk)

            # Create unique ID based on content
            chunk_id = hashlib.sha256(
                f"{metadata.get('hts_code', 'unknown')}:{i}:{chunk[:50]}".encode()
            ).hexdigest()[:32]

            vectors.append({
                "id": chunk_id,
                "values": embedding,
                "metadata": {
                    **metadata,
                    "chunk_index": i,
                    "chunk_text": chunk[:1000],  # Store truncated for retrieval
                    "indexed_at": datetime.utcnow().isoformat()
                }
            })

        return vectors

    def search_similar(
        self,
        query: str,
        hts_code: Optional[str] = None,
        query_type: Optional[str] = None,
        chunk_type: Optional[str] = None,
        material: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict]:
        """
        Search for similar content in vector store.

        Returns cached chunks that may answer the query without Gemini.

        Args:
            query: The search query (e.g., "Section 232 steel for HTS 8544.42.9090")
            hts_code: Optional filter by HTS code
            query_type: Optional filter by query type ('section_232', 'section_301')
            chunk_type: v9.3 - Optional filter by chunk type ('evidence_quote', 'gemini_response')
            material: v9.3 - Optional filter by material ('copper', 'steel', 'aluminum')
            top_k: Number of results to return

        Returns:
            List of matches with scores and metadata
        """
        self._ensure_index()

        # Create query embedding
        query_embedding = self._create_embedding(query)

        # Build filter
        filter_dict = {}
        if hts_code:
            filter_dict["hts_code"] = hts_code
        if query_type:
            filter_dict["query_type"] = query_type
        if chunk_type:
            filter_dict["chunk_type"] = chunk_type
        if material:
            filter_dict["material"] = material

        # Query Pinecone
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            filter=filter_dict if filter_dict else None
        )

        return [
            {
                "id": match.id,
                "score": match.score,
                "metadata": match.metadata
            }
            for match in results.matches
        ]

    def index_search_result(
        self,
        search_result_id: str,
        hts_code: str,
        query_type: str,
        material: Optional[str],
        raw_response: str,
        model_used: str,
        grounding_sources: Optional[List[Dict]] = None
    ) -> int:
        """
        Index a Gemini search result and its grounding sources.

        Called after every successful Gemini search to build cache.

        Args:
            search_result_id: UUID of the GeminiSearchResult record
            hts_code: The HTS code that was searched
            query_type: Type of query ('section_232', 'section_301', etc.)
            material: Material type if applicable ('copper', 'steel', 'aluminum')
            raw_response: The raw text response from Gemini
            model_used: Which model was used
            grounding_sources: List of grounding source dicts with url, fetched_content

        Returns:
            Number of vectors upserted
        """
        self._ensure_index()

        vectors = []

        # 1. Index the Gemini response itself
        if raw_response:
            response_metadata = {
                "search_result_id": search_result_id,
                "hts_code": hts_code,
                "query_type": query_type,
                "material": material,
                "source_type": "gemini_response",
                "model_used": model_used
            }
            vectors.extend(self.chunk_and_embed(raw_response, response_metadata))

        # 2. Index each grounding source (if content was fetched)
        if grounding_sources:
            for source in grounding_sources:
                content = source.get("fetched_content")
                if content:
                    # Extract domain from URL
                    url = source.get("url", "")
                    domain = urlparse(url).netloc if url else None

                    source_metadata = {
                        "search_result_id": search_result_id,
                        "hts_code": hts_code,
                        "query_type": query_type,
                        "material": material,
                        "source_type": "grounding_source",
                        "source_url": url,
                        "domain": domain
                    }
                    vectors.extend(self.chunk_and_embed(content, source_metadata))

        # Upsert to Pinecone (in batches of 100)
        if vectors:
            for i in range(0, len(vectors), 100):
                batch = vectors[i:i + 100]
                self.index.upsert(vectors=batch)

        return len(vectors)

    def delete_by_search_result(self, search_result_id: str) -> bool:
        """
        Delete all vectors associated with a search result.

        Used when force_search replaces a cached result.

        Args:
            search_result_id: UUID of the GeminiSearchResult to delete

        Returns:
            True if deletion was successful
        """
        self._ensure_index()

        try:
            # Delete by metadata filter
            self.index.delete(
                filter={"search_result_id": search_result_id}
            )
            return True
        except Exception:
            return False

    def index_evidence_quotes(
        self,
        search_result_id: str,
        hts_code: str,
        query_type: str,
        result_json: Dict,
        grounding_urls: List[str]
    ) -> int:
        """
        Index evidence quotes from v9.2 citations as high-signal chunks.

        v9.3: Each quoted_text becomes a dedicated vector with rich metadata.
        Unlike raw response chunking, these are normalized and already
        contain the exact evidence for each claim.

        Args:
            search_result_id: UUID of the GeminiSearchResult record
            hts_code: The HTS code that was searched
            query_type: Type of query ('section_232', 'section_301', etc.)
            result_json: Parsed JSON result in v9.2 format
            grounding_urls: List of grounding source URLs

        Returns:
            Number of quote vectors indexed
        """
        self._ensure_index()
        vectors = []

        # Parse v2 structure: results.{metal}.citations[]
        results = result_json.get("results", {})
        if not results:
            return 0

        grounding_url_set = set(grounding_urls)

        for metal, scope_data in results.items():
            if not isinstance(scope_data, dict):
                continue

            in_scope = scope_data.get("in_scope")
            claim_code = scope_data.get("claim_code")
            disclaim_code = scope_data.get("disclaim_code")
            citations = scope_data.get("citations", [])

            for citation in citations:
                if not isinstance(citation, dict):
                    continue

                quoted_text = citation.get("quoted_text")
                if not quoted_text:
                    continue  # Skip citations without quotes

                source_url = citation.get("source_url", "")
                domain = extract_domain(source_url) if source_url else None
                source_type = classify_source_type(domain) if domain else "other"
                reliability = get_reliability_score(source_type)

                # Check if URL was in Google's grounding metadata
                url_in_grounding = source_url in grounding_url_set if source_url else False

                # Create embedding for the quote
                embedding = self._create_embedding(quoted_text)

                # Unique ID based on content hash
                quote_hash = hashlib.sha256(quoted_text.encode()).hexdigest()[:16]
                chunk_id = f"eq_{hts_code.replace('.', '')}_{metal}_{quote_hash}"

                # Build metadata dict, filtering out None values
                # (Pinecone rejects null metadata values)
                metadata = {
                    # Core identifiers (always present)
                    "chunk_type": "evidence_quote",
                    "search_result_id": search_result_id,
                    "hts_code": hts_code,
                    "query_type": query_type,
                    "material": metal,

                    # Source data
                    "source_url": source_url or "",
                    "reliability_score": reliability,

                    # Trust signals
                    "url_in_grounding_metadata": url_in_grounding,
                    "quote_verified": False,

                    # The actual content
                    "chunk_text": quoted_text,
                    "indexed_at": datetime.utcnow().isoformat()
                }

                # Add optional fields only if they have values
                if in_scope is not None:
                    metadata["in_scope"] = in_scope
                if claim_code:
                    metadata["claim_code"] = claim_code
                if disclaim_code:
                    metadata["disclaim_code"] = disclaim_code
                if domain:
                    metadata["source_domain"] = domain
                if citation.get("source_document"):
                    metadata["source_document"] = citation.get("source_document")
                if citation.get("evidence_type"):
                    metadata["evidence_type"] = citation.get("evidence_type")

                vectors.append({
                    "id": chunk_id,
                    "values": embedding,
                    "metadata": metadata
                })

        # Upsert to Pinecone (in batches of 100)
        if vectors:
            for i in range(0, len(vectors), 100):
                batch = vectors[i:i + 100]
                self.index.upsert(vectors=batch)

        return len(vectors)


def extract_domain(url: str) -> Optional[str]:
    """Extract domain from URL for reliability classification."""
    try:
        parsed = urlparse(url)
        return parsed.netloc
    except Exception:
        return None


def classify_source_type(domain: str) -> str:
    """Classify source reliability based on domain."""
    if not domain:
        return "other"

    official_domains = {
        "cbp.gov": "official_cbp",
        "www.cbp.gov": "official_cbp",
        "federalregister.gov": "federal_register",
        "www.federalregister.gov": "federal_register",
        "ustr.gov": "ustr",
        "www.ustr.gov": "ustr",
        "usitc.gov": "usitc",
        "hts.usitc.gov": "usitc",
    }

    return official_domains.get(domain.lower(), "other")


def get_reliability_score(source_type: str) -> float:
    """Get reliability score for a source type."""
    scores = {
        "official_cbp": 1.0,
        "federal_register": 1.0,
        "ustr": 0.95,
        "usitc": 0.95,
        "csms": 0.90,
        "other": 0.50
    }
    return scores.get(source_type, 0.50)
