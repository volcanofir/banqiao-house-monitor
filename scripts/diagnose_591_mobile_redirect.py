"""Read-only diagnosis of 591 mobile entry navigation in GitHub Actions.

Records only navigation host/path, HTTP status, redirect Location host/path,
and whether the original mobile listing API appears. Does not scrape listings,
copy cookies, store credentials, or modify preview/canonical data.
"""
import argparse
import asyncio
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import async_playwright


def public_url(url):
    parts = urlsplit(url)
    keys = ",".join(sorted(parse_qs(parts.query)))
    return f"{parts.scheme}://{parts.netloc}{parts.path} [query keys: {keys or '-'}]"


async def diagnose(label):
    params = {
        "regionid": "3",
        "sectionidStr": "26",
        "o": "32",
        "streetid": "27507",
        "keywords": "中山路二段",
    }
    entry = "https://m.591.com.tw/v2/sale?" + urlencode(params)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="chrome", headless=True, args=["--disable-dev-shm-usage"]
        )
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                locale="zh-TW",
                timezone_id="Asia/Taipei",
            )
            try:
                page = await context.new_page()
                documents = []
                frames = []
                api_responses = []
                failures = []

                def on_response(response):
                    request = response.request
                    if request.resource_type == "document" and request.is_navigation_request():
                        location = response.headers.get("location", "")
                        documents.append({
                            "status": response.status,
                            "url": public_url(response.url),
                            "location": public_url(location) if location.startswith("http") else location[:100],
                        })
                    elif "bff-house.591.com.tw" in urlsplit(response.url).netloc:
                        api_responses.append({
                            "status": response.status,
                            "url": public_url(response.url),
                        })

                def on_navigation(frame):
                    if frame == page.main_frame:
                        frames.append(public_url(frame.url))

                def on_failure(request):
                    if request.is_navigation_request():
                        failures.append(public_url(request.url))

                async def block_media(route):
                    if route.request.resource_type in {"image", "font", "media"}:
                        await route.abort()
                    else:
                        await route.continue_()

                page.on("response", on_response)
                page.on("framenavigated", on_navigation)
                page.on("requestfailed", on_failure)
                await page.route("**/*", block_media)
                first_status = "none"
                error = "none"
                try:
                    response = await page.goto(
                        entry, wait_until="domcontentloaded", timeout=25000
                    )
                    first_status = response.status if response else "none"
                    await page.wait_for_timeout(7000)
                except Exception as exc:
                    error = type(exc).__name__

                print(f"591_REDIRECT_DIAGNOSTIC environment={label}")
                print(f"entry={public_url(entry)}")
                print(f"page_goto_final_http={first_status}")
                print(f"final_page={public_url(page.url)}")
                print(f"navigation_error={error}")
                for step, item in enumerate(documents, 1):
                    print(f"document_{step} status={item['status']} url={item['url']}")
                    if item["location"]:
                        print(f"document_{step} redirect_location={item['location']}")
                for step, url in enumerate(frames, 1):
                    print(f"main_frame_{step}={url}")
                for step, item in enumerate(api_responses[:12], 1):
                    print(f"api_{step} status={item['status']} url={item['url']}")
                print(f"api_total={len(api_responses)}")
                print(f"mobile_list_api_seen={any('/v1/touch/sale/list' in item['url'] for item in api_responses)}")
                print(f"document_request_failures={len(failures)}")
                for step, item in enumerate(failures[:4], 1):
                    print(f"failed_document_{step}={item}")
                print("DIAGNOSTIC_ONLY no credentials, listings, or site data written")
            finally:
                await context.close()
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="direct")
    args = parser.parse_args()
    asyncio.run(diagnose(args.label))
