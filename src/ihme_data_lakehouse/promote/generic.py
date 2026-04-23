"""Generic promote module for any domain with CSV/XLSX files.

Works for: health_financing, vaccination, us_subnational, reference,
surveys, geospatial, gbd_legacy, specialty (expanded), unclassified.

Each dataset folder under raw/{domain}/ becomes one or more Parquet files
under silver/{domain}/native/.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from ihme_data_lakehouse.normalize import add_provenance, coerce_types


def promote_domain(domain: str, raw_dir: Path, bronze_dir: Path, silver_dir: Path,
                   reference_dir: Path, skip_existing: bool = False) -> list[dict]:
    """Promote all datasets in a domain from raw → bronze → silver/native."""
    domain_raw = raw_dir / domain
    native_dir = silver_dir / domain / "native"
    harmonized_dir = silver_dir / domain / "harmonized"
    bronze_out = bronze_dir / domain
    native_dir.mkdir(parents=True, exist_ok=True)
    harmonized_dir.mkdir(parents=True, exist_ok=True)
    bronze_out.mkdir(parents=True, exist_ok=True)

    if not domain_raw.exists():
        return [{"domain": domain, "status": "no_raw_dir"}]

    results: list[dict] = []

    for dataset_dir in sorted(domain_raw.iterdir()):
        if not dataset_dir.is_dir():
            continue

        dataset_name = dataset_dir.name
        parquet_path = native_dir / f"{dataset_name}.parquet"

        if skip_existing and parquet_path.exists():
            results.append({"dataset": dataset_name, "status": "skipped"})
            continue

        frames = []
        file_count = 0

        # Read all CSVs
        for csv_path in sorted(dataset_dir.rglob("*.csv")) + sorted(dataset_dir.rglob("*.CSV")):
            try:
                df = pd.read_csv(csv_path, low_memory=False, encoding="utf-8", on_bad_lines="skip")
                if len(df) < 2:
                    continue

                # Skip codebook/metadata files
                first_vals = df.iloc[0].astype(str).str.lower()  # sentinel:skip-line P1-empty-dataframe-access  (guarded by len(df) < 2 above)
                if any(v in ("label:", "value coding:", "description:") for v in first_vals):
                    continue

                df = coerce_types(df)
                bronze_df = add_provenance(df, csv_path.name)

                # Save bronze
                safe_name = csv_path.stem[:100].replace(" ", "_")
                bronze_df.to_csv(bronze_out / f"{dataset_name}_{safe_name}.csv", index=False)

                frames.append(df)
                file_count += 1
            except Exception as e:
                results.append({"file": str(csv_path.name)[:60], "status": "error", "error": str(e)[:80]})

        # Read extensionless files (IHME downloads often lack extensions)
        for fpath in sorted(dataset_dir.iterdir()):
            if fpath.is_file() and fpath.suffix == "":
                try:
                    # Try CSV first
                    df = pd.read_csv(fpath, low_memory=False, encoding="utf-8", on_bad_lines="skip")
                    if len(df) >= 2:
                        df = coerce_types(df)
                        bronze_df = add_provenance(df, fpath.name)
                        safe_name = fpath.name[:100].replace(" ", "_")
                        bronze_df.to_csv(bronze_out / f"{dataset_name}_{safe_name}.csv", index=False)
                        frames.append(df)
                        file_count += 1
                        continue
                except Exception:
                    pass
                try:
                    # Try XLSX
                    xls = pd.ExcelFile(fpath)
                    for sheet in xls.sheet_names:
                        df = pd.read_excel(fpath, sheet_name=sheet)
                        if len(df) >= 2:
                            df = coerce_types(df)
                            frames.append(df)
                            file_count += 1
                except Exception:
                    pass

        # Read all XLSX
        for xlsx_path in sorted(dataset_dir.rglob("*.xlsx")) + sorted(dataset_dir.rglob("*.XLSX")):
            try:
                xls = pd.ExcelFile(xlsx_path)
                for sheet in xls.sheet_names:
                    df = pd.read_excel(xlsx_path, sheet_name=sheet)
                    if len(df) < 2:
                        continue
                    df = coerce_types(df)
                    frames.append(df)
                    file_count += 1
            except Exception as e:
                results.append({"file": str(xlsx_path.name)[:60], "status": "error", "error": str(e)[:80]})

        if not frames:
            results.append({"dataset": dataset_name, "status": "no_data"})
            continue

        # Save to silver/native as Parquet
        def safe_to_parquet(df, path):
            """Write Parquet, converting mixed-type columns to string if needed."""
            try:
                df.to_parquet(path, index=False)
            except Exception:
                # Stringify object columns that have mixed types
                out = df.copy()
                for col in out.select_dtypes(include=["object"]).columns:
                    out[col] = out[col].astype(str)
                out.to_parquet(path, index=False)

        if len(frames) == 1:
            safe_to_parquet(frames[0], parquet_path)
        else:
            schemas = [tuple(sorted(f.columns)) for f in frames]
            if len(set(schemas)) == 1:
                combined = pd.concat(frames, ignore_index=True)
                safe_to_parquet(combined, parquet_path)
            else:
                for i, df in enumerate(frames):
                    out = native_dir / f"{dataset_name}_{i}.parquet"
                    safe_to_parquet(df, out)

        total_rows = sum(len(f) for f in frames)
        results.append({
            "dataset": dataset_name,
            "status": "promoted",
            "files": file_count,
            "total_rows": total_rows,
        })

    # Harmonized layer — attempt if crosswalk exists
    crosswalk_path = reference_dir / "location_to_iso3.parquet"
    if crosswalk_path.exists():
        _try_harmonize(native_dir, harmonized_dir, crosswalk_path, results)

    return results


def _try_harmonize(native_dir: Path, harmonized_dir: Path, crosswalk_path: Path,
                   results: list[dict]) -> None:
    """Best-effort harmonization: map location_id → iso3c if the column exists."""
    crosswalk = pd.read_parquet(crosswalk_path)

    for pq_path in sorted(native_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(pq_path)
            if "location_id" not in df.columns:
                continue

            merged = df.merge(crosswalk[["location_id", "iso3c"]], on="location_id", how="left")

            # Find year column
            year_col = None
            for candidate in ("year_id", "year", "Year"):
                if candidate in merged.columns:
                    year_col = candidate
                    break

            if year_col is None:
                continue

            # Find value column
            val_col = None
            for candidate in ("val", "mean", "mean_value", "value", "rate"):
                if candidate in merged.columns:
                    val_col = candidate
                    break

            if val_col is None:
                continue

            harmonized = pd.DataFrame({
                "iso3c": merged["iso3c"],
                "year": merged[year_col],
                "value": merged[val_col],
                "lower": merged.get("lower", merged.get("lower_value")),
                "upper": merged.get("upper", merged.get("upper_value")),
            })

            out = harmonized_dir / pq_path.name
            harmonized.to_parquet(out, index=False)
            results.append({"harmonized": pq_path.name, "rows": len(harmonized)})

        except Exception:
            pass  # skip files that can't be harmonized
