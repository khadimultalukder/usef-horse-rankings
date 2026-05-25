# USEF Horse Rankings Scraper

Automated scraper for USEF National Points standings. Logs into usef.org, collects horse rankings by section, downloads and parses PDF reports, saves a JSONL backup, and upserts the results directly into a Supabase database.

---

## Project Structure

```
usef-horse-rankings/
├── run.py                  # CLI entry point
├── requirements.txt
├── .env                    # credentials (not committed)
├── output/                 # JSONL backups (auto-created)
│   ├── 2026-05-25.jsonl
│   └── 2026-05-26.jsonl
└── core/
    ├── config.py           # USEF credentials, section list, browser settings
    ├── scraper.py          # main scrape loop, JSONL backup + Supabase upload
    ├── downloader.py       # async PDF downloader with retries
    ├── pdf_utils.py        # PDF text extraction (pdfplumber)
    ├── notifier.py         # Gmail email notifications
    ├── logger.py           # coloured console logger
    └── __init__.py
```

---

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
playwright install chromium
```

**2. Create a `.env` file**

```env
USEF_USERNAME=your_usef_email
USEF_PASSWORD=your_usef_password

SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=your_supabase_anon_or_service_key

# Optional
HEADLESS=True
TIMEOUT=60000

# Email notifications
NOTIFY_EMAIL_FROM=your_gmail@gmail.com
NOTIFY_EMAIL_PASSWORD=your_gmail_app_password
NOTIFY_EMAIL_TO=recipient@email.com
```

**3. Supabase table**

The scraper upserts into a table named `usef_horse_rankings`. Conflict key: `horse_id, section, competition_year, award_category`.

Minimum expected columns:

| Column | Type |
|---|---|
| competition_year | int |
| horse_name | text |
| horse_id | text |
| horse_link | text |
| section | text |
| start_date | date |
| end_date | date |
| pdf_download_link | text |
| award_category | text |
| nat_points_good | numeric |
| show_count | int |
| shows | numeric[] |

---

## Email Notifications (Gmail)

The scraper sends email alerts automatically via Gmail SMTP — no extra libraries needed.

| Event | Email sent |
|---|---|
| Browser launch fails | 🚨 Failure alert with error detail |
| Login fails | 🚨 Failure alert with error detail |
| Fatal crash | 🚨 Failure alert with error detail |
| Run completes | ✅ Summary: horses, records, success/fail counts |

**Setup:**

1. Go to your Google Account → Security → **2-Step Verification** (must be enabled)
2. Then go to **App Passwords** → create a new app password for "Mail"
3. Copy the 16-character password into `.env` as `NOTIFY_EMAIL_PASSWORD`

If email credentials are missing from `.env`, notifications are silently skipped and the scraper runs normally.

**Test your email setup:**
```bash
python run.py --test-email
```

---

## JSONL Backup

Every run automatically saves a local backup to `output/YYYY-MM-DD.jsonl` before uploading to Supabase. Each line is a single JSON record.

```
output/
├── 2026-05-25.jsonl
├── 2026-05-26.jsonl
└── 2026-05-27.jsonl
```

- Backup is written **before** the Supabase upload — data is safe even if the upload fails
- Appends to today's file on re-runs — existing records are never overwritten
- Deduplicates on the same conflict key as Supabase to avoid duplicate lines
- Use these files to re-upload to Supabase or audit historical data at any time

---

## Usage

**Run all presets (full scrape)**
```bash
python run.py
```

**Run a specific preset event**
```bash
python run.py --event new_event
```

**Run a custom date range**
```bash
python run.py --start-date 3/31/2026 --end-date 3/30/2027 --comp-year 2026
```

**Test mode — scrape only 4 records total (for testing)**
```bash
python run.py --test
python run.py --test --start-date 3/31/2026 --end-date 3/30/2027
```

**Test email notifications**
```bash
python run.py --test-email
```

**Clean up downloaded PDFs**
```bash
python run.py --cleanup
```

---

## How It Works

1. Launches a headless Chromium browser via Playwright and logs into usef.org
2. For each section in `Config.section_values`, selects *National Points / Hunter - Channel 1* filters
3. Paginates through all horses and collects horse IDs and links
4. Downloads each horse's PDF report concurrently (5 workers, 3 retries each)
5. Parses the PDF with `pdfplumber` to extract `Channel 1 Report Totals` and per-show point values
6. Saves all records to a JSONL backup file in `output/`
7. Upserts all records to Supabase in batches of 500, deduplicating on the conflict key
8. Deletes each PDF after extraction to save disk space
9. Sends an email summary (or failure alert) on completion

---

## Record Format

```json
{
  "competition_year": 2026,
  "horse_name": "NIGHT WALK",
  "horse_id": "QiPr2SphEJc",
  "horse_link": "https://www.usef.org/search/horses/display/QiPr2SphEJc?year=2026",
  "section": "2401 Small Junior Hunter 15/Under",
  "start_date": "2026-03-31",
  "end_date": "2027-03-30",
  "pdf_download_link": "https://www.usef.org/search/horses/report/QiPr2SphEJc?startDate=3/31/2026&endDate=3/30/2027",
  "award_category": "JUNIOR HUNTER-SMALL 15 & UNDER",
  "nat_points_good": 250.5,
  "show_count": 2,
  "shows": [145.25, 105.25]
}
```
