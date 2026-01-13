"""
HTS Validator Service

Validates HTS codes against the USITC RESTStop API and provides:
- Format validation (8-10 digits, proper structure)
- Existence validation (is this a real HTS code?)
- Caching with TTL to minimize API calls
- Suggestions for similar codes when validation fails

Part of the Production Verification Layer (Phase 1).
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from app.watchers.usitc import USITCWatcher
from app.web.db import db

logger = logging.getLogger(__name__)


@dataclass
class HTSValidationResult:
    """Result of HTS code validation."""
    hts_code: str
    is_valid: bool
    is_format_valid: bool
    exists_in_schedule: Optional[bool]
    description: Optional[str]
    base_rate: Optional[str]
    unit: Optional[str]
    error_message: Optional[str]
    suggestions: List[str]
    cached: bool
    validated_at: datetime

    def as_dict(self) -> Dict:
        return {
            "hts_code": self.hts_code,
            "is_valid": self.is_valid,
            "is_format_valid": self.is_format_valid,
            "exists_in_schedule": self.exists_in_schedule,
            "description": self.description,
            "base_rate": self.base_rate,
            "unit": self.unit,
            "error_message": self.error_message,
            "suggestions": self.suggestions,
            "cached": self.cached,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
        }


class HTSValidator:
    """
    Validates HTS codes for format correctness and existence.

    Uses USITC RESTStop API for verification with local caching
    to minimize API calls.

    Usage:
        validator = HTSValidator()
        result = validator.validate("8544.42.9090")
        if result.is_valid:
            print(f"Valid: {result.description}")
        else:
            print(f"Invalid: {result.error_message}")
            print(f"Did you mean: {result.suggestions}")
    """

    # HTS code format patterns
    # Valid formats: 8544.42.9090, 85444290, 8544.42.90, 854442
    HTS_PATTERN_DOTTED = re.compile(r'^(\d{4})\.(\d{2})\.(\d{2,4})$')
    HTS_PATTERN_PLAIN = re.compile(r'^\d{6,10}$')

    # Cache TTL
    CACHE_TTL_HOURS = 24

    def __init__(self, cache_enabled: bool = True):
        self.cache_enabled = cache_enabled
        self._usitc_watcher = USITCWatcher()
        self._cache: Dict[str, Tuple[HTSValidationResult, datetime]] = {}

    def validate(self, hts_code: str, force_refresh: bool = False) -> HTSValidationResult:
        """
        Validate an HTS code.

        Args:
            hts_code: HTS code to validate (with or without dots)
            force_refresh: Bypass cache and re-validate

        Returns:
            HTSValidationResult with validation details
        """
        # Normalize the code
        normalized = self._normalize_hts(hts_code)

        # Check format first
        format_result = self._validate_format(hts_code, normalized)
        if not format_result.is_format_valid:
            return format_result

        # Check cache
        if self.cache_enabled and not force_refresh:
            cached = self._get_cached(normalized)
            if cached:
                return cached

        # Query USITC API
        result = self._validate_against_usitc(normalized, hts_code)

        # Cache result
        if self.cache_enabled:
            self._cache_result(normalized, result)

        return result

    def _normalize_hts(self, hts_code: str) -> str:
        """
        Normalize HTS code to plain digits.

        Examples:
            "8544.42.9090" -> "8544429090"
            "85444290" -> "85444290"
        """
        return hts_code.replace(".", "").replace(" ", "").strip()

    def _validate_format(self, original: str, normalized: str) -> HTSValidationResult:
        """
        Validate HTS code format.

        Valid formats:
        - 4 digits (chapter heading)
        - 6 digits (subheading)
        - 8 digits (tariff rate line)
        - 10 digits (statistical suffix)
        """
        now = datetime.utcnow()

        # Check if it matches dotted format
        dotted_match = self.HTS_PATTERN_DOTTED.match(original)
        plain_match = self.HTS_PATTERN_PLAIN.match(normalized)

        # Accept dotted format
        if dotted_match:
            return HTSValidationResult(
                hts_code=original,
                is_valid=True,  # Format valid, still need API check
                is_format_valid=True,
                exists_in_schedule=None,
                description=None,
                base_rate=None,
                unit=None,
                error_message=None,
                suggestions=[],
                cached=False,
                validated_at=now,
            )

        # Accept plain format (6-10 digits)
        if plain_match and 6 <= len(normalized) <= 10:
            return HTSValidationResult(
                hts_code=original,
                is_valid=True,
                is_format_valid=True,
                exists_in_schedule=None,
                description=None,
                base_rate=None,
                unit=None,
                error_message=None,
                suggestions=[],
                cached=False,
                validated_at=now,
            )

        # Invalid format
        error = self._get_format_error(original, normalized)
        suggestions = self._suggest_corrections(normalized)

        return HTSValidationResult(
            hts_code=original,
            is_valid=False,
            is_format_valid=False,
            exists_in_schedule=None,
            description=None,
            base_rate=None,
            unit=None,
            error_message=error,
            suggestions=suggestions,
            cached=False,
            validated_at=now,
        )

    def _get_format_error(self, original: str, normalized: str) -> str:
        """Get descriptive error message for format issues."""
        if len(normalized) < 6:
            return f"HTS code '{original}' is too short. HTS codes must be at least 6 digits."
        if len(normalized) > 10:
            return f"HTS code '{original}' is too long. HTS codes are at most 10 digits."
        if not normalized.isdigit():
            non_digits = [c for c in normalized if not c.isdigit()]
            return f"HTS code '{original}' contains invalid characters: {non_digits}"
        return f"HTS code '{original}' has an invalid format."

    def _suggest_corrections(self, normalized: str) -> List[str]:
        """Suggest possible corrections for invalid HTS codes."""
        suggestions = []

        # If too short, suggest padding
        if len(normalized) < 6:
            padded = normalized.ljust(6, '0')
            suggestions.append(f"{padded[:4]}.{padded[4:6]}")

        # If too long, suggest truncating
        if len(normalized) > 10:
            truncated = normalized[:10]
            suggestions.append(f"{truncated[:4]}.{truncated[4:6]}.{truncated[6:10]}")

        # Suggest dotted format
        if len(normalized) >= 6 and len(normalized) <= 10:
            if len(normalized) == 6:
                suggestions.append(f"{normalized[:4]}.{normalized[4:6]}")
            elif len(normalized) == 8:
                suggestions.append(f"{normalized[:4]}.{normalized[4:6]}.{normalized[6:8]}")
            elif len(normalized) == 10:
                suggestions.append(f"{normalized[:4]}.{normalized[4:6]}.{normalized[6:10]}")

        return suggestions

    def _validate_against_usitc(self, normalized: str, original: str) -> HTSValidationResult:
        """
        Validate HTS code against USITC RESTStop API.

        Returns validation result with schedule data if found.
        """
        now = datetime.utcnow()

        try:
            # Query USITC
            result = self._usitc_watcher.verify_hts_code(original)

            if result:
                return HTSValidationResult(
                    hts_code=original,
                    is_valid=True,
                    is_format_valid=True,
                    exists_in_schedule=True,
                    description=result.get("description"),
                    base_rate=result.get("general_rate"),
                    unit=result.get("unit"),
                    error_message=None,
                    suggestions=[],
                    cached=False,
                    validated_at=now,
                )
            else:
                # HTS not found - try to find similar codes
                suggestions = self._find_similar_codes(normalized)

                return HTSValidationResult(
                    hts_code=original,
                    is_valid=False,
                    is_format_valid=True,
                    exists_in_schedule=False,
                    description=None,
                    base_rate=None,
                    unit=None,
                    error_message=f"HTS code '{original}' not found in current schedule.",
                    suggestions=suggestions,
                    cached=False,
                    validated_at=now,
                )

        except Exception as e:
            logger.warning(f"USITC validation failed for {original}: {e}")

            # Return uncertain result - format valid but couldn't verify
            return HTSValidationResult(
                hts_code=original,
                is_valid=True,  # Assume valid if API fails
                is_format_valid=True,
                exists_in_schedule=None,  # Unknown
                description=None,
                base_rate=None,
                unit=None,
                error_message=f"Could not verify with USITC: {str(e)}",
                suggestions=[],
                cached=False,
                validated_at=now,
            )

    def _find_similar_codes(self, normalized: str) -> List[str]:
        """
        Find similar HTS codes when exact match fails.

        Searches for codes with:
        - Same 6-digit prefix
        - Same 4-digit chapter
        """
        suggestions = []

        # Try 8-digit prefix
        if len(normalized) >= 8:
            prefix_8 = normalized[:8]
            try:
                result = self._usitc_watcher.verify_hts_code(prefix_8)
                if result:
                    hts = result.get("hts_code", prefix_8)
                    if hts not in suggestions:
                        suggestions.append(hts)
            except Exception:
                pass

        # Try 6-digit prefix
        if len(normalized) >= 6:
            prefix_6 = normalized[:6]
            try:
                result = self._usitc_watcher.verify_hts_code(prefix_6)
                if result:
                    hts = result.get("hts_code", prefix_6)
                    if hts not in suggestions:
                        suggestions.append(hts)
            except Exception:
                pass

        return suggestions[:3]  # Limit to 3 suggestions

    def _get_cached(self, normalized: str) -> Optional[HTSValidationResult]:
        """Get cached validation result if not expired."""
        if normalized not in self._cache:
            return None

        result, cached_at = self._cache[normalized]
        ttl = timedelta(hours=self.CACHE_TTL_HOURS)

        if datetime.utcnow() - cached_at > ttl:
            del self._cache[normalized]
            return None

        # Return a copy with cached=True
        return HTSValidationResult(
            hts_code=result.hts_code,
            is_valid=result.is_valid,
            is_format_valid=result.is_format_valid,
            exists_in_schedule=result.exists_in_schedule,
            description=result.description,
            base_rate=result.base_rate,
            unit=result.unit,
            error_message=result.error_message,
            suggestions=result.suggestions,
            cached=True,
            validated_at=result.validated_at,
        )

    def _cache_result(self, normalized: str, result: HTSValidationResult):
        """Cache a validation result."""
        self._cache[normalized] = (result, datetime.utcnow())

    def validate_batch(self, hts_codes: List[str]) -> Dict[str, HTSValidationResult]:
        """
        Validate multiple HTS codes.

        Returns dict mapping code to result.
        """
        return {code: self.validate(code) for code in hts_codes}

    def clear_cache(self):
        """Clear the validation cache."""
        self._cache.clear()

    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        now = datetime.utcnow()
        ttl = timedelta(hours=self.CACHE_TTL_HOURS)

        valid_count = sum(1 for _, (_, cached_at) in self._cache.items()
                         if now - cached_at <= ttl)

        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "ttl_hours": self.CACHE_TTL_HOURS,
        }


# Singleton instance
_validator = None


def get_hts_validator() -> HTSValidator:
    """Get the singleton HTSValidator instance."""
    global _validator
    if _validator is None:
        _validator = HTSValidator()
    return _validator
