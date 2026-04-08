"""Tests for GBD Results promote module."""
import shutil
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.promote.gbd_results import promote_gbd_results

FIXTURES = Path(__file__).parent / "fixtures"

def _setup_raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw" / "gbd_results"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "gbd_results_sample.csv", raw / "gbd_results_sample.csv")
    return raw

def _setup_reference(tmp_path: Path) -> Path:
    ref = tmp_path / "reference"
    ref.mkdir(parents=True)
    shutil.copy(FIXTURES / "location_to_iso3.csv", ref / "location_to_iso3.csv")
    return ref

def test_promote_creates_native_parquet(tmp_path):
    raw = _setup_raw(tmp_path)
    ref = _setup_reference(tmp_path)
    promote_gbd_results(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    native_dir = tmp_path / "silver" / "gbd_results" / "native"
    assert native_dir.exists()
    deaths = native_dir / "deaths.parquet"
    assert deaths.exists()
    df = pd.read_parquet(deaths)
    assert len(df) > 0
    assert "cause_id" in df.columns
    assert "val" in df.columns

def test_promote_creates_harmonized_parquet(tmp_path):
    raw = _setup_raw(tmp_path)
    ref = _setup_reference(tmp_path)
    promote_gbd_results(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    harm_path = tmp_path / "silver" / "gbd_results" / "harmonized" / "gbd_results.parquet"
    assert harm_path.exists()
    df = pd.read_parquet(harm_path)
    assert set(df.columns) == {"iso3c", "year", "indicator_code", "indicator_name", "value", "lower", "upper", "sex", "age_group"}
    pak = df[df["iso3c"] == "PAK"]
    assert len(pak) > 0

def test_promote_creates_bronze_csv(tmp_path):
    raw = _setup_raw(tmp_path)
    ref = _setup_reference(tmp_path)
    promote_gbd_results(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    bronze_files = list((tmp_path / "bronze" / "gbd_results").glob("*.csv"))
    assert len(bronze_files) > 0
    df = pd.read_csv(bronze_files[0])
    assert "_source_file" in df.columns
    assert "_download_timestamp" in df.columns

def test_promote_rejects_bad_schema(tmp_path):
    raw = tmp_path / "raw" / "gbd_results"
    raw.mkdir(parents=True)
    pd.DataFrame({"foo": [1], "bar": [2]}).to_csv(raw / "bad.csv", index=False)
    ref = _setup_reference(tmp_path)
    results = promote_gbd_results(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    rejected = [r for r in results if r.get("status") == "rejected"]
    assert len(rejected) == 1
    assert "missing_columns" in rejected[0]
