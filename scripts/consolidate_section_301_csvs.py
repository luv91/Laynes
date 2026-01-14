#!/usr/bin/env python3
"""
Consolidate Section 301 CSV files into ONE unified temporal CSV.

Merges:
  - data/section_301_hts_codes.csv (legacy, 10,422 rows at 25%)
  - data/section_301_2024_review.csv (2024 review, 395 rows with staged rates)

Output:
  - data/section_301_rates_temporal.csv (unified temporal format)

The output CSV maintains full temporal history:
  - Legacy rates from 2018/2019 with effective_end set when superseded
  - 2024 review rates with staged increases (25% → 50% → 100%)
  - All rates can be queried by effective date

Usage:
    python scripts/consolidate_section_301_csvs.py [--dry-run]
"""

import pandas as pd
from datetime import datetime, timedelta
import argparse
import os

def normalize_hts(hts_value):
    """Normalize HTS code to 8 digits."""
    if pd.isna(hts_value):
        return None
    hts_str = str(hts_value).replace('.', '').replace(' ', '')
    # Take first 8 digits
    return hts_str[:8].zfill(8)

def consolidate_csvs(dry_run=False):
    """
    Merge legacy and 2024 review CSVs into unified temporal format.

    Returns:
        DataFrame: Combined temporal data
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, 'data')

    # Load legacy CSV
    legacy_path = os.path.join(data_dir, 'section_301_hts_codes.csv')
    print(f"Loading legacy CSV: {legacy_path}")
    legacy_df = pd.read_csv(legacy_path)
    print(f"  Loaded {len(legacy_df)} legacy rows")

    # Normalize legacy data
    legacy_rows = []
    for _, row in legacy_df.iterrows():
        legacy_rows.append({
            'hts_8digit': normalize_hts(row.get('hts_8digit') or row.get('hts_digits')),
            'chapter_99_code': row.get('chapter_99_code', ''),
            'duty_rate': float(row.get('rate', 0.25)),
            'effective_start': row.get('effective_start', '2018-07-06'),
            'effective_end': None,  # Will be set if superseded
            'list_name': row.get('list_name', ''),
            'source': row.get('source_pdf', 'legacy')
        })

    legacy_temporal = pd.DataFrame(legacy_rows)
    print(f"  Normalized to {len(legacy_temporal)} temporal rows")

    # Load 2024 review CSV
    review_path = os.path.join(data_dir, 'section_301_2024_review.csv')
    print(f"\nLoading 2024 review CSV: {review_path}")
    review_df = pd.read_csv(review_path)
    print(f"  Loaded {len(review_df)} review rows")

    # Normalize 2024 review data
    review_rows = []
    for _, row in review_df.iterrows():
        review_rows.append({
            'hts_8digit': normalize_hts(row.get('hts_8digit')),
            'chapter_99_code': row.get('chapter_99_code', ''),
            'duty_rate': float(row.get('rate', 0)),
            'effective_start': row.get('effective_date', ''),
            'effective_end': None,  # Will be set for staged rates
            'list_name': row.get('product_group', ''),
            'source': row.get('source_doc', '2024-review')
        })

    review_temporal = pd.DataFrame(review_rows)
    print(f"  Normalized to {len(review_temporal)} temporal rows")

    # Group 2024 review by HTS code to find earliest effective date per HTS
    print("\nProcessing supersession logic...")

    # For each HTS in 2024 review, find its earliest effective date
    hts_first_effective = review_temporal.groupby('hts_8digit')['effective_start'].min().to_dict()

    # Close legacy rates that are superseded by 2024 review
    superseded_count = 0
    for hts, first_date in hts_first_effective.items():
        if pd.isna(hts) or not hts:
            continue
        # Find matching legacy row(s)
        mask = legacy_temporal['hts_8digit'] == hts
        if mask.any():
            # Set effective_end to day before 2024 rate kicks in
            first_date_dt = pd.to_datetime(first_date)
            end_date = (first_date_dt - timedelta(days=1)).strftime('%Y-%m-%d')
            legacy_temporal.loc[mask, 'effective_end'] = end_date
            superseded_count += mask.sum()

    print(f"  Superseded {superseded_count} legacy rates")

    # Handle staged rates in 2024 review (close earlier rates when later ones start)
    print("\nProcessing staged rate increases...")
    staged_count = 0

    # Ensure effective_start is string for consistent comparison
    review_temporal['effective_start'] = review_temporal['effective_start'].astype(str)

    # Group by HTS to find staged rates
    grouped = review_temporal.groupby(['hts_8digit'])

    for hts, group in grouped:
        if len(group) > 1:
            # Multiple rates for same HTS = staged increases
            sorted_group = group.sort_values('effective_start')
            indices = sorted_group.index.tolist()
            dates = sorted_group['effective_start'].tolist()

            for i in range(len(dates) - 1):
                current_idx = indices[i]
                next_date = dates[i + 1]

                # Close current rate the day before next rate starts
                next_date_dt = pd.to_datetime(next_date)
                end_date = (next_date_dt - timedelta(days=1)).strftime('%Y-%m-%d')

                # Use index directly for reliable assignment
                review_temporal.loc[current_idx, 'effective_end'] = end_date
                staged_count += 1

    print(f"  Set effective_end for {staged_count} staged rates")

    # Combine legacy and review
    print("\nCombining datasets...")
    combined = pd.concat([legacy_temporal, review_temporal], ignore_index=True)

    # Sort by HTS and effective_start for clean output
    combined = combined.sort_values(['hts_8digit', 'effective_start'])

    # Remove duplicates (same HTS, same rate, same effective_start)
    before_dedup = len(combined)
    combined = combined.drop_duplicates(
        subset=['hts_8digit', 'duty_rate', 'effective_start'],
        keep='first'
    )
    after_dedup = len(combined)
    if before_dedup != after_dedup:
        print(f"  Removed {before_dedup - after_dedup} duplicate rows")

    print(f"\nFinal combined dataset: {len(combined)} rows")

    # Statistics
    active_rates = combined[combined['effective_end'].isna()]
    print(f"  Active rates (no end date): {len(active_rates)}")

    superseded_rates = combined[combined['effective_end'].notna()]
    print(f"  Superseded rates (has end date): {len(superseded_rates)}")

    # Rate distribution
    print("\n  Rate distribution:")
    rate_counts = combined['duty_rate'].value_counts().sort_index()
    for rate, count in rate_counts.items():
        print(f"    {rate*100:.0f}%: {count} rows")

    if dry_run:
        print("\n[DRY RUN] Would write to: data/section_301_rates_temporal.csv")
        print("\nSample output (first 10 rows):")
        print(combined.head(10).to_string(index=False))

        print("\nSample output (rates for user-reported HTS codes):")
        test_codes = ['38180000', '85414200', '90183100', '40151210']
        for code in test_codes:
            matches = combined[combined['hts_8digit'] == code]
            if not matches.empty:
                print(f"\n  {code}:")
                for _, row in matches.iterrows():
                    end = row['effective_end'] if pd.notna(row['effective_end']) else 'ongoing'
                    print(f"    {row['duty_rate']*100:.0f}% from {row['effective_start']} to {end}")
    else:
        output_path = os.path.join(data_dir, 'section_301_rates_temporal.csv')
        combined.to_csv(output_path, index=False)
        print(f"\nWrote unified temporal CSV to: {output_path}")

    return combined

def main():
    parser = argparse.ArgumentParser(description='Consolidate Section 301 CSVs')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without writing files')
    args = parser.parse_args()

    consolidate_csvs(dry_run=args.dry_run)

if __name__ == '__main__':
    main()
