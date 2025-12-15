"""
Script to populate v6.0 tariff tables.

This script populates:
1. country_aliases - Country name normalization
2. program_country_scope - Data-driven country applicability
3. program_suppressions - Program interaction rules
4. ingestion_runs - Audit trail (created on data changes)

Usage:
    cd lanes
    pipenv run python scripts/populate_v6_tables.py

To reset tables:
    pipenv run python scripts/populate_v6_tables.py --reset

v6.0 Features:
- Data-driven country scope (no more hardcoded country lists)
- Order-independent program suppression resolution
- Country input normalization (Macau/MO/Macao all resolve to MO)
- Audit trail for data ingestion operations
"""

import os
import sys
import argparse
from datetime import date, datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import (
    CountryAlias,
    ProgramCountryScope,
    ProgramSuppression,
    IngestionRun,
    CountryGroup,
    CountryGroupMember,
    SourceDocument,
)


# =============================================================================
# Country Aliases Data
# =============================================================================

COUNTRY_ALIASES = [
    # China variants
    ("China", "china", "CN", "CHN", "China"),
    ("CN", "cn", "CN", "CHN", "China"),
    ("PRC", "prc", "CN", "CHN", "China"),
    ("People's Republic of China", "people's republic of china", "CN", "CHN", "China"),

    # Hong Kong variants
    ("Hong Kong", "hong kong", "HK", "HKG", "Hong Kong"),
    ("HK", "hk", "HK", "HKG", "Hong Kong"),
    ("Hongkong", "hongkong", "HK", "HKG", "Hong Kong"),

    # Macau variants (key addition per broker feedback)
    ("Macau", "macau", "MO", "MAC", "Macau"),
    ("MO", "mo", "MO", "MAC", "Macau"),
    ("Macao", "macao", "MO", "MAC", "Macau"),
    ("MAC", "mac", "MO", "MAC", "Macau"),

    # Germany variants
    ("Germany", "germany", "DE", "DEU", "Germany"),
    ("DE", "de", "DE", "DEU", "Germany"),
    ("Deutschland", "deutschland", "DE", "DEU", "Germany"),
    ("DEU", "deu", "DE", "DEU", "Germany"),

    # United Kingdom variants
    ("United Kingdom", "united kingdom", "GB", "GBR", "United Kingdom"),
    ("UK", "uk", "GB", "GBR", "United Kingdom"),
    ("GB", "gb", "GB", "GBR", "United Kingdom"),
    ("Great Britain", "great britain", "GB", "GBR", "United Kingdom"),
    ("England", "england", "GB", "GBR", "United Kingdom"),

    # Vietnam variants
    ("Vietnam", "vietnam", "VN", "VNM", "Vietnam"),
    ("VN", "vn", "VN", "VNM", "Vietnam"),
    ("Viet Nam", "viet nam", "VN", "VNM", "Vietnam"),

    # Japan variants
    ("Japan", "japan", "JP", "JPN", "Japan"),
    ("JP", "jp", "JP", "JPN", "Japan"),

    # South Korea variants
    ("South Korea", "south korea", "KR", "KOR", "South Korea"),
    ("Korea", "korea", "KR", "KOR", "South Korea"),
    ("KR", "kr", "KR", "KOR", "South Korea"),
    ("Republic of Korea", "republic of korea", "KR", "KOR", "South Korea"),

    # Taiwan variants
    ("Taiwan", "taiwan", "TW", "TWN", "Taiwan"),
    ("TW", "tw", "TW", "TWN", "Taiwan"),

    # Mexico variants
    ("Mexico", "mexico", "MX", "MEX", "Mexico"),
    ("MX", "mx", "MX", "MEX", "Mexico"),

    # Canada variants
    ("Canada", "canada", "CA", "CAN", "Canada"),
    ("CA", "ca", "CA", "CAN", "Canada"),

    # India variants
    ("India", "india", "IN", "IND", "India"),
    ("IN", "in", "IN", "IND", "India"),

    # France variants
    ("France", "france", "FR", "FRA", "France"),
    ("FR", "fr", "FR", "FRA", "France"),

    # Italy variants
    ("Italy", "italy", "IT", "ITA", "Italy"),
    ("IT", "it", "IT", "ITA", "Italy"),

    # Spain variants
    ("Spain", "spain", "ES", "ESP", "Spain"),
    ("ES", "es", "ES", "ESP", "Spain"),

    # Netherlands variants
    ("Netherlands", "netherlands", "NL", "NLD", "Netherlands"),
    ("NL", "nl", "NL", "NLD", "Netherlands"),
    ("Holland", "holland", "NL", "NLD", "Netherlands"),

    # Belgium variants
    ("Belgium", "belgium", "BE", "BEL", "Belgium"),
    ("BE", "be", "BE", "BEL", "Belgium"),

    # Poland variants
    ("Poland", "poland", "PL", "POL", "Poland"),
    ("PL", "pl", "PL", "POL", "Poland"),

    # Thailand variants
    ("Thailand", "thailand", "TH", "THA", "Thailand"),
    ("TH", "th", "TH", "THA", "Thailand"),

    # Indonesia variants
    ("Indonesia", "indonesia", "ID", "IDN", "Indonesia"),
    ("ID", "id", "ID", "IDN", "Indonesia"),

    # Malaysia variants
    ("Malaysia", "malaysia", "MY", "MYS", "Malaysia"),
    ("MY", "my", "MY", "MYS", "Malaysia"),

    # Philippines variants
    ("Philippines", "philippines", "PH", "PHL", "Philippines"),
    ("PH", "ph", "PH", "PHL", "Philippines"),

    # Singapore variants
    ("Singapore", "singapore", "SG", "SGP", "Singapore"),
    ("SG", "sg", "SG", "SGP", "Singapore"),

    # Brazil variants
    ("Brazil", "brazil", "BR", "BRA", "Brazil"),
    ("BR", "br", "BR", "BRA", "Brazil"),

    # Australia variants
    ("Australia", "australia", "AU", "AUS", "Australia"),
    ("AU", "au", "AU", "AUS", "Australia"),
]


