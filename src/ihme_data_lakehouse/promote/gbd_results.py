"""Promote raw GBD Results CSV to bronze + silver (native + harmonized)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.normalize import (
    GBD_RESULTS_COLUMNS, MEASURE_NAMES, add_provenance, coerce_types, harmonize_gbd, validate_columns,
)

def promote_gbd_results(raw_dir: Path, bronze_dir: Path, silver_dir: Path, reference_dir: Path, skip_existing: bool = False) -> list[dict]:
    native_dir = silver_dir / "gbd_results" / "native"
    harmonized_dir = silver_dir / "gbd_results" / "harmonized"
    bronze_out = bronze_dir / "gbd_results"
    native_dir.mkdir(parents=True, exist_ok=True)
    harmonized_dir.mkdir(parents=True, exist_ok=True)
    bronze_out.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(raw_dir.rglob("*.csv"))
    if not csv_files:
        return [{"domain": "gbd_results", "status": "no_csv_found"}]

    results: list[dict] = []
    all_frames: list[pd.DataFrame] = []

    for csv_path in csv_files:
        if skip_existing and (native_dir / "deaths.parquet").exists():
            results.append({"file": csv_path.name, "status": "skipped"})
            continue

        df = pd.read_csv(csv_path, low_memory=False)
        missing = validate_columns(df, GBD_RESULTS_COLUMNS, "gbd_results")
        if missing:
            results.append({"file": csv_path.name, "status": "rejected", "missing_columns": missing})
            continue

        df = coerce_types(df)
        bronze_df = add_provenance(df, csv_path.name)
        bronze_path = bronze_out / csv_path.name
        bronze_df.to_csv(bronze_path, index=False)

        all_frames.append(df)
        results.append({"file": csv_path.name, "status": "promoted", "rows": len(df)})

    if not all_frames:
        return results

    combined = pd.concat(all_frames, ignore_index=True)

    # Silver native: partition by measure
    for measure_id, measure_name in MEASURE_NAMES.items():
        subset = combined[combined["measure_id"] == measure_id]
        if subset.empty:
            continue
        out_path = native_dir / f"{measure_name}.parquet"
        subset.to_parquet(out_path, index=False)
        results.append({"native": measure_name, "rows": len(subset), "path": str(out_path)})

    # Silver harmonized
    crosswalk_path = reference_dir / "location_to_iso3.parquet"
    if crosswalk_path.exists():
        crosswalk = pd.read_parquet(crosswalk_path)
    else:
        csv_crosswalk = reference_dir / "location_to_iso3.csv"
        if csv_crosswalk.exists():
            crosswalk = pd.read_csv(csv_crosswalk)
        else:
            crosswalk = None

    if crosswalk is not None:
        harmonized = harmonize_gbd(combined, crosswalk)
        harm_path = harmonized_dir / "gbd_results.parquet"
        harmonized.to_parquet(harm_path, index=False)
        results.append({"harmonized": "gbd_results", "rows": len(harmonized), "path": str(harm_path)})

    return results
