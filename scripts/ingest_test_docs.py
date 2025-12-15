"""
Script to ingest test documents with corpus metadata.

This script:
1. Creates sample PDF entries in the database with corpus tags
2. Ingests the documents into Pinecone with proper metadata

Usage:
    cd lanes
    pipenv shell
    python scripts/ingest_test_docs.py

For testing without real PDFs, use --mock flag:
    python scripts/ingest_test_docs.py --mock
"""

import os
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def create_mock_documents():
    """Create mock documents for testing without real PDFs."""
    # Import directly to avoid circular imports
    import os
    from pinecone import Pinecone as PineconeClient
    from langchain_pinecone import PineconeVectorStore
    from langchain_openai import OpenAIEmbeddings
    from langchain_core.documents import Document

    # Initialize vector store directly
    pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "docs"))
    embeddings = OpenAIEmbeddings()
    vector_store = PineconeVectorStore(index=index, embedding=embeddings, text_key="text")

    print("Creating mock documents for testing...")

    # Mock documents representing different doc types
    mock_docs = [
        # HTS Schedule documents
        Document(
            page_content="8539.50.00 - Light-emitting diode (LED) lamps. General duty rate: 3.9%. These are electrical lamps that use LED technology for illumination.",
            metadata={
                "pdf_id": "mock-hts-001",
                "page": 1,
                "text": "8539.50.00 - Light-emitting diode (LED) lamps...",
                "corpus": "test_corpus",
                "doc_type": "hts_schedule"
            }
        ),
        Document(
            page_content="8539.52.00 - LED modules for lighting. Used in various lighting applications. Duty rate: 3.9%.",
            metadata={
                "pdf_id": "mock-hts-001",
                "page": 2,
                "text": "8539.52.00 - LED modules for lighting...",
                "corpus": "test_corpus",
                "doc_type": "hts_schedule"
            }
        ),
        Document(
            page_content="8471.30.00 - Portable automatic data processing machines (laptops). General duty rate: Free.",
            metadata={
                "pdf_id": "mock-hts-001",
                "page": 10,
                "text": "8471.30.00 - Portable automatic data processing machines...",
                "corpus": "test_corpus",
                "doc_type": "hts_schedule"
            }
        ),

        # Tariff documents
        Document(
            page_content="Section 301 List 3: Products of China subject to additional 25% tariff. Includes HTS codes starting with 8539 (lamps and lighting).",
            metadata={
                "pdf_id": "mock-tariff-001",
                "page": 1,
                "text": "Section 301 List 3: Products of China...",
                "corpus": "test_corpus",
                "doc_type": "tariff_notice"
            }
        ),
        Document(
            page_content="Section 301 exclusions: Certain LED products may be excluded from additional tariffs if they meet specific criteria.",
            metadata={
                "pdf_id": "mock-tariff-001",
                "page": 5,
                "text": "Section 301 exclusions...",
                "corpus": "test_corpus",
                "doc_type": "tariff_notice"
            }
        ),

        # Agency regulation documents
        Document(
            page_content="FDA Prior Notice: All food products imported into the US require prior notice submission. This applies to HTS chapters 02-21.",
            metadata={
                "pdf_id": "mock-fda-001",
                "page": 1,
                "text": "FDA Prior Notice: All food products...",
                "corpus": "test_corpus",
                "doc_type": "agency_regulation"
            }
        ),
        Document(
            page_content="DOE Energy Efficiency Requirements: LED lamps must meet energy efficiency standards. Certificate of compliance required.",
            metadata={
                "pdf_id": "mock-doe-001",
                "page": 1,
                "text": "DOE Energy Efficiency Requirements...",
                "corpus": "test_corpus",
                "doc_type": "agency_regulation"
            }
        ),
        Document(
            page_content="FCC Part 15: Electronic devices must comply with FCC regulations. LED lighting with electronic components requires FCC Declaration of Conformity.",
            metadata={
                "pdf_id": "mock-fcc-001",
                "page": 1,
                "text": "FCC Part 15: Electronic devices...",
                "corpus": "test_corpus",
                "doc_type": "agency_regulation"
            }
        ),
    ]

    print(f"Adding {len(mock_docs)} mock documents to Pinecone...")
    vector_store.add_documents(mock_docs)
    print("Done! Mock documents added to Pinecone with corpus='test_corpus'")

    return mock_docs


