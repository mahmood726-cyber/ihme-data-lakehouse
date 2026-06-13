"""
Scrape all IHME Data pages from GHDx to build a complete catalog manifest.
Public pages — no auth needed.
"""
import requests
import json
import time
import sys
import io
from bs4 import BeautifulSoup
from pathlib import Path

# Fix Windows console encoding
if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "https://ghdx.healthdata.org"
CATALOG_URL = BASE + "/ihme_data"
OUTPUT = Path(__file__).parent.parent / "registry" / "ghdx_catalog.json"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

all_datasets = []

for page_num in range(10):  # pages 0-9
    url = CATALOG_URL if page_num == 0 else f"{CATALOG_URL}?page={page_num}"
    print(f"[Page {page_num + 1}/10] {url}")

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Each dataset is in an h2 with a link inside the content area
    entries = soup.select("h2 a[href*='/record/']")

    for link in entries:
        title = link.get_text(strip=True)
        href = link.get("href", "")
        if not href.startswith("http"):
            href = BASE + href

        # Get the description paragraph (next sibling elements)
        parent = link.find_parent("div") or link.find_parent("h2")
        description = ""
        modified = ""

        # Walk up to the dataset container
        container = link.find_parent("h2")
        if container:
            container = container.find_parent()

        if container:
            # Get description paragraphs
            paras = container.find_all("p")
            desc_parts = []
            for p in paras:
                text = p.get_text(strip=True)
                if text and "GHDx Entry last modified" not in text:
                    desc_parts.append(text)
                elif "GHDx Entry last modified" in text:
                    modified = text.replace("GHDx Entry last modified on:", "").strip()
            description = " ".join(desc_parts[:2])  # first 2 paragraphs

            # Check for direct download links (cloud.ihme.washington.edu)
            cloud_links = container.find_all("a", href=lambda h: h and "cloud.ihme" in h)
            direct_urls = [a["href"] for a in cloud_links]
        else:
            direct_urls = []

        all_datasets.append({
            "title": title,
            "record_url": href,
            "description": description[:500],
            "last_modified": modified,
            "direct_download_urls": direct_urls,
            "page": page_num + 1
        })

    print(f"  -> Found {len(entries)} entries (total: {len(all_datasets)})")
    time.sleep(1)  # polite crawling

# Save catalog
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump({
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_datasets": len(all_datasets),
        "datasets": all_datasets
    }, f, indent=2, ensure_ascii=False)

print(f"\nDone! {len(all_datasets)} datasets saved to {OUTPUT}")

# Summary stats
with_direct = sum(1 for d in all_datasets if d["direct_download_urls"])
print(f"  {with_direct} have direct cloud download links")

# Show GBD 2023 datasets specifically
gbd2023 = [d for d in all_datasets if "GBD 2023" in d["title"] or "gbd-2023" in d["record_url"]]
print(f"  {len(gbd2023)} are GBD 2023 datasets")
