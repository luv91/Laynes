#!/usr/bin/env python3
"""
v21.1: IEEPA Reciprocal Rate Schedule Expansion — Yale Bootstrap

Ingests ~137 missing countries into ieepa_reciprocal_rate_schedule.
Protects all existing entries via skip-set from DB query.

Data Sources:
  1. Yale Budget Lab YAML (headline_rates): census code → rate
  2. Census-to-ISO mapping CSV: census code → ISO alpha-2
  3. EO 14326 Annex II CSV: ISO → Ch.99 heading code + rate

Strategy:
  - ANNEX CHECK FIRST: if country has a 9903.02.XX heading → FIXED_RATE
  - ELSE rate == 0.10 → BASELINE_10, ch99='9903.01.25', NON_ANNEX_I
  - ELSE rate > 0.10 → HARD FAIL (data gap — needs investigation)

Usage:
    python scripts/ingest_ieepa_reciprocal_yale_expansion.py --dry-run
    python scripts/ingest_ieepa_reciprocal_yale_expansion.py
    python scripts/ingest_ieepa_reciprocal_yale_expansion.py --skip-verify
    python scripts/ingest_ieepa_reciprocal_yale_expansion.py --local-yaml path/to/file.yaml
"""

import argparse
import csv
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests
import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.web import create_app
from app.web.db import db
from app.web.db.models.tariff_tables import IeepaReciprocalRateSchedule


# =============================================================================
# Constants
# =============================================================================

YALE_YAML_URL = (
    "https://raw.githubusercontent.com/Budget-Lab-Yale/Tariff-ETRs/"
    "main/config/12-4/ieepa_reciprocal.yaml"
)

# EU-27 ISO codes (for skip-set awareness during cross-verification)
EU_MEMBER_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}

DATASET_TAG = "v21.1_yale_expansion"
EO_14326_EFFECTIVE = date(2025, 8, 7)
EO_14326_LEGAL = "EO 14326"
EO_14326_FR = "90 FR 37963"


# =============================================================================
# Phase A: Load Data Sources
# =============================================================================

def load_yale_yaml(local_path: str | None = None) -> dict[int, float]:
    """Load Yale Budget Lab headline_rates from YAML.

    Returns dict: census_code (int) → rate (float, e.g. 0.41 for 41%).
    """
    if local_path:
        print(f"  Loading local YAML: {local_path}")
        with open(local_path) as f:
            data = yaml.safe_load(f)
    else:
        print(f"  Downloading Yale YAML from GitHub...")
        resp = requests.get(YALE_YAML_URL, timeout=30)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)

    rates = data["headline_rates"]
    # Extract numeric entries only (skip 'default' key)
    result = {}
    for key, value in rates.items():
        if isinstance(key, int):
            result[key] = float(value)
    default = float(rates.get("default", 0.10))
    print(f"    {len(result)} country entries, default={default}")
    return result


def load_census_mapping(csv_path: Path) -> dict[int, dict]:
    """Load census-to-ISO mapping.

    Returns dict: census_code → {'iso': 'XX', 'name': '...', 'skip': bool}
    """
    mapping = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping[int(row["census_code"])] = {
                "iso": row["iso_alpha2"],
                "name": row["country_name"],
                "skip": bool(row.get("skip", "").strip()),
            }
    print(f"    {len(mapping)} census codes loaded")
    return mapping


def load_annex_csv(csv_path: Path) -> dict[str, dict]:
    """Load EO 14326 Annex II Ch.99 codes.

    Returns dict: iso_alpha2 → {'ch99': '9903.02.XX', 'rate': 15, 'country': '...'}
    Only includes standard country entries (not transshipment or EU special).
    """
    annex = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            iso = row["iso_alpha2"]
            special = row.get("special", "")
            if not iso or special in ("TRANSSHIPMENT", "MFN_CEILING_ZERO", "MFN_CEILING_TOPUP"):
                continue
            # EU special code appears as iso=EU — skip it
            if iso == "EU":
                continue
            annex[iso] = {
                "ch99": row["ch99_code"],
                "rate": int(row["rate_pct"]),
                "country": row["country_name"],
            }
    print(f"    {len(annex)} country headings loaded")
    return annex


