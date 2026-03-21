import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.analyzer.keyword_analyzer import KeywordComplaintAnalyzer
from src.config import settings
from src.db.models import Platform
from src.db.repository import ComplaintRepository, ReviewRepository
from src.db.session import async_session
from src.scrapers.google_maps import GoogleMapsScraper
from src.scrapers.protocols import ReviewScraperProtocol
from src.scrapers.twogis import TwoGisScraper
from src.scrapers.yandex_maps import YandexMapsScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_scrapers() -> list[ReviewScraperProtocol]:
    """Factory: create all scrapers. Easy to swap to API-based implementations."""
    return [
        GoogleMapsScraper(settings.google_url),
        YandexMapsScraper(settings.yandex_url),
        TwoGisScraper(settings.twogis_url),
    ]


async def run_scraping() -> None:
    """Run all scrapers, save results to DB, then analyze complaints."""
    logger.info("=== Starting scraping job ===")
    scrapers = get_scrapers()
    all_reviews = []

    # Get last known review date per platform for incremental scraping
    platform_since: dict[Platform, datetime | None] = {}
    async with async_session() as session:
        repo = ReviewRepository(session)
        for scraper in scrapers:
            platform_since[scraper.platform] = await repo.get_last_review_date(scraper.platform)

    for scraper in scrapers:
        try:
            since = platform_since.get(scraper.platform)
            if since:
                logger.info("Incremental scrape for %s since %s", scraper.platform.value, since)
            else:
                logger.info("Full scrape for %s (no previous data)", scraper.platform.value)

            reviews = await scraper.scrape(since=since)
            all_reviews.extend(reviews)
            logger.info(
                "Scraped %d reviews from %s", len(reviews), scraper.platform.value
            )
        except Exception as e:
            logger.error("Scraper %s failed: %s", scraper.platform.value, e)
        finally:
            await scraper.close()

    # Save to DB
    if all_reviews:
        async with async_session() as session:
            repo = ReviewRepository(session)
            reviews_dicts = [
                {
                    "platform": r.platform,
                    "external_id": r.external_id,
                    "author": r.author,
                    "rating": r.rating,
                    "text": r.text,
                    "published_at": r.published_at,
                    "scraped_at": datetime.now(timezone.utc),
                }
                for r in all_reviews
            ]
            inserted = await repo.upsert_reviews(reviews_dicts)
            logger.info("Inserted %d new, %d duplicate (total scraped: %d)", inserted, len(all_reviews) - inserted, len(all_reviews))

    # Analyze complaints from negative reviews
    async with async_session() as session:
        repo = ReviewRepository(session)
        negative_reviews = await repo.get_reviews(rating_max=3.0, limit=1000)
        texts = [r.text for r in negative_reviews if r.text]

        if texts:
            analyzer = KeywordComplaintAnalyzer()
            complaints = await analyzer.extract_complaints(texts)

            complaint_repo = ComplaintRepository(session)
            complaints_dicts = [
                {
                    "keyword": c.keyword,
                    "category": c.category,
                    "count": c.count,
                    "last_seen": datetime.now(timezone.utc),
                    "sample_texts": "|||".join(c.sample_texts),
                }
                for c in complaints
            ]
            await complaint_repo.save_complaints(complaints_dicts)
            logger.info("Saved %d complaint categories", len(complaints))

    logger.info("=== Scraping job complete ===")


async def main() -> None:
    # Migrations are handled by the `migrate` service in docker-compose

    # Run initial scrape
    logger.info("Running initial scraping...")
    await run_scraping()

    # Schedule daily scrape at 01:00 MSK (UTC+3 → 22:00 UTC)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scraping,
        trigger=CronTrigger(hour=22, minute=0),  # 01:00 MSK = 22:00 UTC
        id="daily_scrape",
        name="Daily review scraping",
        replace_existing=True,
        misfire_grace_time=None,
    )
    scheduler.start()
    logger.info("Scheduler started. Next scrape at 01:00 MSK (22:00 UTC)")

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
