#!/usr/bin/env python3
"""
Populate Section 301 Inclusions from USITC HTS Chapter 99.

Parses U.S. Note 20(pp)-(ss) from the Chapter 99 PDF to extract
all Section 301 inclusion HTS codes under headings 9903.88.01-15.

Data source: USITC HTS Archive - Chapter 99 (current release)
URL: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter+99

Note 20 inclusion buckets:
  - 20(pp): List 1 -> 9903.88.01 (25%)
  - 20(qq): List 2 -> 9903.88.02 (25%)
  - 20(rr): List 3 -> 9903.88.03 (25%)
  - 20(ss): List 4A -> 9903.88.15 (7.5%)

Usage:
    cd lanes
    pipenv run python scripts/populate_section301_inclusions.py --download
    pipenv run python scripts/populate_section301_inclusions.py --csv-only
    pipenv run python scripts/populate_section301_inclusions.py --reset
    pipenv run python scripts/populate_section301_inclusions.py --explore  # Find note sections
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PDF_URL = "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter+99"
PDF_PATH = Path(__file__).parent.parent / "data" / "chapter99_current.pdf"
CSV_PATH = Path(__file__).parent.parent / "data" / "current" / "section_301_inclusions.csv"
MANIFEST_PATH = Path(__file__).parent.parent / "data" / "current" / "manifest.json"

# FIX #1: Use actual Section 301 effective dates from Federal Register
LIST_EFFECTIVE_DATES = {
    "list_1": date(2018, 7, 6),    # FR-2018-13248
    "list_2": date(2018, 8, 23),   # FR-2018-17709
    "list_3": date(2018, 9, 24),   # FR-2018-20610
    "list_4A": date(2019, 9, 1),   # FR-2019-17865
}

# Section definitions for inclusion notes
# The actual inclusion HTS lists are in notes 20(b), 20(d), 20(f), 20(h)
# NOT in 20(pp)-(ss) which are exclusion-related
SECTION_DEFS = [
    {
        "note_bucket": "20(b)",
        "chapter_99_code": "9903.88.01",
        "list_name": "list_1",
        "duty_rate": 0.25,
        # Pattern to find start of 20(b) section
        "pattern": r"\(b\)\s*Heading 9903\.88\.01 applies",
        "heading_fallback": r"Heading 9903\.88\.01 applies to all products of China",
    },
    {
        "note_bucket": "20(d)",
        "chapter_99_code": "9903.88.02",
        "list_name": "list_2",
        "duty_rate": 0.25,
        "pattern": r"\(d\)\s*Heading 9903\.88\.02 applies",
        "heading_fallback": r"Heading 9903\.88\.02 applies to all products of China",
    },
    {
        "note_bucket": "20(f)",
        "chapter_99_code": "9903.88.03",
        "list_name": "list_3",
        "duty_rate": 0.25,
        "pattern": r"\(f\)\s*Heading 9903\.88\.03 applies",
        "heading_fallback": r"Heading 9903\.88\.03 applies to all products of China",
    },
    {
        "note_bucket": "20(s)(i)",
        "chapter_99_code": "9903.88.15",
        "list_name": "list_4A",
        "duty_rate": 0.075,  # 7.5% per FR-2020-00904
        # List 4A codes are in 20(s)(i), which starts after page 321
        "pattern": r"\(s\)\s*\(i\)\s*Heading 9903\.88\.15",
        "heading_fallback": r"\(s\)\s*\(i\)",
    },
]

# FIX #2: Old PDF source patterns to delete on reset
OLD_PDF_SOURCES = [
    "FR-2018-13248%",
    "FR-2018-17709%",
    "FR-2018-20610%",
    "FR-2019-17865%",
    "%List1.pdf%",
    "%List2.pdf%",
    "%List3%",
    "%List4A%",
]

# HTS code pattern: XXXX.XX.XX or XXXX.XX.XXXX
HTS_PATTERN = re.compile(r'\b(\d{4})\.(\d{2})\.(\d{2,4})\b')


# ---------------------------------------------------------------------------
# PDF Download
# ---------------------------------------------------------------------------

def download_chapter99_pdf():
    """Download Chapter 99 PDF from USITC RESTStop (streaming, no size limit)."""
    import requests

    print(f"Downloading Chapter 99 PDF from {PDF_URL} ...")
    resp = requests.get(PDF_URL, stream=True, timeout=120)
    resp.raise_for_status()

    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PDF_PATH, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = PDF_PATH.stat().st_size / (1024 * 1024)
    print(f"  Downloaded: {PDF_PATH} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# PDF Exploration (find note sections)
# ---------------------------------------------------------------------------

def explore_pdf_for_notes(pdf_path: Path):
    """Explore PDF to find Note 20(pp)-(ss) sections."""
    import pdfplumber

    pdf = pdfplumber.open(str(pdf_path))
    print(f"PDF has {len(pdf.pages)} pages")
    print("\nSearching for Note 20(pp), 20(qq), 20(rr), 20(ss)...\n")

    # Search patterns
    patterns = [
        (r"\(pp\)", "20(pp)"),
        (r"\(qq\)", "20(qq)"),
        (r"\(rr\)", "20(rr)"),
        (r"\(ss\)", "20(ss)"),
        (r"9903\.88\.01", "9903.88.01"),
        (r"9903\.88\.02", "9903.88.02"),
        (r"9903\.88\.03", "9903.88.03"),
        (r"9903\.88\.15", "9903.88.15"),
    ]

    results = {name: [] for _, name in patterns}

    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        for pattern, name in patterns:
            if re.search(pattern, text):
                results[name].append(i)

    pdf.close()

    print("Found on pages:")
    for name, pages in results.items():
        if pages:
            # Show ranges for brevity
            page_range = f"{min(pages)}-{max(pages)}" if len(pages) > 5 else str(pages)
            print(f"  {name}: pages {page_range} ({len(pages)} occurrences)")
        else:
            print(f"  {name}: NOT FOUND")

    return results


# ---------------------------------------------------------------------------
# PDF Parsing
# ---------------------------------------------------------------------------

def extract_note_text(pdf_path: Path, page_start: int, page_end: int) -> str:
    """Extract text from specified page range in Chapter 99 PDF."""
    import pdfplumber

    pdf = pdfplumber.open(str(pdf_path))
    print(f"  PDF has {len(pdf.pages)} pages, extracting pages {page_start}-{page_end}...")

    full_text = ""
    for i in range(page_start, min(page_end + 1, len(pdf.pages))):
        page = pdf.pages[i]
        text = page.extract_text() or ""
        # Remove header lines that appear on every page
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            if "Harmonized Tariff Schedule" in line:
                continue
            if "Annotated for Statistical Reporting" in line:
                continue
            if line.strip().startswith("XXII"):
                continue
            if re.match(r"^99\s*-\s*III\s*-\s*\d+", line.strip()):
                continue
            if line.strip() == "U.S. Notes (con.)":
                continue
            cleaned.append(line)
        full_text += "\n".join(cleaned) + "\n"
    pdf.close()
    return full_text


def find_note_section(text: str, section_def: dict) -> int:
    """
    FIX #4: Find note section with fallback to heading markers.

    Returns the start position of the section, or -1 if not found.
    """
    # Try primary pattern first
    match = re.search(section_def["pattern"], text)
    if match:
        return match.start()

    # Fallback: find by heading marker
    if section_def.get("heading_fallback"):
        match = re.search(section_def["heading_fallback"], text, re.IGNORECASE)
        if match:
            return match.start()

    return -1


def extract_hts_codes_from_text(text: str) -> list:
    """Extract all HTS codes from text, returning 8-digit versions."""
    codes = set()
    for match in HTS_PATTERN.finditer(text):
        chapter = match.group(1)
        heading = match.group(2)
        subheading = match.group(3)

        # Skip Chapter 99 codes (9903.xx.xx)
        if chapter.startswith("99"):
            continue

        # Build 8-digit code (no dots)
        hts8 = f"{chapter}{heading}{subheading[:2]}"
        codes.add(hts8)

    return sorted(codes)


def parse_inclusion_sections(full_text: str, source_info: str) -> list:
    """Parse all inclusion entries from Note 20(pp)-(ss) text."""
    # Find section boundaries
    boundaries = []
    for sec in SECTION_DEFS:
        pos = find_note_section(full_text, sec)
        if pos >= 0:
            boundaries.append({**sec, "start": pos})
            print(f"  Found {sec['note_bucket']} at position {pos}")
        else:
            print(f"  WARNING: Section {sec['note_bucket']} not found!")

    if not boundaries:
        print("  ERROR: No sections found!")
        return []

    # Sort by position
    boundaries.sort(key=lambda x: x["start"])

    all_inclusions = []
    for i, sec in enumerate(boundaries):
        # End at next section or end of text
        end = boundaries[i + 1]["start"] if i + 1 < len(boundaries) else len(full_text)
        section_text = full_text[sec["start"]:end]

        # Extract HTS codes from this section
        hts_codes = extract_hts_codes_from_text(section_text)

        effective_date = LIST_EFFECTIVE_DATES.get(sec["list_name"], date(2018, 7, 6))

        for hts8 in hts_codes:
            all_inclusions.append({
                "hts_8digit": hts8,
                "hts_10digit": None,
                "chapter_99_code": sec["chapter_99_code"],
                "duty_rate": sec["duty_rate"],
                "list_name": sec["list_name"],
                "effective_start": effective_date,
                "effective_end": None,  # Open-ended (currently active)
                "source_doc": source_info,
            })

        print(
            f"  {sec['note_bucket']} ({sec['list_name']}): {len(hts_codes)} HTS codes "
            f"(heading: {sec['chapter_99_code']}, rate: {sec['duty_rate']*100:.1f}%)"
        )

    return all_inclusions


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "hts_8digit",
    "hts_10digit",
    "chapter_99_code",
    "duty_rate",
    "list_name",
    "effective_start",
    "effective_end",
    "source_doc",
]


def export_csv(inclusions: list):
    """Export inclusions to CSV."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for inc in inclusions:
            row = {k: inc.get(k, "") for k in CSV_COLUMNS}
            row["effective_start"] = inc["effective_start"].isoformat() if inc["effective_start"] else ""
            row["effective_end"] = inc["effective_end"].isoformat() if inc["effective_end"] else ""
            writer.writerow(row)
    print(f"  Exported {len(inclusions)} rows to {CSV_PATH}")


