import asyncio
import argparse
import shutil
from pathlib import Path
from core.scraper import scrape, create_browser_session, close_browser_session
from core.notifier import notify_failure, notify_summary


PRESETS = [
    {"event": "new_event", "start_date": "3/31/2026", "end_date": "3/30/2027", "comp_year": "2026"},
    {"event": "new_event_1", "start_date": "9/1/2025", "end_date": "8/31/2026", "comp_year": "2025"},
    {"event": "new_event_2", "start_date": "9/1/2025", "end_date": "8/31/2026", "comp_year": "2026"},
]


def cleanup_downloads():
    pdf_dir = Path("pdfs")

    if pdf_dir.exists():
        shutil.rmtree(pdf_dir)
        print("🧹 Download folder cleaned")
    else:
        print("ℹ️ No pdf folder found")


async def run_jobs(jobs, limit=None):

    event_stats = []  # per-event breakdown for summary email

    # Login once — reuse session across all presets
    session = await create_browser_session()
    if not session:
        print("❌ Could not start browser session — aborting")
        return event_stats

    _, _, context, page = session

    try:
        for job in jobs:
            print(
                f"🚀 Running {job['event']} | {job['start_date']} → {job['end_date']} | year={job['comp_year']}"
                + (f" | 🧪 LIMIT: {limit} records" if limit else "")
            )

            stats = await scrape(
                job["start_date"],
                job["end_date"],
                job["comp_year"],
                context=context,
                page=page,
                test_limit=limit,
            ) or {}

            event_stats.append({
                "comp_year":  stats.get("comp_year",  job["comp_year"]),
                "start_date": stats.get("start_date", job["start_date"]),
                "end_date":   stats.get("end_date",   job["end_date"]),
                "scraped":    stats.get("scraped",    0),
                "duplicates": stats.get("duplicates", 0),
                "inserted":   stats.get("inserted",   0),
            })
            print("✅ Finished\n")

    finally:
        await close_browser_session(session)

    return event_stats


def filter_jobs(event=None):

    if not event:
        return PRESETS

    return [job for job in PRESETS if job["event"] == event]


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--event", choices=["devon", "indoors"])
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--comp-year", default="2026")
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send a test failure + summary email to verify credentials",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=None,
        metavar="N",
        help="Scrape only N records in total across all sections (e.g. --n 10)",
    )

    args = parser.parse_args()

    if args.test_email:
        print("Sending test failure email...")
        notify_failure("Test — manual trigger", "This is a test error message")
        print("Sending test summary email...")
        from datetime import date
        notify_summary(
            events=[
                {"comp_year": 2026, "start_date": "2026-03-31", "end_date": "2027-03-30",
                 "scraped": 5484, "duplicates": 312, "inserted": 5172},
                {"comp_year": 2025, "start_date": "2025-09-01", "end_date": "2026-08-31",
                 "scraped": 3200, "duplicates": 100, "inserted": 3100},
            ],
            run_date=date.today().isoformat(),
        )
        print("Done — check your inbox")
        return

    if args.cleanup and not args.start_date and not args.event:
        cleanup_downloads()
        return

    # manual run
    if args.start_date and args.end_date:
        jobs = [{
            "event": "manual",
            "start_date": args.start_date,
            "end_date": args.end_date,
            "comp_year": args.comp_year
        }]
    else:
        jobs = filter_jobs(args.event)

    from datetime import date
    event_stats = asyncio.run(run_jobs(jobs, limit=args.n))

    # Send one summary email after all events complete
    notify_summary(
        events=event_stats,
        run_date=date.today().isoformat(),
    )

    if args.cleanup:
        cleanup_downloads()


if __name__ == "__main__":
    main()
