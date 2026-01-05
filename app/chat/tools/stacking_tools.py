"""
Stacking tools for tariff calculation.

These tools implement a data-driven approach to tariff stacking:
- All tariff rules come from database tables (no hardcoded logic)
- Tools query tables populated from government documents
- Supports Section 301, Section 232, IEEPA, and future programs

Tool Call Sequence (per README5.md):
1. get_applicable_programs() - Entry point, finds which programs to check
2. For each program:
   - check_program_inclusion() - Is HTS in program?
   - check_program_exclusion() - Does product qualify for exclusion?
   - check_material_composition() - For 232, what materials?
   - resolve_program_dependencies() - For IEEPA reciprocal, check 232 claims
   - get_program_output() - Get Chapter 99 code and duty rate
3. calculate_duties() - Final calculation with all applicable programs

v7.0 Update (Jan 2026) - Phoebe-Aligned ACE Filing:
- Added disclaim_behavior lookup from TariffProgram table
- Copper (disclaim_behavior='required'): Must file disclaim code in OTHER slices
- Steel/Aluminum (disclaim_behavior='omit'): Omit entirely when not claimed
- Uses HTS-specific claim_codes from section_232_materials table
- 301 codes come from section_301_inclusions, not program_codes
"""

import os
import json
from datetime import date
from typing import Optional

from langchain_core.tools import tool


# ============================================================================
# Helper: Get Flask App Context and Database Models (Lazy Imports)
# ============================================================================

_flask_app = None


def get_flask_app():
    """Get or create Flask app for database access."""
    global _flask_app
    if _flask_app is None:
        from app.web import create_app
        _flask_app = create_app()
    return _flask_app


def get_db():
    """Get the database instance (lazy import to avoid circular imports)."""
    from app.web.db import db
    return db


def get_models():
    """Get tariff table models (lazy import to avoid circular imports)."""
    from app.web.db.models.tariff_tables import (
        TariffProgram,
        Section301Inclusion,
        Section301Exclusion,
        Section232Material,
        ProgramCode,
        DutyRule,
        ProductHistory,
        IeepaAnnexIIExclusion,  # v4.0
        # v5.0: Country-specific rates and audit trail
        SourceDocument,
        CountryGroup,
        CountryGroupMember,
        ProgramRate,
        HtsBaseRate,
        # v6.0: Data-driven country scope, suppressions, audit trail
        CountryAlias,
        ProgramCountryScope,
        ProgramSuppression,
        IngestionRun,
    )
    return {
        "TariffProgram": TariffProgram,
        "Section301Inclusion": Section301Inclusion,
        "Section301Exclusion": Section301Exclusion,
        "Section232Material": Section232Material,
        "ProgramCode": ProgramCode,
        "DutyRule": DutyRule,
        "ProductHistory": ProductHistory,
        "IeepaAnnexIIExclusion": IeepaAnnexIIExclusion,  # v4.0
        # v5.0: Country-specific rates and audit trail
        "SourceDocument": SourceDocument,
        "CountryGroup": CountryGroup,
        "CountryGroupMember": CountryGroupMember,
        "ProgramRate": ProgramRate,
        "HtsBaseRate": HtsBaseRate,
        # v6.0: Data-driven country scope, suppressions, audit trail
        "CountryAlias": CountryAlias,
        "ProgramCountryScope": ProgramCountryScope,
        "ProgramSuppression": ProgramSuppression,
        "IngestionRun": IngestionRun,
    }


# ============================================================================
# v6.0: Country Normalization and Data-Driven Country Scope
# ============================================================================

def normalize_country(country_input: str) -> dict:
    """
    v6.0: Normalize country input to standardized ISO code.

    Performs data-driven lookup in country_aliases table to map various
    country name formats to canonical ISO alpha-2 codes:
    - 'Macau', 'MO', 'Macao' → {'iso_alpha2': 'MO', 'canonical_name': 'Macau'}
    - 'Deutschland', 'Germany', 'DE' → {'iso_alpha2': 'DE', 'canonical_name': 'Germany'}
    - 'China', 'CN', 'PRC' → {'iso_alpha2': 'CN', 'canonical_name': 'China'}

    This is called ONCE at the start of request processing. All downstream
    lookups use iso_alpha2 as the canonical identifier.

    Args:
        country_input: Any country name or code variant

    Returns:
        dict with:
        - iso_alpha2: Standardized 2-letter code
        - iso_alpha3: Optional 3-letter code
        - canonical_name: Standard name
        - original_input: What was provided
        - normalized: True if found in aliases table
    """
    if not country_input:
        return {
            "iso_alpha2": None,
            "canonical_name": None,
            "original_input": country_input,
            "normalized": False
        }

    app = get_flask_app()
    with app.app_context():
        models = get_models()
        CountryAlias = models["CountryAlias"]

        # Normalize input for lookup
        alias_norm = country_input.lower().strip()

        # Query country_aliases table
        alias = CountryAlias.query.filter(
            CountryAlias.alias_norm == alias_norm
        ).first()

        if alias:
            return {
                "iso_alpha2": alias.iso_alpha2,
                "iso_alpha3": alias.iso_alpha3,
                "canonical_name": alias.canonical_name,
                "original_input": country_input,
                "normalized": True
            }

        # Fallback: if not found, return input as-is
        # This maintains backwards compatibility
        return {
            "iso_alpha2": country_input.upper()[:2] if len(country_input) == 2 else None,
            "iso_alpha3": None,
            "canonical_name": country_input,
            "original_input": country_input,
            "normalized": False
        }


def check_program_country_scope(
    program_id: str,
    country_iso2: str,
    import_date: date = None
) -> dict:
    """
    v6.0: Check if a country is in scope for a program.

    Data-driven replacement for hardcoded country checks like:
        if country.lower() in ["china", "cn", "hong kong", "hk"]:

    Uses program_country_scope table to determine applicability:
    - Program can reference a country_group (e.g., 'FENTANYL_COUNTRIES')
    - Or a single iso_alpha2 code for specific countries
    - scope_type 'include' means country IS subject to program
    - scope_type 'exclude' means country is EXEMPT from program

    Args:
        program_id: Program to check (e.g., 'ieepa_fentanyl')
        country_iso2: Normalized ISO alpha-2 code (e.g., 'CN', 'MO')
        import_date: Date for time-bounded lookups

    Returns:
        dict with:
        - in_scope: True if country is subject to this program
        - scope_type: 'include', 'exclude', or 'default'
        - matched_by: 'group', 'country', or 'none'
        - group_id: Which group matched (if any)
    """
    if not program_id or not country_iso2:
        return {
            "in_scope": False,
            "scope_type": "default",
            "matched_by": "none",
            "group_id": None
        }

    app = get_flask_app()
    with app.app_context():
        models = get_models()
        ProgramCountryScope = models["ProgramCountryScope"]
        CountryGroupMember = models["CountryGroupMember"]

        check_date = import_date or date.today()

        # Query program_country_scope for this program
        scopes = ProgramCountryScope.query.filter(
            ProgramCountryScope.program_id == program_id,
            ProgramCountryScope.effective_date <= check_date,
            (ProgramCountryScope.expiration_date.is_(None)) |
            (ProgramCountryScope.expiration_date > check_date)
        ).all()

        for scope in scopes:
            # Check single-country scope
            if scope.iso_alpha2:
                if scope.iso_alpha2.upper() == country_iso2.upper():
                    return {
                        "in_scope": scope.scope_type == 'include',
                        "scope_type": scope.scope_type,
                        "matched_by": "country",
                        "group_id": None
                    }

            # Check group scope
            elif scope.country_group_id:
                # Check if country is a member of this group
                member = CountryGroupMember.query.filter(
                    CountryGroupMember.group_id == scope.country_group.group_id,
                    CountryGroupMember.country_code.ilike(country_iso2),
                    CountryGroupMember.effective_date <= check_date,
                    (CountryGroupMember.expiration_date.is_(None)) |
                    (CountryGroupMember.expiration_date > check_date)
                ).first()

                if member:
                    return {
                        "in_scope": scope.scope_type == 'include',
                        "scope_type": scope.scope_type,
                        "matched_by": "group",
                        "group_id": scope.country_group.group_id
                    }

        # No scope found - default behavior depends on program
        # For backwards compatibility, return False (not in scope)
        return {
            "in_scope": False,
            "scope_type": "default",
            "matched_by": "none",
            "group_id": None
        }


