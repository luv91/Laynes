#!/usr/bin/env python
"""
Automated test suite for the Stacking Feature.

Tests all scenarios documented in test_stacking_scenarios.md and README8.md

Phase 6 Update (Dec 2025):
- Content-value-based duties: 232 duty calculated on material $ value
- Copper rate: 50% (increased from 25%)
- All materials with content > 0 trigger claim (no threshold)
- Line splitting: 2 lines per material when claiming
  - Line A: Non-material content (disclaim code, 0% duty)
  - Line B: Material content (claim code, duty on content value)

Phase 6.5 Update (Dec 2025) - IEEPA Unstacking:
- IEEPA Reciprocal now calculated on remaining_value (after 232 content deductions)
- CBP rule: "Content subject to Section 232 is NOT subject to Reciprocal IEEPA"
- remaining_value = product_value - copper_value - steel_value - aluminum_value
- This reduces IEEPA Reciprocal duty when 232 claims exist

v4.0 Update (Dec 2025) - Entry Slices and Annex II:
- Output format: entries: List[FilingEntry] for ACE-ready filing
- Each entry is one ACE line with base HTS + stack of 99-codes
- Products with 232 metals split into multiple entries (non_metal + metal slices)
- IEEPA Reciprocal variants: taxable, annex_ii_exempt, metal_exempt, us_content_exempt
- Annex II exclusions: HTS codes exempt from IEEPA Reciprocal (pharma, chem, minerals)
- program_codes table now includes variant and slice_type columns

v4.0 Test Cases:
- UK Chemical (Annex II): 1 entry, $0 duty (9903.01.32 exempt)
- China 3-Metal: 4 entries (non_metal + 3 metals), $6,250 (62.5%)
- Germany 3-Metal: 4 entries (232 only, no China programs), $2,250 (22.5%)
- China Single-Metal: 2 entries (non_metal + copper), $5,700 (57.0%)

Usage:
    pipenv run python tests/test_stacking_automated.py
    pipenv run python tests/test_stacking_automated.py -v  # verbose
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


def test_case_1_usb_c_china_full():
    """
    Test Case 1: USB-C Cable from China (Full Scenario) - v4.0 Entries Format

    Material composition: copper 5%, steel 20%, aluminum 72%
    (Percentages are auto-converted to values: $500, $2000, $7200)

    v4.0 ARCHITECTURE:
    Creates 4 ACE entries (non_metal + 3 metal slices):
    - Entry 1: non_metal slice ($300 = $10,000 - $500 - $2000 - $7200)
    - Entry 2: copper_slice ($500)
    - Entry 3: steel_slice ($2,000)
    - Entry 4: aluminum_slice ($7,200)

    Duty Calculation:
    - Section 301: $10,000 × 25% = $2,500
    - IEEPA Fentanyl: $10,000 × 10% = $1,000
    - 232 Copper: $500 × 50% = $250
    - 232 Steel: $2,000 × 50% = $1,000
    - 232 Aluminum: $7,200 × 25% = $1,800
    - IEEPA Reciprocal: $300 × 10% = $30 (on remaining_value)
    - Total: $6,580 (65.8%)
    """
    result = TestResult("Test Case 1: USB-C Cable from China (Full)")

    stacking = StackingRAG(conversation_id="test-case-1")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable for data transfer and charging",
        product_value=10000.0,
        materials={"copper": 0.05, "steel": 0.20, "aluminum": 0.72, "zinc": 0.03}
    )

    # Verify program count (6 programs)
    result.check(
        len(output.get("programs", [])) == 6,
        f"Expected 6 programs, got {len(output.get('programs', []))}"
    )

    # v4.0: Check 4 entries (non_metal + 3 metal slices)
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Verify slice types
    slice_types = [e.get("slice_type") for e in entries]
    for expected in ["non_metal", "copper_slice", "steel_slice", "aluminum_slice"]:
        result.check(
            expected in slice_types,
            f"Missing slice_type '{expected}' in entries"
        )

    # Check copper_slice entry has 232 copper claim
    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        copper = copper_entries[0]
        result.check(
            abs(copper.get("line_value", 0) - 500.0) < 0.01,
            f"Copper slice should be $500, got ${copper.get('line_value', 0):.2f}"
        )
        stack = copper.get("stack", [])
        for line in stack:
            if line.get("program_id") == "section_232_copper":
                result.check(
                    line.get("action") == "claim",
                    f"Copper slice: 232 Copper should be 'claim', got '{line.get('action')}'"
                )

    # Check steel_slice entry
    steel_entries = [e for e in entries if e.get("slice_type") == "steel_slice"]
    if steel_entries:
        steel = steel_entries[0]
        result.check(
            abs(steel.get("line_value", 0) - 2000.0) < 0.01,
            f"Steel slice should be $2,000, got ${steel.get('line_value', 0):.2f}"
        )

    # Check aluminum_slice entry
    aluminum_entries = [e for e in entries if e.get("slice_type") == "aluminum_slice"]
    if aluminum_entries:
        aluminum = aluminum_entries[0]
        result.check(
            abs(aluminum.get("line_value", 0) - 7200.0) < 0.01,
            f"Aluminum slice should be $7,200, got ${aluminum.get('line_value', 0):.2f}"
        )

    # Verify duty calculation
    total_duty = output.get("total_duty", {})
    expected_duty = 2500 + 1000 + 250 + 1000 + 1800 + 30  # = $6,580
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )
    result.check(
        abs(total_duty.get("effective_rate", 0) - 0.658) < 0.001,
        f"Expected effective rate 65.8%, got {total_duty.get('effective_rate', 0)*100:.2f}%"
    )

    # Verify unstacking audit trail
    unstacking = total_duty.get("unstacking", {})
    result.check(
        unstacking.get("initial_value") == 10000.0,
        f"Expected initial_value $10,000, got {unstacking.get('initial_value')}"
    )
    result.check(
        abs(unstacking.get("remaining_value", 0) - 300.0) < 0.01,
        f"Expected remaining_value $300, got {unstacking.get('remaining_value')}"
    )

    return result


def test_case_2_high_steel():
    """
    Test Case 2: USB-C Cable with High Steel Content - v4.0 Entries Format

    Material composition: copper 15%, steel 80%, aluminum 3%
    (Percentages auto-converted to values: $1,500, $8,000, $300)

    v4.0 ARCHITECTURE:
    Creates 4 ACE entries (non_metal + 3 metal slices):
    - Entry 1: non_metal slice ($200 = $10,000 - $1,500 - $8,000 - $300)
    - Entry 2: copper_slice ($1,500)
    - Entry 3: steel_slice ($8,000)
    - Entry 4: aluminum_slice ($300)

    Duty Calculation:
    - Section 301: $10,000 × 25% = $2,500
    - IEEPA Fentanyl: $10,000 × 10% = $1,000
    - 232 Copper: $1,500 × 50% = $750
    - 232 Steel: $8,000 × 50% = $4,000
    - 232 Aluminum: $300 × 25% = $75
    - IEEPA Reciprocal: $200 × 10% = $20 (on remaining_value)
    - Total: $8,345 (83.45%)
    """
    result = TestResult("Test Case 2: High Steel Content")

    stacking = StackingRAG(conversation_id="test-case-2")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable with steel reinforcement",
        product_value=10000.0,
        materials={"copper": 0.15, "steel": 0.80, "aluminum": 0.03, "zinc": 0.02}
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Check steel_slice entry (dominant material)
    steel_entries = [e for e in entries if e.get("slice_type") == "steel_slice"]
    if steel_entries:
        steel = steel_entries[0]
        result.check(
            abs(steel.get("line_value", 0) - 8000.0) < 0.01,
            f"Steel slice should be $8,000 (80%), got ${steel.get('line_value', 0):.2f}"
        )
        stack = steel.get("stack", [])
        for line in stack:
            if line.get("program_id") == "section_232_steel":
                result.check(
                    line.get("action") == "claim",
                    f"Steel slice: 232 Steel should be 'claim', got '{line.get('action')}'"
                )

    # Check non_metal slice value
    non_metal_entries = [e for e in entries if e.get("slice_type") == "non_metal"]
    if non_metal_entries:
        non_metal = non_metal_entries[0]
        result.check(
            abs(non_metal.get("line_value", 0) - 200.0) < 0.01,
            f"Non-metal slice should be $200, got ${non_metal.get('line_value', 0):.2f}"
        )
        # Check IEEPA Reciprocal is "paid" on non_metal slice
        stack = non_metal.get("stack", [])
        for line in stack:
            if line.get("program_id") == "ieepa_reciprocal":
                result.check(
                    line.get("action") == "paid",
                    f"Non-metal: IEEPA Reciprocal should be 'paid', got '{line.get('action')}'"
                )

    # Verify duty calculation
    total_duty = output.get("total_duty", {})
    expected_duty = 2500 + 1000 + 750 + 4000 + 75 + 20  # = $8,345
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )

    return result


def test_case_3_all_materials_10_percent():
    """
    Test Case 3: All Materials at 10% - v4.0 Entries Format

    Material composition: copper 10%, steel 10%, aluminum 10%
    (Percentages auto-converted to values: $1,000, $1,000, $1,000)

    v4.0 ARCHITECTURE:
    Creates 4 ACE entries (non_metal + 3 metal slices):
    - Entry 1: non_metal slice ($7,000 = $10,000 - $1,000 - $1,000 - $1,000)
    - Entry 2: copper_slice ($1,000)
    - Entry 3: steel_slice ($1,000)
    - Entry 4: aluminum_slice ($1,000)

    Duty Calculation:
    - Section 301: $10,000 × 25% = $2,500
    - IEEPA Fentanyl: $10,000 × 10% = $1,000
    - 232 Copper: $1,000 × 50% = $500
    - 232 Steel: $1,000 × 50% = $500
    - 232 Aluminum: $1,000 × 25% = $250
    - IEEPA Reciprocal: $7,000 × 10% = $700 (on remaining_value)
    - Total: $5,450 (54.5%)
    """
    result = TestResult("Test Case 3: All Materials at 10%")

    stacking = StackingRAG(conversation_id="test-case-3")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable mostly plastic",
        product_value=10000.0,
        materials={"copper": 0.10, "steel": 0.10, "aluminum": 0.10}
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Check each metal slice is $1,000
    for metal in ["copper", "steel", "aluminum"]:
        metal_entries = [e for e in entries if e.get("slice_type") == f"{metal}_slice"]
        if metal_entries:
            slice_entry = metal_entries[0]
            result.check(
                abs(slice_entry.get("line_value", 0) - 1000.0) < 0.01,
                f"{metal.capitalize()} slice should be $1,000 (10%), got ${slice_entry.get('line_value', 0):.2f}"
            )
            # Check that the corresponding 232 program is "claim"
            stack = slice_entry.get("stack", [])
            for line in stack:
                if line.get("program_id") == f"section_232_{metal}":
                    result.check(
                        line.get("action") == "claim",
                        f"{metal}_slice: 232 {metal} should be 'claim', got '{line.get('action')}'"
                    )

    # Check non_metal slice value
    non_metal_entries = [e for e in entries if e.get("slice_type") == "non_metal"]
    if non_metal_entries:
        non_metal = non_metal_entries[0]
        result.check(
            abs(non_metal.get("line_value", 0) - 7000.0) < 0.01,
            f"Non-metal slice should be $7,000 (70%), got ${non_metal.get('line_value', 0):.2f}"
        )
        # Check IEEPA Reciprocal is "paid" on non_metal slice
        stack = non_metal.get("stack", [])
        for line in stack:
            if line.get("program_id") == "ieepa_reciprocal":
                result.check(
                    line.get("action") == "paid",
                    f"Non-metal: IEEPA Reciprocal should be 'paid', got '{line.get('action')}'"
                )
                result.check(
                    line.get("chapter_99_code") == "9903.01.25",
                    f"Non-metal: IEEPA Reciprocal code should be 9903.01.25, got {line.get('chapter_99_code')}"
                )

    # Verify duty calculation
    total_duty = output.get("total_duty", {})
    expected_duty = 2500 + 1000 + 500 + 500 + 250 + 700  # = $5,450
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )

    return result


def test_case_4_non_china_origin():
    """
    Test Case 4: Non-China Origin (Germany) - v4.0 Entries Format

    Only Section 232 programs should apply (country = "ALL")
    No Section 301, IEEPA Fentanyl, or IEEPA Reciprocal

    Material composition: copper 5%, steel 20%, aluminum 72%
    (Percentages auto-converted to values: $500, $2,000, $7,200)

    v4.0 ARCHITECTURE:
    Creates 4 ACE entries (non_metal + 3 metal slices), but no China programs:
    - Entry 1: non_metal slice ($300)
    - Entry 2: copper_slice ($500)
    - Entry 3: steel_slice ($2,000)
    - Entry 4: aluminum_slice ($7,200)

    Duty Calculation (232 only):
    - 232 Copper: $500 × 50% = $250
    - 232 Steel: $2,000 × 50% = $1,000
    - 232 Aluminum: $7,200 × 25% = $1,800
    - Total: $3,050 (30.5%)
    """
    result = TestResult("Test Case 4: Non-China Origin (Germany)")

    stacking = StackingRAG(conversation_id="test-case-4")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="Germany",
        product_description="USB-C cable from Germany",
        product_value=10000.0,
        materials={"copper": 0.05, "steel": 0.20, "aluminum": 0.72}
    )

    # Verify only 3 programs (Section 232 only, no China-specific)
    programs = output.get("programs", [])
    result.check(
        len(programs) == 3,
        f"Expected 3 programs for Germany (232 only), got {len(programs)}"
    )

    # Verify no China-specific programs
    program_ids = [p.get("program_id") for p in programs]
    result.check(
        "section_301" not in program_ids,
        "Section 301 should NOT apply to Germany"
    )
    result.check(
        "ieepa_fentanyl" not in program_ids,
        "IEEPA Fentanyl should NOT apply to Germany"
    )
    result.check(
        "ieepa_reciprocal" not in program_ids,
        "IEEPA Reciprocal should NOT apply to Germany"
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Verify slice values
    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        result.check(
            abs(copper_entries[0].get("line_value", 0) - 500.0) < 0.01,
            f"Copper slice should be $500, got ${copper_entries[0].get('line_value', 0):.2f}"
        )

    steel_entries = [e for e in entries if e.get("slice_type") == "steel_slice"]
    if steel_entries:
        result.check(
            abs(steel_entries[0].get("line_value", 0) - 2000.0) < 0.01,
            f"Steel slice should be $2,000, got ${steel_entries[0].get('line_value', 0):.2f}"
        )

    aluminum_entries = [e for e in entries if e.get("slice_type") == "aluminum_slice"]
    if aluminum_entries:
        result.check(
            abs(aluminum_entries[0].get("line_value", 0) - 7200.0) < 0.01,
            f"Aluminum slice should be $7,200, got ${aluminum_entries[0].get('line_value', 0):.2f}"
        )

    # Verify duty calculation
    total_duty = output.get("total_duty", {})
    expected_duty = 250 + 1000 + 1800  # = $3,050
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )

    return result


def test_case_5_ieepa_unstacking():
    """
    Test Case 5: IEEPA Unstacking (Phase 6.5) - v4.0 Entries Format

    This test uses percentages that match the research doc example:
    - Copper: 30% ($3,000)
    - Steel: 10% ($1,000)
    - Aluminum: 10% ($1,000)
    - Other: 50% ($5,000)

    THE KEY INSIGHT (CBP Rule):
    "Content subject to Section 232 is NOT subject to Reciprocal IEEPA"

    v4.0 ARCHITECTURE:
    Creates 4 ACE entries:
    - Entry 1: non_metal slice ($5,000) - IEEPA Reciprocal paid
    - Entry 2: copper_slice ($3,000) - IEEPA Reciprocal exempt
    - Entry 3: steel_slice ($1,000) - IEEPA Reciprocal exempt
    - Entry 4: aluminum_slice ($1,000) - IEEPA Reciprocal exempt

    Duty Calculation:
    - Section 301: $10,000 × 25% = $2,500
    - IEEPA Fentanyl: $10,000 × 10% = $1,000
    - 232 Copper: $3,000 × 50% = $1,500
    - 232 Steel: $1,000 × 50% = $500
    - 232 Aluminum: $1,000 × 25% = $250
    - IEEPA Reciprocal: $5,000 × 10% = $500 (on remaining_value!)
    - Total: $6,250 (62.5%)
    """
    result = TestResult("Test Case 5: IEEPA Unstacking (Phase 6.5)")

    stacking = StackingRAG(conversation_id="test-case-5")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable with mixed metals (research doc example)",
        product_value=10000.0,
        materials={"copper": 0.30, "steel": 0.10, "aluminum": 0.10}
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Check slice values
    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        result.check(
            abs(copper_entries[0].get("line_value", 0) - 3000.0) < 0.01,
            f"Copper slice should be $3,000, got ${copper_entries[0].get('line_value', 0):.2f}"
        )

    non_metal_entries = [e for e in entries if e.get("slice_type") == "non_metal"]
    if non_metal_entries:
        result.check(
            abs(non_metal_entries[0].get("line_value", 0) - 5000.0) < 0.01,
            f"Non-metal slice should be $5,000, got ${non_metal_entries[0].get('line_value', 0):.2f}"
        )

    total_duty = output.get("total_duty", {})

    # Verify unstacking audit trail is present
    unstacking = total_duty.get("unstacking", {})
    result.check(
        unstacking is not None and len(unstacking) > 0,
        "Expected unstacking audit trail in total_duty"
    )

    # Verify initial_value
    result.check(
        unstacking.get("initial_value") == 10000.0,
        f"Expected initial_value $10,000, got {unstacking.get('initial_value')}"
    )

    # Verify content deductions
    deductions = unstacking.get("content_deductions", {})
    result.check(
        abs(deductions.get("copper", 0) - 3000.0) < 0.01,
        f"Expected copper deduction $3,000, got {deductions.get('copper')}"
    )
    result.check(
        abs(deductions.get("steel", 0) - 1000.0) < 0.01,
        f"Expected steel deduction $1,000, got {deductions.get('steel')}"
    )
    result.check(
        abs(deductions.get("aluminum", 0) - 1000.0) < 0.01,
        f"Expected aluminum deduction $1,000, got {deductions.get('aluminum')}"
    )

    # Verify remaining_value (this is the IEEPA base)
    result.check(
        abs(unstacking.get("remaining_value", 0) - 5000.0) < 0.01,
        f"Expected remaining_value $5,000, got {unstacking.get('remaining_value')}"
    )

    # Verify total duty with unstacking
    expected_duty = 2500 + 1000 + 1500 + 500 + 250 + 500  # = $6,250
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )

    # Verify effective rate
    expected_rate = expected_duty / 10000.0  # = 0.625 = 62.5%
    result.check(
        abs(total_duty.get("effective_rate", 0) - expected_rate) < 0.001,
        f"Expected effective rate {expected_rate*100:.1f}%, got {total_duty.get('effective_rate', 0)*100:.2f}%"
    )

    return result


def test_case_6_no_double_subtraction():
    """
    Test Case 6: Verify No Double-Subtraction in Unstacking - v4.0 Entries Format

    This test explicitly verifies that the unstacking logic only subtracts
    each material's content_value ONCE, even though we have multiple entries.

    v4.0 Architecture creates 4 entries:
    - Entry 1: non_metal slice ($5,000)
    - Entry 2: copper_slice ($3,000)
    - Entry 3: steel_slice ($1,000)
    - Entry 4: aluminum_slice ($1,000)

    If double-subtraction occurred with copper=$3,000, steel=$1,000, aluminum=$1,000:
    - Wrong: remaining = $10,000 - $6,000 - $2,000 - $2,000 = $0
    - Correct: remaining = $10,000 - $3,000 - $1,000 - $1,000 = $5,000

    This test catches the bug by:
    1. Checking remaining_value is exactly $5,000 (not $0 or negative)
    2. Verifying each material appears only ONCE in content_deductions
    3. Verifying content_deductions values match expected (not doubled)
    """
    result = TestResult("Test Case 6: No Double-Subtraction in Unstacking")

    stacking = StackingRAG(conversation_id="test-case-6")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable - double subtraction test",
        product_value=10000.0,
        materials={"copper": 0.30, "steel": 0.10, "aluminum": 0.10}
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    total_duty = output.get("total_duty", {})
    unstacking = total_duty.get("unstacking", {})

    # Key test: remaining_value should be $5,000, NOT $0 (which would indicate double-subtraction)
    remaining = unstacking.get("remaining_value", 0)
    result.check(
        abs(remaining - 5000.0) < 0.01,
        f"Double-subtraction bug! Expected remaining_value $5,000, got ${remaining:.2f}. "
        f"If $0 or negative, materials were subtracted twice."
    )

    # Verify each material is deducted exactly once at correct value
    deductions = unstacking.get("content_deductions", {})

    # Should have exactly 3 materials deducted
    result.check(
        len(deductions) == 3,
        f"Expected 3 materials in content_deductions, got {len(deductions)}: {list(deductions.keys())}"
    )

    # Copper should be $3,000 (not $6,000)
    copper_deduction = deductions.get("copper", 0)
    result.check(
        abs(copper_deduction - 3000.0) < 0.01,
        f"Copper deduction should be $3,000 (once), got ${copper_deduction:.2f}. "
        f"If $6,000, copper was subtracted twice."
    )

    # Steel should be $1,000 (not $2,000)
    steel_deduction = deductions.get("steel", 0)
    result.check(
        abs(steel_deduction - 1000.0) < 0.01,
        f"Steel deduction should be $1,000 (once), got ${steel_deduction:.2f}. "
        f"If $2,000, steel was subtracted twice."
    )

    # Aluminum should be $1,000 (not $2,000)
    aluminum_deduction = deductions.get("aluminum", 0)
    result.check(
        abs(aluminum_deduction - 1000.0) < 0.01,
        f"Aluminum deduction should be $1,000 (once), got ${aluminum_deduction:.2f}. "
        f"If $2,000, aluminum was subtracted twice."
    )

    # v4.0: Verify slice values in entries
    non_metal_entries = [e for e in entries if e.get("slice_type") == "non_metal"]
    if non_metal_entries:
        result.check(
            abs(non_metal_entries[0].get("line_value", 0) - 5000.0) < 0.01,
            f"Non-metal slice should be $5,000 (remaining after 232), got ${non_metal_entries[0].get('line_value', 0):.2f}"
        )

    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        result.check(
            abs(copper_entries[0].get("line_value", 0) - 3000.0) < 0.01,
            f"Copper slice should be $3,000 (30%), got ${copper_entries[0].get('line_value', 0):.2f}"
        )

    return result


# =============================================================================
# v4.0 Test Cases - Entry Slices and Annex II Exclusions
# =============================================================================

def test_v4_case_1_uk_chemical_annex_ii():
    """
    v4.0 Test Case 1: UK Chemical (Annex II Exempt)

    Input:
        HTS: 2934.99.9050 (Plasmid/Chemical)
        Country: UK
        Value: $1,000
        Materials: None

    Expected:
        - UK is subject to IEEPA Reciprocal
        - BUT HTS 2934.99 is in Annex II exclusion list (pharmaceuticals)
        - Output: 1 entry with 9903.01.32 (Annex II exempt), 0% duty

    This tests:
        1. Annex II prefix matching (2934.99 matches 293499 prefix)
        2. annex_ii_exempt variant resolution
        3. Single entry for non-metal product
    """
    result = TestResult("v4.0 Case 1: UK Chemical (Annex II Exempt)")

    stacking = StackingRAG(conversation_id="test-v4-uk-chemical")
    output = stacking.calculate_stacking(
        hts_code="2934.99.9050",
        country="UK",
        product_description="Plasmid DNA for research",
        product_value=1000.0,
        materials={}  # No metals
    )

    # v4.0: Check entries format
    entries = output.get("entries", [])
    result.check(
        len(entries) == 1,
        f"Expected 1 entry (full_product), got {len(entries)}"
    )

    if entries:
        entry = entries[0]
        result.check(
            entry.get("slice_type") == "full",
            f"Expected slice_type='full', got '{entry.get('slice_type')}'"
        )
        result.check(
            entry.get("line_value") == 1000.0,
            f"Expected line_value=$1,000, got {entry.get('line_value')}"
        )

        # Check the stack has Annex II exempt code
        stack = entry.get("stack", [])
        annex_ii_found = False
        for line in stack:
            if line.get("program_id") == "ieepa_reciprocal":
                result.check(
                    line.get("chapter_99_code") == "9903.01.32",
                    f"IEEPA Reciprocal should use 9903.01.32 (Annex II exempt), got {line.get('chapter_99_code')}"
                )
                result.check(
                    line.get("variant") == "annex_ii_exempt",
                    f"Expected variant='annex_ii_exempt', got '{line.get('variant')}'"
                )
                result.check(
                    line.get("action") == "exempt",
                    f"Expected action='exempt', got '{line.get('action')}'"
                )
                annex_ii_found = True

        result.check(
            annex_ii_found,
            "Expected IEEPA Reciprocal entry with Annex II exemption"
        )

    # Verify $0 total duty
    total_duty = output.get("total_duty", {})
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - 0.0) < 0.01,
        f"Expected $0 total duty (Annex II exempt), got ${total_duty.get('total_duty_amount', 0):.2f}"
    )

    return result


def test_v4_case_2_china_3_metal_cable():
    """
    v4.0 Test Case 2: China 3-Metal USB-C Cable

    Input:
        HTS: 8544.42.9090 (USB-C Cable)
        Country: China
        Value: $10,000
        Materials: copper=$3,000, steel=$1,000, aluminum=$1,000

    Expected: 4 ACE entries (non_metal + 3 metal slices)

    Entry 1: Non-metal slice ($5,000)
        Stack: 301[apply], Fentanyl[apply], Reciprocal[paid], Copper[disclaim], Steel[disclaim], Aluminum[disclaim]

    Entry 2: Copper slice ($3,000)
        Stack: 301[apply], Fentanyl[apply], Reciprocal[exempt], Copper[claim], Steel[disclaim], Aluminum[disclaim]

    Entry 3: Steel slice ($1,000)
        Stack: 301[apply], Fentanyl[apply], Reciprocal[exempt], Copper[disclaim], Steel[claim], Aluminum[disclaim]

    Entry 4: Aluminum slice ($1,000)
        Stack: 301[apply], Fentanyl[apply], Reciprocal[exempt], Copper[disclaim], Steel[disclaim], Aluminum[claim]

    Duty Calculation:
        - Section 301: $10,000 × 25% = $2,500
        - IEEPA Fentanyl: $10,000 × 10% = $1,000
        - 232 Copper: $3,000 × 50% = $1,500
        - 232 Steel: $1,000 × 50% = $500
        - 232 Aluminum: $1,000 × 25% = $250
        - IEEPA Reciprocal: $5,000 × 10% = $500 (on remaining_value)
        - Total: $6,250 (62.5%)
    """
    result = TestResult("v4.0 Case 2: China 3-Metal USB-C Cable")

    stacking = StackingRAG(conversation_id="test-v4-china-3-metal")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable with copper, steel, aluminum",
        product_value=10000.0,
        materials={"copper": 3000.0, "steel": 1000.0, "aluminum": 1000.0}  # Content VALUES
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Verify slice types
    slice_types = [e.get("slice_type") for e in entries]
    for expected in ["non_metal", "copper_slice", "steel_slice", "aluminum_slice"]:
        result.check(
            expected in slice_types,
            f"Missing slice_type '{expected}' in entries"
        )

    # Check non_metal entry
    non_metal_entries = [e for e in entries if e.get("slice_type") == "non_metal"]
    if non_metal_entries:
        non_metal = non_metal_entries[0]
        result.check(
            abs(non_metal.get("line_value", 0) - 5000.0) < 0.01,
            f"Non-metal slice should be $5,000, got ${non_metal.get('line_value', 0):.2f}"
        )

        # Check IEEPA Reciprocal is "paid" (taxable) on non_metal slice
        stack = non_metal.get("stack", [])
        for line in stack:
            if line.get("program_id") == "ieepa_reciprocal":
                result.check(
                    line.get("action") == "paid",
                    f"Non-metal: IEEPA Reciprocal should be 'paid', got '{line.get('action')}'"
                )
                result.check(
                    line.get("chapter_99_code") == "9903.01.25",
                    f"Non-metal: IEEPA Reciprocal should use 9903.01.25, got '{line.get('chapter_99_code')}'"
                )

    # Check copper_slice entry
    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        copper = copper_entries[0]
        result.check(
            abs(copper.get("line_value", 0) - 3000.0) < 0.01,
            f"Copper slice should be $3,000, got ${copper.get('line_value', 0):.2f}"
        )

        stack = copper.get("stack", [])
        for line in stack:
            # Copper: claim on copper_slice
            if line.get("program_id") == "section_232_copper":
                result.check(
                    line.get("action") == "claim",
                    f"Copper slice: 232 Copper should be 'claim', got '{line.get('action')}'"
                )
            # Steel: disclaim on copper_slice
            if line.get("program_id") == "section_232_steel":
                result.check(
                    line.get("action") == "disclaim",
                    f"Copper slice: 232 Steel should be 'disclaim', got '{line.get('action')}'"
                )
            # IEEPA Reciprocal: exempt (metal_exempt) on copper_slice
            if line.get("program_id") == "ieepa_reciprocal":
                result.check(
                    line.get("action") == "exempt",
                    f"Copper slice: IEEPA Reciprocal should be 'exempt', got '{line.get('action')}'"
                )
                result.check(
                    line.get("variant") == "metal_exempt",
                    f"Copper slice: IEEPA Reciprocal variant should be 'metal_exempt', got '{line.get('variant')}'"
                )

    # v4.0: Check unstacking info
    unstacking = output.get("unstacking", {})
    result.check(
        unstacking.get("initial_value") == 10000.0,
        f"Expected initial_value $10,000, got {unstacking.get('initial_value')}"
    )
    result.check(
        abs(unstacking.get("remaining_value", 0) - 5000.0) < 0.01,
        f"Expected remaining_value $5,000, got {unstacking.get('remaining_value')}"
    )

    # Verify total duty: $6,250
    total_duty = output.get("total_duty", {})
    expected_duty = 2500 + 1000 + 1500 + 500 + 250 + 500  # = $6,250
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )
    result.check(
        abs(total_duty.get("effective_rate", 0) - 0.625) < 0.001,
        f"Expected effective rate 62.5%, got {total_duty.get('effective_rate', 0)*100:.2f}%"
    )

    return result


def test_v4_case_3_germany_3_metal_cable():
    """
    v4.0 Test Case 3: Germany 3-Metal Cable (232 only, no China programs)

    Input:
        HTS: 8544.42.9090 (USB-C Cable)
        Country: Germany
        Value: $10,000
        Materials: copper=$3,000, steel=$1,000, aluminum=$1,000

    Expected: 4 ACE entries, but NO Section 301, IEEPA Fentanyl, or IEEPA Reciprocal

    Entry 1: Non-metal slice ($5,000)
        Stack: Copper[disclaim], Steel[disclaim], Aluminum[disclaim]

    Entry 2: Copper slice ($3,000)
        Stack: Copper[claim], Steel[disclaim], Aluminum[disclaim]

    Entry 3: Steel slice ($1,000)
        Stack: Copper[disclaim], Steel[claim], Aluminum[disclaim]

    Entry 4: Aluminum slice ($1,000)
        Stack: Copper[disclaim], Steel[disclaim], Aluminum[claim]

    Duty Calculation:
        - 232 Copper: $3,000 × 50% = $1,500
        - 232 Steel: $1,000 × 50% = $500
        - 232 Aluminum: $1,000 × 25% = $250
        - Total: $2,250 (22.5%)
    """
    result = TestResult("v4.0 Case 3: Germany 3-Metal Cable (232 only)")

    stacking = StackingRAG(conversation_id="test-v4-germany-3-metal")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="Germany",
        product_description="USB-C cable from Germany",
        product_value=10000.0,
        materials={"copper": 3000.0, "steel": 1000.0, "aluminum": 1000.0}  # Content VALUES
    )

    # v4.0: Check 4 entries
    entries = output.get("entries", [])
    result.check(
        len(entries) == 4,
        f"Expected 4 entries (non_metal + 3 metals), got {len(entries)}"
    )

    # Verify NO China-specific programs in any entry
    all_program_ids = set()
    for entry in entries:
        for line in entry.get("stack", []):
            all_program_ids.add(line.get("program_id"))

    result.check(
        "section_301" not in all_program_ids,
        "Section 301 should NOT appear for Germany"
    )
    result.check(
        "ieepa_fentanyl" not in all_program_ids,
        "IEEPA Fentanyl should NOT appear for Germany"
    )
    result.check(
        "ieepa_reciprocal" not in all_program_ids,
        "IEEPA Reciprocal should NOT appear for Germany"
    )

    # Verify 232 programs ARE present
    result.check(
        "section_232_copper" in all_program_ids,
        "Section 232 Copper should appear for Germany"
    )
    result.check(
        "section_232_steel" in all_program_ids,
        "Section 232 Steel should appear for Germany"
    )
    result.check(
        "section_232_aluminum" in all_program_ids,
        "Section 232 Aluminum should appear for Germany"
    )

    # Verify total duty: $2,250
    total_duty = output.get("total_duty", {})
    expected_duty = 1500 + 500 + 250  # = $2,250
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )
    result.check(
        abs(total_duty.get("effective_rate", 0) - 0.225) < 0.001,
        f"Expected effective rate 22.5%, got {total_duty.get('effective_rate', 0)*100:.2f}%"
    )

    return result


def test_v4_case_4_china_single_metal():
    """
    v4.0 Test Case 4: China Single-Metal (Copper only)

    Input:
        HTS: 8544.42.9090 (USB-C Cable)
        Country: China
        Value: $10,000
        Materials: copper=$3,000 (only)

    Expected: 2 ACE entries (non_metal + copper_slice)

    Entry 1: Non-metal slice ($7,000)
        Stack: 301[apply], Fentanyl[apply], Reciprocal[paid], Copper[disclaim], Steel[disclaim], Aluminum[disclaim]

    Entry 2: Copper slice ($3,000)
        Stack: 301[apply], Fentanyl[apply], Reciprocal[exempt], Copper[claim], Steel[disclaim], Aluminum[disclaim]

    Duty Calculation:
        - Section 301: $10,000 × 25% = $2,500
        - IEEPA Fentanyl: $10,000 × 10% = $1,000
        - 232 Copper: $3,000 × 50% = $1,500
        - IEEPA Reciprocal: $7,000 × 10% = $700 (on remaining_value)
        - Total: $5,700 (57.0%)
    """
    result = TestResult("v4.0 Case 4: China Single-Metal (Copper only)")

    stacking = StackingRAG(conversation_id="test-v4-china-single-metal")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable with copper only",
        product_value=10000.0,
        materials={"copper": 3000.0}  # Only copper
    )

    # v4.0: Check 2 entries (no steel/aluminum slices)
    entries = output.get("entries", [])
    result.check(
        len(entries) == 2,
        f"Expected 2 entries (non_metal + copper_slice), got {len(entries)}"
    )

    # Verify slice types
    slice_types = [e.get("slice_type") for e in entries]
    result.check(
        "non_metal" in slice_types,
        "Missing 'non_metal' slice"
    )
    result.check(
        "copper_slice" in slice_types,
        "Missing 'copper_slice' slice"
    )
    result.check(
        "steel_slice" not in slice_types,
        "Should NOT have 'steel_slice' (no steel content)"
    )
    result.check(
        "aluminum_slice" not in slice_types,
        "Should NOT have 'aluminum_slice' (no aluminum content)"
    )

    # Check non_metal slice value
    non_metal_entries = [e for e in entries if e.get("slice_type") == "non_metal"]
    if non_metal_entries:
        non_metal = non_metal_entries[0]
        result.check(
            abs(non_metal.get("line_value", 0) - 7000.0) < 0.01,
            f"Non-metal slice should be $7,000, got ${non_metal.get('line_value', 0):.2f}"
        )

    # Check copper slice value
    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        copper = copper_entries[0]
        result.check(
            abs(copper.get("line_value", 0) - 3000.0) < 0.01,
            f"Copper slice should be $3,000, got ${copper.get('line_value', 0):.2f}"
        )

    # v4.0: Check unstacking
    unstacking = output.get("unstacking", {})
    result.check(
        abs(unstacking.get("remaining_value", 0) - 7000.0) < 0.01,
        f"Expected remaining_value $7,000, got {unstacking.get('remaining_value')}"
    )

    # Verify total duty: $5,700
    total_duty = output.get("total_duty", {})
    expected_duty = 2500 + 1000 + 1500 + 700  # = $5,700
    result.check(
        abs(total_duty.get("total_duty_amount", 0) - expected_duty) < 0.01,
        f"Expected total duty ${expected_duty:.2f}, got ${total_duty.get('total_duty_amount', 0):.2f}"
    )
    result.check(
        abs(total_duty.get("effective_rate", 0) - 0.57) < 0.001,
        f"Expected effective rate 57.0%, got {total_duty.get('effective_rate', 0)*100:.2f}%"
    )

    return result


def test_v4_entries_filing_lines_consistency():
    """
    v4.0 Test: Verify entries.stack and filing_lines are consistent.

    The filing_lines should be a flattened view of all entries.stack
    for backwards compatibility.
    """
    result = TestResult("v4.0: Entries/Filing Lines Consistency")

    stacking = StackingRAG(conversation_id="test-v4-consistency")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable",
        product_value=10000.0,
        materials={"copper": 3000.0, "steel": 1000.0, "aluminum": 1000.0}
    )

    entries = output.get("entries", [])
    filing_lines = output.get("filing_lines", [])

    # Count total lines in all entry stacks
    total_stack_lines = sum(len(e.get("stack", [])) for e in entries)

    result.check(
        len(filing_lines) == total_stack_lines,
        f"filing_lines count ({len(filing_lines)}) should match sum of entry stacks ({total_stack_lines})"
    )

    # Verify all chapter_99_codes from entries appear in filing_lines
    entry_codes = set()
    for entry in entries:
        for line in entry.get("stack", []):
            entry_codes.add(line.get("chapter_99_code"))

    filing_codes = set(line.get("chapter_99_code") for line in filing_lines)

    result.check(
        entry_codes == filing_codes,
        f"Chapter 99 codes mismatch. Entries: {entry_codes}, Filing: {filing_codes}"
    )

    return result


def test_decision_audit_trail():
    """
    Test that all decisions have proper audit trail with sources.
    """
    result = TestResult("Test: Decision Audit Trail")

    stacking = StackingRAG(conversation_id="test-audit")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="USB-C cable",
        product_value=10000.0,
        materials={"copper": 0.05, "steel": 0.20, "aluminum": 0.72}
    )

    decisions = output.get("decisions", [])

    # Verify we have decisions
    result.check(
        len(decisions) > 0,
        "Expected decisions in audit trail"
    )

    # Check each decision has required fields
    required_fields = ["step", "program_id", "decision"]
    for d in decisions:
        for field in required_fields:
            result.check(
                field in d,
                f"Decision missing field: {field}"
            )

    # Verify source documents are present for key decisions
    has_source = any(d.get("source_doc") for d in decisions)
    result.check(
        has_source,
        "Expected at least one decision with source_doc"
    )

    return result


def run_all_tests(verbose=False):
    """Run all test cases and report results."""
    tests = [
        # Phase 6/6.5 tests (legacy flat format)
        test_case_1_usb_c_china_full,
        test_case_2_high_steel,
        test_case_3_all_materials_10_percent,  # Renamed for Phase 6
        test_case_4_non_china_origin,
        test_case_5_ieepa_unstacking,  # Phase 6.5: IEEPA Unstacking
        test_case_6_no_double_subtraction,  # Phase 6.5: Verify no double-subtraction bug
        test_decision_audit_trail,
        # v4.0 tests (Entry Slices and Annex II)
        test_v4_case_1_uk_chemical_annex_ii,  # Annex II exemption
        test_v4_case_2_china_3_metal_cable,  # 4 entries (non_metal + 3 metals)
        test_v4_case_3_germany_3_metal_cable,  # 232 only, no China programs
        test_v4_case_4_china_single_metal,  # 2 entries (non_metal + copper)
        test_v4_entries_filing_lines_consistency,  # Verify entries == filing_lines
    ]

    print("=" * 60)
    print("Stacking Feature - Automated Test Suite")
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

    # Print detailed failures if any
    if failed > 0 and not verbose:
        print("\nRun with -v for detailed failure information")

    return failed == 0


if __name__ == "__main__":
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    success = run_all_tests(verbose=verbose)
    sys.exit(0 if success else 1)
