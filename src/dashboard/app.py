from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from src.analyzer.keyword_analyzer import KeywordComplaintAnalyzer
from src.config import settings
from src.db.models import Platform, Review

_engine = create_engine(settings.database_url_sync, echo=False)


def get_session() -> Session:
    return Session(_engine)


def fetch_venues() -> list[str]:
    with get_session() as session:
        result = session.execute(select(Review.venue).distinct().order_by(Review.venue))
        return [row[0] for row in result.all()]


def fetch_reviews(
    venue: str | None = None,
    platform: Platform | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict]:
    with get_session() as session:
        query = select(Review).order_by(Review.published_at.desc())
        if venue:
            query = query.where(Review.venue == venue)
        if platform:
            query = query.where(Review.platform == platform)
        if date_from:
            query = query.where(Review.published_at >= date_from)
        if date_to:
            query = query.where(Review.published_at < date_to)
        result = session.execute(query)
        reviews = result.scalars().all()
        return [
            {
                "id": r.id,
                "venue": r.venue,
                "platform": r.platform.value,
                "author": r.author,
                "rating": r.rating,
                "text": r.text or "",
                "published_at": r.published_at,
            }
            for r in reviews
        ]


def fetch_stats_by_period(
    group_by: str,
    venue: str | None = None,
    platform: Platform | None = None,
    date_from: datetime | None = None,
) -> list[dict]:
    with get_session() as session:
        if group_by == "day":
            date_trunc = func.date_trunc("day", Review.published_at)
        elif group_by == "week":
            date_trunc = func.date_trunc("week", Review.published_at)
        elif group_by == "month":
            date_trunc = func.date_trunc("month", Review.published_at)
        else:
            date_trunc = func.date_trunc("year", Review.published_at)
        query = (
            select(
                date_trunc.label("period"),
                func.avg(Review.rating).label("avg_rating"),
                func.count(Review.id).label("count"),
            )
            .group_by(date_trunc)
            .order_by(date_trunc)
        )
        if venue:
            query = query.where(Review.venue == venue)
        if platform:
            query = query.where(Review.platform == platform)
        if date_from:
            query = query.where(Review.published_at >= date_from)
        result = session.execute(query)
        return [
            {
                "period": row.period,
                "avg_rating": round(float(row.avg_rating), 2),
                "count": row.count,
            }
            for row in result.all()
        ]


def compute_complaints(df: pd.DataFrame, limit: int = 20) -> list[dict]:
    negative_texts = df[df["rating"] <= 3]["text"].tolist()
    if not negative_texts:
        return []
    import asyncio
    analyzer = KeywordComplaintAnalyzer()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                complaints = pool.submit(
                    asyncio.run, analyzer.extract_complaints(negative_texts)
                ).result()
        else:
            complaints = asyncio.run(analyzer.extract_complaints(negative_texts))
    except RuntimeError:
        complaints = asyncio.run(analyzer.extract_complaints(negative_texts))
    results = []
    for c in complaints[:limit]:
        results.append({
            "category": c.category,
            "keyword": c.keyword,
            "count": c.count,
            "sample_texts": "|||".join(c.sample_texts) if c.sample_texts else "",
        })
    return results


# ── Helpers ──────────────────────────────────────────────────
def section_title(text: str):
    """Render a section title inside a card."""
    st.markdown(
        f'<p style="font-family:Inter,sans-serif;font-size:18px;font-weight:600;'
        f'color:#1B1F3B;margin:0 0 12px 0;letter-spacing:-0.3px;">{text}</p>',
        unsafe_allow_html=True,
    )


# ── Design tokens ────────────────────────────────────────────
C_BG = "#EEF1F6"
C_CARD = "#FFFFFF"
C_TEXT = "#1B1F3B"
C_MUTED = "#808495"
C_ACCENT = "#C8E64A"
C_BAR = "#1B1F3B"
C_BAR2 = "#4A5568"
C_BAR3 = "#A0AEC0"
GRID = "#DFE1E6"
FONT = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"

# ── Plotly template ──────────────────────────────────────────
_tpl = go.layout.Template(layout=go.Layout(
    plot_bgcolor=C_CARD,
    paper_bgcolor=C_CARD,
    font=dict(family=FONT, color=C_MUTED, size=13),
    margin=dict(l=40, r=40, t=12, b=32),
    colorway=[C_BAR, C_ACCENT, C_BAR2, C_BAR3],
    xaxis=dict(showgrid=False, zeroline=False, showline=False),
    yaxis=dict(gridcolor=GRID, showgrid=True, gridwidth=1, zeroline=False, showline=False),
))
pio.templates["bublik"] = _tpl
pio.templates.default = "plotly+bublik"

