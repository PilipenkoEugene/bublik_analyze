import json
from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings


@dataclass
class Venue:
    name: str
    google: str
    yandex: str
    twogis: str


class Settings(BaseSettings):
    # Database
    postgres_user: str = "bublic"
    postgres_password: str = "bublic_secret"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "bublic_reviews"

    # Scheduler
    scheduler_hour: int = 1  # 01:00 MSK
    scheduler_minute: int = 0

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_prefix": "BUBLIC_"}


settings = Settings()


def load_venues() -> list[Venue]:
    """Load venue list from venues.json."""
    venues_path = Path("/app/venues.json")
    if not venues_path.exists():
        # Fallback for local dev
        venues_path = Path(__file__).parent.parent / "venues.json"
    data = json.loads(venues_path.read_text(encoding="utf-8"))
    return [Venue(**v) for v in data]
