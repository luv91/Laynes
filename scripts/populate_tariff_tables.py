"""
Script to initialize and populate tariff tables with REAL 2025 tariff rates.

This script:
1. Creates the tariff tables in the database
2. Populates them with REAL rates from government sources (as of Dec 2025)
3. Includes the USB-C cable example (HTS 8544.42.9090)

Usage:
    cd lanes
    pipenv run python scripts/populate_tariff_tables.py

To reset tables:
    pipenv run python scripts/populate_tariff_tables.py --reset

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
)


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

    v4.0 Update:
    - filing_sequence: Order for ACE entry display (per CBP CSMS #64018403)
    - calculation_sequence: Order for duty math (232 before IEEPA Reciprocal)

    Filing Order (per CSMS #64018403):
    1. Section 301
    2. IEEPA Fentanyl
    3. IEEPA Reciprocal
    4-6. Section 232 (Copper, Steel, Aluminum)

    Calculation Order:
    - 232 programs must calculate FIRST to determine remaining_value
    - IEEPA Reciprocal calculates on remaining_value (product - 232 content)
    """
    programs = [
        # Section 301 - China tariffs
        {
            "program_id": "section_301",
            "program_name": "Section 301 China Tariffs",
            "country": "China",
            "check_type": "hts_lookup",
            "condition_handler": "none",
            "condition_param": None,
            "inclusion_table": "section_301_inclusions",
            "exclusion_table": "section_301_exclusions",
            "filing_sequence": 1,
            "calculation_sequence": 1,
            "source_document": "USTR_301_Notice.pdf",
            "effective_date": date(2018, 7, 6),
            "expiration_date": None,
        },
        # IEEPA Fentanyl - applies to all China imports
        {
            "program_id": "ieepa_fentanyl",
            "program_name": "IEEPA Fentanyl Tariff",
            "country": "China",
            "check_type": "always",
            "condition_handler": "none",
            "condition_param": None,
            "inclusion_table": None,
            "exclusion_table": None,
            "filing_sequence": 2,
            "calculation_sequence": 2,
            "source_document": "IEEPA_Fentanyl_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # IEEPA Fentanyl - Hong Kong (same as China per broker feedback)
        {
            "program_id": "ieepa_fentanyl",
            "program_name": "IEEPA Fentanyl Tariff",
            "country": "Hong Kong",
            "check_type": "always",
            "condition_handler": "none",
            "condition_param": None,
            "inclusion_table": None,
            "exclusion_table": None,
            "filing_sequence": 2,
            "calculation_sequence": 2,
            "source_document": "IEEPA_Fentanyl_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # IEEPA Fentanyl - Macau (same as China per broker feedback)
        {
            "program_id": "ieepa_fentanyl",
            "program_name": "IEEPA Fentanyl Tariff",
            "country": "Macau",
            "check_type": "always",
            "condition_handler": "none",
            "condition_param": None,
            "inclusion_table": None,
            "exclusion_table": None,
            "filing_sequence": 2,
            "calculation_sequence": 2,
            "source_document": "IEEPA_Fentanyl_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # Section 232 - Copper (applies to ALL countries)
        # Note: 232 programs calculate BEFORE ieepa_reciprocal for unstacking
        # v7.0: disclaim_behavior='required' - must file disclaim code in other slices
        {
            "program_id": "section_232_copper",
            "program_name": "Section 232 Copper",
            "country": "ALL",
            "check_type": "hts_lookup",
            "condition_handler": "handle_material_composition",
            "condition_param": "copper",
            "inclusion_table": "section_232_materials",
            "exclusion_table": None,
            "filing_sequence": 4,  # Display order: after IEEPA Reciprocal
            "calculation_sequence": 3,  # Calc order: before IEEPA Reciprocal
            "source_document": "Section_232_Copper_Proclamation.pdf",
            "effective_date": date(2020, 1, 1),
            "expiration_date": None,
            "disclaim_behavior": "required",  # v7.0: Must include disclaim code in other slices
        },
        # Section 232 - Steel (applies to ALL countries)
        # v7.0: disclaim_behavior='omit' - omit entirely when not claimed
        {
            "program_id": "section_232_steel",
            "program_name": "Section 232 Steel",
            "country": "ALL",
            "check_type": "hts_lookup",
            "condition_handler": "handle_material_composition",
            "condition_param": "steel",
            "inclusion_table": "section_232_materials",
            "exclusion_table": None,
            "filing_sequence": 5,  # Display order: after IEEPA Reciprocal
            "calculation_sequence": 4,  # Calc order: before IEEPA Reciprocal
            "source_document": "Section_232_Steel_Proclamation.pdf",
            "effective_date": date(2018, 3, 23),
            "expiration_date": None,
            "disclaim_behavior": "omit",  # v7.0: Omit entirely when not claimed
        },
        # Section 232 - Aluminum (applies to ALL countries)
        # v7.0: disclaim_behavior='omit' - omit entirely when not claimed
        {
            "program_id": "section_232_aluminum",
            "program_name": "Section 232 Aluminum",
            "country": "ALL",
            "check_type": "hts_lookup",
            "condition_handler": "handle_material_composition",
            "condition_param": "aluminum",
            "inclusion_table": "section_232_materials",
            "exclusion_table": None,
            "filing_sequence": 6,  # Display order: after IEEPA Reciprocal
            "calculation_sequence": 5,  # Calc order: before IEEPA Reciprocal
            "source_document": "Section_232_Aluminum_Proclamation.pdf",
            "effective_date": date(2018, 3, 23),
            "expiration_date": None,
            "disclaim_behavior": "omit",  # v7.0: Omit entirely when not claimed
        },
        # IEEPA Reciprocal - depends on Section 232 claims for unstacking
        # filing_sequence=3 (display after Fentanyl)
        # calculation_sequence=6 (calculate AFTER 232 to know remaining_value)
        # NOTE: IEEPA Reciprocal applies to many countries, not just China
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "China",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",  # v4.0: Annex II lookup
            "filing_sequence": 3,  # Display order: after Fentanyl
            "calculation_sequence": 6,  # Calc order: AFTER 232 programs
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # IEEPA Reciprocal - Hong Kong (same as China)
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "Hong Kong",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # IEEPA Reciprocal - Macau (same as China)
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "Macau",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # NOTE: Germany is NOT subject to IEEPA Reciprocal
        # per test case v4.0 Case 3 - Germany should only get 232 programs
        # UK and other countries listed below ARE subject to IEEPA Reciprocal
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "UK",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "Japan",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "Vietnam",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "India",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "Taiwan",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        {
            "program_id": "ieepa_reciprocal",
            "program_name": "IEEPA Reciprocal Tariff",
            "country": "South Korea",
            "check_type": "always",
            "condition_handler": "handle_dependency",
            "condition_param": "section_232",
            "inclusion_table": None,
            "exclusion_table": "ieepa_annex_ii_exclusions",
            "filing_sequence": 3,
            "calculation_sequence": 6,
            "source_document": "IEEPA_Reciprocal_Notice.pdf",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
    ]

    with app.app_context():
        print("Populating tariff_programs...")
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


def populate_section_301_inclusions(app):
    """Populate Section 301 inclusion list (sample HTS codes)."""
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
    ]

    with app.app_context():
        print("Populating section_301_inclusions...")
        for inc_data in inclusions:
            existing = Section301Inclusion.query.filter_by(
                hts_8digit=inc_data["hts_8digit"],
                list_name=inc_data["list_name"]
            ).first()
            if not existing:
                inclusion = Section301Inclusion(**inc_data)
                db.session.add(inclusion)
                print(f"  Added HTS {inc_data['hts_8digit']} ({inc_data['list_name']})")
        db.session.commit()
        print(f"  Added {len(inclusions)} Section 301 inclusions")


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

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert HTS code to 8-digit format (remove dots, pad if needed)
                hts_code = row['hts_code'].replace('.', '')
                # Use first 8 digits for lookup (standard 232 matching)
                hts_8digit = hts_code[:8]

                # Map material to source doc
                source_docs = {
                    'copper': 'CSMS_65794272_Copper_Aug2025.pdf',
                    'steel': 'CSMS_65936570_Steel_Aug2025.pdf',
                    'aluminum': 'CSMS_65936615_Aluminum_Aug2025.pdf',
                }

                mat_data = {
                    "hts_8digit": hts_8digit,
                    "material": row['material'],
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

    REAL 2025/2026 RATES (Updated per 90 FR 10524, June 4, 2025):
    - Section 301: 25% (unchanged)
    - IEEPA Fentanyl: 10% (reduced from 20% on Nov 10, 2025)
    - IEEPA Reciprocal: 10% (taxable), 0% (exempt variants)
    - Section 232 Copper: 50%
    - Section 232 Steel: 50% (default), 25% (UK exception)
    - Section 232 Aluminum: 50% (default), 25% (UK exception) - DOUBLED June 2025
    """
    codes = [
        # ===================================================================
        # Section 301 - 25% on full product (slice_type='all' applies to any)
        # ===================================================================
        {"program_id": "section_301", "action": "apply", "variant": None, "slice_type": "all",
         "chapter_99_code": "9903.88.03", "duty_rate": 0.25, "applies_to": "full",
         "source_doc": "USTR_301_List3_Notice.pdf"},

        # ===================================================================
        # IEEPA Fentanyl - 10% on full product (applies to all slices)
        # ===================================================================
        {"program_id": "ieepa_fentanyl", "action": "apply", "variant": None, "slice_type": "all",
         "chapter_99_code": "9903.01.24", "duty_rate": 0.10, "applies_to": "full",
         "source_doc": "IEEPA_Fentanyl_EO_Nov2025.pdf"},

        # ===================================================================
        # IEEPA Reciprocal - Multiple variants with different codes
        # ===================================================================
        # Variant: taxable - Pay 10% on non-metal slice
        {"program_id": "ieepa_reciprocal", "action": "paid", "variant": "taxable", "slice_type": "non_metal",
         "chapter_99_code": "9903.01.25", "duty_rate": 0.10, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_Notice.pdf"},
        {"program_id": "ieepa_reciprocal", "action": "paid", "variant": "taxable", "slice_type": "full",
         "chapter_99_code": "9903.01.25", "duty_rate": 0.10, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_Notice.pdf"},

        # Variant: annex_ii_exempt - HTS in Annex II list (pharma/chem/minerals)
        {"program_id": "ieepa_reciprocal", "action": "exempt", "variant": "annex_ii_exempt", "slice_type": "all",
         "chapter_99_code": "9903.01.32", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_AnnexII.pdf"},

        # Variant: metal_exempt - 232 metal content slice exempt from Reciprocal
        {"program_id": "ieepa_reciprocal", "action": "exempt", "variant": "metal_exempt", "slice_type": "copper_slice",
         "chapter_99_code": "9903.01.33", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_Notice.pdf"},
        {"program_id": "ieepa_reciprocal", "action": "exempt", "variant": "metal_exempt", "slice_type": "steel_slice",
         "chapter_99_code": "9903.01.33", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_Notice.pdf"},
        {"program_id": "ieepa_reciprocal", "action": "exempt", "variant": "metal_exempt", "slice_type": "aluminum_slice",
         "chapter_99_code": "9903.01.33", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_Notice.pdf"},

        # Variant: us_content_exempt - >20% US origin content
        {"program_id": "ieepa_reciprocal", "action": "exempt", "variant": "us_content_exempt", "slice_type": "all",
         "chapter_99_code": "9903.01.34", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "IEEPA_Reciprocal_Notice.pdf"},

        # ===================================================================
        # Section 232 Copper - 50%
        # Claim on copper_slice, Disclaim on non_metal and other metals
        # ===================================================================
        {"program_id": "section_232_copper", "action": "claim", "variant": None, "slice_type": "copper_slice",
         "chapter_99_code": "9903.78.01", "duty_rate": 0.50, "applies_to": "partial",
         "source_doc": "CSMS_65794272_Copper_July2025.pdf"},
        {"program_id": "section_232_copper", "action": "disclaim", "variant": None, "slice_type": "non_metal",
         "chapter_99_code": "9903.78.02", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "CSMS_65794272_Copper_July2025.pdf"},
        {"program_id": "section_232_copper", "action": "disclaim", "variant": None, "slice_type": "steel_slice",
         "chapter_99_code": "9903.78.02", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "CSMS_65794272_Copper_July2025.pdf"},
        {"program_id": "section_232_copper", "action": "disclaim", "variant": None, "slice_type": "aluminum_slice",
         "chapter_99_code": "9903.78.02", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "CSMS_65794272_Copper_July2025.pdf"},
        {"program_id": "section_232_copper", "action": "disclaim", "variant": None, "slice_type": "full",
         "chapter_99_code": "9903.78.02", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "CSMS_65794272_Copper_July2025.pdf"},

        # ===================================================================
        # Section 232 Steel - 50%
        # Claim on steel_slice, Disclaim on non_metal and other metals
        # ===================================================================
        {"program_id": "section_232_steel", "action": "claim", "variant": None, "slice_type": "steel_slice",
         "chapter_99_code": "9903.80.01", "duty_rate": 0.50, "applies_to": "partial",
         "source_doc": "232_Steel_Proclamation_10895.pdf"},
        {"program_id": "section_232_steel", "action": "disclaim", "variant": None, "slice_type": "non_metal",
         "chapter_99_code": "9903.80.02", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "232_Steel_Proclamation_10895.pdf"},
        {"program_id": "section_232_steel", "action": "disclaim", "variant": None, "slice_type": "copper_slice",
         "chapter_99_code": "9903.80.02", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "232_Steel_Proclamation_10895.pdf"},
        {"program_id": "section_232_steel", "action": "disclaim", "variant": None, "slice_type": "aluminum_slice",
         "chapter_99_code": "9903.80.02", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "232_Steel_Proclamation_10895.pdf"},
        {"program_id": "section_232_steel", "action": "disclaim", "variant": None, "slice_type": "full",
         "chapter_99_code": "9903.80.02", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "232_Steel_Proclamation_10895.pdf"},

        # ===================================================================
        # Section 232 Aluminum - 50% (UPDATED per 90 FR 10524, June 4, 2025)
        # Claim on aluminum_slice, Disclaim on non_metal and other metals
        # ===================================================================
        {"program_id": "section_232_aluminum", "action": "claim", "variant": None, "slice_type": "aluminum_slice",
         "chapter_99_code": "9903.85.08", "duty_rate": 0.50, "applies_to": "partial",
         "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf"},
        {"program_id": "section_232_aluminum", "action": "disclaim", "variant": None, "slice_type": "non_metal",
         "chapter_99_code": "9903.85.09", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf"},
        {"program_id": "section_232_aluminum", "action": "disclaim", "variant": None, "slice_type": "copper_slice",
         "chapter_99_code": "9903.85.09", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf"},
        {"program_id": "section_232_aluminum", "action": "disclaim", "variant": None, "slice_type": "steel_slice",
         "chapter_99_code": "9903.85.09", "duty_rate": 0.0, "applies_to": "partial",
         "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf"},
        {"program_id": "section_232_aluminum", "action": "disclaim", "variant": None, "slice_type": "full",
         "chapter_99_code": "9903.85.09", "duty_rate": 0.0, "applies_to": "full",
         "source_doc": "CSMS_65936615_Aluminum_Aug2025.pdf"},
    ]

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
    rules = [
        # Non-232 programs: duty on full product value
        {"program_id": "section_301", "calculation_type": "additive", "base_on": "product_value", "compounds_with": None, "source_doc": "301_Notice.pdf", "content_key": None, "fallback_base_on": None, "base_effect": None},
        {"program_id": "ieepa_fentanyl", "calculation_type": "additive", "base_on": "product_value", "compounds_with": None, "source_doc": "IEEPA_Fentanyl.pdf", "content_key": None, "fallback_base_on": None, "base_effect": None},
        # IEEPA Reciprocal: duty on REMAINING value (after 232 deductions) - Phase 6.5
        {"program_id": "ieepa_reciprocal", "calculation_type": "additive", "base_on": "remaining_value", "compounds_with": None, "source_doc": "IEEPA_Reciprocal.pdf", "content_key": None, "fallback_base_on": None, "base_effect": None},
        # Section 232 programs: duty on material content VALUE (Phase 6)
        # base_effect='subtract_from_remaining' - these values reduce IEEPA base (Phase 6.5)
        # If content_value unknown, fallback to full_value (penalty case)
        {"program_id": "section_232_copper", "calculation_type": "on_portion", "base_on": "content_value", "compounds_with": None, "source_doc": "CSMS_65794272_Copper_July2025.pdf", "content_key": "copper", "fallback_base_on": "full_value", "base_effect": "subtract_from_remaining"},
        {"program_id": "section_232_steel", "calculation_type": "on_portion", "base_on": "content_value", "compounds_with": None, "source_doc": "232_Steel_Proclamation_10895.pdf", "content_key": "steel", "fallback_base_on": "full_value", "base_effect": "subtract_from_remaining"},
        {"program_id": "section_232_aluminum", "calculation_type": "on_portion", "base_on": "content_value", "compounds_with": None, "source_doc": "232_Aluminum_Proclamation_10896.pdf", "content_key": "aluminum", "fallback_base_on": "full_value", "base_effect": "subtract_from_remaining"},
    ]

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


def populate_annex_ii_exclusions(app):
    """Populate IEEPA Annex II exclusions (HTS codes exempt from Reciprocal tariffs).

    v4.0 Update (Dec 2025):
    - New table for HTS codes exempt from IEEPA Reciprocal per Annex II
    - Includes pharmaceuticals, chemicals, critical minerals
    - Uses prefix matching: 2934 matches 2934.99.9050

    Note: This is sample data. Real Annex II list is much larger.
    HTS codes are stored as prefixes (4, 6, 8, or 10 digits).

    Source: Executive Order on Reciprocal Tariffs, Annex II
    """
    exclusions = [
        # Pharmaceutical ingredients (Chapter 29)
        {"hts_code": "2934", "description": "Nucleic acids and their salts, heterocyclic compounds",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "2937", "description": "Hormones, prostaglandins, thromboxanes",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "2941", "description": "Antibiotics",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "2942", "description": "Other organic compounds",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},

        # Pharmaceutical preparations (Chapter 30)
        {"hts_code": "3001", "description": "Glands, organs, extracts for organo-therapeutic uses",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "3002", "description": "Blood, vaccines, toxins, cultures",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "3003", "description": "Medicaments, not in dosage form",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "3004", "description": "Medicaments in measured doses",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},

        # Critical minerals (Chapter 26, 28, 80, 81)
        {"hts_code": "2602", "description": "Manganese ores and concentrates",
         "category": "critical_mineral", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "2610", "description": "Chromium ores and concentrates",
         "category": "critical_mineral", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "2611", "description": "Tungsten ores and concentrates",
         "category": "critical_mineral", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "8001", "description": "Unwrought tin",
         "category": "critical_mineral", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "8101", "description": "Tungsten (wolfram) and articles thereof",
         "category": "critical_mineral", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},

        # Chemicals (Chapter 28)
        {"hts_code": "2801", "description": "Fluorine, chlorine, bromine, iodine",
         "category": "chemical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
        {"hts_code": "2804", "description": "Hydrogen, rare gases, oxygen, nitrogen",
         "category": "chemical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},

        # Plasmids (our UK test case)
        {"hts_code": "293499", "description": "Other heterocyclic compounds, nucleic acid-based",
         "category": "pharmaceutical", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},

        # v7.0: Phoebe example TC-v7.0-006 - Computer parts exempt from IEEPA Reciprocal
        {"hts_code": "84733051", "description": "Parts of ADP machines, printed circuit assemblies",
         "category": "semiconductor", "source_doc": "IEEPA_Reciprocal_AnnexII.pdf",
         "effective_date": date(2024, 1, 1), "expiration_date": None},
    ]

    with app.app_context():
        print("Populating ieepa_annex_ii_exclusions (v4.0)...")
        for exc_data in exclusions:
            existing = IeepaAnnexIIExclusion.query.filter_by(
                hts_code=exc_data["hts_code"]
            ).first()
            if existing:
                # Update existing record
                for key, value in exc_data.items():
                    setattr(existing, key, value)
                print(f"  Updated HTS {exc_data['hts_code']} ({exc_data['category']})")
            else:
                exclusion = IeepaAnnexIIExclusion(**exc_data)
                db.session.add(exclusion)
                print(f"  Added HTS {exc_data['hts_code']} ({exc_data['category']})")
        db.session.commit()
        print(f"  Processed {len(exclusions)} Annex II exclusions")


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

    v5.0 Update (Dec 2025):
    - EU: European Union countries (15% ceiling rule)
    - UK: United Kingdom (232 exception - stays at 25%)
    - CN: China (full tariffs)
    - USMCA: Mexico, Canada (FTA - not currently used for stacking)
    """
    groups = [
        {
            "group_id": "EU",
            "description": "European Union - 15% ceiling rule for IEEPA Reciprocal",
            "effective_date": date(2025, 8, 7),
            "expiration_date": None,
        },
        {
            "group_id": "UK",
            "description": "United Kingdom - 232 Steel/Aluminum exception (25% not 50%)",
            "effective_date": date(2025, 6, 4),
            "expiration_date": None,
        },
        {
            "group_id": "CN",
            "description": "China - Full tariffs (301, Fentanyl, 232, Reciprocal)",
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        {
            "group_id": "USMCA",
            "description": "USMCA countries - Mexico, Canada (FTA treatment)",
            "effective_date": date(2020, 7, 1),
            "expiration_date": None,
        },
        {
            "group_id": "default",
            "description": "Default group for countries without special treatment",
            "effective_date": date(2020, 1, 1),
            "expiration_date": None,
        },
    ]

    with app.app_context():
        print("Populating country_groups (v5.0)...")
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

    v5.0 Update (Dec 2025):
    - Maps country names (and ISO codes) to their groups
    - Supports multiple names per country (Germany, DE, DEU)
    - Membership is time-bound for events like Brexit
    """
    members = [
        # EU countries (27 member states + common variants)
        {"country_code": "Germany", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "DE", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "France", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "FR", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Italy", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "IT", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Spain", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "ES", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Netherlands", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "NL", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Belgium", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "BE", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Poland", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "PL", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Austria", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "AT", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Ireland", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "IE", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Portugal", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "PT", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Greece", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "GR", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Sweden", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "SE", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Denmark", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "DK", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Finland", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "FI", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Czech Republic", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "CZ", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Romania", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "RO", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "Hungary", "group_id": "EU", "effective_date": date(2025, 8, 7)},
        {"country_code": "HU", "group_id": "EU", "effective_date": date(2025, 8, 7)},

        # UK (separate since Brexit)
        {"country_code": "United Kingdom", "group_id": "UK", "effective_date": date(2025, 6, 4)},
        {"country_code": "UK", "group_id": "UK", "effective_date": date(2025, 6, 4)},
        {"country_code": "GB", "group_id": "UK", "effective_date": date(2025, 6, 4)},
        {"country_code": "Great Britain", "group_id": "UK", "effective_date": date(2025, 6, 4)},

        # China
        {"country_code": "China", "group_id": "CN", "effective_date": date(2024, 1, 1)},
        {"country_code": "CN", "group_id": "CN", "effective_date": date(2024, 1, 1)},
        {"country_code": "PRC", "group_id": "CN", "effective_date": date(2024, 1, 1)},

        # USMCA
        {"country_code": "Mexico", "group_id": "USMCA", "effective_date": date(2020, 7, 1)},
        {"country_code": "MX", "group_id": "USMCA", "effective_date": date(2020, 7, 1)},
        {"country_code": "Canada", "group_id": "USMCA", "effective_date": date(2020, 7, 1)},
        {"country_code": "CA", "group_id": "USMCA", "effective_date": date(2020, 7, 1)},
    ]

    with app.app_context():
        print("Populating country_group_members (v5.0)...")
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
    rates = [
        # ===================================================================
        # Section 232 Steel
        # ===================================================================
        {
            "program_id": "section_232_steel",
            "group_id": "default",
            "rate": 0.50,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2025, 6, 4),
            "expiration_date": None,
        },
        {
            "program_id": "section_232_steel",
            "group_id": "UK",
            "rate": 0.25,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2025, 6, 4),
            "expiration_date": None,
        },

        # ===================================================================
        # Section 232 Aluminum - 50% (UPDATED per 90 FR 10524, June 4, 2025)
        # UK exception stays at 25%
        # ===================================================================
        {
            "program_id": "section_232_aluminum",
            "group_id": "default",
            "rate": 0.50,  # UPDATED: 50% per 90 FR 10524 (June 4, 2025)
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2025, 6, 4),
            "expiration_date": None,
        },
        {
            "program_id": "section_232_aluminum",
            "group_id": "UK",
            "rate": 0.25,  # UK exception stays at 25%
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2025, 6, 4),
            "expiration_date": None,
        },

        # ===================================================================
        # Section 232 Copper (same for all countries)
        # ===================================================================
        {
            "program_id": "section_232_copper",
            "group_id": "default",
            "rate": 0.50,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2025, 7, 31),
            "expiration_date": None,
        },

        # ===================================================================
        # IEEPA Reciprocal
        # ===================================================================
        # Default: 10% flat
        {
            "program_id": "ieepa_reciprocal",
            "group_id": "default",
            "rate": 0.10,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
        # EU: Formula - 15% minus MFN base rate
        {
            "program_id": "ieepa_reciprocal",
            "group_id": "EU",
            "rate": None,  # Calculated at runtime
            "rate_type": "formula",
            "rate_formula": "15pct_minus_mfn",
            "effective_date": date(2025, 8, 7),
            "expiration_date": None,
        },
        # UK: 10% flat (not EU, so no ceiling rule)
        {
            "program_id": "ieepa_reciprocal",
            "group_id": "UK",
            "rate": 0.10,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },

        # ===================================================================
        # Section 301 (China only, but store for completeness)
        # ===================================================================
        {
            "program_id": "section_301",
            "group_id": "CN",
            "rate": 0.25,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2018, 7, 6),
            "expiration_date": None,
        },

        # ===================================================================
        # IEEPA Fentanyl (China only)
        # ===================================================================
        {
            "program_id": "ieepa_fentanyl",
            "group_id": "CN",
            "rate": 0.10,
            "rate_type": "fixed",
            "rate_formula": None,
            "effective_date": date(2024, 1, 1),
            "expiration_date": None,
        },
    ]

    with app.app_context():
        print("Populating program_rates (v5.0)...")
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
    """Populate MFN Column 1 base rates.

    v5.0 Update (Dec 2025):
    - Required for EU 15% ceiling formula: Reciprocal = max(0, 15% - MFN)
    - Lookup supports prefix matching (8544.42.9090 -> 8544.42.90 -> 8544.42)
    - Source: USITC HTS https://hts.usitc.gov/

    Sample rates for common HTS codes. In production, this would be populated
    from the full USITC HTS database.
    """
    base_rates = [
        # USB-C cables (HTS 8544.42.90xx)
        {
            "hts_code": "8544.42.90",
            "column1_rate": 0.026,  # 2.6%
            "description": "Other electric conductors, for a voltage not exceeding 1,000 V, fitted with connectors",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },
        # Full 10-digit for more specific match
        {
            "hts_code": "8544.42.9090",
            "column1_rate": 0.026,  # 2.6%
            "description": "Other insulated electric conductors, for voltage <=1kV, with connectors",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },

        # LED lamps (HTS 8539.50.00)
        {
            "hts_code": "8539.50.00",
            "column1_rate": 0.02,  # 2%
            "description": "Light-emitting diode (LED) lamps",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },

        # Computers/laptops (HTS 8471.30.01)
        {
            "hts_code": "8471.30.01",
            "column1_rate": 0.0,  # 0% (duty-free)
            "description": "Portable digital automatic data processing machines, weight <=10 kg",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },

        # Pharmaceuticals - nucleic acids (HTS 2934.99.90)
        {
            "hts_code": "2934.99.90",
            "column1_rate": 0.064,  # 6.4%
            "description": "Other heterocyclic compounds, nucleic acids and their salts",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },
        {
            "hts_code": "2934.99.9050",
            "column1_rate": 0.064,  # 6.4%
            "description": "Nucleic acids and their salts, whether or not chemically defined",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },

        # Optical devices (HTS 9013.80.xx)
        {
            "hts_code": "9013.80.00",
            "column1_rate": 0.049,  # 4.9%
            "description": "Other optical devices, appliances and instruments",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },

        # Steel articles (sample)
        {
            "hts_code": "7326.90.86",
            "column1_rate": 0.029,  # 2.9%
            "description": "Other articles of iron or steel",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },

        # Aluminum articles (sample)
        {
            "hts_code": "7616.99.51",
            "column1_rate": 0.051,  # 5.1%
            "description": "Other articles of aluminum",
            "effective_date": date(2025, 1, 1),
            "expiration_date": None,
        },
    ]

    with app.app_context():
        print("Populating hts_base_rates (v5.0)...")
        for rate_data in base_rates:
            existing = HtsBaseRate.query.filter_by(
                hts_code=rate_data["hts_code"],
                effective_date=rate_data["effective_date"]
            ).first()
            if existing:
                for key, value in rate_data.items():
                    setattr(existing, key, value)
                print(f"  Updated HTS {rate_data['hts_code']} = {rate_data['column1_rate']*100}%")
            else:
                rate = HtsBaseRate(**rate_data)
                db.session.add(rate)
                print(f"  Added HTS {rate_data['hts_code']} = {rate_data['column1_rate']*100}%")
        db.session.commit()
        print(f"  Processed {len(base_rates)} HTS base rates")


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


def main():
    parser = argparse.ArgumentParser(description="Populate tariff tables with sample data")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate tables")
    args = parser.parse_args()

    print("=== Tariff Tables Population Script (v8.0 - CBP 232 Import) ===\n")

    # Use the existing Flask app factory
    app = create_app()

    # Initialize tables
    init_tables(app, reset=args.reset)

    # Populate all tables (v4.0 and earlier)
    populate_tariff_programs(app)
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

    # Verify data
    verify_data(app)

    print("\n=== Done! ===")


if __name__ == "__main__":
    main()
