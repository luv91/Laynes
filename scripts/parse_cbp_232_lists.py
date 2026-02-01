#!/usr/bin/env python
"""
Parse CBP Section 232 DOCX files and extract HTS codes.

This script extracts HTS codes from the official CBP documents:
- CBP_CopperHTSlist_2025-08-01.docx
- CBP_Updated_steelHTSlist_2025-08-18.docx
- CBP_Updated_aluminumHTSlist_2025-08-18.docx

Output: CSV file with columns: hts_code, material, article_type, chapter_99_claim, chapter_99_disclaim, duty_rate

Article types per U.S. Note 16 to Chapter 99:
- 'primary': Raw mill products (Ch 72 steel, Ch 76 raw aluminum 7601-7609) - full value assessment
- 'derivative': Finished articles (Ch 73 steel, Ch 76 finished aluminum 7610-7616) - full value assessment
- 'content': Other chapters with metal content - content value only

Steel Subdivisions per CSMS #65936570:
- Subdivision (l): Legacy derivatives → 9903.81.89 (enumerated codes only)
- Subdivision (m): March 2025 additions → 9903.81.90 (Ch 73 codes NOT in subdivision l)

Aluminum Subdivisions per CBP Aluminum HTS List:
- Subdivision (i): Primary aluminum (7601-7609) → 9903.85.03
- Subdivision (j): Derivative aluminum (7610-7616) → 9903.85.07
"""

import os
import re
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# ============================================================================
# SUBDIVISION (l) ENUMERATED CODES - Steel derivatives using 9903.81.89
# Per CSMS #65936570 and U.S. Note 16(l) to Chapter 99
# All other Ch 73 codes fall under subdivision (m) → 9903.81.90
# ============================================================================
SUBDIVISION_L_STEEL_CODES = {
    # Nails explicitly enumerated in subdivision (l)
    "7317.00.30",      # All codes under this subheading
    "7317.00.5503",
    "7317.00.5505",
    "7317.00.5507",
    "7317.00.5560",
    "7317.00.5580",
    "7317.00.6560",
    # Automotive stampings enumerated in Note 16(l)
    # (bumper stampings under 8708.10, body stampings under 8708.29)
    # These are handled separately as they're in Ch 87, not Ch 73
}

# Subheadings where the ENTIRE subheading is in subdivision (l)
SUBDIVISION_L_FULL_SUBHEADINGS = {
    "7317.00.30",  # All nails under 7317.00.30 are subdivision (l)
}

# ============================================================================
# ALUMINUM HEADING CLASSIFICATION
# Per CBP Aluminum HTS List and U.S. Note 16 to Chapter 99
# ============================================================================
# Primary aluminum headings (raw mill products) → 9903.85.03
ALUMINUM_PRIMARY_HEADINGS = {
    "7601",  # Unwrought aluminum
    "7602",  # Aluminum waste and scrap
    "7603",  # Aluminum powders and flakes
    "7604",  # Aluminum bars, rods and profiles
    "7605",  # Aluminum wire
    "7606",  # Aluminum plates, sheets and strip
    "7607",  # Aluminum foil
    "7608",  # Aluminum tubes and pipes
    "7609",  # Aluminum tube or pipe fittings
}

# Derivative aluminum headings (finished articles) → 9903.85.07
ALUMINUM_DERIVATIVE_HEADINGS = {
    "7610",  # Aluminum structures
    "7611",  # Aluminum reservoirs, tanks, vats
    "7612",  # Aluminum casks, drums, cans
    "7613",  # Aluminum containers for compressed gas
    "7614",  # Stranded wire, cables, plaited bands
    "7615",  # Table, kitchen articles (bakeware, etc.)
    "7616",  # Other articles of aluminum
}

# Directory containing CBP documents
DOCS_DIR = Path(__file__).parent.parent / "data" / "source_docs" / "section232"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "section_232_hts_codes.csv"


