"""
Section 301 Trade Compliance Engine - Deterministic Evaluation Service

This is the DETERMINISTIC CORE of the Section 301 engine.
No LLM in the critical evaluation path.

Implements the 6-step evaluation algorithm:
1. COUNTRY GATE - If COO != CN → No Section 301
2. HTS VALIDATION - Is HTS valid on entry_date?
3. INCLUSION MATCH - Does HTS match tariff measures?
4. EXCLUSION CHECK - Is there an exclusion candidate?
5. RATE STATUS CHECK - Is rate confirmed or pending?
6. FUTURE DATE CHECK - Is entry_date in the future?

Design Principles:
- Pure match + time-window + precedence (no LLM)
- End-exclusive dates: effective_start <= entry_date < effective_end
- HTS10 > HTS8 precedence (most specific wins)
- Exclusions always require verification (never auto-approve)

Version: 1.0.0 (Phase 1)
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from app.models.section301 import (
    TariffMeasure,
    HtsCodeHistory,
    ExclusionClaim,
    SourceVersion,
    ConfidenceStatus,
    HtsValidationStatus,
    RateStatus,
)


# =============================================================================
# Result Data Classes
# =============================================================================

@dataclass
class HtsValidationResult:
    """Result of HTS code validation."""
    status: str  # VALID, INVALID_HTS_FOR_DATE, UNKNOWN
    suggested_codes: Optional[List[str]] = None
    replaced_by: Optional[str] = None


@dataclass
class ExclusionResult:
    """Result of exclusion check."""
    has_candidate: bool
    claim_ch99_heading: Optional[str] = None
    verification_required: bool = True
    verification_packet: Optional[Dict[str, Any]] = None
    candidates: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TemporalResult:
    """Result of temporal/future date check."""
    is_future_date: bool
    confidence_status: str  # CONFIRMED, SCHEDULED, PENDING_PUBLICATION


@dataclass
class Section301Result:
    """
    Full result of Section 301 evaluation.

    This is the final output of the evaluation engine.
    """
    # Core determination
    applies: bool
    reason: Optional[str] = None

    # Rate details (only if applies=True)
    chapter99_heading: Optional[str] = None
    additional_rate: Optional[float] = None
    rate_status: Optional[str] = None  # confirmed, pending
    legal_basis: Optional[str] = None
    source_version: Optional[str] = None

    # Exclusion info
    exclusion: Optional[ExclusionResult] = None

    # Temporal info
    temporal: Optional[TemporalResult] = None

    # HTS validation
    hts_validation: Optional[HtsValidationResult] = None

    # Metadata
    list_name: Optional[str] = None
    product_group: Optional[str] = None
    sector: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response (backward compatible)."""
        result = {
            "applies": self.applies,
            "reason": self.reason,
        }

        if self.applies:
            # Legacy fields for backward compatibility
            result["rate"] = self.additional_rate

            # New fields
            result["chapter99_heading"] = self.chapter99_heading
            result["additional_rate"] = self.additional_rate
            result["rate_status"] = self.rate_status
            result["legal_basis"] = self.legal_basis
            result["source_version"] = self.source_version
            result["list_name"] = self.list_name
            result["product_group"] = self.product_group
            result["sector"] = self.sector

        # Exclusion info
        if self.exclusion:
            result["exclusion"] = {
                "has_candidate": self.exclusion.has_candidate,
                "claim_ch99_heading": self.exclusion.claim_ch99_heading,
                "verification_required": self.exclusion.verification_required,
                "candidates": self.exclusion.candidates,
            }

        # Temporal info
        if self.temporal:
            result["temporal"] = {
                "is_future_date": self.temporal.is_future_date,
                "confidence_status": self.temporal.confidence_status,
            }

        # HTS validation
        if self.hts_validation:
            result["hts_validation"] = {
                "status": self.hts_validation.status,
                "suggested_codes": self.hts_validation.suggested_codes,
                "replaced_by": self.hts_validation.replaced_by,
            }

        return result


# =============================================================================
# Section 301 Evaluation Engine
# =============================================================================

