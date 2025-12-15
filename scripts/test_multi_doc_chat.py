"""
Test script for multi-document chat functionality with LangGraph.

This script tests:
1. Basic multi-doc retrieval
2. Conversation memory across messages
3. Source citations
4. Structured JSON output
5. Trade compliance output format

Usage:
    cd lanes
    pipenv shell
    python scripts/test_multi_doc_chat.py

Prerequisites:
    - Run ingest_test_docs.py --mock first
    - Pinecone configured with test_corpus documents
"""

import os
import sys
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def test_basic_retrieval():
    """Test basic multi-doc retrieval."""
    print("\n" + "="*60)
    print("TEST 1: Basic Multi-Doc Retrieval")
    print("="*60)

    from pinecone import Pinecone as PineconeClient
    from langchain_pinecone import PineconeVectorStore
    from langchain_openai import OpenAIEmbeddings

    pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "docs"))
    embeddings = OpenAIEmbeddings()
    vector_store = PineconeVectorStore(index=index, embedding=embeddings, text_key="text")

    # Build retriever with corpus filter
    scope_filter = {"corpus": "test_corpus"}
    retriever = vector_store.as_retriever(search_kwargs={"filter": scope_filter, "k": 5})

    query = "What is the HTS code for LED lamps?"
    print(f"\nQuery: {query}")
    print("-" * 40)

    docs = retriever.invoke(query)

    print(f"Retrieved {len(docs)} documents:")
    for i, doc in enumerate(docs):
        print(f"\n[{i+1}] Source: {doc.metadata.get('pdf_id', 'unknown')}")
        print(f"    Type: {doc.metadata.get('doc_type', 'unknown')}")
        print(f"    Content: {doc.page_content[:100]}...")

    pdf_ids = set(doc.metadata.get('pdf_id') for doc in docs)
    print(f"\nUnique sources: {len(pdf_ids)} - {pdf_ids}")

    if len(pdf_ids) > 1:
        print("✓ SUCCESS: Retrieved from multiple documents!")
    else:
        print("! NOTE: Only one document source found")


def test_conversational_memory():
    """Test conversation memory with LangGraph."""
    print("\n" + "="*60)
    print("TEST 2: Conversational Memory (LangGraph)")
    print("="*60)

    from app.chat import build_chat, ChatArgs
    from app.chat.models import Metadata

    # Use in-memory checkpointer for testing
    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-memory-001",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-memory-001",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_chat(chat_args)

    # Question 1
    print("\nQ1: What is the HTS code for LED lamps?")
    r1 = chat.invoke("What is the HTS code for LED lamps?")
    print(f"A1: {r1['answer']}")
    print(f"   Condensed: {r1['condensed_question']}")

    # Question 2 (follow-up - tests memory)
    print("\nQ2: What tariffs apply from China?")
    r2 = chat.invoke("What tariffs apply from China?")
    print(f"A2: {r2['answer']}")
    print(f"   Condensed: {r2['condensed_question']}")

    # Check if condensed question includes context
    if "LED" in r2['condensed_question'] or "lamp" in r2['condensed_question'].lower():
        print("\n✓ SUCCESS: Memory retained context from Q1!")
    else:
        print("\n! WARNING: Condensed question may not have full context")


def test_source_citations():
    """Test source citations in responses."""
    print("\n" + "="*60)
    print("TEST 3: Source Citations")
    print("="*60)

    from app.chat import build_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-citations-001",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-citations-001",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_chat(chat_args)

    print("\nQuery: What agencies regulate LED lamps?")
    result = chat.invoke("What agencies regulate LED lamps?")

    print(f"\nAnswer: {result['answer']}")
    print(f"\nCitations ({len(result['citations'])}):")
    for cite in result['citations']:
        print(f"  [{cite['index']}] {cite['pdf_id']} ({cite['doc_type']})")
        print(f"      Snippet: {cite['snippet'][:80]}...")

    if len(result['citations']) > 0:
        print("\n✓ SUCCESS: Citations included in response!")
    else:
        print("\n! WARNING: No citations returned")


