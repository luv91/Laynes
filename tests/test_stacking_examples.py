#!/usr/bin/env python
"""
Test cases for Phoebe's tariff stacking examples.

These are integration tests that run against the real database.
They verify:
1. HTS 8536.90.8585 (Example 3) - No 232 claim
2. Base HTS always appears as last line (CBP requirement)
3. Empty materials dict proceeds without halting
4. Section 301 list-specific codes

Usage:
    pipenv run python tests/test_stacking_examples.py
    pipenv run python tests/test_stacking_examples.py -v  # verbose
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.chat.graphs.stacking_rag import StackingRAG


class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = True
        self.failures = []

    def check(self, condition, message):
        if not condition:
            self.passed = False
            self.failures.append(message)
        return condition

    def __str__(self):
        if self.passed:
            return f"[PASS] {self.name}"
        return f"[FAIL] {self.name}\n" + "\n".join(f"  - {f}" for f in self.failures)


# =============================================================================
# Test Cases
# =============================================================================

def test_example_3_hts_8536_no_232_claim():
    """
    Example 3: HTS 8536.90.8585 (China) - No 232 materials claimed.

    Expected output:
    - 9903.88.01 Section 301 List 1 (25%)
    - 9903.01.24 IEEPA Fentanyl (10%)
    - 9903.01.25 IEEPA Reciprocal taxable (10%)
    - 8536.90.8585 Base HTS (last line)

    Total: 45% effective rate
    """
    result = TestResult("Example 3: HTS 8536.90.8585 - No 232 Claim")

    stacking = StackingRAG(conversation_id="test-example-3")
    output = stacking.calculate_stacking(
        hts_code="8536.90.8585",
        country="China",
        product_description="electrical switching apparatus",
        product_value=174.0,
        materials={}  # No 232 claim
    )

    entries = output.get("entries", [])

    # Should have entries (not halted asking for materials)
    result.check(
        len(entries) >= 1,
        f"Should have at least 1 entry, got {len(entries)}"
    )

    if entries:
        result.check(
            entries[0].get("entry_id") == "full_product",
            f"Expected full_product slice, got {entries[0].get('entry_id')}"
        )

        stack = entries[0].get("stack", [])
        codes = [line.get("chapter_99_code") for line in stack if line.get("chapter_99_code")]

        # Verify Section 301 List 1 code
        result.check(
            "9903.88.01" in codes,
            f"Should have Section 301 List 1 code 9903.88.01, got: {codes}"
        )

        # Verify IEEPA Fentanyl
        result.check(
            "9903.01.24" in codes,
            f"Should have IEEPA Fentanyl code 9903.01.24, got: {codes}"
        )

        # Verify IEEPA Reciprocal (taxable variant for no-metal slice)
        result.check(
            "9903.01.25" in codes,
            f"Should have IEEPA Reciprocal taxable 9903.01.25, got: {codes}"
        )

        # Verify base HTS is last line
        last_line = stack[-1] if stack else {}
        result.check(
            last_line.get("is_base_hts") is True,
            f"Last line should be base HTS, got: {last_line}"
        )
        result.check(
            last_line.get("hts_code") == "8536.90.8585",
            f"Base HTS should be 8536.90.8585, got: {last_line.get('hts_code')}"
        )

        # Verify effective rate ~45%
        total_duty = output.get("total_duty", {})
        effective_rate = total_duty.get("effective_rate", 0)
        result.check(
            abs(effective_rate - 0.45) < 0.05,
            f"Expected ~45% rate, got {effective_rate*100:.1f}%"
        )

    return result


def test_base_hts_always_last_line_full_product():
    """Verify base HTS is last line for full product slice."""
    result = TestResult("Base HTS Last Line: Full Product")

    stacking = StackingRAG(conversation_id="test-base-hts-1")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB cable",
        product_value=1000.0,
        materials={}  # Full product, no metal claims
    )

    entries = output.get("entries", [])

    for entry in entries:
        stack = entry.get("stack", [])
        if not stack:
            continue

        last_line = stack[-1]
        entry_id = entry.get("entry_id")

        result.check(
            last_line.get("is_base_hts") is True,
            f"Last line in {entry_id} is not base HTS"
        )
        result.check(
            last_line.get("hts_code") == "8544.42.9090",
            f"Base HTS code mismatch in {entry_id}: {last_line.get('hts_code')}"
        )
        result.check(
            last_line.get("chapter_99_code") is None,
            f"Base HTS should not have chapter_99_code in {entry_id}"
        )

    return result


def test_base_hts_always_last_line_with_metals():
    """Verify base HTS is last line for all slices including metal slices."""
    result = TestResult("Base HTS Last Line: With Metals")

    stacking = StackingRAG(conversation_id="test-base-hts-2")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB cable with copper",
        product_value=1000.0,
        materials={"copper": 500, "aluminum": 300}
    )

    entries = output.get("entries", [])

    result.check(
        len(entries) >= 2,
        f"Should have multiple slices with metal claims, got {len(entries)}"
    )

    for entry in entries:
        stack = entry.get("stack", [])
        if not stack:
            continue

        last_line = stack[-1]
        entry_id = entry.get("entry_id")

        result.check(
            last_line.get("is_base_hts") is True,
            f"Last line in {entry_id} is not base HTS"
        )
        result.check(
            last_line.get("hts_code") == "8544.42.9090",
            f"Base HTS code mismatch in {entry_id}: {last_line.get('hts_code')}"
        )

    return result


def test_empty_materials_dict_proceeds():
    """
    When materials={} is passed, system should:
    1. NOT halt asking for materials
    2. Proceed with full product slice
    3. Apply Section 301, IEEPA programs
    4. Skip Section 232 (no claim)
    """
    result = TestResult("Empty Materials Dict Proceeds")

    stacking = StackingRAG(conversation_id="test-empty-materials")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="test product",
        product_value=100.0,
        materials={}  # Explicit empty = no 232 claim
    )

    # Should NOT be awaiting input
    result.check(
        output.get("awaiting_user_input") is not True,
        "Should not be awaiting user input with empty materials dict"
    )

    # Should have entries
    entries = output.get("entries", [])
    result.check(
        len(entries) >= 1,
        f"Should have at least 1 entry, got {len(entries)}"
    )

    if entries:
        # Should have calculated duty
        total_duty = output.get("total_duty", {})
        result.check(
            total_duty.get("total_duty_amount", 0) > 0,
            f"Should have calculated duty amount, got {total_duty.get('total_duty_amount')}"
        )

        # Stack should have 301, Fentanyl, Reciprocal, Base HTS
        stack = entries[0].get("stack", [])
        program_ids = [line.get("program_id") for line in stack]

        result.check("section_301" in program_ids, "Should have section_301")
        result.check("ieepa_fentanyl" in program_ids, "Should have ieepa_fentanyl")
        result.check("ieepa_reciprocal" in program_ids, "Should have ieepa_reciprocal")
        result.check("base_hts" in program_ids, "Should have base_hts")

        # For 232 programs with empty materials:
        # - Copper has disclaim_behavior='required', so it appears as DISCLAIM
        # - Aluminum/Steel have disclaim_behavior='omit', so they don't appear
        copper_lines = [l for l in stack if l.get("program_id") == "section_232_copper"]
        if copper_lines:
            # Copper should be DISCLAIM action, not CLAIM
            result.check(
                copper_lines[0].get("action") == "disclaim",
                f"Copper with empty materials should be disclaim, got {copper_lines[0].get('action')}"
            )

        # Aluminum/Steel should NOT appear (omit behavior)
        result.check(
            "section_232_aluminum" not in program_ids,
            "Should NOT have section_232_aluminum with empty materials (omit behavior)"
        )
        result.check(
            "section_232_steel" not in program_ids,
            "Should NOT have section_232_steel with empty materials (omit behavior)"
        )

    return result


def test_section_301_list_1_code():
    """
    HTS 8536.90.8585 is on Section 301 List 1.
    Should use code 9903.88.01.
    """
    result = TestResult("Section 301 List 1 Code")

    stacking = StackingRAG(conversation_id="test-301-list1")
    output = stacking.calculate_stacking(
        hts_code="8536.90.8585",
        country="China",
        product_description="electrical apparatus",
        product_value=100.0,
        materials={}
    )

    entries = output.get("entries", [])
    if entries:
        stack = entries[0].get("stack", [])
        codes = [line.get("chapter_99_code") for line in stack if line.get("chapter_99_code")]
        result.check(
            "9903.88.01" in codes,
            f"List 1 HTS should use 9903.88.01, got codes: {codes}"
        )
    else:
        result.check(False, "No entries returned")

    return result


def test_section_301_list_3_code():
    """
    HTS 8544.42.9090 is on Section 301 List 3.
    Should use code 9903.88.03.
    """
    result = TestResult("Section 301 List 3 Code")

    stacking = StackingRAG(conversation_id="test-301-list3")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB cable",
        product_value=100.0,
        materials={}
    )

    entries = output.get("entries", [])
    if entries:
        stack = entries[0].get("stack", [])
        codes = [line.get("chapter_99_code") for line in stack if line.get("chapter_99_code")]
        result.check(
            "9903.88.03" in codes,
            f"List 3 HTS should use 9903.88.03, got codes: {codes}"
        )
    else:
        result.check(False, "No entries returned")

    return result


# =============================================================================
# Main
# =============================================================================

def main():
    """Run all tests and print results."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    tests = [
        test_example_3_hts_8536_no_232_claim,
        test_base_hts_always_last_line_full_product,
        test_base_hts_always_last_line_with_metals,
        test_empty_materials_dict_proceeds,
        test_section_301_list_1_code,
        test_section_301_list_3_code,
    ]

    print("=" * 70)
    print("Tariff Stacking Examples Test Suite")
    print("=" * 70)
    print()

    passed = 0
    failed = 0
    results = []

    for test_fn in tests:
        try:
            result = test_fn()
            results.append(result)
            if result.passed:
                passed += 1
            else:
                failed += 1
            print(result)
        except Exception as e:
            failed += 1
            print(f"[ERROR] {test_fn.__name__}: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
        print()

    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
