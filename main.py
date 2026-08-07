import os
import json
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
from threading import Thread

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TG_TOKEN = os.environ.get("TG_TOKEN")

TARGET_STREETS = [
    "中山路二段", "中山路2段", "中山路",
    "三民路一段", "三民路1段", "三民路二段", "三民路2段", "三民路",
    "翠華街", "林森街", "萬安街", "光復街"
]

SEARCH_SINYI_URL = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/Banqiao-district/date-desc/1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def matches_target_street(text):
    if not text:
        return False
    return any(street in text for street in TARGET_STREETS)

def fetch_591_cases():
    cases = []
    api_url = "https://house.591.com.tw/stat/v1/web/list"
    params = {"region": 3, "section": 26, "type": 1, "firstRow": 0, "totalRows": 50, "sort": "firstRow_desc"}
    try:
        res = requests.get(api_url, headers=HEADERS, params=params, timeout=10)
        if res.status_code == 200:
            items = res.json().get("data", {}).get("house_list", [])
            for item in items:
                title = item.get("title", "")
                address = item.get("address", "")
                price = f"{item.get('price')}萬"
                url = f"https://sale.591.com.tw/home/{item.get('houseid')}"
                is_matched = matches_target_street(address) or matches_target_street(title)
                cases.append({"source": "591房屋", "title": title, "address": address, "price": price, "url": url, "matched": is_matched})
    except Exception as e:
        print(f"591 抓取異常: {e}")
    return cases

def fetch_sinyi_cases():
    cases = []
    try:
        res = requests.get(SEARCH_SINYI_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 使用更強大的全域搜尋方式定位信義房屋的物件超連結
            links = soup.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                # 信義房屋物件網址格式通常為 /buy/house/XXXXX
                if "/buy/house/" in href:
                    title = link.get("title") or link.text.strip()
                    if not title or len(title) < 4:
                        continue
                    
                    full_url = f"https://www.sinyi.com.tw{href}" if href.startswith("/") else href
                    
                    # 尋找同一張卡片區塊內的地址與價格
                    parent_card = link.find_parent("div")
                    card_text = parent_card.text if parent_card else ""
                    
                    is_matched = matches_target_street(card_text) or matches_target_street(title)
                    
                    # 避免重複抓取相同網址
                    if not any(c["url"] == full_url for c in cases):
                        cases.append({
                            "source": "信義房屋",
                            "title": title[:30], # 截取適當長度標題
                            "address": "板橋區（詳見連結）",
                            "price": "點擊連結查看",
                            "url": full_url,
                            "matched": is_matched
                        })
    except Exception as e:
        print(f"信義房屋 抓取異常: {e}")
    return cases

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 正在即時抓取【板橋指定路段】最新物件，請稍候...")
    
    cases_591 = fetch_591_cases()
    cases_sinyi = fetch_sinyi_cases()
    all_cases = cases_591 + cases_sinyi

    matched_cases = [c for c in all_cases if c["matched"]]

    if matched_cases:
        reply_msg = f"🏠 【板橋指定路段】最新物件（共 {len(matched_cases)} 筆）：\n\n"
        display_cases = matched_cases
    else:
        reply_msg = "⚠️ 指定路段最新頁面內無精確匹配案件，以下為【板橋區最新上架物件】：\n\n"
        display_cases = all_cases[:5]

    for idx, case in enumerate(display_cases, 1):
        reply_msg += f"{idx}. [{case['source']}] {case['title']}\n📍 地址：{case['address']}\n💰 總價：{case['price']}\n🔗 連結：{case['url']}\n\n"
    
    await update.message.reply_text(reply_msg, disable_web_page_preview=True)

def main():
    requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/deleteWebhook")
    Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler(["start", "check", "search"], do_search))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, do_search))
    
    print("Telegram 機器人已成功啟動 Polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
