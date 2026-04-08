"""Bulk download comprehensive IHME GBD data via the GBD Results Tool API.

Usage:
    python scripts/bulk_download.py --login EMAIL PASSWORD
    python scripts/bulk_download.py --submit       # submit all queries
    python scripts/bulk_download.py --fetch         # download ready results
    python scripts/bulk_download.py --status        # check query status
"""
import io
import sys
import json
import time
import hashlib
import zipfile
import argparse
import requests
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "raw" / "gbd_results"
TASKS_FILE = ROOT / "scripts" / ".download_tasks.json"

API_BASE = "https://vizhub.healthdata.org/gbd-results/php"
DL_BASE = "https://dl.healthdata.org/gbd-api-2023-public"
TOKEN_URL = "https://login.healthdata.org/a07655f6-e482-42f3-8b30-6b7d009f813d/b2c_1a_signup_signin/oauth2/v2.0/token"
CLIENT_ID = "9e66b6a3-5d2e-400f-b812-f60f441d5041"

GBD_VERSION = 8352
GBD_ROUND = 2023


def get_hierarchy(session):
    """Get location and cause hierarchy."""
    resp = session.get(f"{API_BASE}/hierarchy/")
    resp.raise_for_status()
    return resp.json()["data"]


def get_metadata(session):
    """Get all metadata (measures, ages, locations, etc.)."""
    resp = session.get(f"{API_BASE}/metadata/?language=en")
    resp.raise_for_status()
    return resp.json()["data"]


def flatten_tree(node, depth=0):
    """Flatten a hierarchy tree, tracking depth."""
    result = [{"id": node["id"], "depth": depth}]
    for child in node.get("children", []):
        result.extend(flatten_tree(child, depth + 1))
    return result


def get_country_ids(hierarchy):
    """Get all country-level location IDs (depth 3)."""
    locs = []
    for root in hierarchy["locations"]:
        locs.extend(flatten_tree(root))
    return [l["id"] for l in locs if l["depth"] == 3]


def get_cause_ids(hierarchy):
    """Get level-3 cause IDs (specific diseases)."""
    causes = []
    for root in hierarchy["causes"]:
        for l1 in root.get("children", []):
            for l2 in l1.get("children", []):
                for l3 in l2.get("children", []):
                    causes.append(l3["id"])
    return causes


def submit_download(session, token, params, email):
    """Submit a download request to the GBD Results Tool."""
    body = {}
    for key, values in params.items():
        if isinstance(values, list):
            for i, v in enumerate(values):
                body[f"{key}[{i}]"] = v
        else:
            body[key] = values

    body.update({
        "version": str(GBD_VERSION),
        "start_year": "1980",
        "fetch_all_years": "false",
        "email": email,
        "idsOrNames": "both",
        "audience": "public",
        "gbdRound": str(GBD_ROUND),
        "toolID": "1",
        "language": "en",
        "base": "single",
    })

    for attempt in range(3):
        try:
            resp = session.post(
                f"{API_BASE}/download.php",
                data=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
            )
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text[:300], "error": "non-JSON response"}
            return resp.status_code, data
        except requests.exceptions.ReadTimeout:
            if attempt < 2:
                time.sleep(5)
                continue
            return 0, {"error": "timeout after 3 attempts"}


