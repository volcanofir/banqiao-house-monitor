"""Read-only 591 public mobile homepage navigation check.

Observes only publicly visible link categories, navigation statuses, hosts/paths
and API path/status metadata. Does not extract house records or session data.
"""
import asyncio
from urllib.parse import urljoin, urlsplit, parse_qs

from playwright.async_api import async_playwright

HOME = "https://m.591.com.tw/v2/"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)


def safe_url(value):
    p = urlsplit(value)
    return f"{p.scheme}://{p.netloc}{p.path} query_keys={','.join(sorted(parse_qs(p.query))) or '-'}"


async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True, args=["--disable-dev-shm-usage"])
        try:
            context = await browser.new_context(
                user_agent=UA, viewport={"width": 390, "height": 844},
                is_mobile=True, has_touch=True, locale="zh-TW", timezone_id="Asia/Taipei"
            )
            try:
                page = await context.new_page()
                navigation = []
                api_responses = []

                def on_response(resp):
                    if resp.request.resource_type == "document" and resp.request.is_navigation_request():
                        navigation.append((resp.status, safe_url(resp.url)))
                    elif urlsplit(resp.url).hostname == "bff-house.591.com.tw" and (
                        "sale" in urlsplit(resp.url).path
                    ):
                        api_responses.append((resp.status, safe_url(resp.url)))

                page.on("response", on_response)

                try:
                    res = await page.goto(HOME, wait_until="domcontentloaded", timeout=22000)
                    print(f"home_navigation={res.status if res else 'none'} {safe_url(page.url)}")
                    await page.wait_for_timeout(3000)
                    candidates = await page.locator("a[href]").evaluate_all(
                        """els => els.map((e, i) => ({
                            i, label: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0,30),
                            href: e.getAttribute('href') || ''
                        })).filter(x => /中古屋|買屋|買房|售屋/.test(x.label)).slice(0, 15)"""
                    )
                    print(f"home_sale_link_candidates={len(candidates)}")
                    for c in candidates:
                        print(f"home_link label={c['label'][:20]!r} {safe_url(urljoin(HOME, c['href']))}")
                    # Follow a normal visible site link; do not change headers or bypass refusals.
                    chosen = next((x for x in candidates if x["label"] in ("中古屋", "買屋", "買房", "售屋")), None)
                    if chosen is None:
                        chosen = next((x for x in candidates if "sale.591.com.tw" in urljoin(HOME,x["href"])), None)
                    if chosen:
                        print(f"chosen_link={safe_url(urljoin(HOME,chosen['href']))}")
                        try:
                            # Navigate with the existing page/context, not a synthetic API request.
                            target = urljoin(HOME, chosen["href"])
                            res = await page.goto(target, wait_until="domcontentloaded", timeout=22000)
                            await page.wait_for_timeout(3500)
                            html = await page.content() if res and res.status == 200 else ""
                            print(
                                f"sale_navigation={res.status if res else 'none'} {safe_url(page.url)} "
                                f"has_nuxt={'window.__NUXT__' in html} "
                                f"has_wareList={'wareList' in html}"
                            )
                        except Exception as e:
                            print(f"sale_navigation_error={type(e).__name__}")
                    else:
                        print("sale_link_not_detected")
                except Exception as exc:
                    print(f"home_navigation_error={type(exc).__name__}")
                print(f"document_chain={navigation[:8]}")
                print(f"sale_api_responses={api_responses[:8]}")
                print("READ_ONLY no credentials or listing contents collected, no protected files changed")
            finally:
                await context.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(inspect())
