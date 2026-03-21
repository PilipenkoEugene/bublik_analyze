from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Complaint, Platform, Review


class ReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_reviews(self, reviews: list[dict]) -> int:
        """Insert reviews, skip duplicates by (platform, external_id). Returns inserted count."""
        if not reviews:
            return 0

        stmt = insert(Review).values(reviews)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_platform_external_id"
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount  # type: ignore[return-value]

    async def get_avg_rating(
        self,
        platform: Platform | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> float | None:
        query = select(func.avg(Review.rating))
        if platform:
            query = query.where(Review.platform == platform)
        if date_from:
            query = query.where(Review.published_at >= date_from)
        if date_to:
            query = query.where(Review.published_at < date_to)

        result = await self._session.execute(query)
        return result.scalar()

    async def get_reviews(
        self,
        platform: Platform | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        rating_max: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Review]:
        query = select(Review).order_by(Review.published_at.desc())
        if platform:
            query = query.where(Review.platform == platform)
        if date_from:
            query = query.where(Review.published_at >= date_from)
        if date_to:
            query = query.where(Review.published_at < date_to)
        if rating_max is not None:
            query = query.where(Review.rating <= rating_max)

        query = query.limit(limit).offset(offset)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_rating_stats(
        self,
        platform: Platform | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        query = select(
            func.count(Review.id).label("total"),
            func.avg(Review.rating).label("avg_rating"),
            func.min(Review.rating).label("min_rating"),
            func.max(Review.rating).label("max_rating"),
        )
        if platform:
            query = query.where(Review.platform == platform)
        if date_from:
            query = query.where(Review.published_at >= date_from)
        if date_to:
            query = query.where(Review.published_at < date_to)

        result = await self._session.execute(query)
        row = result.one()
        return {
            "total": row.total,
            "avg_rating": float(row.avg_rating) if row.avg_rating else None,
            "min_rating": float(row.min_rating) if row.min_rating else None,
            "max_rating": float(row.max_rating) if row.max_rating else None,
        }

    async def get_review_count(self) -> int:
        result = await self._session.execute(select(func.count(Review.id)))
        return result.scalar() or 0

    async def get_last_review_date(self, platform: Platform) -> datetime | None:
        """Get the most recent review date for a given platform."""
        query = (
            select(func.max(Review.published_at))
            .where(Review.platform == platform)
        )
        result = await self._session.execute(query)
        return result.scalar()


class ComplaintRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_complaints(self, complaints: list[dict]) -> None:
        if not complaints:
            return
        for c in complaints:
            stmt = insert(Complaint).values(**c)
            stmt = stmt.on_conflict_do_update(
                index_elements=["keyword"],
                set_={
                    "count": Complaint.count + c.get("count", 1),
                    "last_seen": c["last_seen"],
                    "sample_texts": c.get("sample_texts"),
                    "category": c.get("category", "other"),
                },
            )
            await self._session.execute(stmt)
        await self._session.commit()

    async def get_top_complaints(self, limit: int = 20) -> list[Complaint]:
        query = (
            select(Complaint)
            .order_by(Complaint.count.desc())
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())
