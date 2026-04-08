"""Tests for IHME normalization module."""
import pandas as pd

from ihme_data_lakehouse.normalize import (
    GBD_RESULTS_COLUMNS,
    GBD_RISK_COLUMNS,
    add_provenance,
    coerce_types,
    harmonize_gbd,
    validate_columns,
)

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_validate_columns_gbd_results():
    df = pd.read_csv(FIXTURES / "gbd_results_sample.csv")
    missing = validate_columns(df, GBD_RESULTS_COLUMNS, "gbd_results")
    assert missing == [], f"Missing columns: {missing}"


def test_validate_columns_gbd_risk():
    df = pd.read_csv(FIXTURES / "gbd_risk_sample.csv")
    missing = validate_columns(df, GBD_RISK_COLUMNS, "gbd_risk")
    assert missing == [], f"Missing columns: {missing}"


def test_coerce_types_ids_are_int():
    df = pd.read_csv(FIXTURES / "gbd_results_sample.csv")
    coerced = coerce_types(df)
    assert coerced["measure_id"].dtype.name == "Int64"
    assert coerced["location_id"].dtype.name == "Int64"
    assert coerced["year"].dtype.name == "Int64"


def test_coerce_types_vals_are_float():
    df = pd.read_csv(FIXTURES / "gbd_results_sample.csv")
    coerced = coerce_types(df)
    assert coerced["val"].dtype == "float64"
    assert coerced["upper"].dtype == "float64"
    assert coerced["lower"].dtype == "float64"


def test_add_provenance():
    df = pd.read_csv(FIXTURES / "gbd_results_sample.csv")
    with_prov = add_provenance(df, "test_file.csv")
    assert "_source_file" in with_prov.columns
    assert "_download_timestamp" in with_prov.columns
    assert with_prov["_source_file"].iloc[0] == "test_file.csv"


def test_harmonize_gbd_results():
    df = pd.read_csv(FIXTURES / "gbd_results_sample.csv")
    crosswalk = pd.read_csv(FIXTURES / "location_to_iso3.csv")
    harmonized = harmonize_gbd(df, crosswalk)
    assert set(harmonized.columns) == {
        "iso3c", "year", "indicator_code", "indicator_name",
        "value", "lower", "upper", "sex", "age_group",
    }
    pak_rows = harmonized[harmonized["iso3c"] == "PAK"]
    assert len(pak_rows) > 0
    assert harmonized["iso3c"].isna().any()


def test_harmonize_indicator_code_format():
    df = pd.read_csv(FIXTURES / "gbd_results_sample.csv")
    crosswalk = pd.read_csv(FIXTURES / "location_to_iso3.csv")
    harmonized = harmonize_gbd(df, crosswalk)
    first = harmonized["indicator_code"].iloc[0]
    parts = first.split("_")
    assert len(parts) == 3, f"Expected 3 parts in indicator_code, got: {first}"
