#!/usr/bin/env python3
"""
Test script to verify Section 301 behavior for specific HTS codes.
This script tests WITHOUT making any changes - just queries and reports.

User's expected behavior:
- 9018.90.8000: TW → 9903.02.60, CN → No 301
- 9027.50.4015: TW → 9903.02.60, CN → ?
- 3002.12.0010: TW → ?, CN → No 301 + 9903.01.25
- 7326.90.8660: TW/CN → 232 aluminum claim/disclaim logic
- 7616.99.1000: TW/CN → 232 aluminum claim/disclaim logic
- 8501.31.4000: TW → 9903.02.60, CN → 9903.88.02 or 9903.88.69
- 8473.30.1180: TW → 9903.32 + 9903.79.01, CN → 9903.88.03 or 9903.88.69 + 9903.32
- 8471.50.0150: TW/CN → 9903.32 + missing 232 auto 9903.94.05/06
- 8504.40.9580: TW → 9903.02.60, CN → 9903.88.03 or 9903.88.69
"""

import os
import sys
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up database URL
DATABASE_URL = os.environ.get('DATABASE_URL',
    "postgresql://postgres:lBcijTrVUpeXPiJYKAdIboMpkpslTnJq@metro.proxy.rlwy.net:51109/railway")

# Test cases to verify
TEST_CASES = [
    # (HTS code, COO, Expected behavior description)
    ("9018.90.8000", "TW", "Expected: 9903.02.60 (IEEPA Reciprocal)"),
    ("9018.90.8000", "CN", "Expected: No 301"),

    ("9027.50.4015", "TW", "Expected: 9903.02.60 (IEEPA Reciprocal)"),
    ("9027.50.4015", "CN", "Expected: ? (need to verify)"),

    ("3002.12.0010", "TW", "Expected: ? (need to verify)"),
    ("3002.12.0010", "CN", "Expected: No 301 + 9903.01.25"),

    ("7326.90.8660", "TW", "Expected: 232 aluminum claim/disclaim"),
    ("7326.90.8660", "CN", "Expected: 232 aluminum claim/disclaim"),

    ("7616.99.1000", "TW", "Expected: 232 aluminum claim/disclaim"),
    ("7616.99.1000", "CN", "Expected: 232 aluminum claim/disclaim"),

    ("8501.31.4000", "TW", "Expected: 9903.02.60 (IEEPA Reciprocal)"),
    ("8501.31.4000", "CN", "Expected: 9903.88.02 or 9903.88.69"),

    ("8473.30.1180", "TW", "Expected: 9903.32 + 9903.79.01"),
    ("8473.30.1180", "CN", "Expected: 9903.88.03 or 9903.88.69 + 9903.32"),

    ("8471.50.0150", "TW", "Expected: 9903.32 + missing 232 auto 9903.94.05/06"),
    ("8471.50.0150", "CN", "Expected: 9903.32 + missing 232 auto 9903.94.05/06"),

    ("8504.40.9580", "TW", "Expected: 9903.02.60 (IEEPA Reciprocal)"),
    ("8504.40.9580", "CN", "Expected: 9903.88.03 or 9903.88.69"),
]


