import asyncio
import json
import os
from datetime import date, datetime
from collections import defaultdict
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv

from .config import Config
from .pdf_utils import process_pdf
from .downloader import download_pdf
from .logger import Logger
from .notifier import notify_failure, notify_summary


load_dotenv()

logger = Logger("usef_scraper")

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY"),
)

TABLE_NAME = "usef_horse_rankings"
BATCH_SIZE = 500
CONFLICT_COLS = "horse_id,award_category,start_date"

Extracted_Data = []
_notification_sent = False  # ensures only one email per run

SECTION_STATS = defaultdict(lambda: {
    "total": 0,
    "success": 0,
    "failed": 0
})

# Cumulative run stats — accumulated across all sections
RUN_STATS = {
    "scraped": 0,       # total records extracted from PDFs
    "duplicates": 0,    # records skipped as duplicates (in-batch + already in DB)
    "inserted": 0,      # records actually written to DB
}

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

JSONL_FILE = OUTPUT_DIR / f"{date.today().strftime('%Y-%m-%d')}.jsonl"


# ===============================================
# PROCESS HORSE
# ===============================================

async def process_horse(context, horse_info, start_date, end_date, idx, total):

    horse_id = horse_info["horse_id"]
    section = horse_info["section"]

    SECTION_STATS[section]["total"] += 1

    pdf_url = (
        f"https://www.usef.org/search/horses/report/{horse_id}"
        f"?startDate={start_date}&endDate={end_date}"
    )

    try:
        file_path = await download_pdf(context, horse_id, start_date, end_date)
    except Exception as e:
        SECTION_STATS[section]["failed"] += 1
        logger.error(f"[{idx}/{total}] PDF download exception → {horse_id}: {e}")
        return

    if not file_path:
        SECTION_STATS[section]["failed"] += 1
        logger.error(f"PDF download failed → {horse_id}")
        return

    section_totals = {}
    channel1 = {}

    try:
        loop = asyncio.get_event_loop()
        section_totals, channel1 = await loop.run_in_executor(None, process_pdf, file_path)
    except Exception as e:
        SECTION_STATS[section]["failed"] += 1
        logger.error(f"[{idx}/{total}] PDF extraction exception → {horse_id}: {e}")

    if channel1:

        try:
            for award_category, nat_points_good in channel1.items():
                show_values = section_totals.get(award_category, [])
                record = {
                    "competition_year": horse_info["competition_year"],
                    "horse_name": horse_info["horse_name"],
                    "horse_id": horse_id,
                    "horse_link": horse_info["horse_link"],
                    "section": section,
                    "start_date": start_date,
                    "end_date": end_date,
                    "pdf_download_link": pdf_url,
                    "award_category": award_category,
                    "nat_points_good": nat_points_good,
                    "show_count": len(show_values),
                    "shows": list(show_values),
                }

                Extracted_Data.append(record)

            SECTION_STATS[section]["success"] += 1

            logger.info(
                f"📊 [{idx}/{total}] Processing: "
                f"{horse_info['horse_name']} → {horse_id}"
            )

        except Exception as e:
            SECTION_STATS[section]["failed"] += 1
            logger.error(f"[{idx}/{total}] Error merging row data → {horse_id}: {e}")

    else:
        SECTION_STATS[section]["failed"] += 1
        logger.warning(
            f"[{idx}/{total}] No Channel 1 data → {horse_id} - {pdf_url}"
        )

    # delete pdf after extraction
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"PDF deleted: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to delete PDF: {e}")


# ===============================================
# SAVE JSONL BACKUP
# ===============================================

