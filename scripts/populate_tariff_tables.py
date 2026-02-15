"""
Script to initialize and populate tariff tables with REAL 2025 tariff rates.

This script:
1. Creates the tariff tables in the database
2. Populates them with REAL rates from government sources (as of Dec 2025)
3. Includes the USB-C cable example (HTS 8544.42.9090)

Usage:
    cd lanes
    pipenv run python scripts/populate_tariff_tables.py

To reset tables (drop all data and reload from CSV):
    pipenv run python scripts/populate_tariff_tables.py --reset

To seed only if empty (preserves runtime data - used in Railway deploys):
    pipenv run python scripts/populate_tariff_tables.py --seed-if-empty

v17.0 Update (Jan 2026) - DB AS SOURCE OF TRUTH:
- Added --seed-if-empty flag: Only loads CSV if temporal tables are empty
- This preserves pipeline-discovered rates, evidence packets, and audit history
- Railway deploys now use --seed-if-empty instead of --reset
- Critical fix: Section301Rate table no longer deleted on < 10000 rows

TARIFF RATES (January 2026 - Updated per 90 FR 10524):
- Base Duty (HTS 8544.42.90.90): 2.6%
- Section 301 (List 3): 25%
- Section 232 Steel: 50% (default), 25% (UK exception)
- Section 232 Aluminum: 50% (default), 25% (UK exception) - UPDATED June 4, 2025
- Section 232 Copper: 50% (all countries)
- IEEPA Fentanyl: 10% (reduced Nov 2025 from 20%)
- IEEPA Reciprocal: 10% (default), formula for EU (15% - MFN)

HTS SCOPE (per CSMS #65936615, #65936570, #65794272, Federal Register 90 FR 40326):
- 8544.42.2000: Copper ONLY (Note 36)
- 8544.42.9090: Copper + Aluminum (Notes 36 + 19k) - NO steel
- 9403.99.9045: Steel + Aluminum (Notes 16n + 19k)
- 8473.30.5100: Aluminum only (Note 19k)
- 8536.90.8585: Aluminum only (Note 19k)
- 8539.50.0000: OUT OF SCOPE (removed)

Phase 6 Update (Dec 2025):
- Content-value-based duties: 232 duty calculated on material $ value, not percentage
- Line splitting: 2 filing lines per 232 material (non-material + material content)
- Fallback rule: If content value unknown, charge 232 on full product value

v4.0 Update (Dec 2025):
- Entry slices: Products with 232 metals split into multiple ACE entries
- Annex II exclusions: HTS codes exempt from IEEPA Reciprocal (pharmaceuticals, chemicals)
- IEEPA Reciprocal variants: taxable (9903.01.25), annex_ii_exempt (9903.01.32),
  metal_exempt (9903.01.33), us_content_exempt (9903.01.34)
- Program codes now include variant and slice_type for precise lookup

v5.0 Update (Dec 2025):
- Country-specific rates: EU, UK get different rates than default
- Formula support: EU 15% ceiling = max(0, 15% - MFN_base_rate)
- UK 232 exception: Steel/Aluminum stay at 25% (all others 50%)
- MFN base rates table for formula calculations
- Source document audit trail with change detection
- Country groups: EU, UK, CN with member mappings

v7.0 Update (Jan 2026) - Phoebe-Aligned ACE Filing:
- Added disclaim_behavior to TariffProgram: 'required', 'omit', 'none'
  - Copper: 'required' - must file disclaim code in other slices when applicable
  - Steel/Aluminum: 'omit' - omit entirely when not claimed (no disclaim line)
- Added Phoebe example HTS codes with correct claim_codes:
  - 9403.99.9045 (furniture parts) - steel uses derivative code 9903.81.91
  - 8536.90.8585 (electrical switches) - List 1 with 9903.88.01
  - 8473.30.5100 (computer parts) - Annex II exempt with 9903.88.69

Sources:
- USTR Section 301: https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions
- CBP Section 232 FAQ: https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs
- CBP IEEPA FAQ: https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ
- CBP CSMS #65794272 (July 31, 2025): Section 232 Copper Content-Value Rules
- CBP CSMS #65829726 (Aug 4, 2025): EU 15% Ceiling Rule
- White House Fact Sheet (June 4, 2025): 232 Steel/Aluminum increase to 50%
- Thompson Hine (June 2025): UK exception stays at 25%
- USITC HTS: https://hts.usitc.gov/
"""

import os
import sys
import argparse
from datetime import date

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

# Now import after path is set
from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import (
    TariffProgram,
    Section301Inclusion,
    Section301Exclusion,
    Section232Material,
    ProgramCode,
    DutyRule,
    ProductHistory,
    IeepaAnnexIIExclusion,
    # v5.0: Country-specific rates and audit trail
    SourceDocument,
    CountryGroup,
    CountryGroupMember,
    ProgramRate,
    HtsBaseRate,
    # v13.0: Temporal rate tables
    Section232Rate,
    IeepaRate,
    Section301Rate,
)

# =============================================================================
# v19.0: CSV-driven configuration loaders
# =============================================================================
import csv
from pathlib import Path
from datetime import datetime


def _parse_date(date_str):
    """Parse date string from CSV (YYYY-MM-DD format)."""
    if not date_str or date_str.strip() == '':
        return None
    return datetime.strptime(date_str.strip(), '%Y-%m-%d').date()


def _parse_float(val):
    """Parse float from CSV, return None if empty."""
    if not val or val.strip() == '':
        return None
    return float(val)


def _parse_int(val):
    """Parse int from CSV, return None if empty."""
    if not val or val.strip() == '':
        return None
    return int(val)


def _empty_to_none(val):
    """Convert empty string to None."""
    if not val or val.strip() == '':
        return None
    return val.strip()


def load_tariff_programs_from_csv():
    """Load program definitions from data/tariff_programs.csv.

    v19.0: Replaces hardcoded programs list.
    """
    csv_path = Path(__file__).parent.parent / "data" / "tariff_programs.csv"
    programs = []

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Using empty programs list.")
        return programs

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            programs.append({
                'program_id': row['program_id'],
                'program_name': row['program_name'],
                'country': row['country'],
                'check_type': row['check_type'],
                'condition_handler': _empty_to_none(row['condition_handler']),
                'condition_param': _empty_to_none(row['condition_param']),
                'inclusion_table': _empty_to_none(row['inclusion_table']),
                'exclusion_table': _empty_to_none(row['exclusion_table']),
                'filing_sequence': _parse_int(row['filing_sequence']),
                'calculation_sequence': _parse_int(row['calculation_sequence']),
                'source_document': _empty_to_none(row['source_document']),
                'effective_date': _parse_date(row['effective_date']),
                'expiration_date': _parse_date(row['expiration_date']),
                'disclaim_behavior': _empty_to_none(row.get('disclaim_behavior', '')),
            })

    return programs


def load_program_codes_from_csv():
    """Load program codes from data/tariff_program_codes.csv.

    v19.0: Replaces hardcoded codes list.
    """
    csv_path = Path(__file__).parent.parent / "data" / "tariff_program_codes.csv"
    codes = []

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Using empty codes list.")
        return codes

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            codes.append({
                'program_id': row['program_id'],
                'action': row['action'],
                'variant': _empty_to_none(row['variant']),
                'slice_type': row['slice_type'],
                'chapter_99_code': row['chapter_99_code'],
                'duty_rate': _parse_float(row['duty_rate']),
                'applies_to': row['applies_to'],
                'source_doc': _empty_to_none(row['source_doc']),
            })

    return codes


def load_duty_rules_from_csv():
    """Load duty rules from data/tariff_duty_rules.csv.

    v19.0: Replaces hardcoded rules list.
    """
    csv_path = Path(__file__).parent.parent / "data" / "tariff_duty_rules.csv"
    rules = []

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Using empty rules list.")
        return rules

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rules.append({
                'program_id': row['program_id'],
                'calculation_type': row['calculation_type'],
                'base_on': row['base_on'],
                'compounds_with': _empty_to_none(row['compounds_with']),
                'source_doc': _empty_to_none(row['source_doc']),
                'content_key': _empty_to_none(row['content_key']),
                'fallback_base_on': _empty_to_none(row['fallback_base_on']),
                'base_effect': _empty_to_none(row['base_effect']),
            })

    return rules


def load_program_rates_from_csv():
    """Load program rates from data/tariff_program_rates.csv.

    v19.0: Replaces hardcoded rates list.
    """
    csv_path = Path(__file__).parent.parent / "data" / "tariff_program_rates.csv"
    rates = []

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Using empty rates list.")
        return rates

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rates.append({
                'program_id': row['program_id'],
                'group_id': row['group_id'],
                'rate': _parse_float(row['rate']),
                'rate_type': _empty_to_none(row['rate_type']),
                'rate_formula': _empty_to_none(row['rate_formula']),
                'effective_date': _parse_date(row['effective_date']),
                'expiration_date': _parse_date(row['expiration_date']),
            })

    return rates


def load_country_groups_from_csv():
    """Load country groups from data/country_groups.csv.

    v19.0: Replaces hardcoded groups list.
    """
    csv_path = Path(__file__).parent.parent / "data" / "country_groups.csv"
    groups = []

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Using empty groups list.")
        return groups

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            groups.append({
                'group_id': row['group_id'],
                'description': row['description'],
                'effective_date': _parse_date(row['effective_date']),
                'expiration_date': _parse_date(row['expiration_date']),
            })

    return groups


def load_country_group_members_from_csv():
    """Load country group members from data/country_group_members.csv.

    v19.0: Replaces hardcoded members list.
    """
    csv_path = Path(__file__).parent.parent / "data" / "country_group_members.csv"
    members = []

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Using empty members list.")
        return members

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            members.append({
                'country_code': row['country_code'],
                'group_id': row['group_id'],
                'effective_date': _parse_date(row['effective_date']),
                'expiration_date': _parse_date(row.get('expiration_date', '')),
            })

    return members