# =============================================================================
# Phase B: Cross-Verification
# =============================================================================

def cross_verify(
    yale_rates: dict[int, float],
    census_map: dict[int, dict],
    annex: dict[str, dict],
) -> tuple[bool, list[str]]:
    """Cross-verify Yale rates against Annex II rates.

    Returns (passed: bool, messages: list[str]).
    """
    messages = []
    mismatches = []
    matches = 0

    # Build Yale ISO → rate lookup
    yale_by_iso = {}
    for census_code, rate in yale_rates.items():
        info = census_map.get(census_code)
        if not info or info["skip"] or not info["iso"]:
            continue
        yale_by_iso[info["iso"]] = {
            "rate": int(round(rate * 100)),
            "census": census_code,
            "name": info["name"],
        }

    # Check rate matches for countries in BOTH sources
    for iso, annex_entry in sorted(annex.items()):
        yale_entry = yale_by_iso.get(iso)
        if not yale_entry:
            messages.append(f"  Annex has {iso} ({annex_entry['country']}) but NOT in Yale")
            continue

        if yale_entry["rate"] == annex_entry["rate"]:
            matches += 1
        else:
            msg = (
                f"  MISMATCH: {iso} ({annex_entry['country']}) "
                f"Yale={yale_entry['rate']}% vs Annex={annex_entry['rate']}%"
            )
            mismatches.append(msg)
            messages.append(msg)

    # Check Annex countries missing from Yale
    annex_isos = set(annex.keys())
    yale_isos = set(yale_by_iso.keys())
    annex_only = annex_isos - yale_isos
    if annex_only:
        messages.append(f"\n  Annex countries NOT in Yale ({len(annex_only)}): {sorted(annex_only)}")

    # Check Yale >10% countries missing from Annex (exclude EU members)
    yale_gt10_not_annex = []
    for iso, entry in sorted(yale_by_iso.items()):
        if entry["rate"] > 10 and iso not in annex and iso not in EU_MEMBER_CODES:
            yale_gt10_not_annex.append(f"{iso} ({entry['name']}, {entry['rate']}%)")
    if yale_gt10_not_annex:
        messages.append(
            f"\n  Yale countries >10% NOT in Annex (non-EU) ({len(yale_gt10_not_annex)}):"
        )
        for item in yale_gt10_not_annex:
            messages.append(f"    {item}")

    # Summary
    messages.insert(0, f"  Rate matches: {matches}")
    messages.insert(1, f"  Rate mismatches: {len(mismatches)}")

    # Classify mismatches:
    # 1. Deal overrides (CH, LI, JP, KR): Yale shows post-deal rate, Annex shows original
    # 2. Subsequent reductions (Yale < Annex): country rate was lowered by later EO
    # 3. Unexpected (Yale > Annex): would indicate genuine data gap
    known_deal_overrides = {"CH", "LI", "JP", "KR"}
    unexpected = []
    for iso, annex_entry in sorted(annex.items()):
        yale_entry = yale_by_iso.get(iso)
        if not yale_entry or yale_entry["rate"] == annex_entry["rate"]:
            continue
        # This is a mismatched country
        if iso in known_deal_overrides:
            continue
        if yale_entry["rate"] < annex_entry["rate"]:
            # Yale rate lower than Annex — subsequent reduction, acceptable
            messages.append(
                f"  NOTE: {iso} ({annex_entry['country']}) rate likely reduced after EO 14326 "
                f"(Annex={annex_entry['rate']}% → Yale={yale_entry['rate']}%)"
            )
            continue
        # Yale rate > Annex rate — unexpected
        unexpected.append(
            f"  {iso} ({annex_entry['country']}): Yale={yale_entry['rate']}% > Annex={annex_entry['rate']}%"
        )

    passed = len(unexpected) == 0
    if not passed:
        messages.append("\n  UNEXPECTED mismatches (Yale rate > Annex rate):")
        for m in unexpected:
            messages.append(f"    {m}")

    return passed, messages


# =============================================================================
# Phase C: Skip Set
# =============================================================================