# ============================================================================
# v7.0: Disclaim Behavior Lookup
# ============================================================================

def get_disclaim_behavior(program_id: str) -> str:
    """
    v7.0: Get the disclaim behavior for a program from the TariffProgram table.

    Returns:
        'required' - Copper: Must file disclaim code in other slices when applicable
        'omit' - Steel/Aluminum: Omit entirely when not claimed (no disclaim line)
        'none' - Non-232 programs: No disclaim concept
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        TariffProgram = models["TariffProgram"]

        # Query by program_id (get any entry since disclaim_behavior is same for all countries)
        program = TariffProgram.query.filter_by(program_id=program_id).first()
        if program and hasattr(program, 'disclaim_behavior') and program.disclaim_behavior:
            return program.disclaim_behavior
        return 'none'


# ============================================================================
# v5.0: Country-Specific Rate Lookup Functions
# ============================================================================

def get_country_group(country: str, import_date: date = None) -> str:
    """
    v5.0: Map country to its group for rate lookups.

    Examples:
    - Germany -> 'EU' (15% ceiling rule)
    - UK -> 'UK' (232 exception)
    - China -> 'CN' (full tariffs)
    - Vietnam -> 'default' (standard rates)

    Args:
        country: Country name or ISO code (e.g., 'Germany', 'DE', 'China')
        import_date: Date for time-bounded lookups (defaults to today)

    Returns:
        Group ID: 'EU', 'UK', 'CN', 'USMCA', or 'default'
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        CountryGroupMember = models["CountryGroupMember"]

        check_date = import_date or date.today()

        # Query country_group_members for this country
        member = CountryGroupMember.query.filter(
            CountryGroupMember.country_code == country,
            CountryGroupMember.effective_date <= check_date,
            (CountryGroupMember.expiration_date.is_(None)) |
            (CountryGroupMember.expiration_date > check_date)
        ).first()

        if member:
            return member.group_id

        # Default fallback if country not found
        return "default"


def get_mfn_base_rate(hts_code: str, import_date: date = None) -> float:
    """
    v5.0: Look up MFN Column 1 base rate for an HTS code.

    Required for EU 15% ceiling formula:
    - Reciprocal = max(0, 15% - MFN_base_rate)

    Lookup supports prefix matching:
    - Exact match: '8544.42.9090'
    - 8-digit: '8544.42.90'
    - 6-digit: '8544.42'
    - 4-digit: '8544'

    Args:
        hts_code: HTS code (e.g., '8544.42.9090')
        import_date: Date for time-bounded lookups

    Returns:
        MFN rate as decimal (0.026 = 2.6%). Returns 0.0 if not found.
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        HtsBaseRate = models["HtsBaseRate"]

        check_date = import_date or date.today()
        hts_clean = hts_code.replace(".", "")

        # Try progressively shorter prefixes (longest match wins)
        # 10 digits, 8 digits, 6 digits, 4 digits
        for length in [10, 8, 6, 4]:
            prefix = hts_clean[:length]

            # Re-insert dots for DB lookup (format: 8544.42.9090)
            if length == 10:
                formatted = f"{prefix[:4]}.{prefix[4:6]}.{prefix[6:]}"
            elif length == 8:
                formatted = f"{prefix[:4]}.{prefix[4:6]}.{prefix[6:]}"
            elif length == 6:
                formatted = f"{prefix[:4]}.{prefix[4:]}"
            else:  # 4
                formatted = prefix

            rate = HtsBaseRate.query.filter(
                HtsBaseRate.hts_code == formatted,
                HtsBaseRate.effective_date <= check_date,
                (HtsBaseRate.expiration_date.is_(None)) |
                (HtsBaseRate.expiration_date > check_date)
            ).first()

            if rate:
                return float(rate.column1_rate)

            # Also try without dots
            rate = HtsBaseRate.query.filter(
                HtsBaseRate.hts_code == prefix,
                HtsBaseRate.effective_date <= check_date,
                (HtsBaseRate.expiration_date.is_(None)) |
                (HtsBaseRate.expiration_date > check_date)
            ).first()

            if rate:
                return float(rate.column1_rate)

        # Default to 0 if not found
        return 0.0


def get_rate_for_program(
    program_id: str,
    country: str,
    hts_code: str,
    import_date: date = None
) -> tuple:
    """
    v5.0: Get rate for a program/country combination.

    Supports:
    - Fixed rates: Direct lookup from program_rates table
    - Formula rates: Evaluated at runtime (e.g., EU 15% ceiling)

    Formulas supported:
    - '15pct_minus_mfn': 15% minus MFN base rate (EU ceiling rule)

    Args:
        program_id: Program ID (e.g., 'section_232_steel', 'ieepa_reciprocal')
        country: Country of origin
        hts_code: HTS code (needed for MFN lookup in formulas)
        import_date: Date for time-bounded lookups

    Returns:
        Tuple of (rate: float, rate_source: str)
        - rate: Duty rate as decimal (0.50 = 50%)
        - rate_source: Description of where rate came from
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        ProgramRate = models["ProgramRate"]

        check_date = import_date or date.today()

        # Get country group
        group_id = get_country_group(country, check_date)

        # Try specific group first, then 'default'
        rate_record = None
        for try_group in [group_id, 'default']:
            rate_record = ProgramRate.query.filter(
                ProgramRate.program_id == program_id,
                ProgramRate.group_id == try_group,
                ProgramRate.effective_date <= check_date,
                (ProgramRate.expiration_date.is_(None)) |
                (ProgramRate.expiration_date > check_date)
            ).order_by(ProgramRate.effective_date.desc()).first()

            if rate_record:
                break

        if not rate_record:
            # Fallback to old behavior - look up from ProgramCode
            models = get_models()
            ProgramCode = models["ProgramCode"]
            code = ProgramCode.query.filter_by(program_id=program_id, action="apply").first()
            if code:
                code = ProgramCode.query.filter_by(program_id=program_id).first()
            if code and code.duty_rate:
                return (float(code.duty_rate), "legacy_program_code")
            return (0.0, "no_rate_found")

        # Handle formula-based rates
        if rate_record.rate_type == 'formula':
            if rate_record.rate_formula == '15pct_minus_mfn':
                # EU 15% ceiling rule
                base_mfn = get_mfn_base_rate(hts_code, check_date)
                rate = max(0.0, 0.15 - base_mfn)
                return (rate, f"EU 15% ceiling: 15% - {base_mfn*100:.1f}% MFN = {rate*100:.1f}%")
            else:
                # Unknown formula - return 0 with warning
                return (0.0, f"unknown_formula:{rate_record.rate_formula}")

        # Fixed rate
        if rate_record.rate is not None:
            used_group = rate_record.group_id
            return (float(rate_record.rate), f"fixed_rate_{used_group}")
        else:
            return (0.0, "rate_is_null")


# ============================================================================
# Tool 0: Ensure Materials
# ============================================================================

