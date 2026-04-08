"""Promote raw GBD Covariates/SDI CSV to bronze + silver."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.normalize import (
    GBD_COVARIATES_COLUMNS, SDI_COLUMNS, add_provenance, coerce_types, validate_columns,
)


def _is_codebook(df: pd.DataFrame) -> bool:
    """Detect IHME codebook files (first data row contains label metadata)."""
    if df.empty:
        return False
    first_vals = df.iloc[0].astype(str).str.lower()
    return any(v in ("label:", "value coding:", "description:") for v in first_vals)


def promote_gbd_covariates(raw_dir: Path, bronze_dir: Path, silver_dir: Path, reference_dir: Path, skip_existing: bool = False) -> list[dict]:
    native_dir = silver_dir / "gbd_covariates" / "native"
    harmonized_dir = silver_dir / "gbd_covariates" / "harmonized"
    bronze_out = bronze_dir / "gbd_covariates"
    native_dir.mkdir(parents=True, exist_ok=True)
    harmonized_dir.mkdir(parents=True, exist_ok=True)
    bronze_out.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(raw_dir.rglob("*.csv"))
    if not csv_files:
        return [{"domain": "gbd_covariates", "status": "no_csv_found"}]

    results: list[dict] = []
    all_frames: list[pd.DataFrame] = []

    for csv_path in csv_files:
        if skip_existing and (native_dir / "gbd_covariates.parquet").exists():
            results.append({"file": csv_path.name, "status": "skipped"})
            continue

        df = pd.read_csv(csv_path, low_memory=False)

        # Skip codebook files (contain metadata labels, not data)
        if _is_codebook(df):
            results.append({"file": csv_path.name, "status": "skipped_codebook"})
            continue

        # Try SDI-specific columns first, then generic covariates
        sdi_missing = validate_columns(df, SDI_COLUMNS, "sdi")
        generic_missing = validate_columns(df, GBD_COVARIATES_COLUMNS, "gbd_covariates")

        if sdi_missing and generic_missing:
            results.append({"file": csv_path.name, "status": "rejected", "missing_columns": generic_missing})
            continue

        df = coerce_types(df)
        bronze_df = add_provenance(df, csv_path.name)
        bronze_out_path = bronze_out / csv_path.name
        bronze_df.to_csv(bronze_out_path, index=False)

        all_frames.append(df)
        results.append({"file": csv_path.name, "status": "promoted", "rows": len(df)})

    if not all_frames:
        return results

    combined = pd.concat(all_frames, ignore_index=True)
    native_path = native_dir / "gbd_covariates.parquet"
    combined.to_parquet(native_path, index=False)
    results.append({"native": "gbd_covariates", "rows": len(combined), "path": str(native_path)})

    # Harmonized layer
    crosswalk_path = reference_dir / "location_to_iso3.parquet"
    if crosswalk_path.exists():
        crosswalk = pd.read_parquet(crosswalk_path)
    elif (reference_dir / "location_to_iso3.csv").exists():
        crosswalk = pd.read_csv(reference_dir / "location_to_iso3.csv")
    else:
        crosswalk = None

    if crosswalk is not None:
        merged = combined.merge(crosswalk[["location_id", "iso3c"]], on="location_id", how="left")

        # Determine indicator code from available columns
        if "covariate_name_short" in merged.columns:
            indicator_code = "sdi_" + merged["covariate_name_short"].astype(str)
            indicator_name = merged["covariate_name_short"]
        elif "covariate_id" in merged.columns:
            indicator_code = "cov_" + merged["covariate_id"].astype(str)
            indicator_name = merged.get("covariate_name", indicator_code)
        else:
            indicator_code = pd.Series("cov_unknown", index=merged.index)
            indicator_name = indicator_code

        sex_col = "sex" if "sex" in merged.columns else merged.get("sex_name", "")
        age_col = "age_group_name" if "age_group_name" in merged.columns else merged.get("age_name", "")

        harmonized = pd.DataFrame({
            "iso3c": merged["iso3c"],
            "year": merged["year_id"],
            "indicator_code": indicator_code,
            "indicator_name": indicator_name,
            "value": merged["mean_value"],
            "lower": merged["lower_value"],
            "upper": merged["upper_value"],
            "sex": sex_col if isinstance(sex_col, pd.Series) else pd.Series(sex_col, index=merged.index),
            "age_group": age_col if isinstance(age_col, pd.Series) else pd.Series(age_col, index=merged.index),
        })
        harm_path = harmonized_dir / "gbd_covariates.parquet"
        harmonized.to_parquet(harm_path, index=False)
        results.append({"harmonized": "gbd_covariates", "rows": len(harmonized), "path": str(harm_path)})

    return results