def init_tables(app, reset=False):
    """Create tariff tables in database.

    v5.1: Use db.drop_all() instead of individual table drops.
    This properly handles foreign key dependencies and works with
    both SQLite (local) and PostgreSQL (Railway).
    """
    with app.app_context():
        if reset:
            print("Dropping ALL existing tables (handles FK dependencies)...")
            # db.drop_all() drops tables in correct dependency order
            # and works with PostgreSQL foreign key constraints
            db.drop_all()
            print("All tables dropped successfully!")

        print("Creating tariff tables...")
        db.create_all()
        print("Tables created successfully!")


def populate_tariff_programs(app):
    """Populate the tariff_programs master table.

    v19.0 Update: Now reads from data/tariff_programs.csv (CSV-driven).

    v4.0 Update:
    - filing_sequence: Order for ACE entry display (per CBP CSMS #64018403)
    - calculation_sequence: Order for duty math (232 before IEEPA Reciprocal)

    Filing Order (per CSMS #64018403):
    1. Section 301
    2. IEEPA Fentanyl
    3. IEEPA Reciprocal
    4-8. Section 232 (Copper, Steel, Aluminum, Auto, Semiconductor)

    Calculation Order:
    - 232 programs must calculate FIRST to determine remaining_value
    - IEEPA Reciprocal calculates on remaining_value (product - 232 content)
    """
    # v19.0: Load from CSV instead of hardcoded list
    programs = load_tariff_programs_from_csv()

    with app.app_context():
        print("Populating tariff_programs...")

        # Clean up stale country-specific rows for programs that now use ALL.
        # e.g. ieepa_reciprocal was previously 9 country-specific rows,
        # now it's a single ALL row. Delete the old country rows so they
        # don't coexist with the new ALL row.
        csv_program_keys = {
            (p["program_id"], p["country"]) for p in programs
        }
        all_programs = {p["program_id"] for p in programs if p["country"] == "ALL"}
        if all_programs:
            stale = TariffProgram.query.filter(
                TariffProgram.program_id.in_(all_programs),
                TariffProgram.country != "ALL"
            ).all()
            if stale:
                print(f"  Removing {len(stale)} stale country-specific row(s) "
                      f"for programs that now use ALL:")
                for s in stale:
                    print(f"    {s.program_id} / {s.country}")
                    db.session.delete(s)

        for prog_data in programs:
            # Query by program_id AND country since same program can apply to multiple countries
            existing = TariffProgram.query.filter_by(
                program_id=prog_data["program_id"],
                country=prog_data["country"]
            ).first()
            if existing:
                print(f"  Updating {prog_data['program_id']} ({prog_data['country']})...")
                for key, value in prog_data.items():
                    setattr(existing, key, value)
            else:
                print(f"  Creating {prog_data['program_id']} ({prog_data['country']})...")
                program = TariffProgram(**prog_data)
                db.session.add(program)
        db.session.commit()
        print(f"  Added {len(programs)} tariff programs")


def populate_section_301_from_csv(app):
    """DEPRECATED: Legacy function to import Section 301 HTS codes from old CSV.

    v17.0: This function is NO LONGER CALLED.
    - The temporal table (Section301Rate) is now the single source of truth
    - See populate_section_301_temporal() which reads from section_301_rates_temporal.csv
    - This function remains for backwards compatibility/re-bootstrapping only

    v9.0 Update (Jan 2026):
    - Imports 10,422 HTS codes from data/section_301_hts_codes.csv
    - CSV already contains: hts_8digit, list_name, chapter_99_code, rate, source_pdf
    - Replaces hardcoded sample data with complete USTR list
    """
    import csv
    from pathlib import Path

    csv_path = Path(__file__).parent.parent / "data" / "section_301_hts_codes.csv"

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Skipping CSV import.")
        return 0

    with app.app_context():
        print("Importing Section 301 HTS codes from CSV...")

        imported = 0
        updated = 0
        list_counts = {}

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Use hts_8digit from CSV directly
                hts_8digit = row['hts_8digit']
                list_name = row['list_name']

                # Track counts by list
                list_counts[list_name] = list_counts.get(list_name, 0) + 1

                inc_data = {
                    "hts_8digit": hts_8digit,
                    "list_name": list_name,
                    "chapter_99_code": row['chapter_99_code'],
                    "duty_rate": float(row['rate']),
                    "source_doc": row.get('source_pdf', 'USTR_301_Notice.pdf'),
                }

                existing = Section301Inclusion.query.filter_by(
                    hts_8digit=hts_8digit,
                    list_name=list_name
                ).first()

                if existing:
                    # Update if chapter_99_code or rate changed
                    if (existing.chapter_99_code != inc_data["chapter_99_code"] or
                        existing.duty_rate != inc_data["duty_rate"]):
                        for key, val in inc_data.items():
                            setattr(existing, key, val)
                        updated += 1
                else:
                    inclusion = Section301Inclusion(**inc_data)
                    db.session.add(inclusion)
                    imported += 1

        db.session.commit()

        print(f"  Imported: {imported}, Updated: {updated}")
        for list_name, count in sorted(list_counts.items()):
            print(f"    {list_name}: {count} codes")

        return imported + updated


