"""
VPS entry point for the USEF scraper.

main_app.py runs Chrome in normal (non-headless) mode on purpose — USEF's
rankings site appears to fingerprint/block headless Chrome. A VPS has no
real monitor, so instead of switching to --headless we fake a real display
with Xvfb (via pyvirtualdisplay) and run the *exact same* non-headless
driver setup from main_app.py unchanged.

One-time setup on the VPS:
    sudo apt-get update
    sudo apt-get install -y xvfb
    # Chrome/Chromium must also be installed (Selenium Manager needs a
    # real browser binary present, e.g.):
    sudo apt-get install -y chromium-browser   # or google-chrome-stable
    pip install pyvirtualdisplay

Usage — same CLI flags as main_app.py:
    python main_app_vps.py
    python main_app_vps.py --event "event_0"
    python main_app_vps.py --pdf 5
    python3 main_app_vps.py --section "2401 Small Junior Hunter 15/Under" --event "event_1"
"""
from pyvirtualdisplay import Display

from main_app import main

if __name__ == "__main__":
    # visible=False -> Xvfb (no window shown, but Chrome still thinks it's
    # rendering to a real 1920x1080 screen, so no --headless flag needed).
    with Display(visible=False, size=(1920, 1080)):
        main()
