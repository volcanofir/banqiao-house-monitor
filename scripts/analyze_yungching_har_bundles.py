"""Discover public endpoint paths embedded in Yongching JavaScript captured in HAR.

Only public route strings and bundle paths are persisted. Request headers, cookies,
query values, response bodies and source code snippets are never written out.
"""

import base64
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


HAR = Path("artifacts/yungching-har/yungching-network.har")
OUT = Path("docs/preview/yungching-har-bundle-routes.json")
YUNGCHING_HOSTS = {
    "buy.yungching.com.tw",
    "www.yungching.com.tw",
    "memberyc.yungching.com.tw",
}


def content_text(content: dict) -> str:
    text = content.get("text")
    if not isinstance(text, str):
        return ""
    if content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    return text


def safe_route(raw: str) -> str | None:
    raw = raw.replace("\\/", "/").strip()
    raw = raw.replace("\\u002F", "/")
    raw = raw.split("#", 1)[0]
    if raw.startswith("http://") or raw.startswith("https://"):
        p = urlsplit(raw)
        if p.hostname not in YUNGCHING_HOSTS:
            return None
        path = p.path
        keys = sorted({k for k, _ in parse_qsl(p.query, keep_blank_values=True)})
    else:
        if not raw.startswith("/"):
            return None
        p = urlsplit(raw)
        path = p.path
        keys = sorted({k for k, _ in parse_qsl(p.query, keep_blank_values=True)})
    path = re.sub(r"[^A-Za-z0-9_./{}:$@+~-]+$", "", path)
    if len(path) < 4 or len(path) > 220:
        return None
    # Keep only routes that look data-bearing rather than static assets.
    low = path.lower()
    if not any(x in low for x in ("/api/", "graphql", "search", "house", "list", "mansion", "property", "recommend")):
        return None
    if low.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".woff", ".woff2")):
        return None
    return path + (("?" + "&".join(f"{k}=…" for k in keys)) if keys else "")


def extract_routes(text: str) -> set[str]:
    found = set()
    patterns = [
        r"https?://(?:buy|www|memberyc)\.yungching\.com\.tw/[A-Za-z0-9_./?=&%${}:@+~,-]{3,240}",
        r"/(?:api|graphql|search|house|list|mansion|property|recommend)[A-Za-z0-9_./?=&%${}:@+~,-]{2,220}",
    ]
    for pat in patterns:
        for m in re.findall(pat, text, flags=re.I):
            route = safe_route(m)
            if route:
                found.add(route)
    return found


def main():
    har = json.loads(HAR.read_text(encoding="utf-8"))
    entries = ((har.get("log") or {}).get("entries") or [])
    route_sources = defaultdict(set)
    route_occurrences = defaultdict(int)
    bundle_stats = []

    for e in entries:
        req = e.get("request") or {}
        resp = e.get("response") or {}
        url = str(req.get("url") or "")
        p = urlsplit(url)
        if p.hostname not in YUNGCHING_HOSTS:
            continue
        content = resp.get("content") or {}
        mime = str(content.get("mimeType") or "").lower()
        resource_type = str(e.get("_resourceType") or "").lower()
        if resource_type != "script" and "javascript" not in mime:
            continue
        text = content_text(content)
        if not text:
            continue
        routes = extract_routes(text)
        source_path = p.path
        for route in routes:
            route_sources[route].add(source_path)
            route_occurrences[route] += text.count(route.split("?", 1)[0])
        bundle_stats.append({
            "path": source_path,
            "bytesUtf8": len(text.encode("utf-8", errors="ignore")),
            "routeCount": len(routes),
            "hasFetchToken": "fetch(" in text,
            "hasAxiosToken": "axios" in text.lower(),
            "hasGraphqlToken": "graphql" in text.lower(),
        })

    routes = []
    for route in sorted(route_sources):
        routes.append({
            "route": route,
            "sourceBundleCount": len(route_sources[route]),
            "sourceBundles": sorted(route_sources[route])[:30],
            "approxOccurrences": route_occurrences[route],
        })

    interesting = [x for x in routes if any(k in x["route"].lower() for k in (
        "house", "list", "search", "property", "mansion", "recommend"
    ))]
    out = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "privacy": "Only public route strings and bundle paths are persisted.",
        "scriptBundleCountAnalyzed": len(bundle_stats),
        "discoveredRouteCount": len(routes),
        "interestingHousingRouteCount": len(interesting),
        "interestingHousingRoutes": interesting[:200],
        "allDiscoveredRoutes": routes[:400],
        "bundlesWithRoutes": sorted(
            [x for x in bundle_stats if x["routeCount"]],
            key=lambda x: (-x["routeCount"], x["path"]),
        )[:120],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "scriptBundleCountAnalyzed": out["scriptBundleCountAnalyzed"],
        "discoveredRouteCount": out["discoveredRouteCount"],
        "interestingHousingRouteCount": out["interestingHousingRouteCount"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