@tool
def ensure_materials(hts_code: str, product_description: str, known_materials: Optional[str] = None) -> str:
    """
    Determine if material composition is needed for this HTS code.

    Call this early in the stacking process to identify what material
    information we need from the user (if any).

    Args:
        hts_code: The 10-digit HTS code
        product_description: Description of the product
        known_materials: JSON string of known materials {"copper": 0.05, "steel": 0.20}
                        or None if unknown

    Returns:
        JSON with materials_needed flag and suggested questions
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        Section232Material = models["Section232Material"]
        ProductHistory = models["ProductHistory"]

        hts_8digit = hts_code.replace(".", "")[:8]

        # Check if any Section 232 materials apply to this HTS
        materials = Section232Material.query.filter_by(hts_8digit=hts_8digit).all()

        if not materials:
            return json.dumps({
                "materials_needed": False,
                "reason": f"No Section 232 materials apply to HTS {hts_8digit}",
                "materials": known_materials or {}
            })

        # Materials are needed - what do we know?
        applicable_materials = [m.material for m in materials]

        if known_materials:
            try:
                parsed = json.loads(known_materials) if isinstance(known_materials, str) else known_materials

                # FIX: If user explicitly passed empty dict {}, they're saying "no 232 metals to claim"
                # This is a valid answer - proceed without 232 claims as a full product
                if isinstance(parsed, dict) and len(parsed) == 0:
                    return json.dumps({
                        "materials_needed": False,
                        "reason": "User indicated no Section 232 materials to claim",
                        "materials": {},
                        "explicit_no_claim": True
                    })

                # Check if we have info for all applicable materials
                missing = [m for m in applicable_materials if m not in parsed]
                if not missing:
                    return json.dumps({
                        "materials_needed": False,
                        "reason": "All material composition known",
                        "materials": parsed
                    })
                return json.dumps({
                    "materials_needed": True,
                    "reason": f"Missing composition for: {', '.join(missing)}",
                    "applicable_materials": applicable_materials,
                    "known_materials": parsed,
                    "missing_materials": missing,
                    "suggested_question": f"What percentage of this product is {', '.join(missing)}?"
                })
            except json.JSONDecodeError:
                pass

        # Check product history for similar products
        history = ProductHistory.query.filter_by(hts_code=hts_code).order_by(
            ProductHistory.timestamp.desc()
        ).first()

        if history and history.components and history.user_confirmed:
            return json.dumps({
                "materials_needed": False,
                "reason": "Found composition in product history",
                "materials": history.components,
                "from_history": True
            })

        return json.dumps({
            "materials_needed": True,
            "applicable_materials": applicable_materials,
            "suggested_question": f"What is the material composition of this product? Specifically: {', '.join(applicable_materials)} (as percentages)",
            "from_history": False
        })


# ============================================================================
# Tool 1: Get Applicable Programs
# ============================================================================

@tool
def get_applicable_programs(country: str, hts_code: str, import_date: Optional[str] = None) -> str:
    """
    Query tariff_programs table to find what programs might apply.

    This is the ENTRY POINT for tariff stacking - call this first to get
    the list of programs to check, ordered by filing_sequence.

    Args:
        country: Country of origin (e.g., "China", "Mexico")
        hts_code: The 10-digit HTS code (e.g., "8544.42.9090")
        import_date: Date of import in YYYY-MM-DD format (defaults to today)

    Returns:
        JSON list of applicable programs with check_type, condition_handler, etc.
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        TariffProgram = models["TariffProgram"]

        check_date = date.fromisoformat(import_date) if import_date else date.today()

        # Query programs that apply to this country or ALL countries
        programs = TariffProgram.query.filter(
            (TariffProgram.country == country) | (TariffProgram.country == "ALL"),
            TariffProgram.effective_date <= check_date,
            (TariffProgram.expiration_date.is_(None)) | (TariffProgram.expiration_date > check_date)
        ).order_by(TariffProgram.filing_sequence).all()

        if not programs:
            return json.dumps({
                "programs": [],
                "message": f"No tariff programs found for {country}"
            })

        result = []
        for p in programs:
            result.append({
                "program_id": p.program_id,
                "program_name": p.program_name,
                "country": p.country,
                "check_type": p.check_type,
                "condition_handler": p.condition_handler,
                "condition_param": p.condition_param,
                "inclusion_table": p.inclusion_table,
                "exclusion_table": p.exclusion_table,
                "filing_sequence": p.filing_sequence,
                # v4.0: Include calculation_sequence for duty math order
                "calculation_sequence": p.calculation_sequence or p.filing_sequence,
                "source_document": p.source_document
            })

        return json.dumps({
            "programs": result,
            "total": len(result),
            "country": country,
            "hts_code": hts_code,
            "import_date": check_date.isoformat()
        })


# ============================================================================
# Tool 2: Check Program Inclusion
# ============================================================================

@tool
def check_program_inclusion(program_id: str, hts_code: str) -> str:
    """
    Check if an HTS code is included in a specific tariff program.

    This is a generic checker that works for ANY program by looking up
    the appropriate inclusion table.

    Args:
        program_id: The program to check (e.g., "section_301", "section_232_copper")
        hts_code: The 10-digit HTS code

    Returns:
        JSON with inclusion result, Chapter 99 code, duty rate, and source info
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        TariffProgram = models["TariffProgram"]
        Section301Inclusion = models["Section301Inclusion"]
        Section232Material = models["Section232Material"]

        hts_8digit = hts_code.replace(".", "")[:8]

        # Get program info
        program = TariffProgram.query.filter_by(program_id=program_id).first()
        if not program:
            return json.dumps({
                "included": False,
                "error": f"Unknown program: {program_id}"
            })

        # Programs with check_type="always" don't need inclusion lookup
        if program.check_type == "always":
            return json.dumps({
                "included": True,
                "program_id": program_id,
                "check_type": "always",
                "reason": f"{program.program_name} applies to all qualifying imports"
            })

        # Look up in the appropriate inclusion table
        if program.inclusion_table == "section_301_inclusions":
            inclusion = Section301Inclusion.query.filter_by(hts_8digit=hts_8digit).first()
            if inclusion:
                return json.dumps({
                    "included": True,
                    "program_id": program_id,
                    "hts_8digit": hts_8digit,
                    "list_name": inclusion.list_name,
                    "chapter_99_code": inclusion.chapter_99_code,
                    "duty_rate": float(inclusion.duty_rate),
                    "source_doc": inclusion.source_doc,
                    "source_page": inclusion.source_page
                })
        elif program.inclusion_table == "section_232_materials":
            # For 232, we check if HTS is in the table (material-specific check comes later)
            material = program.condition_param  # e.g., "copper", "steel", "aluminum"
            inclusion = Section232Material.query.filter_by(
                hts_8digit=hts_8digit,
                material=material
            ).first()
            if inclusion:
                return json.dumps({
                    "included": True,
                    "program_id": program_id,
                    "hts_8digit": hts_8digit,
                    "material": material,
                    "claim_code": inclusion.claim_code,
                    "disclaim_code": inclusion.disclaim_code,
                    "duty_rate": float(inclusion.duty_rate),
                    "source_doc": inclusion.source_doc
                })

        return json.dumps({
            "included": False,
            "program_id": program_id,
            "hts_8digit": hts_8digit,
            "reason": f"HTS {hts_8digit} not found in {program.inclusion_table}"
        })


# ============================================================================
# Tool 3: Check Program Exclusion
# ============================================================================

@tool
def check_program_exclusion(program_id: str, hts_code: str, product_description: str, import_date: Optional[str] = None) -> str:
    """
    Check if a product qualifies for an exclusion from a tariff program.

    Uses semantic matching to compare product description against
    exclusion descriptions in the database.

    Args:
        program_id: The program to check exclusions for
        hts_code: The 10-digit HTS code
        product_description: Description of the product for semantic matching
        import_date: Date of import (to check if exclusion is still valid)

    Returns:
        JSON with exclusion result, match confidence, and source info
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        TariffProgram = models["TariffProgram"]
        Section301Exclusion = models["Section301Exclusion"]

        hts_8digit = hts_code.replace(".", "")[:8]
        check_date = date.fromisoformat(import_date) if import_date else date.today()

        # Get program info
        program = TariffProgram.query.filter_by(program_id=program_id).first()
        if not program or not program.exclusion_table:
            return json.dumps({
                "excluded": False,
                "reason": f"No exclusion table for program {program_id}"
            })

        # Look up potential exclusions
        if program.exclusion_table == "section_301_exclusions":
            exclusions = Section301Exclusion.query.filter_by(hts_8digit=hts_8digit).all()

            active_exclusions = [e for e in exclusions if e.is_active(check_date)]

            if not active_exclusions:
                return json.dumps({
                    "excluded": False,
                    "program_id": program_id,
                    "hts_8digit": hts_8digit,
                    "reason": "No active exclusions for this HTS code",
                    "expired_exclusions": len(exclusions) - len(active_exclusions)
                })

            # Check each exclusion for semantic match
            # For MVP, we do simple substring matching
            # In production, use LLM or embeddings for fuzzy matching
            best_match = None
            best_confidence = 0.0

            product_lower = product_description.lower()
            for exc in active_exclusions:
                exc_lower = exc.description.lower()

                # Simple keyword matching (replace with LLM semantic match in production)
                common_words = set(product_lower.split()) & set(exc_lower.split())
                confidence = len(common_words) / max(len(exc_lower.split()), 1)

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = exc

            if best_match and best_confidence > 0.3:  # Threshold for match
                return json.dumps({
                    "excluded": True,
                    "program_id": program_id,
                    "hts_8digit": hts_8digit,
                    "exclusion_id": best_match.id,
                    "exclusion_description": best_match.description,
                    "match_confidence": round(best_confidence, 2),
                    "valid_until": best_match.extended_to.isoformat() if best_match.extended_to else best_match.original_expiry.isoformat() if best_match.original_expiry else None,
                    "source_doc": best_match.exclusion_doc,
                    "source_page": best_match.source_page,
                    "note": "Product description matches exclusion criteria"
                })

            return json.dumps({
                "excluded": False,
                "program_id": program_id,
                "hts_8digit": hts_8digit,
                "reason": "Product does not match any active exclusion descriptions",
                "active_exclusions_checked": len(active_exclusions),
                "best_confidence": round(best_confidence, 2) if best_confidence > 0 else None
            })

        return json.dumps({
            "excluded": False,
            "reason": f"Unknown exclusion table: {program.exclusion_table}"
        })


