#!/usr/bin/env python3
"""
Build Census Bureau country code → ISO 3166-1 alpha-2 mapping.

Downloads Yale Budget Lab's census_codes.csv (249 rows) and matches
country names to ISO codes using pycountry + manual overrides.

Output: lanes/data/census_to_iso_mapping.csv

Usage:
    python scripts/build_census_iso_mapping.py
    python scripts/build_census_iso_mapping.py --output /path/to/output.csv
"""

import argparse
import csv
import io
import sys
from pathlib import Path

import pycountry
import requests

YALE_CENSUS_URL = (
    "https://raw.githubusercontent.com/Budget-Lab-Yale/Tariff-ETRs/"
    "main/resources/census_codes.csv"
)

# Manual overrides for names pycountry can't match or gets wrong.
# Format: census_code -> (iso_alpha2, notes)
MANUAL_OVERRIDES = {
    # Self / US territories → SKIP
    "1000": ("", "SKIP"),       # United States of America
    "9030": ("", "SKIP"),       # Puerto Rico
    "9110": ("", "SKIP"),       # Virgin Islands of the United States
    "9350": ("", "SKIP"),       # Guam
    "9510": ("", "SKIP"),       # American Samoa
    "9610": ("", "SKIP"),       # Northern Mariana Islands
    "9800": ("", "SKIP"),       # United States Minor Outlying Islands

    # Dependencies / territories that are SKIP or map to admin country
    "1010": ("GL", ""),         # Greenland (Danish territory, has own ISO)
    "1610": ("PM", ""),         # Saint Pierre and Miquelon
    "2320": ("BM", ""),         # Bermuda
    "2430": ("TC", ""),         # Turks and Caicos Islands
    "2440": ("KY", ""),         # Cayman Islands
    "2481": ("AI", ""),         # Anguilla
    "2482": ("VG", ""),         # British Virgin Islands
    "2485": ("MS", ""),         # Montserrat
    "2774": ("SX", ""),         # Sint Maarten
    "2777": ("CW", ""),         # Curacao
    "2779": ("AW", ""),         # Aruba
    "2831": ("GP", ""),         # Guadeloupe
    "2839": ("MQ", ""),         # Martinique
    "3170": ("GF", ""),         # French Guiana
    "3720": ("FK", ""),         # Falkland Islands
    "4031": ("SJ", ""),         # Svalbard and Jan Mayen
    "4091": ("FO", ""),         # Faroe Islands
    "4720": ("GI", ""),         # Gibraltar
    "5082": ("PS", ""),         # Gaza Strip → Palestine
    "5083": ("PS", ""),         # West Bank → Palestine (dup with 5082)
    "5660": ("MO", ""),         # Macao
    "5820": ("HK", ""),         # Hong Kong
    "6022": ("NF", ""),         # Norfolk Island
    "6023": ("CC", ""),         # Cocos (Keeling) Islands
    "6024": ("CX", ""),         # Christmas Island
    "6029": ("HM", ""),         # Heard Island and McDonald Islands
    "6142": ("CK", ""),         # Cook Islands
    "6143": ("TK", ""),         # Tokelau
    "6144": ("NU", ""),         # Niue
    "6225": ("PN", ""),         # Pitcairn Islands
    "6412": ("NC", ""),         # New Caledonia
    "6413": ("WF", ""),         # Wallis and Futuna
    "6414": ("PF", ""),         # French Polynesia
    "7580": ("SH", ""),         # Saint Helena
    "7810": ("IO", ""),         # British Indian Ocean Territory
    "7881": ("YT", ""),         # Mayotte
    "7904": ("RE", ""),         # Reunion
    "7905": ("TF", ""),         # French Southern and Antarctic Lands

    # Names that differ between Census and pycountry
    "2010": ("MX", ""),         # Mexico
    "2050": ("GT", ""),         # Guatemala
    "2390": ("CU", ""),         # Cuba
    "4099": ("DK", ""),         # Denmark, except Greenland
    "4120": ("GB", ""),         # United Kingdom
    "4231": ("BE", ""),         # Belgium
    "4239": ("LU", ""),         # Luxembourg
    "4271": ("AD", ""),         # Andorra
    "4272": ("MC", ""),         # Monaco
    "4279": ("FR", ""),         # France
    "4280": ("DE", ""),         # Germany (Federal Republic of Germany)
    "4351": ("CZ", ""),         # Czech Republic
    "4359": ("SK", ""),         # Slovakia
    "4411": ("LI", ""),         # Liechtenstein
    "4419": ("CH", ""),         # Switzerland
    "4621": ("RU", ""),         # Russia
    "4622": ("BY", ""),         # Belarus
    "4623": ("UA", ""),         # Ukraine
    "4631": ("AM", ""),         # Armenia
    "4632": ("AZ", ""),         # Azerbaijan
    "4633": ("GE", ""),         # Georgia
    "4634": ("KZ", ""),         # Kazakhstan
    "4635": ("KG", ""),         # Kyrgyzstan
    "4641": ("MD", ""),         # Moldova
    "4642": ("TJ", ""),         # Tajikistan
    "4643": ("TM", ""),         # Turkmenistan
    "4644": ("UZ", ""),         # Uzbekistan
    "4700": ("ES", ""),         # Spain
    "4710": ("PT", ""),         # Portugal
    "4730": ("MT", ""),         # Malta
    "4751": ("SM", ""),         # San Marino
    "4752": ("VA", ""),         # Holy See (Vatican City)
    "4759": ("IT", ""),         # Italy
    "4791": ("HR", ""),         # Croatia
    "4792": ("SI", ""),         # Slovenia
    "4793": ("BA", ""),         # Bosnia and Herzegovina
    "4794": ("MK", ""),         # North Macedonia
    "4801": ("RS", ""),         # Serbia
    "4803": ("XK", ""),         # Kosovo (no ISO, use XK convention)
    "4804": ("ME", ""),         # Montenegro
    "4810": ("AL", ""),         # Albania
    "4840": ("GR", ""),         # Greece
    "4850": ("RO", ""),         # Romania
    "4870": ("BG", ""),         # Bulgaria
    "4890": ("TR", ""),         # Turkey
    "4910": ("CY", ""),         # Cyprus
    "5020": ("SY", ""),         # Syria
    "5040": ("LB", ""),         # Lebanon
    "5050": ("IQ", ""),         # Iraq
    "5070": ("IR", ""),         # Iran
    "5081": ("IL", ""),         # Israel
    "5110": ("JO", ""),         # Jordan
    "5130": ("KW", ""),         # Kuwait
    "5170": ("SA", ""),         # Saudi Arabia
    "5180": ("QA", ""),         # Qatar
    "5200": ("AE", ""),         # United Arab Emirates
    "5210": ("YE", ""),         # Yemen
    "5230": ("OM", ""),         # Oman
    "5250": ("BH", ""),         # Bahrain
    "5310": ("AF", ""),         # Afghanistan
    "5330": ("IN", ""),         # India
    "5350": ("PK", ""),         # Pakistan
    "5360": ("NP", ""),         # Nepal
    "5380": ("BD", ""),         # Bangladesh
    "5420": ("LK", ""),         # Sri Lanka
    "5460": ("MM", ""),         # Burma (Myanmar)
    "5490": ("TH", ""),         # Thailand
    "5520": ("VN", ""),         # Vietnam
    "5530": ("LA", ""),         # Laos
    "5550": ("KH", ""),         # Cambodia
    "5570": ("MY", ""),         # Malaysia
    "5590": ("SG", ""),         # Singapore
    "5600": ("ID", ""),         # Indonesia
    "5601": ("TL", ""),         # Timor-Leste
    "5610": ("BN", ""),         # Brunei
    "5650": ("PH", ""),         # Philippines
    "5682": ("BT", ""),         # Bhutan
    "5683": ("MV", ""),         # Maldives
    "5700": ("CN", ""),         # China
    "5740": ("MN", ""),         # Mongolia
    "5790": ("KP", ""),         # North Korea
    "5800": ("KR", ""),         # South Korea
    "5830": ("TW", ""),         # Taiwan
    "5880": ("JP", ""),         # Japan
    "6021": ("AU", ""),         # Australia
    "6040": ("PG", ""),         # Papua New Guinea
    "6141": ("NZ", ""),         # New Zealand
    "6150": ("WS", ""),         # Samoa (Western Samoa)
    "6223": ("SB", ""),         # Solomon Islands
    "6224": ("VU", ""),         # Vanuatu
    "6226": ("KI", ""),         # Kiribati
    "6227": ("TV", ""),         # Tuvalu
    "6810": ("MH", ""),         # Marshall Islands
    "6820": ("FM", ""),         # Micronesia
    "6830": ("PW", ""),         # Palau
    "6862": ("NR", ""),         # Nauru
    "6863": ("FJ", ""),         # Fiji
    "6864": ("TO", ""),         # Tonga
    "7140": ("MA", ""),         # Morocco
    "7210": ("DZ", ""),         # Algeria
    "7230": ("TN", ""),         # Tunisia
    "7250": ("LY", ""),         # Libya
    "7290": ("EG", ""),         # Egypt
    "7321": ("SD", ""),         # Sudan
    "7323": ("SS", ""),         # South Sudan
    "7380": ("GQ", ""),         # Equatorial Guinea
    "7410": ("MR", ""),         # Mauritania
    "7420": ("CM", ""),         # Cameroon
    "7440": ("SN", ""),         # Senegal
    "7450": ("ML", ""),         # Mali
    "7460": ("GN", ""),         # Guinea
    "7470": ("SL", ""),         # Sierra Leone
    "7480": ("CI", ""),         # Cote d'Ivoire
    "7490": ("GH", ""),         # Ghana
    "7500": ("GM", ""),         # Gambia
    "7510": ("NE", ""),         # Niger
    "7520": ("TG", ""),         # Togo
    "7530": ("NG", ""),         # Nigeria
    "7540": ("CF", ""),         # Central African Republic
    "7550": ("GA", ""),         # Gabon
    "7560": ("TD", ""),         # Chad
    "7600": ("BF", ""),         # Burkina Faso
    "7610": ("BJ", ""),         # Benin
    "7620": ("AO", ""),         # Angola
    "7630": ("CG", ""),         # Congo, Republic
    "7642": ("GW", ""),         # Guinea-Bissau
    "7643": ("CV", ""),         # Cabo Verde
    "7644": ("ST", ""),         # Sao Tome and Principe
    "7650": ("LR", ""),         # Liberia
    "7660": ("CD", ""),         # Congo, Democratic Republic
    "7670": ("BI", ""),         # Burundi
    "7690": ("RW", ""),         # Rwanda
    "7700": ("SO", ""),         # Somalia
    "7741": ("ER", ""),         # Eritrea
    "7749": ("ET", ""),         # Ethiopia
    "7770": ("DJ", ""),         # Djibouti
    "7780": ("UG", ""),         # Uganda
    "7790": ("KE", ""),         # Kenya
    "7800": ("SC", ""),         # Seychelles
    "7830": ("TZ", ""),         # Tanzania
    "7850": ("MU", ""),         # Mauritius
    "7870": ("MZ", ""),         # Mozambique
    "7880": ("MG", ""),         # Madagascar
    "7890": ("KM", ""),         # Comoros
    "7910": ("ZA", ""),         # South Africa
    "7920": ("NA", ""),         # Namibia
    "7930": ("BW", ""),         # Botswana
    "7940": ("ZM", ""),         # Zambia
    "7950": ("SZ", ""),         # Eswatini
    "7960": ("ZW", ""),         # Zimbabwe
    "7970": ("MW", ""),         # Malawi
    "7990": ("LS", ""),         # Lesotho

    # Americas
    "1220": ("CA", ""),         # Canada
    "2080": ("BZ", ""),         # Belize
    "2110": ("SV", ""),         # El Salvador
    "2150": ("HN", ""),         # Honduras
    "2190": ("NI", ""),         # Nicaragua
    "2230": ("CR", ""),         # Costa Rica
    "2250": ("PA", ""),         # Panama
    "2360": ("BS", ""),         # Bahamas
    "2410": ("JM", ""),         # Jamaica
    "2450": ("HT", ""),         # Haiti
    "2470": ("DO", ""),         # Dominican Republic
    "2483": ("KN", ""),         # Saint Kitts and Nevis
    "2484": ("AG", ""),         # Antigua and Barbuda
    "2486": ("DM", ""),         # Dominica
    "2487": ("LC", ""),         # Saint Lucia
    "2488": ("VC", ""),         # Saint Vincent and the Grenadines
    "2489": ("GD", ""),         # Grenada
    "2720": ("BB", ""),         # Barbados
    "2740": ("TT", ""),         # Trinidad and Tobago
    "3010": ("CO", ""),         # Colombia
    "3070": ("VE", ""),         # Venezuela
    "3120": ("GY", ""),         # Guyana
    "3150": ("SR", ""),         # Suriname
    "3310": ("EC", ""),         # Ecuador
    "3330": ("PE", ""),         # Peru
    "3350": ("BO", ""),         # Bolivia
    "3370": ("CL", ""),         # Chile
    "3510": ("BR", ""),         # Brazil
    "3530": ("PY", ""),         # Paraguay
    "3550": ("UY", ""),         # Uruguay
    "3570": ("AR", ""),         # Argentina

    # Europe
    "4000": ("IS", ""),         # Iceland
    "4010": ("SE", ""),         # Sweden
    "4039": ("NO", ""),         # Norway
    "4050": ("FI", ""),         # Finland
    "4190": ("IE", ""),         # Ireland
    "4210": ("NL", ""),         # Netherlands
    "4330": ("AT", ""),         # Austria
    "4370": ("HU", ""),         # Hungary
    "4470": ("EE", ""),         # Estonia
    "4490": ("LV", ""),         # Latvia
    "4510": ("LT", ""),         # Lithuania
    "4550": ("PL", ""),         # Poland
}


