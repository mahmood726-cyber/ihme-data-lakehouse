"""
Visit each IHME record page and extract file download links.
Writes results to registry/ghdx_files.json.
Resumable — skips already-scraped records.
"""
import requests
import json
import time
import sys
import io
import re
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urljoin

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "https://ghdx.healthdata.org"
CATALOG = Path(__file__).parent.parent / "registry" / "ghdx_catalog.json"
OUTPUT = Path(__file__).parent.parent / "registry" / "ghdx_files.json"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

# Load catalog
with open(CATALOG, encoding="utf-8") as f:
    catalog = json.load(f)

# Load existing progress
if OUTPUT.exists():
    with open(OUTPUT, encoding="utf-8") as f:
        results = json.load(f)
else:
    results = {}

scraped = set(results.keys())
datasets = catalog["datasets"]
total = len(datasets)
skipped = 0
errors = 0
new_files_found = 0

print(f"Total records: {total}, already scraped: {len(scraped)}")

for i, ds in enumerate(datasets):
    url = ds["record_url"]
    slug = url.split("/record/")[-1] if "/record/" in url else url

    if slug in scraped:
        skipped += 1
        continue

    print(f"[{i+1}/{total}] {ds['title'][:80]}...")

    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        files = []

        # Strategy 1: Look for direct file links (CSV, ZIP, XLSX, PDF, etc.)
        file_extensions = ('.csv', '.zip', '.xlsx', '.xls', '.pdf', '.dta',
                          '.parquet', '.gz', '.tar', '.7z', '.rar', '.txt')
        for a in soup.find_all("a", href=True):
            href = a["href"]
            href_lower = href.lower()
            # Match file extensions or cloud.ihme links or sites/default/files
            if (any(href_lower.endswith(ext) for ext in file_extensions) or
                "cloud.ihme" in href or
                "sites/default/files" in href or
                "dl.healthdata.org" in href or
                "/download" in href_lower):
                full_url = urljoin(BASE, href)
                fname = a.get_text(strip=True) or href.split("/")[-1]
                files.append({
                    "filename": fname[:200],
                    "url": full_url,
                    "type": "direct"
                })

        # Strategy 2: Look for "Files" tab content or fieldset
        files_section = soup.find("fieldset", class_="group-files")
        if files_section:
            for a in files_section.find_all("a", href=True):
                href = a["href"]
                full_url = urljoin(BASE, href)
                fname = a.get_text(strip=True) or href.split("/")[-1]
                if full_url not in [f["url"] for f in files]:
                    files.append({
                        "filename": fname[:200],
                        "url": full_url,
                        "type": "files_tab"
                    })

        # Strategy 3: Look for download buttons/links
        for a in soup.find_all("a", class_=re.compile(r"download|btn", re.I)):
            href = a.get("href", "")
            if href and href != "#":
                full_url = urljoin(BASE, href)
                fname = a.get_text(strip=True) or href.split("/")[-1]
                if full_url not in [f["url"] for f in files]:
                    files.append({
                        "filename": fname[:200],
                        "url": full_url,
                        "type": "download_btn"
                    })

        # Strategy 4: Check for GBD Results Tool references
        gbd_tool = bool(soup.find("a", href=re.compile(r"vizhub\.healthdata\.org/gbd-results")))

        # Deduplicate by URL
        seen_urls = set()
        unique_files = []
        for f in files:
            if f["url"] not in seen_urls:
                seen_urls.add(f["url"])
                unique_files.append(f)

        results[slug] = {
            "title": ds["title"],
            "record_url": url,
            "files": unique_files,
            "file_count": len(unique_files),
            "uses_gbd_results_tool": gbd_tool,
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        new_files_found += len(unique_files)
        if unique_files:
            print(f"  -> {len(unique_files)} files found")
        else:
            print(f"  -> No direct files (GBD Tool: {gbd_tool})")

    except Exception as e:
        errors += 1
        results[slug] = {
            "title": ds["title"],
            "record_url": url,
            "files": [],
            "file_count": 0,
            "error": str(e),
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        print(f"  -> ERROR: {e}")

    # Save every 10 records (resumable)
    if (i + 1) % 10 == 0:
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    time.sleep(0.5)  # polite 500ms delay

# Final save
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

# Summary
with_files = sum(1 for r in results.values() if r.get("file_count", 0) > 0)
gbd_tool_only = sum(1 for r in results.values()
                    if r.get("uses_gbd_results_tool") and r.get("file_count", 0) == 0)
total_files = sum(r.get("file_count", 0) for r in results.values())

print(f"\n{'='*60}")
print(f"SCRAPING COMPLETE")
print(f"  Records scraped: {len(results)}")
print(f"  Records with files: {with_files}")
print(f"  Records GBD Tool only: {gbd_tool_only}")
print(f"  Total file URLs found: {total_files}")
print(f"  Errors: {errors}")
print(f"  Output: {OUTPUT}")