def test_with_postgresql():
    """Test against PostgreSQL database."""
    import psycopg2

    print("=" * 80)
    print("TESTING AGAINST POSTGRESQL DATABASE")
    print("=" * 80)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    today = date.today()

    for hts_code, coo, expected in TEST_CASES:
        print(f"\n{'─' * 60}")
        print(f"HTS: {hts_code} | COO: {coo}")
        print(f"Expected: {expected}")
        print(f"{'─' * 60}")

        # Clean HTS code (remove dots)
        hts_clean = hts_code.replace(".", "")
        hts8 = hts_clean[:8]
        hts10 = hts_clean if len(hts_clean) == 10 else None

        # Query section_301_rates table
        cur.execute("""
            SELECT
                hts_8digit,
                hts_10digit,
                duty_rate,
                chapter_99_code,
                list_name,
                effective_start,
                effective_end
            FROM section_301_rates
            WHERE (hts_8digit = %s OR hts_10digit = %s)
            AND (effective_start IS NULL OR effective_start <= %s)
            AND (effective_end IS NULL OR effective_end > %s)
            ORDER BY
                CASE WHEN hts_10digit IS NOT NULL THEN 1 ELSE 2 END,
                effective_start DESC NULLS LAST
        """, (hts8, hts10, today, today))

        results = cur.fetchall()

        if results:
            print(f"  Found {len(results)} match(es) in section_301_rates:")
            for r in results:
                hts8_val, hts10_val, rate, ch99, list_name, eff_start, eff_end = r
                print(f"    HTS8: {hts8_val} | HTS10: {hts10_val}")
                print(f"    Rate: {rate}% | Ch99: {ch99} | List: {list_name}")
                print(f"    Dates: {eff_start or 'open'} to {eff_end or 'open'}")

                # Determine if 301 applies based on COO
                if coo == "CN":
                    print(f"    → 301 APPLIES (COO=CN)")
                else:
                    print(f"    → 301 does NOT apply (COO={coo}, only applies to CN)")
        else:
            print(f"  No matches found in section_301_rates")
            if coo == "CN":
                print(f"    → 301 does NOT apply (HTS not in 301 list)")
            else:
                print(f"    → 301 does NOT apply (COO={coo})")

        # Check IEEPA rates (applies to various countries including TW)
        cur.execute("""
            SELECT chapter_99_code, duty_rate, country_code, program_type, variant,
                   effective_start, effective_end
            FROM ieepa_rates
            WHERE (effective_start IS NULL OR effective_start <= %s)
            AND (effective_end IS NULL OR effective_end > %s)
            ORDER BY chapter_99_code
        """, (today, today))
        ieepa_results = cur.fetchall()

        # Filter for relevant country
        relevant_ieepa = []
        for r in ieepa_results:
            ch99, rate, country, prog, variant, eff_start, eff_end = r
            # Check if this applies to the COO
            if country is None or country == coo or country == 'ALL':
                relevant_ieepa.append(r)

        if relevant_ieepa:
            print(f"\n  [IEEPA rates (COO={coo})]:")
            for r in relevant_ieepa[:5]:  # Limit output
                ch99, rate, country, prog, variant, eff_start, eff_end = r
                print(f"    Ch99: {ch99} | Rate: {rate}% | Country: {country or 'ALL'} | Type: {prog}")

        # Check Section 232 for aluminum products (chapters 73, 76)
        if hts_clean.startswith("73") or hts_clean.startswith("76"):
            cur.execute("""
                SELECT hts_8digit, duty_rate, chapter_99_claim, chapter_99_disclaim,
                       material_type, country_code
                FROM section_232_rates
                WHERE hts_8digit = %s
                AND (effective_start IS NULL OR effective_start <= %s)
                AND (effective_end IS NULL OR effective_end > %s)
            """, (hts8, today, today))
            s232_results = cur.fetchall()
            if s232_results:
                print(f"\n  [Section 232 rates (aluminum)]:")
                for r in s232_results:
                    hts, rate, claim, disclaim, material, country = r
                    print(f"    HTS: {hts} | Rate: {rate}%")
                    print(f"    Claim: {claim} | Disclaim: {disclaim}")
                    print(f"    Material: {material} | Country: {country or 'ALL'}")
            else:
                print(f"\n  [No Section 232 rates found for this HTS]")

    cur.close()
    conn.close()


