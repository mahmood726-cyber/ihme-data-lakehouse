"""YAML registry loader, URL verification, and checksum management."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ihme_data_lakehouse.config import DOMAINS, REGISTRY_DIR


@dataclass
class RegistryFile:
    name: str
    url: str
    sha256: str | None
    requires_auth: bool
    size_hint: str = ""


@dataclass
class RegistryDomain:
    name: str
    description: str
    manual_fallback: bool
    files: list[RegistryFile] = field(default_factory=list)


def load_registry(path: Path | None = None) -> dict[str, RegistryDomain]:
    """Load sources.yaml and return {domain_name: RegistryDomain}."""
    if path is None:
        path = REGISTRY_DIR / "sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry: dict[str, RegistryDomain] = {}
    for domain_name, domain_data in raw.items():
        files = [
            RegistryFile(
                name=f["name"],
                url=f["url"],
                sha256=f.get("sha256"),
                requires_auth=f.get("requires_auth", False),
                size_hint=f.get("size_hint", ""),
            )
            for f in domain_data.get("files", [])
        ]
        registry[domain_name] = RegistryDomain(
            name=domain_name,
            description=domain_data.get("description", ""),
            manual_fallback=domain_data.get("manual_fallback", True),
            files=files,
        )
    return registry


def validate_registry(registry: dict[str, RegistryDomain]) -> list[str]:
    """Check registry for issues. Returns list of error strings (empty = valid)."""
    errors: list[str] = []
    seen_names: set[str] = set()

    for domain_name in DOMAINS:
        if domain_name not in registry:
            errors.append(f"Missing domain: {domain_name}")

    for domain_name, domain in registry.items():
        if not domain.files and not domain.manual_fallback:
            errors.append(f"{domain_name}: no files registered")
        for f in domain.files:
            if not f.name:
                errors.append(f"{domain_name}: file with empty name")
            if not f.url:
                errors.append(f"{domain_name}/{f.name}: empty URL")
            key = f"{domain_name}/{f.name}"
            if key in seen_names:
                errors.append(f"Duplicate file: {key}")
            seen_names.add(key)

    return errors


def update_checksum(
    registry_path: Path, domain_name: str, file_name: str, sha256: str
) -> None:
    """Update sha256 for a specific file in sources.yaml."""
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for f in raw[domain_name]["files"]:
        if f["name"] == file_name:
            f["sha256"] = sha256
            break
    registry_path.write_text(
        yaml.dump(raw, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