def download_census_codes() -> list[dict]:
    """Download Yale Budget Lab census_codes.csv and return list of dicts."""
    print(f"Downloading census codes from {YALE_CENSUS_URL}...")
    resp = requests.get(YALE_CENSUS_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    print(f"  Downloaded {len(rows)} census codes")
    return rows


def try_pycountry_match(name: str) -> str | None:
    """Try to match a country name to ISO alpha-2 using pycountry."""
    # Exact match
    try:
        country = pycountry.countries.lookup(name)
        return country.alpha_2
    except LookupError:
        pass

    # Fuzzy search
    results = pycountry.countries.search_fuzzy(name)
    if results:
        return results[0].alpha_2
    return None


def build_mapping(census_rows: list[dict]) -> list[dict]:
    """Build census_code → ISO alpha-2 mapping."""
    output = []
    unmatched = []

    for row in census_rows:
        code = row.get("Code") or row.get("code")
        name = row.get("Name") or row.get("name")

        if not code or not name:
            continue

        code = str(code).strip()
        name = name.strip()

        # Check manual overrides first
        if code in MANUAL_OVERRIDES:
            iso2, skip = MANUAL_OVERRIDES[code]
            output.append({
                "census_code": code,
                "iso_alpha2": iso2,
                "country_name": name,
                "skip": skip,
            })
            continue

        # Try pycountry
        try:
            iso2 = try_pycountry_match(name)
        except Exception:
            iso2 = None

        if iso2:
            output.append({
                "census_code": code,
                "iso_alpha2": iso2,
                "country_name": name,
                "skip": "",
            })
        else:
            unmatched.append((code, name))
            output.append({
                "census_code": code,
                "iso_alpha2": "",
                "country_name": name,
                "skip": "UNMATCHED",
            })

    if unmatched:
        print(f"\nWARNING: {len(unmatched)} unmatched census codes:")
        for code, name in unmatched:
            print(f"  {code}: {name}")
        print("Add these to MANUAL_OVERRIDES and re-run.")

    return output


def write_csv(rows: list[dict], output_path: Path):
    """Write mapping to CSV."""
    fieldnames = ["census_code", "iso_alpha2", "country_name", "skip"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {output_path}")


def print_summary(rows: list[dict]):
    """Print summary statistics."""
    total = len(rows)
    mapped = sum(1 for r in rows if r["iso_alpha2"] and r["skip"] != "SKIP")
    skipped = sum(1 for r in rows if r["skip"] == "SKIP")
    unmatched = sum(1 for r in rows if r["skip"] == "UNMATCHED")

    print(f"\nSummary:")
    print(f"  Total census codes:  {total}")
    print(f"  Mapped to ISO:       {mapped}")
    print(f"  Skipped (US/terr.):  {skipped}")
    print(f"  Unmatched:           {unmatched}")

    # Show some examples
    print(f"\nSample mappings:")
    samples = [r for r in rows if r["iso_alpha2"] and r["skip"] != "SKIP"][:10]
    for r in samples:
        print(f"  {r['census_code']} → {r['iso_alpha2']}  ({r['country_name']})")


def main():
    parser = argparse.ArgumentParser(
        description="Build Census → ISO alpha-2 country code mapping"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "census_to_iso_mapping.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Census-to-ISO Country Code Mapping Builder")
    print("=" * 60)

    census_rows = download_census_codes()
    mapping = build_mapping(census_rows)
    write_csv(mapping, args.output)
    print_summary(mapping)

    print("\n[DONE] Review the CSV and fix any UNMATCHED entries.")


if __name__ == "__main__":
    main()