class Section301Engine:
    """
    Deterministic Section 301 evaluation engine.

    Implements the 6-step algorithm from the design document.

    Usage:
        engine = Section301Engine()
        result = engine.evaluate(
            coo="CN",
            hts_code="8544429090",
            entry_date=date(2025, 3, 15)
        )

        if result.applies:
            print(f"301 tariff applies: {result.additional_rate}%")
            print(f"Chapter 99: {result.chapter99_heading}")
        else:
            print(f"No 301 tariff: {result.reason}")
    """

    # Countries subject to Section 301 (China only)
    # Note: HK and MO are NOT CN, so they are automatically excluded
    SECTION_301_COUNTRIES = {"CN"}

    # Country code mappings
    COUNTRY_CODE_MAP = {
        "CN": "CN",
        "CHINA": "CN",
        "CHN": "CN",
        "PRC": "CN",
        "PEOPLES REPUBLIC OF CHINA": "CN",
        # HK and MO are NOT CN
        "HK": "HK",
        "HONG KONG": "HK",
        "HKG": "HK",
        "MO": "MO",
        "MACAU": "MO",
        "MACAO": "MO",
        "MAC": "MO",
    }

    def __init__(self, enable_hts_validation: bool = True):
        """
        Initialize the engine.

        Args:
            enable_hts_validation: Whether to validate HTS codes against history.
                                   Set to False for faster evaluation if HTS
                                   validation is not needed.
        """
        self.enable_hts_validation = enable_hts_validation

    def evaluate(
        self,
        coo: str,
        hts_code: str,
        entry_date: date,
        product_description: Optional[str] = None,
        structured_attributes: Optional[Dict[str, Any]] = None,
    ) -> Section301Result:
        """
        Evaluate Section 301 applicability for a product.

        This is the main entry point implementing the 6-step algorithm.

        Args:
            coo: Country of Origin (ISO-2, ISO-3, or country name)
            hts_code: HTS code (8 or 10 digits, with or without dots)
            entry_date: Entry/import date
            product_description: Optional product description for exclusion matching
            structured_attributes: Optional product attributes for constraint checking

        Returns:
            Section301Result with full evaluation details
        """
        # Normalize inputs
        coo_normalized = self._normalize_coo(coo)
        hts_normalized = hts_code.replace(".", "").strip()

        # =================================================================
        # STEP 1: COUNTRY GATE
        # =================================================================
        if not self._is_section_301_country(coo_normalized):
            return Section301Result(
                applies=False,
                reason=f"COO '{coo}' is not subject to Section 301 (China only)",
            )

        # =================================================================
        # STEP 2: HTS VALIDATION (optional)
        # =================================================================
        hts_validation = None
        if self.enable_hts_validation:
            hts_validation = self._validate_hts_code(hts_normalized, entry_date)

            if hts_validation.status == HtsValidationStatus.INVALID_HTS_FOR_DATE.value:
                return Section301Result(
                    applies=False,
                    reason=f"HTS code '{hts_code}' is not valid on {entry_date}",
                    hts_validation=hts_validation,
                )

        # =================================================================
        # STEP 3: INCLUSION MATCH
        # =================================================================
        measure = TariffMeasure.get_measure_as_of(hts_normalized, entry_date)

        if not measure:
            return Section301Result(
                applies=False,
                reason=f"HTS code '{hts_code}' is not covered by Section 301 on {entry_date}",
                hts_validation=hts_validation,
            )

        # =================================================================
        # STEP 4: EXCLUSION CHECK
        # =================================================================
        exclusion_result = self._check_exclusions(hts_normalized, entry_date)

        # =================================================================
        # STEP 5: RATE STATUS CHECK
        # =================================================================
        rate_status = measure.rate_status
        confidence_status = measure.get_confidence_status(entry_date)

        # =================================================================
        # STEP 6: FUTURE DATE CHECK
        # =================================================================
        is_future = entry_date > date.today()
        temporal_result = TemporalResult(
            is_future_date=is_future,
            confidence_status=confidence_status,
        )

        # =================================================================
        # BUILD FINAL RESULT
        # =================================================================
        source_version_str = None
        if measure.source_version_id:
            sv = SourceVersion.query.get(measure.source_version_id)
            if sv:
                source_version_str = f"{sv.source_type}_{sv.document_id}"

        return Section301Result(
            applies=True,
            chapter99_heading=measure.ch99_heading,
            additional_rate=float(measure.additional_rate) if measure.additional_rate else None,
            rate_status=rate_status,
            legal_basis=measure.legal_basis,
            source_version=source_version_str,
            exclusion=exclusion_result,
            temporal=temporal_result,
            hts_validation=hts_validation,
            list_name=measure.list_name,
            product_group=measure.product_group,
            sector=measure.sector,
        )

    def _normalize_coo(self, coo: str) -> str:
        """
        Normalize country of origin to ISO-2 code.

        Args:
            coo: Country code or name

        Returns:
            ISO-2 code (e.g., "CN", "HK", "MO")
        """
        coo_upper = coo.upper().strip()
        return self.COUNTRY_CODE_MAP.get(coo_upper, coo_upper)

    def _is_section_301_country(self, coo_normalized: str) -> bool:
        """
        Check if country is subject to Section 301.

        Note: Only CN is subject. HK and MO are NOT CN.
        """
        return coo_normalized in self.SECTION_301_COUNTRIES

    def _validate_hts_code(self, hts_code: str, entry_date: date) -> HtsValidationResult:
        """
        Validate HTS code is valid on entry_date.

        Uses HtsCodeHistory table for dual indexing.
        """
        validation = HtsCodeHistory.validate_hts_code(hts_code, entry_date)

        return HtsValidationResult(
            status=validation["status"],
            suggested_codes=validation.get("suggested_codes"),
            replaced_by=validation.get("replaced_by"),
        )

    def _check_exclusions(self, hts_code: str, entry_date: date) -> ExclusionResult:
        """
        Check for exclusion candidates.

        NOTE: This returns CANDIDATES only. Verification is ALWAYS required.
        The engine never auto-approves exclusions.
        """
        candidates = ExclusionClaim.find_exclusion_candidates(hts_code, entry_date)

        if not candidates:
            return ExclusionResult(
                has_candidate=False,
                verification_required=False,  # No candidate = no verification needed
            )

        # Build candidate list for verification packet
        candidate_list = [
            {
                "id": c.id,
                "note_bucket": c.note_bucket,
                "claim_ch99_heading": c.claim_ch99_heading,
                "description_scope_text": c.description_scope_text[:200] + "..."
                    if c.description_scope_text and len(c.description_scope_text) > 200
                    else c.description_scope_text,
                "effective_start": c.effective_start.isoformat(),
                "effective_end": c.effective_end.isoformat() if c.effective_end else None,
            }
            for c in candidates
        ]

        return ExclusionResult(
            has_candidate=True,
            claim_ch99_heading=candidates[0].claim_ch99_heading if candidates else None,
            verification_required=True,  # ALWAYS
            candidates=candidate_list,
            verification_packet={
                "status": "REVIEW_REQUIRED",
                "candidate_count": len(candidates),
                "message": "Exclusion candidate(s) found. Verification required before applying."
            }
        )


