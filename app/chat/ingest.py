"""
Smart PDF ingestion with junk filtering and progress tracking.

Features:
- Filters out junk pages (TOC, blank, index)
- Larger chunks for fewer vectors
- Auto-detects doc_type from filename
- Progress callbacks for UI feedback
"""
import os
from typing import Callable, List, Optional
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.chat.vector_stores.pinecone import _get_vector_store


# ============================================================================
# Junk Page Detection
# ============================================================================

def should_skip_page(text: str) -> bool:
    """
    Detect junk pages that should be skipped during ingestion.

    Skips:
    - Very short pages (< 100 chars)
    - Table of contents
    - Blank page notices
    - Index pages at end of document
    """
    text_lower = text.lower().strip()

    # Too short to be useful
    if len(text) < 100:
        return True

    # Table of contents (usually at start)
    if "table of contents" in text_lower[:300]:
        return True

    # Blank page notices
    if "this page intentionally" in text_lower:
        return True

    # Index pages (often at end, short and start with "Index")
    if text_lower.startswith("index") and len(text) < 500:
        return True

    # Common header-only pages
    if len(text) < 200 and ("chapter" in text_lower or "section" in text_lower):
        return True

    return False


# ============================================================================
# Document Type Inference
# ============================================================================

def infer_doc_type(filename: str) -> str:
    """
    Infer document type from filename for metadata tagging.

    Returns one of:
    - hts_schedule: HTS tariff schedule chapters
    - section301_tariff: Section 301 tariff lists
    - cbp_guide: CBP import guides
    - gov_publication: Government publications
    - agency_regulation: FDA, FCC, DOE regulations
    - general: Unknown type
    """
    name = filename.lower()

    if "chapter 85" in name or "hts" in name or "tariff schedule" in name:
        return "hts_schedule"
    elif "tariff" in name or "301" in name or "list" in name:
        return "section301_tariff"
    elif "import" in name or "cbp" in name:
        return "cbp_guide"
    elif "govpub" in name or "gov" in name:
        return "gov_publication"
    elif "fda" in name:
        return "agency_regulation"
    elif "fcc" in name:
        return "agency_regulation"
    elif "doe" in name or "energy" in name:
        return "agency_regulation"
    else:
        return "general"


# ============================================================================
# PDF Ingestion
# ============================================================================

def ingest_pdf(
    pdf_path: str,
    corpus: str = "trade_compliance",
    doc_type: Optional[str] = None,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
    progress_callback: Optional[Callable[[str], None]] = None
) -> dict:
    """
    Ingest a PDF with smart filtering and chunking.

    Args:
        pdf_path: Path to the PDF file
        corpus: Corpus tag for grouping documents
        doc_type: Document type (auto-inferred if None)
        chunk_size: Size of text chunks in characters
        chunk_overlap: Overlap between chunks
        progress_callback: Optional callback for progress updates

    Returns:
        dict with stats: {filename, pdf_id, doc_type, pages, chunks, skipped}
    """
    filename = os.path.basename(pdf_path)
    # Create a clean pdf_id from filename
    pdf_id = filename.replace(".pdf", "").replace(" ", "_").replace("-", "_")[:50]

    if doc_type is None:
        doc_type = infer_doc_type(filename)

    def log(msg: str):
        if progress_callback:
            progress_callback(msg)

    log(f"Loading {filename}...")

    # Load PDF
    try:
        loader = PyPDFLoader(pdf_path)
        pages = loader.load()
    except Exception as e:
        log(f"Error loading {filename}: {str(e)}")
        raise

    total_pages = len(pages)
    log(f"Loaded {total_pages} pages, filtering junk...")

    # Filter junk pages
    filtered_pages = [p for p in pages if not should_skip_page(p.page_content)]
    skipped = total_pages - len(filtered_pages)

    log(f"Kept {len(filtered_pages)} pages (skipped {skipped} junk pages)")

    if len(filtered_pages) == 0:
        log(f"Warning: No usable pages in {filename}")
        return {
            "filename": filename,
            "pdf_id": pdf_id,
            "doc_type": doc_type,
            "pages": total_pages,
            "chunks": 0,
            "skipped": skipped
        }

    # Chunk the documents
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_documents(filtered_pages)

    log(f"Created {len(chunks)} chunks, embedding and uploading...")

    # Add metadata to each chunk
    for chunk in chunks:
        chunk.metadata["corpus"] = corpus
        chunk.metadata["doc_type"] = doc_type
        chunk.metadata["pdf_id"] = pdf_id
        chunk.metadata["source_file"] = filename
        # Keep original page number if present
        if "page" not in chunk.metadata:
            chunk.metadata["page"] = 0

    # Upsert to Pinecone
    try:
        _get_vector_store().add_documents(chunks)
    except Exception as e:
        log(f"Error uploading to Pinecone: {str(e)}")
        raise

    log(f"✓ Ingested {filename}: {len(chunks)} chunks ({doc_type})")

    return {
        "filename": filename,
        "pdf_id": pdf_id,
        "doc_type": doc_type,
        "pages": total_pages,
        "chunks": len(chunks),
        "skipped": skipped
    }


def ingest_multiple_pdfs(
    pdf_paths: List[str],
    corpus: str = "trade_compliance",
    progress_callback: Optional[Callable[[str], None]] = None
) -> List[dict]:
    """
    Ingest multiple PDFs with progress tracking.

    Args:
        pdf_paths: List of paths to PDF files
        corpus: Corpus tag for all documents
        progress_callback: Optional callback for progress updates

    Returns:
        List of result dicts from ingest_pdf
    """
    results = []
    total = len(pdf_paths)

    def log(msg: str):
        if progress_callback:
            progress_callback(msg)

    log(f"Starting ingestion of {total} files...")

    for i, path in enumerate(pdf_paths):
        log(f"\n--- Processing file {i+1}/{total} ---")

        try:
            result = ingest_pdf(
                path,
                corpus=corpus,
                progress_callback=progress_callback
            )
            results.append(result)
        except Exception as e:
            log(f"Error processing {path}: {str(e)}")
            results.append({
                "filename": os.path.basename(path),
                "error": str(e)
            })

    # Summary
    total_chunks = sum(r.get("chunks", 0) for r in results)
    total_pages = sum(r.get("pages", 0) for r in results)
    log(f"\n=== Ingestion Complete ===")
    log(f"Files: {len(results)}")
    log(f"Total pages: {total_pages}")
    log(f"Total chunks: {total_chunks}")

    return results


def format_results_markdown(results: List[dict]) -> str:
    """Format ingestion results as markdown for display."""
    lines = ["### Loaded Documents\n"]

    total_chunks = 0
    for r in results:
        if "error" in r:
            lines.append(f"- **{r['filename']}** - Error: {r['error']}")
        else:
            chunks = r.get("chunks", 0)
            doc_type = r.get("doc_type", "unknown")
            pages = r.get("pages", 0)
            skipped = r.get("skipped", 0)
            total_chunks += chunks
            lines.append(
                f"- **{r['filename']}** (`{doc_type}`) - "
                f"{chunks} chunks from {pages} pages (skipped {skipped})"
            )

    lines.append(f"\n**Total: {total_chunks} chunks indexed**")

    return "\n".join(lines)
