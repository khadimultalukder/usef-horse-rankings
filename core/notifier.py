import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
EMAIL_FROM    = os.getenv("NOTIFY_EMAIL_FROM")   # your Gmail address
EMAIL_PASSWORD = os.getenv("NOTIFY_EMAIL_PASSWORD")  # Gmail app password
EMAIL_TO      = os.getenv("NOTIFY_EMAIL_TO")     # recipient email


def _send(subject: str, body: str):
    """Send an email notification. Silently skips if credentials are missing."""
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
    """Call this when a critical failure occurs."""
    subject = "🚨 USEF Scraper — FAILURE"
    body = (
        "USEF Scraper encountered a critical error and stopped.\n\n"
        f"Where : {context}\n"
        f"Error : {error}\n\n"
        "Please check the logs for more details."
    )
    _send(subject, body)


def notify_summary(
    total_records: int,
    section_stats: dict,
    start_date: str,
    end_date: str,
    comp_year,
):
    """Call this at the end of a scrape run with a full summary."""
    total_horses  = sum(s["total"]   for s in section_stats.values())
    total_success = sum(s["success"] for s in section_stats.values())
    total_failed  = sum(s["failed"]  for s in section_stats.values())

    subject = "✅ USEF Scraper — Run Complete"

    lines = [
        "USEF Scraper finished successfully.\n",
        f"Period  : {start_date} → {end_date}",
        f"Year    : {comp_year}",
        f"Horses  : {total_horses}",
        f"Records : {total_records}",
        f"Success : {total_success}",
        f"Failed  : {total_failed}",
    ]

    if total_failed:
        failed_sections = [s for s, v in section_stats.items() if v["failed"] > 0]
        lines.append("\nFailed sections:")
        lines += [f"  - {s}" for s in failed_sections]

    lines.append("\nThis is an automated message from the USEF scraper.")

    _send(subject, "\n".join(lines))
