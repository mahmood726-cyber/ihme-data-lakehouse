"""Export silver parquets to clean, well-named CSV + Parquet in datasets/.

Creates user-friendly files with clear names and a data catalog.
"""
import io
import sys
from pathlib import Path

if "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data" / "silver"
OUT = ROOT / "datasets"
OUT.mkdir(exist_ok=True)


def clean_gbd_results(path: Path, name: str) -> pd.DataFrame:
    """Load a GBD results parquet and produce a clean, minimal DataFrame."""
    df = pd.read_parquet(path)
    # Keep only essential columns, rename for clarity
    cols = {
        "location_id": "location_id",
        "location_name": "location",
        "year": "year",
        "sex_name": "sex",
        "age_name": "age_group",
        "cause_name": "cause",
        "measure_name": "measure",
        "metric_name": "metric",
        "val": "value",
        "upper": "upper",
        "lower": "lower",
    }
    available = {k: v for k, v in cols.items() if k in df.columns}
    out = df[list(available.keys())].rename(columns=available)
    return out


def clean_population(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    cols = {
        "location_id": "location_id",
        "location_name": "location",
        "year": "year",
        "sex_name": "sex",
        "age_name": "age_group",
        "metric_name": "metric",
        "val": "value",
        "upper": "upper",
        "lower": "lower",
    }
    available = {k: v for k, v in cols.items() if k in df.columns}
    return df[list(available.keys())].rename(columns=available)


def clean_sdi(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    cols = {
        "location_id": "location_id",
        "location_name": "location",
        "year_id": "year",
        "sex": "sex",
        "age_group_name": "age_group",
        "mean_value": "sdi",
        "lower_value": "sdi_lower",
        "upper_value": "sdi_upper",
    }
    available = {k: v for k, v in cols.items() if k in df.columns}
    return df[list(available.keys())].rename(columns=available)


def export(df: pd.DataFrame, name: str) -> dict:
    """Export as both CSV and Parquet. Returns metadata."""
    csv_path = OUT / f"{name}.csv"
    pq_path = OUT / f"{name}.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(pq_path, index=False)
    return {
        "name": name,
        "rows": len(df),
        "columns": list(df.columns),
        "csv_size_kb": round(csv_path.stat().st_size / 1024, 1),
        "parquet_size_kb": round(pq_path.stat().st_size / 1024, 1),
    }


def main():
    catalog = []

    # GBD Results
    for measure in ["deaths", "dalys", "ylls", "ylds"]:
        path = SILVER / "gbd_results" / "native" / f"{measure}.parquet"
        if path.exists():
            df = clean_gbd_results(path, measure)
            info = export(df, f"gbd2023_{measure}_204countries_1990_2023")
            catalog.append(info)
            print(f"  {info['name']}: {info['rows']:,} rows, {info['csv_size_kb']}KB CSV")

    # Population
    pop_path = SILVER / "population" / "native" / "population.parquet"
    if pop_path.exists():
        df = clean_population(pop_path)
        info = export(df, "gbd2023_population_204countries_1990_2023")
        catalog.append(info)
        print(f"  {info['name']}: {info['rows']:,} rows, {info['csv_size_kb']}KB CSV")

    # SDI
    sdi_path = SILVER / "gbd_covariates" / "native" / "gbd_covariates.parquet"
    if sdi_path.exists():
        df = clean_sdi(sdi_path)
        info = export(df, "gbd2021_sdi_1950_2021")
        catalog.append(info)
        print(f"  {info['name']}: {info['rows']:,} rows, {info['csv_size_kb']}KB CSV")

    # Write catalog
    print(f"\n  Total: {len(catalog)} datasets exported to {OUT}/")

    # Also create a combined all-cause burden file for easy analysis
    frames = []
    for measure in ["deaths", "dalys", "ylls", "ylds"]:
        path = SILVER / "gbd_results" / "native" / f"{measure}.parquet"
        if path.exists():
            frames.append(clean_gbd_results(path, measure))
    if frames:
        combined = pd.concat(frames, ignore_index=True)
        info = export(combined, "gbd2023_all_burden_204countries_1990_2023")
        catalog.append(info)
        print(f"  {info['name']}: {info['rows']:,} rows, {info['csv_size_kb']}KB CSV (combined)")

    return catalog


if __name__ == "__main__":
    main()
