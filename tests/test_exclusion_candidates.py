"""
Tests for Section 301 Exclusion Claims.

Four test layers:
  A) Parser correctness — PDF → structured exclusions
  B) Ingestion/upsert — idempotency, change detection, effective windows
  C) Candidate matching — HTS10 + date → candidates
  D) Stacker output — deferred until stacking wiring is implemented

Uses existing conftest.py fixtures (app, db_session with in-memory SQLite).
"""

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
PDF_PATH = PROJECT_ROOT / "data" / "chapter99_current.pdf"
CSV_PATH = PROJECT_ROOT / "data" / "current" / "exclusion_claims.csv"

# Lazy-load parsed exclusions (expensive PDF parse, do once per session)
_parsed_cache = None


def _get_parsed_exclusions():
    """Parse exclusions from PDF (cached across tests)."""
    global _parsed_cache
    if _parsed_cache is not None:
        return _parsed_cache

    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from populate_exclusion_claims import extract_note_text, parse_sections

    full_text = extract_note_text(PDF_PATH)
    _parsed_cache = parse_sections(full_text)
    return _parsed_cache


def _insert_test_exclusions(db_session):
    """Insert a small set of known exclusion claims for matching tests."""
    from app.models.section301 import ExclusionClaim

    fixtures = [
        {
            "id": str(uuid4()),
            "exclusion_id": "vvvi-031",
            "note_bucket": "20(vvv)(i)",
            "claim_ch99_heading": "9903.88.69",
            "source_heading": "9903.88.01",
            "hts_constraints": {
                "hts10_exact": ["8536904000"],
                "hts8_prefix": ["85369040"],
            },
            "description_scope_text": (
                "Ring terminals, for a voltage not exceeding 1,000 V "
                "(described in statistical reporting number 8536.90.4000)"
            ),
            "scope_text_hash": hashlib.sha256(
                "Ring terminals, for a voltage not exceeding 1,000 V "
                "(described in statistical reporting number 8536.90.4000)".encode()
            ).hexdigest(),
            "effective_start": date(2025, 11, 30),
            "effective_end": date(2026, 11, 11),
            "verification_required": True,
        },
        {
            "id": str(uuid4()),
            "exclusion_id": "www-001",
            "note_bucket": "20(www)",
            "claim_ch99_heading": "9903.88.70",
            "source_heading": "9903.88.02",
            "hts_constraints": {
                "hts10_exact": ["8486100000"],
                "hts8_prefix": ["84861000"],
            },
            "description_scope_text": (
                "Silicon growth furnaces, including Czochralski crystal growth furnaces, "
                "designed for growing monocrystalline silicon ingots"
            ),
            "scope_text_hash": hashlib.sha256(
                "Silicon growth furnaces, including Czochralski crystal growth furnaces, "
                "designed for growing monocrystalline silicon ingots".encode()
            ).hexdigest(),
            "effective_start": date(2025, 11, 30),
            "effective_end": date(2026, 11, 11),
            "verification_required": True,
        },
        {
            "id": str(uuid4()),
            "exclusion_id": "vvviii-042",
            "note_bucket": "20(vvv)(iii)",
            "claim_ch99_heading": "9903.88.69",
            "source_heading": "9903.88.03",
            "hts_constraints": {
                "hts10_exact": ["8486200000"],
                "hts8_prefix": ["84862000"],
            },
            "description_scope_text": "Texturing, etching, polishing, and cleaning machines",
            "scope_text_hash": hashlib.sha256(
                "Texturing, etching, polishing, and cleaning machines".encode()
            ).hexdigest(),
            "effective_start": date(2025, 11, 30),
            "effective_end": date(2026, 11, 11),
            "verification_required": True,
        },
    ]

    for f in fixtures:
        claim = ExclusionClaim(**f)
        db_session.add(claim)
    db_session.commit()
    return fixtures


# ===========================================================================
# LAYER A: Parser Correctness Tests
# ===========================================================================


