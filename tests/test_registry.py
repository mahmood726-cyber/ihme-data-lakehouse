"""Tests for registry loading and validation."""
from pathlib import Path

import yaml

from ihme_data_lakehouse.registry import (
    load_registry,
    validate_registry,
)


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "registry" / "sources.yaml"


def test_registry_loads():
    registry = load_registry(REGISTRY_PATH)
    assert len(registry) >= 6


def test_registry_validates_clean():
    registry = load_registry(REGISTRY_PATH)
    errors = validate_registry(registry)
    assert errors == [], f"Registry validation errors: {errors}"


def test_registry_all_domains_present():
    registry = load_registry(REGISTRY_PATH)
    for domain in ("gbd_results", "gbd_risk", "gbd_covariates", "population", "forecasts", "specialty"):
        assert domain in registry, f"Missing domain: {domain}"
        assert len(registry[domain].files) > 0, f"{domain} has no files"


def test_registry_no_duplicate_filenames():
    registry = load_registry(REGISTRY_PATH)
    seen = set()
    for domain_name, domain in registry.items():
        for f in domain.files:
            key = f"{domain_name}/{f.name}"
            assert key not in seen, f"Duplicate: {key}"
            seen.add(key)


def test_validate_catches_missing_domain(tmp_path):
    """A registry missing a required domain should report an error."""
    minimal = {
        "gbd_results": {
            "description": "test",
            "manual_fallback": True,
            "files": [{"name": "a.zip", "url": "https://example.com/a.zip"}],
        }
    }
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.dump(minimal), encoding="utf-8")
    registry = load_registry(path)
    errors = validate_registry(registry)
    assert any("Missing domain" in e for e in errors)
