#!/usr/bin/env python3
"""
Reconciliation Job - Compare Database vs CSV Coverage

Identifies gaps between:
1. CSV data (seed data) vs Database (runtime data)
2. Expected HTS coverage vs Actual coverage
3. Documents discovered vs Documents processed

Usage:
    # Run full reconciliation report
    pipenv run python scripts/reconcile_coverage.py

    # Export database rates to CSV (backup)
    pipenv run python scripts/reconcile_coverage.py --export-csv

    # Check specific HTS codes
    pipenv run python scripts/reconcile_coverage.py --check-hts 8426.19.00 7606.12.30

v17.0: Created as part of DB-as-source-of-truth architecture
"""

import argparse
import csv
import os
import sys
from datetime import date, datetime
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


def load_csv_section_301() -> set:
    """Load HTS codes from Section 301 CSV."""
    csv_path = Path(__file__).parent.parent / "data" / "section_301_rates_temporal.csv"
    codes = set()

    if csv_path.exists():
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                codes.add(row['hts_8digit'])

    return codes


def load_csv_section_232() -> set:
    """Load HTS codes from Section 232 CSV."""
    csv_path = Path(__file__).parent.parent / "data" / "section_232_hts_codes.csv"
    codes = set()

    if csv_path.exists():
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize code format (remove dots)
                code = row['hts_code'].replace('.', '')
                codes.add(code)

    return codes


def reconcile_section_301():
    """Compare Section 301 coverage: CSV vs Database."""
    from app.web import create_app
    from app.web.db.models.tariff_tables import Section301Rate

    app = create_app()
    print("\n" + "=" * 60)
    print("SECTION 301 RECONCILIATION")
    print("=" * 60)

    csv_codes = load_csv_section_301()
    print(f"CSV codes: {len(csv_codes)}")

    with app.app_context():
        # Get unique HTS codes from database
        db_codes = set()
        rates = Section301Rate.query.with_entities(Section301Rate.hts_8digit).distinct().all()
        for r in rates:
            db_codes.add(r.hts_8digit)

        print(f"Database codes: {len(db_codes)}")

        # Find differences
        in_csv_not_db = csv_codes - db_codes
        in_db_not_csv = db_codes - csv_codes

        print(f"\nIn CSV but not in Database: {len(in_csv_not_db)}")
        if in_csv_not_db:
            for code in sorted(list(in_csv_not_db))[:20]:
                print(f"  - {code}")
            if len(in_csv_not_db) > 20:
                print(f"  ... and {len(in_csv_not_db) - 20} more")

        print(f"\nIn Database but not in CSV: {len(in_db_not_csv)}")
        if in_db_not_csv:
            for code in sorted(list(in_db_not_csv))[:20]:
                # Get the rate details
                rate = Section301Rate.query.filter_by(hts_8digit=code).first()
                source = rate.source_doc if rate else "unknown"
                print(f"  - {code} (source: {source})")
            if len(in_db_not_csv) > 20:
                print(f"  ... and {len(in_db_not_csv) - 20} more")

        # These are likely pipeline-discovered rates that should be preserved
        if in_db_not_csv:
            print("\n  NOTE: Codes in DB but not CSV may be pipeline-discovered.")
            print("        These should NOT be deleted - they are runtime data.")

        return {
            "csv_count": len(csv_codes),
            "db_count": len(db_codes),
            "in_csv_not_db": len(in_csv_not_db),
            "in_db_not_csv": len(in_db_not_csv),
        }


def reconcile_section_232():
    """Compare Section 232 coverage: CSV vs Database."""
    from app.web import create_app
    from app.web.db.models.tariff_tables import Section232Material

    app = create_app()
    print("\n" + "=" * 60)
    print("SECTION 232 RECONCILIATION")
    print("=" * 60)

    csv_codes = load_csv_section_232()
    print(f"CSV codes: {len(csv_codes)}")

    with app.app_context():
        # Get unique HTS codes from database
        db_codes = set()
        materials = Section232Material.query.with_entities(Section232Material.hts_8digit).distinct().all()
        for m in materials:
            db_codes.add(m.hts_8digit)

        print(f"Database codes: {len(db_codes)}")

        # Find differences
        in_csv_not_db = csv_codes - db_codes
        in_db_not_csv = db_codes - csv_codes

        print(f"\nIn CSV but not in Database: {len(in_csv_not_db)}")
        if in_csv_not_db:
            for code in sorted(list(in_csv_not_db))[:20]:
                print(f"  - {code}")

        print(f"\nIn Database but not in CSV: {len(in_db_not_csv)}")
        if in_db_not_csv:
            for code in sorted(list(in_db_not_csv))[:20]:
                mat = Section232Material.query.filter_by(hts_8digit=code).first()
                material = mat.material if mat else "unknown"
                print(f"  - {code} ({material})")

        return {
            "csv_count": len(csv_codes),
            "db_count": len(db_codes),
            "in_csv_not_db": len(in_csv_not_db),
            "in_db_not_csv": len(in_db_not_csv),
        }


def reconcile_ingest_jobs():
    """Check status of ingest jobs."""
    from app.web import create_app
    from app.models.ingest_job import IngestJob

    app = create_app()
    print("\n" + "=" * 60)
    print("INGEST JOB STATUS")
    print("=" * 60)

    with app.app_context():
        # Count by status
        status_counts = defaultdict(int)
        jobs = IngestJob.query.all()

        for job in jobs:
            status_counts[job.status] += 1

        print(f"Total jobs: {len(jobs)}")
        print("\nBy status:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")

        # Count by source
        source_counts = defaultdict(int)
        for job in jobs:
            source_counts[job.source] += 1

        print("\nBy source:")
        for source, count in sorted(source_counts.items()):
            print(f"  {source}: {count}")

        # Find failed jobs
        failed_jobs = IngestJob.query.filter_by(status="failed").all()
        if failed_jobs:
            print(f"\nFailed jobs ({len(failed_jobs)}):")
            for job in failed_jobs[:10]:
                print(f"  - {job.external_id}: {job.error_message[:50] if job.error_message else 'No error'}...")

        return {
            "total": len(jobs),
            "by_status": dict(status_counts),
            "by_source": dict(source_counts),
        }


