"""
IHME GHDx Bulk Downloader — Authenticated
==========================================
Phase 1: Re-scrape record pages with auth cookies to get real download URLs
Phase 2: Download all files, resumable, with progress tracking

Usage:
  1. Open Chrome → ghdx.healthdata.org (logged in)
  2. F12 → Network tab → reload page → click any request to ghdx.healthdata.org
  3. Copy the Cookie header value
  4. Run: python scripts/download_all_ghdx.py --cookie "paste_here"

  Or use --cookie-file to point to a text file containing the cookie string.
"""
import argparse
import json
import os
import re
import sys
import io
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "https://ghdx.healthdata.org"
PROJECT_ROOT = Path(__file__).parent.parent
CATALOG = PROJECT_ROOT / "registry" / "ghdx_catalog.json"
FILES_DB = PROJECT_ROOT / "registry" / "ghdx_files.json"
AUTH_FILES_DB = PROJECT_ROOT / "registry" / "ghdx_files_auth.json"
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "raw" / "ghdx_bulk"
PROGRESS_FILE = PROJECT_ROOT / "registry" / "download_progress.json"


def create_session(cookie_str):
    """Create requests session with auth cookies."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie_str.strip(),
    })
    return s


def verify_auth(session):
    """Check if the session is authenticated."""
    resp = session.get(f"{BASE}/user", allow_redirects=False, timeout=15)
    # If authenticated, /user shows profile (200). If not, redirects to login (302/303).
    if resp.status_code == 200 and "Log out" in resp.text:
        # Extract username
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.find("title")
        print(f"[OK] Authenticated as: {title.text if title else 'unknown'}")
        return True
    else:
        print(f"[FAIL] Not authenticated (status {resp.status_code})")
        print("  Make sure you copied the full Cookie header from Chrome DevTools")
        return False


def scrape_record_files_auth(session, record_url, title=""):
    """Scrape a single record page for file download links (authenticated)."""
    try:
        resp = session.get(record_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        files = []

        # Look for the Files fieldset/section
        # When authenticated, file links should have real URLs instead of /download-access/login

        # Strategy 1: Find file table rows
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                link = cells[0].find("a", href=True)
                if link:
                    href = link["href"]
                    fname = link.get_text(strip=True)
                    size_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    full_url = urljoin(BASE, href)

                    # Skip non-file links
                    if "help/downloading" in href:
                        continue

                    files.append({
                        "filename": fname,
                        "url": full_url,
                        "size": size_text,
                        "is_auth_url": "download-access/login" in href
                    })

        # Strategy 2: Direct file links (cloud.ihme, sites/default/files, etc.)
        seen_urls = {f["url"] for f in files}
        file_extensions = ('.csv', '.zip', '.xlsx', '.xls', '.pdf', '.dta',
                          '.parquet', '.gz', '.tar', '.7z')
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(BASE, href)
            if full_url in seen_urls:
                continue
            if ("cloud.ihme" in href or
                "sites/default/files" in href or
                "dl.healthdata.org" in href or
                any(href.lower().endswith(ext) for ext in file_extensions)):
                fname = a.get_text(strip=True) or href.split("/")[-1]
                files.append({
                    "filename": fname,
                    "url": full_url,
                    "size": "",
                    "is_auth_url": False
                })
                seen_urls.add(full_url)

        return files

    except Exception as e:
        print(f"  ERROR scraping {record_url}: {e}")
        return []


def phase1_scrape_auth(session, limit=None):
    """Re-scrape all record pages with authentication to get real download URLs."""
    with open(CATALOG, encoding="utf-8") as f:
        catalog = json.load(f)

    # Load existing auth results for resume
    if AUTH_FILES_DB.exists():
        with open(AUTH_FILES_DB, encoding="utf-8") as f:
            auth_results = json.load(f)
    else:
        auth_results = {}

    datasets = catalog["datasets"]
    if limit:
        datasets = datasets[:limit]

    total = len(datasets)
    scraped_count = 0
    new_files = 0

    for i, ds in enumerate(datasets):
        url = ds["record_url"]
        slug = url.split("/record/")[-1] if "/record/" in url else url

        if slug in auth_results and not auth_results[slug].get("is_auth_url_only"):
            continue  # Already scraped with good URLs

        print(f"[{i+1}/{total}] {ds['title'][:75]}...")
        files = scrape_record_files_auth(session, url, ds["title"])

        auth_results[slug] = {
            "title": ds["title"],
            "record_url": url,
            "files": files,
            "file_count": len(files),
            "is_auth_url_only": all(f.get("is_auth_url") for f in files) if files else True,
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        real_files = [f for f in files if not f.get("is_auth_url")]
        if real_files:
            new_files += len(real_files)
            print(f"  -> {len(real_files)} downloadable files")
        elif files:
            print(f"  -> {len(files)} files (still auth-gated)")
        else:
            print(f"  -> No files found")

        scraped_count += 1

        # Save every 10
        if (i + 1) % 10 == 0:
            with open(AUTH_FILES_DB, "w", encoding="utf-8") as f:
                json.dump(auth_results, f, indent=2, ensure_ascii=False)

        time.sleep(0.3)

    # Final save
    with open(AUTH_FILES_DB, "w", encoding="utf-8") as f:
        json.dump(auth_results, f, indent=2, ensure_ascii=False)

    total_downloadable = sum(
        len([f for f in r.get("files", []) if not f.get("is_auth_url")])
        for r in auth_results.values()
    )
    print(f"\nPhase 1 complete: {scraped_count} records scraped, {total_downloadable} downloadable URLs found")
    return auth_results


def sanitize_filename(name, max_len=200):
    """Make a filename safe for Windows."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name[:max_len] if name else 'unnamed'


