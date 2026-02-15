from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.chat.vector_stores.pinecone import _get_vector_store


def create_embeddings_for_pdf(
    pdf_id: str,
    pdf_path: str,
    corpus: str = None,
    doc_type: str = None
):
    """
    Create embeddings for a PDF and store in Pinecone.

    Args:
        pdf_id: Unique identifier for the PDF
        pdf_path: Path to the PDF file
        corpus: Optional corpus tag for multi-doc retrieval (e.g., "gov_trade")
        doc_type: Optional document type (e.g., "hts_schedule", "regulation")
    """
    # Larger chunks = fewer vectors = faster queries & lower cost
    # 1200 chars ~ 300 tokens, good balance for dense legal/trade docs
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200
    )

    loader = PyPDFLoader(pdf_path)
    docs = loader.load_and_split(text_splitter)

    for doc in docs:
        # Build metadata with new fields for multi-doc support
        metadata = {
            "page": doc.metadata["page"],
            "text": doc.page_content,
            "pdf_id": pdf_id
        }

        # Add optional corpus and doc_type for multi-doc filtering
        if corpus:
            metadata["corpus"] = corpus
        if doc_type:
            metadata["doc_type"] = doc_type

        doc.metadata = metadata

    _get_vector_store().add_documents(docs)