def export_database_to_csv():
    """Export current database rates to CSV (backup)."""
    from app.web import create_app
    from app.web.db.models.tariff_tables import Section301Rate, Section232Rate, IeepaRate

    app = create_app()
    export_dir = Path(__file__).parent.parent / "data" / "exports"
    export_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    with app.app_context():
        # Export Section 301
        rates_301 = Section301Rate.query.all()
        export_path = export_dir / f"section_301_rates_export_{timestamp}.csv"

        with open(export_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['hts_8digit', 'chapter_99_code', 'duty_rate', 'effective_start',
                           'effective_end', 'list_name', 'source_doc', 'role'])
            for r in rates_301:
                writer.writerow([
                    r.hts_8digit,
                    r.chapter_99_code,
                    r.duty_rate,
                    r.effective_start,
                    r.effective_end or '',
                    r.list_name or '',
                    r.source_doc or '',
                    r.role or 'impose',
                ])

        print(f"Exported {len(rates_301)} Section 301 rates to {export_path}")

        # Export Section 232
        rates_232 = Section232Rate.query.all()
        export_path = export_dir / f"section_232_rates_export_{timestamp}.csv"

        with open(export_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['hts_8digit', 'material_type', 'article_type', 'chapter_99_claim',
                           'chapter_99_disclaim', 'duty_rate', 'country_code', 'effective_start',
                           'effective_end', 'source_doc'])
            for r in rates_232:
                writer.writerow([
                    r.hts_8digit,
                    r.material_type,
                    r.article_type,
                    r.chapter_99_claim,
                    r.chapter_99_disclaim,
                    r.duty_rate,
                    r.country_code or '',
                    r.effective_start,
                    r.effective_end or '',
                    r.source_doc or '',
                ])

        print(f"Exported {len(rates_232)} Section 232 rates to {export_path}")

        return {"section_301": len(rates_301), "section_232": len(rates_232)}


def check_specific_hts(hts_codes: list):
    """Check coverage for specific HTS codes."""
    from app.web import create_app
    from app.web.db.models.tariff_tables import Section301Rate, Section232Material, Section232Rate

    app = create_app()
    print("\n" + "=" * 60)
    print("SPECIFIC HTS CODE CHECK")
    print("=" * 60)

    with app.app_context():
        for code in hts_codes:
            # Normalize code (remove dots)
            normalized = code.replace('.', '')
            print(f"\n{code} ({normalized}):")

            # Check Section 301
            rate_301 = Section301Rate.query.filter_by(hts_8digit=normalized).first()
            if rate_301:
                print(f"  Section 301: {float(rate_301.duty_rate)*100}% via {rate_301.chapter_99_code}")
            else:
                print(f"  Section 301: NOT FOUND")

            # Check Section 232
            mat_232 = Section232Material.query.filter_by(hts_8digit=normalized).first()
            if mat_232:
                print(f"  Section 232 Material: {mat_232.material} ({mat_232.article_type})")
            else:
                print(f"  Section 232 Material: NOT FOUND")

            # Check Section 232 temporal
            rate_232 = Section232Rate.query.filter_by(hts_8digit=normalized).first()
            if rate_232:
                print(f"  Section 232 Rate: {float(rate_232.duty_rate)*100}% via {rate_232.chapter_99_claim}")
            else:
                print(f"  Section 232 Rate: NOT FOUND")


def main():
    parser = argparse.ArgumentParser(description="Reconcile database vs CSV coverage")
    parser.add_argument("--export-csv", action="store_true",
                       help="Export database rates to CSV backup")
    parser.add_argument("--check-hts", nargs="+", type=str,
                       help="Check specific HTS codes (e.g., 8426.19.00 7606.12.30)")

    args = parser.parse_args()

    print("=" * 60)
    print("COVERAGE RECONCILIATION REPORT")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if args.export_csv:
        export_database_to_csv()
        return

    if args.check_hts:
        check_specific_hts(args.check_hts)
        return

    # Run full reconciliation
    results = {}
    results["section_301"] = reconcile_section_301()
    results["section_232"] = reconcile_section_232()
    results["ingest_jobs"] = reconcile_ingest_jobs()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("\nSection 301:")
    print(f"  CSV: {results['section_301']['csv_count']} codes")
    print(f"  Database: {results['section_301']['db_count']} codes")
    print(f"  Gap (CSV-DB): {results['section_301']['in_csv_not_db']}")
    print(f"  Pipeline-discovered (DB-CSV): {results['section_301']['in_db_not_csv']}")

    print("\nSection 232:")
    print(f"  CSV: {results['section_232']['csv_count']} codes")
    print(f"  Database: {results['section_232']['db_count']} codes")
    print(f"  Gap: {results['section_232']['in_csv_not_db']}")

    print("\nIngest Jobs:")
    print(f"  Total: {results['ingest_jobs']['total']}")
    committed = results['ingest_jobs']['by_status'].get('committed', 0)
    queued = results['ingest_jobs']['by_status'].get('queued', 0)
    failed = results['ingest_jobs']['by_status'].get('failed', 0)
    print(f"  Committed: {committed}, Queued: {queued}, Failed: {failed}")


if __name__ == "__main__":
    main()
