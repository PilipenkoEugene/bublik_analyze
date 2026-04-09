import logging
import re
from datetime import datetime, timedelta, timezone

from src.db.models import Platform
from src.scrapers.base import BaseBrowserScraper
from src.scrapers.protocols import ReviewData

logger = logging.getLogger(__name__)

_MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


class TwoGisScraper(BaseBrowserScraper):
    """Scraper for 2GIS reviews using Playwright."""

    @property
    def platform(self) -> Platform:
        return Platform.TWOGIS

    async def _new_page(self):
        """Override to skip cookie loading — stale 2GIS cookies cause Sber ID redirects."""
        from playwright.async_api import async_playwright
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
        self._context = await self._browser.new_context(
            locale="ru-RU",
            timezone_id="Asia/Yekaterinburg",
            viewport={"width": 1280, "height": 900},
            user_agent=self._user_agent,
        )
        from src.scrapers.base import _STEALTH_SCRIPTS
        await self._context.add_init_script("\n".join(_STEALTH_SCRIPTS))
        # Deliberately skip cookie loading for 2GIS
        return await self._context.new_page()

    async def scrape(self, since: datetime | None = None) -> list[ReviewData]:
        logger.info("Starting 2GIS scrape (since=%s): %s", since, self.url)
        page = await self._new_page()
        reviews: list[ReviewData] = []

        try:
            await page.goto(self.url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            # Check for captcha or broken page
            title = await page.title()
            if "captcha" in title.lower():
                logger.error("2GIS captcha detected for %s (title: %s)", self.venue, title)
                await page.screenshot(path="/app/browser_data/debug_2gis_captcha.png")
                return reviews

            # Ensure URL has /tab/reviews so page loads reviews directly
            current_url = page.url
            if "/tab/reviews" not in current_url:
                # Navigate to reviews tab URL
                reviews_url = current_url.split("?")[0].rstrip("/") + "/tab/reviews"
                query = current_url.split("?")[1] if "?" in current_url else ""
                if query:
                    reviews_url += "?" + query
                logger.info("2GIS: redirecting to reviews tab: %s", reviews_url)
                await page.goto(reviews_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

            # Sort by newest
            await self._sort_by_newest(page)

            # Load all reviews by clicking "Загрузить ещё" repeatedly
            await self._load_all_reviews(page, since)

            # Extract reviews via JS for speed and reliability
            reviews = await self._extract_reviews_js(page, since)

            if not reviews:
                title = await page.title()
                logger.warning("2GIS: 0 reviews extracted for %s (title: %s)", self.venue, title)
                await page.screenshot(path="/app/browser_data/debug_2gis_empty.png")

        except Exception as e:
            logger.error("2GIS scrape failed: %s", e)
            try:
                await page.screenshot(path="/app/debug_2gis_error.png")
            except Exception:
                pass
        finally:
            await page.close()

        logger.info("Scraped %d new reviews from 2GIS", len(reviews))
        return reviews

    async def _sort_by_newest(self, page) -> None:
        try:
            # Dismiss 2GIS sort-change banner if present
            await page.evaluate("""() => {
                document.querySelectorAll('div').forEach(el => {
                    if (el.textContent.includes('Изменили сортировку') && el.offsetHeight > 0) {
                        const close = el.querySelector('button, [class*="close"], [class*="dismiss"]');
                        if (close) close.click();
                    }
                });
            }""")
            await page.wait_for_timeout(500)

            # 2GIS new layout: sort selector is a clickable div showing current sort
            # e.g. div._8pvfb2 with text "По доверию", options in sibling div._1u9fru1
            sorted = await page.evaluate("""() => {
                // Find the sort trigger — a small div whose own text is exactly a sort label
                const labels = ['По доверию', 'По новизне'];
                const allDivs = document.querySelectorAll('div');
                for (const div of allDivs) {
                    const ownText = div.childNodes.length <= 2
                        ? div.textContent.trim() : '';
                    if (labels.includes(ownText) && div.offsetHeight > 0 &&
                        div.offsetHeight < 60 && div.offsetWidth < 250) {
                        // This looks like the sort trigger — click it to open dropdown
                        div.click();
                        return 'clicked_trigger: ' + ownText;
                    }
                }
                return null;
            }""")
            if sorted:
                logger.info("2GIS sort: %s", sorted)
                await page.wait_for_timeout(1000)

                # Now find and click "По новизне" option
                clicked = await page.evaluate("""() => {
                    const allDivs = document.querySelectorAll('div');
                    for (const div of allDivs) {
                        const text = div.textContent.trim();
                        if (text === 'По новизне' && div.offsetHeight > 0 &&
                            div.children.length === 0) {
                            div.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if clicked:
                    await page.wait_for_timeout(2000)
                    logger.info("Sorted 2GIS reviews by newest")
                else:
                    logger.warning("2GIS: could not find 'По новизне' option")
            else:
                logger.warning("2GIS sort trigger not found on page")
        except Exception as e:
            logger.warning("Could not sort 2GIS reviews: %s", e)

    async def _load_all_reviews(self, page, since: datetime | None) -> None:
        """Click 'Загрузить ещё' button and scroll to load all reviews."""
        stale_rounds = 0
        prev_count = 0

        # First, find the scrollable container for reviews
        scroll_selector = await page.evaluate("""() => {
            const authors = document.querySelectorAll('span[title][class*="_16s5yj"]');
            if (authors.length === 0) return null;
            let el = authors[0];
            for (let i = 0; i < 20; i++) {
                el = el.parentElement;
                if (!el) return null;
                const style = window.getComputedStyle(el);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                    style.overflow === 'auto' || style.overflow === 'scroll') {
                    if (el.id) return '#' + el.id;
                    if (el.className) return '.' + el.className.split(' ').filter(c => c).join('.');
                    return null;
                }
            }
            return null;
        }""")
        logger.info("2GIS scrollable selector: %s", scroll_selector)

        for i in range(200):  # up to 200 iterations
            try:
                # Scroll to bottom — try scrollable container and page
                if scroll_selector:
                    await page.evaluate(f"""() => {{
                        const el = document.querySelector('{scroll_selector}');
                        if (el) el.scrollTop = el.scrollHeight;
                    }}""")
                await page.evaluate("""() => {
                    window.scrollTo(0, document.body.scrollHeight);
                    // Also scroll all parents of review cards
                    const authors = document.querySelectorAll('span[title][class*="_16s5yj"]');
                    if (authors.length > 0) {
                        let el = authors[authors.length - 1];
                        for (let i = 0; i < 10 && el; i++) {
                            el = el.parentElement;
                            if (el) el.scrollTop = el.scrollHeight;
                        }
                    }
                }""")
                await page.wait_for_timeout(1000)

                # Use JS click to bypass overlay that blocks Playwright clicks
                clicked = await page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const text = btn.textContent.trim();
                        if (text.includes('Загрузить ещё') || text.includes('Ещё отзывы') ||
                            text.includes('Показать ещё')) {
                            btn.scrollIntoView({block: 'center'});
                            btn.click();
                            return text;
                        }
                    }
                    return null;
                }""")
                if clicked:
                    await page.wait_for_timeout(2500)
                    if i == 0:
                        logger.info("Found and JS-clicked '%s' button", clicked)

                # Count reviews to detect stale loading — THIS is the only stale check
                current_count = await page.locator('span[title][class*="_16s5yj"]').count()
                if current_count > prev_count:
                    stale_rounds = 0
                    prev_count = current_count
                else:
                    stale_rounds += 1

                if stale_rounds >= 8:
                    logger.info("No new reviews after %d stale rounds at iteration %d (total: %d)", stale_rounds, i, current_count)
                    break

                # Check if we've reached old reviews (early termination)
                if since and i % 5 == 4:
                    dates = page.locator('div[class*="_a5f6uz"]')
                    count = await dates.count()
                    if count > 0:
                        last_text = await dates.nth(count - 1).inner_text()
                        if self._parse_date(last_text) < since:
                            logger.info("Reached reviews older than %s at iteration %d", since, i)
                            break

                if i % 10 == 9:
                    logger.info("2GIS load iteration %d, reviews: %d", i, current_count)
            except Exception as e:
                logger.debug("2GIS load iteration %d error: %s", i, e)
                break

    async def _extract_reviews_js(self, page, since: datetime | None) -> list[ReviewData]:
        """Extract all reviews using JS evaluation for speed."""
        raw = await page.evaluate("""() => {
            const results = [];
            // Find all review cards by author span
            const authors = document.querySelectorAll('span[title][class*="_16s5yj"]');
            for (const authorEl of authors) {
                // Walk up to find the card container
                let card = authorEl;
                for (let j = 0; j < 10; j++) {
                    card = card.parentElement;
                    if (!card) break;
                    if (card.offsetHeight > 80 && card.textContent.length > 50) break;
                }
                if (!card) continue;

                const author = authorEl.getAttribute('title') || authorEl.textContent.trim();

                // Date — div with date-like class
                const dateEl = card.querySelector('div[class*="_a5f6uz"], div[class*="date"]');
                const dateText = dateEl ? dateEl.textContent.trim() : '';

                // Rating — count stars by width of filled container
                let rating = 5;
                const starsContainer = card.querySelector('div[class*="_1fkin5c"]');
                if (starsContainer) {
                    const style = starsContainer.getAttribute('style') || '';
                    const widthMatch = style.match(/width:\\s*(\\d+)px/);
                    if (widthMatch) {
                        rating = Math.round(parseInt(widthMatch[1]) / 10);
                    }
                }

                // Text — only the user's review text, not org response
                const textEls = card.querySelectorAll('div[class*="_49x36f"], div[class*="_1i94jn5"]');
                let text = '';
                for (const te of textEls) {
                    // Skip elements that are inside an org response block
                    // (response blocks contain "официальный ответ" in sibling/parent text)
                    let inResponse = false;
                    let parent = te.parentElement;
                    for (let k = 0; k < 3 && parent; k++) {
                        const parentText = parent.textContent || '';
                        if (parentText.includes('официальный ответ') ||
                            parentText.includes('Ответ организации') ||
                            parentText.includes('Ответ представителя')) {
                            // Only mark as response if this element IS the response part
                            // Check if the element itself contains the response marker
                            const elText = te.textContent || '';
                            if (elText.includes('официальный ответ') ||
                                elText.includes('Ответ организации') ||
                                elText.includes('здравствуйте')) {
                                inResponse = true;
                                break;
                            }
                        }
                        parent = parent.parentElement;
                    }
                    if (inResponse) continue;

                    const t = te.textContent.trim();
                    if (t.includes(author)) continue;
                    if (t.length > text.length) {
                        text = t;
                    }
                }

                // Post-process: clean up UI artifacts and org response leaks
                if (text) {
                    // Cut off everything after org response markers
                    const responseMarkers = [
                        /\d*\??(Бублик|бублик),?\s*детский.*/s,
                        /официальный ответ.*/si,
                        /Ответ организации.*/si,
                        /Ответ представителя.*/si,
                    ];
                    for (const marker of responseMarkers) {
                        text = text.replace(marker, '');
                    }
                    // Clean UI button text
                    text = text
                        .replace(/Читать целиком/g, '')
                        .replace(/Полезно?\s*\d*/g, '')
                        .replace(/Не полезно/g, '')
                        .replace(/Посмотреть ещё/g, '')
                        .replace(/Показать полностью/g, '')
                        .replace(/Ответить/g, '')
                        .replace(/\d+\s*$/, '')  // trailing rating number
                        .trim();
                }

                results.push({author, dateText, rating, text: text || null});
            }
            return results;
        }""")

        logger.info("Found %d 2GIS reviews via JS", len(raw))

        reviews = []
        for r in raw:
            published = self._parse_date(r["dateText"])
            if since and published <= since:
                continue

            ext_id = self.generate_id("twogis", r["author"], r["dateText"], r["text"] or "")
            reviews.append(ReviewData(
                venue=self.venue,
                platform=Platform.TWOGIS,
                external_id=ext_id,
                author=r["author"],
                rating=float(r["rating"]) if r["rating"] > 0 else 5.0,
                text=r["text"],
                published_at=published,
            ))

        return reviews

    @staticmethod
    def _parse_date(text: str) -> datetime:
        text = text.lower().strip()
        now = datetime.now(timezone.utc)

        for month_name, month_num in _MONTHS_RU.items():
            if month_name in text:
                numbers = re.findall(r"\d+", text)
                if len(numbers) >= 2:
                    day = int(numbers[0])
                    year = int(numbers[1]) if int(numbers[1]) > 31 else now.year
                    try:
                        return datetime(year, month_num, day, tzinfo=timezone.utc)
                    except ValueError:
                        pass
                elif len(numbers) == 1:
                    day = int(numbers[0])
                    try:
                        return datetime(now.year, month_num, day, tzinfo=timezone.utc)
                    except ValueError:
                        pass

        if "вчера" in text:
            return now - timedelta(days=1)
        if "сегодня" in text:
            return now
        if "назад" in text:
            numbers = re.findall(r"\d+", text)
            n = int(numbers[0]) if numbers else 1
            if "минут" in text or "мин" in text:
                return now - timedelta(minutes=n)
            if "час" in text:
                return now - timedelta(hours=n)
            if "день" in text or "дня" in text or "дней" in text:
                return now - timedelta(days=n)
            if "недел" in text:
                return now - timedelta(weeks=n)
            if "месяц" in text or "мес" in text:
                return now - timedelta(days=n * 30)
            if "год" in text or "лет" in text:
                return now - timedelta(days=n * 365)

        return now
