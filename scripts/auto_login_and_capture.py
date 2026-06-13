"""
Auto-login to GHDx via Azure B2C, capture cookies, then clean up.
Credentials used in-memory only, never written to disk.
"""
import sys
import io
import time
import json
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

if 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).parent.parent
COOKIE_FILE = PROJECT_ROOT / "registry" / ".cookies.json"
COOKIE_STR_FILE = PROJECT_ROOT / "registry" / ".cookie_str.txt"

# Credentials in-memory only — never written to disk
EMAIL = sys.argv[1] if len(sys.argv) > 1 else ""
PASSW = sys.argv[2] if len(sys.argv) > 2 else ""

if not EMAIL or not PASSW:
    print("Usage: python auto_login_and_capture.py EMAIL PASSWORD")
    sys.exit(1)

print("Launching Chrome...")
options = webdriver.ChromeOptions()
profile = str(PROJECT_ROOT / ".selenium_auto")
options.add_argument(f"--user-data-dir={profile}")
options.add_argument("--no-first-run")
options.add_argument("--no-default-browser-check")
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1280,900")

driver = webdriver.Chrome(options=options)
driver.set_page_load_timeout(60)

try:
    print("Navigating to GHDx download-access login...")
    driver.get("https://ghdx.healthdata.org/download-access/login")
    time.sleep(5)
    print(f"Page: {driver.current_url[:80]}")

    # Azure B2C login form
    if "b2clogin" in driver.current_url:
        print("Azure B2C login page detected. Filling form...")

        # Wait for email field
        wait = WebDriverWait(driver, 15)

        # Try different possible field selectors for Azure B2C
        email_selectors = [
            (By.ID, "signInName"),
            (By.ID, "email"),
            (By.NAME, "loginfmt"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[placeholder*='mail']"),
            (By.CSS_SELECTOR, "input[type='text']"),
        ]

        email_field = None
        for by, sel in email_selectors:
            try:
                email_field = wait.until(EC.presence_of_element_located((by, sel)))
                print(f"  Found email field: {by}={sel}")
                break
            except Exception:
                continue

        if not email_field:
            # Debug: print page source to understand the form
            print("Could not find email field. Page elements:")
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs:
                print(f"  <input id='{inp.get_attribute('id')}' name='{inp.get_attribute('name')}' type='{inp.get_attribute('type')}' placeholder='{inp.get_attribute('placeholder')}'>")
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                print(f"  <button id='{btn.get_attribute('id')}'>{btn.text}</button>")
            driver.quit()
            sys.exit(1)

        email_field.clear()
        email_field.send_keys(EMAIL)
        print("  Email entered.")
        time.sleep(1)

        # Find password field
        pass_selectors = [
            (By.ID, "password"),
            (By.NAME, "passwd"),
            (By.CSS_SELECTOR, "input[type='password']"),
        ]

        pass_field = None
        for by, sel in pass_selectors:
            try:
                pass_field = driver.find_element(by, sel)
                if pass_field.is_displayed():
                    print(f"  Found password field: {by}={sel}")
                    break
            except Exception:
                continue

        if not pass_field:
            # Maybe need to click "Next" first (some B2C flows split email/password)
            print("  No password field visible. Looking for Next button...")
            next_btns = driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], #next, .next")
            for btn in next_btns:
                if btn.is_displayed():
                    print(f"  Clicking: {btn.text}")
                    btn.click()
                    time.sleep(3)
                    break

            # Try password again
            for by, sel in pass_selectors:
                try:
                    pass_field = wait.until(EC.presence_of_element_located((by, sel)))
                    print(f"  Found password field: {by}={sel}")
                    break
                except Exception:
                    continue

        if pass_field:
            pass_field.clear()
            pass_field.send_keys(PASSW)
            print("  Password entered.")
            time.sleep(1)

            # Find and click submit
            submit_selectors = [
                (By.ID, "next"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "#idSIButton9"),
                (By.CSS_SELECTOR, "button.btn-primary"),
            ]

            for by, sel in submit_selectors:
                try:
                    btn = driver.find_element(by, sel)
                    if btn.is_displayed():
                        print(f"  Clicking submit: {by}={sel}")
                        btn.click()
                        break
                except Exception:
                    continue

            # Wait for redirect back to GHDx
            print("  Waiting for redirect to GHDx...")
            for i in range(60):
                time.sleep(1)
                url = driver.current_url
                if i % 10 == 0:
                    print(f"    [{i}s] {url[:70]}")
                if "ghdx.healthdata.org" in url and "b2clogin" not in url:
                    print(f"  Redirected to: {url[:80]}")
                    break
            else:
                print("  Timeout waiting for redirect.")
                # Check for error messages
                try:
                    errors = driver.find_elements(By.CSS_SELECTOR, ".error, .alert, #errorMessage, .errorMessage")
                    for e in errors:
                        if e.text:
                            print(f"  Error on page: {e.text}")
                except Exception:
                    pass
                driver.quit()
                sys.exit(1)
        else:
            print("  Could not find password field.")
            driver.quit()
            sys.exit(1)

    # Capture cookies
    time.sleep(3)
    cookies = driver.get_cookies()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    print(f"\nCaptured {len(cookies)} cookies")
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f, indent=2)
    with open(COOKIE_STR_FILE, "w") as f:
        f.write(cookie_str)

    # Verify authentication
    import requests
    from bs4 import BeautifulSoup

    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    s.headers["Cookie"] = cookie_str

    r = s.get("https://ghdx.healthdata.org/user", timeout=15)
    logged_in = "Log out" in r.text
    print(f"GHDx authenticated: {logged_in}")

    if logged_in:
        r2 = s.get("https://ghdx.healthdata.org/record/ihme-data/gbd-2023-covariates-1980-2023", timeout=15)
        soup = BeautifulSoup(r2.text, "html.parser")
        real = [a["href"] for a in soup.find_all("a", href=True) if "sites/default/files" in a["href"]]
        auth = [a["href"] for a in soup.find_all("a", href=True) if "download-access/login" in a["href"]]
        print(f"Real file URLs: {len(real)}")
        for u in real[:3]:
            print(f"  {u[:120]}")
        print(f"Auth-gated URLs: {len(auth)}")
        print("\nSUCCESS! Cookies saved. Ready for bulk scrape+download.")
    else:
        print("Login may have failed or cookies didn't transfer to requests.")

finally:
    driver.quit()
    # Clear credential variables
    EMAIL = ""
    PASSW = ""
    print("Browser closed. Credentials cleared from memory.")
