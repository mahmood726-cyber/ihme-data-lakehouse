"""
Full pipeline: Login via Selenium -> Scrape all records -> Download files
Keeps Selenium session alive throughout to avoid cookie expiry.
"""
import sys
import io
import time
import json
import re
import os
from pathlib import Path
from urllib.parse import urljoin

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.common.by import By
import requests
from bs4 import BeautifulSoup

BASE = "https://ghdx.healthdata.org"
ROOT = Path(__file__).parent.parent
CATALOG = ROOT / "registry" / "ghdx_catalog.json"
AUTH_DB = ROOT / "registry" / "ghdx_files_auth.json"
DOWNLOAD_DIR = ROOT / "data" / "raw" / "ghdx_bulk"
PROGRESS = ROOT / "registry" / "download_progress.json"

# ── Phase 0: Login ──────────────────────────────────────────
print("=" * 60)
print("Phase 0: Logging in via Selenium")
print("=" * 60)

options = webdriver.ChromeOptions()
options.add_argument("--user-data-dir=" + str(ROOT / ".selenium_pipeline"))
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1280,1024")
options.add_argument("--no-first-run")

driver = webdriver.Chrome(options=options)
driver.set_page_load_timeout(60)

driver.get(f"{BASE}/download-access/login")
time.sleep(5)

if "b2clogin" in driver.current_url:
    email = driver.find_element(By.ID, "signInName")
    email.clear()
    email.send_keys(sys.argv[1])
    pw = driver.find_element(By.ID, "password")
    pw.clear()
    pw.send_keys(sys.argv[2])
    driver.execute_script('document.getElementById("next").click()')
    print("Login submitted, waiting for redirect...")

    for i in range(30):
        time.sleep(2)
        if "ghdx.healthdata.org" in driver.current_url and "b2clogin" not in driver.current_url:
            print(f"Logged in! ({driver.current_url[:60]})")
            break
    else:
        print("Login timeout.")
        driver.quit()
        sys.exit(1)
elif "ghdx.healthdata.org" in driver.current_url:
    print("Already authenticated (cached session).")
else:
    print(f"Unexpected URL: {driver.current_url}")
    driver.quit()
    sys.exit(1)

# Transfer cookies to requests session
cookies = driver.get_cookies()
cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

# Also visit the download-access page to get any additional cookies
driver.get(f"{BASE}/user")
time.sleep(2)
cookies = driver.get_cookies()
cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# Set cookies properly
for c in cookies:
    session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

# Verify
r = session.get(f"{BASE}/user", timeout=15)
if "Log out" in r.text:
    print(f"Requests session verified! ({len(cookies)} cookies)")
else:
    print("Requests auth failed. Using Selenium for scraping instead...")
    # Fall through - we'll use Selenium for scraping

# ── Phase 1: Scrape ────────────────────────────────────────
print()
print("=" * 60)
print("Phase 1: Scraping all 482 records for file URLs")
print("=" * 60)

with open(CATALOG, encoding="utf-8") as f:
    catalog = json.load(f)

# Resume support
if AUTH_DB.exists():
    with open(AUTH_DB, encoding="utf-8") as f:
        results = json.load(f)
else:
    results = {}

datasets = catalog["datasets"]
total = len(datasets)
total_files = 0
use_selenium = "Log out" not in r.text  # fallback to Selenium if requests auth failed

