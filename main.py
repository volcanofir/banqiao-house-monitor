import os
import json
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TG_TOKEN = os.environ.get("TG_TOKEN")
TARGET_REGION_NAME = "板橋區"
TARGET_STREETS = [
    "中山路二段", "三民路一段", "三民路二段", "翠華街", "林森街", "萬安街", "光復街"
]

SEARCH_SINYI_URL = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/Banqiao-district/default-desc/1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

app_flask = Flask(__name__)

def matches_target_street(text):
    if not text:
        return False
    return any(street in text for street in TARGET_STREETS)

def fetch_591_cases():
    cases = []
    api_url = "https://house.591.com.tw/stat/v1/web/list"
    params = {"region": 3, "section": 26, "type": 1, "firstRow": 0, "totalRows": 50}
    try:
        res = requests.get(api_url, headers=HEADERS, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", {}).get("house_list", [])
            for item in items:
                title = item.get("title", "")
                address = item.get("address", "")
                if not (matches_target_street(address) or matches_target_street(title)):
                    continue
                price = f"{item.get('price')}萬"
                url = f"https://sale.591.com.tw/home/{item.get('houseid')}"
                cases.append({
                    "source": "591房屋",
                    "title": title,
                    "address": address,
                    "price": price,
                    "url": url
                })
    except Exception as e:
        print(f"591 抓取異常: {e}")
    return cases

def fetch_sinyi_cases():
    cases = []
    try:
        res = requests.get(SEARCH_SINYI_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            cards = soup.select(".buy-list-item") or soup.select("div[class*='ItemCard']")
            for card in cards:
                title_elem = card.select_one(".buy-list-title") or card.select_one("a[title]")
                if not title_elem:
                    continue
                title = title_elem.text.strip()
                href = title_elem.get("href", "")
                url = f"https://www.sinyi.com.tw{href}" if href.startswith("/") else href
                address_elem = card.select_one(".buy-list-address") or card.select_one("span[class*='address']")
                address = address_elem.text.strip() if address_elem else ""
                if not (matches_target_street(address) or matches_target_street(title)):
                    continue
                price_elem = card.select_one(".buy-list-price") or card.select_one("span[class*='price']")
                price = price_elem.text.strip().replace("\n", "") if price_elem else "未知"
                cases.append({
                    "source": "信義房屋",
                    "title": title,
                    "address": address,
                    "price": price,
                    "url": url
                })
    except Exception as e:
        print(f"信義房屋 抓取異常: {e}")
    return cases

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 正在即時抓取【板橋指定路段】最新物件，請稍候...")
    
    cases_591 = fetch_591_cases()
    cases_sinyi = fetch_sinyi_cases()
    all_cases = cases_591 + cases_sinyi

    if not all_cases:
        await update.message.reply_text("目前未發現指定路段的最新上架物件。")
        return

    reply_msg = f"🏠 【板橋指定路段】最新物件查詢結果（共 {len(all_cases)} 筆）：\n\n"
    for idx, case in enumerate(all_cases, 1):
        reply_msg += (
            f"{idx}. [{case['source']}] {case['title']}\n"
            f"📍 地址：{case['address']}\n"
            f"💰 總價：{case['price']}\n"
            f"🔗 連結：{case['url']}\n\n"
        )
    
    await update.message.reply_text(reply_msg, disable_web_page_preview=True)

tg_app = Application.builder().token(TG_TOKEN).build()
tg_app.add_handler(CommandHandler(["start", "check", "search"], do_search))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, do_search))

@app_flask.route('/', methods=['GET'])
def health():
    return "OK", 200

@app_flask.route('/webhook', methods=['POST'])
def webhook():
    if request.method == "POST":
        try:
            json_data = request.get_json(force=True)
            update = Update.de_json(json_data, tg_app.bot)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(tg_app.initialize())
            loop.run_until_complete(tg_app.process_update(update))
            loop.close()
        except Exception as e:
            print("Webhook 處理錯誤:", e)
        return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)
