import logging
import random
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from src.db.models import Platform
from src.scrapers.base import BaseBrowserScraper, human_scroll, random_delay
from src.scrapers.protocols import ReviewData

logger = logging.getLogger(__name__)


class YandexMapsScraper(BaseBrowserScraper):
    """Scraper for Yandex Maps reviews using API interception + DOM fallback."""

    @property
    def platform(self) -> Platform:
        return Platform.YANDEX

    async def scrape(self, since: datetime | None = None) -> list[ReviewData]:
        logger.info("Starting Yandex Maps scrape (since=%s): %s", since, self.url)
        page = await self._new_page()
        reviews: list[ReviewData] = []

        try:
            # Intercept fetchReviews API responses to capture review data
            api_reviews = []

            async def capture_reviews(response):
                if 'fetchReviews' in response.url:
                    try:
                        data = await response.json()
                        if 'data' in data and 'reviews' in data['data']:
                            api_reviews.extend(data['data']['reviews'])
                            logger.info("Captured %d reviews from API (total: %d)",
                                       len(data['data']['reviews']), len(api_reviews))
                    except Exception as e:
                        logger.debug("Failed to capture API response: %s", e)

            page.on('response', capture_reviews)

            # Load the page
            await page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(await random_delay(5000, 8000))

            logger.info("Yandex page title: %s", await page.title())

            # Sort by newest for incremental scraping
            await self._sort_by_newest(page)

            # Scroll to trigger all lazy-loaded API pages
            prev_api_count = 0
            stale_rounds = 0
            reached_old = False
            for i in range(200):
                if reached_old:
                    break

                # Human-like scroll: move mouse, scroll by variable amount
                await human_scroll(page, '.scroll__container')

                # Then scroll to absolute bottom to trigger lazy loading
                await page.evaluate("""() => {
                    const c = document.querySelector('.scroll__container');
                    if (c) c.scrollTop = c.scrollHeight;
                    let el = c;
                    for (let j = 0; j < 5 && el; j++) {
                        el = el.parentElement;
                        if (el) el.scrollTop = el.scrollHeight;
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                }""")
                await page.wait_for_timeout(await random_delay(500, 1500))

                # Track API captures
                if len(api_reviews) > prev_api_count:
                    stale_rounds = 0
                    prev_api_count = len(api_reviews)

                    # Check if latest API reviews are older than `since`
                    if since and api_reviews:
                        last_review = api_reviews[-1]
                        last_date = self._parse_api_date(last_review.get('updatedTime', ''))
                        if last_date < since:
                            logger.info("Yandex API: reached reviews older than %s, stopping", since)
                            reached_old = True
                else:
                    stale_rounds += 1

                if stale_rounds >= 8:
                    logger.info("No new API reviews after %d stale rounds (API: %d)", stale_rounds, len(api_reviews))
                    break

                if i % 10 == 9:
                    dom_count = await page.locator('div.business-reviews-card-view__review').count()
                    logger.info("Yandex scroll iteration %d, DOM: %d, API captured: %d", i, dom_count, len(api_reviews))

            # Now extract ALL reviews from DOM (includes page 1 SSR + pages loaded via API)
            # DOM has all reviews that were rendered, which is the complete set
            await self._expand_reviews(page)
            dom_reviews = await self._extract_reviews_dom(page, since)

            # Also parse API-captured reviews (these have better structured data)
            api_parsed = self._parse_api_reviews(api_reviews, since)

            # API has exact dates and text — always prefer it, DOM is fallback
            if api_parsed:
                reviews = api_parsed
                logger.info("Using API reviews (%d), DOM had %d", len(api_parsed), len(dom_reviews))
            else:
                reviews = dom_reviews
                logger.info("API empty, using DOM reviews (%d)", len(dom_reviews))

        except Exception as e:
            logger.error("Yandex Maps scrape failed: %s", e)
            try:
                await page.screenshot(path="/app/debug_yandex_error.png")
            except Exception:
                pass
        finally:
            await page.close()

        logger.info("Scraped %d new reviews from Yandex Maps", len(reviews))
        return reviews

    async def _sort_by_newest(self, page) -> None:
        """Sort Yandex reviews by newest first ('По новизне')."""
        try:
            # Step 1: find and click the sort trigger
            # It's a leaf element (no children with same text) near "отзывов"
            sort_btn = await page.evaluate("""() => {
                const keywords = ['по умолчанию', 'по новизне', 'по дате', 'сначала новые'];
                const all = document.querySelectorAll('span, a, button');
                for (const el of all) {
                    const text = el.textContent.trim().toLowerCase();
                    const ownText = el.childElementCount === 0 ? text : '';
                    // Must be a leaf or near-leaf with short text
                    if (text.length > 3 && text.length < 25) {
                        for (const kw of keywords) {
                            if (text.includes(kw)) {
                                el.click();
                                return el.textContent.trim();
                            }
                        }
                    }
                }
                return null;
            }""")
            if sort_btn:
                logger.info("Clicked Yandex sort dropdown: '%s'", sort_btn)
                await page.wait_for_timeout(await random_delay(1000, 2000))

                # Step 2: screenshot dropdown for debugging
                await page.screenshot(path="/app/debug_yandex_sort_dropdown.png")

                # Step 3: select "По новизне" from the dropdown
                # After clicking, a popup/menu appears with sort options
                selected = await page.evaluate("""() => {
                    const all = document.querySelectorAll(
                        'div[role="option"], div[role="menuitem"], div[role="listbox"] *, ' +
                        'li, span, a, button, label, div[class*="popup"] span, ' +
                        'div[class*="menu"] span, div[class*="select"] span'
                    );
                    for (const el of all) {
                        const text = el.textContent.trim().toLowerCase();
                        if (text.length < 20 && text.includes('новизне')) {
                            el.click();
                            return el.textContent.trim();
                        }
                    }
                    // Fallback: broader search
                    const all2 = document.querySelectorAll('*');
                    for (const el of all2) {
                        if (el.children.length > 0) continue;  // only leaf nodes
                        const text = el.textContent.trim().toLowerCase();
                        if (text === 'по новизне') {
                            el.click();
                            return el.textContent.trim();
                        }
                    }
                    return null;
                }""")
                if selected:
                    logger.info("Selected Yandex sort: '%s'", selected)
                    await page.wait_for_timeout(await random_delay(2000, 4000))
                else:
                    logger.warning("Could not find 'По новизне' in dropdown")
                    await page.screenshot(path="/app/debug_yandex_sort_fail.png")
                return

            logger.debug("Could not find Yandex sort dropdown")
        except Exception as e:
            logger.debug("Yandex sort failed: %s", e)

    async def _expand_reviews(self, page) -> None:
        try:
            await page.evaluate("""() => {
                document.querySelectorAll('div.business-reviews-card-view__review')
                    .forEach(review => {
                        const btn = review.querySelector('span[class*="more"], a[class*="more"]');
                        if (btn) btn.click();
                    });
            }""")
            await page.wait_for_timeout(1000)
        except Exception:
            pass

    def _parse_api_reviews(self, api_reviews: list, since: datetime | None) -> list[ReviewData]:
        """Parse reviews from Yandex API JSON format."""
        reviews = []
        for r in api_reviews:
            try:
                author = r.get('author', {}).get('name', 'Unknown')
                rating = r.get('rating', 5)
                text = r.get('text', None)
                review_id = r.get('reviewId', '')

                updated = r.get('updatedTime', '')
                published = self._parse_api_date(updated)

                if since and published <= since:
                    continue

                ext_id = review_id or self.generate_id("yandex", author, updated, text or "")
                reviews.append(ReviewData(
                    platform=Platform.YANDEX,
                    external_id=ext_id,
                    author=author,
                    rating=float(rating) if rating else 5.0,
                    text=text if text else None,
                    published_at=published,
                ))
            except Exception as e:
                logger.debug("Failed to parse API review: %s", e)
        return reviews

    @staticmethod
    def _parse_api_date(date_str: str) -> datetime:
        if not date_str:
            return datetime.now(timezone.utc)
        try:
            date_str = date_str.replace('Z', '+00:00')
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    async def _extract_reviews_dom(self, page, since: datetime | None) -> list[ReviewData]:
        """Extract reviews from DOM."""
        raw = await page.evaluate("""() => {
            const months = {
                'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
            };
            const results = [];
            const reviews = document.querySelectorAll('div.business-reviews-card-view__review');
            for (const review of reviews) {
                const authorEl = review.querySelector('a.business-review-view__link span, a.business-review-view__link');
                const author = authorEl ? authorEl.textContent.trim() : 'Unknown';

                let dateText = '';
                const spans = review.querySelectorAll('span');
                for (const span of spans) {
                    const text = span.textContent.trim().toLowerCase();
                    if (text.length > 3 && text.length < 30) {
                        for (const month of Object.keys(months)) {
                            if (text.includes(month)) {
                                dateText = span.textContent.trim();
                                break;
                            }
                        }
                        if (!dateText && (text.includes('назад') || text.includes('вчера') || text.includes('сегодня'))) {
                            dateText = span.textContent.trim();
                        }
                    }
                    if (dateText) break;
                }

                const filledStars = review.querySelectorAll(
                    'span.business-rating-badge-view__star._full, ' +
                    'span.inline-image._loaded[class*="star-icon_full"], ' +
                    'span[class*="star"][class*="_full"]'
                );
                let rating = filledStars.length || 5;

                // Only user review text, not org response
                const textEl = review.querySelector(
                    '.business-review-view__body-text, div[class*="review-text"]'
                );
                let text = textEl ? textEl.textContent.trim() : null;

                // Remove org response if it leaked in
                const responseEl = review.querySelector(
                    '.business-review-view__owner-response, .business-review-view__response'
                );
                if (responseEl && text) {
                    const responseText = responseEl.textContent.trim();
                    if (text.includes(responseText)) {
                        text = text.replace(responseText, '').trim();
                    }
                }
                // Clean up UI artifacts
                if (text) {
                    text = text.replace(/Посмотреть ещё/g, '').replace(/Показать полностью/g, '').trim();
                    if (text.length === 0) text = null;
                }

                results.push({author, dateText, rating, text});
            }
            return results;
        }""")

        logger.info("Found %d Yandex reviews via DOM", len(raw))
        reviews = []
        for r in raw:
            published = self._parse_dom_date(r["dateText"])
            if since and published <= since:
                continue
            ext_id = self.generate_id("yandex", r["author"], r["dateText"], r["text"] or "")
            reviews.append(ReviewData(
                platform=Platform.YANDEX,
                external_id=ext_id,
                author=r["author"],
                rating=float(r["rating"]) if r["rating"] > 0 else 5.0,
                text=r["text"],
                published_at=published,
            ))
        return reviews

    @staticmethod
    def _parse_dom_date(text: str) -> datetime:
        from datetime import timedelta

        _MONTHS_RU = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
        }
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
