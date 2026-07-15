# VPS Deployment Guide — USEF Horse Rankings

Fresh VPS (Ubuntu/Debian assumed) → running scraper + dashboard. Repo: `https://github.com/khadimultalukder/usef-horse-rankings.git`

## 0. Log in and update the box

```bash
ssh root@your.vps.ip
apt update && apt upgrade -y
```

(Optional but recommended: create a non-root user — `adduser deploy && usermod -aG sudo deploy` — and do the rest as that user.)

## 1. Install system packages

```bash
sudo apt install -y python3 python3-venv python3-pip git xvfb wget curl unzip
```

**Google Chrome** (the scraper's user-agent/driver setup expects real Chrome, not just Chromium):

```bash
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable
```

Selenium 4.6+ auto-downloads the matching chromedriver at runtime (Selenium Manager) — no manual chromedriver install needed.

## 2. Clone the repo

```bash
git clone https://github.com/khadimultalukder/usef-horse-rankings.git
cd usef-horse-rankings
```

## 3. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Create the `.env` file (not in git, must be made by hand)

```bash
nano .env
```

```env
USEF_USERNAME=your_usef_login
USEF_PASSWORD=your_usef_password
SUPABASE_URL=https://xlfgcavttyzqzzddvuyq.supabase.co
SUPABASE_KEY=your_supabase_service_key
```

This single root `.env` is picked up by both `usef_scraper_seleninum/main_app.py` and `dashboard_app/dashboard_app.py` automatically (they resolve the path relative to their own file location).

## 5. Test run (scraper)

```bash
cd usef_scraper_seleninum
python3 main_app_vps.py --pdf 1
```

`main_app_vps.py` starts Xvfb (virtual display) itself via `pyvirtualdisplay`, then runs the same non-headless Chrome driver as local — no code differs between local/VPS besides this wrapper. If this finishes and prints `🎉 Scraping done!`, the setup is good.

## 6. Run the full scraper

```bash
python3 main_app_vps.py
```

Same flags as local: `--event`, `--section`, `--pdf`.

### Automate with cron

```bash
crontab -e
```

Add (example: every day at 3am, logging output):

```
0 3 * * * cd /home/deploy/usef-horse-rankings/usef_scraper_seleninum && /home/deploy/usef-horse-rankings/venv/bin/python3 main_app_vps.py >> /home/deploy/usef-horse-rankings/scraper.log 2>&1
```

Use full absolute paths in cron — it doesn't load your shell profile or venv activation.

## 7. (Optional) Run the dashboard on the same VPS

```bash
cd ~/usef-horse-rankings/dashboard_app
../venv/bin/streamlit run dashboard_app.py --server.port 8501 --server.address 0.0.0.0
```

Keep it alive after logout with a systemd service:

```bash
sudo nano /etc/systemd/system/usef-dashboard.service
```

```ini
[Unit]
Description=USEF Dashboard
After=network.target

[Service]
User=deploy
WorkingDirectory=/home/deploy/usef-horse-rankings/dashboard_app
ExecStart=/home/deploy/usef-horse-rankings/venv/bin/streamlit run dashboard_app.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now usef-dashboard
```

Open `http://your.vps.ip:8501` (open port 8501 in the firewall: `sudo ufw allow 8501`), or put Nginx in front for a domain + HTTPS.

Alternative: skip all this and just deploy the dashboard on **Streamlit Community Cloud** instead (already documented in `dashboard_app/README.md`) — no VPS resources used for it.

## Troubleshooting

- `selenium.common.exceptions.WebDriverException: unknown error: cannot find Chrome binary` → Chrome isn't installed or not on PATH; re-check step 1.
- Xvfb/display errors → confirm `xvfb` package installed (step 1); `main_app_vps.py` handles starting/stopping it, don't run a separate `Xvfb :99 &` manually.
- Script hangs / gets blocked by USEF → the site fingerprints headless browsers; this setup deliberately avoids `--headless`, so if it's still blocked, check the VPS's IP isn't already flagged (some hosting IP ranges get blocked by target sites).
- Cron job runs nothing → almost always a hardcoded path issue; test the exact cron command manually first.