def build_queries(country_ids, cause_ids):
    """Build comprehensive download queries."""
    years = list(range(1990, 2024))
    all_ages = [22]  # All ages aggregate
    age_specific = [2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 30, 31, 32, 235]
    both_sex = [3]
    all_sex = [1, 2, 3]

    queries = []

    # === CAUSE-LEVEL DATA ===
    # 10 causes × 204 countries × 34 years × 1 metric = ~69K rows (under 100K limit)
    CAUSE_CHUNK = 10

    # 1. Deaths by specific cause (number only)
    for i in range(0, len(cause_ids), CAUSE_CHUNK):
        chunk = cause_ids[i:i+CAUSE_CHUNK]
        queries.append({
            "name": f"deaths_causes_{i//CAUSE_CHUNK+1}",
            "params": {
                "context": "cause", "population_group": "1",
                "year": years, "location": country_ids,
                "measure": [1], "metric": [1],
                "cause": chunk, "age": all_ages, "sex": both_sex,
            }
        })

    # 2. DALYs by specific cause (number only)
    for i in range(0, len(cause_ids), CAUSE_CHUNK):
        chunk = cause_ids[i:i+CAUSE_CHUNK]
        queries.append({
            "name": f"dalys_causes_{i//CAUSE_CHUNK+1}",
            "params": {
                "context": "cause", "population_group": "1",
                "year": years, "location": country_ids,
                "measure": [2], "metric": [1],
                "cause": chunk, "age": all_ages, "sex": both_sex,
            }
        })

    # 3. Prevalence + Incidence for all causes aggregate
    queries.append({
        "name": "prevalence_allcause",
        "params": {
            "context": "cause", "population_group": "1",
            "year": years, "location": country_ids,
            "measure": [5, 6], "metric": [1],
            "cause": [294], "age": all_ages, "sex": both_sex,
        }
    })

    # 4. Age-specific deaths, all causes (21 ages × 3 sex × 204 × 34 = ~437K — split by sex)
    for sex_id, sex_label in [(1, "male"), (2, "female"), (3, "both")]:
        queries.append({
            "name": f"deaths_by_age_{sex_label}",
            "params": {
                "context": "cause", "population_group": "1",
                "year": years, "location": country_ids,
                "measure": [1], "metric": [1],
                "cause": [294], "age": age_specific, "sex": [sex_id],
            }
        })

    # 5. Age-specific DALYs
    for sex_id, sex_label in [(1, "male"), (2, "female"), (3, "both")]:
        queries.append({
            "name": f"dalys_by_age_{sex_label}",
            "params": {
                "context": "cause", "population_group": "1",
                "year": years, "location": country_ids,
                "measure": [2], "metric": [1],
                "cause": [294], "age": age_specific, "sex": [sex_id],
            }
        })

    # === CARDIOLOGY FOCUS ===
    cvd_causes = [493, 494, 498, 499, 500, 501, 492, 503, 502, 507]

    # 6. CVD deaths, age-specific, both sexes
    queries.append({
        "name": "cvd_deaths_by_age",
        "params": {
            "context": "cause", "population_group": "1",
            "year": years, "location": country_ids,
            "measure": [1], "metric": [1],
            "cause": cvd_causes, "age": age_specific, "sex": both_sex,
        }
    })

    # 7. CVD DALYs, age-specific, both sexes
    queries.append({
        "name": "cvd_dalys_by_age",
        "params": {
            "context": "cause", "population_group": "1",
            "year": years, "location": country_ids,
            "measure": [2], "metric": [1],
            "cause": cvd_causes, "age": age_specific, "sex": both_sex,
        }
    })

    # 8. CVD prevalence + incidence
    queries.append({
        "name": "cvd_prevalence",
        "params": {
            "context": "cause", "population_group": "1",
            "year": years, "location": country_ids,
            "measure": [5, 6], "metric": [1],
            "cause": cvd_causes, "age": all_ages, "sex": both_sex,
        }
    })

    # === RISK FACTORS ===
    risk_factors = [107, 99, 108, 105, 367, 109, 86, 102, 130]

    # 9. Risk-attributable deaths
    queries.append({
        "name": "risk_deaths",
        "params": {
            "context": "risk", "population_group": "1",
            "year": years, "location": country_ids,
            "measure": [1], "metric": [1],
            "rei": risk_factors, "age": all_ages, "sex": both_sex,
        }
    })

    # 10. Risk-attributable DALYs
    queries.append({
        "name": "risk_dalys",
        "params": {
            "context": "risk", "population_group": "1",
            "year": years, "location": country_ids,
            "measure": [2], "metric": [1],
            "rei": risk_factors, "age": all_ages, "sex": both_sex,
        }
    })

    # === DEMOGRAPHIC ===

    # 11. Population by age + sex (split by sex to stay under limit)
    for sex_id, sex_label in [(1, "male"), (2, "female"), (3, "both")]:
        queries.append({
            "name": f"population_by_age_{sex_label}",
            "params": {
                "context": "population", "population_group": "1",
                "year": years, "location": country_ids,
                "measure": [44], "metric": [1],
                "age": age_specific, "sex": [sex_id],
            }
        })

    return queries


