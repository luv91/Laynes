"""
Test script for conversation memory in agentic chat.

This script tests that the system properly remembers previous messages
and can answer follow-up questions using conversation context.

Usage:
    cd lanes
    pipenv shell
    python scripts/test_conversation_memory.py

Prerequisites:
    - Run ingest_test_docs.py --mock first
    - Pinecone configured with test_corpus documents
    - OPENAI_API_KEY set in .env
"""

import os
import sys
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def test_agentic_conversation_memory():
    """
    Test that agentic RAG remembers previous conversation and can answer follow-ups.

    This is the critical test for the memory fix:
    1. Ask about LED lamp tariffs
    2. Ask a vague follow-up like "what is it?"
    3. Verify the system understands "it" refers to LED lamps/tariffs
    """
    print("\n" + "="*70)
    print("TEST: Agentic Conversation Memory")
    print("="*70)

    from app.chat import build_agentic_chat, ChatArgs
    from app.chat.models import Metadata

    # Use SQLite checkpointer for persistence across invocations
    os.environ["USE_SQLITE_CHECKPOINTER"] = "true"

    # Use a unique conversation ID for this test
    conversation_id = f"memory-test-{uuid.uuid4().hex[:8]}"

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

    # Build the chat instance
    chat = build_agentic_chat(chat_args)

    # =========================================================================
    # Message 1: Ask about LED lamp tariffs
    # =========================================================================
    print("\n--- Message 1 ---")
    question1 = "What are the tariffs for LED lamps from China?"
    print(f"User: {question1}")

    result1 = chat.invoke(question1)
    answer1 = result1.get("answer", "")

    print(f"Assistant: {answer1[:500]}...")
    print(f"Tools used: {len(result1.get('tool_calls', []))}")

    # Verify we got a meaningful answer about LED lamps
    answer1_lower = answer1.lower()
    has_led = "led" in answer1_lower or "8539" in answer1_lower
    has_tariff = "tariff" in answer1_lower or "duty" in answer1_lower or "%" in answer1

    if has_led and has_tariff:
        print("✓ First answer mentions LED and tariffs")
    else:
        print("! WARNING: First answer may not have relevant content")

    # =========================================================================
    # Message 2: Vague follow-up that requires memory
    # =========================================================================
    print("\n--- Message 2 (Follow-up) ---")

    # Rebuild chat instance (simulates new request, but same conversation_id)
    # This tests that the SQLite checkpointer properly restores state
    chat2 = build_agentic_chat(chat_args)

    question2 = "Can you explain that in more detail?"
    print(f"User: {question2}")

    result2 = chat2.invoke(question2)
    answer2 = result2.get("answer", "")

    print(f"Assistant: {answer2[:500]}...")

    # =========================================================================
    # Verify: The follow-up should reference LED lamps/tariffs
    # =========================================================================
    answer2_lower = answer2.lower()

    # Check if the answer still talks about LED lamps or tariffs
    # (proving it remembered the context)
    remembers_context = (
        "led" in answer2_lower or
        "lamp" in answer2_lower or
        "8539" in answer2_lower or
        "tariff" in answer2_lower or
        "duty" in answer2_lower or
        "china" in answer2_lower or
        "section 301" in answer2_lower
    )

    # Check for "I don't know" type responses which indicate memory failure
    is_confused = (
        "not clear" in answer2_lower or
        "don't understand" in answer2_lower or
        "please clarify" in answer2_lower or
        "what are you referring" in answer2_lower or
        "could you specify" in answer2_lower
    )

    print("\n--- Results ---")
    if remembers_context and not is_confused:
        print("✓ SUCCESS: System remembered the conversation context!")
        print("  The follow-up answer references LED lamps/tariffs from the first question.")
        return True
    elif is_confused:
        print("✗ FAILURE: System did NOT remember the conversation!")
        print("  The follow-up response indicates confusion about what 'that' refers to.")
        return False
    else:
        print("? UNCLEAR: Could not definitively verify memory")
        print("  Please check the answers manually.")
        return None


def test_standard_rag_conversation_memory():
    """
    Test that standard (non-agentic) RAG also remembers conversation.

    This tests the conversational_rag.py condense node which should
    reformulate follow-up questions using chat history.
    """
    print("\n" + "="*70)
    print("TEST: Standard RAG Conversation Memory")
    print("="*70)

    from app.chat import build_chat, ChatArgs
    from app.chat.models import Metadata

    # Use SQLite checkpointer
    os.environ["USE_SQLITE_CHECKPOINTER"] = "true"

    conversation_id = f"standard-memory-test-{uuid.uuid4().hex[:8]}"

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

    # Build standard (non-agentic) chat
    chat = build_chat(chat_args, output_format="text")

    # =========================================================================
    # Message 1: Ask about HTS code
    # =========================================================================
    print("\n--- Message 1 ---")
    question1 = "What is the HTS code for LED lamps?"
    print(f"User: {question1}")

    result1 = chat.invoke(question1)
    answer1 = result1.get("answer", "")

    print(f"Assistant: {answer1[:400]}...")

    # =========================================================================
    # Message 2: Follow-up
    # =========================================================================
    print("\n--- Message 2 (Follow-up) ---")

    # Rebuild chat (simulates new HTTP request)
    chat2 = build_chat(chat_args, output_format="text")

    question2 = "What duty rate applies to it?"
    print(f"User: {question2}")

    result2 = chat2.invoke(question2)
    answer2 = result2.get("answer", "")
    condensed = result2.get("condensed_question", "")

    print(f"Condensed question: {condensed}")
    print(f"Assistant: {answer2[:400]}...")

    # =========================================================================
    # Verify
    # =========================================================================
    answer2_lower = answer2.lower()

    # The answer should mention duty rates and LED context
    has_rate_info = "%" in answer2 or "duty" in answer2_lower or "rate" in answer2_lower
    has_led_context = "led" in answer2_lower or "8539" in answer2_lower or "lamp" in answer2_lower

    print("\n--- Results ---")
    if has_rate_info and has_led_context:
        print("✓ SUCCESS: Standard RAG remembered context!")
        return True
    else:
        print("? UNCLEAR: Check the condensed question and answer")
        return None


def main():
    """Run all conversation memory tests."""
    print("\n" + "#"*70)
    print("# CONVERSATION MEMORY TESTS")
    print("# Testing that the system remembers previous messages")
    print("#"*70)

    results = {}

    # Test 1: Agentic mode
    try:
        results["agentic"] = test_agentic_conversation_memory()
    except Exception as e:
        print(f"\n✗ ERROR in agentic test: {e}")
        import traceback
        traceback.print_exc()
        results["agentic"] = False

    # Test 2: Standard RAG mode
    try:
        results["standard"] = test_standard_rag_conversation_memory()
    except Exception as e:
        print(f"\n✗ ERROR in standard RAG test: {e}")
        import traceback
        traceback.print_exc()
        results["standard"] = False

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else ("? UNCLEAR" if passed is None else "✗ FAILED")
        print(f"  {test_name}: {status}")

    all_passed = all(r is True for r in results.values())
    if all_passed:
        print("\n✓ All conversation memory tests passed!")
    else:
        print("\n! Some tests failed or need manual verification")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
