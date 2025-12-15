"""
SQLAlchemy models for Tariff Stacking feature.

These tables are populated from government documents (Section 301, 232, IEEPA)
and used by the stacking tools to determine applicable tariffs.

All tariff logic is data-driven - NO hardcoded country or HTS checks in code.

Version History:
- v2.0 (Phase 6): Content-value-based duties
- v3.0 (Phase 6.5): IEEPA unstacking
- v4.0 (Phase 7): Entry slices, Annex II exclusions, variant/slice_type support
- v5.0 (Phase 8): Country-specific rates, formula support, MFN base rates, source document audit trail
  - CountryGroup: 'EU', 'UK', 'CN' groupings
  - CountryGroupMember: Map 'Germany' → 'EU'
  - ProgramRate: Country-group-specific rates with formula support (e.g., EU 15% ceiling)
  - HtsBaseRate: MFN Column 1 rates for formula calculations
  - SourceDocument: Full audit trail for all rules with change detection
- v6.0 (Phase 9): Data-driven country scope, order-independent suppression, audit trail
  - CountryAlias: Normalize country input ('Macau', 'MO', 'Macao' → 'MO')
  - ProgramCountryScope: Data-driven country applicability per program (replaces hardcoded lists)
  - ProgramSuppression: Program interaction rules (e.g., timber suppresses reciprocal)
  - IngestionRun: Audit trail for data ingestion operations
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import JSON, UniqueConstraint
from app.web.db import db
from app.web.db.models.base import BaseModel


class TariffProgram(BaseModel):
    """
    Master table defining what tariff programs exist and when they apply.

    This is the entry point for stacking - query this table first to find
    what programs might apply, then use the inclusion/exclusion tables.

    v4.0 Update: Added calculation_sequence for duty math order (separate from filing_sequence).
    - filing_sequence: Order in ACE entry (301 → Fentanyl → Reciprocal → 232)
    - calculation_sequence: Order for duty calculation (301 → Fentanyl → 232 → Reciprocal)

    v4.1 Update: program_id is no longer unique - same program can apply to multiple countries.
    - Composite unique key on (program_id, country)
    - IEEPA Reciprocal can have entries for China, Germany, UK, etc.
    """
    __tablename__ = "tariff_programs"
    __table_args__ = (
        UniqueConstraint('program_id', 'country', name='uq_program_country'),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.String(64), nullable=False, index=True)  # "section_301", "ieepa_fentanyl"
    program_name = db.Column(db.String(256), nullable=False)  # "Section 301 China Tariffs"
    country = db.Column(db.String(64), nullable=False)  # "China", "ALL", etc.
    check_type = db.Column(db.String(32), nullable=False)  # "hts_lookup", "always"
    condition_handler = db.Column(db.String(64), default="none")  # "none", "handle_material_composition", "handle_dependency"
    condition_param = db.Column(db.String(64), nullable=True)  # NULL, or "section_232" for dependencies
    inclusion_table = db.Column(db.String(64), nullable=True)  # "section_301_inclusions" or NULL
    exclusion_table = db.Column(db.String(64), nullable=True)  # "section_301_exclusions" or NULL
    filing_sequence = db.Column(db.Integer, nullable=False)  # Order in CBP filing (1, 2, 3...)
    # v4.0: Separate sequence for duty calculation (232 before Reciprocal for unstacking)
    calculation_sequence = db.Column(db.Integer, nullable=True)  # Order for duty math (defaults to filing_sequence)
    source_document = db.Column(db.String(256), nullable=True)  # "USTR_301_Notice.pdf"
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)  # NULL if still active

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_id": self.program_id,
            "program_name": self.program_name,
            "country": self.country,
            "check_type": self.check_type,
            "condition_handler": self.condition_handler,
            "condition_param": self.condition_param,
            "inclusion_table": self.inclusion_table,
            "exclusion_table": self.exclusion_table,
            "filing_sequence": self.filing_sequence,
            "calculation_sequence": self.calculation_sequence or self.filing_sequence,
            "source_document": self.source_document,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
        }


class Section301Inclusion(BaseModel):
    """
    Section 301 inclusion list (populated from Lists 1-4 PDFs).

    If an HTS 8-digit prefix is in this table, Section 301 tariffs apply
    (unless there's a matching exclusion).
    """
    __tablename__ = "section_301_inclusions"
    __table_args__ = (
        UniqueConstraint('hts_8digit', 'list_name', name='uq_301_inclusion'),
    )

    id = db.Column(db.Integer, primary_key=True)
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)  # First 8 digits
    list_name = db.Column(db.String(32), nullable=False)  # "list_1", "list_2", "list_3", "list_4a"
    chapter_99_code = db.Column(db.String(16), nullable=False)  # "9903.88.03"
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)  # 0.25 for 25%
    source_doc = db.Column(db.String(256), nullable=True)
    source_page = db.Column(db.Integer, nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_8digit": self.hts_8digit,
            "list_name": self.list_name,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "source_doc": self.source_doc,
            "source_page": self.source_page,
        }


class Section301Exclusion(BaseModel):
    """
    Section 301 exclusions (populated from exclusion notices + extensions).

    If a product matches an exclusion description (semantic match), the
    Section 301 tariff does NOT apply for that product.
    """
    __tablename__ = "section_301_exclusions"

    id = db.Column(db.Integer, primary_key=True)
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)  # Full exclusion description for semantic match
    exclusion_doc = db.Column(db.String(256), nullable=True)  # Source document
    original_expiry = db.Column(db.Date, nullable=True)
    extended_to = db.Column(db.Date, nullable=True)  # Latest extension date
    source_page = db.Column(db.Integer, nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if exclusion is active as of a given date (defaults to today)."""
        check_date = as_of_date or date.today()
        if self.extended_to:
            return self.extended_to > check_date
        if self.original_expiry:
            return self.original_expiry > check_date
        return True  # No expiry = always active

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_8digit": self.hts_8digit,
            "description": self.description,
            "exclusion_doc": self.exclusion_doc,
            "original_expiry": self.original_expiry.isoformat() if self.original_expiry else None,
            "extended_to": self.extended_to.isoformat() if self.extended_to else None,
            "is_active": self.is_active(),
            "source_page": self.source_page,
        }


