"""
USEF Horse Rankings Dashboard
-----------------------------
A Streamlit dashboard for the `usef_horse_rankings` table in Supabase.

Features:
- Search by horse name or horse ID
- Filters: competition year (season), section, award category
- Date range filter (start_date / end_date)
- Top-15 highest-scoring shows toggle
- Sortable data table
- CSV export of filtered results
- Summary KPIs

Run:
    streamlit run app.py
"""

from __future__ import annotations

import os
from typing import List, Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TABLE_NAME = "usef_horse_rankings"
PAGE_SIZE = 500  # Smaller pages reduce risk of HTTP/2 stream resets on big tables
MAX_RETRIES = 4

load_dotenv()

st.set_page_config(
    page_title="USEF Horse Rankings",
    page_icon="🐎",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Custom styles — animated KPI cards, detail card, table row styling
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap');

    /* ---------- Animated KPI cards ---------- */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1rem;
        margin: 0.5rem 0 1.25rem 0;
    }
    @media (max-width: 900px) {
        .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    }
    .kpi-card {
        position: relative;
        padding: 1.1rem 1.25rem 1rem 1.25rem;
        border-radius: 16px;
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(236, 72, 153, 0.06) 100%),
                    rgba(255, 255, 255, 0.6);
        border: 1px solid rgba(148, 163, 184, 0.18);
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.03);
        transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
                    box-shadow 0.28s cubic-bezier(0.4, 0, 0.2, 1),
                    border-color 0.28s ease;
        overflow: hidden;
        animation: kpi-fade-in 0.55s ease-out both;
    }
    @media (prefers-color-scheme: dark) {
        .kpi-card {
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.10) 0%, rgba(236, 72, 153, 0.08) 100%),
                        rgba(30, 41, 59, 0.55);
            border-color: rgba(148, 163, 184, 0.18);
        }
    }
    .kpi-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: var(--accent, linear-gradient(90deg, #6366f1, #a855f7));
        opacity: 0.95;
    }
    .kpi-card::after {
        content: '';
        position: absolute;
        top: -40%; right: -20%;
        width: 160px; height: 160px;
        background: radial-gradient(circle, var(--glow, rgba(99,102,241,0.25)) 0%, transparent 70%);
        filter: blur(20px);
        opacity: 0.6;
        pointer-events: none;
        transition: opacity 0.3s ease;
    }
    .kpi-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 14px 28px rgba(15, 23, 42, 0.12), 0 0 0 1px rgba(99, 102, 241, 0.25);
        border-color: rgba(99, 102, 241, 0.4);
    }
    .kpi-card:hover::after { opacity: 1; }

    .kpi-card.kpi-indigo::before { background: linear-gradient(90deg, #6366f1, #8b5cf6); }
    .kpi-card.kpi-indigo { --glow: rgba(99, 102, 241, 0.30); }
    .kpi-card.kpi-cyan::before   { background: linear-gradient(90deg, #06b6d4, #22d3ee); }
    .kpi-card.kpi-cyan   { --glow: rgba(34, 211, 238, 0.30); }
    .kpi-card.kpi-pink::before   { background: linear-gradient(90deg, #ec4899, #f472b6); }
    .kpi-card.kpi-pink   { --glow: rgba(236, 72, 153, 0.30); }
    .kpi-card.kpi-amber::before  { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
    .kpi-card.kpi-amber  { --glow: rgba(245, 158, 11, 0.30); }

    .kpi-icon {
        font-size: 1.35rem;
        line-height: 1;
        margin-bottom: 0.4rem;
        display: inline-block;
        animation: kpi-icon-pop 0.7s ease-out both;
    }
    .kpi-label {
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748b;
        margin-bottom: 0.3rem;
    }
    .kpi-value {
        font-family: 'Space Grotesk', 'Inter', sans-serif;
        font-size: 1.85rem;
        font-weight: 700;
        line-height: 1.1;
        color: #0f172a;
    }
    @media (prefers-color-scheme: dark) {
        .kpi-value { color: #f8fafc; }
    }
    .kpi-sub {
        font-size: 0.72rem;
        color: #94a3b8;
        margin-top: 0.3rem;
    }

    @keyframes kpi-fade-in {
        from { opacity: 0; transform: translateY(8px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes kpi-icon-pop {
        0%   { opacity: 0; transform: scale(0.6) rotate(-10deg); }
        60%  { opacity: 1; transform: scale(1.15) rotate(4deg); }
        100% { opacity: 1; transform: scale(1) rotate(0); }
    }
    /* Stagger each card */
    .kpi-card:nth-child(1) { animation-delay: 0.00s; }
    .kpi-card:nth-child(2) { animation-delay: 0.08s; }
    .kpi-card:nth-child(3) { animation-delay: 0.16s; }
    .kpi-card:nth-child(4) { animation-delay: 0.24s; }

    /* ---------- Detail card (selected row) ---------- */
    .detail-card {
        padding: 1rem 1.25rem;
        margin: 0.75rem 0 0.25rem 0;
        border-radius: 14px;
        border: 1px solid rgba(168, 85, 247, 0.35);
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.10) 0%, rgba(236, 72, 153, 0.10) 100%);
        animation: kpi-fade-in 0.4s ease-out both;
    }
    .detail-card .detail-title {
        font-family: 'Space Grotesk', 'Inter', sans-serif;
        font-size: 1.1rem;
        font-weight: 700;
        margin: 0 0 0.15rem 0;
    }
    .detail-card .detail-sub {
        font-size: 0.82rem;
        color: #64748b;
    }

    /* ---------- Row details — grouped field grid ---------- */
    .detail-section {
        font-family: 'Space Grotesk', 'Inter', sans-serif;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: #a855f7;
        margin: 1.1rem 0 0.55rem 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .detail-section::before {
        content: '';
        width: 4px;
        height: 14px;
        background: linear-gradient(180deg, #6366f1, #ec4899);
        border-radius: 2px;
    }
    .detail-section .section-line {
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, rgba(168,85,247,0.25), transparent);
    }
    .detail-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 0.6rem;
    }
    .detail-field {
        padding: 0.7rem 0.85rem;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(236, 72, 153, 0.04) 100%),
                    rgba(30, 41, 59, 0.35);
        border: 1px solid rgba(148, 163, 184, 0.14);
        transition: border-color 0.2s ease, transform 0.2s ease;
        animation: kpi-fade-in 0.35s ease-out both;
    }
    @media (prefers-color-scheme: light) {
        .detail-field {
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(236, 72, 153, 0.04) 100%),
                        rgba(255, 255, 255, 0.85);
        }
    }
    .detail-field:hover {
        border-color: rgba(168, 85, 247, 0.45);
        transform: translateY(-1px);
    }
    .detail-field.detail-field--wide { grid-column: 1 / -1; }
    .detail-label {
        font-size: 0.66rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 0.3rem;
    }
    .detail-value {
        font-size: 0.95rem;
        font-weight: 500;
        color: #e2e8f0;
        word-break: break-word;
    }
    @media (prefers-color-scheme: light) {
        .detail-value { color: #0f172a; }
    }
    .detail-value.detail-value--big {
        font-family: 'Space Grotesk', 'Inter', sans-serif;
        font-size: 1.35rem;
        font-weight: 700;
        background: linear-gradient(135deg, #6366f1, #ec4899);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .detail-value.detail-value--muted { color: #94a3b8; font-style: italic; }
    .detail-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
        margin-top: 0.2rem;
    }
    .detail-chip {
        display: inline-flex;
        align-items: center;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        background: linear-gradient(135deg, rgba(99,102,241,0.18), rgba(168,85,247,0.18));
        border: 1px solid rgba(168,85,247,0.35);
        color: #e9d5ff;
        font-size: 0.78rem;
        font-weight: 600;
        font-family: 'Space Grotesk', monospace;
    }
    @media (prefers-color-scheme: light) {
        .detail-chip { color: #6b21a8; }
    }
    .detail-link-btn {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.4rem 0.85rem;
        border-radius: 10px;
        background: linear-gradient(135deg, #6366f1, #a855f7);
        color: white !important;
        font-weight: 600;
        font-size: 0.82rem;
        text-decoration: none !important;
        transition: transform 0.15s ease, box-shadow 0.2s ease;
        box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
    }
    .detail-link-btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 14px rgba(99, 102, 241, 0.45);
    }

    /* ---------- DataFrame row styling ---------- */
    [data-testid="stDataFrame"] {
        border-radius: 14px;
        overflow: hidden;
        border: 1px solid rgba(148, 163, 184, 0.18);
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }
    /* Zebra rows */
    [data-testid="stDataFrame"] [role="row"]:nth-child(even) > [role="gridcell"] {
        background: rgba(99, 102, 241, 0.04) !important;
    }
    /* Hover highlight */
    [data-testid="stDataFrame"] [role="row"]:hover > [role="gridcell"] {
        background: rgba(168, 85, 247, 0.10) !important;
        cursor: pointer;
        transition: background 0.15s ease;
    }
    /* Header */
    [data-testid="stDataFrame"] [role="columnheader"] {
        background: linear-gradient(180deg, rgba(99, 102, 241, 0.10), rgba(99, 102, 241, 0.04)) !important;
        font-weight: 600 !important;
        color: #1e293b !important;
        border-bottom: 1px solid rgba(99, 102, 241, 0.25) !important;
    }
    @media (prefers-color-scheme: dark) {
        [data-testid="stDataFrame"] [role="columnheader"] {
            color: #e2e8f0 !important;
            background: linear-gradient(180deg, rgba(99, 102, 241, 0.18), rgba(99, 102, 241, 0.08)) !important;
        }
        [data-testid="stDataFrame"] [role="row"]:nth-child(even) > [role="gridcell"] {
            background: rgba(99, 102, 241, 0.07) !important;
        }
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------
def _get_secret(name: str) -> Optional[str]:
    """Look in st.secrets (Streamlit Cloud) first, then env vars / .env (local)."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        # st.secrets raises if no secrets file exists; that's fine locally.
        pass
    return os.environ.get(name)


@st.cache_resource(show_spinner=False)
def get_client() -> Client:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    if not url or not key:
        st.error(
            "Missing SUPABASE_URL or SUPABASE_KEY.\n\n"
            "**Local:** add them to a `.env` file in this folder.\n"
            "**Streamlit Cloud:** add them under App Settings → Secrets."
        )
        st.stop()
    return create_client(url, key)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _fetch_page(sb, start: int, end: int):
    """Fetch one page with retry/backoff for transient network errors."""
    import time
    from httpx import RemoteProtocolError, ReadTimeout, ConnectError

    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            return (
                sb.table(TABLE_NAME)
                .select("*")
                .range(start, end)
                .execute()
            )
        except (RemoteProtocolError, ReadTimeout, ConnectError) as e:
            last_err = e
            sleep_s = 1.5 * (2 ** attempt)  # 1.5s, 3s, 6s, 12s
            time.sleep(sleep_s)
    # exhausted retries
    raise last_err  # type: ignore[misc]


@st.cache_data(ttl=300, show_spinner="Loading rankings from Supabase…")
def load_rankings() -> pd.DataFrame:
    """Load all rows from usef_horse_rankings, paginating past the row limit."""
    sb = get_client()
    rows: List[dict] = []
    offset = 0
    while True:
        resp = _fetch_page(sb, offset, offset + PAGE_SIZE - 1)
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Drop the primary-key `id` column from display (still exists in DB)
    if "id" in df.columns:
        df = df.drop(columns=["id"])

    # Coerce types
    for col in ("nat_points_good",):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Backup original nat_points_good from DB before any recalculation
    if "nat_points_good" in df.columns:
        df["nat_points_original"] = df["nat_points_good"]
    for col in ("show_count", "competition_year"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("start_date", "end_date", "scraped_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    return df


# ---------------------------------------------------------------------------
# UI: Header
# ---------------------------------------------------------------------------
st.title("🐎 USEF Horse Rankings Dashboard")
st.caption(f"Source: Supabase table `{TABLE_NAME}`")

with st.spinner("Loading data…"):
    df = load_rankings()

if df.empty:
    st.warning("No rows returned from Supabase.")
    st.stop()

# ---------------------------------------------------------------------------
# Compute global date bounds for the date range pickers
# ---------------------------------------------------------------------------
import datetime

_has_start_date = "start_date" in df.columns and df["start_date"].notna().any()
_has_end_date   = "end_date"   in df.columns and df["end_date"].notna().any()

_start_date_min = df["start_date"].dropna().min() if _has_start_date else datetime.date(2000, 1, 1)
_start_date_max = df["start_date"].dropna().max() if _has_start_date else datetime.date.today()
_end_date_min   = df["end_date"].dropna().min()   if _has_end_date   else datetime.date(2000, 1, 1)
_end_date_max   = df["end_date"].dropna().max()   if _has_end_date   else datetime.date.today()

# ---------------------------------------------------------------------------
# UI: Filters (on main page)
# ---------------------------------------------------------------------------
with st.expander("🔎 Search & Filters", expanded=True):
    # Row 1: horse picker + free-text search
    r1c1, r1c2 = st.columns([1, 1])
    horse_names_available = sorted(
        df["horse_name"].dropna().astype(str).unique().tolist()
    ) if "horse_name" in df.columns else []
    with r1c1:
        selected_horse = st.selectbox(
            "Pick horse (autocomplete)",
            options=horse_names_available,
            index=None,
            placeholder="Start typing a horse name…",
            help="Type any part of the name to filter the list.",
        )
    with r1c2:
        search_query = st.text_input(
            "Or free-text search (name or ID)",
            placeholder="e.g. ADLER or 4OwKggwWH28",
        ).strip()

    # Row 2: years + sections + award category
    r2c1, r2c2, r2c3 = st.columns(3)
    years_available = sorted(
        [int(y) for y in df["competition_year"].dropna().unique()], reverse=True
    ) if "competition_year" in df.columns else []
    with r2c1:
        selected_years = st.multiselect(
            "Season (competition year)",
            options=years_available,
            default=years_available,
        )
    sections_available = sorted(df["section"].dropna().unique().tolist()) \
        if "section" in df.columns else []
    with r2c2:
        selected_sections: Optional[List[str]] = st.multiselect(
            "Section",
            options=sections_available,
            default=[],
            help="Leave empty to include all sections",
        )
    awards_available = sorted(df["award_category"].dropna().unique().tolist()) \
        if "award_category" in df.columns else []
    with r2c3:
        selected_awards: Optional[List[str]] = st.multiselect(
            "Award category",
            options=awards_available,
            default=[],
            help="Leave empty to include all award categories",
        )

    # Row 3: Start Date / End Date single pickers
    st.markdown("**📅 Date Filters**")
    date_col1, date_col2 = st.columns(2)
    with date_col1:
        filter_start_date = st.date_input(
            "Start Date",
            value=None,
            min_value=datetime.date(2000, 1, 1),
            max_value=datetime.date(2100, 12, 31),
            format="MM/DD/YYYY",
            help="Show records whose competition period includes or starts from this date. Leave blank for no filter.",
            key="filter_start_date",
        )
    with date_col2:
        filter_end_date = st.date_input(
            "End Date",
            value=None,
            min_value=datetime.date(2000, 1, 1),
            max_value=datetime.date(2100, 12, 31),
            format="MM/DD/YYYY",
            help="Show records whose competition period includes or ends by this date. Leave blank for no filter.",
            key="filter_end_date",
        )

    # Row 4: top-15 toggle + refresh button
    r4c1, r4c2 = st.columns([1, 1])

    with r4c1:
        st.write("")  # vertical spacer
        st.write("")
        top15_enabled = st.toggle(
            "🏅 Top 15 shows",
            value=False,
            help="OFF: national points = sum of ALL shows. ON: national points = sum of the top 15 highest-scoring shows.",
        )

    with r4c2:
        st.write("")  # spacer
        st.write("")
        if st.button("🔄 Refresh data", use_container_width=True):
            load_rankings.clear()
            st.rerun()


# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
filtered = df.copy()

if selected_horse:
    filtered = filtered[filtered["horse_name"].astype(str) == selected_horse]

if search_query:
    q = search_query.lower()
    name_match = filtered["horse_name"].astype(str).str.lower().str.contains(q, na=False) \
        if "horse_name" in filtered.columns else False
    id_match = filtered["horse_id"].astype(str).str.lower().str.contains(q, na=False) \
        if "horse_id" in filtered.columns else False
    filtered = filtered[name_match | id_match]

if selected_years and "competition_year" in filtered.columns:
    filtered = filtered[filtered["competition_year"].isin(selected_years)]

if selected_sections:
    filtered = filtered[filtered["section"].isin(selected_sections)]

if selected_awards:
    filtered = filtered[filtered["award_category"].isin(selected_awards)]

# Date overlap filter — show records whose competition period overlaps with the selected range.
# Overlap condition: record.start_date <= filter_end_date AND record.end_date >= filter_start_date
if filter_start_date or filter_end_date:
    mask = pd.Series([True] * len(filtered), index=filtered.index)
    if filter_start_date and _has_end_date:
        mask &= filtered["end_date"].notna() & (filtered["end_date"] >= filter_start_date)
    if filter_end_date and _has_start_date:
        mask &= filtered["start_date"].notna() & (filtered["start_date"] <= filter_end_date)
    filtered = filtered[mask]

# Recalculate nat_points_good from the shows column every time.
# Always compute all-shows sum first (used as highlight reference).
# Toggle OFF → sum all shows | Toggle ON → sort descending, sum top 15 highest values.
if "shows" in filtered.columns:
    def _sum_all_shows(row):
        shows = row["shows"]
        if not isinstance(shows, list) or len(shows) == 0:
            return row["nat_points_good"]
        scores = [s for s in shows if isinstance(s, (int, float))]
        return round(sum(scores), 4)

    filtered = filtered.copy()
    filtered["_nat_all_shows"] = filtered.apply(_sum_all_shows, axis=1)

    if top15_enabled:
        def _top15_points(row):
            shows = row["shows"]
            if not isinstance(shows, list) or len(shows) == 0:
                return row["nat_points_good"]
            scores = sorted([s for s in shows if isinstance(s, (int, float))], reverse=True)
            return round(sum(scores[:15]), 4)
        filtered["nat_points_good"] = filtered.apply(_top15_points, axis=1)
    else:
        filtered["nat_points_good"] = filtered["_nat_all_shows"]


# ---------------------------------------------------------------------------
# UI: KPIs (animated cards)
# ---------------------------------------------------------------------------
_kpi_rows = len(filtered)
_kpi_total = len(df)
_kpi_unique = f"{filtered['horse_id'].nunique():,}" if "horse_id" in filtered.columns else "—"
_kpi_awards = f"{filtered['award_category'].nunique():,}" if "award_category" in filtered.columns else "—"
if "nat_points_good" in filtered.columns and len(filtered) and filtered["nat_points_good"].notna().any():
    _kpi_avg = f"{filtered['nat_points_good'].mean():.2f}"
else:
    _kpi_avg = "—"

st.markdown(
    f"""
    <div class="kpi-grid">
        <div class="kpi-card kpi-indigo">
            <div class="kpi-icon">📊</div>
            <div class="kpi-label">Rows</div>
            <div class="kpi-value">{_kpi_rows:,}</div>
            <div class="kpi-sub">of {_kpi_total:,} total</div>
        </div>
        <div class="kpi-card kpi-cyan">
            <div class="kpi-icon">🐎</div>
            <div class="kpi-label">Unique horses</div>
            <div class="kpi-value">{_kpi_unique}</div>
            <div class="kpi-sub">in current filter</div>
        </div>
        <div class="kpi-card kpi-pink">
            <div class="kpi-icon">🏆</div>
            <div class="kpi-label">Award categories</div>
            <div class="kpi-value">{_kpi_awards}</div>
            <div class="kpi-sub">distinct categories</div>
        </div>
        <div class="kpi-card kpi-amber">
            <div class="kpi-icon">⚡</div>
            <div class="kpi-label">Avg national points</div>
            <div class="kpi-value">{_kpi_avg}</div>
            <div class="kpi-sub">across filtered rows</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()


# ---------------------------------------------------------------------------
# UI: Results table
# ---------------------------------------------------------------------------
_top15_label = " — Nat. points = top 15 highest shows" if top15_enabled else " — Nat. points = all shows"
st.subheader(f"Results ({len(filtered):,}){_top15_label}")

preferred_cols = [
    "competition_year",
    "horse_name",
    "horse_id",
    "section",
    "award_category",
    "nat_points_good",
    "nat_points_original",
    "show_count",
    "start_date",
    "end_date",
    "shows",
    "horse_link",
    "pdf_download_link",
    "scraped_at",
]
display_cols = [c for c in preferred_cols if c in filtered.columns] + \
               [c for c in filtered.columns if c not in preferred_cols]

display_cols = [c for c in display_cols if c != '_nat_all_shows']
display_df = filtered[display_cols].copy()
# Keep _nat_all_shows in filtered for highlight comparison
if '_nat_all_shows' in filtered.columns:
    display_df['_nat_all_shows'] = filtered['_nat_all_shows']

# Render with link columns when possible
column_config = {}
if "competition_year" in display_df.columns:
    column_config["competition_year"] = st.column_config.NumberColumn(
        "Year", format="%d", width="small"
    )
if "horse_link" in display_df.columns:
    column_config["horse_link"] = st.column_config.LinkColumn(
        "USEF page", display_text="Open"
    )
if "pdf_download_link" in display_df.columns:
    column_config["pdf_download_link"] = st.column_config.LinkColumn(
        "PDF report", display_text="PDF"
    )
if "nat_points_good" in display_df.columns:
    column_config["nat_points_good"] = st.column_config.NumberColumn(
        "Nat. points", format="%.2f"
    )
if "nat_points_original" in display_df.columns:
    column_config["nat_points_original"] = st.column_config.NumberColumn(
        "Nat. points (DB)", format="%.2f"
    )

# Highlight nat_points_good cell when toggle is ON and value changed vs DB original
def _highlight_changed(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    if (
        top15_enabled
        and "nat_points_good" in df.columns
        and "_nat_all_shows" in df.columns
    ):
        changed = df["nat_points_good"].round(4) != df["_nat_all_shows"].round(4)
        styles.loc[changed, "nat_points_good"] = "background-color: rgba(99, 102, 241, 0.25); color: #6366f1; font-weight: 700;"
    return styles

styled_df = display_df.style.apply(_highlight_changed, axis=None)

event = st.dataframe(
    styled_df,
    use_container_width=True,
    hide_index=True,
    column_config=column_config,
    height=600,
    on_select="rerun",
    selection_mode="single-row",
    key="rankings_table",
)

# ---------------------------------------------------------------------------
# UI: Selected row details
# ---------------------------------------------------------------------------
selected_rows = event.selection.rows if hasattr(event, "selection") else []
if selected_rows:
    row_idx = selected_rows[0]
    row = display_df.iloc[row_idx]
    horse = row.get("horse_name", "—")
    pts = row.get("nat_points_good", None)
    pts_str = f" · {pts:.2f} pts" if isinstance(pts, (int, float)) and pd.notna(pts) else ""
    st.markdown(
        f"""
        <div class="detail-card">
            <div class="detail-title">✨ {horse}<span style="color:#94a3b8;font-weight:500;">{pts_str}</span></div>
            <div class="detail-sub">Row {row_idx + 1} of {len(display_df):,}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("📋 Row details", expanded=True):
        import html as _html

        LABELS = {
            "competition_year": "Year",
            "horse_name": "Horse",
            "horse_id": "Horse ID",
            "section": "Section",
            "award_category": "Award category",
            "nat_points_good": "National points",
            "nat_points_original": "Nat. points (DB original)",
            "show_count": "Show count",
            "shows": "Shows",
            "start_date": "Start date",
            "end_date": "End date",
            "horse_link": "USEF page",
            "pdf_download_link": "PDF report",
            "scraped_at": "Scraped at",
        }
        GROUPS = [
            ("🐎 Identity",    ["horse_name", "horse_id", "section", "award_category"]),
            ("⚡ Performance", ["nat_points_good", "nat_points_original", "show_count", "shows"]),
            ("📅 Period",      ["competition_year", "start_date", "end_date"]),
            ("🔗 Links",       ["horse_link", "pdf_download_link"]),
            ("ℹ️ Meta",        ["scraped_at"]),
        ]

        def _fmt_value(key, value):
            """Return HTML for the value side of a detail-field card."""
            if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
                return '<div class="detail-value detail-value--muted">—</div>'
            # Big highlighted number for points
            if key == "nat_points_good" and isinstance(value, (int, float)):
                return f'<div class="detail-value detail-value--big">{value:.2f}</div>'
            # Show scores as chips
            if key == "shows":
                items = []
                if isinstance(value, (list, tuple)):
                    items = list(value)
                else:
                    s = str(value).strip().strip("[]")
                    if s:
                        items = [p.strip() for p in s.split(",") if p.strip()]
                if not items:
                    return '<div class="detail-value detail-value--muted">—</div>'
                chips = "".join(
                    f'<span class="detail-chip">{_html.escape(str(it))}</span>'
                    for it in items
                )
                return f'<div class="detail-chips">{chips}</div>'
            # Links as buttons
            if key in ("horse_link", "pdf_download_link"):
                url = _html.escape(str(value), quote=True)
                label = "Open USEF page ↗" if key == "horse_link" else "Open PDF ↗"
                return f'<a class="detail-link-btn" href="{url}" target="_blank" rel="noopener">{label}</a>'
            # Default
            return f'<div class="detail-value">{_html.escape(str(value))}</div>'

        # Render grouped sections
        section_html_parts = []
        rendered_keys = set()
        for group_label, keys in GROUPS:
            keys_present = [k for k in keys if k in row.index]
            if not keys_present:
                continue
            cards = []
            for k in keys_present:
                rendered_keys.add(k)
                wide_cls = " detail-field--wide" if k in ("shows", "section", "award_category") else ""
                cards.append(
                    f'<div class="detail-field{wide_cls}">'
                    f'<div class="detail-label">{_html.escape(LABELS.get(k, k))}</div>'
                    f'{_fmt_value(k, row.get(k))}'
                    f'</div>'
                )
            section_html_parts.append(
                f'<div class="detail-section">{group_label}<span class="section-line"></span></div>'
                f'<div class="detail-grid">{"".join(cards)}</div>'
            )

        # Catch-all section for any unexpected columns
        leftover = [k for k in row.index if k not in rendered_keys]
        if leftover:
            cards = []
            for k in leftover:
                cards.append(
                    f'<div class="detail-field">'
                    f'<div class="detail-label">{_html.escape(LABELS.get(k, str(k)))}</div>'
                    f'{_fmt_value(k, row.get(k))}'
                    f'</div>'
                )
            section_html_parts.append(
                f'<div class="detail-section">📦 Other<span class="section-line"></span></div>'
                f'<div class="detail-grid">{"".join(cards)}</div>'
            )

        st.markdown("".join(section_html_parts), unsafe_allow_html=True)
else:
    st.caption("👆 Click any row to highlight it and see its details.")

# ---------------------------------------------------------------------------
# UI: CSV download
# ---------------------------------------------------------------------------
csv_bytes = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️  Download filtered results as CSV",
    data=csv_bytes,
    file_name="usef_horse_rankings_filtered.csv",
    mime="text/csv",
    use_container_width=False,
)

st.caption(
    "Tip: click any column header in the table above to sort. "
    "Filters apply live and the CSV reflects the current filtered view."
)
