import logging
import re
from datetime import datetime, timedelta, timezone

from src.db.models import Platform
from src.scrapers.base import BaseBrowserScraper
from src.scrapers.protocols import ReviewData

logger = logging.getLogger(__name__)


class GoogleMapsScraper(BaseBrowserScraper):
    """Scraper for Google Maps reviews using Playwright."""

    @property
    def platform(self) -> Platform:
        return Platform.GOOGLE

    async def scrape(self, since: datetime | None = None) -> list[ReviewData]:
        logger.info("Starting Google Maps scrape (since=%s): %s", since, self.url)
        page = await self._new_page()
        reviews: list[ReviewData] = []
        reached_old = False

        try:
            # Pre-load Google Maps homepage to establish cookies/session
            await page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Handle Google consent dialog (cookie popup)
            await self._accept_consent(page)

            # Now navigate to the place page
            await page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            logger.info("Page title: %s", await page.title())

            # Click on "Отзывы" tab
            await self._click_reviews_tab(page)

            # Sort by newest
            await self._sort_by_newest(page)

            # Debug: screenshot after setup
            await page.screenshot(path="/app/debug_google_reviews.png")

            # Find the scrollable reviews container
            scrollable = await self._find_scrollable(page)

            # Scroll to load reviews
            if scrollable:
                prev_count = 0
                stale_rounds = 0
                for scroll_i in range(300):
                    if reached_old:
                        break
                    try:
                        await scrollable.evaluate("el => el.scrollTop = el.scrollHeight")
                        await page.wait_for_timeout(1500)

                        # Count reviews to detect stale
                        current_count = await page.locator('div.jftiEf').count()
                        if current_count == 0:
                            current_count = await page.locator('div[data-review-id]').count()

                        if current_count > prev_count:
                            stale_rounds = 0
                            prev_count = current_count
                        else:
                            stale_rounds += 1

                        if stale_rounds >= 10:
                            logger.info("Google: no new reviews after %d stale rounds (total: %d)", stale_rounds, current_count)
                            break

                        if scroll_i % 20 == 19:
                            logger.info("Google scroll iteration %d, reviews: %d", scroll_i, current_count)

                        if since:
                            reached_old = await self._check_reached_old(page, since)
                    except Exception as e:
                        logger.debug("Scroll iteration %d failed: %s", scroll_i, e)
                        break
            else:
                logger.warning("Could not find scrollable reviews container")

            # Expand all review texts ("Ещё" / "More" buttons)
            await self._expand_reviews(page)

            # Parse reviews
            reviews = await self._parse_reviews(page, since)

        except Exception as e:
            logger.error("Google Maps scrape failed: %s", e)
            try:
                await page.screenshot(path="/app/debug_google_error.png")
            except Exception:
                pass
        finally:
            await page.close()

        logger.info("Scraped %d new reviews from Google Maps", len(reviews))
        return reviews

    async def _accept_consent(self, page) -> None:
        """Handle Google cookie consent dialog."""
        try:
            # Multiple possible consent button selectors
            consent_selectors = [
                'button:has-text("Принять все")',
                'button:has-text("Accept all")',
                'button:has-text("Agree")',
                'form[action*="consent"] button',
                '[aria-label="Accept all"]',
                'button:has-text("Согласен")',
            ]
            for selector in consent_selectors:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click()
                    await page.wait_for_timeout(2000)
                    logger.info("Accepted Google consent dialog")
                    return
        except Exception as e:
            logger.debug("No consent dialog or failed to accept: %s", e)

    async def _click_reviews_tab(self, page) -> None:
        """Click the 'Отзывы' (Reviews) tab to open full reviews list."""
        try:
            # Always click the reviews tab, even if some preview reviews are visible
            all_tabs = page.locator('button[role="tab"]')
            tab_count = await all_tabs.count()
            for i in range(tab_count):
                text = (await all_tabs.nth(i).inner_text()).strip()
                if "отзыв" in text.lower() or "review" in text.lower():
                    await all_tabs.nth(i).click()
                    await page.wait_for_timeout(3000)
                    logger.info("Clicked reviews tab: '%s'", text)
                    return

            # Fallback: click "Все отзывы" or review count link
            for selector in [
                'button:has-text("Все отзывы")',
                'a:has-text("Все отзывы")',
                'button:has-text("All reviews")',
            ]:
                el = page.locator(selector)
                if await el.count() > 0:
                    await el.first.click()
                    await page.wait_for_timeout(3000)
                    logger.info("Clicked '%s'", selector)
                    return

            # Fallback: click review count text like "Отзывов: 659"
            try:
                spans = page.locator('span, a, button')
                count = await spans.count()
                for i in range(min(count, 200)):
                    text = (await spans.nth(i).inner_text()).strip()
                    if re.search(r'отзывов:\s*\d+', text, re.IGNORECASE):
                        await spans.nth(i).click()
                        await page.wait_for_timeout(3000)
                        logger.info("Clicked review count: '%s'", text)
                        return
            except Exception:
                pass

            logger.warning("Could not find reviews tab (tabs found: %d)", tab_count)
        except Exception as e:
            logger.warning("Failed to click reviews tab: %s", e)

    async def _sort_by_newest(self, page) -> None:
        """Sort reviews by newest first."""
        try:
            sort_selectors = [
                'button[aria-label*="Сортировка"]',
                'button[aria-label*="Sort"]',
                'button[data-value="Сортировка"]',
                'button[data-value="Sort"]',
                'button.g88MCb',
            ]
            for selector in sort_selectors:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.first.click()
                    await page.wait_for_timeout(1500)

                    # Click "Newest" / "Сначала новые"
                    newest_selectors = [
                        'li[data-index="1"]',
                        'div[role="menuitemradio"]:nth-child(2)',
                        'div[data-index="1"]',
                        ':text("Сначала новые")',
                        ':text("Newest")',
                    ]
                    for ns in newest_selectors:
                        opt = page.locator(ns)
                        if await opt.count() > 0:
                            await opt.first.click()
                            await page.wait_for_timeout(3000)
                            logger.info("Sorted by newest")
                            return
            logger.debug("Could not sort by newest")
        except Exception as e:
            logger.debug("Sort failed: %s", e)

    async def _find_scrollable(self, page):
        """Find the scrollable reviews container."""
        selectors = [
            'div.m6QErb.DxyBCb.kA9KIf.dS8AEf',
            'div.m6QErb.DxyBCb',
            'div[role="main"] div.m6QErb',
            'div.review-dialog-list',
        ]
        for selector in selectors:
            el = page.locator(selector)
            if await el.count() > 0:
                logger.info("Found scrollable container: %s", selector)
                return el.first
        return None

    async def _check_reached_old(self, page, since: datetime) -> bool:
        """Check if the last visible review date is older than `since`."""
        try:
            date_selectors = ['span.rsqaWe', 'span.xRkPPb', 'span[class*="date"]']
            for sel in date_selectors:
                date_els = page.locator(sel)
                count = await date_els.count()
                if count > 0:
                    last_text = await date_els.nth(count - 1).inner_text()
                    last_date = self._parse_relative_date(last_text)
                    if last_date < since:
                        logger.info("Reached reviews older than %s, stopping scroll", since)
                        return True
                    return False
        except Exception:
            pass
        return False

    async def _expand_reviews(self, page) -> None:
        """Click all 'More' buttons to expand review texts."""
        try:
            buttons = page.locator('button.w8nwRe.kyuRq')
            count = await buttons.count()
            if count == 0:
                buttons = page.locator('button.w8nwRe')
                count = await buttons.count()
            if count > 0:
                logger.info("Expanding %d reviews...", count)
                # Use JavaScript to click all at once — much faster than individual clicks
                await page.evaluate("""() => {
                    document.querySelectorAll('button.w8nwRe.kyuRq, button.w8nwRe')
                        .forEach(btn => btn.click());
                }""")
                await page.wait_for_timeout(2000)
                logger.info("Expanded reviews via JS")
        except Exception as e:
            logger.debug("Failed to expand reviews: %s", e)

    async def _parse_reviews(self, page, since: datetime | None) -> list[ReviewData]:
        """Parse all visible reviews from the page."""
        reviews: list[ReviewData] = []

        # Try multiple review container selectors
        review_selectors = [
            'div.jftiEf.fontBodyMedium',
            'div.jftiEf',
            'div[data-review-id]',
            'div[class*="fontBodyMedium"][data-review-id]',
        ]

        review_elements = None
        for selector in review_selectors:
            el = page.locator(selector)
            count = await el.count()
            if count > 0:
                review_elements = el
                logger.info("Found %d reviews with selector: %s", count, selector)
                break

        if review_elements is None:
            # Debug: log page content snippet
            try:
                body_text = await page.locator('body').inner_text()
                logger.warning(
                    "No reviews found. Page text preview (500 chars): %s",
                    body_text[:500]
                )
                await page.screenshot(path="/app/debug_google_no_reviews.png")
            except Exception:
                pass
            return reviews

        count = await review_elements.count()
        for i in range(count):
            try:
                el = review_elements.nth(i)

                # Author
                author = "Unknown"
                for author_sel in ['div.d4r55', 'button.al6Kxe div', 'div.d4r55 span']:
                    author_el = el.locator(author_sel)
                    if await author_el.count() > 0:
                        author = (await author_el.first.inner_text()).strip()
                        break

                # Rating
                rating = 0.0
                for stars_sel in ['span.kvMYJc', 'span[role="img"]']:
                    stars_el = el.locator(stars_sel)
                    if await stars_el.count() > 0:
                        aria = await stars_el.first.get_attribute("aria-label") or ""
                        rating_match = re.search(r"(\d)", aria)
                        if rating_match:
                            rating = float(rating_match.group(1))
                            break

                # Date
                date_text = ""
                for date_sel in ['span.rsqaWe', 'span.xRkPPb', 'span[class*="date"]']:
                    date_el = el.locator(date_sel)
                    if await date_el.count() > 0:
                        date_text = await date_el.first.inner_text()
                        break

                published = self._parse_relative_date(date_text)

                # Skip old reviews
                if since and published <= since:
                    continue

                # Text — only user review, exclude owner response (.CDe7pd)
                text = None
                for text_sel in [
                    'div.MyEned span.wiI7pd',   # review text, not response
                    'span.wiI7pd',
                ]:
                    text_el = el.locator(text_sel)
                    if await text_el.count() > 0:
                        # Make sure it's NOT inside the owner response block
                        candidate = await text_el.first.inner_text()
                        candidate = candidate.strip()
                        if candidate:
                            text = candidate
                            break
                # Verify we didn't accidentally grab the owner response
                if text:
                    response_el = el.locator('div.CDe7pd span.wiI7pd')
                    if await response_el.count() > 0:
                        response_text = (await response_el.first.inner_text()).strip()
                        if text == response_text:
                            # We grabbed the response, not the review
                            text = None

                ext_id = self.generate_id("google", author, date_text, text or "")

                reviews.append(ReviewData(
                    platform=Platform.GOOGLE,
                    external_id=ext_id,
                    author=author,
                    rating=rating,
                    text=text if text else None,
                    published_at=published,
                ))
            except Exception as e:
                logger.warning("Failed to parse Google review #%d: %s", i, e)

        return reviews

    @staticmethod
    def _parse_relative_date(text: str) -> datetime:
        now = datetime.now(timezone.utc)
        if not text:
            return now

        text = text.lower().strip()

        # "N дней/недель/месяцев/лет назад" or "N days/weeks/months/years ago"
        numbers = re.findall(r"\d+", text)
        n = int(numbers[0]) if numbers else 1

        if any(w in text for w in ["минут", "мин", "minute", "min"]):
            return now - timedelta(minutes=n)
        if any(w in text for w in ["час", "hour"]):
            return now - timedelta(hours=n)
        if any(w in text for w in ["день", "дня", "дней", "day"]):
            return now - timedelta(days=n)
        if any(w in text for w in ["недел", "week"]):
            return now - timedelta(weeks=n)
        if any(w in text for w in ["месяц", "мес", "month"]):
            return now - timedelta(days=n * 30)
        if any(w in text for w in ["год", "года", "лет", "year"]):
            return now - timedelta(days=n * 365)

        return now