# ── Page ─────────────────────────────────────────────────────
st.set_page_config(page_title="Bublik", page_icon="🫧", layout="wide")

# ── CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ═══ BASE ═══ */
html, body, .stApp, .stApp * {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
html, body, .stApp {
    background: #EEF1F6 !important;
    color: #1B1F3B !important;
}
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

/* ═══ LAYOUT ═══ */
section[data-testid="stMain"] > div:first-child {
    padding: 24px 32px !important;
}
section[data-testid="stMain"] [data-testid="stVerticalBlock"] {
    gap: 20px !important;
}
section[data-testid="stMain"] [data-testid="stHorizontalBlock"] {
    gap: 20px !important;
}

/* ═══ HEADER BAR ═══ */
.bublik-header {
    background: #1B1F3B !important;
    border-radius: 20px;
    padding: 18px 32px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
}
.bublik-header .brand {
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 700;
    font-family: 'Inter', sans-serif;
    letter-spacing: -0.3px;
}
.bublik-header .sep {
    color: #C8E64A;
    margin: 0 8px;
}
.bublik-header .subtitle {
    color: rgba(255,255,255,0.7);
    font-size: 20px;
    font-weight: 400;
    font-family: 'Inter', sans-serif;
}
.bublik-header .pill {
    background: #C8E64A;
    color: #1B1F3B;
    font-size: 13px;
    font-weight: 600;
    font-family: 'Inter', sans-serif;
    padding: 6px 18px;
    border-radius: 20px;
    margin-left: auto;
}

/* ═══ SIDEBAR ═══ */
section[data-testid="stSidebar"] {
    background: #FFFFFF !important;
    border-right: none !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] [data-testid="stHeading"] h2 {
    display: block !important;
    font-size: 20px !important;
    font-weight: 700 !important;
    color: #1B1F3B !important;
}
section[data-testid="stSidebar"] label {
    font-size: 14px !important;
    font-weight: 500 !important;
    color: #1B1F3B !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    border-radius: 12px !important;
    font-size: 14px !important;
}

/* ═══ ROOT WRAPPER — transparent ═══ */
div[data-testid="stVerticalBlockBorderWrapper"].st-emotion-cache-0,
div[data-testid="stVerticalBlockBorderWrapper"].st-emotion-cache-0 > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}

/* ═══ CARDS (bordered containers) ═══ */
div[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) {
    background: #FFFFFF !important;
    border: none !important;
    border-radius: 20px !important;
    box-shadow: 0 1px 3px rgba(27,31,59,0.04), 0 4px 16px rgba(27,31,59,0.03) !important;
    overflow: hidden !important;
    padding: 24px !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) > div {
    background: #FFFFFF !important;
}

/* ═══ METRICS ═══ */
div[data-testid="metric-container"] {
    background: transparent;
    border: none;
    padding: 4px 4px;
}
div[data-testid="metric-container"] label {
    color: #808495 !important;
    font-size: 14px !important;
    font-weight: 400 !important;
    text-transform: none !important;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #1B1F3B !important;
    font-size: 36px !important;
    font-weight: 700 !important;
    letter-spacing: -0.5px;
}

/* ═══ HIDE default st.subheader in MAIN — we use section_title() inside cards ═══ */
section[data-testid="stMain"] [data-testid="stHeading"] {
    display: none !important;
}

/* ═══ DATAFRAME ═══ */
div[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
}

/* ═══ EXPANDER ═══ */
div[data-testid="stExpander"] details { border: none !important; }

