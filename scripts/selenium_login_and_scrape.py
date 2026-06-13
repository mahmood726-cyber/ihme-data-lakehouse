"""
Selenium-based GHDx Login + Scrape + Download
==============================================
Opens a Chrome window -> navigates to GHDx login -> waits for you to log in
-> scrapes all 482 record pages for real file URLs -> downloads everything.

Usage:
  python scripts/selenium_login_and_scrape.py [--scrape-only] [--download-only] [--filter GBD]
"""
import argparse
import json
import os
import re
import sys
import io
import time
from pathlib import Path
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "https://ghdx.healthdata.org"
PROJECT_ROOT = Path(__file__).parent.parent
CATALOG = PROJECT_ROOT / "registry" / "ghdx_catalog.json"
AUTH_FILES_DB = PROJECT_ROOT / "registry" / "ghdx_files_auth.json"
COOKIE_CACHE = PROJECT_ROOT / "registry" / ".cookies.json"
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "raw" / "ghdx_bulk"
PROGRESS_FILE = PROJECT_ROOT / "registry" / "download_progress.json"


def launch_browser_and_login():
    """Open Chrome, navigate to GHDx login, wait for user to authenticate."""
    print("Launching Chrome browser...")
    options = webdriver.ChromeOptions()
    # Use a persistent temp profile so login persists across runs
    profile_dir = str(PROJECT_ROOT / ".selenium_profile")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    # Set download directory
    dl_dir = str(DOWNLOAD_DIR.resolve())
    prefs = {"download.default_directory": dl_dir}
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)

    # Navigate to a page that triggers the download-access login
    print("Navigating to GHDx download login...")
    driver.get(f"{BASE}/download-access/login")

    # Check if already authenticated (redirected back to GHDx)
    time.sleep(3)
    if "ghdx.healthdata.org" in driver.current_url and "b2clogin" not in driver.current_url:
        print("[OK] Already authenticated!")
    else:
        print("\n" + "=" * 60)
        print("  PLEASE LOG IN in the Chrome window that just opened.")
        print("  Use your IHME/GHDx account credentials.")
        print("  The script will continue automatically after login.")
        print("=" * 60 + "\n")

        # Wait up to 5 minutes for the user to complete login
        for i in range(300):
            time.sleep(1)
            try:
                current = driver.current_url
                # After successful Azure B2C login, user is redirected back to GHDx
                if ("ghdx.healthdata.org" in current and
                    "b2clogin" not in current and
                    "login" not in current):
                    print("[OK] Login detected! Proceeding...")
                    break
            except Exception:
                pass
        else:
            print("[TIMEOUT] Login not detected after 5 minutes.")
            driver.quit()
            return None, None

    # Extract cookies from the Selenium session
    selenium_cookies = driver.get_cookies()
    print(f"  Captured {len(selenium_cookies)} cookies")

    # Build cookie string for requests
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in selenium_cookies)

    # Save cookies for reuse
    with open(COOKIE_CACHE, "w") as f:
        json.dump(selenium_cookies, f, indent=2)
    print(f"  Cookies cached to {COOKIE_CACHE}")

    return driver, cookie_str


