# USEF Horse Rankings Dashboard

A Streamlit dashboard for the `usef_horse_rankings` Supabase table.

## Features
- Autocomplete horse-name picker + free-text search (name or ID)
- Filters: season (competition year), section, award category, minimum points
- Sortable data table with clickable USEF page / PDF links
- Click any row to highlight it and view full details
- CSV export of the filtered results
- Summary KPIs

---

## Run locally

1. Make sure your `.env` (already in this folder) has:
   ```
   SUPABASE_URL=https://...supabase.co
   SUPABASE_KEY=...
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the dashboard:
   ```bash
   streamlit run app.py
   ```

The app opens at http://localhost:8501.

---

## Deploy to Streamlit Community Cloud

### 1. Push the project to GitHub
From inside this folder:
```bash
git init
git add app.py requirements.txt README.md .gitignore .streamlit/config.toml
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

> ⚠️ `.gitignore` already excludes `.env` and `.streamlit/secrets.toml`, so credentials will **not** be pushed.

### 2. Create the app
1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **"New app"** → pick your repo, branch (`main`), and main file (`app.py`).
3. Click **"Advanced settings"** → set Python version to **3.11** (recommended).

### 3. Add your secrets
Still in the **Advanced settings** dialog (or later under **App settings → Secrets**), paste:
```toml
SUPABASE_URL = "https://xlfgcavttyzqzzddvuyq.supabase.co"
SUPABASE_KEY = "your_supabase_anon_or_publishable_key_here"
```
The app reads `st.secrets` automatically — no code changes needed.

### 4. Deploy
Click **"Deploy"**. First boot takes ~2 minutes while Streamlit installs dependencies.

### Updating
Every `git push` to `main` auto-redeploys the app.

---

## Notes
- Data is cached for 5 minutes. Use the **"Refresh data from Supabase"** sidebar button to force a reload.
- The loader paginates 500 rows at a time with retries to handle flaky HTTP/2 connections on large tables.
- Local: credentials come from `.env`. Cloud: credentials come from `st.secrets`. The same `app.py` works in both environments.
