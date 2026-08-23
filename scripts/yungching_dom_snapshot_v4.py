"""PREVIEW-only Yongching DOM snapshot v4.

The Yongching production search page was verified to expose real result pagination
through the `pg` query parameter. For example, `?od=80&pg=2` returned a distinct
second result page with new house IDs. Prefer direct Chromium navigation to `pg=N`
instead of clicking the visual pager, which can be covered by the site's AI overlay.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yungching_dom_snapshot_v3 as v3


def pg_url(url: str, target: int) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "pg"]
    query.append(("pg", str(target)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def direct_pg_page(page, target: int):
    """Navigate to Yongching's verified `pg=N` URL and require DOM activation."""
    before_pages = v3.pager_state(page)
    visible_pages = {
        str(x.get("text") or "").strip()
        for x in before_pages
        if str(x.get("text") or "").strip().isdigit()
    }

    # Do not guess nonexistent pages. The rendered pager must advertise the target.
    if str(target) not in visible_pages:
        return {
            "clicked": False,
            "mode": "yungching-direct-pg-v4",
            "target": target,
            "reason": "target page is not advertised by rendered pager",
            "beforePages": before_pages,
        }

    before_url = page.url
    target_url = pg_url(before_url, target)
    try:
        response = page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        http = response.status if response else None
        page.wait_for_timeout(1800)
        activated = v3.wait_pager_active(page, target, timeout=5000)
        after_pages = v3.pager_state(page)
        ok = bool(http == 200 and activated)
        return {
            "clicked": ok,
            "mode": "yungching-direct-pg-v4",
            "target": target,
            "http": http,
            "beforeUrl": before_url,
            "targetUrl": target_url,
            "finalUrl": page.url,
            "beforePages": before_pages,
            "afterPages": after_pages,
            "activeVerified": bool(activated),
            "error": None if ok else "pg navigation did not produce HTTP 200 + active target page",
        }
    except Exception as exc:
        return {
            "clicked": False,
            "mode": "yungching-direct-pg-v4",
            "target": target,
            "beforeUrl": before_url,
            "targetUrl": target_url,
            "error": f"{type(exc).__name__}: {str(exc)[:220]}",
        }


def click_numeric_page(page, target: int):
    # Primary path: verified direct page navigation.
    action = direct_pg_page(page, target)
    if action.get("clicked"):
        return action

    # Keep v3's strict click implementation only as a future DOM fallback.
    fallback = v3.click_numeric_page(page, target)
    fallback.setdefault("previousDirectPg", action)
    return fallback


def main():
    # v3.main patches the active PREVIEW collector with its global click_numeric_page.
    # Replace that global first so production code remains untouched while Preview uses
    # the verified `pg=N` route.
    v3.click_numeric_page = click_numeric_page
    v3.main()


if __name__ == "__main__":
    main()