def create_requests_session(cookie_str):
    """Create a requests session with the Selenium cookies."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie_str,
    })
    return s


def verify_auth(session):
    """Verify the requests session is authenticated."""
    resp = session.get(f"{BASE}/user", timeout=15)
    if "Log out" in resp.text:
        print("[OK] Requests session authenticated")
        return True
    print("[WARN] Requests session may not be authenticated")
    return False


def scrape_record_auth(session, record_url):
    """Scrape a single record page for file download links (authenticated)."""
    try:
        resp = session.get(record_url, timeout=30)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        files = []
        seen_urls = set()

        # Find all file links in the record page
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = urljoin(BASE, href)
            fname = a.get_text(strip=True)

            # Skip navigation/help links
            if any(skip in href for skip in [
                "help/downloading", "/keyword/", "/series/", "/data-type/",
                "/geography/", "/countries", "/organizations", "/about",
                "/user", "#", "javascript:", "mailto:", "/printmail/",
                "/print/", "/ihme_data", "/gbd-2023", "/gbd-2021"
            ]):
                continue

            # Keep file-like links
            is_file = (
                "sites/default/files" in href or
                "cloud.ihme" in href or
                "dl.healthdata.org" in href or
                "download-access" in href or
                any(href.lower().endswith(ext) for ext in
                    ('.csv', '.zip', '.xlsx', '.xls', '.pdf', '.dta', '.gz', '.parquet'))
            )

            if is_file and full_url not in seen_urls:
                # Get size from parent table row if available
                size = ""
                parent_row = a.find_parent("tr")
                if parent_row:
                    cells = parent_row.find_all("td")
                    if len(cells) >= 2:
                        size = cells[-1].get_text(strip=True)

                files.append({
                    "filename": fname or href.split("/")[-1],
                    "url": full_url,
                    "size": size,
                    "is_auth_url": "download-access/login" in href
                })
                seen_urls.add(full_url)

        return files
    except Exception as e:
        return [{"error": str(e)}]


def phase1_scrape(session, limit=None):
    """Scrape all record pages with authentication."""
    with open(CATALOG, encoding="utf-8") as f:
        catalog = json.load(f)

    if AUTH_FILES_DB.exists():
        with open(AUTH_FILES_DB, encoding="utf-8") as f:
            auth_results = json.load(f)
    else:
        auth_results = {}

    datasets = catalog["datasets"]
    if limit:
        datasets = datasets[:limit]

    total = len(datasets)
    new_real = 0

    for i, ds in enumerate(datasets):
        url = ds["record_url"]
        slug = url.split("/record/")[-1] if "/record/" in url else url

        # Skip if already has real (non-auth) URLs
        existing = auth_results.get(slug, {})
        if existing.get("files") and not existing.get("is_auth_url_only"):
            continue

        print(f"[{i+1}/{total}] {ds['title'][:70]}...")
        files = scrape_record_auth(session, url)

        real_files = [f for f in files if not f.get("is_auth_url") and not f.get("error")]
        auth_files = [f for f in files if f.get("is_auth_url")]

        auth_results[slug] = {
            "title": ds["title"],
            "record_url": url,
            "files": files,
            "file_count": len(files),
            "real_file_count": len(real_files),
            "is_auth_url_only": len(real_files) == 0 and len(auth_files) > 0,
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        if real_files:
            new_real += len(real_files)
            print(f"  -> {len(real_files)} real download URLs!")
        elif auth_files:
            print(f"  -> {len(auth_files)} still auth-gated")
        else:
            print(f"  -> no files")

        if (i + 1) % 10 == 0:
            with open(AUTH_FILES_DB, "w", encoding="utf-8") as f:
                json.dump(auth_results, f, indent=2, ensure_ascii=False)

        time.sleep(0.3)

    with open(AUTH_FILES_DB, "w", encoding="utf-8") as f:
        json.dump(auth_results, f, indent=2, ensure_ascii=False)

    total_real = sum(r.get("real_file_count", 0) for r in auth_results.values())
    total_auth = sum(1 for r in auth_results.values() if r.get("is_auth_url_only"))
    print(f"\nScrape complete: {total_real} real URLs, {total_auth} still auth-gated")
    return auth_results


def sanitize_filename(name, max_len=180):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip('. ')[:max_len] or 'unnamed'


def phase2_download(session, auth_results=None, filter_pattern=None, dry_run=False):
    """Download all files with real URLs."""
    if auth_results is None:
        with open(AUTH_FILES_DB, encoding="utf-8") as f:
            auth_results = json.load(f)

    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            progress = json.load(f)
    else:
        progress = {"completed": {}, "failed": {}}

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    queue = []
    for slug, record in auth_results.items():
        if filter_pattern and filter_pattern.lower() not in record.get("title", "").lower():
            continue
        for fi in record.get("files", []):
            url = fi.get("url", "")
            if fi.get("is_auth_url") or fi.get("error") or "help/downloading" in url:
                continue

            folder = sanitize_filename(slug)
            fname = sanitize_filename(fi.get("filename", "") or url.split("/")[-1])
            dest = DOWNLOAD_DIR / folder / fname
            key = f"{slug}/{fname}"

            if key in progress["completed"]:
                continue

            queue.append({"url": url, "dest": str(dest), "key": key,
                         "title": record.get("title", ""), "filename": fname,
                         "size": fi.get("size", "")})

    print(f"\nDownload queue: {len(queue)} files")

    if dry_run:
        for item in queue[:60]:
            print(f"  [{item['size']:>10}] {item['title'][:55]} / {item['filename']}")
        if len(queue) > 60:
            print(f"  ... and {len(queue) - 60} more")
        return

    ok = fail = 0
    for i, item in enumerate(queue):
        print(f"[{i+1}/{len(queue)}] {item['filename'][:55]} ({item['size']})...")
        try:
            dest = Path(item["dest"])
            dest.parent.mkdir(parents=True, exist_ok=True)

            resp = session.get(item["url"], stream=True, timeout=120, allow_redirects=True)
            resp.raise_for_status()

            total_size = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
                    total_size += len(chunk)

            progress["completed"][item["key"]] = {
                "path": str(dest), "size": total_size,
                "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            ok += 1
            print(f"  -> OK ({total_size:,} bytes)")
        except Exception as e:
            progress["failed"][item["key"]] = {
                "url": item["url"], "error": str(e),
                "attempted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            fail += 1
            print(f"  -> FAILED: {e}")

        if (i + 1) % 5 == 0:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2)

    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)

    print(f"\nDone: {ok} downloaded, {fail} failed")
    print(f"Files in: {DOWNLOAD_DIR}")


def main():
    parser = argparse.ArgumentParser(description="GHDx Selenium Login + Bulk Download")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape, don't download")
    parser.add_argument("--download-only", action="store_true", help="Skip scrape, use cached auth URLs")
    parser.add_argument("--filter", help="Filter datasets by title substring (e.g. 'GBD 2023')")
    parser.add_argument("--limit", type=int, help="Limit records to scrape (testing)")
    parser.add_argument("--dry-run", action="store_true", help="Show download queue without downloading")
    args = parser.parse_args()

    # Step 1: Get authenticated session
    driver = None
    if not args.download_only:
        driver, cookie_str = launch_browser_and_login()
        if not cookie_str:
            print("Login failed. Exiting.")
            return

        session = create_requests_session(cookie_str)
        if not verify_auth(session):
            print("Auth verification failed. Cookies may not have transferred correctly.")
            # Try using Selenium cookies directly
            print("Will proceed anyway and see what happens...")
    else:
        # Load cached cookies
        if COOKIE_CACHE.exists():
            with open(COOKIE_CACHE) as f:
                cached = json.load(f)
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cached)
            session = create_requests_session(cookie_str)
        else:
            print("No cached cookies found. Run without --download-only first.")
            return

    # Step 2: Scrape with auth
    if not args.download_only:
        print("\n--- Phase 1: Scraping record pages with authentication ---")
        auth_results = phase1_scrape(session, limit=args.limit)
    else:
        auth_results = None

    # Step 3: Download
    if not args.scrape_only:
        print("\n--- Phase 2: Downloading files ---")
        phase2_download(session, auth_results, filter_pattern=args.filter, dry_run=args.dry_run)

    if driver:
        input("\nPress Enter to close the browser (or Ctrl+C to keep it open)...")
        driver.quit()


if __name__ == "__main__":
    main()