# ============================================================================
# Phase 6: Helper Function for Line Splitting
# ============================================================================

def should_split_lines(total_value: float, content_value: float,
                       split_policy: str, split_threshold_pct: float = None) -> bool:
    """
    Determines if filing lines should be split based on DB parameters.

    This is a GENERIC function - doesn't know about copper/steel/aluminum.
    All specifics come from the DB row for that material.

    If CBP changes the rule in future, we update DB data, not this code.

    Args:
        total_value: Total product value
        content_value: Value of the material content
        split_policy: 'never', 'if_any_content', 'if_above_threshold'
        split_threshold_pct: Threshold percentage (only for 'if_above_threshold')

    Returns:
        True if lines should be split, False otherwise
    """
    if content_value is None or content_value <= 0:
        return False
    if content_value >= total_value:
        return False  # All material, no split needed

    if split_policy == "never":
        return False
    elif split_policy == "if_any_content":
        return True  # Current US 232 behavior: split if ANY content present
    elif split_policy == "if_above_threshold":
        return (content_value / total_value) >= (split_threshold_pct or 0)

    return False  # Default: no split


# ============================================================================
# Tool 4: Check Material Composition (Phase 6 Updated)
# ============================================================================

@tool
def check_material_composition(hts_code: str, materials: str, product_value: float = None) -> str:
    """
    Check Section 232 material requirements for an HTS code.

    Phase 6 Update (Dec 2025):
    - Now accepts material VALUES in addition to percentages
    - Generates line splitting info for content-value-based duties
    - Returns content_value, non_content_value for split filing lines

    Args:
        hts_code: The 10-digit HTS code
        materials: JSON string of material composition. Supports two formats:
            - Simple: {"copper": 0.05, "steel": 0.20, "aluminum": 0.72}
            - With values: {"copper": {"percentage": 0.05, "value": 500.00}, ...}
        product_value: Total product value in USD (required for content-value calculations)

    Returns:
        JSON with claim/disclaim decision, line split info, and content values
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        Section232Material = models["Section232Material"]

        hts_8digit = hts_code.replace(".", "")[:8]

        try:
            composition = json.loads(materials) if isinstance(materials, str) else materials
        except json.JSONDecodeError:
            return json.dumps({
                "error": "Invalid materials JSON format",
                "expected": '{"copper": 0.05, "steel": 0.20, "aluminum": 0.72} or {"copper": {"percentage": 0.05, "value": 500.00}}'
            })

        # Get all 232 materials that apply to this HTS
        applicable = Section232Material.query.filter_by(hts_8digit=hts_8digit).all()

        if not applicable:
            return json.dumps({
                "has_232_materials": False,
                "hts_8digit": hts_8digit,
                "reason": "No Section 232 materials apply to this HTS code"
            })

        results = []
        any_claims = False

        for mat in applicable:
            material_name = mat.material
            mat_data = composition.get(material_name, {})

            # Handle both simple (float) and complex (dict) material formats
            if isinstance(mat_data, dict):
                percentage = mat_data.get("percentage", 0)
                content_value = mat_data.get("value")
                mass_kg = mat_data.get("mass_kg")
                value_source = "user_provided" if content_value is not None else "estimated"
            else:
                # Simple format: just percentage
                percentage = mat_data if isinstance(mat_data, (int, float)) else 0
                content_value = None
                mass_kg = None
                value_source = "estimated"

            # If content_value not provided but we have product_value and percentage, estimate it
            if content_value is None and product_value and percentage > 0:
                content_value = product_value * percentage
                value_source = "estimated_from_percentage"

            # Get split policy from DB (Phase 6)
            split_policy = mat.split_policy or "if_any_content"
            split_threshold = float(mat.split_threshold_pct) if mat.split_threshold_pct else None
            content_basis = mat.content_basis or "value"

            # Determine if we should split lines
            do_split = should_split_lines(
                total_value=product_value or 0,
                content_value=content_value or 0,
                split_policy=split_policy,
                split_threshold_pct=split_threshold
            )

            # For Phase 6 content-value basis:
            # - If content_value > 0: claim (duty on content value)
            # - If content_value == 0 or None: disclaim (no duty)
            threshold = float(mat.threshold_percent) if mat.threshold_percent else 0

            if content_value and content_value > 0:
                action = "claim"
                code = mat.claim_code
                any_claims = True
                non_content_value = (product_value or 0) - content_value if product_value else None
            else:
                action = "disclaim"
                code = mat.disclaim_code
                non_content_value = product_value if product_value else None

            results.append({
                "material": material_name,
                "percentage": percentage,
                "threshold": threshold,
                "action": action,
                "chapter_99_code": code,
                "duty_rate": float(mat.duty_rate) if action == "claim" else 0,
                "applies_to": "partial" if action == "claim" else "none",
                "source_doc": mat.source_doc,
                # Phase 6: Content-value fields
                "content_value": content_value,
                "non_content_value": non_content_value,
                "mass_kg": mass_kg,
                "value_source": value_source,
                "content_basis": content_basis,
                "split_lines": do_split,
                "split_policy": split_policy,
                "claim_code": mat.claim_code,
                "disclaim_code": mat.disclaim_code,
            })

        return json.dumps({
            "has_232_materials": True,
            "hts_8digit": hts_8digit,
            "composition": composition,
            "materials": results,
            "any_claims": any_claims,
            "product_value": product_value
        })


# ============================================================================
# Tool 5: Resolve Program Dependencies
# ============================================================================

@tool
def resolve_program_dependencies(program_id: str, previous_results: str) -> str:
    """
    Resolve conditional program logic based on other program results.

    For programs with condition_handler='handle_dependency', this determines
    the appropriate action based on results from dependent programs.

    Example: IEEPA Reciprocal depends on Section 232 claims.
    - If any 232 claims exist -> action = "paid"
    - Else -> action = "disclaim"

    Args:
        program_id: The program to resolve (e.g., "ieepa_reciprocal")
        previous_results: JSON string with results from previous programs

    Returns:
        JSON with resolved action and Chapter 99 code
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        TariffProgram = models["TariffProgram"]
        ProgramCode = models["ProgramCode"]

        program = TariffProgram.query.filter_by(program_id=program_id).first()
        if not program:
            return json.dumps({
                "error": f"Unknown program: {program_id}"
            })

        if program.condition_handler != "handle_dependency":
            return json.dumps({
                "error": f"Program {program_id} does not use dependency handling",
                "condition_handler": program.condition_handler
            })

        try:
            results = json.loads(previous_results) if isinstance(previous_results, str) else previous_results
        except json.JSONDecodeError:
            return json.dumps({
                "error": "Invalid previous_results JSON format"
            })

        dependency = program.condition_param  # e.g., "section_232"

        # Check if any 232 programs had claims
        has_232_claims = False
        if dependency == "section_232":
            # Look for any section_232_* programs with claims
            for prog_id, prog_result in results.items():
                if prog_id.startswith("section_232_"):
                    if isinstance(prog_result, dict) and prog_result.get("any_claims"):
                        has_232_claims = True
                        break

        # Determine action based on dependency results
        if has_232_claims:
            action = "paid"
            reason = "Section 232 claims exist, must pay IEEPA reciprocal"
        else:
            action = "disclaim"
            reason = "No Section 232 claims, disclaim IEEPA reciprocal"

        # Get the output code for this action
        code = ProgramCode.query.filter_by(program_id=program_id, action=action).first()

        if not code:
            return json.dumps({
                "error": f"No output code found for {program_id}/{action}"
            })

        return json.dumps({
            "program_id": program_id,
            "dependency": dependency,
            "dependency_met": has_232_claims,
            "action": action,
            "chapter_99_code": code.chapter_99_code,
            "duty_rate": float(code.duty_rate) if code.duty_rate else 0,
            "reason": reason,
            "source_doc": code.source_doc
        })


