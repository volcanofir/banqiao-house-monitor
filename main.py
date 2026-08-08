import asyncio
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from threading import Thread
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("banqiao-house-bot")
logging.getLogger("httpx").setLevel(logging.WARNING)

TG_TOKEN = os.environ.get("TG_TOKEN")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "10"))
BOT_VERSION = "2026-08-09-591-fallback-v2"

TARGET_STREETS = [
    "中山路二段",
    "中山路2段",
    "三民路一段",
    "三民路1段",
    "三民路二段",
    "三民路2段",
    "翠華街",
    "林森街",
    "萬安街",
    "光復街",
]

BANQIAO_ALIASES = ("板橋", "板橋區", "新北市板橋區")
OTHER_DISTRICTS = ("永和", "中和", "土城", "新莊", "三重", "台北", "北市")

SEARCH_SINYI_URL = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/Banqiao-district/date-desc/1"
SEARCH_591_API = "https://sale.591.com.tw/home/search/list"
SEARCH_591_HOME = "https://sale.591.com.tw"
SEARCH_591_FALLBACK_URLS = [
    "https://sale.591.com.tw/list?regionid=3&section=26&order=posttime_desc",
    "https://sale.591.com.tw/?regionid=3&section=26&order=posttime_desc",
]

app_flask = Flask(__name__)


@app_flask.route("/")
def home():
    return "Bot is running!", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)


@dataclass(frozen=True)
class HouseCase:
    source: str
    title: str
    address: str
    price: str
    url: str
    matched: bool


def default_headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
    }
    if referer:
        headers["Referer"] = referer
    return headers


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def looks_like_other_district(text: str) -> bool:
    return any(dist in text for dist in OTHER_DISTRICTS)


def is_banqiao_text(text: str, source_is_already_banqiao: bool = False) -> bool:
    if not text or looks_like_other_district(text):
        return False
    if source_is_already_banqiao:
        return True
    return any(alias in text for alias in BANQIAO_ALIASES)


def matches_target_street(text: str, source_is_already_banqiao: bool = False) -> bool:
    if not is_banqiao_text(text, source_is_already_banqiao=source_is_already_banqiao):
        return False
    return any(street in text for street in TARGET_STREETS)


def format_price(value: Any) -> str:
    value = normalize_text(value)
    if not value:
        return "未提供"
    return value if "萬" in value else f"{value}萬"


def dedupe_cases(cases: Iterable[HouseCase]) -> list[HouseCase]:
    seen: set[str] = set()
    unique_cases: list[HouseCase] = []
    for case in cases:
        key = case.url or f"{case.source}:{case.title}:{case.address}:{case.price}"
        if key in seen:
            continue
        seen.add(key)
        unique_cases.append(case)
    return unique_cases


def fetch_591_cases() -> tuple[list[HouseCase], str]:
    cases: list[HouseCase] = []
    logs: list[str] = []
    params = {
        "type": "1",
        "regionid": "3",
        "section": "26",
        "firstRow": "0",
        "totalRows": "30",
        "order": "posttime_desc",
    }
    headers = default_headers(SEARCH_591_HOME)
    headers["X-Requested-With"] = "XMLHttpRequest"

    try:
        session = requests.Session()
        session.get(SEARCH_591_HOME, headers=headers, timeout=8, verify=VERIFY_SSL)
        response = session.get(
            SEARCH_591_API,
            headers=headers,
            params=params,
            timeout=12,
            verify=VERIFY_SSL,
        )
        if response.status_code == 200:
            payload = response.json()
            data = payload.get("data", {})
            items = data.get("house_list") or data.get("data") or []

            for item in items:
                title = normalize_text(item.get("title"))
                address = normalize_text(item.get("address")) or "新北市板橋區"
                price = format_price(item.get("price"))
                house_id = item.get("houseid") or item.get("id")
                if not title or not house_id:
                    continue

                url = f"https://sale.591.com.tw/home/{house_id}"
                full_text = f"{title} {address}"
                cases.append(
                    HouseCase(
                        source="591房屋",
                        title=title,
                        address=address,
                        price=price,
                        url=url,
                        matched=matches_target_street(full_text, source_is_already_banqiao=True),
                    )
                )
            return dedupe_cases(cases), ""

        logs.append(f"591 API HTTP {response.status_code}")
        fallback_cases, fallback_log = fetch_591_cases_from_html(session)
        if fallback_cases:
            return fallback_cases, fallback_log
        if fallback_log:
            logs.append(fallback_log)
        return cases, "；".join(logs)
    except Exception as exc:
        logger.exception("591 fetch failed")
        try:
            fallback_cases, fallback_log = fetch_591_cases_from_html(requests.Session())
            if fallback_cases:
                return fallback_cases, fallback_log
            return cases, f"591 異常：{exc}；{fallback_log}"
        except Exception:
            return cases, f"591 異常：{exc}"


