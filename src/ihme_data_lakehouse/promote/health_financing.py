"""Promote raw Health Financing data to bronze + silver."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.normalize import add_provenance, coerce_types


def promote_health_financing(raw_dir: Path, bronze_dir: Path, silver_dir: Path, reference_dir: Path, skip_existing: bool = False) -> list[dict]:
    native_dir = silver_dir / "health_financing" / "native"
    bronze_out = bronze_dir / "health_financing"
    native_dir.mkdir(parents=True, exist_ok=True)
    bronze_out.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    # Process each dataset folder
    for dataset_dir in sorted(raw_dir.iterdir()):
        if not dataset_dir.is_dir():
            continue

        dataset_name = dataset_dir.name
        parquet_path = native_dir / f"{dataset_name}.parquet"

        if skip_existing and parquet_path.exists():
            results.append({"dataset": dataset_name, "status": "skipped"})
            continue

        frames = []
        for csv_path in sorted(dataset_dir.glob("*.csv")) + sorted(dataset_dir.glob("*.CSV")):
            try:
                df = pd.read_csv(csv_path, low_memory=False)
                if len(df) < 2:
                    continue
                df = coerce_types(df)
                bronze_df = add_provenance(df, csv_path.name)
                bronze_df.to_csv(bronze_out / f"{dataset_name}_{csv_path.name}", index=False)
                frames.append(df)
            except Exception as e:
                results.append({"file": csv_path.name, "status": "error", "error": str(e)[:100]})

        for xlsx_path in sorted(dataset_dir.glob("*.xlsx")) + sorted(dataset_dir.glob("*.XLSX")):
            try:
                df = pd.read_excel(xlsx_path)
                if len(df) < 2:
                    continue
                df = coerce_types(df)
                frames.append(df)
            except Exception as e:
                results.append({"file": xlsx_path.name, "status": "error", "error": str(e)[:100]})

        if frames:
            # Save each frame as its own parquet (different schemas)
            for i, df in enumerate(frames):
                suffix = f"_{i}" if len(frames) > 1 else ""
                out = native_dir / f"{dataset_name}{suffix}.parquet"
                df.to_parquet(out, index=False)
            results.append({"dataset": dataset_name, "status": "promoted", "files": len(frames),
                           "total_rows": sum(len(f) for f in frames)})
        else:
            results.append({"dataset": dataset_name, "status": "no_data"})

    return results
