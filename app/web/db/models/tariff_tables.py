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

    v7.0 Update: Added disclaim_behavior for Phoebe-aligned ACE filing.
    - 'required': Copper - must file disclaim code in other slices when applicable but not claimed
    - 'omit': Steel/Aluminum - omit entirely when not claimed (no disclaim line)
    - 'none': Non-232 programs - no disclaim concept
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
    # v7.0: Disclaim behavior for Phoebe-aligned ACE filing
    disclaim_behavior = db.Column(db.String(16), default='none')  # 'required', 'omit', 'none'

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
            "disclaim_behavior": self.disclaim_behavior,
        }


class Section301Inclusion(BaseModel):
    """
    Section 301 inclusion list (populated from Lists 1-4 PDFs).

    If an HTS 8-digit prefix is in this table, Section 301 tariffs apply
    (unless there's a matching exclusion).

    NOTE: This is the LEGACY table (static). For temporal rate tracking,
    use Section301Rate which supports effective_start/effective_end dates.
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


class Section301Rate(BaseModel):
    """
    v10.0: Temporal Section 301 rates for time-series tracking.

    This table replaces Section301Inclusion for temporal queries.
    Supports rate changes over time (e.g., 2024 Four-Year Review):
    - List 4A facemasks: 7.5% (2020) → 25% (Sept 2024) → 50% (Jan 2026)

    Key design:
    - effective_start: When this rate begins
    - effective_end: When superseded (NULL = currently active)
    - chapter_99_code: The new Ch.99 code for this rate period
    - supersedes_id: Links to the rate this one replaces

    Query pattern for "rate as of date D":
      WHERE hts_8digit = X
        AND effective_start <= D
        AND (effective_end IS NULL OR effective_end > D)
      ORDER BY effective_start DESC
      LIMIT 1
    """
    __tablename__ = "section_301_rates"
    __table_args__ = (
        UniqueConstraint('hts_8digit', 'chapter_99_code', 'effective_start', name='uq_301_rate_temporal'),
        db.Index('idx_301_rates_hts_date', 'hts_8digit', 'effective_start', 'effective_end'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # HTS identification
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)  # First 8 digits (no dots)
    hts_10digit = db.Column(db.String(12), nullable=True)  # Full 10-digit if applicable

    # Chapter 99 code and rate
    chapter_99_code = db.Column(db.String(16), nullable=False)  # "9903.91.07"
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)  # 0.50 for 50%

    # Temporal validity
    effective_start = db.Column(db.Date, nullable=False)  # When rate begins
    effective_end = db.Column(db.Date, nullable=True)  # When superseded (NULL = active)

    # Classification
    list_name = db.Column(db.String(64), nullable=True)  # "list_4a", "strategic_medical", etc.
    sector = db.Column(db.String(64), nullable=True)  # "medical", "semiconductor", "ev", etc.
    product_group = db.Column(db.String(128), nullable=True)  # "Facemasks", "Electric Vehicles"
    description = db.Column(db.Text, nullable=True)  # Product description

    # Audit trail
    source_doc = db.Column(db.String(256), nullable=True)  # "2024-21217"
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)

    # Supersession tracking
    supersedes_id = db.Column(db.Integer, db.ForeignKey('section_301_rates.id'), nullable=True)
    superseded_by_id = db.Column(db.Integer, db.ForeignKey('section_301_rates.id'), nullable=True)

    # Role: 'impose' (adds duty) vs 'exclude' (removes duty via exclusion)
    # Exclusions take precedence over impose codes per CBP guidance
    role = db.Column(db.String(16), nullable=False, default='impose')  # 'impose' or 'exclude'

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(64), nullable=True)  # "system", "human"

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if rate is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.effective_end:
            return self.effective_start <= check_date < self.effective_end
        return self.effective_start <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_8digit": self.hts_8digit,
            "hts_10digit": self.hts_10digit,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "list_name": self.list_name,
            "sector": self.sector,
            "product_group": self.product_group,
            "description": self.description,
            "source_doc": self.source_doc,
            "source_doc_id": self.source_doc_id,
            "supersedes_id": self.supersedes_id,
            "superseded_by_id": self.superseded_by_id,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
            "is_active": self.is_active(),
        }

    @classmethod
    def get_rate_as_of(cls, hts_8digit: str, as_of_date: date) -> Optional["Section301Rate"]:
        """
        Get the applicable rate for an HTS code as of a specific date.

        Uses role-based precedence:
        1. First check for active EXCLUSION within its time window
        2. If exclusion exists and is active → return it (0% duty)
        3. If no active exclusion → return most recent IMPOSE code

        Per CBP guidance: When filing exclusion code, do NOT file base duty code.
        Exclusions (role='exclude') always take precedence over impose codes.
        """
        from sqlalchemy import or_, case

        return cls.query.filter(
            cls.hts_8digit == hts_8digit,
            cls.effective_start <= as_of_date,
            or_(
                cls.effective_end.is_(None),
                cls.effective_end > as_of_date
            )
        ).order_by(
            # Priority: exclusions first (0), impose second (1)
            case((cls.role == 'exclude', 0), else_=1),
            # Within same priority, most recent first
            cls.effective_start.desc()
        ).first()


class Section232Rate(BaseModel):
    """
    v10.0: Temporal Section 232 rates for time-series tracking.

    Supports rate changes over time and country-specific exceptions:
    - Global rate: 50% (steel, aluminum) / 25% (copper)
    - UK exception: 25% for steel/aluminum

    Key design:
    - country_code: NULL for global, 'GBR' for UK exception, etc.
    - material_type: 'steel', 'aluminum', 'copper'
    - article_type: 'primary' or 'derivative'
    """
    __tablename__ = "section_232_rates"
    __table_args__ = (
        UniqueConstraint('hts_8digit', 'material_type', 'country_code', 'effective_start',
                        name='uq_232_rate_temporal'),
        db.Index('idx_232_rates_hts_date', 'hts_8digit', 'effective_start', 'effective_end'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # HTS identification
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)
    material_type = db.Column(db.String(20), nullable=False)  # steel, aluminum, copper

    # Chapter 99 codes
    chapter_99_claim = db.Column(db.String(16), nullable=False)  # Claim code
    chapter_99_disclaim = db.Column(db.String(16), nullable=True)  # Disclaim code

    # Rate
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)  # 0.50 for 50%

    # Country scope (NULL = all countries, specific code for exception)
    country_code = db.Column(db.String(3), nullable=True, index=True)  # 'GBR', 'CAN', etc.

    # Article classification
    article_type = db.Column(db.String(20), nullable=True)  # 'primary', 'derivative'

    # Temporal validity
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)

    # Audit trail
    source_doc = db.Column(db.String(256), nullable=True)
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(64), nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if rate is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.effective_end:
            return self.effective_start <= check_date < self.effective_end
        return self.effective_start <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_8digit": self.hts_8digit,
            "material_type": self.material_type,
            "chapter_99_claim": self.chapter_99_claim,
            "chapter_99_disclaim": self.chapter_99_disclaim,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "country_code": self.country_code,
            "article_type": self.article_type,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "source_doc": self.source_doc,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.is_active(),
        }

    @classmethod
    def get_rate_as_of(cls, hts_8digit: str, material: str, country_code: str,
                       as_of_date: date) -> Optional["Section232Rate"]:
        """
        Get the applicable rate for an HTS/material/country as of a specific date.

        Tries country-specific rate first, then falls back to global rate.
        """
        from sqlalchemy import or_

        # Try country-specific rate first
        rate = cls.query.filter(
            cls.hts_8digit == hts_8digit,
            cls.material_type == material,
            cls.country_code == country_code,
            cls.effective_start <= as_of_date,
            or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
        ).order_by(cls.effective_start.desc()).first()

        if rate:
            return rate

        # Fall back to global rate (country_code = NULL)
        return cls.query.filter(
            cls.hts_8digit == hts_8digit,
            cls.material_type == material,
            cls.country_code.is_(None),
            cls.effective_start <= as_of_date,
            or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
        ).order_by(cls.effective_start.desc()).first()


class IeepaRate(BaseModel):
    """
    v10.0: Temporal IEEPA rates for time-series tracking.

    Supports both IEEPA programs:
    - ieepa_fentanyl: 20% on China/HK/Macau (effective Apr 2025)
    - ieepa_reciprocal: 10% baseline, country-specific rates

    Key design:
    - program_type: 'fentanyl' or 'reciprocal'
    - country_code: 'CHN', 'HKG', 'MAC' for fentanyl; various for reciprocal
    - variant: 'taxable', 'annex_ii_exempt', 'metal_exempt', etc.
    """
    __tablename__ = "ieepa_rates"
    __table_args__ = (
        UniqueConstraint('program_type', 'country_code', 'chapter_99_code', 'effective_start',
                        name='uq_ieepa_rate_temporal'),
        db.Index('idx_ieepa_rates_date', 'program_type', 'effective_start', 'effective_end'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Program identification
    program_type = db.Column(db.String(20), nullable=False)  # 'fentanyl', 'reciprocal'

    # Country scope
    country_code = db.Column(db.String(3), nullable=True, index=True)  # 'CHN', 'HKG', 'MAC', NULL for all

    # Chapter 99 code and rate
    chapter_99_code = db.Column(db.String(16), nullable=False)
    duty_rate = db.Column(db.Numeric(5, 4), nullable=False)

    # Variant for different exemption types
    variant = db.Column(db.String(32), nullable=True)  # 'taxable', 'annex_ii_exempt', 'metal_exempt'

    # Rate type (fixed or formula)
    rate_type = db.Column(db.String(20), default='fixed')  # 'fixed', 'formula'
    rate_formula = db.Column(db.String(64), nullable=True)  # '15pct_minus_mfn' for EU ceiling

    # Temporal validity
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)

    # Audit trail
    source_doc = db.Column(db.String(256), nullable=True)
    source_doc_id = db.Column(db.Integer, db.ForeignKey('source_documents.id'), nullable=True)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(64), nullable=True)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if rate is active as of a given date."""
        check_date = as_of_date or date.today()
        if self.effective_end:
            return self.effective_start <= check_date < self.effective_end
        return self.effective_start <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program_type": self.program_type,
            "country_code": self.country_code,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "variant": self.variant,
            "rate_type": self.rate_type,
            "rate_formula": self.rate_formula,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "source_doc": self.source_doc,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.is_active(),
        }

    @classmethod
    def get_rate_as_of(cls, program_type: str, country_code: str,
                       as_of_date: date, variant: str = None) -> Optional["IeepaRate"]:
        """
        Get the applicable IEEPA rate for a program/country as of a specific date.
        """
        from sqlalchemy import or_

        query = cls.query.filter(
            cls.program_type == program_type,
            cls.country_code == country_code,
            cls.effective_start <= as_of_date,
            or_(cls.effective_end.is_(None), cls.effective_end > as_of_date)
        )

        if variant:
            query = query.filter(cls.variant == variant)

        return query.order_by(cls.effective_start.desc()).first()


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

    Phase 11 Update (Jan 2026): Added article_type per U.S. Note 16 to Chapter 99.
    Three categories with different valuation and code rules:
    - 'primary': Ch 72 steel, Ch 76 aluminum raw materials → full value, codes 9903.80.01/9903.85.03
    - 'derivative': Ch 73 steel articles → full value, codes 9903.81.89/9903.81.90
    - 'content': Other chapters with metal components → content value only, codes 9903.81.91/9903.85.08

    IEEPA Reciprocal exemption rule:
    - 'primary' and 'derivative': 100% of value exempt (entire article subject to 232)
    - 'content': Only metal content portion exempt
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
    # Phase 11: Article type per U.S. Note 16 to Chapter 99
    article_type = db.Column(db.String(16), default="content")  # 'primary', 'derivative', 'content'

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
            "article_type": self.article_type,
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


