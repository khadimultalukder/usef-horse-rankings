import asyncio
import argparse
import shutil
from pathlib import Path
from core.scraper import scrape
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

    for job in jobs:

        print(
            f"🚀 Running {job['event']} | {job['start_date']} → {job['end_date']} | year={job['comp_year']}"
            + (f" | 🧪 LIMIT: {limit} records" if limit else "")
        )

        await scrape(
            job["start_date"],
            job["end_date"],
            job["comp_year"],
            test_limit=limit,
        )

        print("✅ Finished\n")


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
        notify_summary(
            total_records=42,
            section_stats={"2401 Small Junior Hunter": {"total": 20, "success": 18, "failed": 2}},
            start_date="3/31/2026",
            end_date="3/30/2027",
            comp_year=2026,
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

    asyncio.run(run_jobs(jobs, limit=args.n))

    if args.cleanup:
        cleanup_downloads()


if __name__ == "__main__":
    main()
