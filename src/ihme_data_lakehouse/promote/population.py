"""Promote raw IHME population CSV to bronze + silver."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.normalize import (
    POPULATION_COLUMNS, add_provenance, coerce_types, validate_columns,
)

def promote_population(raw_dir: Path, bronze_dir: Path, silver_dir: Path, reference_dir: Path, skip_existing: bool = False) -> list[dict]:
    native_dir = silver_dir / "population" / "native"
    harmonized_dir = silver_dir / "population" / "harmonized"
    bronze_out = bronze_dir / "population"
    native_dir.mkdir(parents=True, exist_ok=True)
    harmonized_dir.mkdir(parents=True, exist_ok=True)
    bronze_out.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(raw_dir.rglob("*.csv"))
    if not csv_files:
        return [{"domain": "population", "status": "no_csv_found"}]

    results: list[dict] = []
    all_frames: list[pd.DataFrame] = []

    for csv_path in csv_files:
        if skip_existing and (native_dir / "population.parquet").exists():
            results.append({"file": csv_path.name, "status": "skipped"})
            continue

        df = pd.read_csv(csv_path, low_memory=False)
        missing = validate_columns(df, POPULATION_COLUMNS, "population")
        if missing:
            results.append({"file": csv_path.name, "status": "rejected", "missing_columns": missing})
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
    native_path = native_dir / "population.parquet"
    combined.to_parquet(native_path, index=False)
    results.append({"native": "population", "rows": len(combined), "path": str(native_path)})

    crosswalk_path = reference_dir / "location_to_iso3.parquet"
    if crosswalk_path.exists():
        crosswalk = pd.read_parquet(crosswalk_path)
    elif (reference_dir / "location_to_iso3.csv").exists():
        crosswalk = pd.read_csv(reference_dir / "location_to_iso3.csv")
    else:
        crosswalk = None

    if crosswalk is not None:
        merged = combined.merge(crosswalk[["location_id", "iso3c"]], on="location_id", how="left")
        harmonized = pd.DataFrame({
            "iso3c": merged["iso3c"],
            "year": merged["year_id"],
            "indicator_code": "pop_" + merged["sex_id"].astype(str) + "_" + merged["age_group_id"].astype(str),
            "indicator_name": "Population — " + merged["sex_name"] + " — " + merged["age_group_name"],
            "value": merged["val"],
            "lower": merged["lower"],
            "upper": merged["upper"],
            "sex": merged["sex_name"],
            "age_group": merged["age_group_name"],
        })
        harm_path = harmonized_dir / "population.parquet"
        harmonized.to_parquet(harm_path, index=False)
        results.append({"harmonized": "population", "rows": len(harmonized), "path": str(harm_path)})

    return results