# ============================================================================
# Tool 6: Get Program Output (v4.0 Updated)
# ============================================================================

@tool
def get_program_output(program_id: str, action: str, variant: Optional[str] = None, slice_type: str = "all") -> str:
    """
    Look up the output codes for a program decision.

    After determining what action to take (apply/claim/disclaim/paid/exempt),
    use this to get the specific Chapter 99 code and duty rate.

    v4.0 Update: Added variant and slice_type for precise code lookup.
    - variant: 'taxable', 'annex_ii_exempt', 'metal_exempt', 'us_content_exempt'
    - slice_type: 'all', 'non_metal', 'copper_slice', 'steel_slice', 'aluminum_slice'

    Args:
        program_id: The program (e.g., "section_301", "section_232_copper")
        action: The action determined (e.g., "apply", "claim", "disclaim", "paid", "exempt")
        variant: Optional variant for programs with multiple outcomes (e.g., IEEPA Reciprocal)
        slice_type: Slice type for per-slice lookups (default "all")

    Returns:
        JSON with chapter_99_code, duty_rate, applies_to, variant, slice_type, and source info
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        ProgramCode = models["ProgramCode"]

        # v4.0: Query with variant and slice_type
        query = ProgramCode.query.filter_by(program_id=program_id, action=action)

        # Add variant filter if provided
        if variant:
            query = query.filter_by(variant=variant)
        else:
            query = query.filter(ProgramCode.variant.is_(None))

        # Add slice_type filter
        query = query.filter_by(slice_type=slice_type)

        code = query.first()

        # Fallback: Try with slice_type='all' if specific slice not found
        if not code and slice_type != "all":
            query = ProgramCode.query.filter_by(program_id=program_id, action=action)
            if variant:
                query = query.filter_by(variant=variant)
            else:
                query = query.filter(ProgramCode.variant.is_(None))
            query = query.filter_by(slice_type="all")
            code = query.first()

        if not code:
            return json.dumps({
                "found": False,
                "program_id": program_id,
                "action": action,
                "variant": variant,
                "slice_type": slice_type,
                "error": f"No output code found for {program_id}/{action}/{variant}/{slice_type}"
            })

        return json.dumps({
            "found": True,
            "program_id": program_id,
            "action": action,
            "variant": code.variant,
            "slice_type": code.slice_type,
            "chapter_99_code": code.chapter_99_code,
            "duty_rate": float(code.duty_rate) if code.duty_rate else 0,
            "applies_to": code.applies_to,
            "source_doc": code.source_doc
        })


# ============================================================================
# Tool 7: Calculate Duties (Phase 6.5 Updated - IEEPA Unstacking)
# ============================================================================

@tool
def calculate_duties(
    filing_lines: str,
    product_value: float,
    materials: Optional[str] = None,
    country: Optional[str] = None,
    hts_code: Optional[str] = None,
    import_date: Optional[str] = None
) -> str:
    """
    Calculate total duties based on all applicable programs.

    Phase 6 Update (Dec 2025):
    - Supports content-value-based duties (base_on='content_value')
    - Calculates duty on material $ value instead of percentage
    - Applies fallback to full_value if content value unknown
    - Generates split filing lines for 232 materials

    Phase 6.5 Update (Dec 2025) - IEEPA Unstacking:
    - Tracks remaining_value after 232 content deductions
    - 232 programs with base_effect='subtract_from_remaining' reduce the IEEPA base
    - IEEPA Reciprocal with base_on='remaining_value' uses the reduced base
    - This implements CBP rule: "Content subject to 232 is NOT subject to Reciprocal IEEPA"

    v5.0 Update (Dec 2025) - Country-Specific Rates:
    - Uses get_rate_for_program() to get country-specific rates
    - Supports EU 15% ceiling rule (formula: 15% - MFN base rate)
    - Supports UK 232 exception (25% instead of 50% for steel/aluminum)
    - If country/hts_code not provided, falls back to rate from filing_lines

    Args:
        filing_lines: JSON string with list of filing lines from program decisions
        product_value: The declared value of the product in USD
        materials: JSON string of material composition. Supports:
            - Simple: {"copper": 0.05, "steel": 0.20}
            - With values: {"copper": {"percentage": 0.05, "value": 500.00}, ...}
        country: v5.0 - Country of origin for rate lookup (optional)
        hts_code: v5.0 - HTS code for MFN lookup in formulas (optional)
        import_date: v5.0 - Import date (YYYY-MM-DD) for time-bounded lookups

    Returns:
        JSON with total duty calculation breakdown, including base_value, value_source,
        rate_source (v5.0), and remaining_value tracking for IEEPA unstacking
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        DutyRule = models["DutyRule"]

        try:
            lines = json.loads(filing_lines) if isinstance(filing_lines, str) else filing_lines
            composition = json.loads(materials) if materials and isinstance(materials, str) else (materials or {})
        except json.JSONDecodeError as e:
            return json.dumps({
                "error": f"Invalid JSON: {str(e)}"
            })

        # v5.0: Parse import_date for rate lookups
        check_date = date.fromisoformat(import_date) if import_date else date.today()

        # v5.0: Get country group for audit trail
        country_group = get_country_group(country, check_date) if country else None

        total_duty_percent = 0.0
        total_duty_amount = 0.0
        breakdown = []
        flags = []
        rate_sources = {}  # v5.0: Track where each rate came from

        # Phase 6.5: Track remaining_value for IEEPA unstacking
        # Start with full product value, subtract 232 content values as we process them
        remaining_value = product_value
        content_deductions = {}  # Track what was deducted for audit trail
        processed_materials = set()  # Prevent double-subtraction for split lines

        for line in lines:
            program_id = line.get("program_id")
            action = line.get("action")
            duty_rate = line.get("duty_rate", 0)
            material = line.get("material")

            # v5.0: Get country-specific rate if country and hts_code provided
            rate_source = None
            if country and hts_code and action not in ["disclaim", "skip"]:
                dynamic_rate, rate_source = get_rate_for_program(
                    program_id, country, hts_code, check_date
                )
                # Use dynamic rate if found (overrides rate from filing_lines)
                if rate_source and rate_source != "no_rate_found":
                    duty_rate = dynamic_rate
                    rate_sources[program_id] = rate_source

            # Get duty rule for calculation type
            rule = DutyRule.query.filter_by(program_id=program_id).first()
            if not rule:
                calculation_type = "additive"
                base_on = "product_value"
                content_key = None
                fallback_base_on = None
                base_effect = None
            else:
                calculation_type = rule.calculation_type
                base_on = rule.base_on
                content_key = rule.content_key
                fallback_base_on = rule.fallback_base_on
                base_effect = rule.base_effect  # Phase 6.5: 'subtract_from_remaining' for 232

            # Initialize values for Phase 6 tracking
            base_value = product_value
            value_source = None
            material_percent = None
            content_value = None  # Track for potential deduction

            # Calculate duty based on rule
            if action in ["disclaim", "skip"]:
                duty_amount = 0.0
                base_value = 0

            elif base_on == "product_value":
                # Standard: duty on full product value
                duty_amount = product_value * duty_rate
                base_value = product_value

            elif base_on == "remaining_value":
                # Phase 6.5: IEEPA Reciprocal uses remaining_value (after 232 deductions)
                # v4.0: Use line_value if provided (from calculate_duties_node)
                line_value_from_line = line.get("line_value")
                if line_value_from_line is not None and line_value_from_line > 0:
                    # line_value is already the non_metal slice value
                    duty_amount = line_value_from_line * duty_rate
                    base_value = line_value_from_line
                    value_source = "from_entry_slice"
                else:
                    # Fall back to calculated remaining_value
                    duty_amount = remaining_value * duty_rate
                    base_value = remaining_value
                    value_source = "remaining_after_232"

            elif base_on == "content_value" and content_key:
                # Phase 6: Content-value-based duty (Section 232)
                #
                # v4.0: Check for line_value first (passed from calculate_duties_node)
                # This is the slice value for this specific 232 material
                line_value_from_line = line.get("line_value")
                if line_value_from_line is not None and line_value_from_line > 0:
                    content_value = line_value_from_line
                    material_percent = content_value / product_value if product_value > 0 else 0
                    value_source = "from_entry_slice"
                else:
                    # Fall back to looking up from materials composition
                    mat_data = composition.get(content_key, {})

                    # Get content value from material data
                    # Support three formats:
                    #   1. Dict with value: {"copper": {"percentage": 0.30, "value": 3000}}
                    #   2. Percentage (<=1.0): {"copper": 0.30} means 30%
                    #   3. Dollar value (>1.0): {"copper": 3000} means $3000
                    if isinstance(mat_data, dict):
                        content_value = mat_data.get("value")
                        material_percent = mat_data.get("percentage", 0)
                        value_source = mat_data.get("value_source", "user_provided" if content_value else "estimated")
                    elif isinstance(mat_data, (int, float)):
                        if mat_data <= 1.0:
                            # Simple format - percentage (0.30 = 30%)
                            material_percent = mat_data
                            content_value = None
                            value_source = "estimated"
                        else:
                            # v4.0: Dollar value directly (3000 = $3000)
                            material_percent = None
                            content_value = mat_data
                            value_source = "user_provided_value"
                    else:
                        material_percent = 0
                        content_value = None
                        value_source = "unknown"

                    # If content_value not provided, estimate from percentage
                    if content_value is None and material_percent and material_percent > 0:
                        content_value = product_value * material_percent
                        value_source = "estimated_from_percentage"

                # Apply fallback if content_value still unknown
                if content_value is None or content_value <= 0:
                    if fallback_base_on == "full_value":
                        # Penalty case: charge on full product value
                        content_value = product_value
                        value_source = "fallback"
                        flags.append(f"fallback_applied_for_{content_key}")

                if content_value and content_value > 0:
                    duty_amount = content_value * duty_rate
                    base_value = content_value
                else:
                    duty_amount = 0.0
                    base_value = 0

            elif base_on == "material_percentage" and material:
                # Legacy: percentage-based (for backwards compatibility)
                mat_data = composition.get(material, {})
                if isinstance(mat_data, dict):
                    material_percent = mat_data.get("percentage", 0)
                else:
                    material_percent = mat_data if isinstance(mat_data, (int, float)) else 0
                duty_amount = product_value * material_percent * duty_rate
                base_value = product_value * material_percent
                value_source = "percentage_based"

            else:
                # Default fallback
                duty_amount = product_value * duty_rate
                base_value = product_value

            # Phase 6.5: Update remaining_value for IEEPA unstacking
            # If this is a 232 program with base_effect='subtract_from_remaining',
            # subtract the content_value from remaining_value for subsequent programs
            #
            # IMPORTANT: Only subtract on material_content lines, not non_material_content lines!
            # With line splitting, we have 2 lines per material:
            #   - non_material_content (disclaim, 0% duty) - DON'T subtract
            #   - material_content (claim, 50%/25% duty) - DO subtract
            # We also track processed_materials to prevent any double-subtraction.
            split_type = line.get("split_type")
            material_key = content_key or material or program_id

            should_subtract = (
                base_effect == "subtract_from_remaining"
                and content_value
                and content_value > 0
                and material_key not in processed_materials
                # Only subtract on material_content lines (or non-split lines where split_type is None)
                and split_type in (None, "material_content")
            )

            if should_subtract:
                remaining_value -= content_value
                content_deductions[material_key] = content_value
                processed_materials.add(material_key)
                # Ensure remaining_value doesn't go negative
                remaining_value = max(0, remaining_value)

            breakdown.append({
                "program_id": program_id,
                "chapter_99_code": line.get("chapter_99_code"),
                "action": action,
                "duty_rate": duty_rate,
                "duty_amount": round(duty_amount, 2),
                "calculation": f"{calculation_type} on {base_on}",
                "material": material,
                "material_percent": material_percent,
                # Phase 6: Content-value fields
                "base_value": round(base_value, 2) if base_value else None,
                "value_source": value_source,
                # Phase 6.5: Track remaining_value at each step
                "remaining_value_after": round(remaining_value, 2) if base_effect == "subtract_from_remaining" else None,
                # v5.0: Rate source audit trail
                "rate_source": rate_source,
            })

            if action not in ["disclaim", "skip"]:
                total_duty_amount += duty_amount
                if base_on == "product_value":
                    total_duty_percent += duty_rate

        # Build result with Phase 6.5 unstacking info
        result = {
            "product_value": product_value,
            "total_duty_percent": round(total_duty_percent, 4),
            "total_duty_amount": round(total_duty_amount, 2),
            "effective_rate": round(total_duty_amount / product_value, 4) if product_value > 0 else 0,
            "filing_lines": len(breakdown),
            "breakdown": breakdown,
            "flags": flags,  # Phase 6: Include warning flags
        }

        # Phase 6.5: Include unstacking audit trail
        if content_deductions:
            result["unstacking"] = {
                "initial_value": product_value,
                "content_deductions": content_deductions,
                "remaining_value": round(remaining_value, 2),
                "note": "IEEPA Reciprocal calculated on remaining_value after 232 content deductions"
            }

        # v5.0: Include country-specific rate metadata
        if country or hts_code:
            mfn_rate = get_mfn_base_rate(hts_code, check_date) if hts_code else None
            result["v5_metadata"] = {
                "country": country,
                "country_group": country_group,
                "hts_code": hts_code,
                "mfn_base_rate": mfn_rate,
                "rate_sources": rate_sources,
                "rates_as_of": check_date.isoformat(),
            }

        return json.dumps(result)


