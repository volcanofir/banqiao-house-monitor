"""Verify Sinyi source publication separately from all cross-platform grouping.

Checks both origin/main and the public Pages JSON plus its preview UI wiring.
A succeeded scrape/commit does NOT count as a successful publication if Pages
still serves an old, incomplete or different source snapshot.
No writes or listing/delisting decisions are performed here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from check_preview_source_freshness import sinyi_snapshot_error

SOURCE_PATH = "docs/preview/sinyi-source.json"
PAGES_JSON = "https://volcanofir.github.io/banqiao-house-monitor/preview/sinyi-source.json"
PAGES_HTML = "https://volcanofir.github.io/banqiao-house-monitor/preview/"


def parse_stamp(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Missing timezone")
    return stamp.astimezone(timezone.utc)


def verify_snapshot(expected, published, channel):
    """Require a complete published source at least as new as the captured feed.

    If timestamps are identical, all content must match, not just the count.
    Another concurrent independent source run may publish a NEWER verified
    snapshot while this run is waiting, and that is safe.
    """
    for label, payload in (("expected", expected), ("published", published)):
        if not isinstance(payload, dict):
            raise ValueError(f"{channel}: {label} source is not JSON object")
        reason = sinyi_snapshot_error(payload)
        if reason:
            raise ValueError(f"{channel}: {label} source invalid: {reason}")
    incoming = parse_stamp(expected["updatedAt"])
    observed = parse_stamp(published["updatedAt"])
    if observed < incoming:
        raise ValueError(
            f"{channel}: published snapshot is older: {published['updatedAt']} < {expected['updatedAt']}")
    if observed == incoming and expected != published:
        raise ValueError(f"{channel}: same timestamp but published source content differs")
    print(f"{channel}: verified published Sinyi {published['updatedAt']} / "
          f"{published['uniqueListingCount']} IDs")
    return published


def read_git_snapshot():
    subprocess.run(["git", "fetch", "--quiet", "origin", "main"], check=True)
    result = subprocess.run(
        ["git", "show", f"origin/main:{SOURCE_PATH}"],
        check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def fetch_text(url):
    # Fresh URL avoids intermediary caches serving the previous Pages deploy.
    separator = "&" if "?" in url else "?"
    url = f"{url}{separator}{urlencode({'verify_ts': time.time_ns()})}"
    req = Request(url, headers={
        "User-Agent": "BanqiaoHouseMonitor-PublicationVerifier/1.0",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
        "Cache-Control": "no-cache",
    })
    with urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return response.read().decode("utf-8")


def verify_public_site(expected, retries=12, delay=10):
    error = None
    for attempt in range(1, retries + 1):
        try:
            published = json.loads(fetch_text(PAGES_JSON))
            verify_snapshot(expected, published, "GitHub Pages JSON")
            html = fetch_text(PAGES_HTML)
            if "sinyi-source.json" not in html or "refreshLiveSourceReports" not in html:
                raise ValueError("GitHub Pages Preview does not load independent Sinyi source")
            print("GitHub Pages Preview: verified independent Sinyi feed URL is wired to status UI")
            return published
        except (OSError, ValueError, RuntimeError) as exc:
            error = exc
            print(f"::warning title=Sinyi Pages publish verification::{attempt}/{retries}: {exc}", flush=True)
            if attempt < retries:
                time.sleep(delay)
    raise RuntimeError(f"Sinyi Preview public publication not confirmed: {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--check-git", action="store_true")
    parser.add_argument("--check-pages", action="store_true")
    parser.add_argument("--retries", type=int, default=12)
    parser.add_argument("--delay", type=int, default=10)
    args = parser.parse_args()
    if not args.check_git and not args.check_pages:
        parser.error("Specify --check-git and/or --check-pages")
    if not 1 <= args.retries <= 30 or not 0 <= args.delay <= 60:
        parser.error("Invalid retries/delay")
    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    if args.check_git:
        verify_snapshot(expected, read_git_snapshot(), "origin/main")
    if args.check_pages:
        verify_public_site(expected, retries=args.retries, delay=args.delay)


if __name__ == "__main__":
    main()
