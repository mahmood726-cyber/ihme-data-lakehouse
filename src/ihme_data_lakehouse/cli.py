"""CLI entry point: ihme-data command with subcommands."""
from __future__ import annotations

import argparse
import json
import sys

from ihme_data_lakehouse.config import (
    BRONZE_DIR, DATA_DIR, DOMAINS, MANIFEST_DIR, RAW_DIR, REFERENCE_DIR, REGISTRY_DIR, SILVER_DIR,
    ensure_project_directories,
)


def command_fetch(args) -> dict:
    from ihme_data_lakehouse.sources import fetch_domain
    if args.all:
        domains = list(DOMAINS)
    else:
        domains = [args.domain]
    results = {}
    for domain in domains:
        results[domain] = fetch_domain(domain, skip_existing=args.skip_existing, check_only=args.check_only)
    return results


def command_promote(args) -> dict:
    from ihme_data_lakehouse.promote.gbd_results import promote_gbd_results
    from ihme_data_lakehouse.promote.gbd_risk import promote_gbd_risk
    from ihme_data_lakehouse.promote.gbd_covariates import promote_gbd_covariates
    from ihme_data_lakehouse.promote.population import promote_population
    from ihme_data_lakehouse.promote.generic import promote_domain

    # Specialized promoters for domains with custom logic
    specialized = {
        "gbd_results": promote_gbd_results,
        "gbd_risk": promote_gbd_risk,
        "gbd_covariates": promote_gbd_covariates,
        "population": promote_population,
    }

    if args.all:
        domains = list(DOMAINS)
    else:
        domains = [args.domain]

    results = {}
    for domain in domains:
        raw_dir = RAW_DIR / domain
        if not raw_dir.exists():
            results[domain] = [{"status": "no_raw_dir"}]
            continue
        if domain in specialized:
            results[domain] = specialized[domain](raw_dir, BRONZE_DIR, SILVER_DIR, REFERENCE_DIR, skip_existing=args.skip_existing)
        else:
            results[domain] = promote_domain(domain, RAW_DIR, BRONZE_DIR, SILVER_DIR, REFERENCE_DIR, skip_existing=args.skip_existing)
    return results


def command_catalog(args) -> dict:
    from ihme_data_lakehouse.catalog import build_catalog
    output = DATA_DIR / "catalog.parquet"
    catalog = build_catalog(SILVER_DIR, output_path=output)
    return {"datasets": len(catalog), "output": str(output)}


def command_search(args) -> dict:
    import pandas as pd
    from ihme_data_lakehouse.catalog import search_catalog
    catalog_path = DATA_DIR / "catalog.parquet"
    if not catalog_path.exists():
        return {"error": "Catalog not found. Run 'ihme-data catalog' first."}
    catalog = pd.read_parquet(catalog_path)
    hits = search_catalog(catalog, keyword=args.keyword, domain=args.domain)
    records = hits.to_dict(orient="records")
    return {"matches": len(records), "results": records}


def command_registry_list(args) -> dict:
    from ihme_data_lakehouse.registry import load_registry
    registry = load_registry()
    rows = []
    for domain_name, domain in registry.items():
        for f in domain.files:
            rows.append({
                "domain": domain_name,
                "file": f.name,
                "url": f.url[:80] + "..." if len(f.url) > 80 else f.url,
                "requires_auth": f.requires_auth,
                "sha256": f.sha256[:16] + "..." if f.sha256 else None,
                "size_hint": f.size_hint,
            })
    return {"total_files": len(rows), "files": rows}


def command_registry_verify(args) -> dict:
    from ihme_data_lakehouse.http import compute_sha256
    from ihme_data_lakehouse.registry import load_registry
    registry = load_registry()
    results = []
    for domain_name, domain in registry.items():
        for f in domain.files:
            local = RAW_DIR / domain_name / f.name
            if not local.exists():
                results.append({"domain": domain_name, "file": f.name, "status": "missing"})
            elif f.sha256:
                actual = compute_sha256(local)
                ok = actual == f.sha256
                results.append({"domain": domain_name, "file": f.name, "status": "ok" if ok else "mismatch"})
            else:
                results.append({"domain": domain_name, "file": f.name, "status": "no_checksum"})
    return {"files": results}


def command_status(args) -> dict:
    from ihme_data_lakehouse.registry import load_registry
    registry = load_registry()
    status = {}
    for domain_name in DOMAINS:
        raw_dir = RAW_DIR / domain_name
        bronze_dir = BRONZE_DIR / domain_name
        native_dir = SILVER_DIR / domain_name / "native"
        harmonized_dir = SILVER_DIR / domain_name / "harmonized"

        raw_files = list(raw_dir.rglob("*.csv")) + list(raw_dir.rglob("*.zip")) if raw_dir.exists() else []
        bronze_files = list(bronze_dir.glob("*.csv")) if bronze_dir.exists() else []
        native_files = list(native_dir.glob("*.parquet")) if native_dir.exists() else []
        harmonized_files = list(harmonized_dir.glob("*.parquet")) if harmonized_dir.exists() else []

        registered = len(registry[domain_name].files) if domain_name in registry else 0

        status[domain_name] = {
            "registered_files": registered,
            "raw_files": len(raw_files),
            "bronze_files": len(bronze_files),
            "native_parquets": len(native_files),
            "harmonized_parquets": len(harmonized_files),
        }
    return status


def print_summary(summary: dict) -> None:
    print(json.dumps(summary, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ihme-data", description="IHME Data Lakehouse \u2014 registry-driven GBD data pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # fetch
    sp = subparsers.add_parser("fetch", help="Download data from registry URLs")
    sp.add_argument("domain", nargs="?", choices=DOMAINS, help="Domain to fetch")
    sp.add_argument("--all", action="store_true", help="Fetch all domains")
    sp.add_argument("--skip-existing", action="store_true", help="Skip already-downloaded files")
    sp.add_argument("--check-only", action="store_true", help="Only verify URL reachability")
    sp.set_defaults(handler=command_fetch)

    # promote
    sp = subparsers.add_parser("promote", help="Promote raw data to bronze + silver")
    sp.add_argument("domain", nargs="?", choices=DOMAINS, help="Domain to promote")
    sp.add_argument("--all", action="store_true", help="Promote all domains")
    sp.add_argument("--skip-existing", action="store_true", help="Skip existing silver files")
    sp.set_defaults(handler=command_promote)

    # catalog
    sp = subparsers.add_parser("catalog", help="Build master catalog from silver layer")
    sp.set_defaults(handler=command_catalog)

    # search
    sp = subparsers.add_parser("search", help="Search the catalog")
    sp.add_argument("keyword", help="Search keyword")
    sp.add_argument("--domain", help="Filter by domain")
    sp.set_defaults(handler=command_search)

    # registry list
    sp = subparsers.add_parser("registry-list", help="List all registered URLs")
    sp.set_defaults(handler=command_registry_list)

    # registry verify
    sp = subparsers.add_parser("registry-verify", help="Verify checksums of downloaded files")
    sp.set_defaults(handler=command_registry_verify)

    # status
    sp = subparsers.add_parser("status", help="Show pipeline status for all domains")
    sp.set_defaults(handler=command_status)

    return parser


def main() -> None:
    ensure_project_directories()
    parser = build_parser()
    args = parser.parse_args()

    if args.command in ("fetch", "promote") and not args.all and args.domain is None:
        parser.error("Specify a domain or use --all")

    summary = args.handler(args)
    print_summary(summary)
