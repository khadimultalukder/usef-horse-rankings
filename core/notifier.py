import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
EMAIL_FROM     = os.getenv("NOTIFY_EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("NOTIFY_EMAIL_PASSWORD")
EMAIL_TO       = os.getenv("NOTIFY_EMAIL_TO")


def _send(subject: str, body: str):
    if not all([EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO]):
        print("[Notifier] Email credentials not set — skipping notification")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())

        print(f"[Notifier] Email sent → {EMAIL_TO}")
    except Exception as e:
        print(f"[Notifier] Failed to send email: {e}")


def notify_failure(context: str, error: str):
    subject = "🚨 USEF Scraper — FAILURE"
    body = (
        "USEF Scraper encountered a critical error and stopped.\n\n"
        f"Where : {context}\n"
        f"Error : {error}\n\n"
        "Please check the logs for more details."
    )
    _send(subject, body)


def notify_summary(events: list, run_date: str):
    """
    Send one summary email after ALL events complete.

    Each item in `events` must have:
        comp_year, start_date, end_date, scraped, duplicates, inserted
    """
    subject = "✅ USEF Scraper — All Events Complete"

    # Build per-event table
    col_w = [4, 6, 12, 12, 10, 10, 10]
    header = (
        f"{'#':<{col_w[0]}}  "
        f"{'Year':<{col_w[1]}}  "
        f"{'Start Date':<{col_w[2]}}  "
        f"{'End Date':<{col_w[3]}}  "
        f"{'Scraped':>{col_w[4]}}  "
        f"{'Dupes':>{col_w[5]}}  "
        f"{'Exported':>{col_w[6]}}"
    )
    sep = "─" * len(header)

    rows = []
    total_scraped = total_dupes = total_inserted = 0

    for i, ev in enumerate(events, 1):
        total_scraped   += ev.get("scraped", 0)
        total_dupes     += ev.get("duplicates", 0)
        total_inserted  += ev.get("inserted", 0)

        rows.append(
            f"{i:<{col_w[0]}}  "
            f"{str(ev.get('comp_year','')):<{col_w[1]}}  "
            f"{str(ev.get('start_date','')):<{col_w[2]}}  "
            f"{str(ev.get('end_date','')):<{col_w[3]}}  "
            f"{ev.get('scraped', 0):>{col_w[4]}}  "
            f"{ev.get('duplicates', 0):>{col_w[5]}}  "
            f"{ev.get('inserted', 0):>{col_w[6]}}"
        )

    footer = (
        f"\n{'TOTAL':<{col_w[0]+col_w[1]+col_w[2]+col_w[3]+8}}"
        f"  {total_scraped:>{col_w[4]}}  {total_dupes:>{col_w[5]}}  {total_inserted:>{col_w[6]}}"
    )

    table = "\n".join([sep, header, sep] + rows + [sep, footer])

    body = (
        f"USEF Scraper finished all events successfully.\n\n"
        f"Run Date : {run_date}\n\n"
        f"{table}\n\n"
        "This is an automated message from the USEF scraper."
    )
    _send(subject, body)
