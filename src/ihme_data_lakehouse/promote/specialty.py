"""Promote specialty datasets (IGME, AMR, subnational) to bronze + silver."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.normalize import add_provenance

def promote_specialty(raw_dir: Path, bronze_dir: Path, silver_dir: Path, reference_dir: Path, skip_existing: bool = False) -> list[dict]:
    native_dir = silver_dir / "specialty" / "native"
    harmonized_dir = silver_dir / "specialty" / "harmonized"
    bronze_out = bronze_dir / "specialty"
    native_dir.mkdir(parents=True, exist_ok=True)
    harmonized_dir.mkdir(parents=True, exist_ok=True)
    bronze_out.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(raw_dir.rglob("*.csv"))
    if not csv_files:
        return [{"domain": "specialty", "status": "no_csv_found"}]

    results: list[dict] = []
    harmonized_frames: list[pd.DataFrame] = []

    for csv_path in csv_files:
        stem = csv_path.stem.lower().replace("-", "_").replace(" ", "_")
        native_path = native_dir / f"{stem}.parquet"

        if skip_existing and native_path.exists():
            results.append({"file": csv_path.name, "status": "skipped"})
            continue

        df = pd.read_csv(csv_path, low_memory=False)
        if df.empty:
            results.append({"file": csv_path.name, "status": "empty"})
            continue

        bronze_df = add_provenance(df, csv_path.name)
        bronze_path = bronze_out / csv_path.name
        bronze_df.to_csv(bronze_path, index=False)

        df.to_parquet(native_path, index=False)
        results.append({"file": csv_path.name, "status": "promoted", "rows": len(df)})

        if "ISO3Code" in df.columns and "Obs Value" in df.columns:
            h = pd.DataFrame({
                "iso3c": df["ISO3Code"],
                "year": pd.to_numeric(df.get("Year", pd.Series(dtype="Int64")), errors="coerce"),
                "indicator_code": "igme_" + df["Indicator"].str.lower().str.replace(" ", "_", regex=False),
                "indicator_name": df["Indicator"],
                "value": pd.to_numeric(df["Obs Value"], errors="coerce"),
                "lower": pd.to_numeric(df.get("Lower Bound", pd.Series(dtype="float64")), errors="coerce"),
                "upper": pd.to_numeric(df.get("Upper Bound", pd.Series(dtype="float64")), errors="coerce"),
                "sex": df.get("Sex", ""),
                "age_group": "",
            })
            harmonized_frames.append(h)

    if harmonized_frames:
        combined = pd.concat(harmonized_frames, ignore_index=True)
        harm_path = harmonized_dir / "specialty.parquet"
        combined.to_parquet(harm_path, index=False)
        results.append({"harmonized": "specialty", "rows": len(combined), "path": str(harm_path)})

    return results
