from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
    """Get list of all venues in the database."""
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
    """Compute complaints on the fly from filtered reviews."""
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


# ── Streamlit UI ──────────────────────────────────────────────

st.set_page_config(
    page_title="Bublik - Анализ отзывов",
    page_icon="🎡",
    layout="wide",
)

st.title("Анализ отзывов")

# Sidebar filters
st.sidebar.header("Фильтры")

# Venue filter
venues_list = fetch_venues()
venue_options = {"Все заведения": None}
for v in venues_list:
    venue_options[v] = v
selected_venue_label = st.sidebar.selectbox("Заведение", list(venue_options.keys()))
selected_venue = venue_options[selected_venue_label]

platform_options = {"Все": None, "Google": Platform.GOOGLE, "Яндекс": Platform.YANDEX, "2GIS": Platform.TWOGIS}
selected_platform_label = st.sidebar.selectbox("Платформа", list(platform_options.keys()))
selected_platform = platform_options[selected_platform_label]

period_options = {"День": "day", "Неделя": "week", "Месяц": "month", "Год": "year"}
selected_period_label = st.sidebar.selectbox("Группировка", list(period_options.keys()), index=2)
selected_period = period_options[selected_period_label]

date_range = st.sidebar.selectbox(
    "Период",
    ["За всё время", "За год", "За месяц", "За неделю", "За сегодня"],
)

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


# ── Main content ──────────────────────────────────────────────

reviews_data = fetch_reviews(selected_venue, selected_platform, date_from)
df = pd.DataFrame(reviews_data)

if not df.empty:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Всего отзывов", len(df))
    with col2:
        st.metric("Средняя оценка", f"{df['rating'].mean():.2f}")
    with col3:
        negative = len(df[df["rating"] <= 3])
        st.metric("Негативных (≤3)", negative)
    with col4:
        venues_count = df["venue"].nunique()
        st.metric("Заведений", venues_count)

    # Rating trend chart
    st.subheader("Динамика оценок")
    stats_data = fetch_stats_by_period(selected_period, selected_venue, selected_platform, date_from)
    if stats_data:
        stats_df = pd.DataFrame(stats_data)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=stats_df["period"],
            y=stats_df["avg_rating"],
            mode="lines+markers",
            name="Средняя оценка",
            line=dict(color="#FF6B6B", width=3),
        ))
        fig.add_trace(go.Bar(
            x=stats_df["period"],
            y=stats_df["count"],
            name="Кол-во отзывов",
            yaxis="y2",
            opacity=0.3,
            marker_color="#4ECDC4",
        ))
        fig.update_layout(
            yaxis=dict(title="Средняя оценка", range=[1, 5.5]),
            yaxis2=dict(title="Кол-во отзывов", overlaying="y", side="right"),
            hovermode="x unified",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Platform breakdown
    st.subheader("Разбивка по платформам")
    platform_stats = df.groupby("platform").agg(
        count=("rating", "count"),
        avg_rating=("rating", "mean"),
    ).reset_index()
    platform_stats["avg_rating"] = platform_stats["avg_rating"].round(2)

    col1, col2 = st.columns(2)
    with col1:
        fig_pie = px.pie(
            platform_stats,
            values="count",
            names="platform",
            title="Распределение отзывов",
            color_discrete_sequence=["#FF6B6B", "#4ECDC4", "#45B7D1"],
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    with col2:
        fig_bar = px.bar(
            platform_stats,
            x="platform",
            y="avg_rating",
            color="platform",
            title="Средняя оценка по платформам",
            color_discrete_sequence=["#FF6B6B", "#4ECDC4", "#45B7D1"],
        )
        fig_bar.update_layout(yaxis=dict(range=[1, 5.5]))
        st.plotly_chart(fig_bar, use_container_width=True)

    # Rating distribution
    st.subheader("Распределение оценок")
    fig_hist = px.histogram(
        df,
        x="rating",
        color="platform",
        nbins=5,
        title="Распределение оценок",
        color_discrete_sequence=["#FF6B6B", "#4ECDC4", "#45B7D1"],
    )
    st.plotly_chart(fig_hist, use_container_width=True)

    # Complaints section — computed on the fly from filtered reviews
    st.subheader("Топ жалоб и недовольств")
    complaints_data = compute_complaints(df, 20)
    if complaints_data:
        complaints_df = pd.DataFrame(complaints_data)
        fig_complaints = px.bar(
            complaints_df,
            x="count",
            y="category",
            orientation="h",
            title="Частота жалоб по категориям",
            color="count",
            color_continuous_scale="Reds",
        )
        fig_complaints.update_layout(height=400, yaxis=dict(categoryorder="total ascending"))
        st.plotly_chart(fig_complaints, use_container_width=True)

        with st.expander("Примеры жалоб"):
            for _, row in complaints_df.iterrows():
                st.markdown(f"**{row['category']}** (ключевое: `{row['keyword']}`, упоминаний: {row['count']})")
                if row["sample_texts"]:
                    for sample in row["sample_texts"].split("|||"):
                        if sample.strip():
                            st.markdown(f"> {sample.strip()}")
                st.divider()
    else:
        st.info("Негативных отзывов за выбранный период не найдено.")

    # Recent reviews table
    st.subheader("Последние отзывы")
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        show_negative = st.checkbox("Только негативные (≤3)")
    with filter_col2:
        show_with_text = st.checkbox("Только с текстом")
    display_df = df.copy()
    if show_negative:
        display_df = display_df[display_df["rating"] <= 3]
    if show_with_text:
        display_df = display_df[display_df["text"].str.len() > 0]

    columns = ["venue", "platform", "author", "rating", "text", "published_at"]
    st.dataframe(
        display_df[columns].head(50),
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
