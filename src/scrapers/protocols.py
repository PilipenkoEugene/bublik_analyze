from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from src.db.models import Platform


@dataclass
class ReviewData:
    """Platform-agnostic review data transfer object."""
    platform: Platform
    external_id: str
    author: str
    rating: float
    text: str | None
    published_at: datetime


@runtime_checkable
class ReviewScraperProtocol(Protocol):
    """Protocol for review scrapers.

    Implement this to add a new scraping source (browser, API, etc.).
    """

    @property
    def platform(self) -> Platform: ...

    async def scrape(self, since: datetime | None = None) -> list[ReviewData]:
        """Scrape reviews published after `since`. If None — scrape all available."""
        ...

    async def close(self) -> None:
        """Cleanup resources (browser, connections, etc.)."""
        ...
