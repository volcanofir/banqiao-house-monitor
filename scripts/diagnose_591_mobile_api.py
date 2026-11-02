"""Read-only, low-volume reachability check for legacy 591 mobile listing APIs.

Only aggregate JSON shape/field names and HTTP metadata are printed;
no listing values, cookies, credentials or tokens are logged or persisted.
One request per path.
An HTTP error does not prove an API endpoint has been permanently retired.
"""
import argparse
import json
import socket
import time
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
    request_params = dict(params)
    # The 2026-10-30 success code generated a fresh millisecond timestamp
    # after capturing the real website's request template.
    request_params["timestamp"] = str(int(time.time() * 1000))
    url = BASE + path + "?" + urlencode(request_params)
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
    payload_info = {}
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
            content_type = response.headers.get("content-type", "")
            raw = response.read(2_000_000)
            payload_info["body_bytes_sampled"] = len(raw)
            if "application/json" in content_type:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    if isinstance(payload, dict):
                        payload_info["root_keys"] = sorted(payload.keys())[:20]
                        for key in ("status", "code", "success"):
                            if key in payload:
                                value = payload[key]
                                if isinstance(value, (bool, int, float)) or (isinstance(value, str) and len(value) < 12):
                                    payload_info[key] = value
                        data = payload.get("data")
                        payload_info["data_type"] = type(data).__name__
                        if isinstance(data, list):
                            payload_info["list_count"] = len(data)
                            if data and isinstance(data[0], dict):
                                payload_info["first_item_field_keys"] = sorted(data[0].keys())[:30]
                        elif isinstance(data, dict):
                            payload_info["data_keys"] = sorted(data.keys())[:25]
                            for item_key in ("house_list", "items", "list", "data"):
                                items = data.get(item_key)
                                if isinstance(items, list):
                                    payload_info["list_count"] = len(items)
                                    payload_info["list_key"] = item_key
                                    if items and isinstance(items[0], dict):
                                        payload_info["first_item_field_keys"] = sorted(items[0].keys())[:30]
                                    break
                    else:
                        payload_info["root_type"] = type(payload).__name__
                except (ValueError, UnicodeError):
                    payload_info["json_parse"] = "failed"
            else:
                payload_info["json_parse"] = "not_json"
            for k in ("server", "content-type", "x-cache"):
                if response.headers.get(k):
                    headers[k] = response.headers[k][:90]
            redirect = response.headers.get("location")
            if redirect:
                parts = urlsplit(redirect)
                headers["redirect_host_path"] = parts.netloc + parts.path
    print(
        f"MOBILE_API_REACHABILITY environment={label} endpoint={name} "
        f"http={code} error={err} timestamp_included=True "
        f"response_metadata={headers} payload_shape={payload_info}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="direct")
    args = parser.parse_args()
    for name, path, params in ENDPOINTS:
        check(name, path, params, args.label)
    print("READ_ONLY only in-memory response shape inspected; no listing values or credentials printed or persisted")