# =============================================================================
# v9.0: Search Persistence & Vector Caching Models
# =============================================================================

class GeminiSearchResult(BaseModel):
    """
    v9.0: Stores structured JSON output from Gemini searches.

    Caches the results of Gemini MCP searches to avoid redundant API calls.
    Each search is keyed by (hts_code, query_type, material).

    Cache invalidation:
    - expires_at: Optional TTL for automatic expiration
    - is_verified: Human-verified results never expire
    - was_force_search: Tracks if this replaced a previous cached result
    """
    __tablename__ = "gemini_search_results"
    __table_args__ = (
        UniqueConstraint('hts_code', 'query_type', 'material', name='uq_gemini_search_result'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Query identification
    hts_code = db.Column(db.String(20), nullable=False, index=True)
    query_type = db.Column(db.String(32), nullable=False)  # 'section_232', 'section_301', 'ieepa', etc.
    material = db.Column(db.String(16), nullable=True)  # 'copper', 'steel', 'aluminum', 'all', null

    # Result data
    result_json = db.Column(JSON, nullable=False)  # Full Gemini response parsed as JSON
    raw_response = db.Column(db.Text, nullable=True)  # Original response text (for debugging)

    # Model metadata
    model_used = db.Column(db.String(64), nullable=False)  # 'gemini-2.5-flash', 'gemini-3-pro-preview'
    thinking_budget = db.Column(db.Integer, nullable=True)  # null if not using thinking mode

    # Timestamps
    searched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)  # Optional TTL for cache invalidation

    # Verification
    is_verified = db.Column(db.Boolean, default=False)
    verified_by = db.Column(db.String(100), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verification_notes = db.Column(db.Text, nullable=True)

    # Force search tracking
    was_force_search = db.Column(db.Boolean, default=False)

    # Relationships
    grounding_sources = db.relationship('GroundingSource', backref='search_result', cascade='all, delete-orphan')

    def is_expired(self, as_of: Optional[datetime] = None) -> bool:
        """Check if cached result has expired."""
        if self.is_verified:
            return False  # Verified results never expire
        if self.expires_at is None:
            return False  # No expiry set
        check_time = as_of or datetime.utcnow()
        return self.expires_at < check_time

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "query_type": self.query_type,
            "material": self.material,
            "result_json": self.result_json,
            "raw_response": self.raw_response,
            "model_used": self.model_used,
            "thinking_budget": self.thinking_budget,
            "searched_at": self.searched_at.isoformat() if self.searched_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_verified": self.is_verified,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verification_notes": self.verification_notes,
            "was_force_search": self.was_force_search,
            "is_expired": self.is_expired(),
            "grounding_source_count": len(self.grounding_sources) if self.grounding_sources else 0,
        }


class GroundingSource(BaseModel):
    """
    v9.0: Stores URLs/sources that Gemini used for grounding.

    Each Gemini search with Google Search grounding returns a list of
    source URLs. We store these for:
    - Audit trail (where did this information come from?)
    - Content caching (optionally fetch and store page content)
    - Vector indexing (chunk content for Pinecone)

    Reliability tracking helps prioritize official sources (cbp.gov,
    federalregister.gov) over unofficial ones.
    """
    __tablename__ = "grounding_sources"
    __table_args__ = (
        UniqueConstraint('search_result_id', 'url', name='uq_grounding_source_url'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Link to search result
    search_result_id = db.Column(db.String(36), db.ForeignKey('gemini_search_results.id', ondelete='CASCADE'), nullable=False)

    # Source details
    url = db.Column(db.Text, nullable=False)
    domain = db.Column(db.String(255), nullable=True, index=True)  # Extracted domain (cbp.gov, federalregister.gov)
    title = db.Column(db.Text, nullable=True)  # Page title if available
    snippet = db.Column(db.Text, nullable=True)  # Relevant excerpt from the page

    # Content for vector indexing
    fetched_content = db.Column(db.Text, nullable=True)  # Full page content (for chunking)
    content_hash = db.Column(db.String(64), nullable=True)  # SHA-256 hash to detect changes

    # Timestamps
    first_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_verified_at = db.Column(db.DateTime, nullable=True)

    # Reliability tracking
    source_type = db.Column(db.String(32), nullable=True)  # 'official_cbp', 'federal_register', 'csms', 'other'
    reliability_score = db.Column(db.Numeric(3, 2), nullable=True)  # 0.00 to 1.00

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "search_result_id": self.search_result_id,
            "url": self.url,
            "domain": self.domain,
            "title": self.title,
            "snippet": self.snippet,
            "fetched_content": self.fetched_content[:500] if self.fetched_content else None,  # Truncated
            "content_hash": self.content_hash,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "source_type": self.source_type,
            "reliability_score": float(self.reliability_score) if self.reliability_score else None,
        }


class SearchAuditLog(BaseModel):
    """
    v9.0: Tracks all search attempts for analytics and debugging.

    Every search request is logged here, including:
    - Cache hits/misses
    - Response times
    - Token usage and cost estimates
    - Errors and failures

    Use cases:
    - Monitor API costs over time
    - Debug slow searches
    - Analyze cache effectiveness
    - Track force_search usage
    """
    __tablename__ = "search_audit_log"

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Request details
    hts_code = db.Column(db.String(20), nullable=False, index=True)
    query_type = db.Column(db.String(32), nullable=False)
    material = db.Column(db.String(16), nullable=True)
    requested_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    requested_by = db.Column(db.String(100), nullable=True)  # User/system identifier

    # Cache behavior
    cache_hit = db.Column(db.Boolean, nullable=False)  # Did we use cached result?
    cache_source = db.Column(db.String(20), nullable=True)  # 'postgres', 'pinecone', 'gemini'
    force_search = db.Column(db.Boolean, default=False)

    # Response details
    response_time_ms = db.Column(db.Integer, nullable=True)  # How long the search took
    model_used = db.Column(db.String(64), nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    error_message = db.Column(db.Text, nullable=True)

    # Cost tracking
    input_tokens = db.Column(db.Integer, nullable=True)
    output_tokens = db.Column(db.Integer, nullable=True)
    estimated_cost_usd = db.Column(db.Numeric(10, 6), nullable=True)

    # Link to result (if successful)
    search_result_id = db.Column(db.String(36), db.ForeignKey('gemini_search_results.id', ondelete='SET NULL'), nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "query_type": self.query_type,
            "material": self.material,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "requested_by": self.requested_by,
            "cache_hit": self.cache_hit,
            "cache_source": self.cache_source,
            "force_search": self.force_search,
            "response_time_ms": self.response_time_ms,
            "model_used": self.model_used,
            "success": self.success,
            "error_message": self.error_message,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": float(self.estimated_cost_usd) if self.estimated_cost_usd else None,
            "search_result_id": self.search_result_id,
        }


# =============================================================================
# v9.2: Evidence-First Citations
# =============================================================================

class NeedsReviewQueue(BaseModel):
    """
    v10.0: Queue for unverified LLM responses awaiting human/system review.

    When Gemini returns a scope determination, it goes here FIRST instead
    of being treated as truth. The response must pass through:
    1. Write Gate (mechanical proof checks)
    2. Validator LLM (semantic verification)
    3. Human review (for high-stakes decisions)

    Only after validation does the assertion move to verified_assertion.

    This breaks the "cache LLM conclusion as truth" anti-pattern.

    Status flow:
    - pending: Awaiting review
    - validated: Passed Write Gate + Validator, ready to promote
    - rejected: Failed validation, will not be promoted
    - needs_human: Requires human review (edge cases, conflicts)
    """
    __tablename__ = "needs_review_queue"
    __table_args__ = (
        db.Index('idx_review_queue_status', 'status', 'created_at'),
        db.Index('idx_review_queue_hts', 'hts_code', 'query_type'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Query context
    hts_code = db.Column(db.String(20), nullable=False, index=True)
    query_type = db.Column(db.String(32), nullable=False)  # 'section_232', 'section_301'
    material = db.Column(db.String(20), nullable=True)  # 'copper', 'steel', 'aluminum'

    # Link to the raw Gemini response
    search_result_id = db.Column(db.String(36), db.ForeignKey('gemini_search_results.id', ondelete='CASCADE'), nullable=True)

    # LLM outputs (stored for debugging)
    reader_output = db.Column(JSON, nullable=True)  # Future: Reader LLM response
    validator_output = db.Column(JSON, nullable=True)  # Future: Validator LLM response

    # Blocking reason
    block_reason = db.Column(db.Text, nullable=False)  # Why it was queued
    block_details = db.Column(JSON, nullable=True)  # Detailed failure info

    # Review status
    status = db.Column(db.String(20), default='pending')  # pending, validated, rejected, needs_human
    priority = db.Column(db.Integer, default=0)  # Higher = more urgent

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # Reviewer info
    reviewed_by = db.Column(db.String(100), nullable=True)  # Human or 'validator_llm'
    resolution_notes = db.Column(db.Text, nullable=True)

    # Relationship
    search_result = db.relationship('GeminiSearchResult', backref='review_queue_entries')

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "query_type": self.query_type,
            "material": self.material,
            "search_result_id": self.search_result_id,
            "reader_output": self.reader_output,
            "validator_output": self.validator_output,
            "block_reason": self.block_reason,
            "block_details": self.block_details,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reviewed_by": self.reviewed_by,
            "resolution_notes": self.resolution_notes,
        }


class EvidenceQuote(BaseModel):
    """
    v9.2: Normalized citations extracted from Gemini responses.

    Each citation represents a piece of evidence that Gemini used to make
    a scope determination. These are the "proofs" - verbatim quotes from
    official sources that justify the in_scope determination.

    Key differences from GroundingSource:
    - GroundingSource: URLs Gemini observed during search (Layer 1)
    - EvidenceQuote: Specific quoted text Gemini cited as proof (Layer 2)

    Business validation:
    - If in_scope=True, must have at least one EvidenceQuote with quoted_text
    - quoted_text should contain the HTS code (enforced as warning)

    Trust model:
    - quote_verified=False: Gemini's claim (not yet verified)
    - quote_verified=True: Quote confirmed to exist in source URL
    - url_in_grounding_metadata=True: URL was in Google's grounding (higher trust)
    """
    __tablename__ = "evidence_quotes"
    __table_args__ = (
        db.Index('idx_evidence_quote_hts', 'hts_code', 'program_id', 'material'),
        db.Index('idx_evidence_quote_search', 'search_result_id'),
    )

    id = db.Column(db.String(36), primary_key=True)  # UUID

    # Link to search result
    search_result_id = db.Column(db.String(36), db.ForeignKey('gemini_search_results.id', ondelete='CASCADE'), nullable=False)

    # Context
    program_id = db.Column(db.String(50), nullable=False)  # 'section_232', 'section_301'
    material = db.Column(db.String(20), nullable=True)  # 'copper', 'steel', 'aluminum', null
    hts_code = db.Column(db.String(20), nullable=False, index=True)

    # Decision
    in_scope = db.Column(db.Boolean, nullable=True)  # true/false/null (null = unknown)
    claim_code = db.Column(db.String(20), nullable=True)
    disclaim_code = db.Column(db.String(20), nullable=True)

    # Citation details
    source_url = db.Column(db.Text, nullable=True)
    source_domain = db.Column(db.String(255), nullable=True, index=True)
    source_title = db.Column(db.Text, nullable=True)
    source_document = db.Column(db.String(255), nullable=True)  # 'CSMS #65936570'
    effective_date = db.Column(db.Date, nullable=True)
    location_hint = db.Column(db.Text, nullable=True)  # 'Table row: 8544.42.90'
    evidence_type = db.Column(db.String(50), nullable=True)  # 'table', 'paragraph', 'bullet', 'scope_statement'

    # The proof - verbatim quote from the source
    quoted_text = db.Column(db.Text, nullable=True)
    quote_hash = db.Column(db.String(64), nullable=True)  # SHA-256 of quoted_text for deduplication

    # Verification status
    quote_verified = db.Column(db.Boolean, default=False)  # Has quote been verified to exist in source?
    verified_at = db.Column(db.DateTime, nullable=True)
    verification_method = db.Column(db.String(50), nullable=True)  # 'substring', 'pdf_extract', 'manual'

    # Trust signal
    url_in_grounding_metadata = db.Column(db.Boolean, default=False)  # Was URL in Google's grounding?

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    search_result = db.relationship('GeminiSearchResult', backref='evidence_quotes_rel')

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "search_result_id": self.search_result_id,
            "program_id": self.program_id,
            "material": self.material,
            "hts_code": self.hts_code,
            "in_scope": self.in_scope,
            "claim_code": self.claim_code,
            "disclaim_code": self.disclaim_code,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "source_title": self.source_title,
            "source_document": self.source_document,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "location_hint": self.location_hint,
            "evidence_type": self.evidence_type,
            "quoted_text": self.quoted_text,
            "quote_hash": self.quote_hash,
            "quote_verified": self.quote_verified,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verification_method": self.verification_method,
            "url_in_grounding_metadata": self.url_in_grounding_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
