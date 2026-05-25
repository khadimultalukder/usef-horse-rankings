import pdfplumber
import re
import csv
import os
from collections import defaultdict
from pdfplumber.utils.exceptions import PdfminerException

MIN_PDF_SIZE = 1024


def is_valid_pdf(pdf_path) -> bool:
    try:
        if os.path.getsize(pdf_path) < MIN_PDF_SIZE:
            return False
        with open(pdf_path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except Exception:
        return False


def process_pdf(pdf_path):
    if not is_valid_pdf(pdf_path):
        print(f"[WARN] Skipping invalid/corrupt PDF: {pdf_path}")
        return [], {}

    full_text = ""
    section_totals = defaultdict(list)
    current_section = None

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text()
                    if not text:
                        continue
                    full_text += text + "\n"

                    for line in text.split("\n"):
                        line = line.strip()

                        if line.startswith("SECTION:"):
                            current_section = line.replace("SECTION:", "").strip()

                        elif line.startswith("TOTALS:") and current_section:
                            match = re.search(
                                r"TOTALS:\s+[\d.]+\s+([\d.]+)\s*/", line
                            )
                            if match:
                                section_totals[current_section].append(match.group(1))

                except Exception as e:
                    print(f"[WARN] Page error in {pdf_path}: {e}")

    except (PdfminerException, Exception) as e:
        print(f"[WARN] Could not open {pdf_path}: {e}")
        return [], {}

    # ── Parse Channel 1 Report Totals ────────────────────────────────────
    channel1 = {}

    if "Channel 1 Report Totals" in full_text:
        block = full_text.split("Channel 1 Report Totals", 1)[1]

        for stopper in ["Channel 2 Report Totals", "Printed on"]:
            if stopper in block:
                block = block.split(stopper, 1)[0]

        for line in block.split("\n"):
            line = line.strip()
            if not line or "AWARD CATEGORY" in line:
                continue

            m = re.match(
                r"^(.+?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$",
                line
            )
            if m:
                channel1[m.group(1).strip()] = m.group(2)

    return section_totals, channel1


# ── Main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    pdf_path   = "UkVmNv13qPg.pdf"
    output_csv = "grouped_section_totals.csv"

    section_totals, channel1 = process_pdf(pdf_path)

    if not section_totals:
        print("No TOTALS data found.")
    else:
        max_len = max(len(v) for v in section_totals.values())
        fieldnames = (
            ["award_category", "nat_points_good", "Show_Count"]
            + [f"Show{i+1}" for i in range(max_len)]
        )

        rows = []
        for section, values in section_totals.items():
            row = {
                "award_category":  section,
                "nat_points_good": channel1.get(section, ""),
                "Show_Count":      len(values),
            }
            for i in range(max_len):
                row[f"Show{i+1}"] = values[i] if i < len(values) else ""
            rows.append(row)

        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print("── Channel 1 NAT POINTS GOOD ──")
        for cat, val in channel1.items():
            print(f"  {cat:<35} {val}")
        print(f"\n✅ Saved to {output_csv}")