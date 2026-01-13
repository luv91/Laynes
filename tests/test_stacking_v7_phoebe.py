#!/usr/bin/env python
"""
v7.0 Test Suite: Phoebe-Aligned ACE Filing Model

Tests the Phoebe-aligned changes to tariff stacking:
- disclaim_behavior: 'required' (copper), 'omit' (steel/aluminum), 'none' (other)
- Copper disclaim appears in ALL non-copper slices when copper is applicable
- Steel/Aluminum are OMITTED entirely when not claimed (no disclaim line)
- HTS-specific claim_codes from section_232_materials table
- 301 codes come from section_301_inclusions table

Test Cases (from docs/readme11.md):
- TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)
- TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)
- TC-v7.0-003: No 232 Claimed (Residual Only)
- TC-v7.0-004: Copper Full Claim
- TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)
- TC-v7.0-006: Annex II Exemption

Usage:
    pipenv run python tests/test_stacking_v7_phoebe.py
    pipenv run python tests/test_stacking_v7_phoebe.py -v  # verbose
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
# v7.0 Phoebe Example Test Cases
# =============================================================================

def test_v7_001_steel_aluminum_50_50():
    """
    TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)

    Source: Phoebe Example 1

    Input:
        HTS: 9403.99.9045 (Furniture parts)
        Country: CN
        Value: $123.12
        Quantity: 6
        Materials: steel=$61.56, aluminum=$61.56

    Expected:
        - 2 slices (steel_claim, aluminum_claim)
        - NO residual slice (all value allocated to metals)
        - Steel uses derivative code 9903.81.91 (not 9903.80.01)
        - No copper codes (copper not applicable to this HTS)
        - No steel disclaim in aluminum slice (steel omitted)
        - No aluminum disclaim in steel slice (aluminum omitted)

    Key v7.0 behaviors tested:
        1. disclaim_behavior='omit' for steel - no steel code in aluminum slice
        2. disclaim_behavior='omit' for aluminum - no aluminum code in steel slice
        3. HTS-specific claim_code (9903.81.91 for derivative steel)
    """
    result = TestResult("TC-v7.0-001: Steel + Aluminum Claim (50/50 Split)")

    stacking = StackingRAG(conversation_id="test-v7-001")
    output = stacking.calculate_stacking(
        hts_code="9403.99.9045",
        country="China",
        product_description="Metal furniture parts",
        product_value=123.12,
        materials={"steel": 61.56, "aluminum": 61.56}
    )

    entries = output.get("entries", [])

    # Check for 2 slices (no residual - all value allocated to metals)
    result.check(
        len(entries) == 2,
        f"Expected 2 entries (steel + aluminum, no residual), got {len(entries)}"
    )

    # Check slice types
    slice_types = [e.get("slice_type") for e in entries]
    result.check(
        "steel_slice" in slice_types,
        f"Missing steel_slice. Got: {slice_types}"
    )
    result.check(
        "aluminum_slice" in slice_types,
        f"Missing aluminum_slice. Got: {slice_types}"
    )

    # Check steel slice
    steel_entries = [e for e in entries if e.get("slice_type") == "steel_slice"]
    if steel_entries:
        steel = steel_entries[0]
        stack = steel.get("stack", [])

        # Find steel claim code
        steel_codes = [l for l in stack if l.get("program_id") == "section_232_steel"]
        result.check(
            len(steel_codes) == 1,
            f"Expected exactly 1 steel code in steel slice, got {len(steel_codes)}"
        )
        if steel_codes:
            # v7.0: HTS-specific code - 9903.81.91 for derivative steel
            result.check(
                steel_codes[0].get("chapter_99_code") == "9903.81.91",
                f"Steel slice: Expected derivative code 9903.81.91, got {steel_codes[0].get('chapter_99_code')}"
            )
            result.check(
                steel_codes[0].get("action") == "claim",
                f"Steel slice: Expected action='claim', got {steel_codes[0].get('action')}"
            )

        # v7.0: NO aluminum code in steel slice (disclaim_behavior='omit')
        aluminum_codes = [l for l in stack if l.get("program_id") == "section_232_aluminum"]
        result.check(
            len(aluminum_codes) == 0,
            f"Steel slice should NOT have aluminum code (omit behavior), but found {len(aluminum_codes)}"
        )

        # No copper code (copper not applicable to this HTS)
        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]
        result.check(
            len(copper_codes) == 0,
            f"Steel slice should NOT have copper code (not applicable), but found {len(copper_codes)}"
        )

    # Check aluminum slice
    aluminum_entries = [e for e in entries if e.get("slice_type") == "aluminum_slice"]
    if aluminum_entries:
        aluminum = aluminum_entries[0]
        stack = aluminum.get("stack", [])

        # Find aluminum claim code
        alum_codes = [l for l in stack if l.get("program_id") == "section_232_aluminum"]
        result.check(
            len(alum_codes) == 1,
            f"Expected exactly 1 aluminum code in aluminum slice, got {len(alum_codes)}"
        )
        if alum_codes:
            result.check(
                alum_codes[0].get("chapter_99_code") == "9903.85.08",
                f"Aluminum slice: Expected 9903.85.08, got {alum_codes[0].get('chapter_99_code')}"
            )
            result.check(
                alum_codes[0].get("action") == "claim",
                f"Aluminum slice: Expected action='claim', got {alum_codes[0].get('action')}"
            )

        # v7.0: NO steel code in aluminum slice (disclaim_behavior='omit')
        steel_codes = [l for l in stack if l.get("program_id") == "section_232_steel"]
        result.check(
            len(steel_codes) == 0,
            f"Aluminum slice should NOT have steel code (omit behavior), but found {len(steel_codes)}"
        )

    return result


def test_v7_002_copper_aluminum_50_50():
    """
    TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)

    Source: Phoebe Example 2

    Input:
        HTS: 8544.42.9090
        Country: CN
        Value: $36.00
        Quantity: 3
        Materials: copper=$18.00, aluminum=$18.00

    Expected:
        - 2 slices (copper_claim, aluminum_claim)
        - Copper disclaim (9903.78.02) appears in aluminum slice
        - Aluminum is OMITTED in copper slice (not disclaimed)

    Key v7.0 behaviors tested:
        1. disclaim_behavior='required' for copper - copper disclaim in aluminum slice
        2. disclaim_behavior='omit' for aluminum - no aluminum code in copper slice
    """
    result = TestResult("TC-v7.0-002: Copper + Aluminum Claim (50/50 Split)")

    stacking = StackingRAG(conversation_id="test-v7-002")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Insulated cable with copper and aluminum",
        product_value=36.00,
        materials={"copper": 18.00, "aluminum": 18.00}
    )

    entries = output.get("entries", [])

    # Check for 2 slices
    result.check(
        len(entries) == 2,
        f"Expected 2 entries (copper + aluminum), got {len(entries)}"
    )

    # Check aluminum slice - should have copper DISCLAIM (required behavior)
    aluminum_entries = [e for e in entries if e.get("slice_type") == "aluminum_slice"]
    if aluminum_entries:
        aluminum = aluminum_entries[0]
        stack = aluminum.get("stack", [])

        # v7.0: Copper DISCLAIM should be present in aluminum slice
        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]
        result.check(
            len(copper_codes) == 1,
            f"Aluminum slice should have copper disclaim (required behavior), got {len(copper_codes)}"
        )
        if copper_codes:
            result.check(
                copper_codes[0].get("chapter_99_code") == "9903.78.02",
                f"Copper disclaim code should be 9903.78.02, got {copper_codes[0].get('chapter_99_code')}"
            )
            result.check(
                copper_codes[0].get("action") == "disclaim",
                f"Copper in aluminum slice should be 'disclaim', got {copper_codes[0].get('action')}"
            )

        # Aluminum should be CLAIM in its own slice
        alum_codes = [l for l in stack if l.get("program_id") == "section_232_aluminum"]
        result.check(
            len(alum_codes) == 1,
            f"Aluminum slice should have aluminum claim, got {len(alum_codes)}"
        )
        if alum_codes:
            result.check(
                alum_codes[0].get("action") == "claim",
                f"Aluminum in aluminum slice should be 'claim', got {alum_codes[0].get('action')}"
            )

    # Check copper slice - should NOT have aluminum code (omit behavior)
    copper_entries = [e for e in entries if e.get("slice_type") == "copper_slice"]
    if copper_entries:
        copper = copper_entries[0]
        stack = copper.get("stack", [])

        # v7.0: NO aluminum code in copper slice (disclaim_behavior='omit')
        alum_codes = [l for l in stack if l.get("program_id") == "section_232_aluminum"]
        result.check(
            len(alum_codes) == 0,
            f"Copper slice should NOT have aluminum code (omit behavior), but found {len(alum_codes)}"
        )

        # Copper should be CLAIM in its own slice
        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]
        result.check(
            len(copper_codes) == 1,
            f"Copper slice should have copper claim, got {len(copper_codes)}"
        )
        if copper_codes:
            result.check(
                copper_codes[0].get("action") == "claim",
                f"Copper in copper slice should be 'claim', got {copper_codes[0].get('action')}"
            )

    return result


def test_v7_003_no_232_claimed():
    """
    TC-v7.0-003: No 232 Claimed (Residual Only)

    Source: Phoebe Example 3

    UPDATED: Use HTS 8539.50.0000 (LED lamps) which is in 301 but NOT in 232 scope
    per Federal Register 90 FR 40326 (removed from 232 derivative lists)

    Input:
        HTS: 8539.50.0000 (LED lamps)
        Country: CN
        Value: $174.00
        Quantity: 3
        Materials: {} (none)

    Expected:
        - 1 slice (residual/full)
        - NO 232 codes at all (HTS not in any 232 scope)
        - Uses 9903.88.03 (List 3) for Section 301
        - Uses 9903.01.25 (paid) for IEEPA Reciprocal

    Key v7.0 behaviors tested:
        1. No 232 materials in HTS scope means no 232 codes at all
        2. 301 code comes from section_301_inclusions (list-specific)
    """
    result = TestResult("TC-v7.0-003: No 232 Claimed (Residual Only)")

    stacking = StackingRAG(conversation_id="test-v7-003")
    output = stacking.calculate_stacking(
        hts_code="8539.50.0000",  # LED lamps - NOT in 232 scope
        country="China",
        product_description="LED lamps and light fixtures",
        product_value=174.00,
        materials={}  # No metals
    )

    entries = output.get("entries", [])

    # Check for 1 slice (full product)
    result.check(
        len(entries) == 1,
        f"Expected 1 entry (full/residual), got {len(entries)}"
    )

    if entries:
        entry = entries[0]
        stack = entry.get("stack", [])

        # v7.0: NO 232 codes at all
        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]
        steel_codes = [l for l in stack if l.get("program_id") == "section_232_steel"]
        alum_codes = [l for l in stack if l.get("program_id") == "section_232_aluminum"]

        result.check(
            len(copper_codes) == 0,
            f"Should have NO copper codes, but found {len(copper_codes)}"
        )
        result.check(
            len(steel_codes) == 0,
            f"Should have NO steel codes, but found {len(steel_codes)}"
        )
        result.check(
            len(alum_codes) == 0,
            f"Should have NO aluminum codes, but found {len(alum_codes)}"
        )

        # Check 301 code is from List 3 (9903.88.03) for LED lamps
        s301_codes = [l for l in stack if l.get("program_id") == "section_301"]
        if s301_codes:
            result.check(
                s301_codes[0].get("chapter_99_code") == "9903.88.03",
                f"301 code should be 9903.88.03 (List 3), got {s301_codes[0].get('chapter_99_code')}"
            )

        # Check IEEPA Reciprocal is paid (9903.01.25)
        recip_codes = [l for l in stack if l.get("program_id") == "ieepa_reciprocal"]
        if recip_codes:
            result.check(
                recip_codes[0].get("chapter_99_code") == "9903.01.25",
                f"IEEPA Reciprocal should be 9903.01.25 (paid), got {recip_codes[0].get('chapter_99_code')}"
            )

    return result


def test_v7_004_copper_full_claim():
    """
    TC-v7.0-004: Copper Full Claim

    Source: Phoebe Example 4

    Input:
        HTS: 8544.42.2000
        Country: CN
        Value: $66.00
        Quantity: 6
        Materials: copper=$66.00

    Expected:
        - 1 slice (copper_claim)
        - No residual (100% copper)
        - Copper claim code 9903.78.01
    """
    result = TestResult("TC-v7.0-004: Copper Full Claim")

    stacking = StackingRAG(conversation_id="test-v7-004")
    output = stacking.calculate_stacking(
        hts_code="8544.42.2000",
        country="China",
        product_description="Copper insulated cable",
        product_value=66.00,
        materials={"copper": 66.00}
    )

    entries = output.get("entries", [])

    # Check for 1 slice (all copper, no residual)
    result.check(
        len(entries) == 1,
        f"Expected 1 entry (copper_slice), got {len(entries)}"
    )

    if entries:
        entry = entries[0]
        result.check(
            entry.get("slice_type") == "copper_slice",
            f"Expected slice_type='copper_slice', got {entry.get('slice_type')}"
        )

        stack = entry.get("stack", [])
        copper_codes = [l for l in stack if l.get("program_id") == "section_232_copper"]

        result.check(
            len(copper_codes) == 1,
            f"Expected 1 copper code, got {len(copper_codes)}"
        )
        if copper_codes:
            result.check(
                copper_codes[0].get("chapter_99_code") == "9903.78.01",
                f"Copper claim code should be 9903.78.01, got {copper_codes[0].get('chapter_99_code')}"
            )
            result.check(
                copper_codes[0].get("action") == "claim",
                f"Copper action should be 'claim', got {copper_codes[0].get('action')}"
            )

    return result


def test_v7_005_steel_aluminum_with_residual():
    """
    TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)

    Source: Phoebe Example 5

    Input:
        HTS: 9403.99.9045
        Country: CN
        Value: $3,348.00
        Quantity: 18
        Materials: steel=$3,046.68, aluminum=$21.09

    Expected:
        - 3 slices (residual, steel_claim, aluminum_claim)
        - Residual slice: NO steel disclaim, NO aluminum disclaim
        - Steel slice: Uses 9903.81.91 (derivative)
    """
    result = TestResult("TC-v7.0-005: Steel + Aluminum with Residual (3 Slices)")

    stacking = StackingRAG(conversation_id="test-v7-005")
    output = stacking.calculate_stacking(
        hts_code="9403.99.9045",
        country="China",
        product_description="Metal furniture parts with mixed metals",
        product_value=3348.00,
        materials={"steel": 3046.68, "aluminum": 21.09}
    )

    entries = output.get("entries", [])

    # Check for 3 slices
    result.check(
        len(entries) == 3,
        f"Expected 3 entries (residual + steel + aluminum), got {len(entries)}"
    )

    slice_types = [e.get("slice_type") for e in entries]
    result.check(
        "non_metal" in slice_types or "full" in slice_types,
        f"Missing residual/non_metal slice. Got: {slice_types}"
    )
    result.check(
        "steel_slice" in slice_types,
        f"Missing steel_slice. Got: {slice_types}"
    )
    result.check(
        "aluminum_slice" in slice_types,
        f"Missing aluminum_slice. Got: {slice_types}"
    )

    # Check residual slice - should have NO 232 codes (omit behavior)
    residual_entries = [e for e in entries if e.get("slice_type") in ["non_metal", "full"]]
    if residual_entries:
        residual = residual_entries[0]
        stack = residual.get("stack", [])

        # v7.0: NO steel disclaim in residual (omit behavior)
        steel_codes = [l for l in stack if l.get("program_id") == "section_232_steel"]
        result.check(
            len(steel_codes) == 0,
            f"Residual should NOT have steel code (omit behavior), but found {len(steel_codes)}"
        )

        # v7.0: NO aluminum disclaim in residual (omit behavior)
        alum_codes = [l for l in stack if l.get("program_id") == "section_232_aluminum"]
        result.check(
            len(alum_codes) == 0,
            f"Residual should NOT have aluminum code (omit behavior), but found {len(alum_codes)}"
        )

        # Check residual value is approximately $280.23
        expected_residual = 3348.00 - 3046.68 - 21.09  # = $280.23
        result.check(
            abs(residual.get("line_value", 0) - expected_residual) < 0.10,
            f"Residual value should be ~${expected_residual:.2f}, got ${residual.get('line_value', 0):.2f}"
        )

    return result


def test_v7_006_annex_ii_exemption():
    """
    TC-v7.0-006: Annex II Exemption

    Source: Phoebe Example 6

    Input:
        HTS: 8473.30.5100 (Computer parts)
        Country: CN
        Value: $842.40
        Quantity: 27
        Materials: aluminum=$126.36
        Import Date: 2024-07-15 (inside exclusion window: 2024-06-15 to 2025-05-31)

    Expected:
        - 2 slices (residual, aluminum_claim)
        - Uses 9903.01.32 (Annex II exempt) for IEEPA Reciprocal
        - Uses 9903.88.69 (Section 301 exclusion) - takes precedence over 9903.88.03

    Note: The exclusion code 9903.88.69 is only valid within its time window.
    After 2025-05-31, the base duty code 9903.88.03 (List 3) applies.
    """
    result = TestResult("TC-v7.0-006: Annex II Exemption")

    stacking = StackingRAG(conversation_id="test-v7-006")
    output = stacking.calculate_stacking(
        hts_code="8473.30.5100",
        country="China",
        product_description="Computer parts with aluminum housing",
        product_value=842.40,
        materials={"aluminum": 126.36},
        import_date="2024-07-15"  # Date inside exclusion window
    )

    entries = output.get("entries", [])

    # Check for 2 slices
    result.check(
        len(entries) == 2,
        f"Expected 2 entries (residual + aluminum), got {len(entries)}"
    )

    # Check that Annex II exempt code is used for IEEPA Reciprocal
    for entry in entries:
        stack = entry.get("stack", [])
        recip_codes = [l for l in stack if l.get("program_id") == "ieepa_reciprocal"]

        if recip_codes:
            result.check(
                recip_codes[0].get("chapter_99_code") == "9903.01.32",
                f"IEEPA Reciprocal should use 9903.01.32 (Annex II exempt), got {recip_codes[0].get('chapter_99_code')}"
            )
            result.check(
                recip_codes[0].get("variant") == "annex_ii_exempt",
                f"IEEPA Reciprocal variant should be 'annex_ii_exempt', got {recip_codes[0].get('variant')}"
            )

        # Check 301 code is 9903.88.69
        s301_codes = [l for l in stack if l.get("program_id") == "section_301"]
        if s301_codes:
            result.check(
                s301_codes[0].get("chapter_99_code") == "9903.88.69",
                f"301 code should be 9903.88.69, got {s301_codes[0].get('chapter_99_code')}"
            )

    return result


def test_v7_007_derivative_article_note16():
    """
    TC-v7.0-007: Derivative Article - Note 16 Full Value Assessment

    Source: Design Flaw Fix (readme-design-flaws-1-document.md)

    This test verifies the fix for derivative articles per U.S. Note 16 to Chapter 99.

    Input:
        HTS: 7317.00.5502 (Steel nails - Chapter 73 derivative article)
        Country: CN
        Value: $10,000
        Materials: steel=$6,000 (60%)

    Expected:
        - 1 slice with full $10,000 value (NOT $6,000 content value)
        - Section 232 code: 9903.81.89 (derivative, NOT 9903.80.01 primary)
        - IEEPA Reciprocal: 9903.01.33 @ 0% (Note 16 full exempt)
        - Total duty: $8,500 (85%), NOT $6,900 (69%)

    Key behaviors tested:
        1. article_type='derivative' triggers full value assessment
        2. Derivative steel uses 9903.81.89 (not primary code 9903.80.01)
        3. IEEPA Reciprocal is 100% exempt for derivative articles (Note 16)
    """
    result = TestResult("TC-v7.0-007: Derivative Article - Note 16 Full Value (Steel Nails)")

    stacking = StackingRAG(conversation_id="test-v7-007")
    output = stacking.calculate_stacking(
        hts_code="7317.00.5502",
        country="China",
        product_description="Steel nails (Ch 73 derivative)",
        product_value=10000.00,
        materials={"steel": 6000.00}
    )

    entries = output.get("entries", [])

    # Check for single slice
    result.check(
        len(entries) == 1,
        f"Expected 1 entry (full value, no slicing), got {len(entries)}"
    )

    if entries:
        entry = entries[0]

        # Check line value is full $10,000 (not $6,000 steel content)
        result.check(
            abs(entry.get("line_value", 0) - 10000.00) < 0.01,
            f"Line value should be $10,000.00 (full), got ${entry.get('line_value', 0):.2f}"
        )

        stack = entry.get("stack", [])

        # Check Section 232 Steel code is derivative (9903.81.89)
        steel_codes = [l for l in stack if l.get("program_id") == "section_232_steel"]
        result.check(
            len(steel_codes) == 1,
            f"Expected 1 Section 232 Steel code, got {len(steel_codes)}"
        )
        if steel_codes:
            result.check(
                steel_codes[0].get("chapter_99_code") == "9903.81.89",
                f"Section 232 Steel should use derivative code 9903.81.89, got {steel_codes[0].get('chapter_99_code')}"
            )

        # Check IEEPA Reciprocal is Note 16 exempt (9903.01.33 @ 0%)
        recip_codes = [l for l in stack if l.get("program_id") == "ieepa_reciprocal"]
        result.check(
            len(recip_codes) == 1,
            f"Expected 1 IEEPA Reciprocal code, got {len(recip_codes)}"
        )
        if recip_codes:
            result.check(
                recip_codes[0].get("chapter_99_code") == "9903.01.33",
                f"IEEPA Reciprocal should be 9903.01.33 (Note 16 exempt), got {recip_codes[0].get('chapter_99_code')}"
            )
            result.check(
                recip_codes[0].get("variant") == "note16_full_exempt",
                f"IEEPA Reciprocal variant should be 'note16_full_exempt', got {recip_codes[0].get('variant')}"
            )
            result.check(
                recip_codes[0].get("duty_rate") == 0.0,
                f"IEEPA Reciprocal duty_rate should be 0.0, got {recip_codes[0].get('duty_rate')}"
            )

    # Check total duty is $8,500 (85%)
    total_duty = output.get("total_duty", {})
    if isinstance(total_duty, dict):
        duty_amount = total_duty.get("total_duty_amount", 0)
        effective_rate = total_duty.get("effective_rate", 0)
    else:
        duty_amount = total_duty or 0
        effective_rate = 0

    result.check(
        abs(duty_amount - 8500.00) < 0.01,
        f"Total duty should be $8,500.00, got ${duty_amount:.2f}"
    )
    result.check(
        abs(effective_rate - 0.85) < 0.001,
        f"Effective rate should be 85%, got {effective_rate*100:.1f}%"
    )

    return result


def test_v7_no_steel_aluminum_disclaim_codes():
    """
    TC-v7.0-008: No Steel/Aluminum Disclaim Codes

    Verify steel/aluminum disclaim codes NEVER appear in any output.

    Input:
        HTS: 8544.42.9090
        Country: CN
        Value: $1,000
        Materials: copper=$1,000

    Expected:
        - NO 9903.80.02 (steel disclaim) in output
        - NO 9903.85.09 (aluminum disclaim) in output
    """
    result = TestResult("TC-v7.0-008: No Steel/Aluminum Disclaim Codes")

    stacking = StackingRAG(conversation_id="test-v7-008")
    output = stacking.calculate_stacking(
        hts_code="8544.42.9090",
        country="China",
        product_description="Copper cable",
        product_value=1000.00,
        materials={"copper": 1000.00}
    )

    entries = output.get("entries", [])

    # Collect all chapter_99_codes from all stacks
    all_codes = []
    for entry in entries:
        for line in entry.get("stack", []):
            all_codes.append(line.get("chapter_99_code"))

    # v7.0: Steel disclaim should NEVER appear
    result.check(
        "9903.80.02" not in all_codes,
        f"Steel disclaim (9903.80.02) should NEVER appear, but found in {all_codes}"
    )

    # v7.0: Aluminum disclaim should NEVER appear
    result.check(
        "9903.85.09" not in all_codes,
        f"Aluminum disclaim (9903.85.09) should NEVER appear, but found in {all_codes}"
    )

    return result


# =============================================================================
# Main Test Runner
# =============================================================================

def run_all_tests(verbose=False):
    """Run all v7.0 Phoebe test cases."""
    tests = [
        test_v7_001_steel_aluminum_50_50,
        test_v7_002_copper_aluminum_50_50,
        test_v7_003_no_232_claimed,
        test_v7_004_copper_full_claim,
        test_v7_005_steel_aluminum_with_residual,
        test_v7_006_annex_ii_exemption,
        test_v7_007_derivative_article_note16,  # New: Ch 73 derivative full value test
        test_v7_no_steel_aluminum_disclaim_codes,
    ]

    print("=" * 60)
    print("v7.0 Phoebe-Aligned ACE Filing - Test Suite")
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
