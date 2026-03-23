import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)

_COOKIES_DIR = Path("/app/browser_data")

# Realistic stealth scripts
_STEALTH_SCRIPTS = [
    # Hide webdriver flag
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
    # Realistic plugins (Chrome PDF plugins)
    """Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const p = {
                0: {type: 'application/pdf', suffixes: 'pdf', description: 'PDF Viewer'},
                length: 1,
                item: (i) => p[i],
                namedItem: (n) => p[0],
                refresh: () => {},
                [Symbol.iterator]: function*() { yield p[0]; }
            };
            return [p];
        },
    });""",
    # Languages
    """Object.defineProperty(navigator, 'languages', {
        get: () => ['ru-RU', 'ru', 'en-US', 'en'],
    });""",
    # Platform
    """Object.defineProperty(navigator, 'platform', {
        get: () => 'Linux x86_64',
    });""",
    # Hardware concurrency
    """Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
    });""",
    # Device memory
    """Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
    });""",
    # Chrome runtime
    """window.chrome = {
        runtime: {
            onMessage: { addListener: () => {}, removeListener: () => {} },
            sendMessage: () => {},
        },
        loadTimes: () => ({
            commitLoadTime: Date.now() / 1000,
            connectionInfo: 'h2',
            finishDocumentLoadTime: Date.now() / 1000,
            finishLoadTime: Date.now() / 1000,
            firstPaintAfterLoadTime: 0,
            firstPaintTime: Date.now() / 1000,
            navigationType: 'Other',
            npnNegotiatedProtocol: 'h2',
            requestTime: Date.now() / 1000,
            startLoadTime: Date.now() / 1000,
            wasAlternateProtocolAvailable: false,
            wasFetchedViaSpdy: true,
            wasNpnNegotiated: true,
        }),
        csi: () => ({startE: Date.now(), onloadT: Date.now()}),
    };""",
    # Permissions
    """const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);""",
    # WebGL vendor/renderer
    """const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Google Inc. (NVIDIA)';
        if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650, OpenGL 4.5)';
        return getParameter.call(this, parameter);
    };""",
]

_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
]


async def random_delay(min_ms: int = 1000, max_ms: int = 3000) -> int:
    """Return a random delay in ms for use with page.wait_for_timeout."""
    return random.randint(min_ms, max_ms)


async def human_scroll(page, container_selector: str | None = None) -> None:
    """Scroll like a human — variable speed, small random mouse movements."""
    # Random mouse wiggle
    x = random.randint(300, 900)
    y = random.randint(200, 600)
    try:
        await page.mouse.move(x, y)
        await page.wait_for_timeout(random.randint(100, 400))
    except Exception:
        pass

    # Scroll
    if container_selector:
        await page.evaluate(f"""() => {{
            const el = document.querySelector('{container_selector}');
            if (el) el.scrollBy(0, {random.randint(400, 900)});
        }}""")
    else:
        await page.evaluate(f"window.scrollBy(0, {random.randint(400, 900)})")

    await page.wait_for_timeout(await random_delay(800, 2500))

    # Occasionally do a small extra scroll (humans aren't perfectly consistent)
    if random.random() < 0.3:
        await page.wait_for_timeout(random.randint(300, 800))
        if container_selector:
            await page.evaluate(f"""() => {{
                const el = document.querySelector('{container_selector}');
                if (el) el.scrollBy(0, {random.randint(100, 300)});
            }}""")
        else:
            await page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")


class BaseBrowserScraper:
    """Base class with shared Playwright browser logic."""

    def __init__(self, url: str, venue: str = "") -> None:
        self.url = url
        self.venue = venue
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._user_agent = random.choice(_USER_AGENTS)

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

    def _cookies_path(self) -> Path:
        """Per-platform cookies file."""
        name = self.__class__.__name__.lower().replace("scraper", "")
        return _COOKIES_DIR / f"cookies_{name}.json"

    async def _load_cookies(self, context: BrowserContext) -> None:
        """Load saved cookies into browser context."""
        path = self._cookies_path()
        if path.exists():
            try:
                cookies = json.loads(path.read_text())
                await context.add_cookies(cookies)
                logger.info("Loaded %d saved cookies for %s", len(cookies), path.name)
            except Exception as e:
                logger.debug("Failed to load cookies: %s", e)

    async def _save_cookies(self, context: BrowserContext) -> None:
        """Save browser cookies for reuse."""
        path = self._cookies_path()
        try:
            _COOKIES_DIR.mkdir(parents=True, exist_ok=True)
            cookies = await context.cookies()
            path.write_text(json.dumps(cookies, ensure_ascii=False))
            logger.debug("Saved %d cookies to %s", len(cookies), path.name)
        except Exception as e:
            logger.debug("Failed to save cookies: %s", e)

    async def _new_page(self) -> Page:
        browser = await self._get_browser()
        self._context = await browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            geolocation={"latitude": 45.0123, "longitude": 41.9185},
            permissions=["geolocation"],
            viewport={"width": 1280, "height": 900},
            user_agent=self._user_agent,
        )
        # Inject stealth scripts before any page navigation
        await self._context.add_init_script("\n".join(_STEALTH_SCRIPTS))
        # Load saved cookies
        await self._load_cookies(self._context)
        page = await self._context.new_page()
        return page

    async def close(self) -> None:
        if self._context:
            await self._save_cookies(self._context)
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
