#!/usr/bin/env python
"""
v7.0 Stability Test Suite: Edge Cases and Error Handling

Tests edge cases and stability for the Phoebe-aligned tariff stacking:
- TC-v7.0-009: Quantity Duplication (all slices get same quantity)
- TC-v7.0-010: Rounding / Penny Drift
- TC-v7.0-011: Invalid Allocation (Sum > Total)
- TC-v7.0-013: Copper Applicable, No Copper Slice Exists
- TC-v7.0-014: No Duplicate Copper Disclaim Insertion

Usage:
    pipenv run python tests/test_stacking_v7_stability.py
    pipenv run python tests/test_stacking_v7_stability.py -v  # verbose
"""

import sys
import os
import json

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
# v7.0 Stability Test Cases
# =============================================================================

def test_v7_009_quantity_duplication():
    """
    TC-v7.0-009: Quantity Duplication

    All slices should repeat the SAME piece count (quantity duplicated, value split).

    Input:
        HTS: 8544.42.9090
        Country: CN
        Value: $10,000
        Quantity: 100
        Materials: copper=$3,000, steel=$2,000, aluminum=$1,000

    Expected:
        - 4 slices (non_metal + 3 metals)
        - ALL slices have quantity: 100 (NOT split)
        - Sum of values: $10,000 (IS split)
    """
    result = TestResult("TC-v7.0-009: Quantity Duplication")

    stacking = StackingRAG(conversation_id="test-v7-009")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable",
        product_value=10000.00,
        materials={"copper": 3000.00, "steel": 2000.00, "aluminum": 1000.00},
        quantity=100
    )

    entries = output.get("entries", [])

    # Check for 4 slices
    result.check(
        len(entries) == 4,
        f"Expected 4 entries, got {len(entries)}"
    )

    # Check all slices have same quantity (100)
    for entry in entries:
        entry_qty = entry.get("quantity", entry.get("line_quantity"))
        if entry_qty is not None:
            result.check(
                entry_qty == 100,
                f"Slice {entry.get('slice_type')} should have quantity=100, got {entry_qty}"
            )

    # Check sum of values equals product_value
    total_value = sum(e.get("line_value", 0) for e in entries)
    result.check(
        abs(total_value - 10000.00) < 0.01,
        f"Sum of slice values should be $10,000, got ${total_value:.2f}"
    )

    return result


def test_v7_010_rounding_penny_drift():
    """
    TC-v7.0-010: Rounding / Penny Drift

    Ensure no penny drift in value allocation.

    Input:
        Value: $100.00
        Materials: copper=$33.33, aluminum=$33.33, steel=$33.33

    Expected:
        - Sum of slice values: $100.00 (exactly, no drift)
        - Residual absorbs any rounding (if 0.01 remainder)
    """
    result = TestResult("TC-v7.0-010: Rounding / Penny Drift")

    stacking = StackingRAG(conversation_id="test-v7-010")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Cable for rounding test",
        product_value=100.00,
        materials={"copper": 33.33, "aluminum": 33.33, "steel": 33.33}
    )

    entries = output.get("entries", [])

    # Sum of all slice values should equal exactly $100.00
    total_value = sum(e.get("line_value", 0) for e in entries)
    result.check(
        abs(total_value - 100.00) < 0.01,
        f"Sum of slice values should be exactly $100.00, got ${total_value:.2f} (penny drift!)"
    )

    # Check no negative values
    for entry in entries:
        line_value = entry.get("line_value", 0)
        result.check(
            line_value >= 0,
            f"Slice {entry.get('slice_type')} has negative value: ${line_value:.2f}"
        )

    return result


