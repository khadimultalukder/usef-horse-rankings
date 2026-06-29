"""
Usage:
  python main_app.py                                                              # run all events & sections
  python main_app.py --event "event_0"                                           # run specific event
  python main_app.py --pdf 5                                                      # stop after 5 PDFs, then export
  python main_app.py --event "event_0" --pdf 3
  python main_app.py --section "2421 Small Junior Hunter 3'3\" 15 & Under"               # run one section across all events
  python main_app.py --section "2401 Small Junior Hunter 15/Under" --event "event_0"  # combine section + event
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoSuchWindowException, TimeoutException, WebDriverException
from pdf_utils import process_pdf
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
import time
import os
import re
import glob
import json
import shutil
import argparse

load_dotenv()

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "horse_reports")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usef_cookies.json")

USEF_HOME    = "https://www.usef.org"           # base domain — cookies set here apply to ALL subdomains
LOGIN_URL    = "https://members.usef.org/"
RANKINGS_URL = "https://www.usef.org/compete/rankings-results"
EMAIL    = os.environ["USEF_USERNAME"]
PASSWORD = os.environ["USEF_PASSWORD"]

SECTIONS = [
    "2401 Small Junior Hunter 15/Under",
    "2402 Large Junior Hunter 15/Under",
    "2403 Small Junior Hunter 16-17 Years",
    "2404 Large Junior Hunter 16-17 Years",
    "2421 Small Junior Hunter 3'3\" 15 & Under",
    "2422 Large Junior Hunter 3'3\" 15 & Under",
    "2423 Small Junior Hunter 3'3\" 16-17",
    "2424 Large Junior Hunter 3'3\" 16-17",
    "2501 Small Pony Hunter",
    "2502 Medium Pony Hunter",
    "2503 Large Pony Hunter",
]

EVENTS = [
    {
        "event_name": "event_0",
        "comp_year": "2026",
        "date": [
            {"start_date": "3/31/2026", "end_date": "3/30/2027"},
            {"start_date": "9/1/2025",  "end_date": "8/31/2026"},
        ]
    },
    {
        "event_name": "event_1",
        "comp_year": "2025",
        "date": [
            {"start_date": "9/1/2025", "end_date": "8/31/2026"},
        ]
    },
]

# ──────────────────────────────────────────────
# Supabase setup
# ──────────────────────────────────────────────
TABLE_NAME    = "usef_horse_rankings"
CONFLICT_COLS = "horse_id,award_category,start_date"
BATCH_SIZE    = 500

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_KEY"],
)

# Accumulates records across all events; uploaded at the end of main()
Extracted_Data: list = []


def _parse_date(s: str) -> str:
    """Convert MM/DD/YYYY → YYYY-MM-DD (ISO 8601)."""
    return datetime.strptime(s, "%m/%d/%Y").date().isoformat()


def _transform_record(r: dict) -> dict:
    """Return a DB-ready dict from a raw extracted record."""
    return {
        "competition_year":  r["competition_year"],
        "horse_name":        r["horse_name"],
        "horse_id":          r["horse_id"],
        "horse_link":        r["horse_link"],
        "section":           r["section"],
        "start_date":        _parse_date(r["start_date"]),
        "end_date":          _parse_date(r["end_date"]),
        "pdf_download_link": r["pdf_download_link"],
        "award_category":    r["award_category"],
        "nat_points_good":   r.get("nat_points_good"),
        "show_count":        r.get("show_count", 0),
        "shows":             r.get("shows", []),
        "scraped_at":        datetime.now(timezone.utc).isoformat(),
    }


def _dedupe(rows: list) -> list:
    """
    Keep only the LAST occurrence of each (horse_id, award_category, start_date).
    Prevents Supabase 'ON CONFLICT cannot affect row a second time' errors.
    """
    seen = {}
    for row in rows:
        key = (
            str(row.get("horse_id", "")).strip(),
            str(row.get("award_category", "")).strip(),
            str(row.get("start_date", "")).strip(),
        )
        seen[key] = row
    return list(seen.values())


def upload_to_supabase():
    """
    Upsert all collected records to Supabase.

    Conflict key : horse_id + award_category + start_date
    On conflict  : replace the existing row (scraped_at always updated)
    New records  : inserted as new rows
    """
    if not Extracted_Data:
        print("⚠️  No data to upload to Supabase")
        return

    rows   = [_transform_record(r) for r in Extracted_Data]
    before = len(rows)
    rows   = _dedupe(rows)
    dupes  = before - len(rows)
    if dupes:
        print(f"ℹ️  Removed {dupes} in-batch duplicate(s) before upload")

    total    = len(rows)
    inserted = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        try:
            supabase.table(TABLE_NAME).upsert(batch, on_conflict=CONFLICT_COLS).execute()
            inserted += len(batch)
            print(f"✅ Supabase batch {i // BATCH_SIZE + 1}: {inserted}/{total} rows upserted")
        except Exception as e:
            print(f"❌ Supabase batch {i // BATCH_SIZE + 1} failed: {e}")

    print(f"\n🎉 Supabase upload complete — {inserted}/{total} rows upserted to '{TABLE_NAME}'")


# ──────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────
def get_driver():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    options.page_load_strategy = "none"
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    }
    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.set_script_timeout(60)
    return driver


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def accept_cookies(driver):
    try:
        btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
        )
        btn.click()
        print("✅ Cookie banner accepted")
        time.sleep(1)
    except Exception:
        pass


def wait_for_page_ready(driver, timeout=60):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") in ("complete", "interactive")
        )
    except Exception:
        pass


def safe_close_tab(driver, main_tab):
    try:
        if driver.current_window_handle != main_tab:
            driver.close()
    except (NoSuchWindowException, WebDriverException):
        pass
    try:
        driver.switch_to.window(main_tab)
    except (NoSuchWindowException, WebDriverException) as e:
        print(f"⚠️ Could not switch back to main tab: {e}")


def sanitize_date(date_str):
    return date_str.replace("/", "-")


def build_pdf_link(horse_id, start_date, end_date):
    return f"https://www.usef.org/search/horses/report/{horse_id}?startDate={start_date}&endDate={end_date}"


def extract_pdf_data(pdf_path, base_row, seen_rows):
    """
    Parse PDF, collect records into Extracted_Data for Supabase upload,
    then delete the PDF.

    base_row order: [comp_year, horse_name, horse_id, url,
                     section_id, start, end, pdf_link]
    """
    section_totals, channel1 = process_pdf(pdf_path)

    if not section_totals and not channel1:
        print(f"      ⚠️ No data extracted from PDF")
    else:
        written = 0
        skipped = 0
        for category, nat_points in channel1.items():
            shows_list = section_totals.get(category, [])
            show_count = len(shows_list)

            horse_id   = base_row[2]
            start_date = base_row[5]
            dedup_key  = (horse_id, start_date, category, nat_points)
            if dedup_key in seen_rows:
                skipped += 1
                continue
            seen_rows.add(dedup_key)

            # Collect for Supabase
            Extracted_Data.append({
                "competition_year":  base_row[0],
                "horse_name":        base_row[1],
                "horse_id":          base_row[2],
                "horse_link":        base_row[3],
                "section":           base_row[4],
                "start_date":        base_row[5],
                "end_date":          base_row[6],
                "pdf_download_link": base_row[7],
                "award_category":    category,
                "nat_points_good":   nat_points,
                "show_count":        show_count,
                "shows":             shows_list,
            })

            written += 1
        print(f"      📊 {written} rows collected, {skipped} duplicates skipped")

    try:
        os.remove(pdf_path)
        print(f"      🗑️ PDF deleted: {os.path.basename(pdf_path)}")
    except Exception as e:
        print(f"      ⚠️ Could not delete PDF: {e}")


# ──────────────────────────────────────────────
# Cookie-based session management
# ──────────────────────────────────────────────
def save_cookies(driver):
    """Save current browser cookies to disk."""
    cookies = driver.get_cookies()
    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"🍪 Cookies saved ({len(cookies)} cookies → {os.path.basename(COOKIES_FILE)})")


def load_cookies(driver):
    """Inject saved cookies into the driver. Driver must already be on the target domain."""
    if not os.path.exists(COOKIES_FILE):
        return False
    with open(COOKIES_FILE, "r") as f:
        cookies = json.load(f)
    for cookie in cookies:
        cookie.pop("sameSite", None)   # can cause InvalidCookieDomainException
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass
    print(f"🍪 Cookies loaded ({len(cookies)} cookies)")
    return True


def is_logged_in(driver):
    """Return True if the current page shows an authenticated session."""
    # URL check: site redirects to /log-in/ when session is invalid
    if "log-in" in driver.current_url or "/login" in driver.current_url.lower():
        return False
    try:
        # Login form present → not authenticated
        driver.find_element(By.CSS_SELECTOR, "input#Username")
        return False
    except Exception:
        return True


def _do_login(driver):
    """Submit the login form. Assumes driver is already on LOGIN_URL."""
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input#Username"))
        ).send_keys(EMAIL)
        time.sleep(0.5)

        driver.find_element(By.CSS_SELECTOR, "input#Password").send_keys(PASSWORD)
        time.sleep(0.5)

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))
        ).click()
        print("✅ Login submitted")
        wait_for_page_ready(driver, 30)
        time.sleep(2)
    except Exception as e:
        print(f"⚠️ Login failed: {e}")


def smart_login(driver):
    """
    ✅ First run   → fresh login → cookies saved to disk
    ✅ Next runs   → cookies loaded → session verified (no login needed)
    ✅ Cookie expired → auto re-login → cookies updated on disk
    ✅ Login frequency kept low → looks natural to the site

    Cookie loading order (critical for multi-domain sites):
      1. Land on www.usef.org  → inject cookies (they apply to .usef.org = all subdomains)
      2. Navigate to members.usef.org → browser already carries the cookies
      3. Check session → skip login if valid
    """
    if os.path.exists(COOKIES_FILE):
        print("🍪 Saved cookies found — restoring session...")

        # Step 1: Base domain first so cookies cover .usef.org and all subdomains
        print(f"🌐 Opening {USEF_HOME} to prime cookie domain...")
        driver.get(USEF_HOME)
        wait_for_page_ready(driver, 20)
        time.sleep(1)
        accept_cookies(driver)
        load_cookies(driver)

        # Step 2: Navigate to members subdomain — cookies are already in browser
        print(f"🌐 Navigating to {LOGIN_URL}")
        driver.get(LOGIN_URL)
        wait_for_page_ready(driver, 30)
        time.sleep(2)

        if is_logged_in(driver):
            print("✅ Session restored from cookies — skipping login")
            return

        print("⚠️  Cookies expired — performing fresh login...")
    else:
        print("🔐 No saved cookies — first-time login...")
        driver.get(LOGIN_URL)
        wait_for_page_ready(driver, 30)
        time.sleep(2)
        accept_cookies(driver)

    _do_login(driver)
    save_cookies(driver)


def ensure_logged_in(driver):
    """
    Call this mid-scrape if a page unexpectedly shows the login form.
    Re-logs in, saves updated cookies, and returns to the current URL.
    """
    current = driver.current_url
    if not is_logged_in(driver):
        print("🔄 Session expired mid-scrape — re-logging in...")
        driver.get(LOGIN_URL)
        wait_for_page_ready(driver, 30)
        time.sleep(2)
        _do_login(driver)
        save_cookies(driver)
        driver.get(current)
        wait_for_page_ready(driver, 30)
        time.sleep(2)


# ──────────────────────────────────────────────
# Rankings page setup
# ──────────────────────────────────────────────
def open_rankings(driver, comp_year, section_id):
    print(f"\n🌐 Rankings — CompYear={comp_year} | Section={section_id}")
    driver.get(RANKINGS_URL)
    wait_for_page_ready(driver, 30)
    time.sleep(2)

    # Guard: if we were silently logged out, recover before touching dropdowns
    ensure_logged_in(driver)

    dropdowns = [
        ("CompYear",            comp_year,            f"CompYear={comp_year}"),
        ("StandingTypeDisplay", "National Points",    "National Points"),
        ("Category",            "Hunter - Channel 1", "Hunter - Channel 1"),
    ]
    for elem_id, value, label in dropdowns:
        try:
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, elem_id))
            )
            Select(el).select_by_value(value)
            print(f"  ✅ {label}")
            time.sleep(2)
        except Exception as e:
            print(f"  ⚠️ Could not select {elem_id}: {e}")

    try:
        el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "SectionUID"))
        )
        Select(el).select_by_visible_text(section_id)
        print(f"  ✅ Section={section_id}")
        time.sleep(2)
    except Exception as e:
        print(f"  ⚠️ Could not select SectionUID: {e}")


# ──────────────────────────────────────────────
# Process a single horse tab
# ──────────────────────────────────────────────
def process_horse(driver, url, horse_id, horse_name, dates, main_tab,
                  section_id, comp_year, seen_rows):
    for handle in driver.window_handles:
        if handle != main_tab:
            try:
                driver.switch_to.window(handle)
                driver.close()
            except Exception:
                pass
    driver.switch_to.window(main_tab)

    driver.execute_script("window.open(arguments[0]);", url)
    time.sleep(1)

    new_tabs = [h for h in driver.window_handles if h != main_tab]
    if not new_tabs:
        print(f"    ⚠️ Tab didn't open for {horse_id}, skipping")
        return

    driver.switch_to.window(new_tabs[0])
    wait_for_page_ready(driver, 30)
    time.sleep(1)

    try:
        for date_entry in dates:
            start = date_entry["start_date"]
            end   = date_entry["end_date"]
            print(f"    📅 {start} → {end}")

            pdf_link = build_pdf_link(horse_id, start, end)
            base_row = [
                comp_year, horse_name, horse_id, url,
                section_id, start, end, pdf_link,
            ]

            try:
                el = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "StartDate"))
                )
                el.clear()
                el.send_keys(start)
                time.sleep(0.5)
            except Exception as e:
                print(f"      ⚠️ StartDate: {e}")

            try:
                el = driver.find_element(By.ID, "EndDate")
                el.clear()
                el.send_keys(end)
                time.sleep(0.5)
            except Exception as e:
                print(f"      ⚠️ EndDate: {e}")

            try:
                driver.find_element(
                    By.CSS_SELECTOR, "input[type='submit'][name='Update']"
                ).click()
                WebDriverWait(driver, 180).until(
                    EC.element_to_be_clickable((By.ID, "Report"))
                )
                print(f"      ✅ Results updated")
            except TimeoutException:
                print(f"      ⚠️ Timed out waiting for Report ({horse_id}, {start})")
                continue
            except Exception as e:
                print(f"      ⚠️ Update failed: {e}")
                continue

            MAX_RETRIES = 3
            downloaded = None
            dest = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    before = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*")))
                    driver.find_element(By.ID, "Report").click()
                    print(f"      📥 Download attempt {attempt}/{MAX_RETRIES}...")

                    for _ in range(60):
                        time.sleep(1)
                        after     = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*")))
                        new_files = [f for f in (after - before) if not f.endswith(".crdownload") and not f.endswith(".tmp")]
                        if new_files:
                            downloaded = new_files[0]
                            break

                    if downloaded:
                        from pdf_utils import is_valid_pdf
                        if not is_valid_pdf(downloaded):
                            print(f"      ⚠️ Attempt {attempt} — corrupt/incomplete file, {'retrying...' if attempt < MAX_RETRIES else 'giving up.'}")
                            try:
                                os.remove(downloaded)
                            except Exception:
                                pass
                            downloaded = None
                        else:
                            ext      = os.path.splitext(downloaded)[1]
                            filename = f"{horse_id}_{sanitize_date(start)}{ext}"
                            dest     = os.path.join(DOWNLOAD_DIR, filename)
                            if os.path.exists(dest):
                                os.remove(dest)
                            os.rename(downloaded, dest)
                            print(f"      💾 {filename}")
                            break
                    else:
                        print(f"      ⚠️ Attempt {attempt} timed out, {'retrying...' if attempt < MAX_RETRIES else 'giving up.'}")

                except Exception as e:
                    print(f"      ⚠️ Attempt {attempt} failed: {e}, {'retrying...' if attempt < MAX_RETRIES else 'giving up.'}")

                if attempt < MAX_RETRIES:
                    time.sleep(3)

            if dest and os.path.exists(dest):
                extract_pdf_data(dest, base_row, seen_rows)
            else:
                print(f"      ⚠️ PDF not available for extraction")

    finally:
        safe_close_tab(driver, main_tab)
        time.sleep(1)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="USEF Horse Scraper")
    parser.add_argument(
        "--event",
        type=str,
        default=None,
        help='Run a specific event by name (e.g. --event "event_0")'
    )
    parser.add_argument(
        "--section",
        type=str,
        default=None,
        help='Run a specific section (e.g. --section "2401 Small Junior Hunter 15/Under")'
    )
    parser.add_argument(
        "--pdf",
        type=int,
        default=None,
        help="Stop after processing this many PDFs total, then export (e.g. --pdf 5)"
    )
    args = parser.parse_args()
    pdf_limit = args.pdf
    pdf_count = 0

    sections_to_run = SECTIONS
    if args.section:
        sections_to_run = [s for s in SECTIONS if s == args.section]
        if not sections_to_run:
            print(f"❌ No section found: '{args.section}'")
            print(f"   Available sections: {SECTIONS}")
            return
        print(f"🎯 Running only section: {args.section}")

    events_to_run = EVENTS
    if args.event:
        events_to_run = [e for e in EVENTS if e["event_name"] == args.event]
        if not events_to_run:
            print(f"❌ No event found with name '{args.event}'")
            print(f"   Available events: {[e['event_name'] for e in EVENTS]}")
            return
        print(f"🎯 Running only: {args.event}")

    if pdf_limit:
        print(f"🧪 Test mode: will stop after {pdf_limit} PDF(s)")

    driver = get_driver()
    smart_login(driver)   # ← cookie-aware login (replaces plain login())

    stop = False

    for event in events_to_run:
        if stop:
            break
        event_name = event["event_name"]
        comp_year  = event["comp_year"]
        dates      = event["date"]
        seen       = set()
        seen_rows  = set()

        for section_id in sections_to_run:
            if stop:
                break
            print(f"\n{'='*60}")
            print(f"📋  {event_name}  |  CompYear: {comp_year}  |  Section: {section_id}")
            print(f"{'='*60}")

            open_rankings(driver, comp_year, section_id)

            page = 1
            while True:
                print(f"\n  📄 Page {page}")
                time.sleep(2)

                links = driver.find_elements(
                    By.XPATH,
                    "//details//div[@class='td text-table horse-owner-label ']/div/a[1]"
                )
                horses = [
                    (a.get_attribute("href"), a.text.strip())
                    for a in links if a.get_attribute("href")
                ]
                print(f"  🔗 {len(horses)} horses found")

                main_tab = driver.current_window_handle

                for i, (url, horse_name) in enumerate(horses):
                    m = re.search(r'/display/([^?/]+)', url)
                    horse_id = m.group(1) if m else f"horse_{i+1}"

                    if horse_id in seen:
                        print(f"  ⏭  Skip (seen): {horse_id}")
                        continue

                    seen.add(horse_id)
                    print(f"  ↗  [{i+1}/{len(horses)}] {horse_name} ({horse_id})")
                    process_horse(
                        driver, url, horse_id, horse_name, dates, main_tab,
                        section_id, comp_year, seen_rows
                    )
                    pdf_count += 1

                    if pdf_limit and pdf_count >= pdf_limit:
                        print(f"\n🧪 --pdf {pdf_limit} limit reached — stopping and exporting")
                        stop = True
                        break

                if stop:
                    break

                next_btn = driver.find_elements(
                    By.XPATH,
                    "//div[@class='btn-group']//a[@class='btn btn-primary']/following-sibling::a[1]"
                )
                if not next_btn:
                    print(f"  ✅ No more pages")
                    break

                next_btn[0].click()
                wait_for_page_ready(driver, 30)
                page += 1
                time.sleep(2)

    try:
        driver.quit()
    except Exception:
        pass

    print(f"\n🎉 Scraping done!")

    # ── Upload all collected data to Supabase ──────────────────────────────
    print(f"\n📤 Uploading {len(Extracted_Data)} records to Supabase...")
    upload_to_supabase()

    # ── Delete horse_reports folder ────────────────────────────────────────
    try:
        shutil.rmtree(DOWNLOAD_DIR)
        print(f"🗑️  Deleted folder: {DOWNLOAD_DIR}")
    except Exception as e:
        print(f"⚠️  Could not delete horse_reports folder: {e}")


if __name__ == "__main__":
    main()
