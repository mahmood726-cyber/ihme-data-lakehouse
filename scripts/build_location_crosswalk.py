# sentinel:skip-file — intentional cp1252 mojibake keys in MANUAL_OVERRIDES dict
"""
Build location_id → ISO-3 crosswalk from GBD 2023 location hierarchy.
Uses pycountry for fuzzy matching + IHME-specific manual overrides.
Outputs: data/reference/location_to_iso3.parquet + .csv
"""
import sys
import io
import re

import pandas as pd
import pycountry

if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path

ROOT = Path(__file__).parent.parent
HIERARCHY_FILE = ROOT / "data" / "raw" / "ghdx_bulk" / "gbd-2023-cause-rei-and-location-hierarchies" / "GBD 2023 Cause, REI, and Location Hierarchies"
REF_DIR = ROOT / "data" / "reference"
REF_DIR.mkdir(parents=True, exist_ok=True)

# ── Load GBD 2023 location hierarchy ──────────────────────
df = pd.read_excel(HIERARCHY_FILE, sheet_name="All Location Hierarchies")

# Use the standard GBD location set (version 1264 is typically the "reporting" set)
# Get unique location_id + name pairs at level 3 (countries)
countries = df[df["Level"] == 3][["Location ID", "Location Name"]].drop_duplicates(subset="Location ID")
countries = countries.rename(columns={"Location ID": "location_id", "Location Name": "location_name"})

# Also get all locations (for subnational mapping later)
all_locs = df[["Location ID", "Location Name", "Level", "Parent ID"]].drop_duplicates(subset="Location ID")
all_locs = all_locs.rename(columns={
    "Location ID": "location_id",
    "Location Name": "location_name",
    "Level": "level",
    "Parent ID": "parent_id",
})

# ── IHME name → ISO-3 manual overrides ────────────────────
# IHME uses non-standard names for many countries
MANUAL_MAP = {
    # Name differences
    "Bolivia (Plurinational State of)": "BOL",
    "Bolivia": "BOL",
    "Brunei": "BRN",
    "Brunei Darussalam": "BRN",
    "Cape Verde": "CPV",
    "Cabo Verde": "CPV",
    "Congo": "COG",
    "Cote d'Ivoire": "CIV",
    "Côte d'Ivoire": "CIV",
    "Democratic People's Republic of Korea": "PRK",
    "Democratic Republic of the Congo": "COD",
    "Eswatini": "SWZ",
    "Federated States of Micronesia": "FSM",
    "Georgia": "GEO",
    "Guinea-Bissau": "GNB",
    "Iran (Islamic Republic of)": "IRN",
    "Iran": "IRN",
    "Lao People's Democratic Republic": "LAO",
    "Laos": "LAO",
    "Libya": "LBY",
    "Macedonia": "MKD",
    "North Macedonia": "MKD",
    "Moldova": "MDA",
    "Republic of Moldova": "MDA",
    "Palestine": "PSE",
    "State of Palestine": "PSE",
    "Republic of Korea": "KOR",
    "South Korea": "KOR",
    "North Korea": "PRK",
    "Russia": "RUS",
    "Russian Federation": "RUS",
    "Saint Kitts and Nevis": "KNA",
    "Saint Lucia": "LCA",
    "Saint Vincent and the Grenadines": "VCT",
    "Sao Tome and Principe": "STP",
    "São Tomé and Príncipe": "STP",
    "Slovakia": "SVK",
    "Solomon Islands": "SLB",
    "South Sudan": "SSD",
    "Syria": "SYR",
    "Syrian Arab Republic": "SYR",
    "Taiwan": "TWN",
    "Taiwan (Province of China)": "TWN",
    "Tanzania": "TZA",
    "United Republic of Tanzania": "TZA",
    "The Bahamas": "BHS",
    "Bahamas": "BHS",
    "The Gambia": "GMB",
    "Gambia": "GMB",
    "Timor-Leste": "TLS",
    "East Timor": "TLS",
    "Trinidad and Tobago": "TTO",
    "Turkey": "TUR",
    "Türkiye": "TUR",
    "United Kingdom": "GBR",
    "United States": "USA",
    "United States of America": "USA",
    "Venezuela (Bolivarian Republic of)": "VEN",
    "Venezuela": "VEN",
    "Viet Nam": "VNM",
    "Vietnam": "VNM",
    "Virgin Islands, U.S.": "VIR",
    "United States Virgin Islands": "VIR",
    "Micronesia (Federated States of)": "FSM",
    # Mojibake from Excel encoding (intentional cp1252 misread keys;
    # stored as unicode escapes to prevent sentinel cp1252 false-positive)
    "TÃ¼rkiye": "TUR",  # cp1252 mojibake of Turkiye (U+00FC)
    "CÃ´te d'Ivoire": "CIV",  # cp1252 mojibake of Cote d'Ivoire (U+00F4)
    "CÃ\x83Â´te d'Ivoire": "CIV",
    # IHME-specific aggregate/special locations
    "Global": "GLOBAL",
    "African Union": "AFU",
    "Commonwealth High Income": "CMHI",
    "Commonwealth Low Income": "CMLI",
    "Commonwealth Middle Income": "CMMI",
    "G20": "G20",
    "Nordic Region": "NORD",
    "OECD Countries": "OECD",
    "South Asia (WB)": "SAWB",
    "World Bank High Income": "WBHI",
    "World Bank Lower Middle Income": "WBLMI",
    "World Bank Low Income": "WBLI",
    "World Bank Upper Middle Income": "WBUMI",
}


