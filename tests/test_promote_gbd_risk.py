"""Tests for GBD Risk Factor promote module."""
import shutil
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.promote.gbd_risk import promote_gbd_risk

FIXTURES = Path(__file__).parent / "fixtures"

def _setup(tmp_path):
    raw = tmp_path / "raw" / "gbd_risk"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "gbd_risk_sample.csv", raw / "gbd_risk_sample.csv")
    ref = tmp_path / "reference"
    ref.mkdir(parents=True)
    shutil.copy(FIXTURES / "location_to_iso3.csv", ref / "location_to_iso3.csv")
    return raw, ref

def test_promote_risk_native(tmp_path):
    raw, ref = _setup(tmp_path)
    promote_gbd_risk(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    native = tmp_path / "silver" / "gbd_risk" / "native" / "gbd_risk.parquet"
    assert native.exists()
    df = pd.read_parquet(native)
    assert "rei_id" in df.columns
    assert "rei_name" in df.columns
    assert len(df) == 4

def test_promote_risk_harmonized_uses_rei(tmp_path):
    raw, ref = _setup(tmp_path)
    promote_gbd_risk(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    harm = tmp_path / "silver" / "gbd_risk" / "harmonized" / "gbd_risk.parquet"
    assert harm.exists()
    df = pd.read_parquet(harm)
    first_code = df["indicator_code"].iloc[0]
    assert first_code.startswith("107_")

def test_promote_risk_bronze(tmp_path):
    raw, ref = _setup(tmp_path)
    promote_gbd_risk(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    bronze_files = list((tmp_path / "bronze" / "gbd_risk").glob("*.csv"))
    assert len(bronze_files) == 1