# ============================================================================
# Tool 8: Lookup Product History
# ============================================================================

@tool
def lookup_product_history(hts_code: str, product_description: str) -> str:
    """
    Check if we've handled similar products before.

    Looks up previous classifications to:
    1. Suggest material composition if we've seen this product
    2. Provide historical decisions as reference
    3. Reduce user questions by using confirmed data

    Args:
        hts_code: The 10-digit HTS code
        product_description: Description of the product

    Returns:
        JSON with historical data and suggestions
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        ProductHistory = models["ProductHistory"]

        # Look up by exact HTS code
        history = ProductHistory.query.filter_by(hts_code=hts_code).order_by(
            ProductHistory.timestamp.desc()
        ).limit(5).all()

        if not history:
            return json.dumps({
                "found": False,
                "hts_code": hts_code,
                "message": "No history found for this HTS code",
                "suggestion": "Will need to ask user for material composition if 232 applies"
            })

        # Find best match by product description (simple substring for MVP)
        best_match = None
        best_score = 0

        product_lower = product_description.lower()
        for h in history:
            if h.product_desc:
                desc_lower = h.product_desc.lower()
                # Simple matching score
                common = len(set(product_lower.split()) & set(desc_lower.split()))
                if common > best_score:
                    best_score = common
                    best_match = h

        if best_match and best_match.user_confirmed:
            return json.dumps({
                "found": True,
                "hts_code": hts_code,
                "match_type": "exact_hts_with_description_match",
                "match_score": best_score,
                "previous_composition": best_match.components,
                "previous_decisions": best_match.decisions,
                "user_confirmed": best_match.user_confirmed,
                "timestamp": best_match.timestamp.isoformat() if best_match.timestamp else None,
                "suggestion": "Can use historical composition, verify with user if different product"
            })

        # Return most recent entry
        recent = history[0]
        return json.dumps({
            "found": True,
            "hts_code": hts_code,
            "match_type": "exact_hts_only",
            "previous_composition": recent.components,
            "previous_decisions": recent.decisions,
            "user_confirmed": recent.user_confirmed,
            "timestamp": recent.timestamp.isoformat() if recent.timestamp else None,
            "suggestion": "Historical data available but should verify with user"
        })


# ============================================================================
# Tool 9: Save Product Decision (for learning)
# ============================================================================

@tool
def save_product_decision(
    hts_code: str,
    country: str,
    product_description: str,
    materials: str,
    filing_lines: str,
    user_confirmed: bool = False
) -> str:
    """
    Save a product stacking decision to history for future reference.

    Call this after completing a stacking calculation to build up
    the knowledge base for similar products.

    Args:
        hts_code: The 10-digit HTS code
        country: Country of origin
        product_description: Description of the product
        materials: JSON string of material composition
        filing_lines: JSON string of final filing lines
        user_confirmed: Whether user verified the composition

    Returns:
        JSON confirming save
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        ProductHistory = models["ProductHistory"]
        db = get_db()

        try:
            composition = json.loads(materials) if isinstance(materials, str) else materials
            decisions = json.loads(filing_lines) if isinstance(filing_lines, str) else filing_lines
        except json.JSONDecodeError as e:
            return json.dumps({
                "saved": False,
                "error": f"Invalid JSON: {str(e)}"
            })

        history = ProductHistory(
            hts_code=hts_code,
            country=country,
            product_desc=product_description,
            components=composition,
            decisions=decisions,
            user_confirmed=user_confirmed
        )
        db.session.add(history)
        db.session.commit()

        return json.dumps({
            "saved": True,
            "id": history.id,
            "hts_code": hts_code,
            "user_confirmed": user_confirmed
        })


