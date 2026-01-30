"""
Populate Section 301 Exclusion Claims from USITC HTS Chapter 99.

Parses U.S. Note 20(vvv)(i)-(iv) and 20(www) from the Chapter 99 PDF
to extract all Section 301 product exclusions granted under headings
9903.88.69 and 9903.88.70.

Data source: USITC HTS Archive — Chapter 99 (current release)
URL: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter+99

Effective window (from USTR FRN extending 178 exclusions):
  - Start: 2025-11-30
  - End:   2026-11-11 (end-exclusive for "through November 10, 2026")

Usage:
    cd lanes
    pipenv run python scripts/populate_exclusion_claims.py

    # Download fresh PDF from USITC before populating:
    pipenv run python scripts/populate_exclusion_claims.py --download

    # Export CSV only (no DB write):
    pipenv run python scripts/populate_exclusion_claims.py --csv-only

    # Reset (delete all existing claims before inserting):
    pipenv run python scripts/populate_exclusion_claims.py --reset
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
from uuid import uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PDF_URL = "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter+99"
PDF_PATH = Path(__file__).parent.parent / "data" / "chapter99_current.pdf"
CSV_PATH = Path(__file__).parent.parent / "data" / "current" / "exclusion_claims.csv"
MANIFEST_PATH = Path(__file__).parent.parent / "data" / "current" / "manifest.json"

# Effective window from USTR FRN extending 178 exclusions
EFFECTIVE_START = date(2025, 11, 30)
EFFECTIVE_END = date(2026, 11, 11)  # End-exclusive: "through November 10, 2026"

# PDF page range containing Note 20(vvv) and 20(www)
# Pages are 0-indexed in pdfplumber
NOTE_PAGES_START = 481
NOTE_PAGES_END = 492

# Section definitions: (note_bucket, claim_ch99_heading, source_heading, regex_pattern)
SECTION_DEFS = [
    {
        "note_bucket": "20(vvv)(i)",
        "claim_ch99_heading": "9903.88.69",
        "source_heading": "9903.88.01",
        "pattern": r"\(vvv\)\s*\(i\)\s*The U\.S\.",
    },
    {
        "note_bucket": "20(vvv)(ii)",
        "claim_ch99_heading": "9903.88.69",
        "source_heading": "9903.88.02",
        "pattern": r"\(ii\)\s*The U\.S\.Trade Representative determined to establish a process by which particular products classified in heading\s*\n?9903\.88\.02",
    },
    {
        "note_bucket": "20(vvv)(iii)",
        "claim_ch99_heading": "9903.88.69",
        "source_heading": "9903.88.03",
        "pattern": r"\(iii\)\s*The U\.S\.Trade Representative determined to establish a process by which particular products classified in heading\s*\n?9903\.88\.03",
    },
    {
        "note_bucket": "20(vvv)(iv)",
        "claim_ch99_heading": "9903.88.69",
        "source_heading": "9903.88.15",
        "pattern": r"\(iv\)\s*The U\.S\.Trade Representative determined to establish a process by which particular products classified in heading\s*\n?9903\.88\.15",
    },
    {
        "note_bucket": "20(www)",
        "claim_ch99_heading": "9903.88.70",
        "source_heading": "9903.88.02",
        "pattern": r"\(www\)\s*The U\.S\.Trade Representative",
    },
]


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
# PDF Parsing
# ---------------------------------------------------------------------------

def extract_note_text(pdf_path: Path) -> str:
    """Extract Note 20(vvv) and 20(www) text from Chapter 99 PDF."""
    import pdfplumber

    pdf = pdfplumber.open(str(pdf_path))
    print(f"  PDF has {len(pdf.pages)} pages, extracting pages {NOTE_PAGES_START}-{NOTE_PAGES_END}...")

    full_text = ""
    for i in range(NOTE_PAGES_START, NOTE_PAGES_END):
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


def extract_hts_codes(text: str) -> list:
    """Extract HTS10 codes from exclusion description text."""
    codes = set()
    # Match dotted format: 8536.90.4000
    for m in re.finditer(r"\b(\d{4}\.\d{2}\.\d{4})\b", text):
        codes.add(m.group(1).replace(".", ""))
    return sorted(codes)


def make_exclusion_id(note_bucket: str, item_number: int) -> str:
    """Generate stable exclusion_id from note bucket and item number.

    Examples: "vvvi-031", "vvvii-003", "www-014"
    """
    bucket_short = (
        note_bucket.replace("20(", "")
        .replace(")", "")
        .replace("(", "")
    )
    return f"{bucket_short}-{item_number:03d}"


def parse_sections(full_text: str) -> list:
    """Parse all exclusion entries from Note 20 text."""
    # Find section boundaries
    boundaries = []
    for sec in SECTION_DEFS:
        match = re.search(sec["pattern"], full_text)
        if match:
            boundaries.append({**sec, "start": match.start()})
        else:
            print(f"  WARNING: Section {sec['note_bucket']} not found in text!")

    all_exclusions = []
    for i, sec in enumerate(boundaries):
        end = boundaries[i + 1]["start"] if i + 1 < len(boundaries) else len(full_text)
        section_text = full_text[sec["start"]:end]

        # Find where the numbered list starts (after preamble ending with "reporting numbers:")
        list_start = re.search(
            r"(?:statistical reporting numbers?|subchapter):\s*\n", section_text
        )
        if list_start:
            items_text = section_text[list_start.end():]
        else:
            items_text = section_text

        # Split on numbered items: (1), (2), etc.
        parts = re.split(r"(?:^|\n)\s*\((\d+)\)\s*", items_text)

        prev_item_num = 0
        for j in range(1, len(parts), 2):
            if j + 1 >= len(parts):
                break
            item_num = int(parts[j])

            # Contiguity guard: stop if item numbers jump by more than 1
            # (e.g., www items 1-14 then suddenly "(21)" from Note 21 preamble)
            if prev_item_num > 0 and item_num > prev_item_num + 1:
                break
            prev_item_num = item_num

            item_text = parts[j + 1].strip()

            # Clean up multi-line text
            item_text = re.sub(r"\s+", " ", item_text).strip()

            # Extract HTS codes
            hts_codes = extract_hts_codes(item_text)

            # Build constraints
            constraints = {}
            if hts_codes:
                constraints["hts10_exact"] = hts_codes
                constraints["hts8_prefix"] = sorted(set(c[:8] for c in hts_codes))

            # Skip items with no HTS constraints (parser artifacts)
            if not constraints.get("hts10_exact"):
                continue

            # For bare HTS code entries (e.g., "8483.50.9040")
            bare_match = re.match(r"^(\d{4}\.\d{2}\.\d{4})\s*$", item_text)
            if bare_match:
                desc = f"Products described in statistical reporting number {bare_match.group(1)}"
            else:
                desc = item_text

            exclusion_id = make_exclusion_id(sec["note_bucket"], item_num)
            scope_hash = hashlib.sha256(desc.encode()).hexdigest()

            all_exclusions.append({
                "exclusion_id": exclusion_id,
                "note_bucket": sec["note_bucket"],
                "claim_ch99_heading": sec["claim_ch99_heading"],
                "source_heading": sec["source_heading"],
                "item_number": item_num,
                "hts_constraints": constraints,
                "description_scope_text": desc,
                "scope_text_hash": scope_hash,
                "effective_start": EFFECTIVE_START,
                "effective_end": EFFECTIVE_END,
                "verification_required": True,
            })

        print(
            f"  {sec['note_bucket']}: {sum(1 for e in all_exclusions if e['note_bucket'] == sec['note_bucket'])} exclusions "
            f"(claim: {sec['claim_ch99_heading']}, exempts from: {sec['source_heading']})"
        )

    return all_exclusions


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "exclusion_id",
    "note_bucket",
    "claim_ch99_heading",
    "source_heading",
    "item_number",
    "hts_constraints",
    "description_scope_text",
    "scope_text_hash",
    "effective_start",
    "effective_end",
    "verification_required",
]


def export_csv(exclusions: list):
    """Export exclusion claims to CSV."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for exc in exclusions:
            row = {k: exc[k] for k in CSV_COLUMNS}
            row["hts_constraints"] = json.dumps(exc["hts_constraints"])
            row["effective_start"] = exc["effective_start"].isoformat()
            row["effective_end"] = exc["effective_end"].isoformat()
            writer.writerow(row)
    print(f"  Exported {len(exclusions)} rows to {CSV_PATH}")


