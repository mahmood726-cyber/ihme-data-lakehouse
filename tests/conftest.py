"""Shared pytest fixtures."""
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_data(tmp_path):
    """Create a temporary data directory mirroring the project layout."""
    for sub in ("raw", "bronze", "silver", "reference", "manifests"):
        (tmp_path / sub).mkdir()
    return tmp_path


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR
