"""Record the public egress IP and approximate GeoIP of the Sinyi GitHub runner.

Usage:
    python scripts/log_sinyi_runner_ip.py capture
    python scripts/log_sinyi_runner_ip.py merge

The sample is written outside the checkout so git reset cannot erase it.
IP-based location is approximate and is not a physical runner location.
"""
import ipaddress
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

SAMPLE = Path("/tmp/sinyi-runner-ip-sample.json")
HISTORY = Path("docs/data/sinyi-runner-ip-history.json")
MAX_ENTRIES = 500


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_json(url, timeout=8):
    request = Request(url, headers={"User-Agent": "banqiao-house-monitor-ip-log/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def public_ip():
    errors = []
    for url in ("https://api.ipify.org?format=json", "https://api64.ipify.org?format=json"):
        try:
            candidate = str(fetch_json(url)["ip"]).strip()
            return str(ipaddress.ip_address(candidate)), None
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return None, "; ".join(errors)[:400]


def geoip(ip):
    errors = []
    try:
        data = fetch_json("https://ipwho.is/" + ip)
        if data.get("success") is not False and data.get("country"):
            conn = data.get("connection") or {}
            return {
                "geoProvider": "ipwho.is",
                "country": data.get("country"),
                "countryCode": data.get("country_code"),
                "region": data.get("region"),
                "city": data.get("city"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "isp": conn.get("isp"),
                "org": conn.get("org"),
                "asn": conn.get("asn"),
            }, None
        errors.append(str(data.get("message") or "No location in ipwho.is response"))
    except Exception as exc:
        errors.append(f"ipwho.is: {type(exc).__name__}: {exc}")

    try:
        data = fetch_json("https://ipapi.co/" + ip + "/json/")
        if not data.get("error") and data.get("country_name"):
            return {
                "geoProvider": "ipapi.co",
                "country": data.get("country_name"),
                "countryCode": data.get("country_code"),
                "region": data.get("region"),
                "city": data.get("city"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "isp": data.get("org"),
                "org": data.get("org"),
                "asn": data.get("asn"),
            }, None
        errors.append(str(data.get("reason") or "No location in ipapi.co response"))
    except Exception as exc:
        errors.append(f"ipapi.co: {type(exc).__name__}: {exc}")

    return {}, "; ".join(errors)[:400]


def capture():
    sample = {
        "sampledAtUtc": now(),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "runnerOs": os.environ.get("RUNNER_OS"),
        "ip": None,
        "ipVersion": None,
        "status": "ip_lookup_failed",
        "locationNote": "Approximate GeoIP database location, not a physical runner or GPS location.",
    }
    ip, error = public_ip()
    if ip:
        sample["ip"] = ip
        sample["ipVersion"] = ipaddress.ip_address(ip).version
        sample["status"] = "location_lookup_failed"
        location, geo_error = geoip(ip)
        sample.update(location)
        if location:
            sample["status"] = "ok"
        elif geo_error:
            sample["error"] = geo_error
    elif error:
        sample["error"] = error
    SAMPLE.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Sinyi runner egress sample: " + json.dumps(sample, ensure_ascii=False))


def merge():
    if not SAMPLE.is_file():
        print("Runner IP sample not found; nothing to merge.")
        return
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    try:
        previous = json.loads(HISTORY.read_text(encoding="utf-8"))
        entries = previous.get("entries", [])
        if not isinstance(entries, list):
            entries = []
    except (OSError, ValueError, AttributeError):
        entries = []

    key = (str(sample.get("runId")), str(sample.get("runAttempt")))
    entries = [
        item for item in entries
        if isinstance(item, dict)
        and (str(item.get("runId")), str(item.get("runAttempt"))) != key
    ]
    entries.append(sample)
    entries.sort(key=lambda item: item.get("sampledAtUtc") or "")
    entries = entries[-MAX_ENTRIES:]
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history = {
        "description": "GitHub Actions runner public egress IP samples and approximate GeoIP locations for Sinyi Banqiao 16-store workflow.",
        "locationAccuracy": "Approximate IP geolocation; not a precise host/runner location.",
        "updatedAtUtc": now(),
        "entries": entries,
    }
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(entries)} Sinyi runner IP samples to {HISTORY}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("capture", "merge"):
        raise SystemExit("Usage: log_sinyi_runner_ip.py capture|merge")
    globals()[sys.argv[1]]()