for i, ds in enumerate(datasets):
    url = ds["record_url"]
    slug = url.split("/record/")[-1] if "/record/" in url else url

    # Skip already scraped with real files
    existing = results.get(slug, {})
    if existing.get("file_count", 0) > 0:
        total_files += existing["file_count"]
        continue

    try:
        if use_selenium:
            driver.get(url)
            time.sleep(2)
            html = driver.page_source
        else:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        files = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(BASE, href)
            if full in seen:
                continue
            if ("sites/default/files" in href or "cloud.ihme" in href or
                "dl.healthdata.org" in href):
                fname = a.get_text(strip=True) or href.split("/")[-1]
                size = ""
                row = a.find_parent("tr")
                if row:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        size = cells[-1].get_text(strip=True)
                files.append({"filename": fname, "url": full, "size": size})
                seen.add(full)

        results[slug] = {
            "title": ds["title"],
            "record_url": url,
            "files": files,
            "file_count": len(files),
            "is_auth_only": False
        }
        total_files += len(files)

    except Exception as e:
        results[slug] = {"title": ds["title"], "record_url": url,
                        "files": [], "file_count": 0, "error": str(e)}

    if (i + 1) % 25 == 0:
        with_f = sum(1 for r in results.values() if r.get("file_count", 0) > 0)
        print(f"  [{i+1}/{total}] {with_f} records with files, {total_files} total URLs")
        with open(AUTH_DB, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    time.sleep(0.3)

# Final save
with open(AUTH_DB, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

with_files = sum(1 for r in results.values() if r.get("file_count", 0) > 0)
errors = sum(1 for r in results.values() if r.get("error"))
print(f"\nScrape complete: {with_files} records with files, {total_files} URLs, {errors} errors")

# ── Phase 2: Download ──────────────────────────────────────
print()
print("=" * 60)
print("Phase 2: Downloading files")
print("=" * 60)

if PROGRESS.exists():
    with open(PROGRESS, encoding="utf-8") as f:
        progress = json.load(f)
else:
    progress = {"completed": {}, "failed": {}}

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

def sanitize(name, max_len=180):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')[:max_len] or 'unnamed'

queue = []
for slug, rec in results.items():
    for fi in rec.get("files", []):
        url = fi["url"]
        folder = sanitize(slug)
        fname = sanitize(fi.get("filename", "") or url.split("/")[-1].split("?")[0])
        key = f"{slug}/{fname}"
        if key in progress["completed"]:
            continue
        queue.append({"url": url, "dest": str(DOWNLOAD_DIR / folder / fname),
                     "key": key, "title": rec.get("title", ""), "size": fi.get("size", "")})

print(f"Download queue: {len(queue)} files (skipping {len(progress['completed'])} already done)")

ok = fail = 0
consecutive_fails = 0
for i, item in enumerate(queue):
    if (i + 1) % 10 == 0 or i == 0:
        print(f"[{i+1}/{len(queue)}] {item['title'][:50]} ({item['size']})")

    # Retry logic: up to 3 attempts with exponential backoff
    success = False
    for attempt in range(3):
        try:
            dest = Path(item["dest"])
            dest.parent.mkdir(parents=True, exist_ok=True)

            resp = session.get(item["url"], stream=True, timeout=300, allow_redirects=True)
            resp.raise_for_status()

            total_size = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
                    total_size += len(chunk)

            progress["completed"][item["key"]] = {
                "path": str(dest), "size": total_size,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            ok += 1
            success = True
            consecutive_fails = 0
            break
        except Exception as e:
            if attempt < 2:
                wait = (attempt + 1) * 15  # 15s, 30s
                time.sleep(wait)
            else:
                progress["failed"][item["key"]] = {
                    "url": item["url"], "error": str(e),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                }
                fail += 1
                consecutive_fails += 1

    # Throttle: 2s between downloads, longer pause after failures
    if consecutive_fails >= 10:
        print(f"  10 consecutive failures — backing off 60s...")
        time.sleep(60)
        consecutive_fails = 0
    elif not success:
        time.sleep(5)
    else:
        time.sleep(2)  # polite delay between downloads

    if (i + 1) % 10 == 0:
        with open(PROGRESS, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2)

with open(PROGRESS, "w", encoding="utf-8") as f:
    json.dump(progress, f, indent=2)

driver.quit()

print(f"\n{'=' * 60}")
print(f"PIPELINE COMPLETE")
print(f"  Records scraped: {len(results)}")
print(f"  Records with files: {with_files}")
print(f"  Downloaded: {ok}")
print(f"  Failed: {fail}")
print(f"  Files in: {DOWNLOAD_DIR}")
print(f"{'=' * 60}")