def extract_text_from_docx(docx_path: str) -> str:
    """Extract all text content from a DOCX file."""
    with zipfile.ZipFile(docx_path, 'r') as zip_ref:
        xml_content = zip_ref.read('word/document.xml')

    # Parse XML
    root = ET.fromstring(xml_content)

    # Define namespaces
    namespaces = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    }

    # Extract all text from <w:t> elements
    texts = []
    for elem in root.iter():
        if elem.tag.endswith('}t'):
            if elem.text:
                texts.append(elem.text)

    return '\n'.join(texts)


def extract_hts_codes(text: str) -> list:
    """Extract HTS codes from text content."""
    # Pattern for HTS codes: 4 digits, dot, 2+ digits (with optional more segments)
    # Examples: 7406.10.00, 7317.00.5502, 8302.41.6015
    pattern = r'\b(\d{4}\.\d{2}\.\d{2,4}(?:\.\d{2,4})?)\b'

    codes = re.findall(pattern, text)
    # Deduplicate while preserving order
    seen = set()
    unique_codes = []
    for code in codes:
        # Skip Chapter 99 codes (tariff markers, not products)
        if code.startswith('99'):
            continue
        if code not in seen:
            seen.add(code)
            unique_codes.append(code)

    return unique_codes


def get_article_type(hts_code: str, material: str) -> str:
    """
    Determine article type per U.S. Note 16 to Chapter 99.

    Article types determine valuation rules:
    - 'primary': Full value assessment (Ch 72 steel, Ch 76 raw aluminum 7601-7609)
    - 'derivative': Full value assessment (Ch 73 steel articles, Ch 76 finished aluminum 7610-7616)
    - 'content': Content value only (all other chapters)

    Copper is always 'primary' per Proclamation 10896.
    """
    chapter = hts_code.replace('.', '')[:2]
    heading = hts_code.replace('.', '')[:4]

    if material == 'copper':
        if chapter == '74':
            return 'primary'  # Chapter 74 copper articles
        else:
            return 'content'  # Copper as component in other products

    elif material == 'steel':
        if chapter == '72':
            return 'primary'  # Raw steel mill products
        elif chapter == '73':
            return 'derivative'  # Steel articles (nails, screws, etc.)
        else:
            return 'content'  # Steel as component in other products

    elif material == 'aluminum':
        if chapter == '76':
            # Distinguish between raw materials and finished articles
            if heading in ALUMINUM_PRIMARY_HEADINGS:
                return 'primary'  # Raw aluminum mill products (7601-7609)
            elif heading in ALUMINUM_DERIVATIVE_HEADINGS:
                return 'derivative'  # Finished aluminum articles (7610-7616)
            else:
                return 'primary'  # Default for unknown Ch 76 headings
        else:
            return 'content'  # Aluminum as component in other products

    return 'content'


def is_subdivision_l_code(hts_code: str) -> bool:
    """
    Check if a steel HTS code is in subdivision (l) per CSMS #65936570.

    Subdivision (l) codes use 9903.81.89.
    All other Ch 73 codes use subdivision (m) → 9903.81.90.
    """
    # Check exact match
    if hts_code in SUBDIVISION_L_STEEL_CODES:
        return True

    # Check if the code falls under a full subheading that's in subdivision (l)
    # e.g., 7317.00.3045 falls under 7317.00.30
    for subheading in SUBDIVISION_L_FULL_SUBHEADINGS:
        if hts_code.startswith(subheading.replace('.', '')[:8]):
            return True

    return False


