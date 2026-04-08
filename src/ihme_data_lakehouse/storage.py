"""I/O utilities: JSON, CSV, Parquet, manifest writing."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(payload: object, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_dataframe(frame: pd.DataFrame, destination: Path, index: bool = False) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix == ".parquet":
        frame.to_parquet(destination, index=index)
    elif destination.suffix == ".csv":
        frame.to_csv(destination, index=index)
    else:
        raise ValueError(f"Unsupported format: {destination.suffix}")
    return destination


def write_manifest(prefix: str, summary: dict, manifest_dir: Path) -> dict:
    stamp = utc_stamp()
    path = manifest_dir / f"{prefix}_{stamp}.json"
    write_json(summary, path)
    summary["manifest_path"] = str(path)
    return summary