def build_skip_set() -> set[str]:
    """Query all existing country_code values from DB.

    Returns set of ISO alpha-2 codes already in the rate schedule.
    None (baseline) is excluded from the set.
    """
    existing = IeepaReciprocalRateSchedule.query.with_entities(
        IeepaReciprocalRateSchedule.country_code
    ).distinct().all()
    return {r[0] for r in existing if r[0] is not None}


# =============================================================================
# Phase D: Build Insert Records
# =============================================================================

def build_insert_records(
    yale_rates: dict[int, float],
    census_map: dict[int, dict],
    annex: dict[str, dict],
    skip_set: set[str],
) -> tuple[list[dict], list[str]]:
    """Build rate records for countries NOT in skip set.

    Returns (records: list[dict], hard_fails: list[str]).
    """
    records = []
    hard_fails = []
    skipped_exempt = 0
    skipped_existing = 0
    skipped_territory = 0
    skipped_eu_member = 0
    annex_inserts = 0
    baseline_inserts = 0

    for census_code, rate in sorted(yale_rates.items()):
        info = census_map.get(census_code)
        if not info:
            continue

        # Skip US territories and unmapped entries
        if info["skip"] or not info["iso"]:
            skipped_territory += 1
            continue

        iso = info["iso"]

        # Skip exempt countries (rate == 0)
        if rate == 0.0:
            skipped_exempt += 1
            continue

        # Skip countries already in DB
        if iso in skip_set:
            skipped_existing += 1
            continue

        # Skip EU members — they use MFN ceiling (9903.02.19/20), not FIXED_RATE.
        # They should be ingested by the base script (ingest_ieepa_reciprocal_rates.py),
        # not by this expansion script.
        if iso in EU_MEMBER_CODES:
            skipped_eu_member += 1
            continue

        rate_pct = int(round(rate * 100))

        # ANNEX CHECK FIRST: if country has a specific 9903.02.XX heading
        if iso in annex:
            annex_entry = annex[iso]
            records.append({
                "country_code": iso,
                "country_group": "ANNEX_I",
                "regime_type": "FIXED_RATE",
                "rate_pct": Decimal(str(annex_entry["rate"])) + Decimal("0.00"),
                "ceiling_pct": None,
                "ch99_code": annex_entry["ch99"],
                "ch99_mfn_zero": None,
                "ch99_mfn_topup": None,
                "effective_start": EO_14326_EFFECTIVE,
                "effective_end": date(9999, 12, 31),
                "legal_authority": EO_14326_LEGAL,
                "fr_citation": EO_14326_FR,
                "deal_name": None,
                "source_doc_id": None,
                "dataset_tag": DATASET_TAG,
            })
            annex_inserts += 1

        elif rate_pct == 10:
            # Non-Annex baseline country at 10%
            records.append({
                "country_code": iso,
                "country_group": "NON_ANNEX_I",
                "regime_type": "BASELINE_10",
                "rate_pct": Decimal("10.00"),
                "ceiling_pct": None,
                "ch99_code": "9903.01.25",
                "ch99_mfn_zero": None,
                "ch99_mfn_topup": None,
                "effective_start": EO_14326_EFFECTIVE,
                "effective_end": date(9999, 12, 31),
                "legal_authority": EO_14326_LEGAL,
                "fr_citation": EO_14326_FR,
                "deal_name": None,
                "source_doc_id": None,
                "dataset_tag": DATASET_TAG,
            })
            baseline_inserts += 1

        else:
            # Rate > 10% but no Annex entry — data gap
            hard_fails.append(
                f"  {iso} ({info['name']}): Yale={rate_pct}% but no Annex Ch.99 heading"
            )

    print(f"\n  Build results:")
    print(f"    Skipped (US territory/unmapped): {skipped_territory}")
    print(f"    Skipped (exempt, rate=0):        {skipped_exempt}")
    print(f"    Skipped (already in DB):         {skipped_existing}")
    print(f"    Skipped (EU member/MFN ceiling): {skipped_eu_member}")
    print(f"    Annex I inserts (FIXED_RATE):    {annex_inserts}")
    print(f"    Non-Annex inserts (BASELINE_10): {baseline_inserts}")
    print(f"    Hard fails (data gaps):          {len(hard_fails)}")
    print(f"    Total records to insert:         {len(records)}")

    return records, hard_fails