def get_chapter_99_codes(hts_code: str, material: str) -> dict:
    """
    Determine Chapter 99 codes based on HTS code and material type.

    Per CBP guidance and U.S. Note 16:

    Steel:
    - Primary articles: Ch 72 → 9903.80.01
    - Derivative articles (subdivision l): enumerated Ch 73 codes → 9903.81.89
    - Derivative articles (subdivision m): other Ch 73 codes → 9903.81.90
    - Content articles: Other chapters → 9903.81.91

    Aluminum:
    - Primary articles: Ch 76 raw (7601-7609) → 9903.85.03
    - Derivative articles: Ch 76 finished (7610-7616) → 9903.85.07
    - Content articles: Other chapters → 9903.85.08

    Returns dict with article_type, claim_code, disclaim_code, duty_rate
    """
    # Get article type first
    article_type = get_article_type(hts_code, material)
    chapter = hts_code.replace('.', '')[:2]

    if material == 'copper':
        # Copper is same code regardless of chapter (all primary)
        return {
            'article_type': article_type,
            'claim_code': '9903.78.01',
            'disclaim_code': '9903.78.02',
            'duty_rate': 0.50
        }

    elif material == 'steel':
        if article_type == 'primary':
            # Ch 72: Raw steel mill products
            return {
                'article_type': article_type,
                'claim_code': '9903.80.01',
                'disclaim_code': '9903.80.02',
                'duty_rate': 0.50
            }
        elif article_type == 'derivative':
            # Ch 73: Steel articles - check subdivision (l) vs (m)
            if is_subdivision_l_code(hts_code):
                # Subdivision (l): Legacy derivatives (enumerated codes)
                return {
                    'article_type': article_type,
                    'claim_code': '9903.81.89',
                    'disclaim_code': '9903.80.02',
                    'duty_rate': 0.50
                }
            else:
                # Subdivision (m): March 2025 additions (non-enumerated Ch 73)
                return {
                    'article_type': article_type,
                    'claim_code': '9903.81.90',  # NEW: subdivision (m) code
                    'disclaim_code': '9903.80.02',
                    'duty_rate': 0.50
                }
        else:
            # Content: Steel as component in other products
            return {
                'article_type': article_type,
                'claim_code': '9903.81.91',
                'disclaim_code': '9903.80.02',
                'duty_rate': 0.50
            }

    elif material == 'aluminum':
        if article_type == 'primary':
            # Ch 76 raw: Unwrought aluminum and semi-finished products (7601-7609)
            return {
                'article_type': article_type,
                'claim_code': '9903.85.03',
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50
            }
        elif article_type == 'derivative':
            # Ch 76 finished: Aluminum articles (7610-7616)
            return {
                'article_type': article_type,
                'claim_code': '9903.85.07',  # NEW: derivative aluminum code
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50
            }
        else:
            # Content: Aluminum as component in other products
            return {
                'article_type': article_type,
                'claim_code': '9903.85.08',
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50
            }

    return {'article_type': 'content', 'claim_code': None, 'disclaim_code': None, 'duty_rate': 0.50}


def parse_copper_list():
    """Parse copper HTS list."""
    docx_path = DOCS_DIR / "CBP_CopperHTSlist_2025-08-01.docx"
    if not docx_path.exists():
        print(f"Warning: {docx_path} not found")
        return []

    text = extract_text_from_docx(str(docx_path))
    codes = extract_hts_codes(text)

    results = []
    for code in codes:
        ch99 = get_chapter_99_codes(code, 'copper')
        results.append({
            'hts_code': code,
            'material': 'copper',
            'article_type': ch99['article_type'],
            'chapter_99_claim': ch99['claim_code'],
            'chapter_99_disclaim': ch99['disclaim_code'],
            'duty_rate': ch99['duty_rate']
        })

    print(f"Copper: {len(results)} HTS codes extracted (all primary)")
    return results


