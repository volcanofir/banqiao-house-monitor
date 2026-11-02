"""Read-only 591 page-load diagnosis: legacy mobile redirect vs desktop search.

No listing pagination, authentication changes, response bodies, or writes.
Prints HTTP statuses, URL hosts/paths/query *keys*, and resource/error counts.
"""
import argparse
import asyncio
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright


URLS = {
    "legacy_mobile": (
        "https://m.591.com.tw/v2/sale?"
        "regionid=3&sectionidStr=26&o=32&streetid=27507&keywords=%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5"
    ),
    "bare_desktop": "https://sale.591.com.tw/",
    "clean_desktop": (
        "https://sale.591.com.tw/"
        "?regionid=3&section=26&firstRow=0&shType=list&type=2"
    ),
    "redirect_style_desktop": (
        "https://sale.591.com.tw/"
        "?regionid=3&sectionidStr=26&o=32&streetid=27507"
        "&keywords=%E4%B8%AD%E5%B1%B1%E8%B7%AF%E4%BA%8C%E6%AE%B5"
        "&type=2&shType=list&firstRow=0"
    ),
}


def display_url(value):
    parsed = urlsplit(value)
    query_keys = ",".join(sorted(parse_qs(parsed.query)))
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path} keys={query_keys or '-'}"


async def check(browser, name, target, environment):
    mobile = name == "legacy_mobile"
    context = await browser.new_context(
        locale="zh-TW", timezone_id="Asia/Taipei",
        viewport={"width": 390, "height": 844} if mobile else {"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ) if mobile else None,
        is_mobile=mobile,
        has_touch=mobile,
    )
    try:
        page = await context.new_page()
        documents = []
        resources = []
        failures = []
        page_errors = []

        def on_response(response):
            parsed = urlsplit(response.url)
            if response.request.is_navigation_request() and response.request.resource_type == "document":
                documents.append((response.status, display_url(response.url)))
            elif (parsed.hostname or "").endswith("591.com.tw") and response.request.resource_type in ("xhr", "fetch", "script"):
                resources.append((response.status, response.request.resource_type, display_url(response.url)))

        def on_failed(request):
            parsed = urlsplit(request.url)
            if (parsed.hostname or "").endswith("591.com.tw"):
                failures.append((request.resource_type, display_url(request.url)))

        page.on("response", on_response)
        page.on("requestfailed", on_failed)
        page.on("pageerror", lambda error: page_errors.append(type(error).__name__))

        status = "none"
        error = "none"
        response_header_clues = {}
        response_block_clues = []
        response_body_length = 0
        try:
            result = await page.goto(target, wait_until="domcontentloaded", timeout=25000)
            status = result.status if result else "none"
            if result and result.status >= 400:
                # Only metadata; never log response bodies, auth or cookies.
                headers = await result.all_headers()
                for key in ("server", "content-type", "cf-ray", "x-cache", "x-amz-cf-pop", "via", "x-request-id"):
                    if key in headers:
                        # Request IDs are often long, and are not needed verbatim.
                        response_header_clues[key] = "present" if key in ("cf-ray", "x-request-id") else headers[key][:120]
                body = (await result.text())[:32768].lower()
                response_body_length = len(body)
                response_block_clues = [word for word in ("access denied", "forbidden", "cloudflare", "captcha", "blocked", "request rejected", "reference #", "403") if word in body]
            await page.wait_for_timeout(4000)
        except Exception as exc:
            error = type(exc).__name__

        print(f"DESKTOP_LOAD_CHECK environment={environment} case={name}")
        print(f"entry={display_url(target)}")
        print(f"navigation_status={status} navigation_error={error}")
        print(f"final_url={display_url(page.url)}")
        # A 200 document can include the initial listing state even when no
        # subsequent XHR listing request occurs. Inspect markers only.
        if status == 200:
            try:
                html = await page.content()
                has_nuxt = "window.__NUXT__" in html
                has_initial_rows = "wareList:" in html
                has_total_marker = "wareTotal:" in html
                print(
                    "document_initial_data "
                    f"nuxt={has_nuxt} wareList={has_initial_rows} "
                    f"wareTotal={has_total_marker} "
                    f"houseid_keys={html.count('houseid:')}"
                )
            except Exception as exc:
                print(f"document_initial_data_error={type(exc).__name__}")
        print(f"error_header_clues={response_header_clues}")
        print(f"error_page_clues={response_block_clues} truncated_body_length={response_body_length}")
        for index, (code, url) in enumerate(documents[:8], 1):
            print(f"document_{index} code={code} {url}")

        api = [(code, kind, url) for code, kind, url in resources if "/v1/web/sale/list" in url or "/v1/touch/sale/list" in url]
        print(f"listing_api_seen={bool(api)} listing_api_http={[item[0] for item in api]}")
        print(f"site_resource_count={len(resources)} site_resource_http_403={sum(1 for x in resources if x[0]==403)}")
        for index, (code, kind, url) in enumerate(api[:6], 1):
            print(f"listing_api_{index} http={code} kind={kind} {url}")
        for index, (code, kind, url) in enumerate(resources[:12], 1):
            print(f"site_resource_{index} http={code} kind={kind} {url}")
        print(f"site_request_failures={len(failures)} page_js_errors={len(page_errors)}")
        for index, (kind, url) in enumerate(failures[:5], 1):
            print(f"request_failed_{index} kind={kind} {url}")
        print("NO_DATA_WRITTEN no response bodies, credentials, or page content logged")
    finally:
        await context.close()


async def main(env):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome", headless=True, args=["--disable-dev-shm-usage"]
        )
        try:
            for name, target in URLS.items():
                await check(browser, name, target, env)
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="direct")
    args = parser.parse_args()
    asyncio.run(main(args.label))
