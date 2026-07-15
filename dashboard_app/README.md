# 🐎 USEF Horse Rankings — Dashboard & Data Freshness System

A Streamlit dashboard for the `usef_horse_rankings` table in Supabase, with a built-in **stale-data flagging system** and a **scrape status banner** so the client always knows how fresh the data is.

---

## 📋 Overview

The scraper runs section-by-section and a full pass can take **3–5 days** (slow site + anti-bot protection). Because rows are **upserted**, entries that disappear from the USEF site are never deleted — they just stop getting updated. This system solves two problems:

1. **Stale rows** — rows not found in the latest scrape are flagged in a `remark` column instead of being deleted.
2. **Run status** — a tiny `scrape_status` table tells the dashboard whether a scrape is *in progress* or *completed*, and when the last full run finished. This prevents the client from mistaking a half-finished run for fresh data.

Both are managed **manually via SQL** — the scraper script needs no changes and never touches the `remark` column.

---

## 🗂️ Project Structure

```
project/
├── dashboard_app.py      # Streamlit dashboard
├── .env                  # SUPABASE_URL + SUPABASE_KEY (local dev)
└── README.md             # This file
```

**Supabase tables:**

| Table | Purpose |
|---|---|
| `usef_horse_rankings` | Main data table (upserted by the scraper) |
| `scrape_status` | Single-row table tracking run status & last completion time |

---

## ⚙️ Setup

### 1. Install dependencies

```bash
pip install streamlit supabase pandas python-dotenv httpx
```

### 2. Environment variables

Create a `.env` file one level above `dashboard_app.py` (or add these under **App Settings → Secrets** on Streamlit Cloud):

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-or-service-role-key
```

### 3. One-time SQL setup

Run once in the Supabase SQL Editor:

```sql
-- Remark column on the main table
ALTER TABLE usef_horse_rankings
ADD COLUMN IF NOT EXISTS remark TEXT DEFAULT NULL;

-- Single-row status table
CREATE TABLE IF NOT EXISTS scrape_status (
    id INT PRIMARY KEY DEFAULT 1,
    last_completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'completed',
    CONSTRAINT single_row CHECK (id = 1)
);

INSERT INTO scrape_status (id, last_completed_at, status)
VALUES (1, NOW(), 'completed')
ON CONFLICT (id) DO NOTHING;
```

> **RLS note:** If Row Level Security is enabled and the dashboard uses the `anon` key, add a read policy:
>
> ```sql
> ALTER TABLE scrape_status ENABLE ROW LEVEL SECURITY;
> CREATE POLICY "Allow read access" ON scrape_status FOR SELECT USING (true);
> ```

### 4. Run the dashboard

```bash
streamlit run dashboard_app.py
```

---

## 🔄 Scrape Workflow (manual SQL)

Save these as named queries in the Supabase SQL Editor and run them at the right moment.

### ▶️ Before starting a scrape run — `Pre-Scrape Status`

```sql
UPDATE scrape_status
SET status = 'in_progress'
WHERE id = 1;
```

The dashboard will show a yellow banner:
> 🔄 Scraping status: **In Progress** — showing data from last complete update: **June 14, 2026**

### ✅ After the run fully completes — `Post-Scrape Cleanup`

> ⚠️ **Change the cutoff date first** — it must be the **start date of the run you just finished**.

```sql
-- 1) Flag stale rows / clear remarks on fresh rows
UPDATE usef_horse_rankings
SET remark = CASE
    WHEN scraped_at::date < '2026-06-28'  -- ⬅️ change to this run's start date
        THEN 'Stale - not found in latest scrape'
    ELSE NULL
END;

-- 2) Mark the run as completed
UPDATE scrape_status
SET last_completed_at = NOW(), status = 'completed'
WHERE id = 1;
```

The dashboard will show a green banner:
> ✅ Scraping status: **Completed** — Last updated: **July 02, 2026** (2 days ago)

### 🔍 Sanity check — `Verify Status`

```sql
SELECT remark, COUNT(*) AS total
FROM usef_horse_rankings
GROUP BY remark;

SELECT * FROM scrape_status;
```

Expected: one `NULL` group (fresh rows) and one `Stale - not found in latest scrape` group.

---

## 🧠 How the Stale Logic Works

| Situation | `scraped_at` after upsert | Remark after cleanup query |
|---|---|---|
| Found in this run | New (≥ cutoff) | `NULL` (fresh) |
| Was stale, came back | New (upsert refreshed it) | `NULL` — stale flag cleared automatically |
| Not found in this run | Old (< cutoff) | `Stale - not found in latest scrape` |

Key points:

- The `CASE` query rewrites **every** row's remark, so it also normalizes any empty-string (`''`) values back to `NULL` — no `IS NULL` vs `EMPTY` bugs.
- Because the cutoff date is chosen **manually** after checking the data, multi-day runs (3–5 days) and long gaps between runs (e.g. 2 months) are both safe.
- The scraper never sends the `remark` field, so upserts can't accidentally overwrite flags mid-run.

Helper query to find the run's start date:

```sql
SELECT scraped_at::date AS scrape_date, COUNT(*) AS total_rows
FROM usef_horse_rankings
GROUP BY scrape_date
ORDER BY scrape_date DESC;
```

---

## 📊 Dashboard Features

- **Scraping status banner** — green (Completed + last update date + days ago) or yellow (In Progress, showing last complete run's date)
- **Search** — horse name autocomplete + free-text search by name or ID
- **Filters** — season (year), section, award category, exact start/end date
- **Top 15 toggle** — recalculates national points from the top 15 highest-scoring shows (changed values highlighted in red)
- **Missing remark toggle** — show only fresh rows (`remark IS NULL`)
- **Stale row highlighting** — rows with a remark are tinted amber in the results table
- **Imported Today KPI** — click to filter to rows scraped today
- **Row details panel** — grouped fields, show-score chips, USEF page / PDF links
- **CSV export** — reflects the current filtered view with friendly headers
- **Refresh button** — clears both the data cache (5 min TTL) and status cache (30 min TTL)

---

## 🧾 Quick Reference

| When | Query | What it does |
|---|---|---|
| Before a run | `Pre-Scrape Status` | Banner → 🔄 In Progress |
| After a run | `Post-Scrape Cleanup` | Flags stale rows + banner → ✅ Completed |
| Anytime | `Verify Status` | Check remark counts & status row |

**Remember:** the only thing you ever edit is the **cutoff date** in `Post-Scrape Cleanup`.