/* ═══ MISC ═══ */
hr { border-color: #F0F1F3 !important; }
blockquote {
    border-left: 3px solid #C8E64A !important;
    background: #F8F9FB !important;
    border-radius: 0 12px 12px 0;
    padding: 12px 16px !important;
    margin: 6px 0 !important;
    color: #4A4E5A !important;
    font-size: 13px !important;
    line-height: 1.6 !important;
}
code {
    background: #EEF1F6 !important;
    color: #1B1F3B !important;
    padding: 2px 8px !important;
    border-radius: 6px !important;
    font-size: 12px !important;
}
.stButton > button {
    background: #C8E64A !important;
    color: #1B1F3B !important;
    border: none !important;
    border-radius: 20px !important;
    font-weight: 600 !important;
}
/* plotly — round the fullscreen frame + SVG container */
div[data-testid="stFullScreenFrame"] {
    border-radius: 14px !important;
    overflow: hidden !important;
}
/* plotly hover — remove SVG clipPath so tooltip text isn't clipped */
div[data-testid="stPlotlyChart"] .hoverlayer,
div[data-testid="stPlotlyChart"] .hoverlayer * {
    clip-path: none !important;
    -webkit-clip-path: none !important;
}
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────
st.markdown("""
<div class="bublik-header">
    <span class="brand">Bublik</span>
    <span class="sep">/</span>
    <span class="subtitle">Анализ отзывов</span>
    <span class="pill">Dashboard</span>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────
st.sidebar.header("Фильтры")

venues_list = fetch_venues()
venue_options = {"Все заведения": None}
for v in venues_list:
    venue_options[v] = v
selected_venue_label = st.sidebar.selectbox("Заведение", list(venue_options.keys()))
selected_venue = venue_options[selected_venue_label]

platform_options = {"Все": None, "Google": Platform.GOOGLE, "Яндекс": Platform.YANDEX, "2GIS": Platform.TWOGIS}
selected_platform_label = st.sidebar.selectbox("Платформа", list(platform_options.keys()))
selected_platform = platform_options[selected_platform_label]

date_range = st.sidebar.selectbox(
    "Период", ["За всё время", "За год", "За месяц", "За неделю", "За сегодня"],
)
period_options = {"День": "day", "Неделя": "week", "Месяц": "month", "Год": "year"}
default_group = {"За сегодня": 0, "За неделю": 0, "За месяц": 0, "За год": 2, "За всё время": 2}
selected_period_label = st.sidebar.selectbox(
    "Группировка", list(period_options.keys()), index=default_group.get(date_range, 2),
)
selected_period = period_options[selected_period_label]

now = datetime.now(timezone.utc)
date_from = None
if date_range == "За год":
    date_from = now - timedelta(days=365)
elif date_range == "За месяц":
    date_from = now - timedelta(days=30)
elif date_range == "За неделю":
    date_from = now - timedelta(weeks=1)
elif date_range == "За сегодня":
    date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)


# ── Data ─────────────────────────────────────────────────────
reviews_data = fetch_reviews(selected_venue, selected_platform, date_from)
df = pd.DataFrame(reviews_data)

if not df.empty:

    # ── KPI ──────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4, gap="large")
    with k1:
        with st.container(border=True):
            st.metric("Всего отзывов", len(df))
    with k2:
        with st.container(border=True):
            st.metric("Средняя оценка", f"{df['rating'].mean():.2f}")
    with k3:
        with st.container(border=True):
            st.metric("Негативных (<=3)", len(df[df["rating"] <= 3]))
    with k4:
        with st.container(border=True):
            st.metric("Заведений", df["venue"].nunique())

    # ── Trend ────────────────────────────────────────────────
    stats_data = fetch_stats_by_period(selected_period, selected_venue, selected_platform, date_from)
    if stats_data:
        stats_df = pd.DataFrame(stats_data)
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=stats_df["period"], y=stats_df["count"],
            name="Кол-во отзывов", yaxis="y2",
            marker_color=C_BAR, marker_cornerradius=8, opacity=0.9,
            hovertemplate="<b>%{x|%b %Y}</b><br>Отзывов: %{y}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=stats_df["period"], y=stats_df["avg_rating"],
            mode="lines+markers", name="Средняя оценка",
            line=dict(color=C_ACCENT, width=2.5, shape="spline"),
            marker=dict(color=C_ACCENT, size=5),
            hovertemplate="<b>%{x|%b %Y}</b><br>Оценка: %{y}<extra></extra>",
        ))
        fig.update_layout(
            yaxis=dict(title="", range=[1, 5.5], dtick=1, gridcolor=GRID, showgrid=True),
            yaxis2=dict(title="", overlaying="y", side="right", showgrid=False),
            hovermode="closest", height=360,
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, font=dict(size=12, color=C_MUTED)),
            margin=dict(l=40, r=44, t=8, b=28),
        )
        with st.container(border=True):
            section_title("Динамика оценок")
            st.plotly_chart(fig, use_container_width=True, theme=None)

    # ── Platforms ────────────────────────────────────────────
    plat_stats = df.groupby("platform").agg(
        count=("rating", "count"), avg_rating=("rating", "mean"),
    ).reset_index()
    plat_stats["avg_rating"] = plat_stats["avg_rating"].round(2)

    c1, c2 = st.columns(2, gap="large")
    with c1:
        fig_pie = px.pie(
            plat_stats, values="count", names="platform",
            color_discrete_sequence=[C_BAR, C_ACCENT, C_BAR3], hole=0.5,
        )
        fig_pie.update_traces(
            textinfo="percent+label", textfont_size=12,
            marker=dict(line=dict(color=C_CARD, width=3)),
        )
        fig_pie.update_layout(
            showlegend=False, height=300,
            margin=dict(l=20, r=20, t=8, b=20),
        )
        with st.container(border=True):
            section_title("Распределение отзывов")
            st.plotly_chart(fig_pie, use_container_width=True, theme=None)
    with c2:
        fig_bar = px.bar(
            plat_stats, x="platform", y="avg_rating", color="platform",
            color_discrete_sequence=[C_BAR, C_ACCENT, C_BAR3],
        )
        fig_bar.update_traces(marker_cornerradius=10, width=0.5)
        fig_bar.update_layout(
            yaxis=dict(title="", range=[1, 5.5]),
            xaxis=dict(title=""),
            showlegend=False, height=300,
            margin=dict(l=36, r=20, t=8, b=28),
        )
        with st.container(border=True):
            section_title("Средняя оценка по платформам")
            st.plotly_chart(fig_bar, use_container_width=True, theme=None)

    # ── Rating distribution ──────────────────────────────────
    fig_hist = px.histogram(
        df, x="rating", color="platform", nbins=5,
        color_discrete_sequence=[C_BAR, C_ACCENT, C_BAR3],
    )
    fig_hist.update_traces(marker_cornerradius=8)
    fig_hist.update_layout(
        xaxis=dict(title=""), yaxis=dict(title=""),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=12, color=C_MUTED)),
        height=320,
        margin=dict(l=36, r=36, t=8, b=28),
    )
    with st.container(border=True):
        section_title("Распределение оценок")
        st.plotly_chart(fig_hist, use_container_width=True, theme=None)

    # ── Complaints ───────────────────────────────────────────
    complaints_data = compute_complaints(df, 20)
    if complaints_data:
        cdf = pd.DataFrame(complaints_data)
        fig_c = px.bar(
            cdf, x="count", y="category", orientation="h",
            color="count",
            color_continuous_scale=[[0, C_BAR3], [0.5, C_BAR2], [1, C_BAR]],
        )
        fig_c.update_traces(marker_cornerradius=8)
        fig_c.update_layout(
            height=360,
            yaxis=dict(title="", categoryorder="total ascending"),
            xaxis=dict(title=""),
            margin=dict(l=160, r=36, t=8, b=28),
        )
        with st.container(border=True):
            section_title("Топ жалоб и недовольств")
            st.plotly_chart(fig_c, use_container_width=True, theme=None)

        with st.container(border=True):
            section_title("Примеры жалоб")
            for _, row in cdf.iterrows():
                # Category header
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:10px;margin:16px 0 10px 0;">'
                    f'<span style="font-family:Inter,sans-serif;font-size:17px;font-weight:600;color:#1B1F3B;">{row["category"]}</span>'
                    f'<span style="background:#EEF1F6;color:#606474;font-size:13px;font-weight:500;'
                    f'padding:4px 12px;border-radius:8px;font-family:Inter,sans-serif;">{row["keyword"]}</span>'
                    f'<span style="color:#808495;font-size:14px;font-family:Inter,sans-serif;">'
                    f'{row["count"]} упоминаний</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if row["sample_texts"]:
                    for sample in row["sample_texts"].split("|||"):
                        txt = sample.strip()
                        if txt:
                            st.markdown(
                                f'<div style="background:#F8F9FB;border-radius:12px;padding:14px 18px;'
                                f'margin:8px 0;font-size:15px;line-height:1.7;color:#3A3E4A;'
                                f'border-left:3px solid #C8E64A;font-family:Inter,sans-serif;">'
                                f'{txt}</div>',
                                unsafe_allow_html=True,
                            )
                st.markdown('<hr style="border:none;border-top:1px solid #F0F1F3;margin:12px 0;">', unsafe_allow_html=True)
    else:
        st.info("Негативных отзывов за выбранный период не найдено.")

    # ── Reviews table ────────────────────────────────────────
    fc1, fc2 = st.columns(2)
    with fc1:
        show_negative = st.checkbox("Только негативные (<=3)")
    with fc2:
        show_with_text = st.checkbox("Только с текстом")
    display_df = df.copy()
    if show_negative:
        display_df = display_df[display_df["rating"] <= 3]
    if show_with_text:
        display_df = display_df[display_df["text"].str.len() > 0]

    with st.container(border=True):
        section_title("Последние отзывы")
        st.dataframe(
            display_df[["venue", "platform", "author", "rating", "text", "published_at"]].head(50),
            use_container_width=True,
            column_config={
                "venue": "Заведение",
                "platform": "Платформа",
                "author": "Автор",
                "rating": st.column_config.NumberColumn("Оценка", format="%.1f"),
                "text": "Отзыв",
                "published_at": st.column_config.DatetimeColumn("Дата", format="DD.MM.YYYY"),
            },
        )
else:
    st.warning("Отзывы пока не собраны. Запустите сбор данных.")
    st.code("docker compose up app", language="bash")
