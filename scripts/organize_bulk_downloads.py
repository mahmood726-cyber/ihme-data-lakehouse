"""
Organize GHDx bulk downloads into the IHME Data Lakehouse structure.

Reads ghdx_files_auth.json to classify each dataset, then:
1. Creates domain folders under data/raw/ matching the lakehouse schema
2. Symlinks or copies files from ghdx_bulk/ into the right domain
3. Extracts ZIP files
4. Updates registry/sources.yaml with new entries
5. Reports what's ready for promotion (raw → bronze → silver)

Run periodically as downloads complete:
  python scripts/organize_bulk_downloads.py [--copy | --move]
"""
import json
import os
import re
import shutil
import sys
import io
import zipfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).parent.parent
BULK_DIR = ROOT / "data" / "raw" / "ghdx_bulk"
RAW_DIR = ROOT / "data" / "raw"
AUTH_DB = ROOT / "registry" / "ghdx_files_auth.json"

# Domain classification rules — map dataset titles/slugs to lakehouse domains
DOMAIN_RULES = [
    # GBD 2023 core results
    {
        "domain": "gbd_results",
        "patterns": [
            r"gbd 2023.*cause-specific mortality",
            r"gbd 2023.*yld.*daly",
            r"gbd 2023.*hale.*risk",
            r"gbd 2023.*cardiovascular burden",
            r"gbd 2023.*chronic kidney",
            r"gbd 2023.*headache",
            r"gbd 2023.*lower respiratory",
            r"gbd 2023.*cancer",
            r"gbd 2023.*tuberculosis",
            r"gbd 2023.*nonfatal",
            r"gbd 2023.*incidence",
            r"gbd 2023.*prevalence",
            r"gbd 2023.*mortality",
            r"gbd 2023.*burden",
        ],
    },
    # GBD covariates
    {
        "domain": "gbd_covariates",
        "patterns": [
            r"covariates \d{4}",
            r"socio-demographic index",
            r"sdi \d{4}",
            r"disability weights",
            r"gbd 2023.*sdi",
        ],
    },
    # Population & demographics
    {
        "domain": "population",
        "patterns": [
            r"demographics \d{4}",
            r"population",
            r"fertility",
            r"life expectancy",
            r"life table",
            r"mortality.*\d{4}.*country",
            r"neonatal mortality",
            r"under-?\d.*mortality",
            r"child mortality",
            r"infant mortality",
            r"birth registration",
        ],
    },
    # Risk factors & exposures
    {
        "domain": "gbd_risk",
        "patterns": [
            r"risk exposure",
            r"air pollution",
            r"lead exposure",
            r"smoking.*prevalence",
            r"smoking.*mortality",
            r"tobacco",
            r"unsafe water",
            r"unsafe sanitation",
            r"hygiene exposure",
            r"overweight.*obesity",
            r"burden of proof",
            r"processed foods",
            r"dietary risk",
            r"alcohol.*burden",
            r"drug use",
            r"occupational",
            r"ambient temperature",
            r"risk factor",
            r"child.*growth failure",
            r"breastfeeding",
            r"male circumcision",
            r"stunting|wasting|underweight",
        ],
    },
    # Forecasts
    {
        "domain": "forecasts",
        "patterns": [
            r"forecasts? \d{4}-\d{4}",
            r"forecast",
        ],
    },
    # Health financing
    {
        "domain": "health_financing",
        "patterns": [
            r"health spending",
            r"health expenditure",
            r"development assistance for health",
            r"gdp per capita",
            r"health.*spending.*inefficiency",
            r"health.*care.*spending",
            r"health financing",
            r"dah.*database",
            r"universal health coverage",
            r"health care.*cost",
            r"inpatient.*outpatient.*cost",
            r"abce project",
        ],
    },
    # Vaccination & immunization
    {
        "domain": "vaccination",
        "patterns": [
            r"vaccination coverage",
            r"vaccine",
            r"immunization",
            r"measles.*incidence",
            r"measles.*susceptibility",
            r"rsv.*hospitali",
            r"dtp.*coverage",
            r"mcv\d.*coverage",
            r"zero.?dose",
        ],
    },
    # US subnational
    {
        "domain": "us_subnational",
        "patterns": [
            r"united states.*county",
            r"united states.*race.*ethnicity",
            r"united states.*mortality",
            r"united states.*health",
            r"us health",
            r"us .*mortality",
        ],
    },
    # ICD mappings & hierarchies (reference)
    {
        "domain": "reference",
        "patterns": [
            r"icd codes",
            r"cause.*rei.*location.*hierarch",
            r"location hierarch",
        ],
    },
    # Surveys (Salud Mesoamerica, facility surveys, household surveys)
    {
        "domain": "surveys",
        "patterns": [
            r"salud mesoam",
            r"baseline.*survey",
            r"facility survey",
            r"household survey",
            r"lqas survey",
            r"census.*survey",
            r"access.*bottleneck.*cost.*equity",
        ],
    },
    # Geospatial estimates
    {
        "domain": "geospatial",
        "patterns": [
            r"geospatial estimate",
            r"admin \d location",
            r"gridded",
            r"5x5 km",
        ],
    },
    # GBD legacy (2010-2019)
    {
        "domain": "gbd_legacy",
        "patterns": [
            r"gbd 201[0-9]",
            r"gbd 2010",
            r"global burden of disease study 201[0-9]",
        ],
    },
    # Specialty / disease-specific
    {
        "domain": "specialty",
        "patterns": [
            r"diabetes care",
            r"rheumatic heart",
            r"hiv.*mortality",
            r"hiv.*prevalence",
            r"suicide",
            r"sexual violence",
            r"gender.based violence",
            r"violence against children",
            r"homicide",
            r"malnutrition",
            r"pregnancy.*mortality",
            r"brain health",
            r"delivery location",
            r"maternal health",
            r"antimicrobial resistance",
            r"\bamr\b",
            r"neglected tropical",
            r"onchocerciasis",
            r"lymphatic filariasis",
            r"oral rehydration",
            r"insecticide.*bed net",
            r"covid",
            r"diarrhea",
            r"anemia",
            r"hearing loss",
            r"weight change",
            r"educational attainment",
            r"human capital",
        ],
    },
]


