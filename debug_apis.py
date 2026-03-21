"""Intercept API responses to find review data endpoints."""
import asyncio
from playwright.async_api import async_playwright

STEALTH_SCRIPTS = [
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
    """Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});""",
    """Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});""",
    "window.chrome = { runtime: {} };",
]

TWOGIS_URL = (
    "https://2gis.ru/stavropol/branches/70000001018219934"
    "/firm/70000001018219935/41.918345%2C45.012166/tab/reviews"
)

YANDEX_URL = (
    "https://yandex.com/maps/org/bublik/1390659107/reviews/"
    "?ll=41.918463%2C45.012415&z=14"
)


async def debug_2gis():
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

    api_responses = []

    async def on_response(response):
        url = response.url
        if any(k in url.lower() for k in ['review', 'comment', 'feedback', 'public-api']):
            try:
                body = await response.text()
                api_responses.append({
                    'url': url[:300],
                    'status': response.status,
                    'body_len': len(body),
                    'body_preview': body[:500],
                })
            except Exception:
                api_responses.append({'url': url[:300], 'status': response.status, 'body_len': -1})

    page.on('response', on_response)

    print("=== Loading 2GIS page ===")
    await page.goto(TWOGIS_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    # Use JS click to bypass overlay
    for i in range(5):
        clicked = await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('Загрузить ещё') || btn.textContent.includes('Ещё отзывы')) {
                    btn.click();
                    return btn.textContent.trim();
                }
            }
            return null;
        }""")
        if clicked:
            print(f"JS-clicked: '{clicked}' ({i+1})")
            await page.wait_for_timeout(3000)
        else:
            print(f"No button found at iteration {i+1}")
            break

    # Count reviews after loading
    count = await page.evaluate("""() => {
        return document.querySelectorAll('span[title][class*="_16s5yj"]').length;
    }""")
    print(f"\n2GIS reviews in DOM: {count}")

    # Check for overlay element
    overlay = await page.evaluate("""() => {
        const el = document.querySelector('div._n1367pl');
        if (!el) return 'not found';
        return {
            tag: el.tagName,
            classes: el.className,
            display: window.getComputedStyle(el).display,
            position: window.getComputedStyle(el).position,
            zIndex: window.getComputedStyle(el).zIndex,
            width: el.offsetWidth,
            height: el.offsetHeight,
        };
    }""")
    print(f"\nOverlay element: {overlay}")

    print(f"\n=== Found {len(api_responses)} API responses ===")
    for r in api_responses:
        print(f"\nURL: {r['url']}")
        print(f"Status: {r['status']}, Body length: {r['body_len']}")
        if r.get('body_preview'):
            print(f"Preview: {r['body_preview'][:400]}")

    await browser.close()
    await pw.stop()


async def debug_yandex():
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

    api_responses = []

    async def on_response(response):
        url = response.url
        if any(k in url.lower() for k in ['review', 'comment', 'feedback', 'ugc', 'orgpage']):
            try:
                body = await response.text()
                api_responses.append({
                    'url': url[:300],
                    'status': response.status,
                    'body_len': len(body),
                    'body_preview': body[:500],
                })
            except Exception:
                api_responses.append({'url': url[:300], 'status': response.status, 'body_len': -1})

    page.on('response', on_response)

    print("\n\n=== Loading Yandex page ===")
    await page.goto(YANDEX_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)

    # Scroll a few times
    for i in range(5):
        await page.evaluate("""() => {
            const c = document.querySelector('.scroll__container');
            if (c) c.scrollTop = c.scrollHeight;
        }""")
        await page.wait_for_timeout(2000)

    # Count reviews
    count = await page.evaluate("""() => {
        return document.querySelectorAll('div.business-reviews-card-view__review').length;
    }""")
    print(f"\nYandex reviews in DOM: {count}")

    # Check what the page shows as total review count
    total = await page.evaluate("""() => {
        const els = document.querySelectorAll('*');
        const results = [];
        for (const el of els) {
            const text = el.textContent.trim();
            if ((text.match(/\\d+\\s*(отзыв|оценк|review|rating)/) && text.length < 50) ||
                (text.match(/^\\d+$/) && el.parentElement &&
                 el.parentElement.textContent.includes('отзыв'))) {
                results.push({text: text.substring(0, 80), tag: el.tagName, cls: el.className.substring(0, 80)});
            }
        }
        return results.slice(0, 10);
    }""")
    print(f"\nTotal review count elements: {total}")

    print(f"\n=== Found {len(api_responses)} API responses ===")
    for r in api_responses:
        print(f"\nURL: {r['url']}")
        print(f"Status: {r['status']}, Body length: {r['body_len']}")
        if r.get('body_preview'):
            print(f"Preview: {r['body_preview'][:400]}")

    await browser.close()
    await pw.stop()


async def main():
    await debug_2gis()
    await debug_yandex()


asyncio.run(main())