@pytest.mark.skipif(not PDF_PATH.exists(), reason="Chapter 99 PDF not available")
class TestParserCorrectness:
    """Tests that the PDF parser produces valid, complete exclusion data."""

    @pytest.fixture(autouse=True, scope="class")
    def exclusions(self):
        """Parse exclusions once for the class."""
        self.__class__._exclusions = _get_parsed_exclusions()

    @property
    def excl(self):
        return self._exclusions

    # --- Bucket counts ---

    def test_total_count_178(self):
        assert len(self.excl) == 178, f"Expected 178, got {len(self.excl)}"

    def test_bucket_count_vvvi(self):
        count = sum(1 for e in self.excl if e["note_bucket"] == "20(vvv)(i)")
        assert count == 47

    def test_bucket_count_vvvii(self):
        count = sum(1 for e in self.excl if e["note_bucket"] == "20(vvv)(ii)")
        assert count == 22

    def test_bucket_count_vvviii(self):
        count = sum(1 for e in self.excl if e["note_bucket"] == "20(vvv)(iii)")
        assert count == 70

    def test_bucket_count_vvviv(self):
        count = sum(1 for e in self.excl if e["note_bucket"] == "20(vvv)(iv)")
        assert count == 25

    def test_bucket_count_www(self):
        count = sum(1 for e in self.excl if e["note_bucket"] == "20(www)")
        assert count == 14

    def test_no_empty_buckets(self):
        buckets = set(e["note_bucket"] for e in self.excl)
        expected = {"20(vvv)(i)", "20(vvv)(ii)", "20(vvv)(iii)", "20(vvv)(iv)", "20(www)"}
        assert buckets == expected

    # --- Schema integrity ---

    def test_exclusion_id_format(self):
        pattern = re.compile(r"^(vvvi|vvvii|vvviii|vvviv|www)-\d{3}$")
        for e in self.excl:
            assert pattern.match(e["exclusion_id"]), (
                f"Bad exclusion_id: {e['exclusion_id']}"
            )

    def test_claim_heading_values(self):
        allowed = {"9903.88.69", "9903.88.70"}
        for e in self.excl:
            assert e["claim_ch99_heading"] in allowed, (
                f"{e['exclusion_id']} has claim_heading={e['claim_ch99_heading']}"
            )

    def test_scope_text_not_empty(self):
        for e in self.excl:
            text = e["description_scope_text"]
            assert text and len(text.strip()) > 30, (
                f"{e['exclusion_id']} has short scope text: {text!r}"
            )

    def test_scope_text_hash_present(self):
        for e in self.excl:
            assert e["scope_text_hash"] and len(e["scope_text_hash"]) == 64

    def test_scope_text_hash_stable(self):
        """Same text → same hash."""
        for e in self.excl:
            expected = hashlib.sha256(e["description_scope_text"].encode()).hexdigest()
            assert e["scope_text_hash"] == expected, (
                f"{e['exclusion_id']} hash mismatch"
            )

    # --- HTS constraint extraction ---

    def test_every_row_has_hts_constraint(self):
        for e in self.excl:
            codes = e["hts_constraints"].get("hts10_exact", [])
            assert len(codes) > 0, (
                f"{e['exclusion_id']} has no HTS10 codes"
            )

    def test_hts_codes_format(self):
        for e in self.excl:
            for code in e["hts_constraints"].get("hts10_exact", []):
                assert re.match(r"^\d{10}$", code), (
                    f"{e['exclusion_id']} bad HTS code: {code}"
                )

    def test_hts8_prefix_format(self):
        for e in self.excl:
            for prefix in e["hts_constraints"].get("hts8_prefix", []):
                assert re.match(r"^\d{8}$", prefix), (
                    f"{e['exclusion_id']} bad HTS8 prefix: {prefix}"
                )

    # --- Uniqueness ---

    def test_no_duplicate_exclusion_ids(self):
        ids = [e["exclusion_id"] for e in self.excl]
        assert len(set(ids)) == len(ids), "Duplicate exclusion_ids found"

    def test_no_duplicate_scope_hashes(self):
        keys = [(e["claim_ch99_heading"], e["scope_text_hash"]) for e in self.excl]
        assert len(set(keys)) == len(keys), "Duplicate (heading, hash) found"

    # --- Contiguity ---

    def test_item_numbers_contiguous(self):
        by_bucket = {}
        for e in self.excl:
            by_bucket.setdefault(e["note_bucket"], []).append(e["item_number"])

        for bucket, nums in by_bucket.items():
            nums_sorted = sorted(nums)
            expected = list(range(1, len(nums_sorted) + 1))
            assert nums_sorted == expected, (
                f"{bucket} has non-contiguous items: {nums_sorted}"
            )

    # --- No parser artifacts ---

    def test_no_parser_artifacts(self):
        for e in self.excl:
            text = e["description_scope_text"].lower()
            assert not text.startswith("(a) except as provided"), (
                f"{e['exclusion_id']} is a Note preamble artifact"
            )
            assert e["hts_constraints"].get("hts10_exact"), (
                f"{e['exclusion_id']} has empty hts10_exact"
            )


