"""Find 2GIS reviews list API endpoint."""
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

    api_responses = []

    async def on_response(response):
        url = response.url
        # Capture ALL requests to 2gis APIs
        if '2gis' in url and ('api' in url or '.json' in url) and 'cachizer' not in url and 'assets' not in url:
            try:
                ct = response.headers.get('content-type', '')
                if 'json' in ct or 'javascript' in ct:
                    body = await response.text()
                    if len(body) > 1000:  # Only large responses
                        api_responses.append({
                            'url': url[:400],
                            'status': response.status,
                            'body_len': len(body),
                            'body_preview': body[:800],
                        })
            except Exception:
                pass

    page.on('response', on_response)

    print("=== Loading 2GIS page ===")
    await page.goto(TWOGIS_URL, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    # JS click load more once to trigger pagination API call
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            if (btn.textContent.includes('Загрузить ещё')) {
                btn.click();
                return true;
            }
        }
        return false;
    }""")
    await page.wait_for_timeout(3000)

    print(f"\n=== Found {len(api_responses)} large API responses ===")
    for r in api_responses:
        print(f"\nURL: {r['url']}")
        print(f"Status: {r['status']}, Body length: {r['body_len']}")
        print(f"Preview: {r['body_preview'][:600]}")

    await browser.close()
    await pw.stop()


asyncio.run(main())
