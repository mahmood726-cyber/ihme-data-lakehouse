"""
Resume downloads using fresh login. Skips completed files.
Uses requests with fresh cookies + retry logic + throttling.
"""
import sys
import io
import os
import re
import json
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stdout.reconfigure(line_buffering=True)  # Force flush each line

from selenium import webdriver
from selenium.webdriver.common.by import By
import requests

BASE = "https://ghdx.healthdata.org"
ROOT = Path(__file__).parent.parent
AUTH_DB = ROOT / "registry" / "ghdx_files_auth.json"
DOWNLOAD_DIR = ROOT / "data" / "raw" / "ghdx_bulk"
PROGRESS = ROOT / "registry" / "download_progress.json"

EMAIL = sys.argv[1] if len(sys.argv) > 1 else ""
PASSW = sys.argv[2] if len(sys.argv) > 2 else ""

if not EMAIL or not PASSW:
    print("Usage: python download_resume.py EMAIL PASSWORD")
    sys.exit(1)


def login():
    """Login and return requests session with valid cookies."""
    print("Logging in...")
    options = webdriver.ChromeOptions()
    profile = str(ROOT / ".selenium_dl")
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--no-first-run")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)

    driver.get(f"{BASE}/download-access/login")
    time.sleep(5)

    if "b2clogin" in driver.current_url:
        driver.find_element(By.ID, "signInName").send_keys(EMAIL)
        driver.find_element(By.ID, "password").send_keys(PASSW)
        driver.execute_script('document.getElementById("next").click()')
        for _ in range(30):
            time.sleep(2)
            if "ghdx.healthdata.org" in driver.current_url and "b2clogin" not in driver.current_url:
                break
        else:
            print("Login timeout!")
            driver.quit()
            return None

    print(f"Logged in: {driver.current_url[:60]}")

    # Build session
    cookies = driver.get_cookies()
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    # Verify
    r = session.get(f"{BASE}/user", timeout=15)
    if "Log out" in r.text:
        print("Session verified!")
    else:
        print("WARN: Session may not be authenticated, proceeding anyway...")

    driver.quit()
    return session


def sanitize(name, max_len=180):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip('. ')[:max_len] or 'unnamed'


def download_file(session, url, dest, timeout=300):
    """Download with streaming."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(url, stream=True, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
            total += len(chunk)
    return total


def main():
    session = login()
    if not session:
        sys.exit(1)

    # Load data
    with open(AUTH_DB, encoding="utf-8") as f:
        auth_data = json.load(f)

    if PROGRESS.exists():
        with open(PROGRESS, encoding="utf-8") as f:
            progress = json.load(f)
    else:
        progress = {"completed": {}, "failed": {}}

    # Clear old failures for retry
    old_fails = len(progress.get("failed", {}))
    progress["failed"] = {}

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Build queue
    queue = []
    for slug, rec in auth_data.items():
        for fi in rec.get("files", []):
            url = fi["url"]
            folder = sanitize(slug)
            fname = sanitize(fi.get("filename", "") or url.split("/")[-1].split("?")[0])
            key = f"{slug}/{fname}"
            if key in progress["completed"]:
                continue
            queue.append({"url": url, "dest": str(DOWNLOAD_DIR / folder / fname),
                         "key": key, "title": rec.get("title", ""), "size": fi.get("size", "")})

    print(f"Queue: {len(queue)} files ({len(progress['completed'])} already done, {old_fails} retrying)")

    ok = fail = 0
    consecutive_fails = 0
    relogin_count = 0

    for i, item in enumerate(queue):
        if (i + 1) % 20 == 0 or i == 0:
            print(f"[{i+1}/{len(queue)}] done={ok} fail={fail} | {item['title'][:45]} ({item['size']})")

        success = False
        for attempt in range(3):
            try:
                sz = download_file(session, item["url"], item["dest"])
                progress["completed"][item["key"]] = {
                    "path": item["dest"], "size": sz,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                }
                ok += 1
                success = True
                consecutive_fails = 0
                break
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (401, 403):
                    # Session expired — re-login
                    if relogin_count < 5:
                        print(f"  Auth expired, re-logging in...")
                        session = login()
                        relogin_count += 1
                        if not session:
                            print("Re-login failed. Stopping.")
                            # Save progress
                            with open(PROGRESS, "w", encoding="utf-8") as f:
                                json.dump(progress, f, indent=2)
                            sys.exit(1)
                        time.sleep(5)
                    else:
                        raise
                elif attempt < 2:
                    time.sleep((attempt + 1) * 15)
                else:
                    raise
            except Exception as e:
                if attempt < 2:
                    time.sleep((attempt + 1) * 15)
                else:
                    progress["failed"][item["key"]] = {
                        "url": item["url"], "error": str(e)[:200],
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
                    }
                    fail += 1
                    consecutive_fails += 1

        # Throttle — IHME rate-limits aggressively
        if consecutive_fails >= 5:
            print(f"  5 consecutive fails — cooling down 120s...")
            time.sleep(120)
            consecutive_fails = 0
            # Re-login after cooldown
            print(f"  Re-logging in after cooldown...")
            new_session = login()
            if new_session:
                session = new_session
                relogin_count += 1
        elif success:
            time.sleep(5)  # 5s between successful downloads
        else:
            time.sleep(10)

        # Save every 10
        if (i + 1) % 10 == 0:
            with open(PROGRESS, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2)

    # Final save
    with open(PROGRESS, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"DOWNLOAD COMPLETE")
    print(f"  Succeeded: {ok}")
    print(f"  Failed: {fail}")
    print(f"  Total completed: {len(progress['completed'])}")
    print(f"  Files at: {DOWNLOAD_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