class Section232Material(BaseModel):
    """
    Section 232 materials (populated from 232 proclamations for steel, aluminum, copper).

    For each HTS/material combination, stores both claim and disclaim codes.
    Whether to claim or disclaim depends on material composition.

    Phase 6 Update (Dec 2025): Added content-value-based duty fields.
    - content_basis: 'value' means duty is on material $ value, not percentage
    - split_policy: 'if_any_content' means generate 2 filing lines when material present
    - CBP now requires line splitting: one line for non-material content, one for material content
    """
    __tablename__ = "section_232_materials"
    __table_args__ = (
        UniqueConstraint('hts_8digit', 'material', name='uq_232_material'),
    )

    id = db.Column(db.Integer, primary_key=True)
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)
    material = db.Column(db.String(32), nullable=False)  # "copper", "steel", "aluminum"
    claim_code = db.Column(db.String(16), nullable=False)  # "9903.78.01"
    disclaim_code = db.Column(db.String(16), nullable=False)  # "9903.78.02"
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)  # Rate when claiming
    threshold_percent = db.Column(db.Numeric(5, 4), nullable=True)  # Min % to trigger claim (if any)
    source_doc = db.Column(db.String(256), nullable=True)
    # Phase 6: Content-value-based duty columns
    content_basis = db.Column(db.String(32), default="value")  # 'value' (duty on $ value), 'mass', 'percent'
    quantity_unit = db.Column(db.String(16), default="kg")  # Unit for material content reporting
    split_policy = db.Column(db.String(32), default="if_any_content")  # 'never', 'if_any_content', 'if_above_threshold'
    split_threshold_pct = db.Column(db.Numeric(5, 4), nullable=True)  # NULL for 'if_any_content', threshold for 'if_above_threshold'

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_8digit": self.hts_8digit,
            "material": self.material,
            "claim_code": self.claim_code,
            "disclaim_code": self.disclaim_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "threshold_percent": float(self.threshold_percent) if self.threshold_percent else None,
            "source_doc": self.source_doc,
            "content_basis": self.content_basis,
            "quantity_unit": self.quantity_unit,
            "split_policy": self.split_policy,
            "split_threshold_pct": float(self.split_threshold_pct) if self.split_threshold_pct else None,
        }


