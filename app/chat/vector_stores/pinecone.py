import os
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from app.chat.embeddings.openai import embeddings

# Lazy-init Pinecone: defer API calls until first use so that
# DB-only tests and app startup don't fail when Pinecone/network
# is unavailable.
_pc = None
_index = None
_vector_store = None


def _get_vector_store():
    """Lazily initialize Pinecone client, index, and vector store."""
    global _pc, _index, _vector_store
    if _vector_store is None:
        _pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))
        index_name = os.getenv("PINECONE_INDEX_NAME", "docs")
        _index = _pc.Index(index_name)
        _vector_store = PineconeVectorStore(
            index=_index,
            embedding=embeddings,
            text_key="text"
        )
    return _vector_store


def build_retriever(chat_args, k):
    """
    Build a retriever based on the conversation mode.

    For mode="user_pdf" (default): filters by single pdf_id
    For mode="multi_doc": uses scope_filter from conversation
    """
    vs = _get_vector_store()

    # Check if we're in multi_doc mode
    mode = getattr(chat_args, 'mode', 'user_pdf')
    scope_filter = getattr(chat_args, 'scope_filter', None)

    if mode == "multi_doc" and scope_filter:
        # Multi-doc mode: use the scope_filter directly
        search_kwargs = {
            "filter": scope_filter,
            "k": k
        }
    else:
        # Default single-doc mode: filter by pdf_id
        search_kwargs = {
            "filter": {"pdf_id": chat_args.pdf_id},
            "k": k
        }

    return vs.as_retriever(
        search_kwargs=search_kwargs
    )


def build_multi_doc_retriever(scope_filter: dict, k: int = 5):
    """
    Build a retriever for multi-doc queries.

    Args:
        scope_filter: Pinecone filter dict, e.g.:
            {"corpus": "gov_trade"}
            {"pdf_id": {"$in": ["id1", "id2", "id3"]}}
        k: Number of chunks to retrieve
    """
    vs = _get_vector_store()
    search_kwargs = {
        "filter": scope_filter,
        "k": k
    }
    return vs.as_retriever(
        search_kwargs=search_kwargs
    )