# =============================================================================
# Phase E: Upsert
# =============================================================================

def upsert_records(records: list[dict], dry_run: bool = False) -> dict:
    """Upsert records into ieepa_reciprocal_rate_schedule.

    Reuses the upsert pattern from ingest_ieepa_reciprocal_rates.py.
    """
    stats = {
        "total": len(records),
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "existing_before": IeepaReciprocalRateSchedule.query.count(),
    }

    for rate_data in records:
        existing = IeepaReciprocalRateSchedule.query.filter_by(
            country_code=rate_data["country_code"],
            effective_start=rate_data["effective_start"],
            dataset_tag=rate_data["dataset_tag"],
        ).first()

        if existing:
            needs_update = any(
                getattr(existing, k, None) != v for k, v in rate_data.items()
            )
            if needs_update:
                if not dry_run:
                    for key, value in rate_data.items():
                        setattr(existing, key, value)
                stats["updated"] += 1
            else:
                stats["unchanged"] += 1
        else:
            if not dry_run:
                new_rate = IeepaReciprocalRateSchedule(**rate_data)
                db.session.add(new_rate)
            stats["inserted"] += 1

    if not dry_run:
        db.session.commit()

    return stats


# =============================================================================
# Phase F: Post-Ingestion Validation
# =============================================================================