def test_raw_database_lookup():
    """Direct database queries to understand the data."""
    import psycopg2

    print("\n" + "=" * 80)
    print("RAW DATABASE LOOKUP - Understanding Current Data")
    print("=" * 80)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # List all unique chapter_99_codes in section_301_rates
    print("\n1. All unique Chapter 99 codes in section_301_rates:")
    cur.execute("""
        SELECT DISTINCT chapter_99_code, list_name, COUNT(*) as count
        FROM section_301_rates
        WHERE chapter_99_code IS NOT NULL
        GROUP BY chapter_99_code, list_name
        ORDER BY chapter_99_code
        LIMIT 30
    """)
    for row in cur.fetchall():
        print(f"   {row[0]} | {row[1]} | {row[2]} rows")

    # Check ieepa_rates table
    print("\n2. IEEPA rates summary:")
    cur.execute("""
        SELECT chapter_99_code, program_type, COUNT(*), MIN(duty_rate), MAX(duty_rate)
        FROM ieepa_rates
        GROUP BY chapter_99_code, program_type
        ORDER BY chapter_99_code
    """)
    results = cur.fetchall()
    if results:
        for row in results:
            print(f"   {row[0]} | {row[1]} | {row[2]} rows | Rate: {row[3]}-{row[4]}%")
    else:
        print("   No IEEPA rates found")

    # Check for 232 codes
    print("\n3. Section 232 rates summary:")
    cur.execute("""
        SELECT chapter_99_claim, chapter_99_disclaim, material_type, COUNT(*)
        FROM section_232_rates
        GROUP BY chapter_99_claim, chapter_99_disclaim, material_type
        ORDER BY chapter_99_claim
    """)
    results = cur.fetchall()
    if results:
        for row in results:
            print(f"   Claim: {row[0]} | Disclaim: {row[1]} | {row[2]} | {row[3]} rows")
    else:
        print("   No Section 232 codes found")

    # Check for exclusion-related codes
    print("\n4. Exclusion codes (9903.88.xx) in section_301_rates:")
    cur.execute("""
        SELECT chapter_99_code, list_name, COUNT(*)
        FROM section_301_rates
        WHERE chapter_99_code LIKE '9903.88%%'
        GROUP BY chapter_99_code, list_name
        ORDER BY chapter_99_code
    """)
    results = cur.fetchall()
    if results:
        for row in results:
            print(f"   {row[0]} | {row[1]} | {row[2]} rows")
    else:
        print("   No 9903.88.xx codes found")

    # Check total rows
    print("\n5. Total rows in key tables:")
    for table in ['section_301_rates', 'ieepa_rates', 'section_232_rates']:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"   {table}: {cur.fetchone()[0]} rows")
        except Exception as e:
            print(f"   {table}: error - {e}")

    # Sample of HTS codes for each test case
    print("\n6. Checking specific HTS codes from test cases:")
    test_hts = [
        ("9018908000", "90189080"),
        ("9027504015", "90275040"),
        ("3002120010", "30021200"),
        ("7326908660", "73269086"),
        ("7616991000", "76169910"),
        ("8501314000", "85013140"),
        ("8473301180", "84733011"),
        ("8471500150", "84715001"),
        ("8504409580", "85044095")
    ]
    for hts10, hts8 in test_hts:
        cur.execute("""
            SELECT hts_8digit, hts_10digit, duty_rate, chapter_99_code, list_name
            FROM section_301_rates
            WHERE hts_8digit = %s OR hts_10digit = %s
        """, (hts8, hts10))
        results = cur.fetchall()
        if results:
            for r in results:
                print(f"   {r[0] or r[1]}: {r[2]}% | {r[3]} | {r[4]}")
        else:
            print(f"   {hts10}: NOT FOUND in section_301_rates")

    cur.close()
    conn.close()


def test_with_section301_engine():
    """Test using the Section 301 engine directly."""
    print("\n" + "=" * 80)
    print("TESTING WITH SECTION 301 ENGINE")
    print("=" * 80)

    try:
        from app.services.section301_engine import evaluate_section_301, Section301Engine

        # Initialize the engine
        engine = Section301Engine()

        for hts_code, coo, expected in TEST_CASES:
            print(f"\n{'─' * 60}")
            print(f"HTS: {hts_code} | COO: {coo}")
            print(f"Expected: {expected}")
            print(f"{'─' * 60}")

            try:
                result = engine.evaluate(coo=coo, hts_code=hts_code, entry_date=date.today())
                print(f"  Engine Result:")
                print(f"    applies: {result.applies}")
                if result.applies:
                    print(f"    ch99_heading: {result.chapter99_heading}")
                    print(f"    additional_rate: {result.additional_rate}%")
                    print(f"    rate_status: {result.rate_status}")
                    if hasattr(result, 'legal_basis') and result.legal_basis:
                        print(f"    legal_basis: {result.legal_basis}")
                else:
                    if hasattr(result, 'reason'):
                        print(f"    reason: {result.reason}")
            except Exception as e:
                print(f"  Engine Error: {e}")

    except ImportError as e:
        print(f"Could not import Section 301 engine: {e}")
        print("Skipping engine tests...")


if __name__ == "__main__":
    print("Section 301 HTS Code Verification")
    print("Testing WITHOUT making any changes")
    print("=" * 80)

    # Run tests
    test_raw_database_lookup()
    test_with_postgresql()
    test_with_section301_engine()

    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETE")
    print("=" * 80)