def parse_steel_list():
    """Parse steel HTS list."""
    docx_path = DOCS_DIR / "CBP_Updated_steelHTSlist_2025-08-18.docx"
    if not docx_path.exists():
        print(f"Warning: {docx_path} not found")
        return []

    text = extract_text_from_docx(str(docx_path))
    codes = extract_hts_codes(text)

    results = []
    type_counts = {'primary': 0, 'derivative': 0, 'content': 0}
    subdivision_counts = {'9903.80.01': 0, '9903.81.89': 0, '9903.81.90': 0, '9903.81.91': 0}
    for code in codes:
        ch99 = get_chapter_99_codes(code, 'steel')
        type_counts[ch99['article_type']] += 1
        if ch99['claim_code'] in subdivision_counts:
            subdivision_counts[ch99['claim_code']] += 1
        results.append({
            'hts_code': code,
            'material': 'steel',
            'article_type': ch99['article_type'],
            'chapter_99_claim': ch99['claim_code'],
            'chapter_99_disclaim': ch99['disclaim_code'],
            'duty_rate': ch99['duty_rate']
        })

    print(f"Steel: {len(results)} HTS codes extracted")
    print(f"  By article_type:")
    print(f"    - Primary (Ch 72): {type_counts['primary']}")
    print(f"    - Derivative (Ch 73): {type_counts['derivative']}")
    print(f"    - Content (other): {type_counts['content']}")
    print(f"  By Chapter 99 code:")
    print(f"    - 9903.80.01 (primary): {subdivision_counts['9903.80.01']}")
    print(f"    - 9903.81.89 (subdivision l): {subdivision_counts['9903.81.89']}")
    print(f"    - 9903.81.90 (subdivision m): {subdivision_counts['9903.81.90']}")
    print(f"    - 9903.81.91 (content): {subdivision_counts['9903.81.91']}")
    return results


def parse_aluminum_list():
    """Parse aluminum HTS list."""
    docx_path = DOCS_DIR / "CBP_Updated_aluminumHTSlist_2025-08-18.docx"
    if not docx_path.exists():
        print(f"Warning: {docx_path} not found")
        return []

    text = extract_text_from_docx(str(docx_path))
    codes = extract_hts_codes(text)

    results = []
    type_counts = {'primary': 0, 'derivative': 0, 'content': 0}
    subdivision_counts = {'9903.85.03': 0, '9903.85.07': 0, '9903.85.08': 0}
    for code in codes:
        ch99 = get_chapter_99_codes(code, 'aluminum')
        type_counts[ch99['article_type']] += 1
        if ch99['claim_code'] in subdivision_counts:
            subdivision_counts[ch99['claim_code']] += 1
        results.append({
            'hts_code': code,
            'material': 'aluminum',
            'article_type': ch99['article_type'],
            'chapter_99_claim': ch99['claim_code'],
            'chapter_99_disclaim': ch99['disclaim_code'],
            'duty_rate': ch99['duty_rate']
        })

    print(f"Aluminum: {len(results)} HTS codes extracted")
    print(f"  By article_type:")
    print(f"    - Primary (Ch 76, 7601-7609): {type_counts['primary']}")
    print(f"    - Derivative (Ch 76, 7610-7616): {type_counts['derivative']}")
    print(f"    - Content (other chapters): {type_counts['content']}")
    print(f"  By Chapter 99 code:")
    print(f"    - 9903.85.03 (primary): {subdivision_counts['9903.85.03']}")
    print(f"    - 9903.85.07 (derivative): {subdivision_counts['9903.85.07']}")
    print(f"    - 9903.85.08 (content): {subdivision_counts['9903.85.08']}")
    return results


def main():
    """Parse all CBP documents and generate CSV."""
    print("=" * 60)
    print("CBP Section 232 HTS Code Parser")
    print("=" * 60)
    print()

    # Ensure output directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Parse all documents
    all_results = []
    all_results.extend(parse_copper_list())
    all_results.extend(parse_steel_list())
    all_results.extend(parse_aluminum_list())

    print()
    print(f"Total: {len(all_results)} HTS code entries")

    # Write CSV
    with open(OUTPUT_FILE, 'w', newline='') as f:
        fieldnames = ['hts_code', 'material', 'article_type', 'chapter_99_claim', 'chapter_99_disclaim', 'duty_rate']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    print(f"Output written to: {OUTPUT_FILE}")

    # Show sample by article type
    print()
    print("Sample entries by article_type:")
    print("-" * 80)
    # Show one of each type
    shown_types = set()
    for entry in all_results:
        atype = entry['article_type']
        if atype not in shown_types:
            print(f"  {entry['hts_code']:15} | {entry['material']:8} | {atype:10} | {entry['chapter_99_claim']}")
            shown_types.add(atype)
    print("  ...")

    return all_results


if __name__ == "__main__":
    main()
