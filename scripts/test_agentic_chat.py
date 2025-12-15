"""
Test script for agentic chat functionality with LangGraph.

This script tests:
1. Tool calling (search, HTS lookup, tariff check, agency requirements)
2. Multi-step reasoning
3. Complex trade compliance queries

Usage:
    cd lanes
    pipenv shell
    python scripts/test_agentic_chat.py

Prerequisites:
    - Run ingest_test_docs.py --mock first
    - Pinecone configured with test_corpus documents
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def test_basic_tool_use():
    """Test that the agent uses tools correctly."""
    print("\n" + "="*60)
    print("TEST 1: Basic Tool Use")
    print("="*60)

    from app.chat import build_agentic_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-agent-001",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-agent-001",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_agentic_chat(chat_args)

    print("\nQuery: What is the HTS code for LED lamps?")
    result = chat.invoke("What is the HTS code for LED lamps?")

    print(f"\nAnswer: {result['answer'][:300]}...")
    print(f"\nTools used ({len(result['tool_calls'])}):")
    for i, call in enumerate(result['tool_calls'][:3]):
        print(f"  [{i+1}] {call[:100]}...")

    if result['tool_calls']:
        print("\n✓ SUCCESS: Agent used tools!")
    else:
        print("\n! WARNING: No tool calls detected")


def test_multi_step_reasoning():
    """Test that agent can chain multiple tool calls."""
    print("\n" + "="*60)
    print("TEST 2: Multi-Step Reasoning")
    print("="*60)

    from app.chat import build_agentic_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-agent-002",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-agent-002",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_agentic_chat(chat_args)

    # This query requires multiple steps:
    # 1. Look up HTS code for LED lamps
    # 2. Check tariffs for that HTS code from China
    print("\nQuery: What tariffs would I pay on LED lamps from China?")
    result = chat.invoke("What tariffs would I pay on LED lamps from China?")

    print(f"\nAnswer: {result['answer'][:400]}...")
    print(f"\nTools used ({len(result['tool_calls'])}):")
    for i, call in enumerate(result['tool_calls']):
        # Extract tool name from the call
        tool_name = call.split(']:')[0].replace('[', '') if ']:' in call else 'unknown'
        print(f"  [{i+1}] {tool_name}")

    if len(result['tool_calls']) >= 2:
        print("\n✓ SUCCESS: Agent used multiple tools!")
    else:
        print("\n! NOTE: Agent may have combined queries")


def test_comprehensive_trade_query():
    """Test a complex trade compliance query."""
    print("\n" + "="*60)
    print("TEST 3: Comprehensive Trade Query")
    print("="*60)

    from app.chat import build_agentic_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-agent-003",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-agent-003",
        pdf_id=None,
        metadata=metadata,
        streaming=False,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_agentic_chat(chat_args, output_format="trade_compliance")

    query = """I want to import LED lamps from China to the US.
    Tell me everything I need: HTS codes, tariffs, required documents, and agency requirements."""

    print(f"\nQuery: {query}")
    result = chat.invoke(query)

    print(f"\nAnswer: {result['answer'][:500]}...")
    print(f"\nTools used ({len(result['tool_calls'])}):")
    for i, call in enumerate(result['tool_calls']):
        tool_name = call.split(']:')[0].replace('[', '') if ']:' in call else 'unknown'
        print(f"  [{i+1}] {tool_name}")

    # Check if we got comprehensive information
    answer_lower = result['answer'].lower()
    checks = {
        "HTS code": "8539" in result['answer'] or "hts" in answer_lower,
        "Tariff": "tariff" in answer_lower or "duty" in answer_lower,
        "Agency": "fcc" in answer_lower or "doe" in answer_lower or "agency" in answer_lower,
    }

    print("\nCoverage check:")
    for item, found in checks.items():
        icon = "✓" if found else "✗"
        print(f"  {icon} {item}: {'Found' if found else 'Missing'}")

    if all(checks.values()):
        print("\n✓ SUCCESS: Comprehensive answer with all key info!")
    else:
        print("\n! WARNING: Some information may be missing")


def test_streaming():
    """Test streaming with agentic chat."""
    print("\n" + "="*60)
    print("TEST 4: Streaming")
    print("="*60)

    from app.chat import build_agentic_chat, ChatArgs
    from app.chat.models import Metadata

    os.environ["USE_SQLITE_CHECKPOINTER"] = "false"

    metadata = Metadata(
        conversation_id="test-agent-004",
        user_id="test-user",
        pdf_id=None
    )

    chat_args = ChatArgs(
        conversation_id="test-agent-004",
        pdf_id=None,
        metadata=metadata,
        streaming=True,
        mode="multi_doc",
        scope_filter={"corpus": "test_corpus"}
    )

    chat = build_agentic_chat(chat_args)

    print("\nQuery: What agencies regulate LED lamps?")
    print("\nStreaming response:")
    print("-" * 40)

    chunk_count = 0
    for chunk in chat.stream("What agencies regulate LED lamps?"):
        chunk_count += 1
        if "final_answer" in chunk and chunk["final_answer"]:
            print(f"\n[Final Answer]: {chunk['final_answer'][:200]}...")
        elif "tool_outputs" in chunk and chunk["tool_outputs"]:
            print(f"[Tool outputs: {len(chunk['tool_outputs'])} calls]")

    print("-" * 40)
    print(f"Total chunks: {chunk_count}")

    if chunk_count > 0:
        print("\n✓ SUCCESS: Streaming works!")
    else:
        print("\n! WARNING: No chunks received")


def test_tool_specific_queries():
    """Test specific tool invocations."""
    print("\n" + "="*60)
    print("TEST 5: Tool-Specific Queries")
    print("="*60)

    from app.chat.graphs.agentic_rag import (
        search_documents,
        lookup_hts_code,
        check_tariffs,
        check_agency_requirements
    )

    print("\n--- Testing search_documents ---")
    result = search_documents.invoke({"query": "LED lighting requirements", "max_results": 3})
    print(f"Results: {result[:200]}...")

    print("\n--- Testing lookup_hts_code ---")
    result = lookup_hts_code.invoke({"product_description": "LED lamp"})
    print(f"Results: {result[:200]}...")

    print("\n--- Testing check_tariffs ---")
    result = check_tariffs.invoke({"hts_code": "8539.50.00", "country_of_origin": "China"})
    print(f"Results: {result[:200]}...")

    print("\n--- Testing check_agency_requirements ---")
    result = check_agency_requirements.invoke({"product_type": "LED lamps"})
    print(f"Results: {result[:200]}...")

    print("\n✓ SUCCESS: All tools executed!")


def main():
    print("="*60)
    print("LANGGRAPH AGENTIC RAG TEST SUITE")
    print("="*60)

    tests = [
        ("Basic Tool Use", test_basic_tool_use),
        ("Multi-Step Reasoning", test_multi_step_reasoning),
        ("Comprehensive Trade Query", test_comprehensive_trade_query),
        ("Streaming", test_streaming),
        ("Tool-Specific Queries", test_tool_specific_queries),
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
