import os
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore
from app.chat.embeddings.openai import embeddings

# Initialize Pinecone v5+ client
pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))

# Get the index
index_name = os.getenv("PINECONE_INDEX_NAME", "docs")
index = pc.Index(index_name)

# Create vector store using langchain-pinecone
vector_store = PineconeVectorStore(
    index=index,
    embedding=embeddings,
    text_key="text"
)


def build_retriever(chat_args, k):
    """
    Build a retriever based on the conversation mode.

    For mode="user_pdf" (default): filters by single pdf_id
    For mode="multi_doc": uses scope_filter from conversation
    """
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

    return vector_store.as_retriever(
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
    search_kwargs = {
        "filter": scope_filter,
        "k": k
    }
    return vector_store.as_retriever(
        search_kwargs=search_kwargs
    )