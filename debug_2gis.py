"""Debug script to inspect current 2GIS review page structure."""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


URL = "https://2gis.ru/tyumen/firm/70000001075324004/tab/reviews?m=65.573518%2C57.120165%2F16"
COOKIES_PATH = Path("/app/browser_data/cookies_twogis.json")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
        )
        if COOKIES_PATH.exists():
            cookies = json.loads(COOKIES_PATH.read_text())
            await ctx.add_cookies(cookies)

        page = await ctx.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(5000)

        # Screenshot the page
        await page.screenshot(path="/app/debug_2gis_page.png", full_page=False)
        print("Screenshot saved to /app/debug_2gis_page.png")

        # Look for sort-related elements
        sort_info = await page.evaluate("""() => {
            const info = {selectors: [], buttons: [], dropdowns: []};

            // Find anything with "sort" in class
            document.querySelectorAll('[class*="sort"], [class*="Sort"]').forEach(el => {
                info.selectors.push({
                    tag: el.tagName,
                    class: el.className,
                    text: el.textContent.trim().slice(0, 100),
                    role: el.getAttribute('role'),
                });
            });

            // Find buttons/divs with sort-like text
            document.querySelectorAll('button, div[role="button"], [class*="dropdown"], [class*="select"]').forEach(el => {
                const text = el.textContent.trim();
                if (text.includes('доверию') || text.includes('дате') || text.includes('новые') ||
                    text.includes('Сортир') || text.includes('сортир') || text.includes('По ')) {
                    info.buttons.push({
                        tag: el.tagName,
                        class: el.className.slice(0, 120),
                        text: text.slice(0, 100),
                        role: el.getAttribute('role'),
                    });
                }
            });

            // Check for review cards
            const authors = document.querySelectorAll('span[title][class*="_16s5yj"]');
            info.authorCount = authors.length;

            // Check all span[title] elements
            const allTitles = document.querySelectorAll('span[title]');
            info.allTitleSpans = [];
            allTitles.forEach(el => {
                info.allTitleSpans.push({
                    class: el.className.slice(0, 80),
                    title: el.getAttribute('title').slice(0, 50),
                });
            });
            if (info.allTitleSpans.length > 20) {
                info.allTitleSpans = info.allTitleSpans.slice(0, 20);
                info.allTitleSpansTruncated = true;
            }

            // Tab/review section
            const tabReviews = document.querySelector('[class*="tab"][class*="review"], [data-name="reviews"]');
            if (tabReviews) {
                info.reviewTab = {class: tabReviews.className, text: tabReviews.textContent.trim().slice(0, 100)};
            }

            // Page title
            info.title = document.title;

            return info;
        }""")
        print(json.dumps(sort_info, indent=2, ensure_ascii=False))

        await browser.close()


asyncio.run(main())