def cmd_submit(args):
    """Submit all download queries."""
    session = requests.Session()
    session.headers.update({"User-Agent": "IHME-DataLakehouse/1.0"})

    print("Fetching hierarchy and metadata...")
    hierarchy = get_hierarchy(session)
    country_ids = get_country_ids(hierarchy)
    cause_ids = get_cause_ids(hierarchy)
    print(f"  {len(country_ids)} countries, {len(cause_ids)} level-3 causes")

    queries = build_queries(country_ids, cause_ids)
    print(f"  {len(queries)} queries to submit")

    # Load or create tasks file
    tasks = {}
    if TASKS_FILE.exists():
        tasks = json.loads(TASKS_FILE.read_text())

    submitted = 0
    for q in queries:
        if q["name"] in tasks and tasks[q["name"]].get("status") == "submitted":
            print(f"  SKIP (already submitted): {q['name']}")
            continue

        try:
            status, data = submit_download(session, args.token, q["params"], args.email)
        except Exception as e:
            tasks[q["name"]] = {"status": "error", "code": 0, "data": str(e)[:200]}
            print(f"  EXCEPTION: {q['name']} -> {e}")
            TASKS_FILE.write_text(json.dumps(tasks, indent=2))
            time.sleep(2)
            continue

        if status == 202:
            tasks[q["name"]] = {
                "status": "submitted",
                "taskID": data["taskID"],
                "url": data.get("urlForUser", ""),
            }
            submitted += 1
            print(f"  SUBMITTED: {q['name']} -> {data['taskID'][:12]}...")
        elif status == 413:
            tasks[q["name"]] = {"status": "too_large", "code": status}
            print(f"  TOO LARGE: {q['name']} — will need smaller chunks")
        else:
            tasks[q["name"]] = {"status": "error", "code": status, "data": str(data)[:200]}
            print(f"  ERROR ({status}): {q['name']}")

        # Save progress after each query
        TASKS_FILE.write_text(json.dumps(tasks, indent=2))
        # Rate limit
        time.sleep(1)

    TASKS_FILE.write_text(json.dumps(tasks, indent=2))
    print(f"\n{submitted} new queries submitted. {len(tasks)} total tracked in {TASKS_FILE.name}")


def cmd_fetch(args):
    """Download all ready results."""
    if not TASKS_FILE.exists():
        print("No tasks file. Run --submit first.")
        return

    tasks = json.loads(TASKS_FILE.read_text())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "IHME-DataLakehouse/1.0"})

    downloaded = 0
    still_pending = 0
    for name, info in tasks.items():
        if info.get("status") == "downloaded":
            continue
        if info.get("status") != "submitted":
            continue

        tid = info["taskID"]
        short = tid[:8]
        dest = DATA_DIR / f"IHME_GBD_2023_{name}.zip"

        if dest.exists():
            info["status"] = "downloaded"
            continue

        url = f"{DL_BASE}/{tid}_files/IHME-GBD_2023_DATA-{short}-1.zip"
        resp = session.get(url, stream=True, timeout=120)

        if resp.status_code == 200:
            h = hashlib.sha256()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8 * 1024 * 1024):
                    f.write(chunk)
                    h.update(chunk)
            info["status"] = "downloaded"
            info["size"] = dest.stat().st_size
            info["sha256"] = h.hexdigest()[:16]
            downloaded += 1
            print(f"  OK: {name} ({dest.stat().st_size:,} bytes)")

            # Extract CSV
            try:
                with zipfile.ZipFile(dest) as z:
                    for member in z.namelist():
                        if member.endswith(".csv"):
                            z.extract(member, DATA_DIR)
            except Exception:
                pass
        else:
            still_pending += 1
            if args.verbose:
                print(f"  PENDING: {name} (404)")

    TASKS_FILE.write_text(json.dumps(tasks, indent=2))
    total_done = sum(1 for v in tasks.values() if v.get("status") == "downloaded")
    print(f"\n{downloaded} new downloads, {total_done}/{len(tasks)} complete, {still_pending} pending")


def cmd_status(args):
    """Show status of all tracked tasks."""
    if not TASKS_FILE.exists():
        print("No tasks file. Run --submit first.")
        return

    tasks = json.loads(TASKS_FILE.read_text())
    by_status = {}
    for name, info in tasks.items():
        s = info.get("status", "unknown")
        by_status.setdefault(s, []).append(name)

    for status, names in sorted(by_status.items()):
        print(f"\n{status.upper()} ({len(names)}):")
        for n in names:
            extra = ""
            if tasks[n].get("size"):
                extra = f" ({tasks[n]['size']:,} bytes)"
            print(f"  {n}{extra}")


def main():
    parser = argparse.ArgumentParser(description="Bulk IHME GBD data download")
    sub = parser.add_subparsers(dest="command")

    p_submit = sub.add_parser("submit", help="Submit download queries")
    p_submit.add_argument("--token", required=True, help="Bearer token from VizHub")
    p_submit.add_argument("--email", default="mahmood.ahmad2@nhs.net")

    p_fetch = sub.add_parser("fetch", help="Download ready results")
    p_fetch.add_argument("--verbose", "-v", action="store_true")

    sub.add_parser("status", help="Show task status")

    args = parser.parse_args()
    if args.command == "submit":
        cmd_submit(args)
    elif args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