def download_file(session, url, dest_path, chunk_size=8192):
    """Download a single file with resume support."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support
    existing_size = dest_path.stat().st_size if dest_path.exists() else 0
    headers = {}
    if existing_size > 0:
        headers["Range"] = f"bytes={existing_size}-"

    resp = session.get(url, stream=True, timeout=60, headers=headers, allow_redirects=True)

    # If server doesn't support range, start over
    if resp.status_code == 200 and existing_size > 0:
        existing_size = 0
    elif resp.status_code == 416:  # Range not satisfiable — file already complete
        return dest_path, existing_size

    resp.raise_for_status()

    total = resp.headers.get("Content-Length")
    total = int(total) + existing_size if total else None

    mode = "ab" if resp.status_code == 206 else "wb"
    downloaded = existing_size

    with open(dest_path, mode) as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            downloaded += len(chunk)

    return dest_path, downloaded


def phase2_download(session, auth_results=None, filter_pattern=None, dry_run=False):
    """Download all files from authenticated scrape results."""
    if auth_results is None:
        with open(AUTH_FILES_DB, encoding="utf-8") as f:
            auth_results = json.load(f)

    # Load progress
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            progress = json.load(f)
    else:
        progress = {"completed": {}, "failed": {}, "skipped": {}}

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Build download queue
    queue = []
    for slug, record in auth_results.items():
        files = record.get("files", [])
        for fi in files:
            url = fi["url"]
            if fi.get("is_auth_url") or "help/downloading" in url:
                continue

            # Apply filter
            if filter_pattern and filter_pattern.lower() not in record["title"].lower():
                continue

            # Create folder per dataset
            folder_name = sanitize_filename(slug)
            filename = sanitize_filename(fi["filename"])
            if not filename or filename == "unnamed":
                filename = url.split("/")[-1].split("?")[0]
                filename = sanitize_filename(filename)

            dest = DOWNLOAD_DIR / folder_name / filename
            file_key = f"{slug}/{filename}"

            if file_key in progress["completed"]:
                continue  # Already downloaded

            queue.append({
                "url": url,
                "dest": str(dest),
                "key": file_key,
                "title": record["title"],
                "filename": filename,
                "size": fi.get("size", "")
            })

    print(f"\nDownload queue: {len(queue)} files")
    if dry_run:
        for item in queue[:50]:
            print(f"  [{item['size']:>10}] {item['title'][:60]} / {item['filename']}")
        if len(queue) > 50:
            print(f"  ... and {len(queue) - 50} more")
        return

    # Download
    success = 0
    failed = 0
    for i, item in enumerate(queue):
        print(f"[{i+1}/{len(queue)}] {item['filename'][:60]} ({item['size']})...")
        try:
            path, size = download_file(session, item["url"], item["dest"])
            progress["completed"][item["key"]] = {
                "path": str(path),
                "size": size,
                "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            success += 1
            print(f"  -> OK ({size:,} bytes)")
        except Exception as e:
            progress["failed"][item["key"]] = {
                "url": item["url"],
                "error": str(e),
                "attempted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            failed += 1
            print(f"  -> FAILED: {e}")

        # Save progress every 5 files
        if (i + 1) % 5 == 0:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2)

    # Final save
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)

    print(f"\nDownload complete: {success} succeeded, {failed} failed")
    print(f"Files saved to: {DOWNLOAD_DIR}")


def main():
    parser = argparse.ArgumentParser(description="IHME GHDx Bulk Downloader")
    parser.add_argument("--cookie", help="Cookie header string from Chrome DevTools")
    parser.add_argument("--cookie-file", help="Path to file containing cookie string")
    parser.add_argument("--phase", choices=["1", "2", "both"], default="both",
                       help="Phase 1=scrape auth URLs, 2=download, both=full pipeline")
    parser.add_argument("--limit", type=int, help="Limit records to scrape (for testing)")
    parser.add_argument("--filter", help="Filter datasets by title substring")
    parser.add_argument("--dry-run", action="store_true", help="Show what would download")
    args = parser.parse_args()

    # Get cookie
    cookie_str = args.cookie
    if args.cookie_file:
        cookie_str = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    if not cookie_str:
        print("ERROR: Provide --cookie or --cookie-file")
        print("\nHow to get your cookie:")
        print("  1. Open Chrome -> ghdx.healthdata.org (logged in)")
        print("  2. F12 -> Network tab -> reload page")
        print("  3. Click any request to ghdx.healthdata.org")
        print("  4. Find 'Cookie:' in Request Headers")
        print("  5. Copy the entire value")
        sys.exit(1)

    session = create_session(cookie_str)

    # Verify authentication
    if not verify_auth(session):
        sys.exit(1)

    if args.phase in ("1", "both"):
        auth_results = phase1_scrape_auth(session, limit=args.limit)
    else:
        auth_results = None

    if args.phase in ("2", "both"):
        phase2_download(session, auth_results, filter_pattern=args.filter, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
