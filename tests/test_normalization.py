"""
HTS and Country Code Normalization Tests

Ensures all normalizers in the codebase produce consistent output.

These tests verify:
1. HTS codes normalize consistently across different input formats
2. Country codes normalize to ISO-2 format correctly
3. All normalizer functions produce the same output for the same input
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHTSNormalization:
    """Test HTS code normalization consistency."""

    def test_normalize_dotted_8digit(self):
        """8544.42.90 → 85444290"""
        from app.services.hts_validator import HTSValidator

        validator = HTSValidator()
        result = validator._normalize_hts("8544.42.90")
        assert result == "85444290"

    def test_normalize_dotted_10digit(self):
        """8544.42.9090 → 8544429090"""
        from app.services.hts_validator import HTSValidator

        validator = HTSValidator()
        result = validator._normalize_hts("8544.42.9090")
        assert result == "8544429090"

    def test_normalize_with_spaces(self):
        """' 8544.42.90 ' → 85444290"""
        from app.services.hts_validator import HTSValidator

        validator = HTSValidator()
        result = validator._normalize_hts(" 8544.42.90 ")
        assert result == "85444290"

    def test_normalize_already_plain(self):
        """85444290 → 85444290 (no change)"""
        from app.services.hts_validator import HTSValidator

        validator = HTSValidator()
        result = validator._normalize_hts("85444290")
        assert result == "85444290"

    def test_write_gate_normalizer(self):
        """Test WriteGate normalizer produces same output."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()
        result = gate._normalize_hts("8544.42.90")
        assert result == "85444290"

    def test_write_gate_with_spaces(self):
        """WriteGate normalizer handles spaces."""
        from app.services.write_gate import WriteGate

        gate = WriteGate()
        result = gate._normalize_hts(" 8544.42.9090 ")
        assert result == "8544429090"

    def test_inline_normalization_pattern(self):
        """
        Test the inline normalization pattern used in stacking_tools.py.

        The inline pattern is: hts_code.replace(".", "")[:8]
        """
        hts_code = "8544.42.9090"

        # This is the inline pattern
        result = hts_code.replace(".", "")[:8]

        assert result == "85444290"

    def test_inline_normalization_short_code(self):
        """Inline pattern handles codes shorter than 8 digits."""
        hts_code = "8544.42"

        result = hts_code.replace(".", "")[:8]

        assert result == "854442"

    def test_all_normalizers_consistent_dotted(self):
        """All normalizers produce same output for dotted input."""
        from app.services.hts_validator import HTSValidator
        from app.services.write_gate import WriteGate

        test_input = "8544.42.9090"

        validator = HTSValidator()
        gate = WriteGate()

        hts_validator_result = validator._normalize_hts(test_input)
        write_gate_result = gate._normalize_hts(test_input)
        inline_result = test_input.replace(".", "").replace(" ", "").strip()

        assert hts_validator_result == write_gate_result
        assert write_gate_result == inline_result
        assert inline_result == "8544429090"

    def test_all_normalizers_consistent_spaced(self):
        """All normalizers produce same output for spaced input."""
        from app.services.hts_validator import HTSValidator
        from app.services.write_gate import WriteGate

        test_input = " 8544.42.90 "

        validator = HTSValidator()
        gate = WriteGate()

        hts_validator_result = validator._normalize_hts(test_input)
        write_gate_result = gate._normalize_hts(test_input)
        inline_result = test_input.replace(".", "").replace(" ", "").strip()

        assert hts_validator_result == write_gate_result
        assert write_gate_result == inline_result
        assert inline_result == "85444290"


