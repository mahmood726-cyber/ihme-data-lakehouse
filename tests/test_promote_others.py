"""Tests for covariates, population, forecasts, and specialty promote modules."""
import shutil
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.promote.gbd_covariates import promote_gbd_covariates
from ihme_data_lakehouse.promote.population import promote_population
from ihme_data_lakehouse.promote.forecasts import promote_forecasts
from ihme_data_lakehouse.promote.specialty import promote_specialty

FIXTURES = Path(__file__).parent / "fixtures"

def _ref(tmp_path):
    ref = tmp_path / "reference"
    ref.mkdir(parents=True)
    shutil.copy(FIXTURES / "location_to_iso3.csv", ref / "location_to_iso3.csv")
    return ref

def test_promote_covariates(tmp_path):
    raw = tmp_path / "raw" / "gbd_covariates"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "gbd_covariates_sample.csv", raw / "covariates.csv")
    ref = _ref(tmp_path)
    promote_gbd_covariates(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    native = tmp_path / "silver" / "gbd_covariates" / "native" / "gbd_covariates.parquet"
    assert native.exists()
    df = pd.read_parquet(native)
    assert "covariate_id" in df.columns
    assert len(df) == 5

def test_promote_covariates_harmonized_indicator_code(tmp_path):
    raw = tmp_path / "raw" / "gbd_covariates"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "gbd_covariates_sample.csv", raw / "covariates.csv")
    ref = _ref(tmp_path)
    promote_gbd_covariates(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    harm = tmp_path / "silver" / "gbd_covariates" / "harmonized" / "gbd_covariates.parquet"
    assert harm.exists()
    df = pd.read_parquet(harm)
    assert df["indicator_code"].iloc[0].startswith("cov_")

def test_promote_population(tmp_path):
    raw = tmp_path / "raw" / "population"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "population_sample.csv", raw / "pop.csv")
    ref = _ref(tmp_path)
    promote_population(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    native = tmp_path / "silver" / "population" / "native" / "population.parquet"
    assert native.exists()
    df = pd.read_parquet(native)
    assert len(df) == 5

def test_promote_forecasts(tmp_path):
    raw = tmp_path / "raw" / "forecasts"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "forecasts_sample.csv", raw / "forecasts.csv")
    ref = _ref(tmp_path)
    promote_forecasts(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    native_dir = tmp_path / "silver" / "forecasts" / "native"
    assert native_dir.exists()
    parquets = list(native_dir.glob("*.parquet"))
    assert len(parquets) >= 2

def test_promote_specialty_igme(tmp_path):
    raw = tmp_path / "raw" / "specialty"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "specialty_igme_sample.csv", raw / "igme.csv")
    ref = _ref(tmp_path)
    promote_specialty(raw, tmp_path / "bronze", tmp_path / "silver", ref)
    native = tmp_path / "silver" / "specialty" / "native"
    assert len(list(native.glob("*.parquet"))) == 1
    harm = tmp_path / "silver" / "specialty" / "harmonized" / "specialty.parquet"
    assert harm.exists()
    df = pd.read_parquet(harm)
    assert "PAK" in df["iso3c"].values
