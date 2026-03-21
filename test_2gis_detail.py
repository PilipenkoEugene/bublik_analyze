"""Detailed 2GIS review card structure analysis."""
import asyncio
from playwright.async_api import async_playwright

STEALTH_SCRIPTS = [
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
    """Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});""",
    """Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});""",
    "window.chrome = { runtime: {} };",
]

URL = (
    "https://2gis.ru/stavropol/branches/70000001018219934"
    "/firm/70000001018219935/41.918345%2C45.012166/tab/reviews"
)


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        locale="ru-RU", viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    )
    await context.add_init_script("\n".join(STEALTH_SCRIPTS))
    page = await context.new_page()

    await page.goto(URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    # Find the review cards by looking for elements containing author names
    print("=== 2GIS Review Card Structure ===\n")
    cards = await page.evaluate("""() => {
        // Find all author spans
        const authors = document.querySelectorAll('span._16s5yj36');
        const results = [];
        for (let i = 0; i < Math.min(authors.length, 3); i++) {
            const author = authors[i];
            // Walk up to find the review card container
            let card = author;
            for (let j = 0; j < 10; j++) {
                card = card.parentElement;
                if (!card) break;
                // A review card should contain: author, date, text, rating
                const text = card.textContent;
                if (text && text.length > 100 && card.offsetHeight > 80) {
                    // Found a likely card
                    results.push({
                        tag: card.tagName,
                        classes: card.className.substring(0, 150),
                        html: card.outerHTML.substring(0, 2000),
                        height: card.offsetHeight,
                        level: j,
                    });
                    break;
                }
            }
        }
        return results;
    }""")

    for i, card in enumerate(cards):
        print(f"\n--- Review Card {i} (level={card['level']}, h={card['height']}) ---")
        print(f"  <{card['tag']} class='{card['classes'][:100]}'>")
        print(f"  HTML preview:\n{card['html'][:1500]}")

    # Also find the scrollable container
    print("\n\n=== Scrollable container ===")
    container = await page.evaluate("""() => {
        const reviewsArea = document.querySelector('div[class*="reviews"]') ||
                           document.querySelector('[class*="scroll"]');
        // Try finding scrollable parent of reviews
        const authors = document.querySelectorAll('span._16s5yj36');
        if (authors.length === 0) return 'no authors found';

        let el = authors[0];
        for (let i = 0; i < 20; i++) {
            el = el.parentElement;
            if (!el) return 'reached top without finding scrollable';
            const style = window.getComputedStyle(el);
            if (style.overflow === 'auto' || style.overflow === 'scroll' ||
                style.overflowY === 'auto' || style.overflowY === 'scroll') {
                return {
                    tag: el.tagName,
                    classes: el.className.substring(0, 150),
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    level: i,
                };
            }
        }
        return 'no scrollable found';
    }""")
    print(f"  {container}")

    # Check total review count shown on page
    print("\n=== Review count on page ===")
    count_text = await page.evaluate("""() => {
        const els = document.querySelectorAll('*');
        for (const el of els) {
            const text = el.textContent.trim();
            if (text.match(/^\\d+\\s*(отзыв|оценк)/) && text.length < 30) {
                return {text: text, tag: el.tagName, classes: el.className.substring(0, 100)};
            }
        }
        return 'not found';
    }""")
    print(f"  {count_text}")

    # Find rating stars pattern
    print("\n=== Rating stars in first review ===")
    stars_info = await page.evaluate("""() => {
        const author = document.querySelector('span._16s5yj36');
        if (!author) return 'no author';
        let card = author;
        for (let i = 0; i < 10; i++) {
            card = card.parentElement;
            if (!card) break;
            if (card.offsetHeight > 80 && card.textContent.length > 100) break;
        }
        // Find star-like elements in card
        const allChildren = card.querySelectorAll('*');
        const results = [];
        for (const el of allChildren) {
            const cls = el.className;
            if (typeof cls !== 'string') continue;
            if (cls.includes('star') || cls.includes('icon') ||
                (el.tagName === 'svg') ||
                (el.getAttribute('style') || '').includes('color')) {
                results.push({
                    tag: el.tagName,
                    classes: cls.substring(0, 100),
                    style: (el.getAttribute('style') || '').substring(0, 80),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    children: el.children.length,
                });
            }
        }
        return results;
    }""")
    for s in stars_info:
        print(f"  <{s['tag']} class='{s['classes'][:70]}' aria='{s['ariaLabel']}' style='{s['style'][:50]}'>")

    # Find the review text elements
    print("\n=== Review text elements ===")
    texts = await page.evaluate("""() => {
        const authors = document.querySelectorAll('span._16s5yj36');
        const results = [];
        for (let i = 0; i < Math.min(3, authors.length); i++) {
            let card = authors[i];
            for (let j = 0; j < 10; j++) {
                card = card.parentElement;
                if (card && card.offsetHeight > 80 && card.textContent.length > 100) break;
            }
            // Find text content div (usually the largest text block)
            const divs = card.querySelectorAll('div, p, span');
            let longestText = '';
            let longestEl = null;
            for (const div of divs) {
                const directText = Array.from(div.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .join('');
                const innerText = div.textContent.trim();
                if (innerText.length > longestText.length && innerText.length < 2000 &&
                    !innerText.includes(authors[i].textContent)) {
                    longestText = innerText;
                    longestEl = div;
                }
            }
            if (longestEl) {
                results.push({
                    tag: longestEl.tagName,
                    classes: longestEl.className.substring(0, 100),
                    text: longestText.substring(0, 100),
                });
            }
        }
        return results;
    }""")
    for t in texts:
        print(f"  <{t['tag']} class='{t['classes'][:70]}'> \"{t['text'][:80]}\"")

    await browser.close()
    await pw.stop()


asyncio.run(main())