# =============================================================================
# Program Country Scope Data
# =============================================================================

# First, we need to create a FENTANYL_COUNTRIES group
FENTANYL_COUNTRIES_GROUP = {
    "group_id": "FENTANYL_COUNTRIES",
    "description": "Countries subject to IEEPA Fentanyl tariffs (China, Hong Kong, Macau)",
    "effective_date": date(2025, 2, 4),
    "members": [
        ("CN", "China", date(2025, 2, 4)),
        ("HK", "Hong Kong", date(2025, 2, 4)),
        ("MO", "Macau", date(2025, 2, 4)),  # Added per broker feedback
    ]
}

# Section 301 applies only to China
SECTION_301_GROUP = {
    "group_id": "SECTION_301_COUNTRIES",
    "description": "Countries subject to Section 301 tariffs (China only)",
    "effective_date": date(2018, 7, 6),
    "members": [
        ("CN", "China", date(2018, 7, 6)),
    ]
}

PROGRAM_COUNTRY_SCOPES = [
    # IEEPA Fentanyl - applies to FENTANYL_COUNTRIES group
    {
        "program_id": "ieepa_fentanyl",
        "group_id": "FENTANYL_COUNTRIES",
        "scope_type": "include",
        "effective_date": date(2025, 2, 4),
        "notes": "IEEPA Fentanyl tariff applies to imports from China, HK, Macau"
    },
    # Section 301 - applies to China only
    {
        "program_id": "section_301",
        "group_id": "SECTION_301_COUNTRIES",
        "scope_type": "include",
        "effective_date": date(2018, 7, 6),
        "notes": "Section 301 tariffs apply to imports from China"
    },
]


# =============================================================================
# Program Suppressions Data
# =============================================================================

PROGRAM_SUPPRESSIONS = [
    # Note: These are placeholder examples. Update with actual rules when known.
    # Section 232 Timber suppresses IEEPA Reciprocal (per broker discussion)
    # {
    #     "suppressor_program_id": "section_232_timber",
    #     "suppressed_program_id": "ieepa_reciprocal",
    #     "suppression_type": "full",
    #     "effective_date": date(2025, 4, 2),
    #     "notes": "232 Timber tariff replaces IEEPA Reciprocal duty"
    # },
    # Section 232 Vehicles suppresses IEEPA Reciprocal
    # {
    #     "suppressor_program_id": "section_232_vehicles",
    #     "suppressed_program_id": "ieepa_reciprocal",
    #     "suppression_type": "full",
    #     "effective_date": date(2025, 4, 3),
    #     "notes": "232 Vehicles tariff replaces IEEPA Reciprocal duty"
    # },
]


