"""IHME-specific normalization: type coercion, provenance, harmonization."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# Expected columns per domain (required subset — extras are kept)
GBD_RESULTS_COLUMNS = {
    "measure_id", "measure_name", "location_id", "location_name",
    "sex_id", "sex_name", "age_id", "age_name",
    "cause_id", "cause_name", "year", "val", "upper", "lower",
    "metric_id", "metric_name",
}

GBD_RISK_COLUMNS = GBD_RESULTS_COLUMNS | {"rei_id", "rei_name"}

GBD_COVARIATES_COLUMNS = {
    "location_id", "location_name", "year_id",
    "mean_value", "lower_value", "upper_value",
}

# SDI files use these column names (different from generic covariates)
SDI_COLUMNS = {
    "covariate_name_short", "location_id", "location_name",
    "year_id", "age_group_id", "age_group_name",
    "sex_id", "sex", "mean_value", "lower_value", "upper_value",
}

POPULATION_COLUMNS = {
    "location_id", "location_name", "sex_id",
    "val", "upper", "lower",
}
# Accepts either "year" (GBD Results Tool) or "year_id" (legacy format)

# Old-format population files use these columns
POPULATION_COLUMNS_LEGACY = {
    "location_id", "location_name", "sex_id", "sex_name",
    "age_group_id", "age_group_name", "year_id",
    "val", "upper", "lower",
}

MEASURE_NAMES = {
    1: "deaths", 2: "dalys", 3: "ylds", 4: "ylls",
    5: "prevalence", 6: "incidence",
    25: "mmr", 26: "life_expectancy", 27: "prob_death",
    28: "hale", 44: "population",
}

GBD_ROUND = 2023
GBD_API_VERSION = 8352


def validate_columns(df: pd.DataFrame, required: set[str], domain: str) -> list[str]:
    """Check that required columns are present. Returns list of missing columns."""
    present = set(df.columns)
    missing = required - present
    return sorted(missing)


_KNOWN_INT_COLS = {
    "location_id", "sex_id", "age_id", "age_group_id", "cause_id",
    "rei_id", "measure_id", "metric_id", "year", "year_id",
    "covariate_id",
}

_KNOWN_FLOAT_COLS = {
    "val", "upper", "lower", "mean_value", "upper_value", "lower_value",
    "mean", "rate", "percent", "se",
}


def coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce known IHME columns to correct types. Leaves unknown columns untouched."""
    out = df.copy()

    for col in out.columns:
        if col in _KNOWN_INT_COLS:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
        elif col in _KNOWN_FLOAT_COLS:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def add_provenance(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Add provenance columns for bronze tier."""
    out = df.copy()
    out["_source_file"] = source_file
    out["_download_timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


def harmonize_gbd(
    df: pd.DataFrame,
    location_crosswalk: pd.DataFrame,
    id_col: str = "cause_id",
    name_col: str = "cause_name",
) -> pd.DataFrame:
    """Convert IHME-native DataFrame to harmonized cross-lakehouse schema.

    Args:
        df: Native IHME DataFrame with standard GBD columns.
        location_crosswalk: DataFrame with columns [location_id, iso3c].
        id_col: Column containing the entity ID (cause_id or rei_id).
        name_col: Column containing the entity name (cause_name or rei_name).

    Returns:
        DataFrame with columns: iso3c, year, indicator_code, indicator_name,
        value, lower, upper, sex, age_group.
    """
    merged = df.merge(location_crosswalk[["location_id", "iso3c"]], on="location_id", how="left")

    year_col = "year" if "year" in merged.columns else "year_id"

    merged["indicator_code"] = (
        merged[id_col].astype(str) + "_"
        + merged["measure_id"].astype(str) + "_"
        + merged["metric_id"].astype(str)
    )
    merged["indicator_name"] = (
        merged[name_col] + " — "
        + merged["measure_name"] + " — "
        + merged["metric_name"]
    )

    val_col = "val" if "val" in merged.columns else "mean_value"
    lower_col = "lower" if "lower" in merged.columns else "lower_value"
    upper_col = "upper" if "upper" in merged.columns else "upper_value"

    harmonized = pd.DataFrame({
        "iso3c": merged["iso3c"],
        "year": merged[year_col],
        "indicator_code": merged["indicator_code"],
        "indicator_name": merged["indicator_name"],
        "value": merged[val_col],
        "lower": merged[lower_col],
        "upper": merged[upper_col],
        "sex": merged["sex_name"],
        "age_group": merged["age_name"] if "age_name" in merged.columns else merged.get("age_group_name", ""),
    })

    return harmonized