class ProgramCode(BaseModel):
    """
    Output codes for each program/action combination.

    Given a program_id and action (claim/disclaim/apply), this table
    provides the Chapter 99 code and duty rate to output.

    v4.0 Update: Added variant and slice_type for precise code lookup.
    - variant: 'taxable', 'annex_ii_exempt', 'metal_exempt', 'us_content_exempt'
    - slice_type: 'all', 'non_metal', 'copper_slice', 'steel_slice', 'aluminum_slice'

    Primary key is now (program_id, action, variant, slice_type).
    """
    __tablename__ = "program_codes"
    __table_args__ = (
        UniqueConstraint('program_id', 'action', 'variant', 'slice_type', name='uq_program_action_variant_slice'),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.String(64), nullable=False, index=True)  # FK to tariff_programs.program_id
    action = db.Column(db.String(32), nullable=False)  # "claim", "disclaim", "apply", "paid", "exempt"
    # v4.0: Variant and slice_type for precise code lookup
    variant = db.Column(db.String(32), nullable=True)  # 'taxable', 'annex_ii_exempt', 'metal_exempt', 'us_content_exempt'
    slice_type = db.Column(db.String(32), default="all")  # 'all', 'non_metal', 'copper_slice', 'steel_slice', 'aluminum_slice'
    chapter_99_code = db.Column(db.String(16), nullable=False)  # "9903.88.03"
    duty_rate = db.Column(db.Numeric(5, 4), nullable=True)  # Rate for this action
    applies_to = db.Column(db.String(32), default="full")  # "full" or "partial"
    source_doc = db.Column(db.String(256), nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_id": self.program_id,
            "action": self.action,
            "variant": self.variant,
            "slice_type": self.slice_type,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "applies_to": self.applies_to,
            "source_doc": self.source_doc,
        }


class DutyRule(BaseModel):
    """
    Duty calculation rules for each program.

    Defines how duties compound/add for each program.

    Phase 6 Update (Dec 2025): Added content-value-based duty fields.
    - base_on='content_value' means duty is calculated on material $ value
    - content_key identifies which material ('copper', 'steel', 'aluminum')
    - fallback_base_on='full_value' means if content value unknown, charge on full product value

    Phase 6.5 Update (Dec 2025): Added IEEPA unstacking fields.
    - base_effect='subtract_from_remaining' means this program's content_value is deducted from remaining_value
    - base_on='remaining_value' means use remaining_value (after 232 deductions) as duty base
    - This implements the CBP rule: "232 content is NOT subject to IEEPA Reciprocal"

    v4.0 Update: Added variant for variant-specific duty rules.
    - IEEPA Reciprocal has different rules per variant (taxable, annex_ii_exempt, etc.)
    """
    __tablename__ = "duty_rules"
    __table_args__ = (
        UniqueConstraint('program_id', 'variant', name='uq_duty_rule_program_variant'),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.String(64), nullable=False, index=True)  # FK to tariff_programs.program_id
    # v4.0: Variant for variant-specific rules
    variant = db.Column(db.String(32), nullable=True)  # 'taxable', 'annex_ii_exempt', 'metal_exempt', 'us_content_exempt'
    calculation_type = db.Column(db.String(32), nullable=False)  # "additive", "compound", "on_portion"
    base_on = db.Column(db.String(64), nullable=False)  # "product_value", "remaining_value", "content_value"
    compounds_with = db.Column(db.String(64), nullable=True)  # NULL or another program_id
    source_doc = db.Column(db.String(256), nullable=True)
    # Phase 6: Content-value-based duty columns
    content_key = db.Column(db.String(32), nullable=True)  # 'copper', 'steel', 'aluminum' (which material)
    fallback_base_on = db.Column(db.String(64), nullable=True)  # 'full_value' if content value unknown
    # Phase 6.5: IEEPA unstacking columns
    base_effect = db.Column(db.String(64), nullable=True)  # 'subtract_from_remaining' for 232 programs

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_id": self.program_id,
            "variant": self.variant,
            "calculation_type": self.calculation_type,
            "base_on": self.base_on,
            "compounds_with": self.compounds_with,
            "source_doc": self.source_doc,
            "content_key": self.content_key,
            "fallback_base_on": self.fallback_base_on,
            "base_effect": self.base_effect,
        }