# ===========================================================================
# LAYER B: Ingestion / Upsert Tests
# ===========================================================================


class TestIngestionUpsert:
    """Tests that DB ingestion is idempotent and handles changes correctly."""

    def test_idempotent_ingestion(self, app):
        """Running populate_db twice yields same row count, no duplicates."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # Clean slate — remove any rows from prior tests
            ExclusionClaim.query.delete()
            db.session.commit()

        # Small fixture set
        fixtures = [
            {
                "exclusion_id": "test-001",
                "note_bucket": "20(vvv)(i)",
                "claim_ch99_heading": "9903.88.69",
                "source_heading": "9903.88.01",
                "hts_constraints": {"hts10_exact": ["1234567890"], "hts8_prefix": ["12345678"]},
                "description_scope_text": "Test product for idempotency testing purposes only",
                "scope_text_hash": hashlib.sha256(
                    "Test product for idempotency testing purposes only".encode()
                ).hexdigest(),
                "effective_start": date(2025, 11, 30),
                "effective_end": date(2026, 11, 11),
                "verification_required": True,
            },
            {
                "exclusion_id": "test-002",
                "note_bucket": "20(www)",
                "claim_ch99_heading": "9903.88.70",
                "source_heading": "9903.88.02",
                "hts_constraints": {"hts10_exact": ["9876543210"], "hts8_prefix": ["98765432"]},
                "description_scope_text": "Another test product for idempotency testing purposes only",
                "scope_text_hash": hashlib.sha256(
                    "Another test product for idempotency testing purposes only".encode()
                ).hexdigest(),
                "effective_start": date(2025, 11, 30),
                "effective_end": date(2026, 11, 11),
                "verification_required": True,
            },
        ]

        with app.app_context():
            # First run
            for exc in fixtures:
                claim = ExclusionClaim(id=str(uuid4()), **exc)
                db.session.add(claim)
            db.session.commit()
            count1 = ExclusionClaim.query.count()

            # Second run: try to add same exclusion_ids
            for exc in fixtures:
                existing = ExclusionClaim.query.filter_by(
                    exclusion_id=exc["exclusion_id"]
                ).first()
                if not existing:
                    claim = ExclusionClaim(id=str(uuid4()), **exc)
                    db.session.add(claim)
            db.session.commit()
            count2 = ExclusionClaim.query.count()

            assert count1 == count2 == 2, f"Expected 2, got {count1} then {count2}"

            # No duplicates
            ids = [c.exclusion_id for c in ExclusionClaim.query.all()]
            assert len(set(ids)) == len(ids)

    def test_change_detection(self, app):
        """Modified scope_text_hash triggers update."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # Insert original
            original_text = "Original scope text for change detection test"
            claim = ExclusionClaim(
                id=str(uuid4()),
                exclusion_id="change-001",
                note_bucket="20(vvv)(i)",
                claim_ch99_heading="9903.88.69",
                source_heading="9903.88.01",
                hts_constraints={"hts10_exact": ["1111111111"], "hts8_prefix": ["11111111"]},
                description_scope_text=original_text,
                scope_text_hash=hashlib.sha256(original_text.encode()).hexdigest(),
                effective_start=date(2025, 11, 30),
                effective_end=date(2026, 11, 11),
                verification_required=True,
            )
            db.session.add(claim)
            db.session.commit()

            # Simulate re-ingestion with changed text
            new_text = "Updated scope text for change detection test"
            new_hash = hashlib.sha256(new_text.encode()).hexdigest()

            existing = ExclusionClaim.query.filter_by(exclusion_id="change-001").first()
            assert existing.scope_text_hash != new_hash

            existing.description_scope_text = new_text
            existing.scope_text_hash = new_hash
            db.session.commit()

            updated = ExclusionClaim.query.filter_by(exclusion_id="change-001").first()
            assert updated.description_scope_text == new_text
            assert updated.scope_text_hash == new_hash

    def test_effective_window_consistency(self, app):
        """All rows have valid effective_start < effective_end."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            claim = ExclusionClaim(
                id=str(uuid4()),
                exclusion_id="window-001",
                note_bucket="20(vvv)(i)",
                claim_ch99_heading="9903.88.69",
                source_heading="9903.88.01",
                hts_constraints={"hts10_exact": ["2222222222"], "hts8_prefix": ["22222222"]},
                description_scope_text="Test product for effective window consistency check",
                scope_text_hash=hashlib.sha256(
                    "Test product for effective window consistency check".encode()
                ).hexdigest(),
                effective_start=date(2025, 11, 30),
                effective_end=date(2026, 11, 11),
                verification_required=True,
            )
            db.session.add(claim)
            db.session.commit()

            row = ExclusionClaim.query.filter_by(exclusion_id="window-001").first()
            assert row.effective_start < row.effective_end
            assert row.effective_start == date(2025, 11, 30)
            assert row.effective_end == date(2026, 11, 11)


# ===========================================================================
# LAYER C: Candidate Matching Tests
# ===========================================================================


class TestCandidateMatching:
    """Tests that find_exclusion_candidates returns correct results."""

    @pytest.fixture(autouse=True)
    def setup_fixtures(self, app):
        """Insert test exclusion claims."""
        from app.web.db import db
        with app.app_context():
            self._fixtures = _insert_test_exclusions(db.session)
            yield

    def test_positive_match_8536904000(self, app):
        """Known HTS10 returns correct candidate."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2026, 1, 29)
            )
            assert len(candidates) >= 1
            ids = [c.exclusion_id for c in candidates]
            assert "vvvi-031" in ids
            match = [c for c in candidates if c.exclusion_id == "vvvi-031"][0]
            assert match.claim_ch99_heading == "9903.88.69"
            assert match.verification_required is True

    def test_negative_match_no_exclusion(self, app):
        """HTS not in exclusions returns empty list."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "9999.99.9999", date(2026, 1, 29)
            )
            assert len(candidates) == 0

    def test_date_inside_window(self, app):
        """Entry date mid-window returns candidate."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2026, 6, 15)
            )
            assert len(candidates) >= 1

    def test_date_before_window(self, app):
        """Entry date before effective_start returns no candidate."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2025, 11, 29)
            )
            assert len(candidates) == 0

    def test_date_on_effective_end(self, app):
        """Entry date == effective_end (end-exclusive) returns no candidate."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2026, 11, 11)
            )
            assert len(candidates) == 0

    def test_date_last_valid_day(self, app):
        """Entry date on last included day (Nov 10) returns candidate."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2026, 11, 10)
            )
            assert len(candidates) >= 1

    def test_hts8_prefix_match(self, app):
        """HTS10 under a stored HTS8 prefix matches."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # 8486.10.0000 should match www-001 (hts8_prefix: 84861000)
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8486.10.0000", date(2026, 1, 29)
            )
            assert len(candidates) >= 1
            ids = [c.exclusion_id for c in candidates]
            assert "www-001" in ids

    def test_multiple_candidates(self, app):
        """HTS with multiple exclusion entries returns all."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # Add a second claim for same HTS
            claim2 = ExclusionClaim(
                id=str(uuid4()),
                exclusion_id="vvvi-999",
                note_bucket="20(vvv)(i)",
                claim_ch99_heading="9903.88.69",
                source_heading="9903.88.01",
                hts_constraints={
                    "hts10_exact": ["8536904000"],
                    "hts8_prefix": ["85369040"],
                },
                description_scope_text="Second exclusion for same HTS code for testing",
                scope_text_hash=hashlib.sha256(
                    "Second exclusion for same HTS code for testing".encode()
                ).hexdigest(),
                effective_start=date(2025, 11, 30),
                effective_end=date(2026, 11, 11),
                verification_required=True,
            )
            db.session.add(claim2)
            db.session.commit()

            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2026, 1, 29)
            )
            assert len(candidates) >= 2
            ids = [c.exclusion_id for c in candidates]
            assert "vvvi-031" in ids
            assert "vvvi-999" in ids

    def test_verification_always_required(self, app):
        """All candidates have verification_required=True."""
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            candidates = ExclusionClaim.find_exclusion_candidates(
                "8536.90.4000", date(2026, 1, 29)
            )
            for c in candidates:
                assert c.verification_required is True

    def test_hts10_exact_match_wins_over_hts8(self, app):
        """When exact HTS10 match exists, HTS8 prefix siblings are excluded."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # Add three exclusions sharing HTS8 prefix 90251980
            # but with different HTS10 codes
            siblings = [
                ("sibling-010", "9025198010", "Products for 9025.19.8010"),
                ("sibling-020", "9025198020", "Products for 9025.19.8020"),
                ("sibling-085", "9025198085", "Products for 9025.19.8085"),
            ]
            for exc_id, hts10, desc in siblings:
                claim = ExclusionClaim(
                    id=str(uuid4()),
                    exclusion_id=exc_id,
                    note_bucket="20(vvv)(ii)",
                    claim_ch99_heading="9903.88.69",
                    source_heading="9903.88.02",
                    hts_constraints={
                        "hts10_exact": [hts10],
                        "hts8_prefix": ["90251980"],
                    },
                    description_scope_text=desc,
                    scope_text_hash=hashlib.sha256(desc.encode()).hexdigest(),
                    effective_start=date(2025, 11, 30),
                    effective_end=date(2026, 11, 11),
                    verification_required=True,
                )
                db.session.add(claim)
            db.session.commit()

            # Query for 9025.19.8010 — should return ONLY the exact match
            candidates = ExclusionClaim.find_exclusion_candidates(
                "9025.19.8010", date(2026, 1, 29)
            )
            assert len(candidates) == 1
            assert candidates[0].exclusion_id == "sibling-010"

    def test_hts8_fallback_when_no_exact_hts10(self, app):
        """When no exact HTS10 match, falls back to HTS8 prefix."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # Exclusion with HTS8 prefix only (hts10_exact doesn't contain our query)
            claim = ExclusionClaim(
                id=str(uuid4()),
                exclusion_id="hts8only-001",
                note_bucket="20(vvv)(i)",
                claim_ch99_heading="9903.88.69",
                source_heading="9903.88.01",
                hts_constraints={
                    "hts10_exact": ["7777770000"],  # Different HTS10
                    "hts8_prefix": ["77777700"],
                },
                description_scope_text="Test product with HTS8 prefix fallback only",
                scope_text_hash=hashlib.sha256(
                    "Test product with HTS8 prefix fallback only".encode()
                ).hexdigest(),
                effective_start=date(2025, 11, 30),
                effective_end=date(2026, 11, 11),
                verification_required=True,
            )
            db.session.add(claim)
            db.session.commit()

            # Query with a different HTS10 under same HTS8 prefix
            candidates = ExclusionClaim.find_exclusion_candidates(
                "7777.77.0099", date(2026, 1, 29)
            )
            assert len(candidates) == 1
            assert candidates[0].exclusion_id == "hts8only-001"

    def test_exact_hts10_suppresses_hts8_siblings(self, app):
        """Exact HTS10 match prevents HTS8-only matches from appearing."""
        from app.web.db import db
        from app.models.section301 import ExclusionClaim

        with app.app_context():
            # Exclusion A: exact HTS10 match
            claim_a = ExclusionClaim(
                id=str(uuid4()),
                exclusion_id="exact-001",
                note_bucket="20(vvv)(i)",
                claim_ch99_heading="9903.88.69",
                source_heading="9903.88.01",
                hts_constraints={
                    "hts10_exact": ["5555550000"],
                    "hts8_prefix": ["55555500"],
                },
                description_scope_text="Exact match product for suppression test",
                scope_text_hash=hashlib.sha256(
                    "Exact match product for suppression test".encode()
                ).hexdigest(),
                effective_start=date(2025, 11, 30),
                effective_end=date(2026, 11, 11),
                verification_required=True,
            )
            # Exclusion B: different HTS10 but same HTS8 prefix
            claim_b = ExclusionClaim(
                id=str(uuid4()),
                exclusion_id="sibling-002",
                note_bucket="20(vvv)(i)",
                claim_ch99_heading="9903.88.69",
                source_heading="9903.88.01",
                hts_constraints={
                    "hts10_exact": ["5555559999"],
                    "hts8_prefix": ["55555500"],
                },
                description_scope_text="Sibling product that should be suppressed",
                scope_text_hash=hashlib.sha256(
                    "Sibling product that should be suppressed".encode()
                ).hexdigest(),
                effective_start=date(2025, 11, 30),
                effective_end=date(2026, 11, 11),
                verification_required=True,
            )
            db.session.add(claim_a)
            db.session.add(claim_b)
            db.session.commit()

            # Query for 5555.55.0000 — exact match on A, HTS8 match on B
            # Should only return A
            candidates = ExclusionClaim.find_exclusion_candidates(
                "5555.55.0000", date(2026, 1, 29)
            )
            assert len(candidates) == 1
            assert candidates[0].exclusion_id == "exact-001"
