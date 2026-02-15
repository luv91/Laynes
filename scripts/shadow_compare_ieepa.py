#!/usr/bin/env python3
"""
v21.0: IEEPA V1/V2 Shadow Comparison Script

Runs both V1 and V2 engines on the same inputs and logs discrepancies.
Useful for gradual rollout validation.

Target countries for shadow comparison (9-country overlap):
- CN, CA, MX (fentanyl + reciprocal)
- BR (free speech + reciprocal)
- IN (historical Russian oil + reciprocal)
- VN, TH, IT, DE (high-volume reciprocal)

Usage:
    python scripts/shadow_compare_ieepa.py              # Run comparison
    python scripts/shadow_compare_ieepa.py --verbose    # Verbose output
    python scripts/shadow_compare_ieepa.py --country VN # Single country
"""

import argparse
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# Test Cases for Shadow Comparison
# =============================================================================

# High-volume test cases across 9 target countries
SHADOW_TEST_CASES = [
    # China - fentanyl + reciprocal overlap
    {'hts_code': '9403.60.80', 'country_code': 'CN', 'description': 'Chinese furniture'},
    {'hts_code': '8471.30.01', 'country_code': 'CN', 'description': 'Chinese laptop'},
    {'hts_code': '6110.30.30', 'country_code': 'CN', 'description': 'Chinese sweater'},

    # Canada - USMCA exempt
    {'hts_code': '8481.80.50', 'country_code': 'CA', 'description': 'Canadian machinery'},
    {'hts_code': '8703.23.01', 'country_code': 'CA', 'description': 'Canadian auto'},

    # Mexico - USMCA exempt
    {'hts_code': '8708.99.81', 'country_code': 'MX', 'description': 'Mexican auto parts'},
    {'hts_code': '9403.60.80', 'country_code': 'MX', 'description': 'Mexican furniture'},

    # Brazil - free speech tariff + reciprocal
    {'hts_code': '2204.21.50', 'country_code': 'BR', 'description': 'Brazilian wine'},
    {'hts_code': '0901.11.00', 'country_code': 'BR', 'description': 'Brazilian coffee'},

    # India - historical Russian oil + reciprocal
    {'hts_code': '5208.31.60', 'country_code': 'IN', 'description': 'Indian textiles'},
    {'hts_code': '3004.90.92', 'country_code': 'IN', 'description': 'Indian pharmaceuticals'},

    # Vietnam - high reciprocal rate
    {'hts_code': '9403.60.80', 'country_code': 'VN', 'description': 'Vietnamese furniture'},
    {'hts_code': '6110.30.30', 'country_code': 'VN', 'description': 'Vietnamese sweater'},

    # Thailand - high reciprocal rate
    {'hts_code': '8471.30.01', 'country_code': 'TH', 'description': 'Thai laptop'},
    {'hts_code': '9403.60.80', 'country_code': 'TH', 'description': 'Thai furniture'},

    # Italy (EU) - MFN ceiling
    {'hts_code': '2204.21.50', 'country_code': 'IT', 'description': 'Italian wine'},
    {'hts_code': '6110.11.00', 'country_code': 'IT', 'description': 'Italian wool sweater'},

    # Germany (EU) - MFN ceiling
    {'hts_code': '8481.80.50', 'country_code': 'DE', 'description': 'German machinery'},
    {'hts_code': '8703.23.01', 'country_code': 'DE', 'description': 'German car'},
]


# =============================================================================
# Comparison Functions
# =============================================================================

def run_v1_engine(hts_code: str, country_code: str, import_date: str) -> dict:
    """Run V1 legacy engine."""
    os.environ['USE_IEEPA_V2_ENGINE'] = 'false'

    from app.chat.tools.stacking_tools import resolve_reciprocal_variant

    try:
        result_json = resolve_reciprocal_variant.invoke({
            'hts_code': hts_code,
            'slice_type': 'full',
            'country_code': country_code,
            'import_date': import_date
        })
        return json.loads(result_json)
    except Exception as e:
        return {'error': str(e), 'variant': 'error'}


def run_v2_engine(hts_code: str, country_code: str, import_date: str) -> dict:
    """Run V2 new engine."""
    os.environ['USE_IEEPA_V2_ENGINE'] = 'true'

    from app.chat.tools.stacking_tools import resolve_reciprocal_variant

    try:
        result_json = resolve_reciprocal_variant.invoke({
            'hts_code': hts_code,
            'slice_type': 'full',
            'country_code': country_code,
            'import_date': import_date
        })
        return json.loads(result_json)
    except Exception as e:
        return {'error': str(e), 'variant': 'error'}