# =============================================================================
# Population Functions
# =============================================================================

def init_tables(app, reset=False):
    """Create v6.0 tables in database."""
    with app.app_context():
        if reset:
            print("Dropping v6.0 tariff tables...")
            IngestionRun.__table__.drop(db.engine, checkfirst=True)
            ProgramSuppression.__table__.drop(db.engine, checkfirst=True)
            ProgramCountryScope.__table__.drop(db.engine, checkfirst=True)
            CountryAlias.__table__.drop(db.engine, checkfirst=True)

        print("Creating v6.0 tariff tables...")
        db.create_all()
        print("Tables created successfully.")


def populate_country_aliases(app):
    """Populate country_aliases table."""
    print("\n--- Populating Country Aliases ---")
    with app.app_context():
        count = 0
        for alias_raw, alias_norm, iso2, iso3, canonical in COUNTRY_ALIASES:
            existing = CountryAlias.query.filter_by(alias_norm=alias_norm).first()
            if not existing:
                alias = CountryAlias(
                    alias_raw=alias_raw,
                    alias_norm=alias_norm,
                    iso_alpha2=iso2,
                    iso_alpha3=iso3,
                    canonical_name=canonical
                )
                db.session.add(alias)
                count += 1
                print(f"  + {alias_raw} -> {iso2} ({canonical})")

        db.session.commit()
        print(f"Added {count} country aliases.")
        return count


def populate_fentanyl_countries_group(app):
    """Populate FENTANYL_COUNTRIES group and members."""
    print("\n--- Populating Fentanyl Countries Group ---")
    with app.app_context():
        # Check if group exists
        group = CountryGroup.query.filter_by(group_id=FENTANYL_COUNTRIES_GROUP["group_id"]).first()
        if not group:
            group = CountryGroup(
                group_id=FENTANYL_COUNTRIES_GROUP["group_id"],
                description=FENTANYL_COUNTRIES_GROUP["description"],
                effective_date=FENTANYL_COUNTRIES_GROUP["effective_date"]
            )
            db.session.add(group)
            db.session.flush()  # Get the ID
            print(f"  + Created group: {group.group_id}")

        # Add members
        for iso2, name, eff_date in FENTANYL_COUNTRIES_GROUP["members"]:
            existing = CountryGroupMember.query.filter_by(
                country_code=iso2,
                group_id=FENTANYL_COUNTRIES_GROUP["group_id"]
            ).first()
            if not existing:
                member = CountryGroupMember(
                    country_code=iso2,
                    group_id=FENTANYL_COUNTRIES_GROUP["group_id"],
                    effective_date=eff_date
                )
                db.session.add(member)
                print(f"    + Added {name} ({iso2}) to {FENTANYL_COUNTRIES_GROUP['group_id']}")

        db.session.commit()


def populate_section_301_group(app):
    """Populate SECTION_301_COUNTRIES group and members."""
    print("\n--- Populating Section 301 Countries Group ---")
    with app.app_context():
        # Check if group exists
        group = CountryGroup.query.filter_by(group_id=SECTION_301_GROUP["group_id"]).first()
        if not group:
            group = CountryGroup(
                group_id=SECTION_301_GROUP["group_id"],
                description=SECTION_301_GROUP["description"],
                effective_date=SECTION_301_GROUP["effective_date"]
            )
            db.session.add(group)
            db.session.flush()
            print(f"  + Created group: {group.group_id}")

        # Add members
        for iso2, name, eff_date in SECTION_301_GROUP["members"]:
            existing = CountryGroupMember.query.filter_by(
                country_code=iso2,
                group_id=SECTION_301_GROUP["group_id"]
            ).first()
            if not existing:
                member = CountryGroupMember(
                    country_code=iso2,
                    group_id=SECTION_301_GROUP["group_id"],
                    effective_date=eff_date
                )
                db.session.add(member)
                print(f"    + Added {name} ({iso2}) to {SECTION_301_GROUP['group_id']}")

        db.session.commit()


