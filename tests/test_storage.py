"""Tests for storage utilities."""
import json
from pathlib import Path

import pandas as pd

from ihme_data_lakehouse.storage import (
    read_json,
    utc_stamp,
    write_dataframe,
    write_json,
    write_manifest,
)


def test_utc_stamp_format():
    stamp = utc_stamp()
    assert len(stamp) == 16
    assert stamp.endswith("Z")
    assert stamp[8] == "T"


def test_write_and_read_json(tmp_path):
    payload = {"source": "gbd_results", "count": 42}
    path = tmp_path / "test.json"
    write_json(payload, path)
    loaded = read_json(path)
    assert loaded == payload


def test_write_dataframe_parquet(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    path = tmp_path / "test.parquet"
    write_dataframe(df, path)
    loaded = pd.read_parquet(path)
    assert len(loaded) == 2
    assert list(loaded.columns) == ["a", "b"]


def test_write_manifest(tmp_path):
    summary = {"source": "gbd_results", "files_fetched": 3}
    result = write_manifest("fetch_gbd_results", summary, tmp_path)
    assert "manifest_path" in result
    on_disk = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert on_disk["source"] == "gbd_results"
