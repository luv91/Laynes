"""
Section 301 Trade Compliance Engine - Core Models

These models implement the Section 301 design document architecture:
- SourceVersion: Audit backbone, tracks all data sources (SCD Type 2)
- TariffMeasure: Temporal tariff rates with full versioning
- ExclusionClaim: Product exclusions with verification workflow
- HtsCodeHistory: HTS code validity tracking for dual indexing

Design Principles:
1. Deterministic Core - No LLM in critical evaluation path
2. SCD Type 2 Versioning - Full audit trail for any historical evaluation
3. No HTS6/4/2 Fallback - Section 301 is enumerated at HTS8/10 only
4. End-Exclusive Dates - effective_start <= entry_date < effective_end

Version: 1.0.0 (Phase 1)
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4

from sqlalchemy import UniqueConstraint, CheckConstraint, Index, or_, case, and_
from app.web.db import db
from app.web.db.models.base import BaseModel


# =============================================================================
# Enums for Type Safety
# =============================================================================

class SourceType(str, Enum):
    """Types of official data sources."""
    USTR_FRN = "USTR_FRN"           # USTR Federal Register Notice (Tier 0)
    USITC_CHINA = "USITC_CHINA"    # USITC China Tariffs CSV (Tier 1)
    USITC_HTS = "USITC_HTS"        # USITC HTS Archive (Tier 1)
    CBP_CSMS = "CBP_CSMS"          # CBP CSMS Bulletins (Tier 2)
    CBP_FAQ = "CBP_FAQ"            # CBP Section 301 FAQs (Tier 2)
    MANUAL = "MANUAL"              # Manual entry (lowest priority)


class Publisher(str, Enum):
    """Publishers of official sources."""
    USTR = "USTR"
    USITC = "USITC"
    CBP = "CBP"
    MANUAL = "MANUAL"


class RateStatus(str, Enum):
    """Status of a tariff rate."""
    CONFIRMED = "confirmed"        # Rate is published and active
    PENDING = "pending"            # Rate is TBD (e.g., semiconductors 2027)
    SCHEDULED = "scheduled"        # Rate is scheduled for future date


class ConfidenceStatus(str, Enum):
    """Confidence level for query results."""
    CONFIRMED = "CONFIRMED"                # Rate is confirmed and active
    SCHEDULED = "SCHEDULED"                # Future date, rate is scheduled
    PENDING_PUBLICATION = "PENDING_PUBLICATION"  # Rate not yet published


class HtsValidationStatus(str, Enum):
    """HTS code validation status."""
    VALID = "VALID"                        # HTS is valid for the date
    INVALID_HTS_FOR_DATE = "INVALID_HTS_FOR_DATE"  # HTS not valid on entry date
    UNKNOWN = "UNKNOWN"                    # Cannot determine validity


class HtsType(str, Enum):
    """HTS code precision level."""
    HTS8 = "HTS8"
    HTS10 = "HTS10"


# =============================================================================
# Source Version Model (Audit Backbone)
# =============================================================================

class SourceVersion(BaseModel):
    """
    Audit backbone - tracks all data sources with versioning.

    Every data change is linked to a source_version, enabling:
    - Full audit trail for compliance defense
    - Reproducibility of any historical evaluation
    - Change detection via content_hash
    - Source hierarchy (Tier 0 > Tier 1 > Tier 2)

    Source Hierarchy:
    - Tier 0: USTR Federal Register Notices (binding legal authority)
    - Tier 1: USITC reference datasets (authoritative)
    - Tier 2: CBP operational guidance (filing guidance)
    """
    __tablename__ = "section_301_source_versions"
    __table_args__ = (
        UniqueConstraint('source_type', 'document_id', 'content_hash',
                        name='uq_301_source_version'),
        Index('idx_301_source_version_lookup', 'source_type', 'document_id'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Source identification
    source_type = db.Column(db.String(32), nullable=False, index=True)
    publisher = db.Column(db.String(32), nullable=False)
    document_id = db.Column(db.String(128), nullable=False)  # FR notice number, CSMS ID, etc.

    # Timestamps
    published_at = db.Column(db.DateTime, nullable=True)     # When source was published
    retrieved_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Content tracking
    content_hash = db.Column(db.String(64), nullable=False, index=True)  # SHA-256

    # Temporal scope (if stated in document)
    effective_start = db.Column(db.Date, nullable=True)
    effective_end = db.Column(db.Date, nullable=True)

    # Supersession tracking
    supersedes_source_version_id = db.Column(
        db.String(36),
        db.ForeignKey("section_301_source_versions.id"),
        nullable=True
    )

    # Artifact storage
    raw_artifact_path = db.Column(db.String(512), nullable=True)

    # Metadata
    title = db.Column(db.String(512), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    supersedes = db.relationship(
        "SourceVersion",
        remote_side=[id],
        backref="superseded_by"
    )

    def get_tier(self) -> int:
        """
        Get source hierarchy tier.
        Lower tier = higher authority.
        """
        tier_map = {
            SourceType.USTR_FRN.value: 0,
            SourceType.USITC_CHINA.value: 1,
            SourceType.USITC_HTS.value: 1,
            SourceType.CBP_CSMS.value: 2,
            SourceType.CBP_FAQ.value: 2,
            SourceType.MANUAL.value: 3,
        }
        return tier_map.get(self.source_type, 3)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "publisher": self.publisher,
            "document_id": self.document_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "content_hash": self.content_hash,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "supersedes_source_version_id": self.supersedes_source_version_id,
            "raw_artifact_path": self.raw_artifact_path,
            "title": self.title,
            "tier": self.get_tier(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Tariff Measure Model (SCD Type 2)
# =============================================================================

class TariffMeasure(BaseModel):
    """
    Section 301 tariff measures with SCD Type 2 versioning.

    Replaces simple rate lookup with full temporal tracking:
    - effective_start/effective_end for time-window queries
    - rate_status for handling TBD rates (semiconductors 2027)
    - legal_basis for compliance documentation
    - source_version_id for audit trail

    Key Query Pattern:
        SELECT * FROM tariff_measures
        WHERE scope_hts_value = ?
        AND effective_start <= ?
        AND (effective_end IS NULL OR effective_end > ?)
        ORDER BY
            CASE scope_hts_type WHEN 'HTS10' THEN 1 ELSE 2 END,
            effective_start DESC
        LIMIT 1

    Design Decision: HTS10 > HTS8 precedence (most specific wins)
    """
    __tablename__ = "section_301_tariff_measures"
    __table_args__ = (
        UniqueConstraint(
            'program', 'ch99_heading', 'scope_hts_type', 'scope_hts_value',
            'effective_start',
            name='uq_301_tariff_measure'
        ),
        Index('idx_301_tariff_measure_hts_date',
              'scope_hts_value', 'effective_start', 'effective_end'),
        Index('idx_301_tariff_measure_ch99', 'ch99_heading'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Program identification
    program = db.Column(db.String(32), nullable=False, index=True)  # "301_NOTE20", "301_NOTE31"

    # Chapter 99 heading
    ch99_heading = db.Column(db.String(16), nullable=False)  # "9903.88.03", "9903.91.01"

    # HTS scope
    scope_hts_type = db.Column(db.String(8), nullable=False)  # "HTS8" or "HTS10"
    scope_hts_value = db.Column(db.String(12), nullable=False, index=True)  # "85444290" or "8544429090"

    # Rate (NULL = TBD)
    additional_rate = db.Column(db.Numeric(6, 4), nullable=True)  # 0.25 for 25%, NULL for TBD
    rate_status = db.Column(db.String(16), nullable=False, default=RateStatus.CONFIRMED.value)

    # Legal reference
    legal_basis = db.Column(db.String(128), nullable=True)  # "Note 31, Subdivision (d)"

    # Temporal validity (end-exclusive: start <= date < end)
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)  # NULL = currently active

    # Classification metadata
    list_name = db.Column(db.String(64), nullable=True)  # "list_1", "list_4a"
    product_group = db.Column(db.String(128), nullable=True)  # "Facemasks", "EVs"
    sector = db.Column(db.String(64), nullable=True)  # "medical", "semiconductor"

    # Audit trail
    source_version_id = db.Column(
        db.String(36),
        db.ForeignKey("section_301_source_versions.id"),
        nullable=True,
        index=True
    )

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    source_version = db.relationship("SourceVersion", backref="tariff_measures")

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if measure is active as of a given date (end-exclusive)."""
        check_date = as_of_date or date.today()
        if self.effective_end:
            return self.effective_start <= check_date < self.effective_end
        return self.effective_start <= check_date

    def get_confidence_status(self, entry_date: date) -> str:
        """
        Get confidence status for this measure on entry_date.

        Returns:
            - CONFIRMED: Rate is confirmed and active
            - SCHEDULED: Future date, rate is scheduled
            - PENDING_PUBLICATION: Rate is TBD
        """
        if self.rate_status == RateStatus.PENDING.value or self.additional_rate is None:
            return ConfidenceStatus.PENDING_PUBLICATION.value

        if entry_date > date.today():
            return ConfidenceStatus.SCHEDULED.value

        return ConfidenceStatus.CONFIRMED.value

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "program": self.program,
            "ch99_heading": self.ch99_heading,
            "scope_hts_type": self.scope_hts_type,
            "scope_hts_value": self.scope_hts_value,
            "additional_rate": float(self.additional_rate) if self.additional_rate else None,
            "rate_status": self.rate_status,
            "legal_basis": self.legal_basis,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "list_name": self.list_name,
            "product_group": self.product_group,
            "sector": self.sector,
            "source_version_id": self.source_version_id,
            "is_active": self.is_active(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def get_measure_as_of(
        cls,
        hts_code: str,
        entry_date: date
    ) -> Optional["TariffMeasure"]:
        """
        Get the applicable tariff measure for an HTS code as of entry_date.

        Implements HTS10 > HTS8 precedence (most specific wins).
        Uses end-exclusive date logic: effective_start <= entry_date < effective_end

        Args:
            hts_code: 8 or 10 digit HTS code (without dots)
            entry_date: Entry/import date

        Returns:
            TariffMeasure if found, None otherwise
        """
        # Normalize HTS code (remove dots)
        hts_normalized = hts_code.replace(".", "").strip()

        # Build query for both HTS10 exact match and HTS8 prefix match
        hts8 = hts_normalized[:8] if len(hts_normalized) >= 8 else hts_normalized

        return cls.query.filter(
            or_(
                # Exact match on HTS10
                and_(
                    cls.scope_hts_type == HtsType.HTS10.value,
                    cls.scope_hts_value == hts_normalized
                ),
                # Match on HTS8 prefix
                and_(
                    cls.scope_hts_type == HtsType.HTS8.value,
                    cls.scope_hts_value == hts8
                )
            ),
            cls.effective_start <= entry_date,
            or_(
                cls.effective_end.is_(None),
                cls.effective_end > entry_date
            )
        ).order_by(
            # HTS10 > HTS8 (most specific wins)
            case((cls.scope_hts_type == HtsType.HTS10.value, 1), else_=2),
            # Most recent first
            cls.effective_start.desc()
        ).first()


# =============================================================================
# HTS Code History Model (Dual Indexing)
# =============================================================================

class HtsCodeHistory(BaseModel):
    """
    HTS code validity tracking for dual indexing.

    Tracks when HTS codes are valid, enabling:
    - Validation that HTS is valid on entry_date
    - Suggestions when code is invalid for date
    - Tracking of code renumbering (replaced_by_code)

    Design Decision: Never silently remap codes.
    Return INVALID_HTS_FOR_DATE + suggested_codes if mismatch.
    """
    __tablename__ = "section_301_hts_code_history"
    __table_args__ = (
        UniqueConstraint('hts_type', 'code', 'valid_from', name='uq_301_hts_code_history'),
        Index('idx_301_hts_code_validity', 'code', 'valid_from', 'valid_to'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # HTS identification
    hts_type = db.Column(db.String(8), nullable=False)  # "HTS8" or "HTS10"
    code = db.Column(db.String(12), nullable=False, index=True)

    # Validity window (end-exclusive)
    valid_from = db.Column(db.Date, nullable=False)
    valid_to = db.Column(db.Date, nullable=True)  # NULL = currently valid

    # Renumbering tracking
    replaced_by_code = db.Column(db.String(12), nullable=True)

    # Optional concept ID for grouping related codes
    canonical_concept_id = db.Column(db.String(36), nullable=True)

    # Description
    description = db.Column(db.Text, nullable=True)

    # Audit trail
    source_version_id = db.Column(
        db.String(36),
        db.ForeignKey("section_301_source_versions.id"),
        nullable=True
    )

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_valid_on(self, check_date: date) -> bool:
        """Check if code is valid on a given date (end-exclusive)."""
        if self.valid_to:
            return self.valid_from <= check_date < self.valid_to
        return self.valid_from <= check_date

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_type": self.hts_type,
            "code": self.code,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "replaced_by_code": self.replaced_by_code,
            "canonical_concept_id": self.canonical_concept_id,
            "description": self.description,
            "source_version_id": self.source_version_id,
            "is_valid_today": self.is_valid_on(date.today()),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def validate_hts_code(
        cls,
        hts_code: str,
        entry_date: date
    ) -> Dict[str, Any]:
        """
        Validate that HTS code is valid on entry_date.

        Returns:
            {
                "status": "VALID" | "INVALID_HTS_FOR_DATE" | "UNKNOWN",
                "suggested_codes": [...] if invalid,
                "replaced_by": code if renumbered
            }
        """
        hts_normalized = hts_code.replace(".", "").strip()
        hts_type = HtsType.HTS10.value if len(hts_normalized) == 10 else HtsType.HTS8.value

        # Look for code in history
        record = cls.query.filter(
            cls.code == hts_normalized,
            cls.hts_type == hts_type
        ).order_by(cls.valid_from.desc()).first()

        if not record:
            # No history record - assume valid (unknown)
            return {
                "status": HtsValidationStatus.UNKNOWN.value,
                "suggested_codes": None,
                "replaced_by": None
            }

        if record.is_valid_on(entry_date):
            return {
                "status": HtsValidationStatus.VALID.value,
                "suggested_codes": None,
                "replaced_by": None
            }

        # Code is not valid on entry_date
        # Find what code replaced it or was valid on that date
        suggested = []

        if record.replaced_by_code:
            suggested.append(record.replaced_by_code)

        # Find codes valid on entry_date with same prefix
        prefix = hts_normalized[:6]
        valid_codes = cls.query.filter(
            cls.code.like(f"{prefix}%"),
            cls.valid_from <= entry_date,
            or_(
                cls.valid_to.is_(None),
                cls.valid_to > entry_date
            )
        ).limit(5).all()

        for vc in valid_codes:
            if vc.code not in suggested:
                suggested.append(vc.code)

        return {
            "status": HtsValidationStatus.INVALID_HTS_FOR_DATE.value,
            "suggested_codes": suggested[:3] if suggested else None,
            "replaced_by": record.replaced_by_code
        }


# =============================================================================
# Exclusion Claim Model
# =============================================================================

class ExclusionClaim(BaseModel):
    """
    Section 301 exclusion claims with verification workflow.

    Exclusions are product-specific exemptions from Section 301 tariffs.
    Design Decision: Soft match + flag (always verification_required=true)

    The LLM (Gemini) helps with:
    - Semantic retrieval of matching exclusions
    - Constraint extraction from scope text
    - Checklist generation for verification

    But NEVER auto-approves. Human review always required.
    """
    __tablename__ = "section_301_exclusion_claims"
    __table_args__ = (
        Index('idx_301_exclusion_claim_hts', 'claim_ch99_heading'),
        Index('idx_301_exclusion_claim_date', 'effective_start', 'effective_end'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Stable exclusion identifier: "vvvi-031", "www-003"
    exclusion_id = db.Column(db.String(32), unique=True, nullable=False)

    # Note bucket (which exclusion list)
    note_bucket = db.Column(db.String(32), nullable=False)  # "20(vvv)(i)", "20(www)"

    # Chapter 99 heading for the exclusion
    claim_ch99_heading = db.Column(db.String(16), nullable=False)  # "9903.88.69", "9903.88.70"

    # Source heading that this exclusion exempts from
    source_heading = db.Column(db.String(16), nullable=True)  # "9903.88.01", "9903.88.02", etc.

    # HTS constraints (JSONB for flexible matching)
    # Example: {"hts8_prefix": ["85369040"], "hts10_exact": ["8536904000"]}
    hts_constraints = db.Column(db.JSON, nullable=True)

    # Description scope text (for semantic matching)
    description_scope_text = db.Column(db.Text, nullable=True)

    # SHA-256 of scope text for change detection across ingestions
    scope_text_hash = db.Column(db.String(64), nullable=True)

    # Temporal validity (end-exclusive)
    effective_start = db.Column(db.Date, nullable=False)
    effective_end = db.Column(db.Date, nullable=True)

    # Verification status (ALWAYS required)
    verification_required = db.Column(db.Boolean, default=True, nullable=False)

    # Audit trail
    source_version_id = db.Column(
        db.String(36),
        db.ForeignKey("section_301_source_versions.id"),
        nullable=True
    )

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_active(self, as_of_date: Optional[date] = None) -> bool:
        """Check if exclusion is active as of a given date (end-exclusive)."""
        check_date = as_of_date or date.today()
        if self.effective_end:
            return self.effective_start <= check_date < self.effective_end
        return self.effective_start <= check_date

    def matches_hts(self, hts_code: str) -> bool:
        """
        Check if HTS code matches this exclusion's constraints.

        This is a preliminary match only - verification still required.
        """
        if not self.hts_constraints:
            return False

        hts_normalized = hts_code.replace(".", "").strip()
        constraints = self.hts_constraints

        # Check exact HTS10 match
        if "hts10_exact" in constraints:
            if hts_normalized in constraints["hts10_exact"]:
                return True

        # Check HTS8 prefix match
        if "hts8_prefix" in constraints:
            hts8 = hts_normalized[:8]
            prefixes = constraints["hts8_prefix"]
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            if hts8 in prefixes or any(hts8.startswith(p) for p in prefixes):
                return True

        return False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "note_bucket": self.note_bucket,
            "claim_ch99_heading": self.claim_ch99_heading,
            "hts_constraints": self.hts_constraints,
            "description_scope_text": self.description_scope_text[:200] + "..."
                if self.description_scope_text and len(self.description_scope_text) > 200
                else self.description_scope_text,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "verification_required": self.verification_required,
            "source_version_id": self.source_version_id,
            "is_active": self.is_active(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def find_exclusion_candidates(
        cls,
        hts_code: str,
        entry_date: date
    ) -> List["ExclusionClaim"]:
        """
        Find exclusion candidates for an HTS code on entry_date.

        Matching priority:
        1. Exact HTS10 match — return only these if any exist
        2. HTS8 prefix fallback — only when no exact HTS10 match found

        NOTE: These are CANDIDATES only. Verification always required.
        """
        hts_normalized = hts_code.replace(".", "").strip()
        hts8 = hts_normalized[:8]

        # Get all active exclusions
        active_exclusions = cls.query.filter(
            cls.effective_start <= entry_date,
            or_(
                cls.effective_end.is_(None),
                cls.effective_end > entry_date
            )
        ).all()

        # Split into exact HTS10 matches vs HTS8 fallback
        exact_hts10 = []
        hts8_fallback = []

        for exc in active_exclusions:
            if not exc.hts_constraints:
                continue
            constraints = exc.hts_constraints

            # Check exact HTS10 match
            if "hts10_exact" in constraints:
                if hts_normalized in constraints["hts10_exact"]:
                    exact_hts10.append(exc)
                    continue

            # Check HTS8 prefix match (fallback only)
            if "hts8_prefix" in constraints:
                prefixes = constraints["hts8_prefix"]
                if isinstance(prefixes, str):
                    prefixes = [prefixes]
                if hts8 in prefixes or any(hts8.startswith(p) for p in prefixes):
                    hts8_fallback.append(exc)

        # Exact HTS10 wins; HTS8 only when no exact match
        return exact_hts10 if exact_hts10 else hts8_fallback


# =============================================================================
# Ingestion Run Model (Pipeline Tracking)
# =============================================================================

class Section301IngestionRun(BaseModel):
    """
    Tracks each ingestion run for the Section 301 pipeline.

    Records:
    - Source processed
    - Rows added/changed/closed
    - Status and any errors
    - Processing time
    """
    __tablename__ = "section_301_ingestion_runs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Source identification
    source_type = db.Column(db.String(32), nullable=False, index=True)
    source_version_id = db.Column(
        db.String(36),
        db.ForeignKey("section_301_source_versions.id"),
        nullable=True
    )

    # Timing
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Statistics
    rows_added = db.Column(db.Integer, default=0)
    rows_changed = db.Column(db.Integer, default=0)
    rows_closed = db.Column(db.Integer, default=0)
    rows_skipped = db.Column(db.Integer, default=0)

    # Status
    status = db.Column(db.String(20), default="running")  # running, success, failed, partial
    error_message = db.Column(db.Text, nullable=True)

    # Metadata
    triggered_by = db.Column(db.String(100), nullable=True)  # "scheduler", "manual", "api"
    notes = db.Column(db.Text, nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_version_id": self.source_version_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": (self.completed_at - self.started_at).total_seconds()
                if self.completed_at and self.started_at else None,
            "rows_added": self.rows_added,
            "rows_changed": self.rows_changed,
            "rows_closed": self.rows_closed,
            "rows_skipped": self.rows_skipped,
            "status": self.status,
            "error_message": self.error_message,
            "triggered_by": self.triggered_by,
        }
