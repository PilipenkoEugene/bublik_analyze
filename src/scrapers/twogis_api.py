"""2GIS reviews scraper via public API — no browser needed."""
import hashlib
import logging
import re
from datetime import datetime, timezone

import httpx

from src.db.models import Platform
from src.scrapers.protocols import ReviewData

logger = logging.getLogger(__name__)

_API_BASE = "https://public-api.reviews.2gis.com/3.0/branches"
_API_KEY = "6e7e1929-4ea9-4a5d-8c05-d601860389bd"
_PAGE_LIMIT = 50


class TwoGisApiScraper:
    """Fetch 2GIS reviews via their public REST API."""

    def __init__(self, url: str, venue: str = "") -> None:
        self.url = url
        self.venue = venue
        self._branch_id = self._extract_branch_id(url)

    @property
    def platform(self) -> Platform:
        return Platform.TWOGIS

    @staticmethod
    def _extract_branch_id(url: str) -> str:
        """Extract branch/firm ID from a 2GIS URL."""
        m = re.search(r"/firm/(\d+)", url)
        if m:
            return m.group(1)
        m = re.search(r"/branches/\d+/firm/(\d+)", url)
        if m:
            return m.group(1)
        raise ValueError(f"Cannot extract branch ID from 2GIS URL: {url}")

    async def scrape(self, since: datetime | None = None) -> list[ReviewData]:
        logger.info("Starting 2GIS API scrape (since=%s): branch=%s", since, self._branch_id)
        reviews: list[ReviewData] = []
        offset = 0

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params = {
                    "key": _API_KEY,
                    "locale": "ru_RU",
                    "limit": _PAGE_LIMIT,
                    "offset": offset,
                    "rated": "true",
                    "sort_by": "date_created",
                    "fields": "meta.branch_rating,meta.branch_reviews_count",
                }
                resp = await client.get(f"{_API_BASE}/{self._branch_id}/reviews", params=params)
                if resp.status_code != 200:
                    logger.error("2GIS API error: %s %s", resp.status_code, resp.text[:200])
                    break

                data = resp.json()
                batch = data.get("reviews", [])
                if not batch:
                    break

                stop = False
                for r in batch:
                    published = self._parse_date(r["date_created"])
                    if since and published <= since:
                        stop = True
                        break

                    reviews.append(ReviewData(
                        venue=self.venue,
                        platform=Platform.TWOGIS,
                        external_id=str(r["id"]),
                        author=r.get("user", {}).get("name", ""),
                        rating=float(r.get("rating", 5)),
                        text=r.get("text") or None,
                        published_at=published,
                    ))

                if stop:
                    break

                # Check if there's a next page
                if not data.get("meta", {}).get("next_link"):
                    break
                offset += _PAGE_LIMIT

                if offset > 5000:
                    logger.warning("2GIS API: hit 5000 offset limit for %s", self.venue)
                    break

        logger.info("Scraped %d new reviews from 2GIS API for %s", len(reviews), self.venue)
        return reviews

    async def close(self) -> None:
        """No-op — no browser to close."""
        pass

    @staticmethod
    def _parse_date(iso_str: str) -> datetime:
        """Parse ISO 8601 date from 2GIS API and convert to UTC."""
        dt = datetime.fromisoformat(iso_str)
        return dt.astimezone(timezone.utc)