def update_manifest(inclusions: list):
    """Update manifest.json with section_301_inclusions.csv entry."""
    manifest = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)

    csv_hash = hashlib.sha256(open(CSV_PATH, "rb").read()).hexdigest()

    # PDF hash for drift detection
    pdf_hash = hashlib.sha256(open(PDF_PATH, "rb").read()).hexdigest() if PDF_PATH.exists() else None

    # Counts by list for quick sanity check
    counts_by_list = {}
    for inc in inclusions:
        list_name = inc["list_name"]
        counts_by_list[list_name] = counts_by_list.get(list_name, 0) + 1

    manifest.setdefault("files", {})
    manifest["files"]["section_301_inclusions.csv"] = {
        "row_count": len(inclusions),
        "sha256": csv_hash,
        "columns": CSV_COLUMNS,
        "exported_at": datetime.utcnow().isoformat(),
        "source": "USITC_HTS_Chapter99",
        "pdf_sha256": pdf_hash,
        "counts_by_list": counts_by_list,
        "total_inclusions": len(inclusions),
    }
    manifest["generated_at"] = datetime.utcnow().isoformat()

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Updated {MANIFEST_PATH}")


# ---------------------------------------------------------------------------
# Database Population
# ---------------------------------------------------------------------------

def populate_db(inclusions: list, reset: bool = False):
    """Insert/update inclusion rates in the database."""
    from app.web import create_app
    from app.web.db import db as flask_db
    from app.web.db.models.tariff_tables import Section301Rate

    app = create_app()
    with app.app_context():
        if reset:
            # FIX #2: Delete BOTH old PDF-sourced rows AND previous Chapter 99 rows
            total_deleted = 0

            # Delete old PDF-sourced rows
            for pattern in OLD_PDF_SOURCES:
                deleted = Section301Rate.query.filter(
                    Section301Rate.source_doc.like(pattern)
                ).delete(synchronize_session=False)
                total_deleted += deleted

            # Delete previous Chapter 99 inclusion rows
            deleted = Section301Rate.query.filter(
                Section301Rate.source_doc.like("USITC Chapter 99%")
            ).delete(synchronize_session=False)
            total_deleted += deleted

            # Delete rows by list_name for the 4 base lists
            for list_name in LIST_EFFECTIVE_DATES.keys():
                deleted = Section301Rate.query.filter(
                    Section301Rate.list_name == list_name
                ).delete(synchronize_session=False)
                total_deleted += deleted

            flask_db.session.commit()
            print(f"  Reset: deleted {total_deleted} existing inclusion rows")

        # OPTIMIZATION: Load all existing keys into memory first
        print("  Loading existing keys from DB...")
        existing_keys = set()
        for row in Section301Rate.query.with_entities(
            Section301Rate.hts_8digit,
            Section301Rate.chapter_99_code,
            Section301Rate.list_name,
            Section301Rate.effective_start
        ).all():
            existing_keys.add((row.hts_8digit, row.chapter_99_code, row.list_name, row.effective_start))
        print(f"  Loaded {len(existing_keys)} existing keys")

        inserted = 0
        skipped = 0

        # Batch insert new records
        batch = []
        for inc in inclusions:
            key = (inc["hts_8digit"], inc["chapter_99_code"], inc["list_name"], inc["effective_start"])

            if key in existing_keys:
                skipped += 1
                continue

            batch.append(Section301Rate(
                hts_8digit=inc["hts_8digit"],
                hts_10digit=inc.get("hts_10digit"),
                chapter_99_code=inc["chapter_99_code"],
                duty_rate=inc["duty_rate"],
                list_name=inc["list_name"],
                effective_start=inc["effective_start"],
                effective_end=inc.get("effective_end"),
                source_doc=inc["source_doc"],
                role="impose",  # Required field
                dataset_tag="USITC_CH99_CURRENT",  # New provenance field
                is_archived=False,  # Active dataset
            ))
            inserted += 1

            # Commit in batches
            if len(batch) >= 500:
                flask_db.session.bulk_save_objects(batch)
                flask_db.session.commit()
                print(f"    Progress: {inserted} inserted, {skipped} skipped...")
                batch = []

        # Final batch
        if batch:
            flask_db.session.bulk_save_objects(batch)
            flask_db.session.commit()

        print(f"  DB: {inserted} inserted, {skipped} skipped (already exist)")

        # Count by list
        for list_name in sorted(LIST_EFFECTIVE_DATES.keys()):
            count = Section301Rate.query.filter_by(list_name=list_name).count()
            print(f"    {list_name}: {count} rows")

        total = Section301Rate.query.count()
        print(f"  Total Section 301 rates in DB: {total}")


