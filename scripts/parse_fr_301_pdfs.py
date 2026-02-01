#!/usr/bin/env python3
"""
Section 301 HTS Code Extraction Script

Extracts HTS codes from Federal Register Section 301 notice PDFs using a
hybrid pdfplumber + LLM (Gemini) chunked extraction approach.

Usage:
    # Set API key
    export GEMINI_API_KEY="your-key-here"

    # Run extraction for all lists
    pipenv run python scripts/parse_fr_301_pdfs.py

    # Run extraction for specific list(s)
    pipenv run python scripts/parse_fr_301_pdfs.py --list list_1
    pipenv run python scripts/parse_fr_301_pdfs.py --list list_1 --list list_2

Output:
    data/section_301_hts_codes.csv
"""

import argparse
import csv
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import pdfplumber

# Try to import google.generativeai (Gemini SDK)
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    print("Warning: google-generativeai not installed. LLM extraction disabled.")

# ============================================
# CONFIGURATION
# ============================================

DOCS_DIR = Path(__file__).parent.parent / "data" / "source_docs" / "section301"
OUTPUT_DIR = Path(__file__).parent.parent / "data"

# Section 301 List configurations
# Note: List 4B is SUSPENDED per FR-2019-27306 - do not import
LIST_CONFIGS = {
    "list_1": {
        "pdf": "section301/FR-2018-06-20_2018-13248_List1.pdf",
        "chapter_99_code": "9903.88.01",
        "duty_rate": 0.25,
        "source_doc": "FR-2018-13248",
        "description": "Section 301 List 1 - Initial 25% tariff"
    },
    "list_2": {
        "pdf": "section301/FR-2018-08-16_2018-17709_List2.pdf",
        "chapter_99_code": "9903.88.02",
        "duty_rate": 0.25,
        "source_doc": "FR-2018-17709",
        "description": "Section 301 List 2 - 25% tariff"
    },
    "list_3": {
        "pdf": "section301/FR-2018-09-21_2018-20610_List3_initial.pdf",
        "chapter_99_code": "9903.88.03",
        "duty_rate": 0.25,  # Confirmed by FR-2019-09681 rate increase notice
        "source_doc": "FR-2018-20610",
        "description": "Section 301 List 3 - 25% tariff (largest list)"
    },
    "list_4a": {
        "pdf": "section301/FR-2019-08-20_2019-17865_List4A_4B_notice.pdf",
        "chapter_99_code": "9903.88.15",
        "duty_rate": 0.075,  # 7.5% per FR-2020-00904 rate reduction
        "source_doc": "FR-2019-17865",
        "description": "Section 301 List 4A - 7.5% tariff"
    },
    # list_4b: SUSPENDED per FR-2019-27306 - DO NOT IMPORT
}

# Chunking parameters
CHUNK_SIZE = 2000  # Characters per chunk
CHUNK_OVERLAP = 200  # Overlap between chunks for context continuity

# Rate limiting for Gemini API
API_DELAY_SECONDS = 0.5  # Delay between API calls to avoid rate limits


# ============================================
# PDF EXTRACTION (pdfplumber)
# ============================================

def extract_pdf_text(pdf_path: str) -> list[dict]:
    """
    Extract text from PDF page by page using pdfplumber.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of dicts with page_num and text for each page
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append({
                "page_num": i + 1,
                "text": text
            })
    return pages


# ============================================
# TEXT CHUNKING
# ============================================

def chunk_text(pages: list[dict], chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split pages into LLM-friendly chunks with page references.

    Args:
        pages: List of page dicts from extract_pdf_text
        chunk_size: Maximum characters per chunk
        overlap: Characters to overlap between chunks

    Returns:
        List of chunk dicts with chunk_id, page refs, and text
    """
    chunks = []
    current_chunk = ""
    current_pages = []

    for page in pages:
        text = page["text"]
        page_num = page["page_num"]

        # Add page marker
        page_text = f"\n--- Page {page_num} ---\n{text}"

        if len(current_chunk) + len(page_text) <= chunk_size:
            # Fits in current chunk
            current_chunk += page_text
            if page_num not in current_pages:
                current_pages.append(page_num)
        else:
            # Need to start a new chunk
            if current_chunk:
                chunks.append({
                    "chunk_id": len(chunks),
                    "page_start": min(current_pages) if current_pages else page_num,
                    "page_end": max(current_pages) if current_pages else page_num,
                    "text": current_chunk
                })

            # Start new chunk with overlap from previous
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else ""
            current_chunk = overlap_text + page_text
            current_pages = [page_num]

    # Don't forget the last chunk
    if current_chunk:
        chunks.append({
            "chunk_id": len(chunks),
            "page_start": min(current_pages) if current_pages else 0,
            "page_end": max(current_pages) if current_pages else 0,
            "text": current_chunk
        })

    return chunks