def fetch_591_cases_from_html(session: requests.Session) -> tuple[list[HouseCase], str]:
    cases: list[HouseCase] = []
    logs: list[str] = []
    link_pattern = re.compile(r"/home/(\d+)")

    for search_url in SEARCH_591_FALLBACK_URLS:
        try:
            response = session.get(
                search_url,
                headers=default_headers(SEARCH_591_HOME),
                timeout=12,
                verify=VERIFY_SSL,
            )
            if response.status_code != 200:
                logs.append(f"591 列表頁 HTTP {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.find_all("a", href=True):
                href = normalize_text(link.get("href"))
                match = link_pattern.search(href)
                if not match:
                    continue

                title = normalize_text(link.get("title") or link.get_text(" ", strip=True))
                parent_text = normalize_text(link.parent.get_text(" ", strip=True) if link.parent else title)
                full_text = f"{title} {parent_text}"
                if not title or not is_banqiao_text(full_text, source_is_already_banqiao=True):
                    continue

                house_id = match.group(1)
                cases.append(
                    HouseCase(
                        source="591房屋",
                        title=title[:40],
                        address="新北市板橋區",
                        price="點擊連結查看",
                        url=f"https://sale.591.com.tw/home/{house_id}",
                        matched=matches_target_street(full_text, source_is_already_banqiao=True),
                    )
                )

            cases = dedupe_cases(cases)
            if cases:
                return cases, "591 API 失敗，已改用列表頁備援抓取"
        except Exception as exc:
            logs.append(f"591 列表頁異常：{exc}")

    return [], "；".join(logs) or "591 API 與列表頁都沒有抓到資料"


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_sinyi_cases_from_json(payload: Any) -> list[HouseCase]:
    cases: list[HouseCase] = []
    for item in walk_json(payload):
        href = normalize_text(item.get("url") or item.get("href") or item.get("link"))
        title = normalize_text(item.get("name") or item.get("title") or item.get("caseName"))
        address = normalize_text(item.get("address") or item.get("addr"))
        price = normalize_text(item.get("price") or item.get("totalPrice") or item.get("amount"))

        if "/buy/house/" not in href or not title:
            continue

        full_url = urljoin("https://www.sinyi.com.tw", href)
        full_text = f"{title} {address}"
        if not is_banqiao_text(full_text):
            continue

        cases.append(
            HouseCase(
                source="信義房屋",
                title=title[:40],
                address=address or "新北市板橋區",
                price=format_price(price) if price else "點擊連結查看",
                url=full_url,
                matched=matches_target_street(full_text),
            )
        )
    return cases


def fetch_sinyi_cases() -> tuple[list[HouseCase], str]:
    cases: list[HouseCase] = []
    try:
        response = requests.get(
            SEARCH_SINYI_URL,
            headers=default_headers("https://www.sinyi.com.tw/"),
            timeout=12,
            verify=VERIFY_SSL,
        )
        if response.status_code != 200:
            return cases, f"信義 HTTP {response.status_code}"

        soup = BeautifulSoup(response.text, "html.parser")

        next_data = soup.find("script", id="__NEXT_DATA__", type="application/json")
        if next_data and next_data.string:
            try:
                cases.extend(extract_sinyi_cases_from_json(json.loads(next_data.string)))
            except json.JSONDecodeError:
                logger.warning("Sinyi __NEXT_DATA__ json parse failed")

        for link in soup.find_all("a", href=True):
            href = normalize_text(link.get("href"))
            if "/buy/house/" not in href:
                continue
            title = normalize_text(link.get("title") or link.get_text(" ", strip=True))
            if not title or len(title) < 4 or "信義" in title or "瀏覽" in title:
                continue

            parent_text = normalize_text(link.parent.get_text(" ", strip=True) if link.parent else title)
            full_text = f"{title} {parent_text}"
            if not is_banqiao_text(full_text):
                continue

            cases.append(
                HouseCase(
                    source="信義房屋",
                    title=title[:40],
                    address="新北市板橋區",
                    price="點擊連結查看",
                    url=urljoin("https://www.sinyi.com.tw", href),
                    matched=matches_target_street(full_text),
                )
            )

        return dedupe_cases(cases), ""
    except Exception as exc:
        logger.exception("Sinyi fetch failed")
        return cases, f"信義 異常：{exc}"


def build_reply(all_cases: list[HouseCase], logs: list[str]) -> str:
    matched_cases = [case for case in all_cases if case.matched]

    if matched_cases:
        display_cases = matched_cases[:MAX_RESULTS]
        message = f"🏠 【板橋指定路段】最新物件（顯示 {len(display_cases)} / 共 {len(matched_cases)} 筆）：\n\n"
    elif all_cases:
        display_cases = all_cases[: min(5, MAX_RESULTS)]
        message = f"⚠️ 指定路段目前無最新上架，以下為【板橋區最新物件】（顯示 {len(display_cases)} 筆）：\n\n"
    else:
        message = "⚠️ 目前沒有抓到資料。\n\n抓取狀態：\n"
        message += "\n".join(f"- {log}" for log in logs if log) or "- 無錯誤紀錄，可能是網站版型或防爬機制變動"
        return message

    for index, case in enumerate(display_cases, 1):
        message += (
            f"{index}. [{case.source}] {case.title}\n"
            f"📍 地址：{case.address}\n"
            f"💰 總價：{case.price}\n"
            f"🔗 連結：{case.url}\n\n"
        )

    useful_logs = [log for log in logs if log]
    if useful_logs:
        message += "抓取提醒：\n" + "\n".join(f"- {log}" for log in useful_logs)

    return message[:3900]


async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text("🔍 正在抓取 591 與信義房屋的板橋最新物件，請稍候...")

    start_time = time.time()
    cases_591, log_591 = fetch_591_cases()
    cases_sinyi, log_sinyi = fetch_sinyi_cases()
    all_cases = dedupe_cases([*cases_591, *cases_sinyi])
    logger.info("Search finished in %.2fs, cases=%s", time.time() - start_time, len(all_cases))

    await update.message.reply_text(
        build_reply(all_cases, [log_591, log_sinyi]),
        disable_web_page_preview=True,
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    streets = "、".join(TARGET_STREETS)
    await update.message.reply_text(
        "可用指令：/search 或 /check\n"
        f"目前篩選路段：{streets}\n"
        "資料來源：591房屋、信義房屋"
    )


async def show_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(f"Bot version: {BOT_VERSION}")


def main():
    if not TG_TOKEN:
        raise RuntimeError("請先設定環境變數 TG_TOKEN")

    requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/deleteWebhook", timeout=8)
    Thread(target=run_flask, daemon=True).start()

    asyncio.set_event_loop(asyncio.new_event_loop())
    application = Application.builder().token(TG_TOKEN).build()
    application.add_handler(CommandHandler(["start", "help"], show_help))
    application.add_handler(CommandHandler(["version"], show_version))
    application.add_handler(CommandHandler(["check", "search"], do_search))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, do_search))

    print("Telegram 機器人已啟動 Polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