class ProductHistory(BaseModel):
    """
    Historical product classifications for learning.

    When a user confirms material composition or makes decisions,
    store it here for future lookups on similar products.
    """
    __tablename__ = "product_history"

    id = db.Column(db.Integer, primary_key=True)
    hts_code = db.Column(db.String(16), nullable=False, index=True)  # Full HTS code
    product_desc = db.Column(db.Text, nullable=True)
    country = db.Column(db.String(64), nullable=False)
    components = db.Column(JSON, nullable=True)  # {"copper": 0.05, "steel": 0.20, ...}
    decisions = db.Column(JSON, nullable=True)  # Previous stacking decisions
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(64), nullable=True)
    user_confirmed = db.Column(db.Boolean, default=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "product_desc": self.product_desc,
            "country": self.country,
            "components": self.components,
            "decisions": self.decisions,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user_id": self.user_id,
            "user_confirmed": self.user_confirmed,
        }


class IeepaAnnexIIExclusion(BaseModel):
    """
    v4.0: IEEPA Reciprocal Annex II exclusions.

    HTS codes exempt from IEEPA Reciprocal tariffs per Annex II of the
    Executive Order. Products classified under these HTS codes receive
    the 9903.01.32 exemption code instead of the taxable 9903.01.25.

    Categories include:
    - pharmaceutical: Antibiotics, hormones, nucleic acids (Ch 29)
    - chemical: Industrial chemicals, rare gases
    - critical_mineral: Tin, rare earths, strategic minerals
    - semiconductor: Certain electronic components

    Lookup is by PREFIX MATCH - a 4-digit prefix matches all 10-digit codes
    starting with those 4 digits.
    """
    __tablename__ = "ieepa_annex_ii_exclusions"

    id = db.Column(db.Integer, primary_key=True)
    hts_code = db.Column(db.String(16), nullable=False, index=True)  # 4/6/8/10 digit prefix
    description = db.Column(db.Text, nullable=True)  # Description from Annex II
    category = db.Column(db.String(64), nullable=True)  # 'pharmaceutical', 'chemical', 'critical_mineral', 'semiconductor'
    source_doc = db.Column(db.String(256), nullable=True)  # Source document
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)  # NULL if still active

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if exclusion is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.expiration_date > check_date
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "description": self.description,
            "category": self.category,
            "source_doc": self.source_doc,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "is_active": self.is_active(),
        }


# =============================================================================
# v5.0: Country-Specific Rates and Data Freshness Models
# =============================================================================

class SourceDocument(BaseModel):
    """
    v5.0: Audit trail for all government sources.

    Tracks every document used to populate tariff rules:
    - CBP CSMS bulletins
    - Federal Register notices
    - Executive Orders
    - USTR notices
    - USITC HTS updates

    Used for:
    - Audit trail (where did this rate come from?)
    - Change detection (content_hash for updates)
    - Data freshness (fetched_at, effective_date)
    """
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint('doc_type', 'doc_identifier', name='uq_source_doc'),
    )

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(512), nullable=True)  # Source URL
    title = db.Column(db.String(256), nullable=False)  # Document title
    doc_type = db.Column(db.String(64), nullable=False)  # 'CSMS', 'FR_notice', 'EO', 'USTR', 'USITC'
    doc_identifier = db.Column(db.String(128), nullable=True)  # 'CSMS #65829726', 'FR 2025-10524'
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    content_hash = db.Column(db.String(64), nullable=True)  # SHA256 for change detection
    content_text = db.Column(db.Text, nullable=True)  # Raw content (optional)
    effective_date = db.Column(db.Date, nullable=True)  # When the rule takes effect
    summary = db.Column(db.Text, nullable=True)  # AI-generated summary

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "doc_type": self.doc_type,
            "doc_identifier": self.doc_identifier,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "content_hash": self.content_hash,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "summary": self.summary,
        }


class CountryGroup(BaseModel):
    """
    v5.0: Country groupings for rate application.

    Groups like:
    - 'EU': European Union (15% ceiling rule)
    - 'UK': United Kingdom (232 exception)
    - 'CN': China (full tariffs)
    - 'USMCA': Mexico, Canada (FTA treatment)

    Countries can change groups over time (effective_date/expiration_date).
    """
    __tablename__ = "country_groups"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.String(32), unique=True, nullable=False, index=True)  # 'EU', 'UK', 'CN'
    description = db.Column(db.String(256), nullable=True)  # 'European Union - 15% ceiling rule'
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)  # NULL if still active
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if group is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.effective_date <= check_date < self.expiration_date
        return self.effective_date <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "description": self.description,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_doc_id": self.source_doc_id,
            "is_active": self.is_active(),
        }


