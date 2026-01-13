#!/usr/bin/env python3
"""
Parse Federal Register 2024-21217 (Four-Year Review) XML document.

Extracts:
- HTS codes and their new Chapter 99 codes
- Rates and effective dates for the staged increases
- Maps to section_301_rates temporal table format

This is Phase 1 Quick Fix: Manually parse the XML to get accurate data.
"""

import re
import csv
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional


@dataclass
class TariffChange:
    """A tariff change from the Four-Year Review."""
    hts_code: str  # 8 or 10 digit (with dots)
    description: str
    product_group: str  # e.g., "Facemasks", "Electric Vehicles"
    chapter_99_code: str  # e.g., "9903.91.07"
    rate: float  # as decimal (0.50 = 50%)
    effective_date: date
    source_doc: str = "2024-21217"


def parse_annex_a_table(xml_path: Path) -> List[TariffChange]:
    """
    Parse Annex A table from the Federal Register XML.

    Returns list of TariffChange records.
    """
    with open(xml_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse XML
    root = ET.fromstring(content)

    changes = []
    current_product_group = None

    # Find the first GPOTABLE (Annex A)
    for table in root.iter("GPOTABLE"):
        for row in table.findall(".//ROW"):
            entries = row.findall("ENT")

            if not entries:
                continue

            # Check if this is a product group header
            first_entry = entries[0]
            e_tag = first_entry.find("E")
            if e_tag is not None and e_tag.get("T") == "02":
                current_product_group = e_tag.text.strip() if e_tag.text else None
                continue

            # Skip if no product group set
            if not current_product_group:
                continue

            # Parse data row
            if len(entries) >= 4:
                hts_code = get_text(entries[0])
                description = get_text(entries[1])
                rate_text = get_text(entries[2])
                timing_text = get_text(entries[3])

                # Skip header rows or empty
                if not hts_code or not rate_text.replace(" ", "").isdigit():
                    # Handle multi-line rates (e.g., "25\n50" for staged increases)
                    rates = parse_rates(entries[2])
                    timings = parse_timings(entries[3])

                    if rates and timings and hts_code:
                        for rate, timing in zip(rates, timings):
                            changes.append(TariffChange(
                                hts_code=hts_code,
                                description=description,
                                product_group=current_product_group,
                                chapter_99_code="",  # Will be filled later
                                rate=rate / 100.0,  # Convert to decimal
                                effective_date=timing_to_date(timing),
                            ))
                else:
                    # Single rate
                    try:
                        rate = float(rate_text)
                        timing = int(timing_text) if timing_text.isdigit() else 2024
                        changes.append(TariffChange(
                            hts_code=hts_code,
                            description=description,
                            product_group=current_product_group,
                            chapter_99_code="",
                            rate=rate / 100.0,
                            effective_date=timing_to_date(timing),
                        ))
                    except ValueError:
                        pass

        # Only process first table (Annex A)
        break

    return changes


def get_text(elem) -> str:
    """Extract all text from an element including nested elements."""
    if elem is None:
        return ""
    text = elem.text or ""
    for child in elem:
        text += " " + (child.text or "") + " " + (child.tail or "")
    return text.strip()


def parse_rates(elem) -> List[float]:
    """Parse rates that may have multiple values (staged increases)."""
    rates = []
    text = elem.text or ""

    # Get main text
    if text.strip():
        try:
            rates.append(float(text.strip()))
        except ValueError:
            pass

    # Get LI elements (sub-items for staged rates)
    for li in elem.findall("LI"):
        if li.text:
            try:
                rates.append(float(li.text.strip()))
            except ValueError:
                pass

    return rates


def parse_timings(elem) -> List[int]:
    """Parse timing years that may have multiple values."""
    timings = []
    text = elem.text or ""

    if text.strip():
        try:
            timings.append(int(text.strip()))
        except ValueError:
            pass

    for li in elem.findall("LI"):
        if li.text:
            try:
                timings.append(int(li.text.strip()))
            except ValueError:
                pass

    return timings


def timing_to_date(year: int) -> date:
    """Convert year to effective date."""
    if year == 2024:
        return date(2024, 9, 27)  # Sept 27, 2024 effective date
    else:
        return date(year, 1, 1)  # Jan 1 for subsequent years


def assign_chapter_99_codes(changes: List[TariffChange]) -> List[TariffChange]:
    """
    Assign Chapter 99 codes based on document structure.

    From the FR notice:
    - 9903.91.01: Facemasks (2024) @ 25%
    - 9903.91.02: Semiconductors @ 50% (Sept 2024)
    - 9903.91.03: Various critical minerals, S2S cranes, etc @ 25% (Sept 2024)
    - 9903.91.04: Disposable facemasks @ 25% (Jan 2025)
    - 9903.91.05: Semiconductors @ 50% (Jan 2025)
    - 9903.91.06: Various @ 25% (Jan 2026) - Li-ion batteries, graphite, magnets
    - 9903.91.07: Facemasks @ 50% (Jan 2026)
    - 9903.91.08: Medical gloves @ 100% (Jan 2026)
    """
    # Mapping based on product group, year, and rate
    code_map = {
        # (product_group_pattern, year, rate) -> chapter_99_code
        ("Facemask", 2024, 0.25): "9903.91.01",
        ("Facemask", 2025, 0.25): "9903.91.04",  # Disposable only
        ("Facemask", 2026, 0.50): "9903.91.07",
        ("Semiconductor", 2024, 0.50): "9903.91.02",
        ("Semiconductor", 2025, 0.50): "9903.91.05",
        ("Electric Vehicle", 2024, 1.00): "9903.91.02",
        ("Battery", 2024, 0.25): "9903.91.03",
        ("Lithium-ion Electrical Vehicle", 2024, 0.25): "9903.91.03",
        ("Lithium-ion Non-electrical Vehicle", 2026, 0.25): "9903.91.06",
        ("Medical Glove", 2025, 0.50): "9903.91.08",  # Actually starts at 50% in 2025
        ("Medical Glove", 2026, 1.00): "9903.91.08",
        ("Natural Graphite", 2026, 0.25): "9903.91.06",
        ("Critical Mineral", 2024, 0.25): "9903.91.03",
        ("Other Critical Mineral", 2024, 0.25): "9903.91.03",
        ("Permanent Magnet", 2026, 0.25): "9903.91.06",
        ("Ship-to-shore Crane", 2024, 0.25): "9903.91.03",
        ("Solar Cell", 2024, 0.50): "9903.91.02",
        ("Steel", 2024, 0.25): "9903.91.03",
        ("Aluminum", 2024, 0.25): "9903.91.03",
        ("Syringe", 2024, 0.50): "9903.91.03",
        ("Needle", 2024, 0.50): "9903.91.03",
    }

    for change in changes:
        year = change.effective_date.year
        pg = change.product_group
        rate = change.rate

        # Find matching code
        for (pattern, y, r), code in code_map.items():
            if pattern.lower() in pg.lower() and y == year and abs(r - rate) < 0.01:
                change.chapter_99_code = code
                break

        # Default assignments if not matched
        if not change.chapter_99_code:
            if year == 2024:
                if rate >= 0.50:
                    change.chapter_99_code = "9903.91.02"
                else:
                    change.chapter_99_code = "9903.91.03"
            elif year == 2025:
                if rate >= 0.50:
                    change.chapter_99_code = "9903.91.05"
                else:
                    change.chapter_99_code = "9903.91.04"
            elif year == 2026:
                if rate >= 0.50:
                    change.chapter_99_code = "9903.91.07"
                else:
                    change.chapter_99_code = "9903.91.06"

    return changes


def export_to_csv(changes: List[TariffChange], output_path: Path):
    """Export changes to CSV for import."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'hts_code', 'hts_8digit', 'description', 'product_group',
            'chapter_99_code', 'rate', 'effective_date', 'source_doc'
        ])

        for c in changes:
            # Convert HTS code to 8-digit (remove dots)
            hts_8 = c.hts_code.replace(".", "")[:8]

            writer.writerow([
                c.hts_code,
                hts_8,
                c.description[:200],  # Truncate long descriptions
                c.product_group,
                c.chapter_99_code,
                f"{c.rate:.4f}",
                c.effective_date.isoformat(),
                c.source_doc,
            ])


def main():
    # Paths
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "data"
    xml_path = data_dir / "fr_notices" / "2024-21217.xml"
    output_path = data_dir / "section_301_2024_review.csv"

    if not xml_path.exists():
        print(f"Error: XML file not found at {xml_path}")
        return

    print(f"Parsing {xml_path}...")

    # Parse
    changes = parse_annex_a_table(xml_path)
    print(f"Found {len(changes)} raw changes from Annex A table")

    # Assign Chapter 99 codes
    changes = assign_chapter_99_codes(changes)

    # Export
    export_to_csv(changes, output_path)
    print(f"Exported to {output_path}")

    # Summary by product group
    print("\nSummary by product group:")
    groups = {}
    for c in changes:
        key = (c.product_group, c.effective_date.year)
        if key not in groups:
            groups[key] = []
        groups[key].append(c)

    for (pg, year), items in sorted(groups.items()):
        rates = set(c.rate for c in items)
        codes = set(c.chapter_99_code for c in items)
        print(f"  {pg} ({year}): {len(items)} HTS codes, rates={[f'{r*100:.0f}%' for r in rates]}, ch99={codes}")

    # Check facemasks specifically
    print("\nFacemask HTS codes (6307.90.98xx):")
    for c in changes:
        if "6307.90.98" in c.hts_code:
            print(f"  {c.hts_code}: {c.rate*100:.0f}% effective {c.effective_date} -> {c.chapter_99_code}")


if __name__ == "__main__":
    main()