# ============================================
# LLM EXTRACTION (Gemini)
# ============================================

EXTRACTION_PROMPT = """You are extracting HTS codes from a Federal Register Section 301 notice annex.

This is from {list_name} (Chapter 99 code: {chapter_99_code}).

Extract ALL HTS codes (tariff numbers) from this text. HTS codes look like:
- 8544.42.90
- 8471.30.0100
- 7318.15.20
- 8517.62.00

Return ONLY a JSON array of objects:
[
  {{"hts_code": "8544.42.90", "description": "brief description if available"}},
  ...
]

Rules:
- Include codes in format XXXX.XX.XX or XXXX.XX.XXXX (8 or 10 digits with dots)
- Do NOT include Chapter 99 codes (9903.xx.xx) - those are tariff heading codes, not product codes
- Do NOT include partial codes or ranges
- If no HTS codes found in this chunk, return: []

TEXT CHUNK:
{chunk_text}"""


def extract_hts_with_llm(chunk: dict, list_name: str, chapter_99_code: str,
                         model) -> list[dict]:
    """
    Send chunk to Gemini for structured HTS extraction.

    Args:
        chunk: Chunk dict with text and page refs
        list_name: Name of the list (e.g., "list_1")
        chapter_99_code: Chapter 99 code for this list
        model: Gemini model instance

    Returns:
        List of dicts with hts_code, description, and page refs
    """
    prompt = EXTRACTION_PROMPT.format(
        list_name=list_name,
        chapter_99_code=chapter_99_code,
        chunk_text=chunk["text"]
    )

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()

        # Handle markdown code blocks
        if "```" in text:
            # Extract content between code blocks
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1]
                # Remove language identifier if present
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

        # Parse JSON
        codes = json.loads(text)

        # Add page reference to each code
        for code in codes:
            code["page_start"] = chunk["page_start"]
            code["page_end"] = chunk["page_end"]

        return codes

    except json.JSONDecodeError as e:
        print(f"    Warning: JSON parse error for chunk {chunk['chunk_id']}: {e}")
        return []
    except Exception as e:
        print(f"    Warning: Error processing chunk {chunk['chunk_id']}: {e}")
        return []


# ============================================
# REGEX-BASED EXTRACTION (Fallback)
# ============================================

# Pattern for HTS codes: XXXX.XX.XX or XXXX.XX.XXXX
HTS_PATTERN = re.compile(r'\b(\d{4}\.\d{2}\.\d{2,4})\b')

# Pattern to exclude Chapter 99 codes
CHAPTER_99_PATTERN = re.compile(r'^99\d{2}\.')


def extract_hts_with_regex(chunk: dict) -> list[dict]:
    """
    Fallback extraction using regex (no LLM).

    Args:
        chunk: Chunk dict with text and page refs

    Returns:
        List of dicts with hts_code and page refs
    """
    matches = HTS_PATTERN.findall(chunk["text"])
    codes = []

    for match in matches:
        # Skip Chapter 99 codes
        if CHAPTER_99_PATTERN.match(match):
            continue
        codes.append({
            "hts_code": match,
            "description": "",
            "page_start": chunk["page_start"],
            "page_end": chunk["page_end"]
        })

    return codes


# ============================================
# VALIDATION
# ============================================

HTS_VALIDATE_PATTERN = re.compile(r'^\d{4}\.\d{2}\.\d{2,4}$')


def validate_hts(code: str) -> bool:
    """
    Validate HTS code format.

    Args:
        code: HTS code string

    Returns:
        True if valid format, False otherwise
    """
    if not code:
        return False
    # Must match pattern and not be a Chapter 99 code
    return bool(HTS_VALIDATE_PATTERN.match(code)) and not code.startswith("99")


def normalize_hts(code: str) -> str:
    """
    Normalize HTS code to standard format.

    Args:
        code: Raw HTS code string

    Returns:
        Cleaned HTS code
    """
    return code.strip().replace(" ", "")


# ============================================
# MAIN PIPELINE
# ============================================