class CountryGroupMember(BaseModel):
    """
    v5.0: Maps countries to their groups.

    Examples:
    - 'Germany' → 'EU'
    - 'DE' → 'EU' (also support ISO codes)
    - 'United Kingdom' → 'UK'
    - 'China' → 'CN'

    Supports multiple names for the same country (Germany, DE, DEU).
    Membership is time-bound (effective_date/expiration_date) for
    handling events like Brexit.
    """
    __tablename__ = "country_group_members"
    __table_args__ = (
        UniqueConstraint('country_code', 'group_id', name='uq_country_group_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    country_code = db.Column(db.String(64), nullable=False, index=True)  # 'Germany', 'DE', 'DEU'
    group_id = db.Column(db.String(32), nullable=False, index=True)  # FK to country_groups.group_id
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)  # NULL if still active
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if membership is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.effective_date <= check_date < self.expiration_date
        return self.effective_date <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "country_code": self.country_code,
            "group_id": self.group_id,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_doc_id": self.source_doc_id,
            "is_active": self.is_active(),
        }


class ProgramRate(BaseModel):
    """
    v5.0: Country-group-specific tariff rates.

    Stores rates that vary by country group:
    - 232 Steel: 50% default, 25% for UK
    - 232 Aluminum: 50% default, 25% for UK
    - IEEPA Reciprocal: 10% default, formula '15pct_minus_mfn' for EU

    rate_type determines how to get the rate:
    - 'fixed': Use the 'rate' column directly
    - 'formula': Evaluate 'rate_formula' at runtime (e.g., EU ceiling)

    Supported formulas:
    - '15pct_minus_mfn': 15% minus MFN base rate (EU ceiling rule)
    """
    __tablename__ = "program_rates"
    __table_args__ = (
        UniqueConstraint('program_id', 'group_id', 'effective_date', name='uq_program_rate'),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.String(64), nullable=False, index=True)  # 'section_232_steel', 'ieepa_reciprocal'
    group_id = db.Column(db.String(32), nullable=False, index=True)  # 'EU', 'UK', 'default'
    rate = db.Column(db.Numeric(6, 4), nullable=True)  # 0.50, 0.25, NULL for formula
    rate_type = db.Column(db.String(32), default='fixed')  # 'fixed', 'formula'
    rate_formula = db.Column(db.String(64), nullable=True)  # '15pct_minus_mfn', NULL for fixed
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)  # NULL if still active
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)
    last_refreshed_at = db.Column(db.DateTime, nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if rate is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.effective_date <= check_date < self.expiration_date
        return self.effective_date <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_id": self.program_id,
            "group_id": self.group_id,
            "rate": float(self.rate) if self.rate else None,
            "rate_type": self.rate_type,
            "rate_formula": self.rate_formula,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_doc_id": self.source_doc_id,
            "last_refreshed_at": self.last_refreshed_at.isoformat() if self.last_refreshed_at else None,
            "is_active": self.is_active(),
        }


class HtsBaseRate(BaseModel):
    """
    v5.0: MFN Column 1 base rates.

    Stores the base duty rate for HTS codes (Column 1 General rate).
    Required for formula-based calculations like EU 15% ceiling:
    - Reciprocal = max(0, 15% - MFN_base_rate)

    Lookup supports prefix matching:
    - Exact match: '8544.42.9090'
    - 8-digit match: '8544.42.90'
    - 6-digit match: '8544.42'
    - 4-digit match: '8544'
    """
    __tablename__ = "hts_base_rates"
    __table_args__ = (
        UniqueConstraint('hts_code', 'effective_date', name='uq_hts_base_rate'),
    )

    id = db.Column(db.Integer, primary_key=True)
    hts_code = db.Column(db.String(12), nullable=False, index=True)  # '8544.42.9090' or '8544.42.90'
    column1_rate = db.Column(db.Numeric(6, 4), nullable=False)  # 0.026 = 2.6%
    description = db.Column(db.String(512), nullable=True)  # 'Insulated electric conductors...'
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)  # NULL if still active
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)
    last_refreshed_at = db.Column(db.DateTime, nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if rate is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.effective_date <= check_date < self.expiration_date
        return self.effective_date <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "column1_rate": float(self.column1_rate) if self.column1_rate else None,
            "description": self.description,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_doc_id": self.source_doc_id,
            "last_refreshed_at": self.last_refreshed_at.isoformat() if self.last_refreshed_at else None,
            "is_active": self.is_active(),
        }