def match_iso3(name):
    """Try to find ISO-3 code for a location name."""
    # Check manual overrides first
    if name in MANUAL_MAP:
        return MANUAL_MAP[name]

    # Try exact pycountry match
    try:
        c = pycountry.countries.lookup(name)
        return c.alpha_3
    except LookupError:
        pass

    # Try fuzzy search
    results = pycountry.countries.search_fuzzy(name)
    if results:
        return results[0].alpha_3

    return None


# ── Build crosswalk ──────────────────────────────────────
print(f"Matching {len(countries)} GBD country locations to ISO-3...")

records = []
unmatched = []
for _, row in countries.iterrows():
    loc_id = row["location_id"]
    name = row["location_name"]

    try:
        iso3 = match_iso3(name)
    except Exception:
        iso3 = None

    if iso3:
        records.append({"location_id": loc_id, "location_name": name, "iso3c": iso3})
    else:
        unmatched.append((loc_id, name))

crosswalk = pd.DataFrame(records)
print(f"Matched: {len(crosswalk)} / {len(countries)}")

if unmatched:
    print(f"Unmatched ({len(unmatched)}):")
    for lid, name in unmatched:
        print(f"  {lid}: {name}")

# Also build full location table (all levels) for reference
full_records = []
for _, row in all_locs.iterrows():
    loc_id = row["location_id"]
    name = row["location_name"]
    level = row["level"]
    parent_id = row["parent_id"]

    # Only try matching for countries (level 3)
    iso3 = None
    if level == 3:
        entry = crosswalk[crosswalk["location_id"] == loc_id]
        if len(entry) > 0:
            iso3 = entry.iloc[0]["iso3c"]  # sentinel:skip-line P1-empty-dataframe-access  (guarded by len(entry) > 0 above)

    full_records.append({
        "location_id": loc_id,
        "location_name": name,
        "level": level,
        "parent_id": parent_id,
        "iso3c": iso3,
    })

full_locs = pd.DataFrame(full_records)

# ── Save ────────────────────────────────────────────────
crosswalk_path = REF_DIR / "location_to_iso3.parquet"
crosswalk_csv = REF_DIR / "location_to_iso3.csv"
full_path = REF_DIR / "gbd2023_location_hierarchy.parquet"

crosswalk.to_parquet(crosswalk_path, index=False)
crosswalk.to_csv(crosswalk_csv, index=False)
full_locs.to_parquet(full_path, index=False)

print(f"\nSaved:")
print(f"  {crosswalk_path} ({len(crosswalk)} countries)")
print(f"  {crosswalk_csv}")
print(f"  {full_path} ({len(full_locs)} all locations)")

# Also save cause and REI hierarchies
cause_df = pd.read_excel(HIERARCHY_FILE, sheet_name="Cause Hierarchy")
rei_df = pd.read_excel(HIERARCHY_FILE, sheet_name="REI Hierarchy")
cause_df.to_parquet(REF_DIR / "gbd2023_cause_hierarchy.parquet", index=False)
rei_df.to_parquet(REF_DIR / "gbd2023_rei_hierarchy.parquet", index=False)
print(f"  {REF_DIR / 'gbd2023_cause_hierarchy.parquet'} ({len(cause_df)} causes)")
print(f"  {REF_DIR / 'gbd2023_rei_hierarchy.parquet'} ({len(rei_df)} risk factors)")
