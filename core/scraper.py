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
CONFLICT_COLS = "horse_id,section,competition_year,award_category"

Extracted_Data = []

SECTION_STATS = defaultdict(lambda: {
    "total": 0,
    "success": 0,
    "failed": 0
})

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
        section_totals, channel1 = process_pdf(file_path)
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
    """Keep only the LAST occurrence of each (horse_id, section, year, award_category) tuple.
    Prevents 'ON CONFLICT cannot affect row a second time' errors."""
    seen = {}
    for row in rows:
        key = (
            row["horse_id"],
            row["section"],
            row["competition_year"],
            row["award_category"],
        )
        seen[key] = row
    return list(seen.values())


def upload_to_supabase():

    if not Extracted_Data:
        logger.warning("No data to upload")
        return

    rows = [transform_record(r) for r in Extracted_Data]

    deduped = dedupe_on_conflict_key(rows)
    if len(deduped) < len(rows):
        logger.info(f"Removed {len(rows) - len(deduped)} duplicate-key rows (kept latest)")
    rows = deduped

    total = len(rows)
    inserted = 0
    failed_batches = []

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        try:
            supabase.table(TABLE_NAME).upsert(
                batch, on_conflict=CONFLICT_COLS
            ).execute()
            inserted += len(batch)
            logger.success(f"Batch {i // BATCH_SIZE + 1}: {inserted}/{total} rows uploaded")
        except Exception as e:
            logger.error(f"Batch {i // BATCH_SIZE + 1} failed: {e}")
            failed_batches.append((i, i + BATCH_SIZE))

    logger.success(f"Done. Upserted {inserted}/{total} rows to '{TABLE_NAME}'")
    if failed_batches:
        logger.warning(f"Failed batch ranges: {failed_batches}")


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
# MAIN SCRAPER
# ===============================================

async def scrape(start_date, end_date, comp_year, test_limit=None):

    logger.info("Script started")
    test_remaining = test_limit  # global PDF counter across all sections

    try:
        async with async_playwright() as p:

            try:
                browser = await p.chromium.launch(
                    headless=Config.HEADLESS,
                    args=["--no-sandbox"]
                )
            except Exception as e:
                logger.error(f"Failed to launch browser: {e}")
                notify_failure("Browser launch", str(e))
                return

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
                return

            # ── Login ──────────────────────────────────────────
            try:
                logger.info(f"Opening: {Config.START_URL}")
                await page.goto(Config.START_URL)

                # accept cookies
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
                    pass  # cookie banner is optional

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
                return

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
                    await asyncio.sleep(1)

                    await page.select_option(
                        "select#StandingTypeDisplay",
                        label="National Points"
                    )
                    await asyncio.sleep(1)

                    await page.select_option(
                        "select#Category",
                        label="Hunter - Channel 1"
                    )
                    await asyncio.sleep(1)

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
                            await asyncio.sleep(2)
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
                semaphore = asyncio.Semaphore(5)

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

                if test_remaining is not None:
                    test_remaining -= len(all_horses)
                    if test_remaining <= 0:
                        logger.info("🧪 Test limit reached — stopping early")
                        break

            await browser.close()

    except Exception as e:
        logger.error(f"Fatal error in scrape(): {e}")
        notify_failure("scrape() — fatal error", str(e))

    finally:
        save_to_jsonl()
        upload_to_supabase()
        print_section_summary()
        logger.success(f"Total Records Processed: {len(Extracted_Data)}")
        notify_summary(
            total_records=len(Extracted_Data),
            section_stats=SECTION_STATS,
            start_date=start_date,
            end_date=end_date,
            comp_year=comp_year,
        )
