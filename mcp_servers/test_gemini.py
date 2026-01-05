#!/usr/bin/env python
"""
Test script for Gemini MCP integration.

Usage:
    pipenv run python mcp/test_gemini.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

def test_connection():
    """Test basic Gemini API connection."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set in environment")
        return False

    print(f"API Key: {api_key[:10]}...{api_key[-4:]}")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='What is 2+2? Reply with just the number.'
        )
        print(f"Basic connection: SUCCESS ({response.text.strip()})")
        return True
    except Exception as e:
        print(f"Basic connection: FAILED - {e}")
        return False


def test_google_search_grounding():
    """Test Google Search grounding capability."""
    api_key = os.environ.get('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)

    print("\nTesting Google Search grounding...")

    try:
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        config = types.GenerateContentConfig(
            tools=[google_search_tool]
        )

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='What is the current Section 232 tariff rate on steel imports? Brief answer.',
            config=config
        )

        print(f"Google Search grounding: SUCCESS")
        print(f"Response: {response.text[:200]}...")

        # Check for grounding URLs
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata
                if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                    print(f"Grounding sources found: {len(metadata.grounding_chunks)}")

        return True
    except Exception as e:
        print(f"Google Search grounding: FAILED - {e}")
        return False


def test_hts_verification():
    """Test HTS scope verification."""
    api_key = os.environ.get('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)

    print("\nTesting HTS verification (8544.42.9090)...")

    try:
        google_search_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        config = types.GenerateContentConfig(
            tools=[google_search_tool]
        )

        prompt = """Is HTS code 8544.42.9090 subject to Section 232 tariffs?

Return JSON format:
{
    "hts_code": "8544.42.9090",
    "copper": {"in_scope": true/false},
    "steel": {"in_scope": true/false},
    "aluminum": {"in_scope": true/false}
}"""

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=config
        )

        print(f"HTS verification: SUCCESS")
        print(f"Response:\n{response.text}")
        return True
    except Exception as e:
        print(f"HTS verification: FAILED - {e}")
        return False


def list_available_models():
    """List available Gemini models."""
    api_key = os.environ.get('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)

    print("\nAvailable models:")
    for model in client.models.list():
        if 'gemini' in model.name.lower():
            print(f"  - {model.name}")


def main():
    print("=" * 60)
    print("Gemini MCP Integration Test Suite")
    print("=" * 60)

    results = []

    # Test 1: Basic connection
    print("\n[Test 1] Basic Connection")
    results.append(("Basic Connection", test_connection()))

    # Test 2: Google Search grounding
    print("\n[Test 2] Google Search Grounding")
    results.append(("Google Search", test_google_search_grounding()))

    # Test 3: HTS verification
    print("\n[Test 3] HTS Verification")
    results.append(("HTS Verification", test_hts_verification()))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    passed_count = sum(1 for _, p in results if p)
    print(f"\nTotal: {passed_count}/{len(results)} tests passed")

    # List models
    if "--models" in sys.argv:
        list_available_models()

    return all(p for _, p in results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
