from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    postgres_user: str = "bublic"
    postgres_password: str = "bublic_secret"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "bublic_reviews"

    # Scraping targets
    twogis_url: str = (
        "https://2gis.ru/stavropol/branches/70000001018219934"
        "/firm/70000001018219935/41.918345%2C45.012166/tab/reviews"
    )
    yandex_url: str = (
        "https://yandex.com/maps/org/bublik/1390659107/reviews/"
        "?ll=41.918463%2C45.012415&z=14"
    )
    google_url: str = (
        "https://www.google.com/maps/place//data="
        "!4m2!3m1!1s0x40f9aa47b39946f7:0xa4fe975c8c941b8f"
    )

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
