"""HTTP session with retry logic for large file downloads."""
from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ihme_data_lakehouse.config import DEFAULT_TIMEOUT_SECONDS, USER_AGENT


def build_session(user_agent: str = USER_AGENT) -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update(
        {"Accept": "*/*", "User-Agent": user_agent}
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def check_url_reachable(session: requests.Session, url: str) -> tuple[bool, int]:
    """HEAD request to check if URL is reachable. Returns (ok, status_code)."""
    try:
        resp = session.head(url, timeout=30, allow_redirects=True)
        return resp.status_code < 400, resp.status_code
    except requests.RequestException:
        return False, 0


def download_to_path(
    session: requests.Session,
    url: str,
    destination: Path,
) -> Path:
    """Stream-download a file to destination. Handles large files."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        resp.raise_for_status()
        with open(destination, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                fh.write(chunk)
    return destination


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
