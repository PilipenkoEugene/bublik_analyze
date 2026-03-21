import hashlib
import logging
from datetime import datetime, timezone

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

# JS scripts to hide headless browser markers
_STEALTH_SCRIPTS = [
    # Hide webdriver flag
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
    # Fake plugins
    """Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });""",
    # Fake languages
    """Object.defineProperty(navigator, 'languages', {
        get: () => ['ru-RU', 'ru', 'en-US', 'en'],
    });""",
    # Chrome runtime
    "window.chrome = { runtime: {} };",
    # Permissions
    """const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);""",
]


class BaseBrowserScraper:
    """Base class with shared Playwright browser logic."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def _get_browser(self) -> Browser:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1280,900",
                ],
            )
        return self._browser

    async def _new_page(self) -> Page:
        browser = await self._get_browser()
        self._context = await browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        # Inject stealth scripts before any page navigation
        await self._context.add_init_script("\n".join(_STEALTH_SCRIPTS))
        page = await self._context.new_page()
        return page

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None

    @staticmethod
    def generate_id(platform: str, author: str, date_str: str, text: str = "") -> str:
        raw = f"{platform}:{author}:{date_str}:{text[:50]}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
