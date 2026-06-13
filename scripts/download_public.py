"""
Download all GHDx files — NO AUTH NEEDED.
The file URLs (sites/default/files) are public once you know them.
Auth was only needed to discover the URLs.

Usage: python scripts/download_public.py [--dry-run] [--filter GBD]
"""
import json
import os
import re
import sys
import io
import time
from pathlib import Path

import requests

if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).parent.parent
AUTH_DB = ROOT / "registry" / "ghdx_files_auth.json"
DOWNLOAD_DIR = ROOT / "data" / "raw" / "ghdx_bulk"
PROGRESS = ROOT / "registry" / "download_progress.json"


def sanitize(name, max_len=180):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')[:max_len] or 'unnamed'


def main():
    dry_run = "--dry-run" in sys.argv
    filter_pat = None
    for i, a in enumerate(sys.argv):
        if a == "--filter" and i + 1 < len(sys.argv):
            filter_pat = sys.argv[i + 1].lower()

    with open(AUTH_DB, encoding="utf-8") as f:
        auth_data = json.load(f)

    if PROGRESS.exists():
        with open(PROGRESS, encoding="utf-8") as f:
            progress = json.load(f)
    else:
        progress = {"completed": {}, "failed": {}}

    # Clear old failures
    progress["failed"] = {}

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Plain session — NO auth cookies
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    # Build queue
    queue = []
    for slug, rec in auth_data.items():
        if filter_pat and filter_pat not in rec.get("title", "").lower():
            continue
        for fi in rec.get("files", []):
            url = fi["url"]
            folder = sanitize(slug)
            fname = sanitize(fi.get("filename", "") or url.split("/")[-1].split("?")[0])
            key = f"{slug}/{fname}"
            if key in progress["completed"]:
                continue
            queue.append({"url": url, "dest": str(DOWNLOAD_DIR / folder / fname),
                         "key": key, "title": rec.get("title", ""),
                         "size": fi.get("size", ""), "filename": fname})

    print(f"Queue: {len(queue)} files | {len(progress['completed'])} already done")

    if dry_run:
        for item in queue[:30]:
            print(f"  {item['size']:>12} {item['title'][:50]} / {item['filename'][:30]}")
        if len(queue) > 30:
            print(f"  ... and {len(queue) - 30} more")
        return

    ok = fail = 0
    consecutive_fails = 0

    for i, item in enumerate(queue):
        if (i + 1) % 20 == 0 or i == 0:
            print(f"[{i+1}/{len(queue)}] ok={ok} fail={fail} | {item['filename'][:40]} ({item['size']})")

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

                # Verify we got real content (not an error page)
                if total_size < 500 and item["size"] and "MB" in item["size"]:
                    raise ValueError(f"File too small ({total_size} bytes), expected {item['size']}")

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
                    time.sleep((attempt + 1) * 10)
                else:
                    progress["failed"][item["key"]] = {
                        "url": item["url"], "error": str(e)[:200],
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                    fail += 1
                    consecutive_fails += 1

        # Throttle
        if consecutive_fails >= 10:
            print(f"  10 consecutive fails — waiting 120s...")
            time.sleep(120)
            consecutive_fails = 0
        elif success:
            time.sleep(1)  # gentle 1s delay
        else:
            time.sleep(5)

        if (i + 1) % 10 == 0:
            with open(PROGRESS, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2)

    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)

    total_done = len(progress["completed"])
    total_fail = len(progress["failed"])
    print(f"\n{'=' * 60}")
    print(f"DOWNLOAD COMPLETE: {ok} new + {total_done - ok} previous = {total_done} total")
    print(f"Failed: {total_fail}")
    print(f"Files at: {DOWNLOAD_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