def update_manifest(exclusions: list):
    """Update manifest.json with exclusion_claims.csv entry."""
    manifest = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)

    csv_hash = hashlib.sha256(open(CSV_PATH, "rb").read()).hexdigest()

    # PDF hash for drift detection
    pdf_hash = hashlib.sha256(open(PDF_PATH, "rb").read()).hexdigest() if PDF_PATH.exists() else None

    # Counts by bucket for quick sanity check
    counts_by_bucket = {}
    for exc in exclusions:
        bucket = exc["note_bucket"]
        counts_by_bucket[bucket] = counts_by_bucket.get(bucket, 0) + 1

    manifest.setdefault("files", {})
    manifest["files"]["exclusion_claims.csv"] = {
        "row_count": len(exclusions),
        "sha256": csv_hash,
        "columns": CSV_COLUMNS,
        "exported_at": datetime.utcnow().isoformat(),
        "source": "USITC_HTS_Chapter99",
        "pdf_sha256": pdf_hash,
        "counts_by_bucket": counts_by_bucket,
        "total_exclusions": len(exclusions),
    }
    manifest["generated_at"] = datetime.utcnow().isoformat()

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Updated {MANIFEST_PATH}")


# ---------------------------------------------------------------------------
# Database Population
# ---------------------------------------------------------------------------