def test_v7_011_invalid_allocation():
    """
    TC-v7.0-011: Invalid Allocation (Sum > Total)

    When material values exceed product value, system should handle gracefully.

    Input:
        Value: $100.00
        Materials: copper=$60.00, aluminum=$60.00 (Sum = $120 > $100)

    Expected:
        - Error OR warning message
        - No partial/incorrect output
    """
    result = TestResult("TC-v7.0-011: Invalid Allocation (Sum > Total)")

    stacking = StackingRAG(conversation_id="test-v7-011")

    try:
        output = stacking.calculate_stacking(
            hts_code="8544.42.9090",
            country="China",
            product_description="Cable with invalid allocation",
            product_value=100.00,
            materials={"copper": 60.00, "aluminum": 60.00}  # Sum = 120 > 100
        )

        # If no exception, check for error handling in output
        entries = output.get("entries", [])
        errors = output.get("errors", [])
        warnings = output.get("warnings", [])

        # Either we should have an error/warning OR the system capped values
        if errors or warnings:
            result.check(
                True,
                "System correctly flagged invalid allocation"
            )
        else:
            # Check if values were capped
            total_value = sum(e.get("line_value", 0) for e in entries)
            result.check(
                total_value <= 100.01,  # Allow small rounding
                f"Sum of slice values exceeds product value: ${total_value:.2f} > $100.00"
            )

    except ValueError as e:
        # Explicit error is acceptable
        result.check(
            "exceed" in str(e).lower() or "invalid" in str(e).lower(),
            f"Expected meaningful error message about invalid allocation, got: {e}"
        )

    except Exception as e:
        # Other exceptions should still mention the issue
        result.check(
            False,
            f"Unexpected exception type: {type(e).__name__}: {e}"
        )

    return result


def test_v7_013_copper_applicable_no_copper_slice():
    """
    TC-v7.0-013: Copper Applicable, No Copper Slice Exists

    When copper is applicable to HTS but no copper is claimed,
    copper disclaim should appear in all other slices.

    Input:
        HTS: 8544.42.9090 (flags for copper+aluminum)
        Materials: aluminum=$5,000 (no copper claimed, but copper IS applicable)

    Expected:
        - Residual slice: contains copper disclaim (9903.78.02) ONCE
        - Aluminum slice: contains copper disclaim (9903.78.02) ONCE
    """
    result = TestResult("TC-v7.0-013: Copper Applicable, No Copper Slice Exists")

    stacking = StackingRAG(conversation_id="test-v7-013")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Cable with aluminum only (copper applicable)",
        product_value=10000.00,
        materials={"aluminum": 5000.00}  # No copper, but copper IS applicable
    )

    entries = output.get("entries", [])

    # Should have 2 slices (residual + aluminum)
    result.check(
        len(entries) == 2,
        f"Expected 2 entries (residual + aluminum), got {len(entries)}"
    )

    # Check each slice for copper disclaim
    for entry in entries:
        slice_type = entry.get("slice_type")
        stack = entry.get("stack", [])

        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]

        # v7.0: Copper disclaim should appear ONCE in each non-copper slice
        result.check(
            len(copper_codes) == 1,
            f"{slice_type}: Expected exactly 1 copper disclaim (required behavior), got {len(copper_codes)}"
        )

        if copper_codes:
            result.check(
                copper_codes[0].get("chapter_99_code") == "9903.78.02",
                f"{slice_type}: Copper code should be 9903.78.02 (disclaim), got {copper_codes[0].get('chapter_99_code')}"
            )
            result.check(
                copper_codes[0].get("action") == "disclaim",
                f"{slice_type}: Copper action should be 'disclaim', got {copper_codes[0].get('action')}"
            )

    return result


def test_v7_014_no_duplicate_copper_disclaim():
    """
    TC-v7.0-014: No Duplicate Copper Disclaim Insertion

    Copper disclaim should appear exactly ONCE per slice, not twice.

    Input:
        HTS: 8544.42.9090
        Materials: aluminum=$1,000

    Expected:
        - Aluminum slice: copper disclaim count = 1 (not 2 or 0)
    """
    result = TestResult("TC-v7.0-014: No Duplicate Copper Disclaim Insertion")

    stacking = StackingRAG(conversation_id="test-v7-014")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Cable with aluminum only",
        product_value=1000.00,
        materials={"aluminum": 1000.00}
    )

    entries = output.get("entries", [])

    # Check aluminum slice for exactly one copper disclaim
    aluminum_entries = [e for e in entries if e.get("slice_type") == "aluminum_slice"]

    if aluminum_entries:
        aluminum = aluminum_entries[0]
        stack = aluminum.get("stack", [])

        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]

        result.check(
            len(copper_codes) == 1,
            f"Aluminum slice should have exactly 1 copper disclaim, got {len(copper_codes)}"
        )

    return result