def process_list_pdf(list_name: str, config: dict, model=None,
                     use_llm: bool = True) -> list[dict]:
    """
    Full pipeline for processing one List PDF.

    Args:
        list_name: Name of the list (e.g., "list_1")
        config: Configuration dict for this list
        model: Gemini model instance (optional)
        use_llm: Whether to use LLM extraction (vs regex fallback)

    Returns:
        List of validated, deduplicated HTS code records
    """
    pdf_path = DOCS_DIR / config["pdf"]
    print(f"\n{'='*60}")
    print(f"Processing {list_name}: {config['description']}")
    print(f"PDF: {pdf_path}")
    print(f"{'='*60}")

    if not pdf_path.exists():
        print(f"  ERROR: PDF not found at {pdf_path}")
        return []

    # Step 1: Extract text from PDF
    print("  Step 1: Extracting text from PDF...")
    pages = extract_pdf_text(str(pdf_path))
    print(f"    Extracted {len(pages)} pages")

    # Step 2: Chunk text
    print("  Step 2: Chunking text...")
    chunks = chunk_text(pages)
    print(f"    Created {len(chunks)} chunks")

    # Step 3: Extract HTS codes
    print(f"  Step 3: Extracting HTS codes ({'LLM' if use_llm and model else 'regex'})...")
    all_codes = []

    for i, chunk in enumerate(chunks):
        if use_llm and model:
            codes = extract_hts_with_llm(chunk, list_name, config["chapter_99_code"], model)
            # Rate limiting
            time.sleep(API_DELAY_SECONDS)
        else:
            codes = extract_hts_with_regex(chunk)

        all_codes.extend(codes)

        # Progress update every 10 chunks
        if (i + 1) % 10 == 0:
            print(f"    Processed {i + 1}/{len(chunks)} chunks, found {len(all_codes)} codes so far")

    print(f"    Total raw codes found: {len(all_codes)}")

    # Step 4: Validate and deduplicate
    print("  Step 4: Validating and deduplicating...")
    seen = set()
    valid_codes = []
    invalid_count = 0

    for code_entry in all_codes:
        hts = normalize_hts(code_entry.get("hts_code", ""))

        # Validate
        if not validate_hts(hts):
            invalid_count += 1
            continue

        # Deduplicate
        if hts in seen:
            continue
        seen.add(hts)

        # Build output record
        valid_codes.append({
            "hts_code": hts,
            "list_name": list_name,
            "chapter_99_code": config["chapter_99_code"],
            "duty_rate": config["duty_rate"],
            "source_doc": config["source_doc"],
            "source_page": code_entry.get("page_start", ""),
            "description": code_entry.get("description", "")
        })

    print(f"    Validated: {len(valid_codes)} unique HTS codes")
    print(f"    Skipped: {invalid_count} invalid, {len(all_codes) - len(valid_codes) - invalid_count} duplicates")

    return valid_codes


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract Section 301 HTS codes from Federal Register PDFs"
    )
    parser.add_argument(
        "--list",
        action="append",
        dest="lists",
        choices=list(LIST_CONFIGS.keys()),
        help="Specific list(s) to process. Can be used multiple times. Default: all lists."
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use regex extraction instead of LLM (faster but less accurate)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV path. Default: data/section_301_hts_codes.csv"
    )

    args = parser.parse_args()

    # Determine which lists to process
    lists_to_process = args.lists if args.lists else list(LIST_CONFIGS.keys())

    # Configure Gemini if using LLM
    model = None
    use_llm = not args.no_llm

    if use_llm:
        if not GENAI_AVAILABLE:
            print("Warning: google-generativeai not available. Falling back to regex extraction.")
            use_llm = False
        else:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                print("Warning: GEMINI_API_KEY not set. Falling back to regex extraction.")
                use_llm = False
            else:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash')
                print("Using Gemini LLM for extraction")

    if not use_llm:
        print("Using regex fallback for extraction")

    # Process each list
    all_records = []
    for list_name in lists_to_process:
        if list_name not in LIST_CONFIGS:
            print(f"Warning: Unknown list '{list_name}', skipping")
            continue

        config = LIST_CONFIGS[list_name]
        records = process_list_pdf(list_name, config, model=model, use_llm=use_llm)
        all_records.extend(records)

    # Write CSV output
    output_path = Path(args.output) if args.output else OUTPUT_DIR / "section_301_hts_codes.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Writing {len(all_records)} records to {output_path}")
    print(f"{'='*60}")

    fieldnames = [
        "hts_code", "list_name", "chapter_99_code", "duty_rate",
        "source_doc", "source_page", "description"
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_records)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    by_list = Counter(r["list_name"] for r in all_records)
    for list_name in sorted(by_list.keys()):
        count = by_list[list_name]
        config = LIST_CONFIGS.get(list_name, {})
        print(f"  {list_name}: {count} HTS codes (Chapter 99: {config.get('chapter_99_code', 'N/A')})")
    print(f"\nTotal: {len(all_records)} unique HTS codes")
    print(f"Output: {output_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()