# ============================================================================
# v4.0 Tools: Entry Slices and Variant Resolution
# ============================================================================

@tool
def plan_entry_slices(hts_code: str, product_value: float, materials: str, applicable_programs: str) -> str:
    """
    v4.0: Determine how many ACE entries (slices) to create for one product.

    When a product has 232 metal content, it must be split into multiple
    ACE entries:
    - 1 non_metal slice (value - all 232 metal values)
    - 1 slice per 232 metal with value > 0

    If no 232 materials apply, returns a single "full_product" slice.

    Args:
        hts_code: The 10-digit HTS code
        product_value: Total product value in USD
        materials: JSON string of material values {"copper": 3000, "steel": 1000, "aluminum": 1000}
        applicable_programs: JSON string of applicable programs from get_applicable_programs()

    Returns:
        JSON with list of entry slices, each with entry_id, slice_type, value, materials
    """
    try:
        composition = json.loads(materials) if isinstance(materials, str) else materials
        programs_data = json.loads(applicable_programs) if isinstance(applicable_programs, str) else applicable_programs
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": f"Invalid JSON: {str(e)}"
        })

    programs = programs_data.get("programs", []) if isinstance(programs_data, dict) else programs_data

    # Handle programs as either list of strings (IDs) or list of dicts
    def get_program_id(p):
        """Extract program_id from string or dict."""
        if isinstance(p, str):
            return p
        elif isinstance(p, dict):
            return p.get("program_id", "")
        return ""

    # Find applicable 232 programs
    applicable_232 = [p for p in programs if get_program_id(p).startswith("section_232_")]

    # Get materials that have 232 programs AND have value > 0
    # v6.0: Support both percentage format (0.05 = 5%) and dollar value format (500.0 = $500)
    materials_with_232 = {}
    for program in applicable_232:
        program_id = get_program_id(program)
        metal = program_id.replace("section_232_", "")  # "copper", "steel", "aluminum"

        mat_data = composition.get(metal, {})
        if isinstance(mat_data, dict):
            # Dict format: {"copper": {"percentage": 0.05, "value": 500}}
            mat_value = mat_data.get("value")
            if mat_value is None:
                # If no explicit value, calculate from percentage
                mat_pct = mat_data.get("percentage", 0)
                mat_value = mat_pct * product_value if mat_pct > 0 else 0
        else:
            # Simple format: {"copper": 0.05} or {"copper": 500.0}
            mat_value = mat_data if isinstance(mat_data, (int, float)) else 0
            # v6.0: Detect percentage vs dollar value
            # If value <= 1.0, it's likely a percentage (0.05 = 5%)
            # If value > 1.0, it's likely a dollar value ($500)
            if 0 < mat_value <= 1.0:
                mat_value = mat_value * product_value  # Convert percentage to dollar value

        if mat_value > 0:
            materials_with_232[metal] = mat_value

    # If no 232 materials, return single full_product slice
    if not materials_with_232:
        return json.dumps({
            "slice_count": 1,
            "slices": [{
                "entry_id": "full_product",
                "slice_type": "full",
                "base_hts": hts_code,
                "value": product_value,
                "materials": composition
            }]
        })

    # Calculate slices
    slices = []
    metal_total = sum(materials_with_232.values())
    non_metal_value = product_value - metal_total

    # Non-metal slice (if there's non-metal value)
    if non_metal_value > 0:
        non_metal_materials = {k: v for k, v in composition.items() if k not in materials_with_232}
        slices.append({
            "entry_id": "non_metal",
            "slice_type": "non_metal",
            "base_hts": hts_code,
            "value": non_metal_value,
            "materials": non_metal_materials
        })

    # One slice per 232 metal
    for metal, value in materials_with_232.items():
        slices.append({
            "entry_id": f"{metal}_slice",
            "slice_type": f"{metal}_slice",
            "base_hts": hts_code,
            "value": value,
            "materials": {metal: composition.get(metal, value)}
        })

    return json.dumps({
        "slice_count": len(slices),
        "metal_total": metal_total,
        "non_metal_value": non_metal_value,
        "slices": slices
    })


@tool
def check_annex_ii_exclusion(hts_code: str, import_date: Optional[str] = None) -> str:
    """
    v4.0: Check if HTS code is in IEEPA Annex II exclusion list.

    Uses PREFIX MATCHING - checks progressively shorter prefixes:
    - 10-digit exact match
    - 8-digit prefix
    - 6-digit prefix
    - 4-digit (chapter) prefix

    If found, the product is exempt from IEEPA Reciprocal tariffs
    and receives code 9903.01.32 instead of 9903.01.25.

    Args:
        hts_code: The 10-digit HTS code (e.g., "2934.99.9050")
        import_date: Date of import for expiration check (YYYY-MM-DD)

    Returns:
        JSON with excluded flag, category, and matched prefix
    """
    app = get_flask_app()
    with app.app_context():
        models = get_models()
        IeepaAnnexIIExclusion = models["IeepaAnnexIIExclusion"]

        hts_clean = hts_code.replace(".", "")
        check_date = date.fromisoformat(import_date) if import_date else date.today()

        # Try progressively shorter prefixes (longest match wins)
        for length in [10, 8, 6, 4]:
            prefix = hts_clean[:length]
            match = IeepaAnnexIIExclusion.query.filter_by(hts_code=prefix).first()

            if match and match.is_active(check_date):
                return json.dumps({
                    "excluded": True,
                    "hts_code": hts_code,
                    "matched_prefix": prefix,
                    "category": match.category,
                    "description": match.description,
                    "source_doc": match.source_doc,
                    "effective_date": match.effective_date.isoformat() if match.effective_date else None,
                    "expiration_date": match.expiration_date.isoformat() if match.expiration_date else None,
                    "variant": "annex_ii_exempt",
                    "chapter_99_code": "9903.01.32"
                })

        return json.dumps({
            "excluded": False,
            "hts_code": hts_code,
            "reason": "HTS code not in Annex II exclusion list"
        })