def test_v7_slice_value_sum():
    """
    TC-v7.0-015: Slice Value Sum Validation

    Sum of all slice values must equal product value.

    Input:
        Value: $5,000
        Materials: copper=$1,500, steel=$2,000, aluminum=$500

    Expected:
        - 4 slices with values summing to $5,000
    """
    result = TestResult("TC-v7.0-015: Slice Value Sum Validation")

    stacking = StackingRAG(conversation_id="test-v7-015")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Cable for value sum test",
        product_value=5000.00,
        materials={"copper": 1500.00, "steel": 2000.00, "aluminum": 500.00}
    )

    entries = output.get("entries", [])

    # Check expected slice values
    expected_residual = 5000.00 - 1500.00 - 2000.00 - 500.00  # = $1,000
    total_value = sum(e.get("line_value", 0) for e in entries)

    result.check(
        abs(total_value - 5000.00) < 0.01,
        f"Sum of slice values should be $5,000, got ${total_value:.2f}"
    )

    # Check individual slice values
    for entry in entries:
        slice_type = entry.get("slice_type")
        line_value = entry.get("line_value", 0)

        if slice_type == "non_metal":
            result.check(
                abs(line_value - expected_residual) < 0.01,
                f"Residual should be ${expected_residual:.2f}, got ${line_value:.2f}"
            )
        elif slice_type == "copper_slice":
            result.check(
                abs(line_value - 1500.00) < 0.01,
                f"Copper slice should be $1,500, got ${line_value:.2f}"
            )
        elif slice_type == "steel_slice":
            result.check(
                abs(line_value - 2000.00) < 0.01,
                f"Steel slice should be $2,000, got ${line_value:.2f}"
            )
        elif slice_type == "aluminum_slice":
            result.check(
                abs(line_value - 500.00) < 0.01,
                f"Aluminum slice should be $500, got ${line_value:.2f}"
            )

    return result


def test_v7_zero_metal_value():
    """
    TC-v7.0-016: Zero Metal Value Handling

    When metal value is $0, no slice should be created for that metal.

    Input:
        HTS: 8544.42.9090
        Value: $1,000
        Materials: copper=$500, steel=$0

    Expected:
        - 2 slices (non_metal, copper_slice)
        - NO steel_slice (steel value is 0)
    """
    result = TestResult("TC-v7.0-016: Zero Metal Value Handling")

    stacking = StackingRAG(conversation_id="test-v7-016")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Cable with zero steel",
        product_value=1000.00,
        materials={"copper": 500.00, "steel": 0}
    )

    entries = output.get("entries", [])
    slice_types = [e.get("slice_type") for e in entries]

    # Should have 2 slices (no steel_slice)
    result.check(
        len(entries) == 2,
        f"Expected 2 entries (non_metal + copper), got {len(entries)}"
    )

    result.check(
        "steel_slice" not in slice_types,
        f"Should NOT have steel_slice when steel value is $0, got: {slice_types}"
    )

    result.check(
        "copper_slice" in slice_types,
        f"Should have copper_slice, got: {slice_types}"
    )

    return result


# =============================================================================
# Main Test Runner
# =============================================================================

def run_all_tests(verbose=False):
    """Run all v7.0 stability test cases."""
    tests = [
        test_v7_009_quantity_duplication,
        test_v7_010_rounding_penny_drift,
        test_v7_011_invalid_allocation,
        test_v7_013_copper_applicable_no_copper_slice,
        test_v7_014_no_duplicate_copper_disclaim,
        test_v7_slice_value_sum,
        test_v7_zero_metal_value,
    ]

    print("=" * 60)
    print("v7.0 Stability Test Suite - Edge Cases")
    print("=" * 60)
    print()

    results = []
    passed = 0
    failed = 0

    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
            if result.passed:
                passed += 1
                print(f"[PASS] {result.name}")
            else:
                failed += 1
                print(f"[FAIL] {result.name}")
                if verbose:
                    for f in result.failures:
                        print(f"       - {f}")
        except Exception as e:
            failed += 1
            print(f"[ERROR] {test_func.__name__}: {e}")
            if verbose:
                import traceback
                traceback.print_exc()

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    if failed > 0 and not verbose:
        print("\nRun with -v for detailed failure information")

    return failed == 0


if __name__ == "__main__":
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    success = run_all_tests(verbose=verbose)
    sys.exit(0 if success else 1)
