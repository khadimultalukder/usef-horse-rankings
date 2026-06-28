import asyncio
from pathlib import Path

PDF_DIR = Path("pdfs")
PDF_DIR.mkdir(parents=True, exist_ok=True)


async def download_pdf(
    context,
    horse_id,
    start_date,
    end_date,
    retries=5,
    base_delay=2
):

    pdf_url = (
        f"https://www.usef.org/search/horses/report/{horse_id}"
        f"?startDate={start_date}&endDate={end_date}"
    )

    safe_start = start_date.replace("/", "-")
    safe_end = end_date.replace("/", "-")

    file_path = PDF_DIR / f"{horse_id}_{safe_start}_{safe_end}.pdf"

    # Return cached file if already downloaded
    if file_path.exists() and file_path.stat().st_size > 1024:
        return file_path

    attempt = 0

    while attempt < retries:

        try:
            response = await context.request.get(
                pdf_url,
                timeout=60000  # 60s timeout per request
            )

            if response.status == 200:
                content = await response.body()

                # Validate it is actually a PDF
                if len(content) > 1024 and content[:5] == b"%PDF-":
                    file_path.write_bytes(content)
                    return file_path
                else:
                    print(
                        f"⚠️ Attempt {attempt + 1}/{retries} — invalid PDF body "
                        f"(size={len(content)}) → {horse_id}"
                    )

            elif response.status == 429:
                # Rate limited — wait longer before retrying
                delay = base_delay * (2 ** attempt) + 10
                print(f"🚦 Rate limited (429). Waiting {delay}s → {horse_id}")
                await asyncio.sleep(delay)
                attempt += 1
                continue

            else:
                print(
                    f"⚠️ Attempt {attempt + 1}/{retries} failed "
                    f"(Status: {response.status}) → {horse_id}"
                )

        except asyncio.TimeoutError:
            print(f"⏱️ Attempt {attempt + 1}/{retries} timed out → {horse_id}")

        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1}/{retries} error → {horse_id} | {e}")

        attempt += 1

        if attempt < retries:
            delay = base_delay * (2 ** (attempt - 1))  # 3s, 6s, 12s, 24s
            print(f"⏳ Retrying in {delay}s... ({attempt}/{retries})")
            await asyncio.sleep(delay)

    print(f"❌ Failed after {retries} attempts → {horse_id}")
    return None
