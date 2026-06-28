# config.py

import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    START_URL = "https://www.usef.org/log-in"

    USERNAME = os.getenv("USEF_USERNAME")
    PASSWORD = os.getenv("USEF_PASSWORD")

    HEADLESS = os.getenv("HEADLESS", "True") == "True"
    TIMEOUT = int(os.getenv("TIMEOUT", 60000))

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    VIEWPORT = {"width": 1280, "height": 900}

    # # Example list of SectionUID values
    section_values = [
        "2401",
        "2402",
        "2403",
        "2404",
        "2421",
        "2422",
        "2423",
        "2424",
        "2501",
        "2502",
        "2503",
    ]