# ---------------------------------------------------------------------------
# Validation (FIX #5)
# ---------------------------------------------------------------------------

def validate_coverage_change(old_snapshot_path: str = "/tmp/section301_snapshot_before.json"):
    """Compare old vs new inclusion sets to measure coverage change."""
    from app.web import create_app
    from app.web.db.models.tariff_tables import Section301Rate

    # Load old snapshot
    try:
        with open(old_snapshot_path) as f:
            old_data = json.load(f)
    except FileNotFoundError:
        print(f"  Snapshot file not found: {old_snapshot_path}")
        print("  Skipping coverage validation")
        return

    app = create_app()
    with app.app_context():
        # Get new counts
        new_by_list = {}
        for list_name in LIST_EFFECTIVE_DATES.keys():
            rates = Section301Rate.query.filter_by(list_name=list_name).all()
            new_by_list[list_name] = set(r.hts_8digit for r in rates)

        old_by_list = {k: set(v) for k, v in old_data.get("by_list", {}).items()}

        print("\n" + "=" * 60)
        print("Coverage Change Analysis")
        print("=" * 60)

        for list_name in sorted(LIST_EFFECTIVE_DATES.keys()):
            old_codes = old_by_list.get(list_name, set())
            new_codes = new_by_list.get(list_name, set())

            added = new_codes - old_codes
            removed = old_codes - new_codes
            unchanged = old_codes & new_codes

            print(f"\n{list_name}:")
            print(f"  Old: {len(old_codes)} codes")
            print(f"  New: {len(new_codes)} codes")
            print(f"  Added: {len(added)} codes")
            print(f"  Removed: {len(removed)} codes")
            print(f"  Unchanged: {len(unchanged)} codes")

            if added and len(added) <= 10:
                print(f"  Added codes: {sorted(added)[:10]}")
            if removed and len(removed) <= 10:
                print(f"  Removed codes: {sorted(removed)[:10]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Populate Section 301 inclusions from USITC HTS Chapter 99"
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Download fresh Chapter 99 PDF from USITC before parsing"
    )
    parser.add_argument(
        "--csv-only", action="store_true",
        help="Export CSV only, do not write to database"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Delete all existing inclusion rows before inserting"
    )
    parser.add_argument(
        "--explore", action="store_true",
        help="Explore PDF to find note section page ranges"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Run coverage validation after population"
    )
    parser.add_argument(
        "--page-start", type=int, default=0,
        help="Start page for extraction (0-indexed)"
    )
    parser.add_argument(
        "--page-end", type=int, default=500,
        help="End page for extraction (0-indexed)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Section 301 Inclusions Ingestion")
    print("=" * 60)

    # Step 1: Download PDF if requested or missing
    if args.download or not PDF_PATH.exists():
        download_chapter99_pdf()
    else:
        size_mb = PDF_PATH.stat().st_size / (1024 * 1024)
        print(f"  Using existing PDF: {PDF_PATH} ({size_mb:.1f} MB)")

    # Explore mode: just find sections and exit
    if args.explore:
        print("\n" + "-" * 40)
        print("EXPLORE MODE: Finding Note 20 sections")
        print("-" * 40 + "\n")
        explore_pdf_for_notes(PDF_PATH)
        return

    # Step 2: Extract and parse
    print("\nParsing Note 20(pp)-(ss) from Chapter 99...")

    # Build source info string
    pdf_hash = hashlib.sha256(open(PDF_PATH, "rb").read()).hexdigest()[:12]
    source_info = f"USITC Chapter 99 currentRelease {pdf_hash}"

    full_text = extract_note_text(PDF_PATH, args.page_start, args.page_end)
    inclusions = parse_inclusion_sections(full_text, source_info)

    if not inclusions:
        print("\n  ERROR: No inclusions parsed! Try --explore to find correct page ranges.")
        return

    print(f"\n  TOTAL: {len(inclusions)} inclusion entries parsed")

    # Deduplicate (same HTS can appear multiple times in PDF text)
    seen = set()
    unique_inclusions = []
    for inc in inclusions:
        key = (inc["hts_8digit"], inc["list_name"])
        if key not in seen:
            seen.add(key)
            unique_inclusions.append(inc)

    if len(unique_inclusions) < len(inclusions):
        print(f"  Deduplicated: {len(unique_inclusions)} unique entries")
    inclusions = unique_inclusions

    # Step 3: Export CSV
    print("\nExporting CSV...")
    export_csv(inclusions)
    update_manifest(inclusions)

    # Step 4: Populate database (unless --csv-only)
    if not args.csv_only:
        print("\nPopulating database...")
        populate_db(inclusions, reset=args.reset)

        if args.validate:
            validate_coverage_change()
    else:
        print("\n  Skipping database (--csv-only mode)")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    by_list = {}
    for inc in inclusions:
        key = inc["list_name"]
        by_list[key] = by_list.get(key, 0) + 1
    for list_name, count in sorted(by_list.items()):
        effective = LIST_EFFECTIVE_DATES.get(list_name, "unknown")
        print(f"  {list_name}: {count} HTS codes (effective: {effective})")
    print(f"  TOTAL: {len(inclusions)}")
    print(f"  Source: {source_info}")
    print(f"  CSV: {CSV_PATH}")


if __name__ == "__main__":
    main()