def save_to_jsonl():
    """Append new records to a JSONL backup file (one JSON object per line).
    Existing records are never overwritten — safe to run multiple times."""

    if not Extracted_Data:
        logger.warning("No data to back up")
        return

    # Load already-saved keys to avoid duplicates
    duplicate_fields = ["horse_id", "start_date", "end_date", "award_category", "nat_points_good"]
    seen_keys = set()

    if JSONL_FILE.exists():
        try:
            with open(JSONL_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    key = tuple(str(record.get(field, "")).strip() for field in duplicate_fields)
                    seen_keys.add(key)
        except Exception as e:
            logger.error(f"Failed to read existing JSONL backup → {JSONL_FILE}: {e}")

    added = 0
    skipped = 0

    try:
        with open(JSONL_FILE, "a", encoding="utf-8") as f:
            for record in Extracted_Data:
                key = tuple(str(record.get(field, "")).strip() for field in duplicate_fields)
                if key in seen_keys:
                    skipped += 1
                    continue
                seen_keys.add(key)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                added += 1

        logger.success(f"JSONL backup saved → {JSONL_FILE} | Added: {added} | Skipped: {skipped}")
    except Exception as e:
        logger.error(f"Failed to write JSONL backup → {JSONL_FILE}: {e}")


# ===============================================
# UPLOAD TO SUPABASE
# ===============================================

def parse_date(s: str) -> str:
    return datetime.strptime(s, "%m/%d/%Y").date().isoformat()


def transform_record(r: dict) -> dict:
    return {
        "competition_year": r["competition_year"],
        "horse_name": r["horse_name"],
        "horse_id": r["horse_id"],
        "horse_link": r["horse_link"],
        "section": r["section"],
        "start_date": parse_date(r["start_date"]),
        "end_date": parse_date(r["end_date"]),
        "pdf_download_link": r["pdf_download_link"],
        "award_category": r["award_category"],
        "nat_points_good": r.get("nat_points_good"),
        "show_count": r.get("show_count", 0),
        "shows": r.get("shows", []),
    }


def dedupe_on_conflict_key(rows: list) -> list:
    """Keep only the LAST occurrence of each (horse_id, award_category, start_date) tuple.
    Prevents 'ON CONFLICT cannot affect row a second time' errors."""
    seen = {}
    for row in rows:
        key = _make_key(row)
        seen[key] = row
    return list(seen.values())


def dedupe_on_content(rows: list) -> list:
    """Remove rows where horse_id + award_category + start_date are identical.
    Keeps the last occurrence so the latest nat_points_good value wins."""
    seen = {}
    for row in rows:
        key = (
            str(row.get("horse_id", "")).strip(),
            str(row.get("award_category", "")).strip(),
            str(row.get("start_date", "")).strip(),
        )
        seen[key] = row
    return list(seen.values())


def _make_key(row: dict) -> tuple:
    """Normalize and build a dedup key from a row dict."""
    return (
        str(row.get("horse_id", "")).strip(),
        str(row.get("award_category", "")).strip(),
        str(row.get("start_date", "")).strip(),
    )


def fetch_existing_keys(start_date: str, end_date: str) -> set:
    """Fetch all dedup keys already in the DB for this date range."""
    existing_keys = set()
    offset = 0
    page_size = 1000
    try:
        while True:
            resp = (
                supabase.table(TABLE_NAME)
                .select("award_category, nat_points_good, start_date, end_date")
                .eq("start_date", start_date)
                .eq("end_date", end_date)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = resp.data or []
            for row in batch:
                existing_keys.add(_make_key(row))
            if len(batch) < page_size:
                break
            offset += page_size
        logger.info(f"Fetched {len(existing_keys)} existing keys from DB for {start_date} → {end_date}")
    except Exception as e:
        logger.warning(f"Could not fetch existing keys: {e}")
    return existing_keys


def delete_old_data(start_date: str, end_date: str):
    """Delete all existing DB records for the given date range before re-scraping."""
    try:
        resp = (
            supabase.table(TABLE_NAME)
            .delete()
            .eq("start_date", start_date)
            .eq("end_date", end_date)
            .execute()
        )
        deleted_count = len(resp.data) if resp.data else 0
        logger.info(f"Deleted {deleted_count} old records from DB for {start_date} → {end_date}")
    except Exception as e:
        logger.error(f"Failed to delete old data for {start_date} → {end_date}: {e}")
        raise


def upload_to_supabase():

    if not Extracted_Data:
        logger.warning("No data to upload")
        return 0

    scraped_this_batch = len(Extracted_Data)
    RUN_STATS["scraped"] += scraped_this_batch

    rows = [transform_record(r) for r in Extracted_Data]

    # Step 1 — dedupe within this batch by content
    deduped_content = dedupe_on_content(rows)
    content_dupes = len(rows) - len(deduped_content)
    if content_dupes:
        logger.info(f"Removed {content_dupes} content-duplicate rows")
    rows = deduped_content

    # Step 2 — dedupe within this batch by conflict key
    deduped = dedupe_on_conflict_key(rows)
    key_dupes = len(rows) - len(deduped)
    if key_dupes:
        logger.info(f"Removed {key_dupes} conflict-key duplicate rows")
    rows = deduped

    RUN_STATS["duplicates"] += content_dupes + key_dupes

    if not rows:
        logger.success("No new records to upload — database is already up to date")
        return 0

    total = len(rows)
    inserted = 0
    failed_batches = []

    # Get DB count before insert to calculate actual new rows
    try:
        before_count = supabase.table(TABLE_NAME).select("*", count="exact").limit(1).execute().count or 0
    except Exception:
        before_count = None

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        try:
            supabase.table(TABLE_NAME).upsert(batch,
                                              on_conflict="horse_id,award_category,start_date").execute()
            inserted += len(batch)
            logger.success(f"Batch {i // BATCH_SIZE + 1}: {inserted}/{total} rows sent")
        except Exception as e:
            logger.error(f"Batch {i // BATCH_SIZE + 1} failed: {e}")
            failed_batches.append((i, i + BATCH_SIZE))

    # Calculate actual inserted from DB count difference
    try:
        after_count = supabase.table(TABLE_NAME).select("*", count="exact").limit(1).execute().count or 0
        actual_inserted = after_count - before_count if before_count is not None else inserted
    except Exception:
        actual_inserted = inserted

    RUN_STATS["inserted"] += actual_inserted

    logger.success(f"Done. Inserted {actual_inserted}/{total} new rows to '{TABLE_NAME}'")
    if failed_batches:
        logger.warning(f"Failed batch ranges: {failed_batches}")
    return inserted


# ===============================================
# SUMMARY
# ===============================================

def print_section_summary():

    logger.info("")
    logger.info("=======================================")
    logger.info("SCRAPER SUMMARY BY SECTION")
    logger.info("=======================================")

    total_all = 0
    success_all = 0
    failed_all = 0

    for section, stats in SECTION_STATS.items():

        total = stats["total"]
        success = stats["success"]
        failed = stats["failed"]

        total_all += total
        success_all += success
        failed_all += failed

        logger.info(section)
        logger.info(f"   Total Horses : {total}")
        logger.info(f"   Success      : {success}")
        logger.info(f"   Failed       : {failed}")
        logger.info("")

    logger.info("---------------------------------------")
    logger.info(f"TOTAL HORSES : {total_all}")
    logger.info(f"SUCCESS      : {success_all}")
    logger.info(f"FAILED       : {failed_all}")
    logger.info("=======================================")


# ===============================================
# BROWSER LOGIN
# ===============================================

async def create_browser_session():
    """Launch browser and login once. Returns (playwright, browser, context, page)."""
    from playwright.async_api import async_playwright as _async_playwright
    p = await _async_playwright().start()

    try:
        browser = await p.chromium.launch(
            headless=Config.HEADLESS,
            args=["--no-sandbox"]
        )
    except Exception as e:
        logger.error(f"Failed to launch browser: {e}")
        notify_failure("Browser launch", str(e))
        await p.stop()
        return None

    try:
        context = await browser.new_context(
            user_agent=Config.USER_AGENT,
            viewport=Config.VIEWPORT
        )
        page = await context.new_page()
        page.set_default_timeout(Config.TIMEOUT)
    except Exception as e:
        logger.error(f"Failed to create browser context/page: {e}")
        await browser.close()
        await p.stop()
        return None

    try:
        logger.info(f"Opening: {Config.START_URL}")
        await page.goto(Config.START_URL)

        try:
            await page.wait_for_selector(
                "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
                timeout=5000
            )
            cookies_button = page.locator(
                "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"
            )
            if await cookies_button.is_visible():
                await cookies_button.click()
                await asyncio.sleep(1)
                logger.info("Cookies accepted")
        except Exception:
            pass

        await page.fill("input#Username", Config.USERNAME)
        await page.fill("input#Password", Config.PASSWORD)
        await page.click("input[type='submit']")
        await page.wait_for_selector(
            "xpath=//h2[contains(.,'My USEF Dashboard')]"
        )
        logger.success("Login successful")

    except Exception as e:
        logger.error(f"Login failed: {e}")
        notify_failure("USEF Login", str(e))
        await browser.close()
        await p.stop()
        return None

    return p, browser, context, page


async def close_browser_session(session):
    """Close browser and playwright instance."""
    if not session:
        return
    p, browser, context, page = session
    try:
        await browser.close()
        await p.stop()
        logger.info("Browser closed")
    except Exception as e:
        logger.warning(f"Failed to close browser: {e}")


# ===============================================
# MAIN SCRAPER
# ===============================================

async def scrape(start_date, end_date, comp_year, context, page, test_limit=None):

    # Reset per-job stats so run_jobs accumulates correctly across multiple jobs
    RUN_STATS["scraped"] = 0
    RUN_STATS["duplicates"] = 0
    RUN_STATS["inserted"] = 0

    logger.info(f"Scraping year={comp_year} | {start_date} → {end_date}")
    test_remaining = test_limit

    try:
            # ── Section loop ───────────────────────────────────
            for value in Config.section_values:

                try:
                    await page.goto("https://www.usef.org/compete/rankings-results")
                    logger.info("Navigating to Compete Ranking Results")
                    await page.wait_for_selector(
                        "xpath=//h2[contains(.,'Rankings & Results')]"
                    )
                except Exception as e:
                    logger.error(f"Failed to navigate to Rankings & Results for section '{value}': {e}")
                    continue

                try:
                    await page.select_option("select#CompYear", value=str(comp_year))
                    logger.info(f"Competition Year: {comp_year}")
                    await asyncio.sleep(1.5)

                    await page.select_option(
                        "select#StandingTypeDisplay",
                        label="National Points"
                    )
                    await asyncio.sleep(1.5)

                    await page.select_option(
                        "select#Category",
                        label="Hunter - Channel 1"
                    )
                    await asyncio.sleep(1.5)

                    logger.info(f"SectionUID: {value}")

                    option = page.locator(
                        f"xpath=//select[@id='SectionUID']/option[contains(text(), '{value}')]"
                    )
                    option_value = await option.get_attribute("value")
                    await page.select_option("select#SectionUID", value=option_value)

                    selected_value_ele = page.locator(
                        "xpath=//select[@id='SectionUID']//option[@selected='selected']"
                    )
                    selected_value = await selected_value_ele.inner_text()
                    logger.info(f"Section: {selected_value}")

                except Exception as e:
                    logger.error(f"Failed to configure filters for section '{value}': {e}")
                    continue

                # ── Pagination & horse collection ──────────────
                all_horses = []

                while True:

                    try:
                        anchors = await page.locator(
                            "xpath=//div[@class='tbody']//summary[@class='tr']/div[2]/div/a[1]"
                        ).all()
                        logger.info(f"{len(anchors)} anchors found on page")

                        for anchor in anchors:
                            try:
                                horse_name = await anchor.inner_text()
                                horse_link = await anchor.get_attribute("href")

                                if not horse_link:
                                    continue

                                parsed = urlparse(horse_link)
                                horse_id = parsed.path.rstrip("/").split("/")[-1]

                                all_horses.append({
                                    "competition_year": comp_year,
                                    "horse_name": horse_name,
                                    "horse_id": horse_id,
                                    "horse_link": horse_link,
                                    "section": selected_value
                                })

                            except Exception as e:
                                logger.warning(f"Skipping anchor due to error: {e}")
                                continue

                    except Exception as e:
                        logger.error(f"Failed to collect anchors on page: {e}")
                        break

                    try:
                        next_button = page.locator(
                            "xpath=//div[@class='btn-group']//a[@class='btn btn-primary']/following-sibling::a[1]"
                        )
                        if await next_button.is_visible():
                            await next_button.click()
                            await asyncio.sleep(1)
                            logger.info("Next page clicked")
                        else:
                            logger.info("No next page")
                            break

                    except Exception as e:
                        logger.warning(f"Pagination error, stopping: {e}")
                        break

                total = len(all_horses)

                if test_remaining is not None:
                    all_horses = all_horses[:test_remaining]
                    logger.info(f"🧪 Test mode: {len(all_horses)} records in this section (global cap {test_limit})")
                logger.info(f"Total anchors collected: {len(all_horses)}")

                # ── Concurrent PDF processing ──────────────────
                semaphore = asyncio.Semaphore(3)

                async def worker(horse_info, idx):
                    async with semaphore:
                        try:
                            await process_horse(
                                context,
                                horse_info,
                                start_date,
                                end_date,
                                idx,
                                total
                            )
                        except Exception as e:
                            logger.error(
                                f"Unhandled error in worker for horse "
                                f"'{horse_info.get('horse_id')}': {e}"
                            )

                tasks = [
                    worker(horse_info, idx)
                    for idx, horse_info in enumerate(all_horses, start=1)
                ]

                try:
                    await asyncio.gather(*tasks)
                except Exception as e:
                    logger.error(f"asyncio.gather failed for section '{value}': {e}")

                # ── Flush to DB after each section, then clear buffer ──
                logger.info(f"Section '{selected_value}' done — flushing {len(Extracted_Data)} records to DB")
                save_to_jsonl()
                upload_to_supabase()
                Extracted_Data.clear()
                logger.info("Buffer cleared — moving to next section")

                if test_remaining is not None:
                    test_remaining -= len(all_horses)
                    if test_remaining <= 0:
                        logger.info("🧪 Test limit reached — stopping early")
                        break

    except Exception as e:
        logger.error(f"Fatal error in scrape(): {e}")
        notify_failure("scrape() — fatal error", str(e))

    finally:
        # Safety net: flush anything left if we exited mid-section
        if Extracted_Data:
            logger.info(f"Flushing {len(Extracted_Data)} remaining records in finally block")
            save_to_jsonl()
            upload_to_supabase()
        print_section_summary()
        logger.success("All sections processed and uploaded")
        logger.info(
            f"RUN TOTALS → Scraped: {RUN_STATS['scraped']} | "
            f"Duplicates: {RUN_STATS['duplicates']} | "
            f"Inserted: {RUN_STATS['inserted']}"
        )

    return RUN_STATS.copy()
