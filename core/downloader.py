import asyncio
from pathlib import Path

PDF_DIR = Path("pdfs")
PDF_DIR.mkdir(parents=True, exist_ok=True)


async def download_pdf(
    context,
    horse_id,
    start_date,
    end_date,
    retries=3,
    base_delay=2
):

    pdf_url = (
        f"https://www.usef.org/search/horses/report/{horse_id}"
        f"?startDate={start_date}&endDate={end_date}"
    )

    safe_start = start_date.replace("/", "-")
    safe_end = end_date.replace("/", "-")

    file_path = PDF_DIR / f"{horse_id}_{safe_start}_{safe_end}.pdf"

    attempt = 0

    while attempt < retries:

        try:

            response = await context.request.get(pdf_url)

            if response.status == 200:

                content = await response.body()

                file_path.write_bytes(content)

                return file_path

            else:

                print(
                    f"⚠️ Attempt {attempt + 1}/{retries} failed "
                    f"(Status: {response.status}) → {horse_id}"
                )

        except Exception as e:

            print(
                f"⚠️ Attempt {attempt + 1}/{retries} error → {horse_id} | {e}"
            )

        attempt += 1

        if attempt < retries:

            delay = base_delay * attempt

            print(f"⏳ Retrying in {delay}s...")

            await asyncio.sleep(delay)

    print(f"❌ Failed after {retries} attempts → {horse_id}")

    return None