def post_validation(annex: dict[str, dict]):
    """Spot-check critical entries after ingestion."""
    checks = [
        ("KH", "Cambodia", 19, "9903.02.11"),
        ("AF", "Afghanistan", 15, "9903.02.02"),
        ("DZ", "Algeria", 30, "9903.02.03"),
        ("BR", "Brazil", 10, "9903.02.09"),
        ("VN", "Vietnam", 20, "9903.02.69"),
        ("TH", "Thailand", 19, "9903.02.61"),
    ]

    print("\n  Spot checks:")
    all_ok = True
    for iso, name, expected_rate, expected_ch99 in checks:
        row = IeepaReciprocalRateSchedule.query.filter_by(
            country_code=iso,
            dataset_tag=DATASET_TAG,
        ).first()
        if not row:
            # Might be in skip set (existing entry with different dataset_tag)
            row = IeepaReciprocalRateSchedule.query.filter_by(
                country_code=iso,
            ).order_by(IeepaReciprocalRateSchedule.effective_start.desc()).first()
            if row:
                print(f"    {iso} ({name}): existing row (tag={row.dataset_tag}), rate={row.rate_pct}% — in skip set")
            else:
                print(f"    {iso} ({name}): NOT FOUND")
                all_ok = False
            continue

        rate_ok = row.rate_pct == Decimal(str(expected_rate))
        ch99_ok = row.ch99_code == expected_ch99
        status = "OK" if (rate_ok and ch99_ok) else "FAIL"
        print(
            f"    {iso} ({name}): rate={row.rate_pct}% "
            f"ch99={row.ch99_code} [{status}]"
        )
        if not (rate_ok and ch99_ok):
            all_ok = False

    # Check existing MFN ceiling data intact
    print("\n  Regression checks (existing data):")
    for iso, name in [("IT", "Italy/EU"), ("JP", "Japan"), ("CN", "China")]:
        rows = IeepaReciprocalRateSchedule.query.filter_by(
            country_code=iso,
        ).all()
        if rows:
            for row in rows:
                print(
                    f"    {iso} ({name}): {row.regime_type} rate={row.rate_pct}% "
                    f"ceiling={row.ceiling_pct} "
                    f"({row.effective_start} to {row.effective_end}) "
                    f"tag={row.dataset_tag}"
                )
        else:
            print(f"    {iso} ({name}): NOT FOUND")

    # Total count
    total = IeepaReciprocalRateSchedule.query.count()
    distinct = db.session.query(
        IeepaReciprocalRateSchedule.country_code
    ).filter(
        IeepaReciprocalRateSchedule.country_code.isnot(None)
    ).distinct().count()
    print(f"\n  Total rows: {total}")
    print(f"  Distinct country codes: {distinct}")

    return all_ok


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ingest ~137 missing countries into IEEPA reciprocal rate schedule"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without DB modification",
    )
    parser.add_argument(
        "--skip-verify", action="store_true",
        help="Skip Yale vs Annex cross-verification",
    )
    parser.add_argument(
        "--local-yaml", type=Path, default=None,
        help="Use local YAML file instead of downloading",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Continue past hard-fail countries (rate >10%% with no Annex entry)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("IEEPA Reciprocal Rate Expansion v21.1 (Yale Bootstrap)")
    print("=" * 60)

    # --- Phase A: Load data sources ---
    print("\nPhase A: Loading data sources...")

    yale_rates = load_yale_yaml(str(args.local_yaml) if args.local_yaml else None)

    census_csv = project_root / "data" / "census_to_iso_mapping.csv"
    print(f"  Loading census mapping: {census_csv}")
    census_map = load_census_mapping(census_csv)

    annex_csv = project_root / "data" / "eo14326_annex_ch99_codes.csv"
    print(f"  Loading Annex II codes: {annex_csv}")
    annex = load_annex_csv(annex_csv)

    # --- Phase B: Cross-verification ---
    if not args.skip_verify:
        print("\nPhase B: Cross-verifying Yale vs Annex rates...")
        passed, messages = cross_verify(yale_rates, census_map, annex)
        for msg in messages:
            print(msg)
        if not passed:
            print("\n[FAIL] Cross-verification failed. Use --skip-verify to bypass.")
            sys.exit(1)
        print("\n  Cross-verification PASSED")
    else:
        print("\nPhase B: Skipped (--skip-verify)")

    # --- Flask app context for DB operations ---
    app = create_app()

    with app.app_context():
        # Ensure table exists
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if "ieepa_reciprocal_rate_schedule" not in inspector.get_table_names():
            print("\n  Table ieepa_reciprocal_rate_schedule does not exist — creating...")
            db.create_all()
            print("  Table created.")

        # --- Phase C: Build skip set ---
        print("\nPhase C: Building skip set from existing DB entries...")
        skip_set = build_skip_set()
        print(f"  Skip set: {len(skip_set)} existing country codes")
        print(f"  Codes: {sorted(skip_set)}")

        # --- Phase D: Build insert records ---
        print("\nPhase D: Building insert records...")
        records, hard_fails = build_insert_records(
            yale_rates, census_map, annex, skip_set
        )

        if hard_fails:
            print(f"\n  HARD FAIL — {len(hard_fails)} countries with rate >10% but no Annex entry:")
            for hf in hard_fails:
                print(hf)
            if not args.force:
                print("\n  These countries need investigation.")
                print("  Use --force to continue without them.")
                sys.exit(1)
            else:
                print("\n  --force specified. Continuing without hard-fail countries...")

        if not records:
            print("\n  No records to insert. All countries already covered.")
            return

        # Show sample records
        print("\n  Sample records (first 10):")
        for r in records[:10]:
            print(
                f"    {r['country_code']}  {r['regime_type']:15s}  "
                f"rate={r['rate_pct']:>5}%  ch99={r['ch99_code']}  "
                f"group={r['country_group']}"
            )
        if len(records) > 10:
            print(f"    ... and {len(records) - 10} more")

        # --- Phase E: Upsert ---
        if args.dry_run:
            print("\n[DRY RUN] Phase E: Preview only — no DB changes")
        else:
            print("\nPhase E: Upserting records...")

        stats = upsert_records(records, dry_run=args.dry_run)

        print(f"\n  Upsert results:")
        print(f"    Total records:    {stats['total']}")
        print(f"    Existing before:  {stats['existing_before']}")
        print(f"    Inserted:         {stats['inserted']}")
        print(f"    Updated:          {stats['updated']}")
        print(f"    Unchanged:        {stats['unchanged']}")

        # --- Phase F: Post-ingestion validation ---
        if not args.dry_run:
            print("\nPhase F: Post-ingestion validation...")
            all_ok = post_validation(annex)
            if all_ok:
                print("\n[SUCCESS] Expansion complete. All checks passed.")
            else:
                print("\n[WARNING] Expansion complete but some checks failed.")
        else:
            print("\n[DRY RUN] Skipping post-validation (no DB changes made)")
            print("[DRY RUN] Re-run without --dry-run to perform actual ingestion.")


if __name__ == "__main__":
    main()
