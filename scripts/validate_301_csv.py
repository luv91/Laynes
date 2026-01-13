#!/usr/bin/env python3
"""
Section 301 CSV Validation Script

Validates the Section 301 HTS codes CSV before database import.
Acts as "write gate" for the derived dataset.

Usage:
    pipenv run python scripts/validate_301_csv.py

Exit codes:
    0 = Validation passed
    1 = Validation failed (errors found)
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

# ============================================
# CONFIGURATION
# ============================================

CSV_PATH = Path(__file__).parent.parent / "data" / "section_301_hts_codes.csv"

# Required list → chapter_99 → rate mappings
# If a row doesn't match these, it's an ERROR
EXPECTED_MAPPINGS = {
    "list_1": {"chapter_99": "9903.88.01", "rate": 0.25},
    "list_2": {"chapter_99": "9903.88.02", "rate": 0.25},
    "list_3": {"chapter_99": "9903.88.03", "rate": 0.25},
    "list_4a": {"chapter_99": "9903.88.15", "rate": 0.075},
    "list_4A": {"chapter_99": "9903.88.15", "rate": 0.075},  # Allow uppercase
}

# Suspended lists - should NOT appear in active data
SUSPENDED_LISTS = {"list_4b", "list_4B"}

# Expected row count range
EXPECTED_MIN_ROWS = 10000
EXPECTED_MAX_ROWS = 11000

# HTS code format pattern (with dots): XXXX.XX.XX or XXXX.XX.XXXX
HTS_PATTERN = re.compile(r'^\d{4}\.\d{2}\.\d{2,4}$')

# Spot checks - known HTS codes that must be present with correct mappings
SPOT_CHECKS = [
    {"hts_8digit": "01012100", "list_name": "list_4A", "chapter_99": "9903.88.15", "rate": 0.075},
    {"hts_8digit": "01012900", "list_name": "list_4A", "chapter_99": "9903.88.15", "rate": 0.075},
]


# ============================================
# VALIDATION FUNCTIONS
# ============================================

def validate_hts_format(hts_code: str) -> tuple[bool, str]:
    """Validate HTS code format (XXXX.XX.XX or XXXX.XX.XXXX)."""
    if not hts_code:
        return False, "Empty HTS code"
    if not HTS_PATTERN.match(hts_code):
        return False, f"Invalid format: {hts_code}"
    return True, ""


def validate_8digit_format(hts_8digit: str) -> tuple[bool, str]:
    """
    Validate 8-digit HTS format.
    CRITICAL: Catches leading-zero loss (0101 → 101).
    """
    if not hts_8digit:
        return False, "Empty hts_8digit"
    if not hts_8digit.isdigit():
        return False, f"Non-digit characters: {hts_8digit}"
    if len(hts_8digit) != 8:
        return False, f"Length is {len(hts_8digit)}, expected 8: {hts_8digit}"
    # Check leading zeros preserved
    if hts_8digit != hts_8digit.zfill(8):
        return False, f"Leading zeros lost: {hts_8digit}"
    return True, ""


def validate_list_chapter99_rate(list_name: str, chapter_99: str, rate_str: str) -> tuple[bool, str]:
    """
    Validate strict list ↔ chapter_99 ↔ rate mapping.
    """
    # Check for suspended lists
    if list_name.lower() in {l.lower() for l in SUSPENDED_LISTS}:
        return False, f"Suspended list found: {list_name}"

    # Check list is known
    if list_name not in EXPECTED_MAPPINGS:
        return False, f"Unknown list_name: {list_name}"

    expected = EXPECTED_MAPPINGS[list_name]

    # Check chapter_99 matches
    if chapter_99 != expected["chapter_99"]:
        return False, f"Wrong chapter_99 for {list_name}: got {chapter_99}, expected {expected['chapter_99']}"

    # Check rate matches
    try:
        rate = float(rate_str)
    except ValueError:
        return False, f"Invalid rate format: {rate_str}"

    if abs(rate - expected["rate"]) > 0.0001:
        return False, f"Wrong rate for {list_name}: got {rate}, expected {expected['rate']}"

    return True, ""


def validate_status(status: str) -> tuple[bool, str]:
    """Validate status is 'active'."""
    if status.lower() != "active":
        return False, f"Non-active status: {status}"
    return True, ""


def validate_csv():
    """
    Comprehensive validation of Section 301 CSV.

    Returns:
        tuple: (passed: bool, errors: list, warnings: list, stats: dict)
    """
    errors = []
    warnings = []
    stats = {
        "total_rows": 0,
        "by_list": defaultdict(int),
        "by_chapter99": defaultdict(int),
    }

    # Track HTS codes to detect cross-list duplicates
    hts_to_lists = defaultdict(list)

    # Check file exists
    if not CSV_PATH.exists():
        errors.append(f"CSV file not found: {CSV_PATH}")
        return False, errors, warnings, stats

    print(f"Validating: {CSV_PATH}")
    print("=" * 60)

    with open(CSV_PATH, "r") as f:
        reader = csv.DictReader(f)

        # Validate headers
        required_headers = {"hts_code", "hts_8digit", "list_name", "chapter_99_code", "rate", "status"}
        if not required_headers.issubset(set(reader.fieldnames or [])):
            missing = required_headers - set(reader.fieldnames or [])
            errors.append(f"Missing required headers: {missing}")
            return False, errors, warnings, stats

        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            stats["total_rows"] += 1

            hts_code = row.get("hts_code", "").strip()
            hts_8digit = row.get("hts_8digit", "").strip()
            list_name = row.get("list_name", "").strip()
            chapter_99 = row.get("chapter_99_code", "").strip()
            rate = row.get("rate", "").strip()
            status = row.get("status", "").strip()

            # Validate HTS format
            valid, msg = validate_hts_format(hts_code)
            if not valid:
                errors.append(f"Row {row_num}: {msg}")

            # Validate 8-digit format (CRITICAL for leading zeros)
            valid, msg = validate_8digit_format(hts_8digit)
            if not valid:
                errors.append(f"Row {row_num}: {msg}")

            # Validate list/chapter99/rate consistency
            valid, msg = validate_list_chapter99_rate(list_name, chapter_99, rate)
            if not valid:
                errors.append(f"Row {row_num}: {msg}")

            # Validate status
            valid, msg = validate_status(status)
            if not valid:
                errors.append(f"Row {row_num}: {msg}")

            # Track for cross-list duplicate check
            hts_to_lists[hts_8digit].append(list_name)

            # Update stats
            stats["by_list"][list_name] += 1
            stats["by_chapter99"][chapter_99] += 1

            # Early exit if too many errors
            if len(errors) > 100:
                errors.append("... (truncated, too many errors)")
                break

    # Check for cross-list duplicates
    # NOTE: This is a WARNING, not an ERROR. Section 301 lists can legitimately
    # overlap - the same HTS may appear on multiple lists with different effective dates.
    # The database unique constraint is (hts_8digit, list_name), so this is allowed.
    print("\nChecking for cross-list duplicates...")
    cross_list_count = 0
    for hts, lists in hts_to_lists.items():
        if len(lists) > 1:
            unique_lists = set(lists)
            if len(unique_lists) > 1:
                cross_list_count += 1
                # Only warn, don't error - this is valid per Section 301 structure
                # warnings.append(f"HTS {hts} appears in multiple lists: {unique_lists}")

    if cross_list_count > 0:
        warnings.append(f"{cross_list_count} HTS codes appear in multiple lists (valid per 301 structure)")

    # Check row count
    print(f"\nChecking row count...")
    if stats["total_rows"] < EXPECTED_MIN_ROWS:
        errors.append(f"Too few rows: {stats['total_rows']} (expected >= {EXPECTED_MIN_ROWS})")
    elif stats["total_rows"] > EXPECTED_MAX_ROWS:
        warnings.append(f"More rows than expected: {stats['total_rows']} (expected <= {EXPECTED_MAX_ROWS})")

    # Run spot checks
    print("\nRunning spot checks...")
    spot_check_passed = 0
    for check in SPOT_CHECKS:
        found = False
        for hts, lists in hts_to_lists.items():
            if hts == check["hts_8digit"]:
                if check["list_name"] in lists or check["list_name"].lower() in [l.lower() for l in lists]:
                    found = True
                    spot_check_passed += 1
                    break
        if not found:
            warnings.append(f"Spot check failed: HTS {check['hts_8digit']} not found in {check['list_name']}")

    print(f"  Spot checks: {spot_check_passed}/{len(SPOT_CHECKS)} passed")

    passed = len(errors) == 0
    return passed, errors, warnings, stats


def print_results(passed: bool, errors: list, warnings: list, stats: dict):
    """Print validation results."""
    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)

    # Stats
    print(f"\nTotal rows: {stats['total_rows']}")
    print("\nBy list:")
    for list_name in sorted(stats["by_list"].keys()):
        count = stats["by_list"][list_name]
        print(f"  {list_name}: {count}")

    print("\nBy chapter_99:")
    for code in sorted(stats["by_chapter99"].keys()):
        count = stats["by_chapter99"][code]
        print(f"  {code}: {count}")

    # Warnings
    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"  - {w}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")

    # Errors
    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for e in errors[:20]:
            print(f"  - {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    # Final verdict
    print("\n" + "=" * 60)
    if passed:
        print("✅ VALIDATION PASSED")
        print("=" * 60)
        print("\nCSV is valid and ready for import.")
    else:
        print("❌ VALIDATION FAILED")
        print("=" * 60)
        print("\nFix the errors above before importing.")


def main():
    """Main entry point."""
    passed, errors, warnings, stats = validate_csv()
    print_results(passed, errors, warnings, stats)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
