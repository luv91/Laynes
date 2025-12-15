#!/usr/bin/env python
"""
Test script for the stacking graph.

Tests the full stacking calculation with a USB-C cable from China.

Usage:
    pipenv run python scripts/test_stacking.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chat.graphs.stacking_rag import StackingRAG


def test_usb_c_cable():
    """
    Test stacking with USB-C cable example.

    Input:
        - HTS: 8544.42.9090
        - Country: China
        - Materials: copper 5%, steel 20%, aluminum 72%, zinc 3%
        - Product Value: $10,000

    Expected filing lines:
        1. 9903.88.03 → Section 301 (25%)
        2. 9903.01.24 → IEEPA Fentanyl
        3. 9903.01.25 → IEEPA Reciprocal (disclaim if no 232 claims)
        4. 9903.78.02 → 232 Copper (disclaim - 5% < 25%)
        5. 9903.85.08 → 232 Aluminum (claim - 72% > 25%)
        6. (steel would need claim if > 25%)
    """
    print("=" * 60)
    print("Testing Stacking Graph: USB-C Cable from China")
    print("=" * 60)

    # Create stacking RAG instance
    stacking = StackingRAG(conversation_id="test-usb-c-001")

    # Test inputs
    hts_code = "8544.42.9090"
    country = "China"
    product_description = "USB-C cable for data transfer and charging"
    product_value = 10000.0
    materials = {
        "copper": 0.05,    # 5%
        "steel": 0.20,      # 20%
        "aluminum": 0.72,   # 72%
        "zinc": 0.03        # 3%
    }

    print(f"\nInput:")
    print(f"  HTS Code: {hts_code}")
    print(f"  Country: {country}")
    print(f"  Product: {product_description}")
    print(f"  Value: ${product_value:,.2f}")
    print(f"  Materials: {materials}")
    print("-" * 60)

    # Run stacking calculation
    try:
        result = stacking.calculate_stacking(
            hts_code=hts_code,
            country=country,
            product_description=product_description,
            product_value=product_value,
            materials=materials
        )

        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)

        # Print output
        if result.get("output"):
            print(result["output"])

        # Print summary
        print("\n" + "-" * 60)
        print("Summary:")
        print(f"  Filing Lines: {len(result.get('filing_lines', []))}")
        print(f"  Programs Found: {len(result.get('programs', []))}")
        print(f"  Decisions Made: {len(result.get('decisions', []))}")

        if result.get("total_duty"):
            duty = result["total_duty"]
            print(f"  Total Duty: ${duty.get('total_duty_amount', 0):,.2f}")
            print(f"  Effective Rate: {duty.get('effective_rate', 0)*100:.2f}%")

        # Check if awaiting user input
        if result.get("awaiting_user_input"):
            print(f"\n⚠️  Awaiting User Input: {result.get('user_question')}")

        return result

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_without_materials():
    """Test stacking when materials are not provided upfront."""
    print("\n" + "=" * 60)
    print("Testing Stacking Graph: Without Materials (should prompt)")
    print("=" * 60)

    stacking = StackingRAG(conversation_id="test-no-materials-001")

    result = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable",
        product_value=5000.0,
        materials=None  # Not provided
    )

    if result.get("awaiting_user_input"):
        print(f"\n✓ Correctly awaiting input: {result.get('user_question')}")

        # Now provide materials and continue
        print("\nContinuing with materials...")
        result = stacking.continue_with_materials({
            "copper": 0.05,
            "aluminum": 0.95
        })

        if result.get("output"):
            print(result["output"])
    else:
        print("\nResult:")
        if result.get("output"):
            print(result["output"])

    return result


if __name__ == "__main__":
    print("\n🚀 Stacking Graph Test Suite\n")

    # Test 1: Full stacking with materials
    result1 = test_usb_c_cable()

    # Test 2: Without materials (should prompt)
    # result2 = test_without_materials()

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)