def classify_dataset(title):
    """Classify a dataset title into a lakehouse domain."""
    title_lower = title.lower()
    for rule in DOMAIN_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, title_lower):
                return rule["domain"]
    return "unclassified"


def sanitize(name, max_len=180):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')[:max_len] or 'unnamed'


def extract_zips(folder):
    """Extract any ZIP files in a folder."""
    extracted = []
    for zf in folder.glob("*.zip"):
        try:
            with zipfile.ZipFile(zf, 'r') as z:
                z.extractall(folder)
                extracted.extend(z.namelist())
        except (zipfile.BadZipFile, Exception) as e:
            print(f"  WARN: Could not extract {zf.name}: {e}")
    return extracted


def main():
    mode = "link"  # default: create directory junctions / symlinks
    if "--copy" in sys.argv:
        mode = "copy"
    elif "--move" in sys.argv:
        mode = "move"

    # Load auth DB for titles
    with open(AUTH_DB, encoding="utf-8") as f:
        auth_data = json.load(f)

    # Scan bulk downloads
    if not BULK_DIR.exists():
        print("No bulk download directory found.")
        return

    bulk_folders = sorted(BULK_DIR.iterdir())
    print(f"Found {len(bulk_folders)} downloaded dataset folders")

    # Classify and organize
    domain_counts = {}
    organized = []

    for folder in bulk_folders:
        if not folder.is_dir():
            continue

        slug = folder.name.replace("_", "/", 1)  # ihme-data_foo → ihme-data/foo
        record = auth_data.get(slug, {})
        title = record.get("title", folder.name)
        domain = classify_dataset(title)

        domain_counts[domain] = domain_counts.get(domain, 0) + 1

        # Create domain directory
        domain_dir = RAW_DIR / domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        # Target folder name (clean)
        target_name = sanitize(slug.replace("/", "_"))
        target = domain_dir / target_name

        files_in_folder = list(folder.iterdir())
        if not files_in_folder:
            continue

        # Copy/move/link files
        try:
            if not target.exists():
                if mode == "copy":
                    shutil.copytree(folder, target, dirs_exist_ok=True)
                elif mode == "move":
                    shutil.move(str(folder), str(target))
                else:
                    target.mkdir(parents=True, exist_ok=True)
                    for f in files_in_folder:
                        if f.is_file():
                            dest = target / f.name
                            if not dest.exists():
                                shutil.copy2(f, dest)
        except (shutil.Error, OSError, PermissionError) as e:
            # Handle locked files gracefully — copy what we can
            target.mkdir(parents=True, exist_ok=True)
            for f in files_in_folder:
                if f.is_file():
                    dest = target / f.name
                    if not dest.exists():
                        try:
                            shutil.copy2(f, dest)
                        except (OSError, PermissionError):
                            pass  # skip locked files

        # Extract ZIPs
        if target.exists():
            extracted = extract_zips(target)
            if extracted:
                print(f"  Extracted {len(extracted)} files from ZIPs in {domain}/{target_name}")

        file_count = len(list(target.iterdir())) if target.exists() else 0
        total_size = sum(f.stat().st_size for f in target.iterdir() if f.is_file()) if target.exists() else 0

        organized.append({
            "slug": slug,
            "title": title,
            "domain": domain,
            "target": str(target),
            "files": file_count,
            "size_mb": total_size / 1024 / 1024,
        })

    # Summary
    print(f"\n{'=' * 60}")
    print(f"ORGANIZATION SUMMARY")
    print(f"{'=' * 60}")
    print(f"Datasets organized: {len(organized)}")
    print(f"\nBy domain:")
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        domain_files = sum(o["files"] for o in organized if o["domain"] == domain)
        domain_size = sum(o["size_mb"] for o in organized if o["domain"] == domain)
        print(f"  {domain:<20} {count:>3} datasets, {domain_files:>4} files, {domain_size:>8.1f} MB")

    # Save manifest
    manifest_path = ROOT / "registry" / "organized_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(organized, f, indent=2, ensure_ascii=False)
    print(f"\nManifest: {manifest_path}")

    # Report what's ready for lakehouse promotion
    existing_domains = {"gbd_results", "gbd_risk", "gbd_covariates", "population", "forecasts", "specialty"}
    new_domains = set(domain_counts.keys()) - existing_domains - {"unclassified"}
    if new_domains:
        print(f"\nNew domains (need promote modules): {', '.join(sorted(new_domains))}")

    print(f"\nNext steps:")
    print(f"  1. Run: ihme-data promote --all  (for existing domains)")
    print(f"  2. New domains need promote modules in src/ihme_data_lakehouse/promote/")
    print(f"  3. Run: ihme-data catalog  (to rebuild search index)")


if __name__ == "__main__":
    main()
