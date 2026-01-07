#!/usr/bin/env python
"""
Parse CBP Section 232 DOCX files and extract HTS codes.

This script extracts HTS codes from the official CBP documents:
- CBP_CopperHTSlist_2025-08-01.docx
- CBP_Updated_steelHTSlist_2025-08-18.docx
- CBP_Updated_aluminumHTSlist_2025-08-18.docx

Output: CSV file with columns: hts_code, material, chapter_99_claim, chapter_99_disclaim, duty_rate
"""

import os
import re
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Directory containing CBP documents
DOCS_DIR = Path(__file__).parent.parent / "docs" / "cbp_section232_official_lists"
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


def get_chapter_99_codes(hts_code: str, material: str) -> dict:
    """
    Determine Chapter 99 codes based on HTS code and material type.

    Per CBP guidance:
    - Primary articles: HTS chapters 72-73 (steel), 76 (aluminum)
    - Derivative articles: Other chapters containing metal content

    Returns dict with claim_code, disclaim_code, duty_rate
    """
    # Extract chapter from HTS code
    chapter = hts_code.replace('.', '')[:2]

    if material == 'copper':
        # Copper is same code regardless of chapter
        return {
            'claim_code': '9903.78.01',
            'disclaim_code': '9903.78.02',
            'duty_rate': 0.50
        }

    elif material == 'steel':
        # Steel primary = Chapters 72, 73
        if chapter in ['72', '73']:
            return {
                'claim_code': '9903.80.01',
                'disclaim_code': '9903.80.02',
                'duty_rate': 0.50
            }
        else:
            # Steel derivative (other chapters)
            return {
                'claim_code': '9903.81.91',
                'disclaim_code': '9903.80.02',
                'duty_rate': 0.50
            }

    elif material == 'aluminum':
        # Aluminum primary = Chapter 76
        if chapter == '76':
            return {
                'claim_code': '9903.85.03',
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50
            }
        else:
            # Aluminum derivative (other chapters)
            return {
                'claim_code': '9903.85.08',
                'disclaim_code': '9903.85.09',
                'duty_rate': 0.50
            }

    return {'claim_code': None, 'disclaim_code': None, 'duty_rate': 0.50}


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
            'chapter_99_claim': ch99['claim_code'],
            'chapter_99_disclaim': ch99['disclaim_code'],
            'duty_rate': ch99['duty_rate']
        })

    print(f"Copper: {len(results)} HTS codes extracted")
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
    for code in codes:
        ch99 = get_chapter_99_codes(code, 'steel')
        results.append({
            'hts_code': code,
            'material': 'steel',
            'chapter_99_claim': ch99['claim_code'],
            'chapter_99_disclaim': ch99['disclaim_code'],
            'duty_rate': ch99['duty_rate']
        })

    print(f"Steel: {len(results)} HTS codes extracted")
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
    for code in codes:
        ch99 = get_chapter_99_codes(code, 'aluminum')
        results.append({
            'hts_code': code,
            'material': 'aluminum',
            'chapter_99_claim': ch99['claim_code'],
            'chapter_99_disclaim': ch99['disclaim_code'],
            'duty_rate': ch99['duty_rate']
        })

    print(f"Aluminum: {len(results)} HTS codes extracted")
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
        fieldnames = ['hts_code', 'material', 'chapter_99_claim', 'chapter_99_disclaim', 'duty_rate']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    print(f"Output written to: {OUTPUT_FILE}")

    # Show sample
    print()
    print("Sample entries:")
    print("-" * 60)
    for entry in all_results[:5]:
        print(f"  {entry['hts_code']:15} | {entry['material']:8} | {entry['chapter_99_claim']}")
    print("  ...")

    return all_results


if __name__ == "__main__":
    main()
