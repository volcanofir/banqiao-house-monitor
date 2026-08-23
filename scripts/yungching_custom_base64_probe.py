"""Recover Yongching SSR TransferState custom Base64 substitutions.

The public SSR value uses the normal Base64 alphanumeric alphabet but replaces the
five special symbols. We know '>' behaves as '=' padding; brute-force the remaining
four substitutions across A/a/+/. Diagnostic-only and never persists raw payloads.
"""

import base64
import gzip
import itertools
import json
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

import yungching_dom_snapshot as base
import yungching_crypto as yc_crypto


OUT = Path("docs/preview/yungching-custom-base64-probe.json")
ROAD = "板橋區中山路二段"
CUSTOM = "{[: ,".replace(" ", "")  # { [ : ,
TARGET = "Aa+/"


def extract_transfer(page):
    loc = page.locator("script#ng-state")
    if not loc.count():
        raise RuntimeError("ng-state missing")
    state = json.loads(loc.first.text_content() or "{}")
    for k, v in state.items():
        if str(k).startswith("transfer-buy:/api/v2/"):
            return str(k), str(v)
    raise RuntimeError("transfer-buy api value missing")


def normalize(value, mapping):
    table = str.maketrans({**mapping, ">": "="})
    return value.translate(table)


def parse_bytes(raw: bytes):
    candidates = [("raw", raw)]
    if raw.startswith(b"\x1f\x8b"):
        try: candidates.append(("gzip", gzip.decompress(raw)))
        except Exception: pass
    try: candidates.append(("zlib", zlib.decompress(raw)))
    except Exception: pass
    for mode, data in candidates:
        try:
            txt = data.decode("utf-8")
        except Exception:
            continue
        try:
            obj = json.loads(txt)
            return mode + "+json", obj
        except Exception:
            if txt.lstrip().startswith(("{", "[")):
                return mode + "+utf8-jsonlike", txt[:0]
    return None, None


def json_summary(obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    ids = sorted(set(re.findall(r"(?<!\d)(\d{5,9})(?!\d)", raw)))
    yc = sorted(set(re.findall(r"\bYC\d{5,12}\b", raw, flags=re.I)))
    floors = sorted(set(re.findall(r"\d{1,2}(?:[~～-]\d{1,2})?/\d{1,2}樓", raw)))
    return {
        "type": type(obj).__name__,
        "topLevelKeys": sorted(map(str, obj.keys()))[:120] if isinstance(obj, dict) else None,
        "length": len(obj) if isinstance(obj, list) else None,
        "jsonBytesUtf8": len(raw.encode("utf-8")),
        "candidateNumericIds": ids[:120],
        "ycCaseIds": yc[:60],
        "floorTokens": floors[:60],
    }


def try_mapping(value, mapping):
    normalized = normalize(value, mapping)
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", normalized):
        return None
    result = {"mapping": {**mapping, ">": "="}}
    try:
        decoded_bytes = base64.b64decode(normalized, validate=True)
        result["base64DecodedBytes"] = len(decoded_bytes)
        result["base64FirstByte"] = decoded_bytes[0] if decoded_bytes else None
        mode, obj = parse_bytes(decoded_bytes)
        if mode and obj is not None:
            result["success"] = True
            result["decodeMode"] = "custom-base64+" + mode
            result["payload"] = json_summary(obj)
            return result
    except Exception as exc:
        result["base64Error"] = type(exc).__name__
        return None

    # Existing Yongching crypto routine expects a standard Base64 ciphertext string.
    try:
        obj = yc_crypto.decrypt_value(normalized)
        result["success"] = True
        result["decodeMode"] = "custom-base64+yungching-aes-256-cbc"
        result["payload"] = json_summary(obj)
        return result
    except Exception as exc:
        result["aesError"] = type(exc).__name__
    return result


def solve(value):
    trials = []
    successes = []
    for perm in itertools.permutations(TARGET):
        mapping = dict(zip(CUSTOM, perm))
        r = try_mapping(value, mapping)
        if not r:
            continue
        trials.append({
            "mapping": r.get("mapping"),
            "base64DecodedBytes": r.get("base64DecodedBytes"),
            "base64FirstByte": r.get("base64FirstByte"),
            "aesError": r.get("aesError"),
            "success": bool(r.get("success")),
            "decodeMode": r.get("decodeMode"),
        })
        if r.get("success"):
            successes.append(r)
    return {
        "inputChars": len(value),
        "trialCount": len(trials),
        "successCount": len(successes),
        "successes": successes,
        "trials": trials,
    }


def main():
    yc_crypto.self_test()
    out = {
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "previewOnly": True,
        "hypothesis": "custom substitutions for missing Base64 symbols A,a,+,/,=",
        "pages": {},
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="zh-TW", timezone_id="Asia/Taipei")
        page = ctx.new_page()
        r = page.goto(base.road_url(ROAD), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        key, value = extract_transfer(page)
        out["pages"]["search"] = {"http": r.status if r else None, "key": key, **solve(value)}

        rd = page.goto(f"{base.BASE}/house/5289400", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        key, value = extract_transfer(page)
        out["pages"]["detail"] = {"http": rd.status if rd else None, "key": key, **solve(value)}
        ctx.close(); browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:{"http":v.get("http"),"successCount":v.get("successCount"),"modes":[x.get("decodeMode") for x in v.get("successes",[])]} for k,v in out["pages"].items()},ensure_ascii=False))


if __name__ == "__main__":
    main()
