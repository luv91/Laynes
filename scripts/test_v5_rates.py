#!/usr/bin/env python3
"""
Test script for v5.0 country-specific tariff rates.

Verifies:
- Germany (EU): 15% ceiling rule for IEEPA Reciprocal
- UK: 232 Steel/Aluminum exception (25% not 50%)
- China: Full tariffs (301, Fentanyl, 232, Reciprocal)
- Vietnam: Default rates (50% 232, 10% Reciprocal)

Expected results from plan:
- Germany: $3,120 (31.2%)
- UK: $2,500 (25%)
- China: $6,500 (65%)
- Vietnam: $3,000 (30%)
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.chat.tools.stacking_tools import (
    get_country_group,
    get_rate_for_program,
    get_mfn_base_rate,
    get_flask_app
)


def test_country_groups():
    """Test country group mappings."""
    print("=" * 60)
    print("Testing Country Group Mappings")
    print("=" * 60)

    test_cases = [
        ("Germany", "EU"),
        ("DE", "EU"),
        ("United Kingdom", "UK"),
        ("UK", "UK"),
        ("China", "CN"),
        ("CN", "CN"),
        ("Vietnam", "default"),
        ("Japan", "default"),
    ]

    app = get_flask_app()
    with app.app_context():
        for country, expected in test_cases:
            result = get_country_group(country)
            status = "✓" if result == expected else "✗"
            print(f"  {status} {country} -> {result} (expected: {expected})")


def test_mfn_base_rates():
    """Test MFN base rate lookups."""
    print("\n" + "=" * 60)
    print("Testing MFN Base Rate Lookups")
    print("=" * 60)

    test_cases = [
        ("8544.42.9090", 0.026),  # USB-C cables: 2.6%
        ("8539.50.00", 0.02),     # LED lamps: 2%
        ("8471.30.01", 0.0),      # Laptops: 0%
    ]

    app = get_flask_app()
    with app.app_context():
        for hts_code, expected in test_cases:
            result = get_mfn_base_rate(hts_code)
            status = "✓" if abs(result - expected) < 0.001 else "✗"
            print(f"  {status} HTS {hts_code} -> {result*100:.1f}% (expected: {expected*100:.1f}%)")


def test_program_rates():
    """Test country-specific program rates."""
    print("\n" + "=" * 60)
    print("Testing Program Rates by Country")
    print("=" * 60)

    hts_code = "8544.42.9090"
    today = date.today()

    test_cases = [
        # (program_id, country, expected_rate, expected_source_contains)
        ("section_232_steel", "Germany", 0.50, "default"),
        ("section_232_steel", "UK", 0.25, "UK"),
        ("section_232_aluminum", "Germany", 0.50, "default"),
        ("section_232_aluminum", "UK", 0.25, "UK"),
        ("section_232_copper", "Germany", 0.50, "default"),
        ("section_232_copper", "UK", 0.50, "default"),  # Copper is 50% everywhere
        ("ieepa_reciprocal", "Germany", 0.124, "EU 15%"),  # 15% - 2.6% MFN = 12.4%
        ("ieepa_reciprocal", "UK", 0.10, "UK"),
        ("ieepa_reciprocal", "Vietnam", 0.10, "default"),
    ]

    app = get_flask_app()
    with app.app_context():
        for program_id, country, expected_rate, expected_source in test_cases:
            rate, source = get_rate_for_program(program_id, country, hts_code, today)
            rate_match = abs(rate - expected_rate) < 0.01
            source_match = expected_source.lower() in source.lower()
            status = "✓" if rate_match and source_match else "✗"
            print(f"  {status} {program_id} / {country}: {rate*100:.1f}% ({source})")
            if not rate_match:
                print(f"      Expected rate: {expected_rate*100:.1f}%")


def calculate_expected_duties():
    """Calculate expected duties for each country test case."""
    print("\n" + "=" * 60)
    print("Expected Duty Calculations (v5.0)")
    print("=" * 60)

    # Common inputs
    hts_code = "8544.42.9090"
    product_value = 10000
    copper_value = 3000
    steel_value = 1000
    aluminum_value = 1000
    remaining_value = product_value - copper_value - steel_value - aluminum_value  # $5,000

    app = get_flask_app()
    with app.app_context():
        today = date.today()

        test_countries = ["Germany", "UK", "China", "Vietnam"]

        for country in test_countries:
            print(f"\n--- {country} ---")

            group = get_country_group(country, today)
            print(f"  Country Group: {group}")

            total_duty = 0

            # 232 Copper (all countries: 50%)
            copper_rate, _ = get_rate_for_program("section_232_copper", country, hts_code, today)
            copper_duty = copper_value * copper_rate
            total_duty += copper_duty
            print(f"  232 Copper: ${copper_value:,} x {copper_rate*100:.0f}% = ${copper_duty:,.0f}")

            # 232 Steel (UK: 25%, others: 50%)
            steel_rate, _ = get_rate_for_program("section_232_steel", country, hts_code, today)
            steel_duty = steel_value * steel_rate
            total_duty += steel_duty
            print(f"  232 Steel: ${steel_value:,} x {steel_rate*100:.0f}% = ${steel_duty:,.0f}")

            # 232 Aluminum (UK: 25%, others: 50%)
            alum_rate, _ = get_rate_for_program("section_232_aluminum", country, hts_code, today)
            alum_duty = aluminum_value * alum_rate
            total_duty += alum_duty
            print(f"  232 Aluminum: ${aluminum_value:,} x {alum_rate*100:.0f}% = ${alum_duty:,.0f}")

            # Section 301 (China only)
            if country in ["China", "CN"]:
                rate_301, _ = get_rate_for_program("section_301", country, hts_code, today)
                duty_301 = product_value * rate_301
                total_duty += duty_301
                print(f"  Section 301: ${product_value:,} x {rate_301*100:.0f}% = ${duty_301:,.0f}")

            # IEEPA Fentanyl (China only)
            if country in ["China", "CN"]:
                fentanyl_rate, _ = get_rate_for_program("ieepa_fentanyl", country, hts_code, today)
                fentanyl_duty = product_value * fentanyl_rate
                total_duty += fentanyl_duty
                print(f"  IEEPA Fentanyl: ${product_value:,} x {fentanyl_rate*100:.0f}% = ${fentanyl_duty:,.0f}")

            # IEEPA Reciprocal (on remaining value)
            recip_rate, recip_source = get_rate_for_program("ieepa_reciprocal", country, hts_code, today)
            recip_duty = remaining_value * recip_rate
            total_duty += recip_duty
            print(f"  IEEPA Reciprocal: ${remaining_value:,} x {recip_rate*100:.1f}% = ${recip_duty:,.0f}")
            print(f"    Source: {recip_source}")

            effective_rate = total_duty / product_value
            print(f"  ─────────────────")
            print(f"  TOTAL: ${total_duty:,.0f} ({effective_rate*100:.1f}%)")


def main():
    print("\n" + "=" * 60)
    print("Tariff Stacker v5.0 - Country-Specific Rate Tests")
    print("=" * 60)

    test_country_groups()
    test_mfn_base_rates()
    test_program_rates()
    calculate_expected_duties()

    print("\n" + "=" * 60)
    print("Tests Complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