def populate_db(exclusions: list, reset: bool = False):
    """Insert exclusion claims into the database."""
    from app.web import create_app
    from app.web.db import db as flask_db
    from app.models.section301 import ExclusionClaim

    app = create_app()
    with app.app_context():
        # Ensure table exists (creates if missing, no-op if already there)
        ExclusionClaim.__table__.create(flask_db.engine, checkfirst=True)

        if reset:
            deleted = ExclusionClaim.query.delete()
            flask_db.session.commit()
            print(f"  Reset: deleted {deleted} existing exclusion claims")

        inserted = 0
        updated = 0
        skipped = 0

        for exc in exclusions:
            existing = ExclusionClaim.query.filter_by(
                exclusion_id=exc["exclusion_id"]
            ).first()

            if existing:
                # Check if scope text changed (via hash)
                if existing.scope_text_hash != exc["scope_text_hash"]:
                    existing.description_scope_text = exc["description_scope_text"]
                    existing.scope_text_hash = exc["scope_text_hash"]
                    existing.hts_constraints = exc["hts_constraints"]
                    existing.effective_start = exc["effective_start"]
                    existing.effective_end = exc["effective_end"]
                    existing.source_heading = exc["source_heading"]
                    updated += 1
                else:
                    skipped += 1
            else:
                claim = ExclusionClaim(
                    id=str(uuid4()),
                    exclusion_id=exc["exclusion_id"],
                    note_bucket=exc["note_bucket"],
                    claim_ch99_heading=exc["claim_ch99_heading"],
                    source_heading=exc["source_heading"],
                    hts_constraints=exc["hts_constraints"],
                    description_scope_text=exc["description_scope_text"],
                    scope_text_hash=exc["scope_text_hash"],
                    effective_start=exc["effective_start"],
                    effective_end=exc["effective_end"],
                    verification_required=True,
                )
                flask_db.session.add(claim)
                inserted += 1

        flask_db.session.commit()
        print(f"  DB: {inserted} inserted, {updated} updated, {skipped} unchanged")
        total = ExclusionClaim.query.count()
        print(f"  Total exclusion claims in DB: {total}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Populate Section 301 exclusion claims from USITC HTS Chapter 99"
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
        help="Delete all existing exclusion claims before inserting"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Section 301 Exclusion Claims Ingestion")
    print("=" * 60)

    # Step 1: Download PDF if requested or missing
    if args.download or not PDF_PATH.exists():
        download_chapter99_pdf()
    else:
        size_mb = PDF_PATH.stat().st_size / (1024 * 1024)
        print(f"  Using existing PDF: {PDF_PATH} ({size_mb:.1f} MB)")

    # Step 2: Extract and parse
    print("\nParsing Note 20(vvv) and 20(www) from Chapter 99...")
    full_text = extract_note_text(PDF_PATH)
    exclusions = parse_sections(full_text)
    print(f"\n  TOTAL: {len(exclusions)} exclusion entries parsed")

    # Step 3: Export CSV
    print("\nExporting CSV...")
    export_csv(exclusions)
    update_manifest(exclusions)

    # Step 4: Populate database (unless --csv-only)
    if not args.csv_only:
        print("\nPopulating database...")
        populate_db(exclusions, reset=args.reset)
    else:
        print("\n  Skipping database (--csv-only mode)")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    by_bucket = {}
    for exc in exclusions:
        key = exc["note_bucket"]
        by_bucket[key] = by_bucket.get(key, 0) + 1
    for bucket, count in sorted(by_bucket.items()):
        print(f"  {bucket}: {count} exclusions")
    print(f"  TOTAL: {len(exclusions)}")
    print(f"  Effective: {EFFECTIVE_START} to {EFFECTIVE_END} (end-exclusive)")
    print(f"  CSV: {CSV_PATH}")


if __name__ == "__main__":
    main()
