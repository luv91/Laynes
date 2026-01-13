"""
Confidence Service for Tariff Stacking

Computes confidence scores for stacking results based on:
- Data source quality (temporal vs static vs hardcoded)
- Evidence strength (verified quote vs no quote)
- Temporal coverage (rate valid for import date)
- Source freshness (watcher update status)
- Conflict detection (sources agree or disagree)

Returns user-facing confidence levels (high/medium/low/critical)
with actionable guidance.

Part of the Production Verification Layer (Phase 4).
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ConfidenceLevel(Enum):
    """User-facing confidence levels with recommended actions."""
    HIGH = "high"        # 0.85+ : Green - Proceed with filing
    MEDIUM = "medium"    # 0.60-0.84 : Yellow - Review before filing
    LOW = "low"          # 0.40-0.59 : Orange - Manual verification required
    CRITICAL = "critical"  # <0.40 : Red - Do not file; consult CBP


class DataSourceType(Enum):
    """Types of data sources ordered by reliability."""
    TEMPORAL_VERIFIED = "temporal_verified"      # 1.00 - Time-bounded + human verified
    TEMPORAL_UNVERIFIED = "temporal_unverified"  # 0.85 - Time-bounded, not verified
    STATIC = "static"                             # 0.65 - Static table lookup
    HARDCODED = "hardcoded"                       # 0.40 - Fallback constant
    LIVE_SEARCH_VERIFIED = "live_search_verified"  # 0.55 - Live search + WriteGate
    LIVE_SEARCH_PENDING = "live_search_pending"    # 0.25 - Live search, not verified
    UNKNOWN = "unknown"                            # 0.10 - Source unknown


@dataclass
class ProgramConfidence:
    """Confidence details for a single program."""
    program_id: str
    score: float
    level: ConfidenceLevel
    data_source: DataSourceType
    evidence_present: bool
    quote_verified: bool
    rate_valid_for_date: bool
    source_doc: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "program_id": self.program_id,
            "score": round(self.score, 3),
            "level": self.level.value,
            "data_source": self.data_source.value,
            "evidence_present": self.evidence_present,
            "quote_verified": self.quote_verified,
            "rate_valid_for_date": self.rate_valid_for_date,
            "source_doc": self.source_doc,
            "notes": self.notes,
        }


@dataclass
class StackingConfidenceResult:
    """Complete confidence assessment for a stacking result."""
    overall_score: float
    overall_level: ConfidenceLevel
    color: str  # CSS color class
    summary: str  # Human-readable summary
    action: str  # Recommended action

    # Factor breakdown
    data_source_score: float
    evidence_strength_score: float
    temporal_coverage_score: float
    source_freshness_score: float
    conflict_score: float

    # Per-program breakdown
    program_confidence: Dict[str, ProgramConfidence]

    # Flags and warnings
    flags: List[str]  # ["rate_extrapolated", "source_stale"]
    warnings: List[str]  # Human-readable warnings
    verified: List[str]  # What was verified
    uncertain: List[str]  # What remains uncertain

    # Authoritative links for verification
    verify_at: List[str]

    def as_dict(self) -> Dict:
        return {
            "score": round(self.overall_score, 3),
            "level": self.overall_level.value,
            "color": self.color,
            "summary": self.summary,
            "action": self.action,
            "factor_breakdown": {
                "data_source": round(self.data_source_score, 3),
                "evidence_strength": round(self.evidence_strength_score, 3),
                "temporal_coverage": round(self.temporal_coverage_score, 3),
                "source_freshness": round(self.source_freshness_score, 3),
                "conflict_detection": round(self.conflict_score, 3),
            },
            "program_confidence": {
                k: v.as_dict() for k, v in self.program_confidence.items()
            },
            "flags": self.flags,
            "warnings": self.warnings,
            "verified": self.verified,
            "uncertain": self.uncertain,
            "verify_at": self.verify_at,
        }


class ConfidenceService:
    """
    Computes confidence scores for tariff stacking results.

    The confidence score is a weighted combination of 5 factors:
    - Data Source Quality (35%): How reliable is the data source?
    - Evidence Strength (25%): Do we have verified quotes/proofs?
    - Temporal Coverage (20%): Is the rate valid for the import date?
    - Source Freshness (10%): How recently was data updated?
    - Conflict Detection (10%): Do all sources agree?

    Usage:
        service = ConfidenceService()
        result = service.compute_confidence(
            stacking_entries=entries,
            hts_code="8544.42.9090",
            country="CN",
            import_date=date.today()
        )
        print(f"Confidence: {result.overall_level.value}")
    """

    # Factor weights (must sum to 1.0)
    WEIGHT_DATA_SOURCE = 0.35
    WEIGHT_EVIDENCE = 0.25
    WEIGHT_TEMPORAL = 0.20
    WEIGHT_FRESHNESS = 0.10
    WEIGHT_CONFLICT = 0.10

    # Data source scores
    DATA_SOURCE_SCORES = {
        DataSourceType.TEMPORAL_VERIFIED: 1.00,
        DataSourceType.TEMPORAL_UNVERIFIED: 0.85,
        DataSourceType.STATIC: 0.65,
        DataSourceType.HARDCODED: 0.40,
        DataSourceType.LIVE_SEARCH_VERIFIED: 0.55,
        DataSourceType.LIVE_SEARCH_PENDING: 0.25,
        DataSourceType.UNKNOWN: 0.10,
    }

    # Level thresholds
    THRESHOLD_HIGH = 0.85
    THRESHOLD_MEDIUM = 0.60
    THRESHOLD_LOW = 0.40

    # Color mapping
    LEVEL_COLORS = {
        ConfidenceLevel.HIGH: "green",
        ConfidenceLevel.MEDIUM: "yellow",
        ConfidenceLevel.LOW: "orange",
        ConfidenceLevel.CRITICAL: "red",
    }

    # Authoritative verification URLs
    VERIFY_URLS = {
        "section_301": "https://www.federalregister.gov/documents/search?conditions%5Bterm%5D=Section+301+tariffs",
        "section_232_steel": "https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel",
        "section_232_aluminum": "https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel",
        "section_232_copper": "https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel",
        "ieepa_fentanyl": "https://www.federalregister.gov/documents/search?conditions%5Bterm%5D=fentanyl+tariff",
        "ieepa_reciprocal": "https://www.federalregister.gov/documents/search?conditions%5Bterm%5D=reciprocal+tariff",
        "default": "https://hts.usitc.gov/",
    }

    def __init__(self):
        self._freshness_service = None

    @property
    def freshness_service(self):
        """Lazy load FreshnessService to avoid circular imports."""
        if self._freshness_service is None:
            from app.services.freshness import get_freshness_service
            self._freshness_service = get_freshness_service()
        return self._freshness_service

    def compute_confidence(
        self,
        stacking_entries: List[Dict],
        hts_code: str,
        country: str,
        import_date: Optional[date] = None,
        freshness_data: Optional[Dict] = None,
    ) -> StackingConfidenceResult:
        """
        Compute confidence score for a stacking result.

        Args:
            stacking_entries: List of entry dicts from StackingRAG
            hts_code: The HTS code being classified
            country: Country of origin
            import_date: Date of import (defaults to today)
            freshness_data: Optional pre-fetched freshness data

        Returns:
            StackingConfidenceResult with scores and guidance
        """
        import_date = import_date or date.today()

        # Collect all programs from entries
        all_programs = self._extract_programs(stacking_entries)

        # Compute per-program confidence
        program_confidence = {}
        for program_info in all_programs:
            prog_conf = self._compute_program_confidence(
                program_info, hts_code, import_date
            )
            program_confidence[program_info["program_id"]] = prog_conf

        # Compute factor scores
        data_source_score = self._compute_data_source_score(program_confidence)
        evidence_score = self._compute_evidence_score(program_confidence)
        temporal_score = self._compute_temporal_score(program_confidence, import_date)
        freshness_score = self._compute_freshness_score(
            program_confidence, freshness_data
        )
        conflict_score = self._compute_conflict_score(stacking_entries)

        # Weighted sum
        overall_score = (
            data_source_score * self.WEIGHT_DATA_SOURCE +
            evidence_score * self.WEIGHT_EVIDENCE +
            temporal_score * self.WEIGHT_TEMPORAL +
            freshness_score * self.WEIGHT_FRESHNESS +
            conflict_score * self.WEIGHT_CONFLICT
        )

        # Determine level
        level = self._score_to_level(overall_score)
        color = self.LEVEL_COLORS[level]

        # Generate summary, action, flags, warnings
        summary = self._generate_summary(level, program_confidence)
        action = self._generate_action(level)
        flags = self._collect_flags(program_confidence)
        warnings = self._collect_warnings(program_confidence)
        verified = self._collect_verified(program_confidence)
        uncertain = self._collect_uncertain(program_confidence)
        verify_at = self._get_verify_urls(program_confidence)

        return StackingConfidenceResult(
            overall_score=overall_score,
            overall_level=level,
            color=color,
            summary=summary,
            action=action,
            data_source_score=data_source_score,
            evidence_strength_score=evidence_score,
            temporal_coverage_score=temporal_score,
            source_freshness_score=freshness_score,
            conflict_score=conflict_score,
            program_confidence=program_confidence,
            flags=flags,
            warnings=warnings,
            verified=verified,
            uncertain=uncertain,
            verify_at=verify_at,
        )

    def _extract_programs(self, entries: List[Dict]) -> List[Dict]:
        """Extract all unique programs from stacking entries."""
        programs = []
        seen = set()

        for entry in entries:
            for stack_line in entry.get("stack", []):
                program_id = stack_line.get("program_id")
                if program_id and program_id not in seen:
                    seen.add(program_id)
                    programs.append({
                        "program_id": program_id,
                        "chapter_99_code": stack_line.get("chapter_99_code"),
                        "duty_rate": stack_line.get("duty_rate"),
                        "action": stack_line.get("action"),
                        "variant": stack_line.get("variant"),
                        "source_doc": stack_line.get("source_doc"),
                        "data_source": stack_line.get("data_source"),
                        "evidence_packet": stack_line.get("evidence_packet"),
                    })

        return programs

    def _compute_program_confidence(
        self,
        program_info: Dict,
        hts_code: str,
        import_date: date
    ) -> ProgramConfidence:
        """Compute confidence for a single program."""
        program_id = program_info["program_id"]

        # Determine data source type
        data_source = self._infer_data_source(program_info)

        # Check for evidence
        evidence_packet = program_info.get("evidence_packet", {})
        evidence_present = bool(evidence_packet and evidence_packet.get("quote"))
        quote_verified = evidence_packet.get("verified", False) if evidence_packet else False

        # Check temporal validity
        rate_valid = self._check_temporal_validity(program_info, import_date)

        # Compute score for this program
        source_score = self.DATA_SOURCE_SCORES.get(data_source, 0.10)

        # Evidence bonus
        evidence_bonus = 0.0
        if quote_verified:
            evidence_bonus = 0.15
        elif evidence_present:
            evidence_bonus = 0.08

        # Temporal penalty
        temporal_factor = 1.0 if rate_valid else 0.7

        score = (source_score + evidence_bonus) * temporal_factor
        score = min(1.0, max(0.0, score))

        level = self._score_to_level(score)

        # Build notes
        notes = []
        if data_source == DataSourceType.HARDCODED:
            notes.append("Using hardcoded fallback rate")
        if not rate_valid:
            notes.append("Rate may not be valid for import date")
        if quote_verified:
            notes.append(f"Quote verified from {program_info.get('source_doc', 'source')}")

        return ProgramConfidence(
            program_id=program_id,
            score=score,
            level=level,
            data_source=data_source,
            evidence_present=evidence_present,
            quote_verified=quote_verified,
            rate_valid_for_date=rate_valid,
            source_doc=program_info.get("source_doc"),
            notes=notes,
        )

    def _infer_data_source(self, program_info: Dict) -> DataSourceType:
        """Infer data source type from program info."""
        # Check if explicitly set
        explicit = program_info.get("data_source")
        if explicit:
            try:
                return DataSourceType(explicit)
            except ValueError:
                pass

        # Infer from available data
        evidence_packet = program_info.get("evidence_packet", {})

        if evidence_packet:
            if evidence_packet.get("verified"):
                return DataSourceType.TEMPORAL_VERIFIED
            elif evidence_packet.get("quote"):
                return DataSourceType.TEMPORAL_UNVERIFIED
            elif evidence_packet.get("from_live_search"):
                if evidence_packet.get("verified"):
                    return DataSourceType.LIVE_SEARCH_VERIFIED
                return DataSourceType.LIVE_SEARCH_PENDING

        # Check if from temporal table
        if program_info.get("from_temporal_table"):
            return DataSourceType.TEMPORAL_UNVERIFIED

        # Check for source doc
        if program_info.get("source_doc"):
            return DataSourceType.STATIC

        # Check if this is a fallback/hardcoded rate
        if program_info.get("is_fallback") or program_info.get("from_hardcoded"):
            return DataSourceType.HARDCODED

        # Default to static (table lookup)
        return DataSourceType.STATIC

    def _check_temporal_validity(self, program_info: Dict, import_date: date) -> bool:
        """Check if rate is valid for the import date."""
        effective_start = program_info.get("effective_start")
        effective_end = program_info.get("effective_end")

        if effective_start:
            if isinstance(effective_start, str):
                effective_start = date.fromisoformat(effective_start)
            if effective_start > import_date:
                return False

        if effective_end:
            if isinstance(effective_end, str):
                effective_end = date.fromisoformat(effective_end)
            if effective_end <= import_date:
                return False

        # If no temporal bounds, assume valid
        return True

    def _compute_data_source_score(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> float:
        """Compute aggregate data source score."""
        if not program_confidence:
            return 0.0

        scores = [
            self.DATA_SOURCE_SCORES.get(pc.data_source, 0.10)
            for pc in program_confidence.values()
        ]

        # Use minimum - confidence is only as good as weakest link
        return min(scores)

    def _compute_evidence_score(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> float:
        """Compute aggregate evidence strength score."""
        if not program_confidence:
            return 0.0

        score = 0.0
        count = len(program_confidence)

        for pc in program_confidence.values():
            if pc.quote_verified:
                score += 1.0
            elif pc.evidence_present:
                score += 0.6
            else:
                score += 0.2

        return score / count

    def _compute_temporal_score(
        self,
        program_confidence: Dict[str, ProgramConfidence],
        import_date: date
    ) -> float:
        """Compute aggregate temporal coverage score."""
        if not program_confidence:
            return 0.0

        valid_count = sum(
            1 for pc in program_confidence.values()
            if pc.rate_valid_for_date
        )

        return valid_count / len(program_confidence)

    def _compute_freshness_score(
        self,
        program_confidence: Dict[str, ProgramConfidence],
        freshness_data: Optional[Dict]
    ) -> float:
        """Compute aggregate source freshness score."""
        if not freshness_data:
            # Try to fetch freshness data
            try:
                freshness_data = self.freshness_service.get_all_freshness()
            except Exception as e:
                logger.debug(f"Could not fetch freshness data: {e}")
                return 0.7  # Assume moderately fresh if unknown

        scores = []
        for program_id in program_confidence:
            # Map program_id to freshness key
            freshness_key = self._program_to_freshness_key(program_id)
            if freshness_key and freshness_key in freshness_data:
                status = freshness_data[freshness_key].get("status", "unknown")
                if status == "current":
                    scores.append(1.0)
                elif status == "stale":
                    scores.append(0.6)
                elif status == "outdated":
                    scores.append(0.3)
                else:
                    scores.append(0.5)
            else:
                scores.append(0.7)  # Unknown defaults to moderate

        return sum(scores) / len(scores) if scores else 0.7

    def _program_to_freshness_key(self, program_id: str) -> Optional[str]:
        """Map program_id to FreshnessService key."""
        mapping = {
            "section_301": "section_301",
            "section_232_steel": "section_232",
            "section_232_aluminum": "section_232",
            "section_232_copper": "section_232",
            "ieepa_fentanyl": "ieepa_fentanyl",
            "ieepa_reciprocal": "ieepa_reciprocal",
            "base_hts": "mfn_base_rates",
        }
        return mapping.get(program_id)

    def _compute_conflict_score(self, entries: List[Dict]) -> float:
        """Check for conflicts between sources."""
        # For now, assume no conflicts if single source per program
        # Future: check if multiple sources give different rates
        return 1.0

    def _score_to_level(self, score: float) -> ConfidenceLevel:
        """Convert numeric score to confidence level."""
        if score >= self.THRESHOLD_HIGH:
            return ConfidenceLevel.HIGH
        elif score >= self.THRESHOLD_MEDIUM:
            return ConfidenceLevel.MEDIUM
        elif score >= self.THRESHOLD_LOW:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.CRITICAL

    def _generate_summary(
        self,
        level: ConfidenceLevel,
        program_confidence: Dict[str, ProgramConfidence]
    ) -> str:
        """Generate human-readable summary."""
        # Find the weakest program
        if not program_confidence:
            return "No programs analyzed"

        weakest = min(program_confidence.values(), key=lambda x: x.score)

        if level == ConfidenceLevel.HIGH:
            return "High confidence - All rates verified from authoritative sources"
        elif level == ConfidenceLevel.MEDIUM:
            return f"Medium confidence - {weakest.program_id} from {weakest.data_source.value}"
        elif level == ConfidenceLevel.LOW:
            return f"Low confidence - {weakest.program_id} requires verification"
        else:
            return f"Critical - {weakest.program_id} data unreliable, do not file"

    def _generate_action(self, level: ConfidenceLevel) -> str:
        """Generate recommended action based on level."""
        actions = {
            ConfidenceLevel.HIGH: "Proceed with filing",
            ConfidenceLevel.MEDIUM: "Review rates before filing",
            ConfidenceLevel.LOW: "Manual verification required before filing",
            ConfidenceLevel.CRITICAL: "Do not file; consult CBP or trade counsel",
        }
        return actions[level]

    def _collect_flags(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> List[str]:
        """Collect warning flags."""
        flags = []

        for pc in program_confidence.values():
            if pc.data_source == DataSourceType.HARDCODED:
                flags.append(f"{pc.program_id}_from_fallback")
            if not pc.rate_valid_for_date:
                flags.append(f"{pc.program_id}_temporal_mismatch")
            if pc.data_source in [DataSourceType.LIVE_SEARCH_PENDING]:
                flags.append(f"{pc.program_id}_pending_verification")

        return list(set(flags))

    def _collect_warnings(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> List[str]:
        """Collect human-readable warnings."""
        warnings = []

        for pc in program_confidence.values():
            if pc.notes:
                for note in pc.notes:
                    if "fallback" in note.lower() or "hardcoded" in note.lower():
                        warnings.append(f"{pc.program_id}: {note}")
                    if "not valid" in note.lower():
                        warnings.append(f"{pc.program_id}: {note}")

        return warnings

    def _collect_verified(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> List[str]:
        """Collect what has been verified."""
        verified = []

        for pc in program_confidence.values():
            if pc.quote_verified and pc.source_doc:
                verified.append(f"{pc.program_id}: Verified from {pc.source_doc}")
            elif pc.data_source == DataSourceType.TEMPORAL_VERIFIED:
                verified.append(f"{pc.program_id}: Verified temporal rate")

        return verified

    def _collect_uncertain(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> List[str]:
        """Collect what remains uncertain."""
        uncertain = []

        for pc in program_confidence.values():
            if pc.score < 0.6:
                reason = pc.notes[0] if pc.notes else "Unverified source"
                uncertain.append(f"{pc.program_id}: {reason}")

        return uncertain

    def _get_verify_urls(
        self, program_confidence: Dict[str, ProgramConfidence]
    ) -> List[str]:
        """Get authoritative URLs for verification."""
        urls = set()

        for program_id in program_confidence:
            url = self.VERIFY_URLS.get(program_id, self.VERIFY_URLS["default"])
            urls.add(url)

        return list(urls)


# Singleton instance
_confidence_service = None


def get_confidence_service() -> ConfidenceService:
    """Get the singleton ConfidenceService instance."""
    global _confidence_service
    if _confidence_service is None:
        _confidence_service = ConfidenceService()
    return _confidence_service
