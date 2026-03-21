"""Debug selectors for 2GIS and Yandex Maps review pages."""
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


async def explore_page(context, url, name):
    page = await context.new_page()
    print(f"\n{'='*60}")
    print(f"Exploring: {name}")
    print(f"URL: {url[:80]}...")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(5000)

        title = await page.title()
        print(f"Title: {title}")

        # Dump page structure to find review containers
        structure = await page.evaluate("""() => {
            const results = [];
            // Find all elements that look like review containers
            const allDivs = document.querySelectorAll('div, article, section');
            const seen = new Set();
            for (const div of allDivs) {
                const classes = div.className;
                if (typeof classes !== 'string') continue;
                // Skip tiny elements
                if (div.offsetHeight < 50) continue;
                // Look for elements with review-like content (has stars + text)
                const text = div.textContent || '';
                if (text.length > 50 && text.length < 5000) {
                    const hasStars = div.querySelector('[class*="star"], [class*="rating"], [class*="icon"]');
                    const hasAuthor = text.match(/[А-Яа-яA-Za-z]{2,}/);
                    if (hasStars || hasAuthor) {
                        const key = classes.split(' ').filter(c => c.length > 3).slice(0, 3).join('.');
                        if (!seen.has(key) && key.length > 0) {
                            seen.add(key);
                            const childCount = div.parentElement ?
                                Array.from(div.parentElement.children).filter(c => c.className === div.className).length : 0;
                            results.push({
                                tag: div.tagName,
                                classes: classes.substring(0, 150),
                                textPreview: text.substring(0, 100).replace(/\\n/g, ' '),
                                childCount: childCount,
                                height: div.offsetHeight,
                                hasDataAttrs: Object.keys(div.dataset).join(','),
                            });
                        }
                    }
                }
            }
            return results.slice(0, 30);
        }""")

        print(f"\nPotential review containers ({len(structure)}):")
        for s in structure:
            if s['childCount'] > 2:
                print(f"  *** <{s['tag']} class='{s['classes'][:80]}'> siblings={s['childCount']} h={s['height']}")
                print(f"      text: {s['textPreview'][:80]}")

        # More targeted: find repeating sibling patterns (review cards)
        print("\n--- Repeating sibling patterns (likely review cards) ---")
        patterns = await page.evaluate("""() => {
            const results = [];
            const allParents = document.querySelectorAll('div, section, ul');
            for (const parent of allParents) {
                const children = Array.from(parent.children);
                if (children.length < 3) continue;
                // Check if children have similar classes
                const classGroups = {};
                for (const child of children) {
                    const cls = child.className;
                    if (!cls || typeof cls !== 'string' || cls.length < 3) continue;
                    if (!classGroups[cls]) classGroups[cls] = [];
                    classGroups[cls].push(child);
                }
                for (const [cls, els] of Object.entries(classGroups)) {
                    if (els.length >= 3 && els[0].offsetHeight > 50) {
                        const sample = els[0];
                        // Check if it looks like a review (has text content)
                        const text = sample.textContent || '';
                        if (text.length > 30) {
                            results.push({
                                parentClasses: parent.className.substring(0, 100),
                                childClasses: cls.substring(0, 100),
                                count: els.length,
                                sampleText: text.substring(0, 120).replace(/\\n/g, ' '),
                                sampleHeight: sample.offsetHeight,
                                childTag: sample.tagName,
                            });
                        }
                    }
                }
            }
            // Sort by count descending
            results.sort((a, b) => b.count - a.count);
            return results.slice(0, 15);
        }""")

        for p in patterns:
            print(f"  <{p['childTag']} class='{p['childClasses'][:70]}'> x{p['count']} (h={p['sampleHeight']})")
            print(f"    parent class='{p['parentClasses'][:70]}'")
            print(f"    sample: {p['sampleText'][:100]}")

        # Find star/rating elements
        print("\n--- Star/rating elements ---")
        stars = await page.evaluate("""() => {
            const results = [];
            const els = document.querySelectorAll('[class*="star"], [class*="rating"], [class*="Stars"], [class*="Rating"]');
            const seen = new Set();
            for (const el of els) {
                const cls = el.className;
                if (typeof cls !== 'string' || seen.has(cls)) continue;
                seen.add(cls);
                results.push({
                    tag: el.tagName,
                    classes: cls.substring(0, 120),
                    text: el.textContent.substring(0, 50),
                    childCount: el.children.length,
                    ariaLabel: el.getAttribute('aria-label') || '',
                });
            }
            return results.slice(0, 10);
        }""")
        for s in stars:
            print(f"  <{s['tag']} class='{s['classes'][:80]}'> children={s['childCount']} aria='{s['ariaLabel'][:50]}'")

        # Find date elements
        print("\n--- Date elements ---")
        dates = await page.evaluate("""() => {
            const months = ['январ', 'феврал', 'март', 'апрел', 'мая', 'июн', 'июл', 'август',
                           'сентябр', 'октябр', 'ноябр', 'декабр', 'назад', 'вчера', 'сегодня'];
            const results = [];
            const allEls = document.querySelectorAll('span, div, time, p');
            for (const el of allEls) {
                const text = el.textContent.trim().toLowerCase();
                if (text.length > 5 && text.length < 50 && months.some(m => text.includes(m))) {
                    // Make sure it's a leaf-ish element
                    if (el.children.length <= 1) {
                        results.push({
                            tag: el.tagName,
                            classes: el.className.substring(0, 100),
                            text: el.textContent.trim().substring(0, 50),
                        });
                    }
                }
            }
            return results.slice(0, 10);
        }""")
        for d in dates:
            print(f"  <{d['tag']} class='{d['classes'][:70]}'> \"{d['text']}\"")

        # Find author elements (names near review cards)
        print("\n--- Potential author elements ---")
        authors = await page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a, span');
            for (const el of links) {
                const text = el.textContent.trim();
                // Russian name pattern: 2+ words, each starting with uppercase Cyrillic
                if (text.match(/^[А-ЯЁ][а-яё]+\\s+[А-ЯЁ]/) && text.length < 60 && text.length > 3) {
                    results.push({
                        tag: el.tagName,
                        classes: el.className.substring(0, 100),
                        text: text.substring(0, 50),
                        href: el.getAttribute('href')?.substring(0, 50) || '',
                    });
                }
            }
            return results.slice(0, 8);
        }""")
        for a in authors:
            print(f"  <{a['tag']} class='{a['classes'][:70]}'> \"{a['text']}\"")

        # Find "show more" / pagination buttons
        print("\n--- Load more / pagination buttons ---")
        buttons = await page.evaluate("""() => {
            const results = [];
            const btns = document.querySelectorAll('button, a[role="button"]');
            for (const btn of btns) {
                const text = btn.textContent.trim().toLowerCase();
                if (text.includes('ещё') || text.includes('еще') || text.includes('показать') ||
                    text.includes('загрузить') || text.includes('далее') || text.includes('more')) {
                    results.push({
                        tag: btn.tagName,
                        classes: btn.className.substring(0, 100),
                        text: btn.textContent.trim().substring(0, 50),
                    });
                }
            }
            return results;
        }""")
        for b in buttons:
            print(f"  <{b['tag']} class='{b['classes'][:70]}'> \"{b['text']}\"")

        # Save screenshot
        await page.screenshot(path=f"/app/debug_{name}.png")

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await page.close()


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        locale="ru-RU",
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    await context.add_init_script("\n".join(STEALTH_SCRIPTS))

    await explore_page(context, TWOGIS_URL, "2gis")
    await explore_page(context, YANDEX_URL, "yandex")

    await browser.close()
    await pw.stop()


asyncio.run(main())