# =============================================================================
# v6.0: Data-Driven Country Scope, Suppressions, and Audit Trail
# =============================================================================

class CountryAlias(BaseModel):
    """
    v6.0: Normalize country input to standardized ISO codes.

    Maps various country name formats to ISO alpha-2 codes:
    - 'Macau', 'MO', 'Macao', 'MAC' → 'MO'
    - 'China', 'CN', 'PRC', 'CHN' → 'CN'
    - 'Deutschland', 'Germany', 'DE', 'DEU' → 'DE'

    This enables data-driven country handling instead of hardcoded string lists.
    All downstream lookups use iso_alpha2 as the canonical country identifier.
    """
    __tablename__ = "country_aliases"
    __table_args__ = (
        UniqueConstraint('alias_norm', name='uq_country_alias_norm'),
    )

    id = db.Column(db.Integer, primary_key=True)
    alias_raw = db.Column(db.String(100), nullable=False)  # Original: 'Macau', 'Deutschland'
    alias_norm = db.Column(db.String(100), nullable=False, index=True)  # Lowercase trimmed: 'macau', 'deutschland'
    iso_alpha2 = db.Column(db.String(2), nullable=False, index=True)  # 'MO', 'DE'
    iso_alpha3 = db.Column(db.String(3), nullable=True)  # 'MAC', 'DEU'
    canonical_name = db.Column(db.String(100), nullable=False)  # 'Macau', 'Germany'

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "alias_raw": self.alias_raw,
            "alias_norm": self.alias_norm,
            "iso_alpha2": self.iso_alpha2,
            "iso_alpha3": self.iso_alpha3,
            "canonical_name": self.canonical_name,
        }


class ProgramCountryScope(BaseModel):
    """
    v6.0: Data-driven country applicability per program.

    Replaces hardcoded country lists like:
        if country.lower() in ["china", "cn", "hong kong", "hk"]:

    With data-driven lookup:
        SELECT * FROM program_country_scope
        WHERE program_id = 'ieepa_fentanyl'
        AND (country_group_id = X OR iso_alpha2 = 'MO')

    Each program can specify:
    - A country group (e.g., 'FENTANYL_COUNTRIES' containing CN, HK, MO)
    - A single ISO code (for country-specific exceptions)
    - scope_type 'include' or 'exclude' for positive/negative scope

    Adding Macau to fentanyl becomes a data insert, not a code change.
    """
    __tablename__ = "program_country_scope"
    __table_args__ = (
        UniqueConstraint('program_id', 'country_group_id', 'iso_alpha2', 'effective_date',
                        name='uq_program_country_scope'),
        db.CheckConstraint(
            '(country_group_id IS NOT NULL AND iso_alpha2 IS NULL) OR '
            '(country_group_id IS NULL AND iso_alpha2 IS NOT NULL)',
            name='chk_scope_target'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.String(64), nullable=False, index=True)  # 'ieepa_fentanyl', 'section_301'
    country_group_id = db.Column(db.Integer, db.ForeignKey('country_groups.id'), nullable=True)  # Use group
    iso_alpha2 = db.Column(db.String(2), nullable=True, index=True)  # Or single country
    scope_type = db.Column(db.String(20), default='include')  # 'include' or 'exclude'
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    country_group = db.relationship('CountryGroup', backref='program_scopes')
    source_document = db.relationship('SourceDocument', backref='country_scopes')

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if scope is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.effective_date <= check_date < self.expiration_date
        return self.effective_date <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_id": self.program_id,
            "country_group_id": self.country_group_id,
            "iso_alpha2": self.iso_alpha2,
            "scope_type": self.scope_type,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_doc_id": self.source_doc_id,
            "notes": self.notes,
            "is_active": self.is_active(),
        }