def test_structured_output():
    """Test structured JSON output."""
    print("\n" + "="*60)
    print("TEST 4: Structured JSON Output")
    print("="*60)

    from app.chat import build_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-structured-001",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-structured-001",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_chat(chat_args, output_format="structured")

    print("\nQuery: What is the duty rate for LED lamps?")
    result = chat.invoke_structured("What is the duty rate for LED lamps?")

    print(f"\nAnswer: {result['answer']}")

    if result['structured_output']:
        print("\nStructured Output:")
        print(json.dumps(result['structured_output'], indent=2))

        if 'confidence' in result['structured_output']:
            print(f"\n✓ SUCCESS: Got structured output with confidence!")
        if 'follow_up_questions' in result['structured_output']:
            print(f"  Follow-up questions: {result['structured_output']['follow_up_questions']}")
    else:
        print("\n! WARNING: No structured output returned")


def test_trade_compliance_output():
    """Test trade compliance specialized output."""
    print("\n" + "="*60)
    print("TEST 5: Trade Compliance Output")
    print("="*60)

    from app.chat import build_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-trade-001",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-trade-001",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_chat(chat_args, output_format="trade_compliance")

    print("\nQuery: I want to import LED lamps from China. What do I need?")
    result = chat.invoke_trade_compliance("I want to import LED lamps from China. What do I need?")

    print(f"\nAnswer: {result['answer'][:300]}...")

    if result['structured_output']:
        so = result['structured_output']
        print("\n--- Trade Compliance Analysis ---")

        if 'hts_codes' in so:
            print(f"HTS Codes: {so['hts_codes']}")

        if 'agencies' in so:
            print(f"Agencies: {so['agencies']}")

        if 'required_documents' in so:
            print(f"Required Documents: {len(so['required_documents'])} items")
            for doc in so['required_documents'][:3]:
                print(f"  - {doc}")

        if 'tariff_info' in so and so['tariff_info']:
            print(f"Tariff Info: {so['tariff_info']}")

        if 'risk_flags' in so:
            print(f"Risk Flags: {so['risk_flags']}")

        print("\n✓ SUCCESS: Got trade compliance structured output!")
    else:
        print("\n! WARNING: No structured output returned")


def test_sqlite_persistence():
    """Test SQLite checkpointer persistence."""
    print("\n" + "="*60)
    print("TEST 6: SQLite Persistence")
    print("="*60)

    from app.chat import build_chat, ChatArgs
    from app.chat.models import Metadata

    # Enable SQLite checkpointer
    os.environ["USE_SQLITE_CHECKPOINTER"] = "true"
    os.environ["CHECKPOINTER_DB_PATH"] = "instance/test_checkpoints.db"

    # Reset global checkpointer
    import app.chat.chat as chat_module
    chat_module._global_checkpointer = None

    conversation_id = "test-persist-001"

    metadata = Metadata(
        conversation_id=conversation_id,
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id=conversation_id,
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    # First conversation
    chat1 = build_chat(chat_args)
    print("\nSession 1 - Q1: What is HTS code for LED?")
    r1 = chat1.invoke("What is HTS code for LED?")
    print(f"A1: {r1['answer'][:100]}...")

    # Simulate new session (rebuild chat with same conversation_id)
    chat_module._global_checkpointer = None  # Reset to force new connection
    chat2 = build_chat(chat_args)

    print("\nSession 2 - Q2: What about tariffs? (should have context)")
    r2 = chat2.invoke("What about tariffs?")
    print(f"A2: {r2['answer'][:100]}...")
    print(f"   Condensed: {r2['condensed_question']}")

    # Check if DB file exists
    if os.path.exists("instance/test_checkpoints.db"):
        print("\n✓ SUCCESS: SQLite checkpoint file created!")
        # Clean up
        os.remove("instance/test_checkpoints.db")
    else:
        print("\n! WARNING: SQLite file not found")


def main():
    print("="*60)
    print("LANGGRAPH MULTI-DOC RAG TEST SUITE")
    print("="*60)

    tests = [
        ("Basic Retrieval", test_basic_retrieval),
        ("Conversational Memory", test_conversational_memory),
        ("Source Citations", test_source_citations),
        ("Structured Output", test_structured_output),
        ("Trade Compliance Output", test_trade_compliance_output),
        ("SQLite Persistence", test_sqlite_persistence),
    ]

    results = []
    for name, test_func in tests:
        try:
            test_func()
            results.append((name, "PASSED"))
        except Exception as e:
            print(f"\n✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, f"FAILED: {e}"))

    print("\n" + "="*60)
    print("TEST RESULTS SUMMARY")
    print("="*60)
    for name, status in results:
        icon = "✓" if status == "PASSED" else "✗"
        print(f"{icon} {name}: {status}")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
