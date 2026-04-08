"""IHME population & fertility fetcher."""
from __future__ import annotations

from pathlib import Path

from ihme_data_lakehouse.sources import fetch_domain


def fetch_population(
    raw_dir: Path | None = None, skip_existing: bool = False, check_only: bool = False
) -> dict:
    return fetch_domain("population", raw_dir=raw_dir, skip_existing=skip_existing, check_only=check_only)
