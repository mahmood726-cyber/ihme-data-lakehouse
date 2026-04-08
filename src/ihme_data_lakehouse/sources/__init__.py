"""Shared fetch engine for all IHME data sources."""
from __future__ import annotations

import zipfile
from pathlib import Path

from ihme_data_lakehouse.config import RAW_DIR, REGISTRY_DIR
from ihme_data_lakehouse.http import build_session, check_url_reachable, compute_sha256, download_to_path
from ihme_data_lakehouse.registry import RegistryFile, load_registry, update_checksum
from ihme_data_lakehouse.storage import write_manifest


def fetch_domain(
    domain_name: str,
    raw_dir: Path | None = None,
    registry_path: Path | None = None,
    manifest_dir: Path | None = None,
    skip_existing: bool = False,
    check_only: bool = False,
) -> dict:
    """Fetch all files for a domain from the registry.

    Returns a summary dict suitable for manifest writing.
    """
    from ihme_data_lakehouse.config import MANIFEST_DIR

    if raw_dir is None:
        raw_dir = RAW_DIR
    if registry_path is None:
        registry_path = REGISTRY_DIR / "sources.yaml"
    if manifest_dir is None:
        manifest_dir = MANIFEST_DIR

    registry = load_registry(registry_path)
    if domain_name not in registry:
        return {"domain": domain_name, "status": "error", "reason": f"Unknown domain: {domain_name}"}

    domain = registry[domain_name]
    session = build_session()
    domain_dir = raw_dir / domain_name
    domain_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    for entry in domain.files:
        result = _fetch_one(session, entry, domain_name, domain_dir, registry_path, skip_existing, check_only)
        results.append(result)

    summary = {
        "domain": domain_name,
        "description": domain.description,
        "status": "check_only" if check_only else "fetched",
        "files": results,
        "fetched_count": sum(1 for r in results if r["status"] == "downloaded"),
        "cached_count": sum(1 for r in results if r["status"] == "cached"),
        "manual_count": sum(1 for r in results if r["status"] == "manual_required"),
    }

    return write_manifest(f"fetch_{domain_name}", summary, manifest_dir)


def _fetch_one(
    session,
    entry: RegistryFile,
    domain_name: str,
    domain_dir: Path,
    registry_path: Path,
    skip_existing: bool,
    check_only: bool,
) -> dict:
    """Fetch a single file from the registry."""
    local_path = domain_dir / entry.name

    # Check for existing file
    if local_path.exists():
        if entry.sha256:
            actual = compute_sha256(local_path)
            if actual == entry.sha256:
                return {"file": entry.name, "status": "cached", "path": str(local_path), "checksum": "verified"}
            else:
                return {"file": entry.name, "status": "checksum_mismatch", "expected": entry.sha256, "actual": actual}
        if skip_existing:
            return {"file": entry.name, "status": "cached", "path": str(local_path), "checksum": "unverified"}

    if check_only:
        ok, code = check_url_reachable(session, entry.url)
        return {"file": entry.name, "status": "reachable" if ok else "unreachable", "http_status": code}

    # Requires auth — manual placement only
    if entry.requires_auth:
        if local_path.exists():
            return {"file": entry.name, "status": "manual_accepted", "path": str(local_path)}
        return {
            "file": entry.name,
            "status": "manual_required",
            "instructions": f"Download from {entry.url} and place at {local_path}",
        }

    # Attempt download
    try:
        download_to_path(session, entry.url, local_path)
        sha = compute_sha256(local_path)
        update_checksum(registry_path, domain_name, entry.name, sha)

        # Extract ZIP if applicable
        extracted = []
        if local_path.suffix.lower() == ".zip":
            extracted = _extract_zip(local_path, domain_dir)

        return {
            "file": entry.name,
            "status": "downloaded",
            "path": str(local_path),
            "sha256": sha,
            "extracted": extracted,
        }
    except Exception as exc:
        return {"file": entry.name, "status": "error", "reason": str(exc)}


def _extract_zip(zip_path: Path, dest_dir: Path) -> list[str]:
    """Extract ZIP contents to dest_dir/{zip_stem}/. Returns list of extracted paths."""
    extract_dir = dest_dir / zip_path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            zf.extract(member, extract_dir)
            extracted.append(str(extract_dir / member))
    return extracted