def populate_program_country_scope(app):
    """Populate program_country_scope table."""
    print("\n--- Populating Program Country Scope ---")
    with app.app_context():
        count = 0
        for scope_data in PROGRAM_COUNTRY_SCOPES:
            # Get the group
            group = CountryGroup.query.filter_by(group_id=scope_data["group_id"]).first()
            if not group:
                print(f"  ! Warning: Group {scope_data['group_id']} not found, skipping")
                continue

            # Check if scope exists
            existing = ProgramCountryScope.query.filter_by(
                program_id=scope_data["program_id"],
                country_group_id=group.id
            ).first()

            if not existing:
                scope = ProgramCountryScope(
                    program_id=scope_data["program_id"],
                    country_group_id=group.id,
                    scope_type=scope_data["scope_type"],
                    effective_date=scope_data["effective_date"],
                    notes=scope_data.get("notes")
                )
                db.session.add(scope)
                count += 1
                print(f"  + {scope_data['program_id']} -> {scope_data['group_id']} ({scope_data['scope_type']})")

        db.session.commit()
        print(f"Added {count} program country scopes.")
        return count


def populate_program_suppressions(app):
    """Populate program_suppressions table."""
    print("\n--- Populating Program Suppressions ---")
    with app.app_context():
        count = 0
        for supp_data in PROGRAM_SUPPRESSIONS:
            existing = ProgramSuppression.query.filter_by(
                suppressor_program_id=supp_data["suppressor_program_id"],
                suppressed_program_id=supp_data["suppressed_program_id"]
            ).first()

            if not existing:
                suppression = ProgramSuppression(
                    suppressor_program_id=supp_data["suppressor_program_id"],
                    suppressed_program_id=supp_data["suppressed_program_id"],
                    suppression_type=supp_data["suppression_type"],
                    effective_date=supp_data["effective_date"],
                    notes=supp_data.get("notes")
                )
                db.session.add(suppression)
                count += 1
                print(f"  + {supp_data['suppressor_program_id']} suppresses {supp_data['suppressed_program_id']}")

        db.session.commit()
        print(f"Added {count} program suppressions.")
        return count


def log_ingestion(app, table_affected, records_added, operator="populate_v6_tables.py"):
    """Log an ingestion run for audit trail."""
    with app.app_context():
        run = IngestionRun(
            ingestion_timestamp=datetime.utcnow(),
            operator=operator,
            table_affected=table_affected,
            records_added=records_added,
            status="success"
        )
        db.session.add(run)
        db.session.commit()
        print(f"  Logged ingestion: {table_affected} ({records_added} records)")


def main():
    parser = argparse.ArgumentParser(description="Populate v6.0 tariff tables")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate tables")
    args = parser.parse_args()

    print("=" * 60)
    print("Tariff Stacker v6.0 - Table Population Script")
    print("=" * 60)

    app = create_app()

    # Initialize tables
    init_tables(app, reset=args.reset)

    # Populate country aliases
    aliases_count = populate_country_aliases(app)
    if aliases_count > 0:
        log_ingestion(app, "country_aliases", aliases_count)

    # Populate country groups for programs
    populate_fentanyl_countries_group(app)
    populate_section_301_group(app)

    # Populate program country scope
    scope_count = populate_program_country_scope(app)
    if scope_count > 0:
        log_ingestion(app, "program_country_scope", scope_count)

    # Populate program suppressions
    supp_count = populate_program_suppressions(app)
    if supp_count > 0:
        log_ingestion(app, "program_suppressions", supp_count)

    print("\n" + "=" * 60)
    print("v6.0 Tables Populated Successfully!")
    print("=" * 60)

    # Summary
    print("\nSummary:")
    print(f"  - Country aliases: {aliases_count}")
    print(f"  - Program country scopes: {scope_count}")
    print(f"  - Program suppressions: {supp_count}")


if __name__ == "__main__":
    main()
