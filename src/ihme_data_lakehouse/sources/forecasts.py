"""GBD Foresight / Lancet 2024 projections fetcher."""
from __future__ import annotations

from pathlib import Path

from ihme_data_lakehouse.sources import fetch_domain


def fetch_forecasts(
    raw_dir: Path | None = None, skip_existing: bool = False, check_only: bool = False
) -> dict:
    return fetch_domain("forecasts", raw_dir=raw_dir, skip_existing=skip_existing, check_only=check_only)