@tool
def resolve_reciprocal_variant(hts_code: str, slice_type: str, us_content_pct: Optional[float] = None, import_date: Optional[str] = None) -> str:
    """
    v4.0: Determine IEEPA Reciprocal variant for a given slice.

    Priority order:
    1. annex_ii_exempt - If HTS is in Annex II exclusion list
    2. us_content_exempt - If US content >= 20%
    3. metal_exempt - If slice is a 232 metal slice (copper_slice, steel_slice, aluminum_slice)
    4. taxable - Default, pay 10% reciprocal tariff

    Args:
        hts_code: The 10-digit HTS code
        slice_type: Slice type: 'full', 'non_metal', 'copper_slice', 'steel_slice', 'aluminum_slice'
        us_content_pct: US content percentage (0.0-1.0), if known
        import_date: Date of import (YYYY-MM-DD)

    Returns:
        JSON with variant, action, chapter_99_code, and duty_rate
    """
    # Priority 1: Check Annex II exclusion
    annex_ii_result = check_annex_ii_exclusion.invoke({"hts_code": hts_code, "import_date": import_date})
    annex_ii_data = json.loads(annex_ii_result)

    if annex_ii_data.get("excluded"):
        return json.dumps({
            "variant": "annex_ii_exempt",
            "action": "exempt",
            "chapter_99_code": "9903.01.32",
            "duty_rate": 0.0,
            "reason": f"HTS {hts_code} is in Annex II exclusion list ({annex_ii_data.get('category')})"
        })

    # Priority 2: US content exemption
    if us_content_pct is not None and us_content_pct >= 0.20:
        return json.dumps({
            "variant": "us_content_exempt",
            "action": "exempt",
            "chapter_99_code": "9903.01.34",
            "duty_rate": 0.0,
            "reason": f"US content ({us_content_pct*100:.1f}%) >= 20% threshold"
        })

    # Priority 3: 232 metal slice exemption
    metal_slices = ["copper_slice", "steel_slice", "aluminum_slice"]
    if slice_type in metal_slices:
        return json.dumps({
            "variant": "metal_exempt",
            "action": "exempt",
            "chapter_99_code": "9903.01.33",
            "duty_rate": 0.0,
            "reason": f"Slice type '{slice_type}' is 232 metal content, exempt from Reciprocal"
        })

    # Default: Taxable
    return json.dumps({
        "variant": "taxable",
        "action": "paid",
        "chapter_99_code": "9903.01.25",
        "duty_rate": 0.10,
        "reason": "No exemption applies, subject to 10% IEEPA Reciprocal tariff"
    })


@tool
def build_entry_stack(
    hts_code: str,
    country: str,
    slice_type: str,
    applicable_programs: str,
    materials: Optional[str] = None,
    us_content_pct: Optional[float] = None,
    import_date: Optional[str] = None
) -> str:
    """
    v4.0: Build the Chapter 99 code stack for a single ACE entry slice.

    For each applicable program, determines:
    - Action (apply, claim, disclaim, paid, exempt)
    - Variant (for IEEPA Reciprocal)
    - Chapter 99 code and duty rate

    Programs are ordered by filing_sequence per CBP CSMS #64018403.

    Args:
        hts_code: The 10-digit HTS code
        country: Country of origin
        slice_type: Slice type: 'full', 'non_metal', 'copper_slice', etc.
        applicable_programs: JSON string of applicable programs
        materials: JSON string of material composition (optional)
        us_content_pct: US content percentage (optional)
        import_date: Import date (optional)

    Returns:
        JSON with list of FilingLine objects for this slice's stack
    """
    try:
        programs_data = json.loads(applicable_programs) if isinstance(applicable_programs, str) else applicable_programs
        composition = json.loads(materials) if materials and isinstance(materials, str) else (materials or {})
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {str(e)}"})

    programs = programs_data.get("programs", []) if isinstance(programs_data, dict) else programs_data

    # Sort by filing_sequence
    programs = sorted(programs, key=lambda p: p.get("filing_sequence", 999))

    stack = []
    seq = 0

    for program in programs:
        program_id = program.get("program_id")
        program_name = program.get("program_name", program_id)

        # Determine action and variant based on program type
        action = None
        variant = None
        duty_rate = None
        chapter_99_code = None

        if program_id == "section_301":
            # Section 301 applies to all slices if product is on 301 list
            action = "apply"
            variant = None

        elif program_id == "ieepa_fentanyl":
            # IEEPA Fentanyl - v6.0: Use data-driven country scope
            # First normalize country to ISO code
            normalized = normalize_country(country)
            country_iso2 = normalized.get("iso_alpha2") or country

            # Check program_country_scope table
            scope_result = check_program_country_scope(
                program_id="ieepa_fentanyl",
                country_iso2=country_iso2,
                import_date=date.fromisoformat(import_date) if import_date else None
            )

            if scope_result.get("in_scope"):
                action = "apply"
                variant = None
            else:
                # Fallback for backwards compatibility (until data is populated)
                # Also includes Macau (MO) per broker feedback
                if country.lower() in ["china", "cn", "hong kong", "hk", "macau", "mo", "macao"]:
                    action = "apply"
                    variant = None

        elif program_id == "ieepa_reciprocal":
            # IEEPA Reciprocal: Resolve variant based on slice type and exclusions
            variant_result = resolve_reciprocal_variant.invoke({
                "hts_code": hts_code,
                "slice_type": slice_type,
                "us_content_pct": us_content_pct,
                "import_date": import_date
            })
            variant_data = json.loads(variant_result)
            variant = variant_data.get("variant")
            action = variant_data.get("action")
            duty_rate = variant_data.get("duty_rate")
            chapter_99_code = variant_data.get("chapter_99_code")

        elif program_id.startswith("section_232_"):
            # Section 232: First check if HTS is on the 232 inclusion list for this metal
            metal = program_id.replace("section_232_", "")

            # Check inclusion list - only show 232 if HTS is actually covered
            inclusion_result = check_program_inclusion.invoke({
                "program_id": program_id,
                "hts_code": hts_code
            })
            inclusion_data = json.loads(inclusion_result)

            if not inclusion_data.get("included"):
                # HTS is NOT on the 232 list for this metal - skip entirely
                continue

            # v7.0: Get disclaim_behavior from TariffProgram table
            disclaim_behavior = get_disclaim_behavior(program_id)

            # HTS IS on the 232 list - determine claim vs disclaim based on slice type
            if slice_type == f"{metal}_slice":
                # This is the claim slice for this metal
                action = "claim"
                # Use HTS-specific claim_code from inclusion data
                chapter_99_code = inclusion_data.get("claim_code")
                duty_rate = inclusion_data.get("duty_rate")
            else:
                # This is NOT the claim slice for this metal
                # v7.0: Apply disclaim_behavior
                if disclaim_behavior == "required":
                    # Copper: Must include disclaim code in OTHER slices
                    action = "disclaim"
                    chapter_99_code = inclusion_data.get("disclaim_code")
                    duty_rate = 0.0
                elif disclaim_behavior == "omit":
                    # Steel/Aluminum: Omit entirely when not claimed (no disclaim line)
                    continue  # Skip this program for this slice
                else:
                    # Default: use disclaim (backwards compatibility)
                    action = "disclaim"
                    chapter_99_code = inclusion_data.get("disclaim_code")
                    duty_rate = 0.0
            variant = None

        # Skip if no action determined
        if action is None:
            continue

        # Look up code if not already set
        if chapter_99_code is None:
            code_result = get_program_output.invoke({
                "program_id": program_id,
                "action": action,
                "variant": variant,
                "slice_type": slice_type
            })
            code_data = json.loads(code_result)
            if code_data.get("found"):
                chapter_99_code = code_data.get("chapter_99_code")
                duty_rate = code_data.get("duty_rate", 0)
            else:
                # Fallback: try with slice_type='all'
                code_result = get_program_output.invoke({
                    "program_id": program_id,
                    "action": action,
                    "variant": variant,
                    "slice_type": "all"
                })
                code_data = json.loads(code_result)
                if code_data.get("found"):
                    chapter_99_code = code_data.get("chapter_99_code")
                    duty_rate = code_data.get("duty_rate", 0)

        if chapter_99_code:
            seq += 1
            stack.append({
                "sequence": seq,
                "chapter_99_code": chapter_99_code,
                "program": program_name,
                "program_id": program_id,
                "action": action,
                "variant": variant,
                "duty_rate": duty_rate,
                "applies_to": "full" if program_id in ["section_301", "ieepa_fentanyl"] else "partial",
                "material": program_id.replace("section_232_", "") if program_id.startswith("section_232_") else None
            })

    return json.dumps({
        "slice_type": slice_type,
        "stack_count": len(stack),
        "stack": stack
    })


# ============================================================================
# Tool List for Agent Binding
# ============================================================================

STACKING_TOOLS = [
    ensure_materials,
    get_applicable_programs,
    check_program_inclusion,
    check_program_exclusion,
    check_material_composition,
    resolve_program_dependencies,
    get_program_output,
    calculate_duties,
    lookup_product_history,
    save_product_decision,
    # v4.0 tools
    plan_entry_slices,
    check_annex_ii_exclusion,
    resolve_reciprocal_variant,
    build_entry_stack,
]