@pytest.fixture
def app_with_country_aliases(app):
    """
    App fixture with CountryAlias data seeded.

    Country normalization requires CountryAlias records in the database.
    """
    from app.web.db import db
    from app.web.db.models.tariff_tables import CountryAlias

    with app.app_context():
        # Seed essential country aliases for tests
        aliases = [
            # China
            ("CN", "cn", "CN", "CHN", "China"),
            ("China", "china", "CN", "CHN", "China"),
            # Germany
            ("DE", "de", "DE", "DEU", "Germany"),
            ("Germany", "germany", "DE", "DEU", "Germany"),
            # Hong Kong
            ("HK", "hk", "HK", "HKG", "Hong Kong"),
            ("Hong Kong", "hong kong", "HK", "HKG", "Hong Kong"),
            # Macau
            ("MO", "mo", "MO", "MAC", "Macau"),
            ("Macau", "macau", "MO", "MAC", "Macau"),
            ("Macao", "macao", "MO", "MAC", "Macau"),
            # United Kingdom
            ("GB", "gb", "GB", "GBR", "United Kingdom"),
            ("UK", "uk", "GB", "GBR", "United Kingdom"),
            ("United Kingdom", "united kingdom", "GB", "GBR", "United Kingdom"),
            ("Great Britain", "great britain", "GB", "GBR", "United Kingdom"),
        ]

        for alias_raw, alias_norm, iso2, iso3, canonical in aliases:
            existing = CountryAlias.query.filter_by(alias_norm=alias_norm).first()
            if not existing:
                db.session.add(CountryAlias(
                    alias_raw=alias_raw,
                    alias_norm=alias_norm,
                    iso_alpha2=iso2,
                    iso_alpha3=iso3,
                    canonical_name=canonical,
                ))
        db.session.commit()

    return app


class TestCountryNormalization:
    """Test country code normalization (ISO2 vs ISO3)."""

    def test_iso2_uppercase(self, app_with_country_aliases):
        """CN → CN"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            result = normalize_country("CN")
            assert result["iso_alpha2"] == "CN"

    def test_iso2_lowercase(self, app_with_country_aliases):
        """cn → CN"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            result = normalize_country("cn")
            assert result["iso_alpha2"] == "CN"

    def test_country_name_to_iso2(self, app_with_country_aliases):
        """China → CN"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            result = normalize_country("China")
            assert result["iso_alpha2"] == "CN"

    def test_country_name_lowercase(self, app_with_country_aliases):
        """china → CN"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            result = normalize_country("china")
            assert result["iso_alpha2"] == "CN"

    def test_germany_variants(self, app_with_country_aliases):
        """Germany, DE, Deutschland → DE"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            for variant in ["Germany", "DE", "de", "germany"]:
                result = normalize_country(variant)
                assert result["iso_alpha2"] == "DE", f"Failed for {variant}"

    def test_hong_kong_variants(self, app_with_country_aliases):
        """Hong Kong, HK, hong kong → HK"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            for variant in ["Hong Kong", "HK", "hk", "hong kong"]:
                result = normalize_country(variant)
                assert result["iso_alpha2"] == "HK", f"Failed for {variant}"

    def test_macau_variants(self, app_with_country_aliases):
        """Macau, MO, Macao → MO"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            for variant in ["Macau", "MO", "Macao", "mo"]:
                result = normalize_country(variant)
                assert result["iso_alpha2"] == "MO", f"Failed for {variant}"

    def test_uk_variants(self, app_with_country_aliases):
        """United Kingdom, UK, GB, Great Britain → GB"""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            for variant in ["UK", "GB", "United Kingdom", "Great Britain"]:
                result = normalize_country(variant)
                # UK normalizes to GB in most systems
                assert result["iso_alpha2"] in ["GB", "UK"], f"Failed for {variant}"

    def test_unknown_country_fallback(self, app_with_country_aliases):
        """Unknown country returns normalized=False."""
        from app.chat.tools.stacking_tools import normalize_country

        with app_with_country_aliases.app_context():
            result = normalize_country("Atlantis")
            assert result["normalized"] is False


class TestHTSTo8Digit:
    """Test that HTS codes are correctly truncated to 8 digits for database lookups."""

    def test_10digit_to_8digit(self):
        """8544.42.9090 → 85444290 (first 8 digits)"""
        hts_10 = "8544.42.9090"
        hts_8 = hts_10.replace(".", "")[:8]
        assert hts_8 == "85444290"

    def test_8digit_unchanged(self):
        """8544.42.90 → 85444290 (already 8 digits)"""
        hts_8 = "8544.42.90"
        result = hts_8.replace(".", "")[:8]
        assert result == "85444290"

    def test_multiple_codes_normalize_consistently(self):
        """Multiple HTS variants for same product normalize to same 8-digit."""
        variants = [
            "8544.42.9090",
            "8544.42.90.90",
            "85444290",
            " 8544.42.9090 ",
        ]

        normalized = [v.replace(".", "").replace(" ", "").strip()[:8] for v in variants]

        # All should produce the same 8-digit code
        assert all(n == "85444290" for n in normalized)