def populate_section_301_inclusions(app):
    """Populate Section 301 inclusion list (sample HTS codes).

    Note: This function adds manual overrides/test cases.
    For the full 10,422 HTS code list, see populate_section_301_from_csv().
    """
    # Sample inclusions including our USB-C cable example
    inclusions = [
        # USB-C cables and related electrical products (List 3)
        {"hts_8digit": "85444290", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "301_List_3.pdf"},
        # More HTS codes for testing
        {"hts_8digit": "85395000", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "301_List_3.pdf"},
        {"hts_8digit": "84713000", "list_name": "list_2", "chapter_99_code": "9903.88.02", "duty_rate": 0.25, "source_doc": "301_List_2.pdf"},
        {"hts_8digit": "84714100", "list_name": "list_1", "chapter_99_code": "9903.88.01", "duty_rate": 0.25, "source_doc": "301_List_1.pdf"},
        {"hts_8digit": "90138000", "list_name": "list_4a", "chapter_99_code": "9903.88.15", "duty_rate": 0.075, "source_doc": "301_List_4A.pdf"},

        # v7.0: Phoebe example HTS codes
        # TC-v7.0-001, TC-v7.0-005: Furniture parts (steel + aluminum) - List 3
        {"hts_8digit": "94039990", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "301_List_3.pdf"},
        # TC-v7.0-002, TC-v7.0-004: Insulated conductors (copper + aluminum) - already covered by 85444290
        # TC-v7.0-003: Electrical switches (no 232 metals) - List 1
        {"hts_8digit": "85369085", "list_name": "list_1", "chapter_99_code": "9903.88.01", "duty_rate": 0.25, "source_doc": "301_List_1.pdf"},
        # TC-v7.0-006: Computer parts (Annex II example) - different list with 9903.88.69
        {"hts_8digit": "84733051", "list_name": "list_other", "chapter_99_code": "9903.88.69", "duty_rate": 0.25, "source_doc": "301_List_Other.pdf"},
        # Additional 10-digit variant for 8544.42.2000 (copper full claim example)
        {"hts_8digit": "85444220", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "301_List_3.pdf"},

        # =================================================================
        # v8.0: Test case HTS codes (January 2026)
        # Sources: 83 FR 28710 (List 1), 83 FR 47974 (List 3), 85 FR 3741 (List 4A), 2024 Four-Year Review
        # =================================================================

        # Case 1: 8302.41.6015 - Base metal fittings for furniture (List 3)
        {"hts_8digit": "83024160", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "83 FR 47974"},
        {"hts_8digit": "83024100", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "83 FR 47974"},

        # Case 2: 7615.10.7130 - Aluminum household bakeware (List 4A @ 7.5%)
        {"hts_8digit": "76151071", "list_name": "list_4a", "chapter_99_code": "9903.88.15", "duty_rate": 0.075, "source_doc": "85 FR 3741"},
        {"hts_8digit": "76151000", "list_name": "list_4a", "chapter_99_code": "9903.88.15", "duty_rate": 0.075, "source_doc": "85 FR 3741"},

        # Case 3: 2711.12.0020 - Propane gas (List 3)
        {"hts_8digit": "27111200", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "83 FR 47974"},

        # Case 4: 7317.00.5502 - Steel nails, wire (List 3)
        {"hts_8digit": "73170055", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "83 FR 47974"},
        {"hts_8digit": "73170000", "list_name": "list_3", "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "source_doc": "83 FR 47974"},

        # Case 5: 8504.90.9642 - Transformer parts (List 1)
        {"hts_8digit": "85049096", "list_name": "list_1", "chapter_99_code": "9903.88.01", "duty_rate": 0.25, "source_doc": "83 FR 28710"},
        {"hts_8digit": "85049000", "list_name": "list_1", "chapter_99_code": "9903.88.01", "duty_rate": 0.25, "source_doc": "83 FR 28710"},
        {"hts_8digit": "85040000", "list_name": "list_1", "chapter_99_code": "9903.88.01", "duty_rate": 0.25, "source_doc": "83 FR 28710"},

        # Case 6: 8507.60.0010 - EV Lithium-ion batteries (2024 Four-Year Review - special code)
        {"hts_8digit": "85076000", "list_name": "ev_batteries", "chapter_99_code": "9903.91.01", "duty_rate": 0.25, "source_doc": "2024 Four-Year Review"},
    ]

    with app.app_context():
        print("Populating section_301_inclusions (test case overrides)...")
        added = 0
        updated = 0
        for inc_data in inclusions:
            # Check if ANY entry exists for this HTS (regardless of list_name)
            existing = Section301Inclusion.query.filter_by(
                hts_8digit=inc_data["hts_8digit"]
            ).first()
            if existing:
                # UPDATE existing entry to use correct test case values
                existing.list_name = inc_data["list_name"]
                existing.chapter_99_code = inc_data["chapter_99_code"]
                existing.duty_rate = inc_data["duty_rate"]
                existing.source_doc = inc_data["source_doc"]
                updated += 1
            else:
                inclusion = Section301Inclusion(**inc_data)
                db.session.add(inclusion)
                added += 1
        db.session.commit()
        print(f"  Added {added}, updated {updated} Section 301 inclusions")


def populate_section_301_exclusions(app):
    """Populate Section 301 exclusions (sample exclusions)."""
    # Sample exclusions
    exclusions = [
        {
            "hts_8digit": "85395000",
            "description": "Light-emitting diode (LED) lamps specifically designed for use with medical diagnostic equipment",
            "exclusion_doc": "301_Exclusions_FRN.pdf",
            "original_expiry": date(2023, 12, 31),
            "extended_to": date(2025, 12, 31),
            "source_page": 15,
        },
        {
            "hts_8digit": "84713000",
            "description": "Portable digital automatic data processing machines for specialized scientific research applications",
            "exclusion_doc": "301_Exclusions_FRN.pdf",
            "original_expiry": date(2022, 12, 31),
            "extended_to": None,  # Expired
            "source_page": 22,
        },
    ]

    with app.app_context():
        print("Populating section_301_exclusions...")
        for exc_data in exclusions:
            existing = Section301Exclusion.query.filter_by(
                hts_8digit=exc_data["hts_8digit"],
            ).first()
            if not existing:
                exclusion = Section301Exclusion(**exc_data)
                db.session.add(exclusion)
                print(f"  Added exclusion for HTS {exc_data['hts_8digit']}")
        db.session.commit()
        print(f"  Added {len(exclusions)} Section 301 exclusions")


def populate_section_232_from_csv(app):
    """Import Section 232 HTS codes from CBP official lists CSV.

    v8.0 Update (Jan 2026):
    - Imports ~931 HTS codes from data/section_232_hts_codes.csv
    - CSV generated by scripts/parse_cbp_232_lists.py from official CBP DOCX files
    - Sources: CSMS #65794272 (copper), CSMS #65936570 (steel), CSMS #65936615 (aluminum)

    v11.0 Update (Jan 2026):
    - Now reads article_type from CSV (data-driven, not hardcoded)
    - article_type values: 'primary', 'derivative', 'content' per U.S. Note 16
    - Claim codes in CSV are correctly mapped to article_type:
      - primary steel → 9903.80.01
      - derivative steel → 9903.81.89
      - content steel → 9903.81.91

    This replaces the hardcoded sample data with the complete CBP list.
    """
    import csv
    from pathlib import Path

    csv_path = Path(__file__).parent.parent / "data" / "section_232_hts_codes.csv"

    if not csv_path.exists():
        print(f"  WARNING: {csv_path} not found. Run scripts/parse_cbp_232_lists.py first.")
        return 0

    with app.app_context():
        print("Importing Section 232 HTS codes from CSV...")

        imported = 0
        updated = 0
        type_counts = {'primary': 0, 'derivative': 0, 'content': 0}

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip comment lines and empty rows
                if not row.get('hts_code') or row['hts_code'].startswith('#'):
                    continue
                if not row.get('duty_rate'):
                    continue

                # Convert HTS code to 8-digit format (remove dots, pad if needed)
                hts_code = row['hts_code'].replace('.', '')
                # Use first 8 digits for lookup (standard 232 matching)
                hts_8digit = hts_code[:8]

                # Map material to source doc
                source_docs = {
                    'copper': 'CSMS_65794272_Copper_Aug2025.pdf',
                    'steel': 'CSMS_65936570_Steel_Aug2025.pdf',
                    'aluminum': 'CSMS_65936615_Aluminum_Aug2025.pdf',
                    'auto': 'Proclamation_10908_90FR14705_AutoParts.pdf',
                    'semiconductor': 'CSMS_67400472_Semiconductor_Jan2026.pdf',
                }

                # v11.0: Read article_type from CSV (data-driven)
                article_type = row.get('article_type', 'content')
                type_counts[article_type] = type_counts.get(article_type, 0) + 1

                mat_data = {
                    "hts_8digit": hts_8digit,
                    "material": row['material'],
                    "article_type": article_type,  # v11.0: From CSV
                    "claim_code": row['chapter_99_claim'],
                    "disclaim_code": row['chapter_99_disclaim'],
                    "duty_rate": float(row['duty_rate']),
                    "threshold_percent": None,
                    "source_doc": source_docs.get(row['material'], 'CBP_Section232_Official.pdf'),
                    "content_basis": "value",
                    "quantity_unit": "kg",
                    "split_policy": "if_any_content",
                    "split_threshold_pct": None,
                }

                existing = Section232Material.query.filter_by(
                    hts_8digit=hts_8digit,
                    material=row['material']
                ).first()

                if existing:
                    for key, value in mat_data.items():
                        setattr(existing, key, value)
                    updated += 1
                else:
                    material = Section232Material(**mat_data)
                    db.session.add(material)
                    imported += 1

        db.session.commit()
        print(f"  Imported {imported} new, updated {updated} existing Section 232 entries")
        print(f"  Article types: primary={type_counts.get('primary', 0)}, derivative={type_counts.get('derivative', 0)}, content={type_counts.get('content', 0)}")
        return imported + updated


def populate_section_232_materials(app):
    """Populate Section 232 materials (copper, steel, aluminum) with REAL 2025 rates.

    Phase 6 Update (Dec 2025):
    - Copper rate is now 50% (was 25%)
    - Added content-value-based duty columns:
      - content_basis='value' means duty is on material $ value
      - split_policy='if_any_content' means generate 2 filing lines
      - split_threshold_pct=NULL (not used for 'if_any_content')
    - threshold_percent=NULL for current 232 rules (percentage threshold not used)

    Source: CBP CSMS #65794272 (July 31, 2025), Proclamations 10895/10896

    v8.0: This function now calls populate_section_232_from_csv() first to import
    the full CBP list, then adds any additional sample entries needed for tests.
    """
    # v8.0: First import the full CBP list from CSV
    populate_section_232_from_csv(app)

    # REAL 2025/2026 RATES (Updated per 90 FR 10524, June 4, 2025):
    # - Steel: 50% (default), 25% (UK exception)
    # - Aluminum: 50% (default), 25% (UK exception) - DOUBLED from 25% on June 4, 2025
    # - Copper: 50% (all countries)
    #
    # Content-Value-Based Duties:
    # - CBP now requires duty on material content VALUE, not percentage
    # - Line splitting: 2 lines per material (non-material + material content)
    # - split_policy='if_any_content' means split whenever content > 0 and < total
    # CORRECTED HTS SCOPE per Federal Register 90 FR 40326, CSMS #65794272, #65936615, #65936570
    # ALL rates updated to 50% per Presidential Proclamation 90 FR 10524 (June 4, 2025)

    # Additional sample entries for test cases (may overlap with CSV imports)
    materials = [
        # =================================================================
        # 8544.42.9090 - Insulated wire/cable (>80V): Copper + Aluminum (NO steel)
        # Authority: CSMS #65794272 (Note 36) + CSMS #65936615 (Note 19k)
        # =================================================================
        {
            "hts_8digit": "85444290",
            "material": "copper",
            "claim_code": "9903.78.01",
            "disclaim_code": "9903.78.02",
            "duty_rate": 0.50,  # 50% as of July 2025
            "threshold_percent": None,
            "source_doc": "CSMS_65794272_Copper_July2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },
        {
            "hts_8digit": "85444290",
            "material": "aluminum",
            "claim_code": "9903.85.08",
            "disclaim_code": "9903.85.09",
            "duty_rate": 0.50,  # UPDATED: 50% per 90 FR 10524 (June 4, 2025)
            "threshold_percent": None,
            "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },
        # NOTE: Steel REMOVED from 85444290 - not in scope per CSMS #65936570

        # =================================================================
        # 9403.99.9045 - Furniture parts: Steel + Aluminum
        # Authority: CSMS #65936570 (Note 16n) + CSMS #65936615 (Note 19k)
        # =================================================================
        {
            "hts_8digit": "94039990",
            "material": "steel",
            "claim_code": "9903.81.91",  # Derivative steel code per Phoebe
            "disclaim_code": "9903.80.02",
            "duty_rate": 0.50,
            "threshold_percent": None,
            "source_doc": "CSMS_65936570_Steel_Aug2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },
        {
            "hts_8digit": "94039990",
            "material": "aluminum",
            "claim_code": "9903.85.08",
            "disclaim_code": "9903.85.09",
            "duty_rate": 0.50,  # UPDATED: 50% per 90 FR 10524 (June 4, 2025)
            "threshold_percent": None,
            "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },

        # =================================================================
        # 8544.42.2000 - Insulated copper wire (≤80V): Copper ONLY
        # Authority: CSMS #65794272 (Note 36)
        # NOTE: Aluminum REMOVED - Phoebe example confirms copper only
        # =================================================================
        {
            "hts_8digit": "85444220",
            "material": "copper",
            "claim_code": "9903.78.01",
            "disclaim_code": "9903.78.02",
            "duty_rate": 0.50,
            "threshold_percent": None,
            "source_doc": "CSMS_65794272_Copper_July2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },

        # =================================================================
        # 8473.30.5100 - Computer parts: Aluminum ONLY
        # Authority: CSMS #65936615 (Note 19k)
        # Also Annex II exempt (IEEPA Reciprocal)
        # =================================================================
        {
            "hts_8digit": "84733051",
            "material": "aluminum",
            "claim_code": "9903.85.08",
            "disclaim_code": "9903.85.09",
            "duty_rate": 0.50,  # UPDATED: 50% per 90 FR 10524 (June 4, 2025)
            "threshold_percent": None,
            "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },

        # =================================================================
        # 8536.90.8585 - Electrical apparatus parts: Aluminum ONLY (NEW)
        # Authority: CSMS #65936615 (Note 19k)
        # Added per Phoebe disclaim example TC-v7.0-003
        # =================================================================
        {
            "hts_8digit": "85369085",
            "material": "aluminum",
            "claim_code": "9903.85.08",
            "disclaim_code": "9903.85.09",
            "duty_rate": 0.50,  # 50% per 90 FR 10524 (June 4, 2025)
            "threshold_percent": None,
            "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf",
            "content_basis": "value",
            "quantity_unit": "kg",
            "split_policy": "if_any_content",
            "split_threshold_pct": None,
        },

        # NOTE: 8539.50.0000 (LED lamps) REMOVED - out of Section 232 scope
        # per Federal Register 90 FR 40326 and CSMS derivative lists
    ]

    with app.app_context():
        print("Populating section_232_materials...")
        for mat_data in materials:
            existing = Section232Material.query.filter_by(
                hts_8digit=mat_data["hts_8digit"],
                material=mat_data["material"]
            ).first()
            if existing:
                # Update existing record with new Phase 6 columns
                print(f"  Updating {mat_data['material']} for HTS {mat_data['hts_8digit']}...")
                for key, value in mat_data.items():
                    setattr(existing, key, value)
            else:
                material = Section232Material(**mat_data)
                db.session.add(material)
                print(f"  Added {mat_data['material']} for HTS {mat_data['hts_8digit']}")
        db.session.commit()
        print(f"  Processed {len(materials)} Section 232 materials")


def populate_program_codes(app):
    """Populate program output codes with v4.0 variant and slice_type support.

    v19.0 Update: Now reads from data/tariff_program_codes.csv (CSV-driven).

    v4.0 Update (Dec 2025):
    - Added variant column for IEEPA Reciprocal outcomes
    - Added slice_type column for per-slice code lookup
    - Primary key is now: (program_id, action, variant, slice_type)

    IEEPA Reciprocal Variants:
    - taxable: 9903.01.25 (10%) - default, pay the tariff
    - annex_ii_exempt: 9903.01.32 (0%) - exempt per Annex II
    - metal_exempt: 9903.01.33 (0%) - exempt because 232 metal slice
    - us_content_exempt: 9903.01.34 (0%) - exempt >20% US content

    Section 232 Slice Types:
    - claim: on own metal slice (e.g., copper_slice for 232 Copper)
    - disclaim: on all other slices (non_metal, other metals)
    """
    # v19.0: Load from CSV instead of hardcoded list
    codes = load_program_codes_from_csv()

    with app.app_context():
        print("Populating program_codes (v4.0 with variant/slice_type)...")
        for code_data in codes:
            # v4.0: Query by all 4 key fields
            existing = ProgramCode.query.filter_by(
                program_id=code_data["program_id"],
                action=code_data["action"],
                variant=code_data["variant"],
                slice_type=code_data["slice_type"]
            ).first()
            if existing:
                # Update existing record
                for key, value in code_data.items():
                    setattr(existing, key, value)
                print(f"  Updated {code_data['program_id']} / {code_data['action']} / {code_data['variant']} / {code_data['slice_type']}")
            else:
                code = ProgramCode(**code_data)
                db.session.add(code)
                print(f"  Added {code_data['program_id']} / {code_data['action']} / {code_data['variant']} / {code_data['slice_type']} -> {code_data['chapter_99_code']}")
        db.session.commit()
        print(f"  Processed {len(codes)} program codes")


def populate_duty_rules(app):
    """Populate duty calculation rules.

    v19.0 Update: Now reads from data/tariff_duty_rules.csv (CSV-driven).

    Phase 6 Update (Dec 2025):
    - Section 232 programs now use base_on='content_value' (duty on material $ value)
    - Added content_key to identify which material (copper, steel, aluminum)
    - Added fallback_base_on='full_value' - if content value unknown, charge on full product value

    Phase 6.5 Update (Dec 2025): IEEPA Unstacking
    - Section 232 programs now have base_effect='subtract_from_remaining'
      This means 232 content values are deducted from remaining_value
    - IEEPA Reciprocal now uses base_on='remaining_value'
      This means IEEPA duty is calculated on product_value MINUS 232 content values
    - This implements CBP rule: "232 content is NOT subject to IEEPA Reciprocal"
    """
    # v19.0: Load from CSV instead of hardcoded list
    rules = load_duty_rules_from_csv()

    with app.app_context():
        print("Populating duty_rules...")
        for rule_data in rules:
            existing = DutyRule.query.filter_by(program_id=rule_data["program_id"]).first()
            if existing:
                # Update existing record with new Phase 6 columns
                print(f"  Updating rule for {rule_data['program_id']}...")
                for key, value in rule_data.items():
                    setattr(existing, key, value)
            else:
                rule = DutyRule(**rule_data)
                db.session.add(rule)
                print(f"  Added rule for {rule_data['program_id']}")
        db.session.commit()
        print(f"  Processed {len(rules)} duty rules")


def populate_annex_ii_exclusions(app, seed_if_empty=False):
    """Populate IEEPA Annex II exclusions from CSV.

    v18.0 Update (Jan 2026):
    - Loads from data/annex_ii_exemptions.csv (consolidated CSV)
    - Removed hardcoded list - CSV is single source of truth
    - Added seed_if_empty parameter for pipeline compatibility

    CSV columns: hts_prefix, description, exemption_code, category, source, effective_date

    Source: EO 14257 Annex II, EO 14346 additions
    """
    import csv
    from pathlib import Path
    from datetime import datetime

    csv_path = Path(__file__).parent.parent / "data" / "annex_ii_exemptions.csv"

    if not csv_path.exists():
        print(f"  ERROR: {csv_path} not found. Annex II exclusions cannot be imported.")
        return 0

    with app.app_context():
        existing_count = IeepaAnnexIIExclusion.query.count()

        if seed_if_empty and existing_count > 0:
            print(f"ieepa_annex_ii_exclusions has {existing_count} rows - PRESERVING (seed-if-empty mode)")
            return existing_count

        print(f"Importing Annex II exclusions from {csv_path.name}...")

        imported = 0
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                hts_code = row['hts_prefix'].replace('.', '')
                description = row['description']
                category = row['category']
                source_doc = row['source']

                effective_date_str = row.get('effective_date', '2025-04-05')
                try:
                    effective_date = datetime.strptime(effective_date_str, '%Y-%m-%d').date()
                except ValueError:
                    effective_date = date(2025, 4, 5)

                existing = IeepaAnnexIIExclusion.query.filter_by(hts_code=hts_code).first()
                if existing:
                    existing.description = description
                    existing.category = category
                    existing.source_doc = source_doc
                    existing.effective_date = effective_date
                else:
                    exclusion = IeepaAnnexIIExclusion(
                        hts_code=hts_code,
                        description=description,
                        category=category,
                        source_doc=source_doc,
                        effective_date=effective_date,
                        expiration_date=None
                    )
                    db.session.add(exclusion)
                imported += 1

        db.session.commit()
        print(f"  Imported {imported} Annex II exclusions from CSV")
        return imported


# =============================================================================
# v5.0: Country-Specific Rates and Data Freshness
# =============================================================================

def populate_source_documents(app):
    """Populate source documents for audit trail.

    v5.0 Update (Dec 2025):
    - Tracks every government document used to populate rates
    - Includes content_hash for change detection
    - Used as FK in other tables for full traceability
    """
    from datetime import datetime

    documents = [
        {
            "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ec7b5e",
            "title": "Reciprocal Tariff Updates - EU 15% Ceiling Rule",
            "doc_type": "CSMS",
            "doc_identifier": "CSMS #65829726",
            "fetched_at": datetime(2025, 8, 4, 12, 0, 0),
            "content_hash": None,
            "effective_date": date(2025, 8, 7),
            "summary": "EU countries receive 15% ceiling rule: Reciprocal = max(0, 15% - MFN base rate)",
        },
        {
            "url": "https://www.whitehouse.gov/fact-sheets/2025/06/fact-sheet-president-donald-j-trump-increases-section-232-tariffs-on-steel-and-aluminum/",
            "title": "Section 232 Steel/Aluminum Increase to 50%",
            "doc_type": "EO",
            "doc_identifier": "White House Fact Sheet June 4, 2025",
            "fetched_at": datetime(2025, 6, 4, 12, 0, 0),
            "content_hash": None,
            "effective_date": date(2025, 6, 4),
            "summary": "Section 232 Steel and Aluminum rates increased from 25% to 50% for all countries except UK",
        },
        {
            "url": "https://www.thompsonhinesmartrade.com/2025/06/section-232-aluminum-and-steel-tariffs-increased-to-50-except-for-uk-significant-changes-made-to-calculating-and-stacking-of-tariffs/",
            "title": "UK Exception - 232 Steel/Aluminum stays at 25%",
            "doc_type": "Analysis",
            "doc_identifier": "Thompson Hine June 2025",
            "fetched_at": datetime(2025, 6, 5, 12, 0, 0),
            "content_hash": None,
            "effective_date": date(2025, 6, 4),
            "summary": "UK exception: Section 232 Steel and Aluminum remain at 25% (not increased to 50%)",
        },
        {
            "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/abc1234",
            "title": "Section 232 Copper Content-Value Rules",
            "doc_type": "CSMS",
            "doc_identifier": "CSMS #65794272",
            "fetched_at": datetime(2025, 7, 31, 12, 0, 0),
            "content_hash": None,
            "effective_date": date(2025, 7, 31),
            "summary": "Copper content duty is 50%, calculated on material dollar value",
        },
        {
            "url": "https://hts.usitc.gov/",
            "title": "USITC HTS Base Rates 2025",
            "doc_type": "USITC",
            "doc_identifier": "HTS 2025 General Notes",
            "fetched_at": datetime(2025, 1, 1, 0, 0, 0),
            "content_hash": None,
            "effective_date": date(2025, 1, 1),
            "summary": "MFN Column 1 General rates for HTS codes",
        },
    ]

    with app.app_context():
        print("Populating source_documents (v5.0)...")
        for doc_data in documents:
            existing = SourceDocument.query.filter_by(
                doc_type=doc_data["doc_type"],
                doc_identifier=doc_data["doc_identifier"]
            ).first()
            if existing:
                for key, value in doc_data.items():
                    setattr(existing, key, value)
                print(f"  Updated {doc_data['doc_identifier']}")
            else:
                doc = SourceDocument(**doc_data)
                db.session.add(doc)
                print(f"  Added {doc_data['doc_identifier']}")
        db.session.commit()
        print(f"  Processed {len(documents)} source documents")


def populate_country_groups(app):
    """Populate country groups for rate lookups.

    v19.0 Update: Now reads from data/country_groups.csv (CSV-driven).

    v5.0 Update (Dec 2025):
    - EU: European Union countries (15% ceiling rule)
    - UK: United Kingdom (232 exception - stays at 25%)
    - CN: China (full tariffs)
    - USMCA: Mexico, Canada (FTA - not currently used for stacking)
    """
    # v19.0: Load from CSV instead of hardcoded list
    groups = load_country_groups_from_csv()

    with app.app_context():
        print("Populating country_groups (v19.0 CSV-driven)...")
        for group_data in groups:
            existing = CountryGroup.query.filter_by(group_id=group_data["group_id"]).first()
            if existing:
                for key, value in group_data.items():
                    setattr(existing, key, value)
                print(f"  Updated {group_data['group_id']}")
            else:
                group = CountryGroup(**group_data)
                db.session.add(group)
                print(f"  Added {group_data['group_id']}")
        db.session.commit()
        print(f"  Processed {len(groups)} country groups")


def populate_country_group_members(app):
    """Populate country to group mappings.

    v19.0 Update: Now reads from data/country_group_members.csv (CSV-driven).

    v5.0 Update (Dec 2025):
    - Maps country names (and ISO codes) to their groups
    - Supports multiple names per country (Germany, DE, DEU)
    - Membership is time-bound for events like Brexit
    """
    # v19.0: Load from CSV instead of hardcoded list
    members = load_country_group_members_from_csv()

    with app.app_context():
        print("Populating country_group_members (v19.0 CSV-driven)...")
        for member_data in members:
            existing = CountryGroupMember.query.filter_by(
                country_code=member_data["country_code"],
                group_id=member_data["group_id"]
            ).first()
            if existing:
                for key, value in member_data.items():
                    setattr(existing, key, value)
            else:
                member = CountryGroupMember(**member_data)
                db.session.add(member)
                print(f"  Added {member_data['country_code']} -> {member_data['group_id']}")
        db.session.commit()
        print(f"  Processed {len(members)} country group members")


def populate_program_rates(app):
    """Populate program-specific rates by country group.

    v19.0 Update: Now reads from data/tariff_program_rates.csv (CSV-driven).

    v5.0 Update (Dec 2025):
    - Rates vary by country group (EU, UK, default)
    - Formula support for EU 15% ceiling rule
    - UK exception for 232 Steel/Aluminum (stays at 25%)

    Key rates:
    - 232 Steel: 50% default, 25% UK exception
    - 232 Aluminum: 25% (all countries)
    - 232 Copper: 50% all countries
    - IEEPA Reciprocal: 10% default, formula '15pct_minus_mfn' for EU
    """
    # v19.0: Load from CSV instead of hardcoded list
    rates = load_program_rates_from_csv()

    with app.app_context():
        print("Populating program_rates (v19.0 CSV-driven)...")
        for rate_data in rates:
            existing = ProgramRate.query.filter_by(
                program_id=rate_data["program_id"],
                group_id=rate_data["group_id"],
                effective_date=rate_data["effective_date"]
            ).first()
            if existing:
                for key, value in rate_data.items():
                    setattr(existing, key, value)
                print(f"  Updated {rate_data['program_id']} / {rate_data['group_id']}")
            else:
                rate = ProgramRate(**rate_data)
                db.session.add(rate)
                rate_display = rate_data['rate'] if rate_data['rate'] else rate_data['rate_formula']
                print(f"  Added {rate_data['program_id']} / {rate_data['group_id']} = {rate_display}")
        db.session.commit()
        print(f"  Processed {len(rates)} program rates")


def populate_hts_base_rates(app):
    """Populate MFN Column 1 base rates from CSV.

    v8.0 Update (Jan 2026):
    - Now loads from data/mfn_base_rates_8digit.csv (15,262 rows)
    - CSV generated from USITC HTS https://hts.usitc.gov/
    - Required for EU 15% ceiling formula: Reciprocal = max(0, 15% - MFN)
    - Lookup supports prefix matching (8544.42.9090 -> 8544.42.90 -> 8544.42)

    CSV columns: hts_8digit, description, unit, general_rate_raw, general_ad_valorem_rate,
                 special_rate_raw, other_rate_raw, edition_label, generated_at, conflict_count_same_8digit
    """
    import csv
    from pathlib import Path
    from datetime import datetime

    csv_path = Path(__file__).parent.parent / "data" / "mfn_base_rates_8digit.csv"

    if not csv_path.exists():
        print(f"  ERROR: {csv_path} not found. MFN base rates cannot be imported.")
        return 0

    with app.app_context():
        # Check if already populated with complete data
        existing_count = HtsBaseRate.query.count()
        if existing_count >= 15000:
            print(f"hts_base_rates already has {existing_count} rows - skipping")
            return existing_count

        # Clear partial imports
        if existing_count > 0:
            print(f"  Clearing {existing_count} partial rows from hts_base_rates...")
            HtsBaseRate.query.delete()
            db.session.commit()

        print(f"Importing MFN base rates from {csv_path.name}...")

        imported = 0
        skipped = 0

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                hts_code = row.get('hts_8digit', '')
                if not hts_code:
                    skipped += 1
                    continue

                # Parse ad valorem rate (e.g., 0.07 for 7%)
                try:
                    column1_rate = float(row.get('general_ad_valorem_rate', 0) or 0)
                except ValueError:
                    column1_rate = 0.0

                description = row.get('description', '')[:512]  # Truncate to fit column

                # Parse effective date from generated_at or use default
                generated_at = row.get('generated_at', '')
                try:
                    effective_date = datetime.fromisoformat(generated_at.replace('Z', '+00:00')).date()
                except (ValueError, AttributeError):
                    effective_date = date(2025, 1, 1)

                rate = HtsBaseRate(
                    hts_code=hts_code,
                    column1_rate=column1_rate,
                    description=description,
                    effective_date=effective_date,
                    expiration_date=None,  # Current rates
                )
                db.session.add(rate)
                imported += 1

                # Commit in batches for performance
                if imported % 5000 == 0:
                    db.session.commit()
                    print(f"  Imported {imported} rows...")

        db.session.commit()
        print(f"  Imported {imported} MFN base rates, skipped {skipped}")
        return imported


def verify_data(app):
    """Verify all tables have data."""
    with app.app_context():
        print("\n=== Data Verification ===")
        print(f"TariffProgram: {TariffProgram.query.count()} rows")
        print(f"Section301Inclusion: {Section301Inclusion.query.count()} rows")
        print(f"Section301Exclusion: {Section301Exclusion.query.count()} rows")
        print(f"Section232Material: {Section232Material.query.count()} rows")
        print(f"ProgramCode: {ProgramCode.query.count()} rows")
        print(f"DutyRule: {DutyRule.query.count()} rows")
        print(f"IeepaAnnexIIExclusion: {IeepaAnnexIIExclusion.query.count()} rows")
        # v5.0 tables
        print(f"SourceDocument: {SourceDocument.query.count()} rows")
        print(f"CountryGroup: {CountryGroup.query.count()} rows")
        print(f"CountryGroupMember: {CountryGroupMember.query.count()} rows")
        print(f"ProgramRate: {ProgramRate.query.count()} rows")
        print(f"HtsBaseRate: {HtsBaseRate.query.count()} rows")

        # Show USB-C cable example
        print("\n=== USB-C Cable Example (HTS 8544.42.9090) ===")
        hts_8digit = "85444290"

        inclusion = Section301Inclusion.query.filter_by(hts_8digit=hts_8digit).first()
        if inclusion:
            print(f"Section 301: {inclusion.chapter_99_code} ({inclusion.list_name}, {float(inclusion.duty_rate)*100}%)")

        materials = Section232Material.query.filter_by(hts_8digit=hts_8digit).all()
        for mat in materials:
            print(f"Section 232 {mat.material}: claim={mat.claim_code}, disclaim={mat.disclaim_code}")

        # v4.0: Show program codes with variants
        print("\n=== v4.0 Program Codes (IEEPA Reciprocal variants) ===")
        reciprocal_codes = ProgramCode.query.filter_by(program_id="ieepa_reciprocal").all()
        for code in reciprocal_codes:
            print(f"  {code.action}/{code.variant}/{code.slice_type} -> {code.chapter_99_code}")

        # v4.0: Show Annex II sample
        print("\n=== v4.0 Annex II Exclusions (sample) ===")
        annex_ii = IeepaAnnexIIExclusion.query.limit(5).all()
        for exc in annex_ii:
            print(f"  HTS {exc.hts_code}: {exc.description[:50]}... ({exc.category})")

        # v5.0: Show country groups and rates
        print("\n=== v5.0 Country Groups ===")
        groups = CountryGroup.query.all()
        for grp in groups:
            print(f"  {grp.group_id}: {grp.description}")

        print("\n=== v5.0 Country Group Members (sample) ===")
        members = CountryGroupMember.query.filter(
            CountryGroupMember.country_code.in_(['Germany', 'UK', 'China', 'Vietnam'])
        ).all()
        for mem in members:
            print(f"  {mem.country_code} -> {mem.group_id}")

        print("\n=== v5.0 Program Rates (232 Steel/Aluminum by country) ===")
        steel_rates = ProgramRate.query.filter_by(program_id="section_232_steel").all()
        for rate in steel_rates:
            print(f"  232 Steel / {rate.group_id}: {rate.rate*100 if rate.rate else rate.rate_formula}%")
        alum_rates = ProgramRate.query.filter_by(program_id="section_232_aluminum").all()
        for rate in alum_rates:
            print(f"  232 Aluminum / {rate.group_id}: {rate.rate*100 if rate.rate else rate.rate_formula}%")

        print("\n=== v5.0 IEEPA Reciprocal Rates (with EU formula) ===")
        recip_rates = ProgramRate.query.filter_by(program_id="ieepa_reciprocal").all()
        for rate in recip_rates:
            if rate.rate_type == "formula":
                print(f"  Reciprocal / {rate.group_id}: FORMULA={rate.rate_formula}")
            else:
                print(f"  Reciprocal / {rate.group_id}: {rate.rate*100}%")

        print("\n=== v5.0 HTS Base Rates (sample for EU ceiling calc) ===")
        base_rates = HtsBaseRate.query.limit(5).all()
        for rate in base_rates:
            print(f"  HTS {rate.hts_code}: {rate.column1_rate*100}% MFN")

        # v13.0: Show temporal table counts
        print("\n=== v13.0 Temporal Rate Tables ===")
        s232_count = Section232Rate.query.count()
        ieepa_count = IeepaRate.query.count()
        print(f"  section_232_rates: {s232_count} rows")
        print(f"  ieepa_rates: {ieepa_count} rows")


def populate_section_232_temporal(app, seed_if_empty=False):
    """
    v13.0: Populate temporal Section 232 rates table.

    v17.0: Added seed_if_empty parameter to preserve runtime data.

    Creates historical rate periods for all HTS codes in section_232_materials.
    See scripts/migrate_232_to_temporal.py for the historical rate definitions.
    """
    from decimal import Decimal

    # Historical Section 232 rate periods from Presidential Proclamations
    # Official sources: CBP CSMS guidance + Federal Register proclamations
    SECTION_232_HISTORY = [
        # Steel - Original Proclamation 9705 (March 23, 2018)
        {'material': 'steel', 'rate': Decimal('0.25'),
         'start': date(2018, 3, 23), 'end': date(2025, 3, 11),
         'source_doc': 'Proclamation 9705 (83 FR 11625)'},
        # Steel - Proclamation 10896 reset to 25% (March 12, 2025)
        # CBP CSMS #64348411 confirms 25% effective Mar 12, 2025
        {'material': 'steel', 'rate': Decimal('0.25'),
         'start': date(2025, 3, 12), 'end': date(2025, 6, 3),
         'source_doc': 'Proclamation 10896 (CBP CSMS #64348411)'},
        # Steel - Proclamation 10947 increased to 50% (June 4, 2025)
        {'material': 'steel', 'rate': Decimal('0.50'),
         'start': date(2025, 6, 4), 'end': None,
         'source_doc': 'Proclamation 10947 (90 FR 25209)'},
        # Aluminum - Original Proclamation 9704 (March 23, 2018)
        {'material': 'aluminum', 'rate': Decimal('0.10'),
         'start': date(2018, 3, 23), 'end': date(2025, 3, 11),
         'source_doc': 'Proclamation 9704 (83 FR 11619)'},
        # Aluminum - Proclamation 10895 reset to 25% (March 12, 2025)
        # CBP CSMS #64384496 confirms 25% effective Mar 12, 2025
        {'material': 'aluminum', 'rate': Decimal('0.25'),
         'start': date(2025, 3, 12), 'end': date(2025, 6, 3),
         'source_doc': 'Proclamation 10895 (CBP CSMS #64384496)'},
        # Aluminum - Proclamation 10947 increased to 50% (June 4, 2025)
        {'material': 'aluminum', 'rate': Decimal('0.50'),
         'start': date(2025, 6, 4), 'end': None,
         'source_doc': 'Proclamation 10947 (90 FR 25209)'},
        # Copper - Added by Proclamation 10962 (Aug 2025)
        {'material': 'copper', 'rate': Decimal('0.50'),
         'start': date(2025, 3, 12), 'end': None,
         'source_doc': 'Proclamation 10962 - Section 232 Copper'},
        # Auto Parts - Proclamation 10908 (May 3, 2025)
        {'material': 'auto', 'rate': Decimal('0.25'),
         'start': date(2025, 5, 3), 'end': None,
         'source_doc': 'Proclamation 10908 (90 FR 14705) - Section 232 Auto Parts'},
        # Semiconductor - CBP CSMS #67400472 (Jan 15, 2026)
        {'material': 'semiconductor', 'rate': Decimal('0.25'),
         'start': date(2026, 1, 15), 'end': None,
         'source_doc': 'CBP CSMS #67400472 - Section 232 Semiconductor'},
    ]

    with app.app_context():
        # Check if already populated
        existing_count = Section232Rate.query.count()
        if existing_count > 0:
            mode_msg = " (seed-if-empty mode)" if seed_if_empty else ""
            print(f"section_232_rates has {existing_count} rows - PRESERVING{mode_msg}")
            return

        print("Populating section_232_rates temporal table...")

        # Get all HTS codes from static table
        materials = Section232Material.query.all()
        print(f"  Found {len(materials)} HTS codes in section_232_materials")

        rows_created = 0
        for mat in materials:
            # Find applicable historical periods for this material
            periods = [p for p in SECTION_232_HISTORY if p['material'] == mat.material]

            for period in periods:
                rate = Section232Rate(
                    hts_8digit=mat.hts_8digit,
                    material_type=mat.material,
                    article_type=getattr(mat, 'article_type', 'content') or 'content',
                    chapter_99_claim=mat.claim_code,
                    chapter_99_disclaim=mat.disclaim_code,
                    duty_rate=period['rate'],
                    country_code=None,  # Global rate, not country-specific
                    effective_start=period['start'],
                    effective_end=period['end'],
                    source_doc=period['source_doc'],
                    created_by='populate_tariff_tables.py v13.0',
                )
                db.session.add(rate)
                rows_created += 1

        db.session.commit()
        print(f"  Created {rows_created} temporal rows in section_232_rates")


def populate_section_232_predicates(app, seed_if_empty=False):
    """v11.0: Populate Section 232 semiconductor predicates from CSMS #67400472.

    Inserts threshold-based predicates for semiconductor 232 evaluation:
    - Range 1: TPP 14,000-17,500 AND DRAM bandwidth 4,500-5,000 GB/s
    - Range 2: TPP 20,800-21,100 AND DRAM bandwidth 5,800-6,200 GB/s

    If predicate passes → 9903.79.01 at 25%
    If predicate fails  → 9903.79.02 at 0%
    """
    with app.app_context():
        from decimal import Decimal
        from app.web.db import db
        from app.web.db.models.tariff_tables import Section232Predicate

        existing = Section232Predicate.query.count()
        if seed_if_empty and existing > 0:
            print(f"  Section 232 predicates: {existing} rows exist, skipping (seed-if-empty)")
            return

        if existing > 0:
            Section232Predicate.query.delete()
            db.session.commit()
            print(f"  Cleared {existing} existing predicate rows")

        SOURCE_DOC = "CBP CSMS #67400472 - Section 232 Semiconductor"
        PREDICATES = [
            # Range 1
            {"predicate_group": "range_1", "attribute_name": "transistor_processing_power",
             "attribute_unit": "TOPS", "threshold_min": Decimal("14000"), "threshold_max": Decimal("17500")},
            {"predicate_group": "range_1", "attribute_name": "dram_bandwidth",
             "attribute_unit": "GB/s", "threshold_min": Decimal("4500"), "threshold_max": Decimal("5000")},
            # Range 2
            {"predicate_group": "range_2", "attribute_name": "transistor_processing_power",
             "attribute_unit": "TOPS", "threshold_min": Decimal("20800"), "threshold_max": Decimal("21100")},
            {"predicate_group": "range_2", "attribute_name": "dram_bandwidth",
             "attribute_unit": "GB/s", "threshold_min": Decimal("5800"), "threshold_max": Decimal("6200")},
        ]

        rows_created = 0
        for pred_data in PREDICATES:
            pred = Section232Predicate(
                program_id="section_232_semiconductor",
                hts_scope="8471,8473",
                predicate_group=pred_data["predicate_group"],
                attribute_name=pred_data["attribute_name"],
                attribute_unit=pred_data["attribute_unit"],
                threshold_min=pred_data["threshold_min"],
                threshold_max=pred_data["threshold_max"],
                claim_heading_if_true="9903.79.01",
                rate_if_true=Decimal("0.25"),
                heading_if_false="9903.79.02",
                rate_if_false=Decimal("0"),
                effective_start=date(2026, 1, 15),
                effective_end=None,
                source_doc=SOURCE_DOC,
                created_by="populate_tariff_tables.py v11.0",
            )
            db.session.add(pred)
            rows_created += 1

        db.session.commit()
        print(f"  Created {rows_created} Section 232 semiconductor predicates")


def populate_ieepa_temporal(app, seed_if_empty=False):
    """Populate temporal IEEPA rates table from CSV.

    v18.0 Update (Jan 2026):
    - Loads from data/ieepa_rates_temporal.csv (consolidated CSV)
    - Removed hardcoded IEEPA_HISTORY - CSV is single source of truth
    - Added seed_if_empty parameter for pipeline compatibility

    CSV columns: program_type, country_code, chapter_99_code, duty_rate, variant,
                 rate_type, effective_start, effective_end, source_doc
    """
    import csv
    from pathlib import Path
    from datetime import datetime
    from decimal import Decimal

    csv_path = Path(__file__).parent.parent / "data" / "ieepa_rates_temporal.csv"

    if not csv_path.exists():
        print(f"  ERROR: {csv_path} not found. IEEPA rates cannot be imported.")
        return 0

    with app.app_context():
        existing_count = IeepaRate.query.count()

        if existing_count > 0:
            mode_msg = " (seed-if-empty mode)" if seed_if_empty else ""
            print(f"ieepa_rates has {existing_count} rows - PRESERVING{mode_msg}")
            return existing_count

        print(f"Importing IEEPA rates from {csv_path.name}...")

        rows_created = 0
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                effective_start_str = row.get('effective_start', '')
                effective_end_str = row.get('effective_end', '')

                try:
                    effective_start = datetime.strptime(effective_start_str, '%Y-%m-%d').date()
                except ValueError:
                    effective_start = date(2025, 4, 9)

                effective_end = None
                if effective_end_str and effective_end_str.strip():
                    try:
                        effective_end = datetime.strptime(effective_end_str.strip(), '%Y-%m-%d').date()
                    except ValueError:
                        effective_end = None

                rate = IeepaRate(
                    program_type=row['program_type'],
                    country_code=row['country_code'],
                    chapter_99_code=row['chapter_99_code'],
                    duty_rate=Decimal(row['duty_rate']),
                    variant=row.get('variant') or None,
                    rate_type=row.get('rate_type', 'ad_valorem'),
                    effective_start=effective_start,
                    effective_end=effective_end,
                    source_doc=row.get('source_doc', ''),
                    created_by='populate_tariff_tables.py v18.0 (CSV)',
                )
                db.session.add(rate)
                rows_created += 1

        db.session.commit()
        print(f"  Created {rows_created} temporal rows in ieepa_rates")
        return rows_created


def populate_section_301_temporal(app, seed_if_empty=False):
    """Populate section_301_rates temporal table from unified CSV.

    v20.0 Update (Jan 2026) - NOTE 31 INVARIANT VALIDATION:
    - Added validation for U.S. Note 31 subdivision ↔ rate mappings
    - 9903.91.01 (subdivision b) must have rate 25%
    - 9903.91.02 (subdivision c) must have rate 50%
    - 9903.91.03 (subdivision d) must have rate 100%
    - Raises ValueError if CSV has incorrect rate for Note 31 headings

    v17.0 Update (Jan 2026) - SEED-IF-EMPTY SUPPORT:
    - New seed_if_empty parameter: if True, skip if ANY data exists
    - This preserves pipeline-discovered rates across deploys
    - Critical for DB-as-source-of-truth architecture

    v17.0 Update (Jan 2026) - ROLE COLUMN SUPPORT:
    - Added 'role' column: 'impose' (default) or 'exclude' (exclusion granted)
    - Exclusions take precedence over impose codes via get_rate_as_of()
    - Generalizable approach: ALL data comes from CSV, no hardcoding

    v16.0 Update (Jan 2026) - UNIFIED TEMPORAL CSV:
    - Reads from data/section_301_rates_temporal.csv (consolidated file)
    - Contains BOTH legacy rates (2018-2019) AND 2024 review rates
    - Properly handles effective_start AND effective_end for rate supersession
    - Staged increases (50% → 100%) are preserved with correct date ranges
    - Replaces separate import scripts with single source of truth

    CSV columns: hts_8digit, chapter_99_code, duty_rate, effective_start, effective_end, list_name, source, role
    """
    # v20.0: U.S. Note 31 heading ↔ rate invariants (legal requirement)
    # Per HTS Chapter 99, U.S. Note 31:
    #   subdivision (b) = 9903.91.01 @ 25%
    #   subdivision (c) = 9903.91.02 @ 50%
    #   subdivision (d) = 9903.91.03 @ 100%
    NOTE_31_INVARIANTS = {
        "9903.91.01": 0.25,  # subdivision (b) - 25%
        "9903.91.02": 0.50,  # subdivision (c) - 50%
        "9903.91.03": 1.00,  # subdivision (d) - 100%
    }
    import csv
    from pathlib import Path
    from datetime import datetime

    # v17.0: Unified temporal CSV is the single source of truth
    csv_path = Path(__file__).parent.parent / "data" / "section_301_rates_temporal.csv"

    if not csv_path.exists():
        print(f"  ERROR: {csv_path} not found. Section 301 rates cannot be imported.")
        return 0

    with app.app_context():
        # Check if already populated
        existing_count = Section301Rate.query.count()

        # v17.0: seed_if_empty mode - preserve ALL existing data
        if seed_if_empty and existing_count > 0:
            print(f"section_301_rates has {existing_count} rows - PRESERVING (seed-if-empty mode)")
            return existing_count

        # Legacy behavior: Skip if >= 10000 rows (complete CSV import)
        if existing_count >= 10000:
            print(f"section_301_rates already has {existing_count} rows - skipping")
            return existing_count

        # Clear partial imports (only in non-seed-if-empty mode)
        if existing_count > 0:
            print(f"  Clearing {existing_count} partial rows from section_301_rates...")
            Section301Rate.query.delete()
            db.session.commit()

        print(f"Importing Section 301 temporal rates from {csv_path.name}...")

        imported = 0
        skipped = 0
        rate_counts = {}
        seen_keys = set()  # Track unique (hts_8digit, duty_rate, effective_start)

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Parse effective_start date
                effective_start_str = row.get('effective_start', '2018-07-06')
                try:
                    effective_start = datetime.strptime(effective_start_str, '%Y-%m-%d').date()
                except ValueError:
                    effective_start = date(2018, 7, 6)  # Default to List 1 start

                # v16.0: Parse effective_end date (may be empty/None for active rates)
                effective_end_str = row.get('effective_end', '')
                effective_end = None
                if effective_end_str and effective_end_str.strip():
                    try:
                        effective_end = datetime.strptime(effective_end_str.strip(), '%Y-%m-%d').date()
                    except ValueError:
                        effective_end = None

                hts_8digit = row['hts_8digit']
                chapter_99_code = row['chapter_99_code']
                duty_rate = float(row.get('duty_rate') or row.get('rate', 0.25))

                # v21.0: STRICT NEW ONLY validation for Note 31 headings
                # - Block NEW violations immediately (fail ingestion)
                # - Log LEGACY violations for cleanup (allow but report)
                source_doc = row.get('source') or row.get('source_pdf', 'USTR_301_Notice.pdf')
                if chapter_99_code in NOTE_31_INVARIANTS:
                    expected_rate = NOTE_31_INVARIANTS[chapter_99_code]
                    if abs(duty_rate - expected_rate) > 1e-6:  # Use tolerance
                        # Check if this EXACT row already exists in database (legacy)
                        existing = Section301Rate.query.filter_by(
                            hts_8digit=hts_8digit,
                            chapter_99_code=chapter_99_code,
                            effective_start=effective_start,
                            effective_end=effective_end,
                            source_doc=source_doc
                        ).first()

                        if existing:
                            # Legacy violation - log but allow (grandfathered)
                            import logging
                            logging.warning(
                                f"LEGACY Note 31 violation (grandfathered): {chapter_99_code} @ "
                                f"{duty_rate*100}% for HTS {hts_8digit} (expected {expected_rate*100}%)"
                            )
                        else:
                            # NEW violation - fail ingestion
                            raise ValueError(
                                f"NEW Note 31 invariant violation: {chapter_99_code} must have "
                                f"rate {expected_rate*100}%, got {duty_rate*100}% for HTS {hts_8digit}. "
                                f"Source: {source_doc}. Fix the source CSV before adding new rows."
                            )

                # Create unique key for deduplication
                unique_key = (hts_8digit, duty_rate, str(effective_start))
                if unique_key in seen_keys:
                    skipped += 1
                    continue
                seen_keys.add(unique_key)

                list_name = row.get('list_name', '')

                # Track rate distribution
                rate_pct = int(duty_rate * 100)
                rate_counts[rate_pct] = rate_counts.get(rate_pct, 0) + 1

                # v17.0: Read role column (default: 'impose')
                role = row.get('role', 'impose') or 'impose'

                rate_data = {
                    "hts_8digit": hts_8digit,
                    "hts_10digit": None,
                    "chapter_99_code": chapter_99_code,
                    "duty_rate": duty_rate,
                    "effective_start": effective_start,
                    "effective_end": effective_end,  # v16.0: Now properly set
                    "list_name": list_name,
                    "source_doc": row.get('source') or row.get('source_pdf', 'USTR_301_Notice.pdf'),
                    "role": role,  # v17.0: Support exclusion rows
                }

                rate = Section301Rate(**rate_data)
                db.session.add(rate)
                imported += 1

                # Commit in batches for performance
                if imported % 1000 == 0:
                    db.session.commit()
                    print(f"    ... imported {imported} rows")

        db.session.commit()

        print(f"  Imported {imported} temporal Section 301 rates (skipped {skipped} duplicates)")
        print(f"  Rate distribution:")
        for rate_pct, count in sorted(rate_counts.items()):
            print(f"    {rate_pct}%: {count} rows")

        return imported


# =============================================================================
# v21.0: IEEPA Enhancements
# =============================================================================

# Mapping of full country names to ISO codes for IEEPA programs
IEEPA_COUNTRY_TO_ISO = {
    "China": "CN",
    "Hong Kong": "HK",
    "Macau": "MO",
    "UK": "GB",
    "United Kingdom": "GB",
    "India": "IN",
    "Japan": "JP",
    "South Korea": "KR",
    "Korea": "KR",
    "Taiwan": "TW",
    "Vietnam": "VN",
}


def deduplicate_ieepa_tariff_programs(app):
    """
    v21.0: Remove semantic duplicates from IEEPA tariff_programs.

    The issue is that some IEEPA rows exist with both full country names
    (e.g., "China", "Hong Kong") AND ISO codes (e.g., "CN", "HK").
    This causes incorrect lookups and double-counting.

    This function:
    1. Identifies IEEPA rows with full country names that have ISO equivalents
    2. Deletes the full-name rows (keeps ISO code rows)
    3. Reports what was cleaned up

    SCOPED TO IEEPA ONLY - does NOT touch 301/232 programs.
    """
    from sqlalchemy import text

    with app.app_context():
        print("\n=== v21.0: IEEPA Semantic Duplicate Cleanup ===")

        # Step 1: Find IEEPA rows with full country names
        # Build individual placeholders for SQLite compatibility
        full_names = list(IEEPA_COUNTRY_TO_ISO.keys())
        placeholders = ", ".join(f":n{i}" for i in range(len(full_names)))
        params = {f"n{i}": name for i, name in enumerate(full_names)}
        full_name_rows = db.session.execute(text(f"""
            SELECT id, program_id, country
            FROM tariff_programs
            WHERE program_id LIKE 'ieepa%'
              AND country IN ({placeholders})
        """), params).fetchall()

        if not full_name_rows:
            print("  No IEEPA semantic duplicates found. Database is clean.")
            return 0

        print(f"  Found {len(full_name_rows)} IEEPA rows with full country names to remove:")

        # Step 2: For each full-name row, verify the ISO version exists before deleting
        deleted_count = 0
        for row in full_name_rows:
            iso_code = IEEPA_COUNTRY_TO_ISO.get(row.country)
            if not iso_code:
                continue

            # Check if ISO version exists
            iso_exists = db.session.execute(text("""
                SELECT COUNT(*) FROM tariff_programs
                WHERE program_id = :program_id AND country = :iso_code
            """), {"program_id": row.program_id, "iso_code": iso_code}).scalar()

            if iso_exists:
                # Safe to delete - ISO version exists
                print(f"    Deleting: {row.program_id} / {row.country} (id={row.id}) - replaced by {iso_code}")
                db.session.execute(text("""
                    DELETE FROM tariff_programs WHERE id = :id
                """), {"id": row.id})
                deleted_count += 1
            else:
                # ISO version doesn't exist - update instead of delete
                print(f"    Updating: {row.program_id} / {row.country} (id={row.id}) -> {iso_code}")
                db.session.execute(text("""
                    UPDATE tariff_programs SET country = :iso_code WHERE id = :id
                """), {"id": row.id, "iso_code": iso_code})

        db.session.commit()
        print(f"  Cleaned up {deleted_count} semantic duplicates from IEEPA tariff_programs")

        # Step 3: Verify no duplicates remain
        remaining = db.session.execute(text("""
            SELECT program_id, country, COUNT(*) as cnt
            FROM tariff_programs
            WHERE program_id LIKE 'ieepa%'
            GROUP BY program_id, country
            HAVING COUNT(*) > 1
        """)).fetchall()

        if remaining:
            print(f"  WARNING: {len(remaining)} exact duplicates still exist!")
            for r in remaining:
                print(f"    {r.program_id} / {r.country}: {r.cnt} rows")
        else:
            print("  Verification passed: No IEEPA duplicates remain.")

        return deleted_count


def add_reciprocal_country(app, country_code: str, standard_rate=None):
    """
    v21.0: Add all 4 IEEPA reciprocal variants for a new country.

    This function:
    1. Gets the existing effective_start from current reciprocal rows (to avoid temporal misalignment)
    2. Inserts all 4 required variants (standard, annex_ii_exempt, section_232_exempt, us_content_exempt)
    3. Respects the unique constraint on ieepa_rates

    Args:
        app: Flask application
        country_code: ISO 2-letter country code (e.g., "AU", "BR")
        standard_rate: Rate for standard variant (default: uses existing rate from other countries)

    Returns:
        Number of rows inserted
    """
    from sqlalchemy import text
    from decimal import Decimal

    VARIANTS = [
        {"variant": "standard", "chapter_99_code": "9903.01.25", "rate_key": "standard_rate"},
        {"variant": "annex_ii_exempt", "chapter_99_code": "9903.01.32", "rate": Decimal("0.0000")},
        {"variant": "section_232_exempt", "chapter_99_code": "9903.01.33", "rate": Decimal("0.0000")},
        {"variant": "us_content_exempt", "chapter_99_code": "9903.01.34", "rate": Decimal("0.0000")},
    ]

    with app.app_context():
        # Get existing effective_start to maintain temporal alignment
        existing_start = db.session.execute(text("""
            SELECT MIN(effective_start)
            FROM ieepa_rates
            WHERE program_type = 'reciprocal'
        """)).scalar()

        if existing_start is None:
            print(f"  ERROR: No existing reciprocal rows found. Cannot determine effective_start.")
            return 0

        # Get existing standard rate if not provided
        if standard_rate is None:
            existing_rate = db.session.execute(text("""
                SELECT duty_rate
                FROM ieepa_rates
                WHERE program_type = 'reciprocal' AND variant = 'standard'
                LIMIT 1
            """)).scalar()
            standard_rate = existing_rate or Decimal("0.1000")

        print(f"  Adding reciprocal variants for {country_code} (effective_start={existing_start}, rate={standard_rate})...")

        inserted = 0
        for v in VARIANTS:
            rate = v.get("rate", standard_rate if v.get("rate_key") == "standard_rate" else Decimal("0.0000"))

            # Check if already exists
            existing = db.session.execute(text("""
                SELECT id FROM ieepa_rates
                WHERE program_type = 'reciprocal'
                  AND country_code = :country_code
                  AND chapter_99_code = :chapter_99_code
                  AND effective_start = :effective_start
            """), {
                "country_code": country_code,
                "chapter_99_code": v["chapter_99_code"],
                "effective_start": existing_start
            }).scalar()

            if existing:
                print(f"    Skipping {v['variant']} - already exists")
                continue

            db.session.execute(text("""
                INSERT INTO ieepa_rates
                    (program_type, country_code, chapter_99_code, duty_rate, variant,
                     rate_type, effective_start, effective_end, source_doc, created_by)
                VALUES
                    ('reciprocal', :country_code, :chapter_99_code, :duty_rate, :variant,
                     'ad_valorem', :effective_start, NULL, 'EO 14257 Annex I', 'populate_tariff_tables.py v21.0')
            """), {
                "country_code": country_code,
                "chapter_99_code": v["chapter_99_code"],
                "duty_rate": rate,
                "variant": v["variant"],
                "effective_start": existing_start
            })
            inserted += 1
            print(f"    Added {v['variant']}: {v['chapter_99_code']} @ {rate}")

        db.session.commit()
        return inserted


def verify_reciprocal_variants(app):
    """
    v21.0: Verify all reciprocal countries have all 4 required variants.

    Returns dict with country_code -> list of missing variants
    """
    from sqlalchemy import text

    REQUIRED_VARIANTS = {'standard', 'annex_ii_exempt', 'section_232_exempt', 'us_content_exempt'}

    with app.app_context():
        result = db.session.execute(text("""
            SELECT country_code, array_agg(variant) as variants
            FROM ieepa_rates
            WHERE program_type = 'reciprocal'
            GROUP BY country_code
        """)).fetchall()

        missing = {}
        for row in result:
            existing_variants = set(row.variants)
            missing_variants = REQUIRED_VARIANTS - existing_variants
            if missing_variants:
                missing[row.country_code] = list(missing_variants)

        if missing:
            print(f"  WARNING: Countries with missing variants:")
            for country, variants in missing.items():
                print(f"    {country}: missing {variants}")
        else:
            print(f"  ✓ All {len(result)} reciprocal countries have all 4 required variants")

        return missing


def main():
    parser = argparse.ArgumentParser(description="Populate tariff tables with sample data")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate tables")
    parser.add_argument("--seed-if-empty", action="store_true",
                       help="Only seed tables if empty (preserves runtime data)")
    args = parser.parse_args()

    # Mutual exclusivity check
    if args.reset and args.seed_if_empty:
        print("ERROR: Cannot use --reset and --seed-if-empty together")
        print("  --reset: Drops all tables and reloads from CSV")
        print("  --seed-if-empty: Only loads CSV if tables are empty (preserves data)")
        return

    seed_if_empty = args.seed_if_empty

    if seed_if_empty:
        print("=== Tariff Tables Population Script (v17.0 - Seed If Empty Mode) ===\n")
        print("Mode: --seed-if-empty - Will only seed tables that are empty")
        print("      Runtime data (pipeline discoveries, evidence) will be preserved.\n")
    else:
        print("=== Tariff Tables Population Script (v17.0 - DB as Source of Truth) ===\n")

    # Use the existing Flask app factory
    app = create_app()

    # Initialize tables (create if not exist, never drop unless --reset)
    init_tables(app, reset=args.reset)

    # Populate all tables (v4.0 and earlier)
    populate_tariff_programs(app)

    # v21.0: Clean up IEEPA semantic duplicates (full names vs ISO codes)
    deduplicate_ieepa_tariff_programs(app)

    # v17.0: Removed populate_section_301_from_csv() - now using unified temporal CSV
    # The temporal table (Section301Rate) is the single source of truth
    # Legacy Section301Inclusion table is populated by populate_section_301_inclusions() for test cases only

    # Manual overrides/test cases
    populate_section_301_inclusions(app)
    populate_section_301_exclusions(app)
    populate_section_232_materials(app)
    populate_program_codes(app)
    populate_duty_rules(app)
    populate_annex_ii_exclusions(app)  # v4.0: Annex II

    # v5.0: Country-specific rates and audit trail
    populate_source_documents(app)
    populate_country_groups(app)
    populate_country_group_members(app)
    populate_program_rates(app)
    populate_hts_base_rates(app)

    # v13.0: Temporal rate tables (must run AFTER section_232_materials is populated)
    # v17.0: Pass seed_if_empty to preserve runtime data
    populate_section_232_temporal(app, seed_if_empty=seed_if_empty)
    populate_section_232_predicates(app, seed_if_empty=seed_if_empty)  # v11.0: Semiconductor predicates
    populate_ieepa_temporal(app, seed_if_empty=seed_if_empty)

    # v15.0: Section 301 temporal (after CSV import)
    # v17.0: Critical - this is where pipeline data was being overwritten
    populate_section_301_temporal(app, seed_if_empty=seed_if_empty)

    # Verify data
    verify_data(app)

    print("\n=== Done! ===")


if __name__ == "__main__":
    main()
