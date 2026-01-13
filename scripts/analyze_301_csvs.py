#!/usr/bin/env python3
"""
Analyze the existing Section 301 CSV files to understand their structure
and determine if they can be used for database import.
"""

import csv
from pathlib import Path
from collections import Counter

CSV_DIR = Path(__file__).parent.parent / "docs" / "section301_csv_only_GPT"


def analyze_csv(csv_path: Path, max_rows: int = 5):
    """Analyze a CSV file and print summary."""
    print(f"\n{'='*60}")
    print(f"FILE: {csv_path.name}")
    print(f"Size: {csv_path.stat().st_size / 1024:.1f} KB")
    print(f"{'='*60}")

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Columns: {reader.fieldnames}")
    print(f"Row count: {len(rows)}")

    # Sample rows
    print(f"\nFirst {min(max_rows, len(rows))} rows:")
    for i, row in enumerate(rows[:max_rows]):
        print(f"  Row {i+1}: {dict(row)}")

    # Column value analysis
    if rows:
        print("\nColumn analysis:")
        for col in reader.fieldnames:
            values = [r.get(col, "") for r in rows]
            unique = len(set(values))
            non_empty = sum(1 for v in values if v)
            sample = list(set(values))[:3]
            print(f"  {col}: {unique} unique values, {non_empty} non-empty")
            print(f"    Sample: {sample}")

    return {
        "filename": csv_path.name,
        "columns": reader.fieldnames,
        "row_count": len(rows),
        "rows": rows
    }


def main():
    print("="*60)
    print("SECTION 301 CSV ANALYSIS")
    print("="*60)

    csv_files = sorted(CSV_DIR.glob("*.csv"))
    print(f"\nFound {len(csv_files)} CSV files in {CSV_DIR}")

    results = {}
    for csv_file in csv_files:
        results[csv_file.name] = analyze_csv(csv_file)

    # Summary comparison
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    # Total counts
    total_rows = 0
    for name, data in results.items():
        print(f"  {name}: {data['row_count']} rows")
        if "list" in name.lower() and "active" not in name.lower() and "all" not in name.lower():
            total_rows += data['row_count']

    print(f"\nTotal HTS codes in list files: {total_rows}")

    # Check if active file matches individual lists
    if "section301_inclusions_active_as_of_2026.csv" in results:
        active = results["section301_inclusions_active_as_of_2026.csv"]
        print(f"\nActive as of 2026: {active['row_count']} rows")

    # Check required columns for database import
    print("\n" + "="*60)
    print("SCHEMA COMPATIBILITY CHECK")
    print("="*60)

    required_cols = ["hts_code", "list_name", "chapter_99_code", "duty_rate"]
    alt_cols = {
        "hts_code": ["hts", "hts_8", "hts_8digit", "tariff_code"],
        "list_name": ["list", "tranche"],
        "chapter_99_code": ["chapter99", "ch99_code", "claim_code"],
        "duty_rate": ["rate", "duty", "tariff_rate"]
    }

    for name, data in results.items():
        if not data["columns"]:
            continue
        cols_lower = [c.lower() for c in data["columns"]]
        print(f"\n{name}:")
        for req in required_cols:
            found = req.lower() in cols_lower
            if not found:
                # Check alternatives
                for alt in alt_cols.get(req, []):
                    if alt in cols_lower:
                        found = f"(as '{alt}')"
                        break
            status = "YES" if found else "MISSING"
            print(f"  {req}: {status}")


if __name__ == "__main__":
    main()
