"""Tests for catalog builder and search."""
import shutil
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.catalog import build_catalog, search_catalog
from ihme_data_lakehouse.promote.gbd_results import promote_gbd_results

FIXTURES = Path(__file__).parent / "fixtures"

def _build_silver(tmp_path):
    raw = tmp_path / "raw" / "gbd_results"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "gbd_results_sample.csv", raw / "sample.csv")
    ref = tmp_path / "reference"
    ref.mkdir(parents=True)
    shutil.copy(FIXTURES / "location_to_iso3.csv", ref / "location_to_iso3.csv")
    promote_gbd_results(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    return tmp_path / "silver"

def test_build_catalog(tmp_path):
    silver = _build_silver(tmp_path)
    catalog = build_catalog(silver)
    assert len(catalog) > 0
    assert "domain" in catalog.columns
    assert "tier" in catalog.columns
    assert catalog["domain"].iloc[0] == "gbd_results"

def test_catalog_save_to_parquet(tmp_path):
    silver = _build_silver(tmp_path)
    out = tmp_path / "catalog.parquet"
    catalog = build_catalog(silver, output_path=out)
    assert out.exists()
    loaded = pd.read_parquet(out)
    assert len(loaded) == len(catalog)

def test_search_by_keyword(tmp_path):
    silver = _build_silver(tmp_path)
    catalog = build_catalog(silver)
    hits = search_catalog(catalog, keyword="deaths")
    assert len(hits) > 0
    assert all("deaths" in row.lower() for row in hits["dataset"])

def test_search_by_domain(tmp_path):
    silver = _build_silver(tmp_path)
    catalog = build_catalog(silver)
    hits = search_catalog(catalog, domain="gbd_results")
    assert len(hits) == len(catalog)

def test_search_by_tier(tmp_path):
    silver = _build_silver(tmp_path)
    catalog = build_catalog(silver)
    native = search_catalog(catalog, tier="native")
    harmonized = search_catalog(catalog, tier="harmonized")
    assert len(native) > 0
    assert len(harmonized) > 0
    assert len(native) + len(harmonized) == len(catalog)
