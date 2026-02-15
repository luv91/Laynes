#!/usr/bin/env python3
"""
Parse EO 14326 Annex II PDF to extract Ch.99 heading → country → rate mapping.

Source: White House PDF (2025ReciprocalTariffs_7.31.eo_.pdf)
Contains headings 9903.02.01 through 9903.02.71.

Strategy:
  - pdfplumber TABLE extraction for heading codes and rates (primary)
  - pdfplumber TEXT extraction for country names (handles page-spanning entries)
  - Text-based rate fallback for entries truncated at page boundaries

Output: lanes/data/eo14326_annex_ch99_codes.csv

Usage:
    python scripts/parse_eo14326_annex.py
    python scripts/parse_eo14326_annex.py --pdf /path/to/local.pdf
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import pdfplumber
import requests

WHITEHOUSE_PDF_URL = (
    "https://www.whitehouse.gov/wp-content/uploads/2025/07/"
    "2025ReciprocalTariffs_7.31.eo_.pdf"
)

# ISO mapping for country names found in the PDF
COUNTRY_NAME_TO_ISO = {
    "Afghanistan": "AF",
    "Algeria": "DZ",
    "Angola": "AO",
    "Bangladesh": "BD",
    "Bolivia": "BO",
    "Bosnia and Herzegovina": "BA",
    "Botswana": "BW",
    "Brazil": "BR",
    "Brunei": "BN",
    "Cambodia": "KH",
    "Cameroon": "CM",
    "Chad": "TD",
    "Costa Rica": "CR",
    "Côte d'Ivoire": "CI",
    "Cote d'Ivoire": "CI",
    "Democratic Republic of the Congo": "CD",
    "Ecuador": "EC",
    "Equatorial Guinea": "GQ",
    "European Union": "EU",
    "Falkland Islands": "FK",
    "Fiji": "FJ",
    "Georgia": "GE",
    "Ghana": "GH",
    "Guyana": "GY",
    "Honduras": "HN",
    "Iceland": "IS",
    "India": "IN",
    "Indonesia": "ID",
    "Iraq": "IQ",
    "Israel": "IL",
    "Jamaica": "JM",
    "Japan": "JP",
    "Jordan": "JO",
    "Kazakhstan": "KZ",
    "Kenya": "KE",
    "Kosovo": "XK",
    "Laos": "LA",
    "Lesotho": "LS",
    "Liberia": "LR",
    "Libya": "LY",
    "Liechtenstein": "LI",
    "Madagascar": "MG",
    "Malawi": "MW",
    "Malaysia": "MY",
    "Mauritius": "MU",
    "Moldova": "MD",
    "Mongolia": "MN",
    "Morocco": "MA",
    "Mozambique": "MZ",
    "Myanmar": "MM",
    "Myanmar (Burma)": "MM",
    "Burma": "MM",
    "Namibia": "NA",
    "Nauru": "NR",
    "Nepal": "NP",
    "New Zealand": "NZ",
    "Nicaragua": "NI",
    "Nigeria": "NG",
    "North Macedonia": "MK",
    "Norway": "NO",
    "Pakistan": "PK",
    "Papua New Guinea": "PG",
    "Paraguay": "PY",
    "Philippines": "PH",
    "Republic of the Congo": "CG",
    "Rwanda": "RW",
    "Senegal": "SN",
    "Serbia": "RS",
    "Singapore": "SG",
    "South Africa": "ZA",
    "South Korea": "KR",
    "Sri Lanka": "LK",
    "Suriname": "SR",
    "Eswatini": "SZ",
    "Swaziland": "SZ",
    "Switzerland": "CH",
    "Syria": "SY",
    "Taiwan": "TW",
    "Tanzania": "TZ",
    "Thailand": "TH",
    "Togo": "TG",
    "Trinidad and Tobago": "TT",
    "Tunisia": "TN",
    "Turkey": "TR",
    "Uganda": "UG",
    "Ukraine": "UA",
    "United Kingdom": "GB",
    "Uruguay": "UY",
    "Vanuatu": "VU",
    "Venezuela": "VE",
    "Vietnam": "VN",
    "Zambia": "ZM",
    "Zimbabwe": "ZW",
}


def download_pdf(url: str, output_path: Path) -> Path:
    """Download PDF if not already present."""
    if output_path.exists():
        print(f"Using existing PDF: {output_path}")
        return output_path
    print(f"Downloading PDF from {url}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    output_path.write_bytes(resp.content)
    print(f"  Saved to {output_path} ({len(resp.content)} bytes)")
    return output_path


def extract_rates_from_tables(pdf_path: Path) -> dict[str, str]:
    """Extract heading code → rate from PDF table columns.

    Returns dict like {'9903.02.03': '30', '9903.02.04': '15', ...}
    Some entries at page boundaries will be missing.
    """
    rates = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                continue
            for table in tables:
                for row in table:
                    code = (row[0] or "").strip()
                    if not re.match(r"9903\.02\.\d{2}$", code):
                        continue
                    # Rate is in column 2 (General rate column)
                    rate_col = (row[2] or "")
                    rate_match = re.search(r"(\d+)%", rate_col)
                    if rate_match and code not in rates:
                        rates[code] = rate_match.group(1)
    return rates


def extract_countries_from_text(pdf_path: Path) -> dict[str, str]:
    """Extract heading code → country name from full concatenated text.

    Text extraction handles page-spanning entries better than table extraction
    because the full text naturally joins continuations across pages.
    """
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    countries = {}
    for num in range(2, 72):  # Skip .01 (transshipment)
        code = f"9903.02.{num:02d}"
        # Find 'articles the product of [COUNTRY]' after this heading code
        pattern = (
            re.escape(code)
            + r".{0,2000}?"
            + r"articles\s+the\s+product\s+of\s+(?:the\s+)?"
            + r"(.+?)"
            + r"(?:,\s*as\s+provided|\.\s*\.\s*\.)"
        )
        match = re.search(pattern, full_text, re.DOTALL)
        if match:
            country = re.sub(r"\s+", " ", match.group(1).strip())
            countries[code] = country
    return countries


def extract_rates_from_text(pdf_path: Path, missing_codes: list[str]) -> dict[str, str]:
    """Fallback: extract rates from full text for entries missing from table extraction.

    For entries that span page boundaries, the table extraction truncates the rate column.
    The full text still contains 'XX% XX%' near 'subheading +' patterns.
    """
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    rates = {}
    for code in missing_codes:
        num = int(code[-2:])
        next_code = f"9903.02.{num + 1:02d}"

        # Find this entry's text chunk
        start_match = re.search(
            re.escape(code) + r"\s+(?:Except|Articles)", full_text
        )
        if not start_match:
            continue

        # Find next entry's start (or end of text)
        end_match = re.search(
            re.escape(next_code) + r"\s+(?:Except|Articles|For)",
            full_text[start_match.end():],
        )
        if end_match:
            chunk = full_text[start_match.start():start_match.end() + end_match.start()]
        else:
            chunk = full_text[start_match.start():start_match.start() + 2000]

        # Find all percentage values in the chunk, take the first valid one (5-50%)
        pct_matches = re.findall(r"(\d+)%", chunk)
        valid = [p for p in pct_matches if 5 <= int(p) <= 50]
        if valid:
            rates[code] = valid[0]

    return rates


def parse_headings(pdf_path: Path) -> list[dict]:
    """Parse all 71 headings using hybrid table + text extraction."""
    print("  Phase 1: Extracting rates from PDF tables...")
    table_rates = extract_rates_from_tables(pdf_path)
    print(f"    Found rates for {len(table_rates)} headings from tables")

    print("  Phase 2: Extracting country names from full text...")
    text_countries = extract_countries_from_text(pdf_path)
    print(f"    Found country names for {len(text_countries)} headings from text")

    # Identify headings missing rates from table extraction
    expected_codes = [f"9903.02.{i:02d}" for i in range(2, 72)]
    missing_rate_codes = [c for c in expected_codes if c not in table_rates]
    # Exclude special EU codes that have no standard rate
    missing_rate_codes = [c for c in missing_rate_codes if c not in ("9903.02.19",)]

    if missing_rate_codes:
        print(f"  Phase 3: Text fallback for {len(missing_rate_codes)} missing rates...")
        text_rates = extract_rates_from_text(pdf_path, missing_rate_codes)
        print(f"    Recovered {len(text_rates)} rates from text")
    else:
        text_rates = {}

    # Merge all rates
    all_rates = {**table_rates, **text_rates}

    # Build results list
    results = []

    # 9903.02.01: Transshipment (special)
    results.append({
        "ch99_code": "9903.02.01",
        "country_name": "Transshipment (any country)",
        "iso_alpha2": "",
        "rate_pct": "40",
        "special": "TRANSSHIPMENT",
    })

    for num in range(2, 72):
        code = f"9903.02.{num:02d}"

        # EU special codes
        if code == "9903.02.19":
            results.append({
                "ch99_code": code,
                "country_name": "European Union (MFN >= 15%)",
                "iso_alpha2": "EU",
                "rate_pct": "0",
                "special": "MFN_CEILING_ZERO",
            })
            continue

        if code == "9903.02.20":
            results.append({
                "ch99_code": code,
                "country_name": "European Union (MFN < 15%)",
                "iso_alpha2": "EU",
                "rate_pct": "15",
                "special": "MFN_CEILING_TOPUP",
            })
            continue

        # Standard country entry
        country_name = text_countries.get(code, "")
        rate = all_rates.get(code, "")

        # Map to ISO
        iso2 = ""
        if country_name:
            iso2 = COUNTRY_NAME_TO_ISO.get(country_name, "")
            if not iso2:
                # Try partial match
                for known_name, known_iso in COUNTRY_NAME_TO_ISO.items():
                    if known_name.lower() in country_name.lower():
                        iso2 = known_iso
                        break

        results.append({
            "ch99_code": code,
            "country_name": country_name,
            "iso_alpha2": iso2,
            "rate_pct": rate,
            "special": "",
        })

    return results


def write_csv(results: list[dict], output_path: Path):
    """Write parsed data to CSV."""
    fieldnames = ["ch99_code", "iso_alpha2", "country_name", "rate_pct", "special"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} headings to {output_path}")


def validate_results(results: list[dict]):
    """Check for parsing issues."""
    issues = []
    for r in results:
        if not r["country_name"]:
            issues.append(f"  {r['ch99_code']}: missing country name")
        if not r["rate_pct"]:
            issues.append(f"  {r['ch99_code']}: missing rate")
        if not r["iso_alpha2"] and r["special"] not in ("TRANSSHIPMENT",):
            issues.append(f"  {r['ch99_code']}: no ISO code for '{r['country_name']}'")

    if issues:
        print(f"\nWARNING: {len(issues)} parsing issues:")
        for issue in issues:
            print(issue)
    else:
        print("\nAll headings parsed successfully - no issues.")

    # Summary
    country_count = sum(
        1 for r in results
        if r["iso_alpha2"] and r["special"] not in ("TRANSSHIPMENT", "MFN_CEILING_ZERO", "MFN_CEILING_TOPUP")
    )
    print(f"\nSummary:")
    print(f"  Total headings:     {len(results)}")
    print(f"  Country headings:   {country_count}")
    print(f"  Special headings:   {len(results) - country_count}")
    print(f"  Range: {results[0]['ch99_code']} – {results[-1]['ch99_code']}")

    # Verify sequential codes
    expected_codes = [f"9903.02.{i:02d}" for i in range(1, 72)]
    actual_codes = [r["ch99_code"] for r in results]
    if actual_codes != expected_codes:
        print("\n  WARNING: Code sequence mismatch!")
        missing = set(expected_codes) - set(actual_codes)
        extra = set(actual_codes) - set(expected_codes)
        if missing:
            print(f"  Missing: {sorted(missing)}")
        if extra:
            print(f"  Extra: {sorted(extra)}")
    else:
        print(f"  Sequence: {len(actual_codes)} codes, 9903.02.01–9903.02.71, all present ✓")


def main():
    parser = argparse.ArgumentParser(
        description="Parse EO 14326 Annex II PDF for Ch.99 code mappings"
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Path to local PDF (downloads from White House if not provided)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "eo14326_annex_ch99_codes.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("EO 14326 Annex II Parser")
    print("=" * 60)

    # Get PDF
    if args.pdf:
        pdf_path = args.pdf
    else:
        pdf_path = Path(__file__).parent.parent / "data" / "eo14326_whitehouse.pdf"
        download_pdf(WHITEHOUSE_PDF_URL, pdf_path)

    # Parse headings
    print(f"\nParsing {pdf_path}...")
    results = parse_headings(pdf_path)

    # Validate
    validate_results(results)

    # Write CSV
    write_csv(results, args.output)

    # Show all headings
    print("\nAll headings:")
    for r in results:
        special = f"  [{r['special']}]" if r["special"] else ""
        print(f"  {r['ch99_code']}  {r['iso_alpha2']:>2}  {r['rate_pct']:>3}%  {r['country_name']}{special}")

    print("\n[DONE] Review the CSV for accuracy.")


if __name__ == "__main__":
    main()
