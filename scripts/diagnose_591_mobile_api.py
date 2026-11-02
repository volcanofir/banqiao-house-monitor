"""Read-only, low-volume reachability check for legacy 591 mobile listing APIs.

Only HTTP response metadata is printed; no bodies, cookies, credentials,
listing records or tokens are read or persisted. One request per path.
An HTTP error does not prove an API endpoint has been permanently retired.
"""
import argparse
import socket
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

BASE = "https://bff-house.591.com.tw"
PARAMS = {
    "regionid": "3", "sectionidStr": "26", "o": "32",
    "streetid": "27507", "firstRow": "0", "newPage": "1",
    "newPageSize": "30", "region_id": "3", "device": "touch",
}
ENDPOINTS = [
    ("v1_touch", "/v1/touch/sale/list", PARAMS),
    # Only probes route reachability; v2 parameter correctness is not verified.
    ("v2_php_action_list", "/v2/php-api", dict(PARAMS, action="list")),
]


def check(name, path, params, label):
    url = BASE + path + "?" + urlencode(params)
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://m.591.com.tw/",
            "Origin": "https://m.591.com.tw",
        },
    )
    code = "none"
    headers = {}
    err = "none"
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        response = None
        err = type(exc).__name__
    if response is not None:
        with response:
            code = response.status
            for k in ("server", "content-type", "x-cache"):
                if response.headers.get(k):
                    headers[k] = response.headers[k][:90]
            redirect = response.headers.get("location")
            if redirect:
                parts = urlsplit(redirect)
                headers["redirect_host_path"] = parts.netloc + parts.path
    print(
        f"MOBILE_API_REACHABILITY environment={label} endpoint={name} "
        f"http={code} error={err} response_metadata={headers}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="direct")
    args = parser.parse_args()
    for name, path, params in ENDPOINTS:
        check(name, path, params, args.label)
    print("READ_ONLY no API payload read; no cookies or tokens; no listing files modified")