def compare_results(v1_result: dict, v2_result: dict) -> dict:
    """Compare V1 and V2 results, return discrepancies."""
    discrepancies = {}

    # Compare key fields
    fields_to_compare = ['variant', 'chapter_99_code', 'duty_rate', 'action']

    for field in fields_to_compare:
        v1_val = v1_result.get(field)
        v2_val = v2_result.get(field)

        # Handle None comparisons
        if v1_val is None and v2_val is None:
            continue

        # Handle numeric comparison with tolerance
        if isinstance(v1_val, (int, float)) and isinstance(v2_val, (int, float)):
            if abs(float(v1_val) - float(v2_val)) > 0.001:
                discrepancies[field] = {'v1': v1_val, 'v2': v2_val}
        elif v1_val != v2_val:
            # Handle variant name differences (e.g., 'exempt' vs 'usmca')
            if field == 'variant':
                # Map equivalent variants
                v1_norm = normalize_variant(v1_val)
                v2_norm = normalize_variant(v2_val)
                if v1_norm != v2_norm:
                    discrepancies[field] = {'v1': v1_val, 'v2': v2_val}
            else:
                discrepancies[field] = {'v1': v1_val, 'v2': v2_val}

    return discrepancies


def normalize_variant(variant: str) -> str:
    """Normalize variant names for comparison."""
    if variant is None:
        return 'unknown'

    # Map V2 specific variants to V1 equivalents
    mapping = {
        'usmca': 'exempt',
        'column2': 'exempt',
        's232_subject': 'metal_exempt',
        'in_transit_apr': 'in_transit',
        'in_transit_aug': 'in_transit',
    }
    return mapping.get(variant, variant)


def shadow_compare(
    hts_code: str,
    country_code: str,
    import_date: str = None,
    verbose: bool = False
) -> dict:
    """
    Compare V1 vs V2 outputs for a single HTS/country combination.
    """
    if import_date is None:
        import_date = date.today().isoformat()

    # Run both engines
    v1_result = run_v1_engine(hts_code, country_code, import_date)
    v2_result = run_v2_engine(hts_code, country_code, import_date)

    # Compare
    discrepancies = compare_results(v1_result, v2_result)

    result = {
        'hts_code': hts_code,
        'country_code': country_code,
        'import_date': import_date,
        'v1_result': v1_result,
        'v2_result': v2_result,
        'discrepancies': discrepancies,
        'match': len(discrepancies) == 0
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"HTS: {hts_code} | Country: {country_code} | Date: {import_date}")
        print(f"{'='*60}")
        print(f"V1: variant={v1_result.get('variant')}, code={v1_result.get('chapter_99_code')}, rate={v1_result.get('duty_rate')}")
        print(f"V2: variant={v2_result.get('variant')}, code={v2_result.get('chapter_99_code')}, rate={v2_result.get('duty_rate')}")
        if discrepancies:
            print(f"DISCREPANCIES: {discrepancies}")
        else:
            print("MATCH: Results are equivalent")

    return result


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Shadow compare IEEPA V1 vs V2 engines'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--country',
        type=str,
        help='Filter to specific country code'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Import date (YYYY-MM-DD)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA V1/V2 Shadow Comparison v21.0")
    print("=" * 60)

    # Create Flask app context
    from app.web import create_app
    from app.chat.tools import stacking_tools

    app = create_app()

    with app.app_context():
        # Reset cached app
        stacking_tools._flask_app = app

        # Filter test cases if country specified
        test_cases = SHADOW_TEST_CASES
        if args.country:
            test_cases = [tc for tc in test_cases if tc['country_code'] == args.country]
            print(f"Filtered to country: {args.country}")

        print(f"Test cases: {len(test_cases)}")
        print(f"Import date: {args.date}")
        print("")

        # Run comparisons
        results = []
        matches = 0
        discrepancy_count = 0

        for tc in test_cases:
            result = shadow_compare(
                hts_code=tc['hts_code'],
                country_code=tc['country_code'],
                import_date=args.date,
                verbose=args.verbose
            )
            results.append(result)

            if result['match']:
                matches += 1
            else:
                discrepancy_count += 1
                if not args.verbose:
                    # Print discrepancies even in non-verbose mode
                    print(f"DIFF: {tc['description']} ({tc['hts_code']}/{tc['country_code']})")
                    print(f"      V1: {result['v1_result'].get('variant')}/{result['v1_result'].get('chapter_99_code')}/{result['v1_result'].get('duty_rate')}")
                    print(f"      V2: {result['v2_result'].get('variant')}/{result['v2_result'].get('chapter_99_code')}/{result['v2_result'].get('duty_rate')}")

        # Summary
        print("\n" + "=" * 60)
        print("Shadow Comparison Summary")
        print("=" * 60)
        print(f"Total test cases:  {len(test_cases)}")
        print(f"Matches:           {matches}")
        print(f"Discrepancies:     {discrepancy_count}")
        print(f"Match rate:        {100 * matches / len(test_cases):.1f}%")

        if discrepancy_count > 0:
            print(f"\n[WARNING] {discrepancy_count} discrepancies found")
            print("Review discrepancies before enabling V2 in production")
        else:
            print("\n[SUCCESS] All test cases match")


if __name__ == "__main__":
    main()