class ProgramSuppression(BaseModel):
    """
    v6.0: Program interaction rules (suppressions).

    Defines when one program suppresses another:
    - Section 232 Timber suppresses IEEPA Reciprocal
    - Section 232 Vehicles suppresses IEEPA Reciprocal

    This is applied ORDER-INDEPENDENTLY:
    1. Collect all applicable programs
    2. Query suppressions for ALL applicable programs in one query
    3. Remove suppressed programs from the set
    4. Build stacks from remaining programs

    This avoids iteration-order bugs where the result depends on which
    program was added to the stack first.
    """
    __tablename__ = "program_suppressions"
    __table_args__ = (
        UniqueConstraint('suppressor_program_id', 'suppressed_program_id', 'effective_date',
                        name='uq_program_suppression'),
        db.Index('idx_suppression_suppressor', 'suppressor_program_id', 'effective_date'),
        db.Index('idx_suppression_suppressed', 'suppressed_program_id', 'effective_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    suppressor_program_id = db.Column(db.String(64), nullable=False, index=True)  # 'section_232_timber'
    suppressed_program_id = db.Column(db.String(64), nullable=False, index=True)  # 'ieepa_reciprocal'
    suppression_type = db.Column(db.String(20), default='full')  # 'full' or 'partial'
    effective_date = db.Column(db.Date, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Relationship
    source_document = db.relationship('SourceDocument', backref='suppressions')

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if suppression is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.expiration_date:
            return self.effective_date <= check_date < self.expiration_date
        return self.effective_date <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "suppressor_program_id": self.suppressor_program_id,
            "suppressed_program_id": self.suppressed_program_id,
            "suppression_type": self.suppression_type,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "source_doc_id": self.source_doc_id,
            "notes": self.notes,
            "is_active": self.is_active(),
        }

    @classmethod
    def get_suppressed_programs(cls, applicable_program_ids: List[str], check_date: date) -> set:
        """
        Get all program_ids that should be suppressed given the applicable programs.

        This is the ORDER-INDEPENDENT suppression resolution:
        - Query all suppressions where suppressor is in applicable_program_ids
        - Return set of suppressed program_ids

        Usage:
            applicable = ['section_301', 'section_232_timber', 'ieepa_reciprocal']
            suppressed = ProgramSuppression.get_suppressed_programs(applicable, date.today())
            # suppressed = {'ieepa_reciprocal'} because timber suppresses it
            resolved = [p for p in applicable if p not in suppressed]
        """
        from sqlalchemy import or_

        suppressions = cls.query.filter(
            cls.suppressor_program_id.in_(applicable_program_ids),
            cls.suppressed_program_id.in_(applicable_program_ids),
            cls.effective_date <= check_date,
            or_(
                cls.expiration_date.is_(None),
                cls.expiration_date > check_date
            )
        ).all()

        return {s.suppressed_program_id for s in suppressions}


class IngestionRun(BaseModel):
    """
    v6.0: Audit trail for data ingestion operations.

    Tracks every data update to tariff tables:
    - What source document triggered the update
    - When it was ingested
    - Who/what ran the ingestion
    - What tables were affected
    - How many records were added/updated/deleted

    This answers:
    - "When was this rate last updated?"
    - "What source document did this rate come from?"
    - "What changed in the last ingestion?"
    """
    __tablename__ = "ingestion_runs"

    id = db.Column(db.Integer, primary_key=True)
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)
    ingestion_timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    operator = db.Column(db.String(100), nullable=True)  # 'system', 'admin@example.com', 'populate_script'
    table_affected = db.Column(db.String(100), nullable=False)  # 'program_rates', 'section_301_inclusions'
    records_added = db.Column(db.Integer, default=0)
    records_updated = db.Column(db.Integer, default=0)
    records_deleted = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='success')  # 'success', 'partial', 'failed'
    error_message = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Relationship
    source_document = db.relationship('SourceDocument', backref='ingestion_runs')

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_doc_id": self.source_doc_id,
            "ingestion_timestamp": self.ingestion_timestamp.isoformat() if self.ingestion_timestamp else None,
            "operator": self.operator,
            "table_affected": self.table_affected,
            "records_added": self.records_added,
            "records_updated": self.records_updated,
            "records_deleted": self.records_deleted,
            "status": self.status,
            "error_message": self.error_message,
            "notes": self.notes,
        }
