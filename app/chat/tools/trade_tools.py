"""
Trade compliance tools for agentic RAG.

Provides tools for:
- Document search across corpus
- HTS code lookup
- Tariff checking
- Agency requirements lookup

All tools use Pinecone vector store for retrieval.
"""

import os
from typing import List, Optional

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore


# ============================================================================
# Vector Store Helper
# ============================================================================

# Global vector store reference (initialized lazily)
_vector_store = None


def get_vector_store():
    """Initialize and return the Pinecone vector store."""
    global _vector_store
    if _vector_store is None:
        pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))
        index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "docs"))
        embeddings = OpenAIEmbeddings()
        _vector_store = PineconeVectorStore(
            index=index,
            embedding=embeddings,
            text_key="text"
        )
    return _vector_store


def reset_vector_store():
    """Reset the global vector store (useful for testing)."""
    global _vector_store
    _vector_store = None


# ============================================================================
# Default Corpus Filter (excludes test/mock data)
# ============================================================================

DEFAULT_CORPUS = "trade_compliance"


# ============================================================================
# Trade Compliance Tools
# ============================================================================

@tool
def search_documents(query: str, doc_type: Optional[str] = None, max_results: int = 5) -> str:
    """
    Search across all documents in the corpus for relevant information.

    Args:
        query: The search query (what you're looking for)
        doc_type: Optional filter by document type (e.g., 'hts_schedule', 'regulation', 'tariff_notice')
        max_results: Maximum number of results to return (default: 5)

    Returns:
        Formatted string with search results including source document info.
    """
    vector_store = get_vector_store()

    # Build filter - ALWAYS include corpus to exclude test data
    search_filter = {"corpus": DEFAULT_CORPUS}
    if doc_type:
        search_filter["doc_type"] = doc_type

    search_kwargs = {"k": max_results, "filter": search_filter}

    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    docs = retriever.invoke(query)

    if not docs:
        return "No relevant documents found for this query."

    results = []
    for i, doc in enumerate(docs):
        pdf_id = doc.metadata.get('pdf_id', 'unknown')
        doc_type_found = doc.metadata.get('doc_type', 'document')
        page = doc.metadata.get('page', 'N/A')
        results.append(
            f"[Result {i+1}] Source: {pdf_id} (Type: {doc_type_found}, Page: {page})\n"
            f"{doc.page_content[:500]}..."
        )

    return "\n\n---\n\n".join(results)


@tool
def lookup_hts_code(product_description: str) -> str:
    """
    Look up the HTS (Harmonized Tariff Schedule) code for a product.

    Args:
        product_description: Description of the product to classify

    Returns:
        HTS code information if found.
    """
    vector_store = get_vector_store()

    # Search specifically in HTS documents within the corpus
    search_kwargs = {
        "k": 3,
        "filter": {"corpus": DEFAULT_CORPUS, "doc_type": "hts_schedule"}
    }

    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    docs = retriever.invoke(f"HTS code classification for {product_description}")

    if not docs:
        return f"No HTS code found for '{product_description}'. Consider using search_documents with a broader query."

    results = []
    for doc in docs:
        results.append(f"[{doc.metadata.get('pdf_id', 'HTS')}]: {doc.page_content}")

    return "\n\n".join(results)


@tool
def check_tariffs(hts_code: str, country_of_origin: str) -> str:
    """
    Check applicable tariffs for an HTS code from a specific country.

    Args:
        hts_code: The HTS code to look up tariffs for
        country_of_origin: The country of origin (e.g., 'China', 'Mexico')

    Returns:
        Tariff information including duty rates and special tariffs.
    """
    vector_store = get_vector_store()

    # Search in tariff documents within the corpus
    # Note: doc_type could be "section301_tariff" or "tariff_notice"
    search_kwargs = {
        "k": 5,
        "filter": {"corpus": DEFAULT_CORPUS}
    }

    query = f"tariff duty rate for HTS {hts_code} from {country_of_origin} section 301"
    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    docs = retriever.invoke(query)

    if not docs:
        return f"No specific tariff information found for HTS {hts_code} from {country_of_origin}."

    results = []
    for doc in docs:
        results.append(f"[{doc.metadata.get('pdf_id', 'Tariff')}]: {doc.page_content}")

    return "\n\n".join(results)


@tool
def check_agency_requirements(product_type: str, agencies: Optional[List[str]] = None) -> str:
    """
    Check regulatory agency requirements for importing a product.

    Args:
        product_type: Type of product (e.g., 'LED lamps', 'food products', 'electronics')
        agencies: Optional list of specific agencies to check (e.g., ['FDA', 'FCC', 'DOT'])

    Returns:
        Agency requirements and required documentation.
    """
    vector_store = get_vector_store()

    # Search in regulation documents within the corpus
    search_kwargs = {
        "k": 5,
        "filter": {"corpus": DEFAULT_CORPUS}
    }

    query = f"regulatory requirements for importing {product_type} CBP customs"
    if agencies:
        query += f" agencies: {', '.join(agencies)}"

    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    docs = retriever.invoke(query)

    if not docs:
        return f"No agency requirements found for '{product_type}'."

    results = []
    for doc in docs:
        results.append(f"[{doc.metadata.get('pdf_id', 'Agency')}]: {doc.page_content}")

    return "\n\n".join(results)


# ============================================================================
# Tool List for Agent Binding
# ============================================================================

TRADE_TOOLS = [
    search_documents,
    lookup_hts_code,
    check_tariffs,
    check_agency_requirements
]