def create_db_entries():
    """Create database entries for the mock PDFs."""
    print("\nCreating database entries for mock PDFs...")

    # This requires Flask app context
    from flask import Flask
    from app.web.db import db
    from app.web.db.models import Pdf

    # Create a minimal Flask app for database operations
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'SQLALCHEMY_DATABASE_URI',
        'sqlite:///instance/sqlite.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        # Check if tables have new columns (migration check)
        try:
            # Create entries for mock documents
            mock_pdfs = [
                {
                    "id": "mock-hts-001",
                    "name": "HTS Schedule Chapter 85.pdf",
                    "corpus": "test_corpus",
                    "doc_type": "hts_schedule",
                    "is_system": True,
                    "user_id": None
                },
                {
                    "id": "mock-tariff-001",
                    "name": "Section 301 Tariffs.pdf",
                    "corpus": "test_corpus",
                    "doc_type": "tariff_notice",
                    "is_system": True,
                    "user_id": None
                },
                {
                    "id": "mock-fda-001",
                    "name": "FDA Import Requirements.pdf",
                    "corpus": "test_corpus",
                    "doc_type": "agency_regulation",
                    "is_system": True,
                    "user_id": None
                },
                {
                    "id": "mock-doe-001",
                    "name": "DOE Energy Efficiency.pdf",
                    "corpus": "test_corpus",
                    "doc_type": "agency_regulation",
                    "is_system": True,
                    "user_id": None
                },
                {
                    "id": "mock-fcc-001",
                    "name": "FCC Part 15 Requirements.pdf",
                    "corpus": "test_corpus",
                    "doc_type": "agency_regulation",
                    "is_system": True,
                    "user_id": None
                },
            ]

            for pdf_data in mock_pdfs:
                existing = Pdf.query.filter_by(id=pdf_data["id"]).first()
                if not existing:
                    pdf = Pdf(**pdf_data)
                    db.session.add(pdf)
                    print(f"  Created: {pdf_data['name']}")
                else:
                    print(f"  Already exists: {pdf_data['name']}")

            db.session.commit()
            print("Database entries created successfully!")

        except Exception as e:
            print(f"Error creating database entries: {e}")
            print("You may need to run database migration first.")
            print("Run: flask --app app.web init-db")


def ingest_real_pdf(pdf_path: str, pdf_id: str, corpus: str, doc_type: str):
    """Ingest a real PDF file with corpus metadata."""
    from app.chat.create_embeddings import create_embeddings_for_pdf

    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return False

    print(f"Ingesting: {pdf_path}")
    print(f"  pdf_id: {pdf_id}")
    print(f"  corpus: {corpus}")
    print(f"  doc_type: {doc_type}")

    create_embeddings_for_pdf(
        pdf_id=pdf_id,
        pdf_path=pdf_path,
        corpus=corpus,
        doc_type=doc_type
    )

    print("Done!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Ingest test documents for multi-doc RAG"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock documents instead of real PDFs"
    )
    parser.add_argument(
        "--pdf",
        type=str,
        help="Path to PDF file to ingest"
    )
    parser.add_argument(
        "--corpus",
        type=str,
        default="test_corpus",
        help="Corpus tag for the document"
    )
    parser.add_argument(
        "--doc-type",
        type=str,
        default="document",
        help="Document type tag"
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database entry creation"
    )

    args = parser.parse_args()

    if args.mock:
        create_mock_documents()
        if not args.skip_db:
            create_db_entries()
    elif args.pdf:
        pdf_id = os.path.basename(args.pdf).replace(".pdf", "")
        ingest_real_pdf(args.pdf, pdf_id, args.corpus, args.doc_type)
    else:
        print("Please specify --mock for mock documents or --pdf <path> for real PDF")
        print("\nExamples:")
        print("  python scripts/ingest_test_docs.py --mock")
        print("  python scripts/ingest_test_docs.py --pdf /path/to/doc.pdf --corpus gov_trade --doc-type hts_schedule")


if __name__ == "__main__":
    main()