# =============================================================================
# Convenience Functions
# =============================================================================

def evaluate_section_301(
    coo: str,
    hts_code: str,
    entry_date: date,
    product_description: Optional[str] = None,
) -> Section301Result:
    """
    Convenience function for Section 301 evaluation.

    Args:
        coo: Country of Origin
        hts_code: HTS code (8 or 10 digits)
        entry_date: Entry/import date
        product_description: Optional product description

    Returns:
        Section301Result

    Example:
        result = evaluate_section_301("CN", "8544429090", date(2025, 3, 15))
        if result.applies:
            print(f"Rate: {result.additional_rate}%")
    """
    engine = Section301Engine()
    return engine.evaluate(coo, hts_code, entry_date, product_description)


def get_section_301_rate(
    hts_code: str,
    entry_date: date,
) -> Optional[float]:
    """
    Get Section 301 rate for a China-origin product.

    This is a simplified function that assumes COO=CN.

    Args:
        hts_code: HTS code
        entry_date: Entry date

    Returns:
        Rate as float (e.g., 0.25 for 25%), or None if no 301 applies
    """
    result = evaluate_section_301("CN", hts_code, entry_date)
    return result.additional_rate if result.applies else None


# =============================================================================
# Singleton Engine Instance
# =============================================================================

_engine: Optional[Section301Engine] = None


def get_section_301_engine() -> Section301Engine:
    """Get the singleton Section 301 engine instance."""
    global _engine
    if _engine is None:
        _engine = Section301Engine()
    return _engine
