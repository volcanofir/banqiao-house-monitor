import os
import json
import logging
import requests
import urllib3
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
from threading import Thread

# 徹底停用所有 SSL 安全警告
urllib3.disable_warnings()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TG_TOKEN = os.environ.get("TG_TOKEN")

TARGET_STREETS = [
    "中山路二段", "中山路2段",
    "三民路一段", "三民路1段", "三民路二段", "三民路2段",
    "翠華街", "林森街", "萬安街", "光復街"
]

SEARCH_SINYI_URL = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/Banqiao-district/date-desc/1"

app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

def is_strictly_banqiao(text):
    if not text:
        return False
    other_districts = ["永和", "中和", "土城", "新莊", "三重", "台北", "北市"]
    if any(dist in text for dist in other_districts):
        return False
    return True

def matches_target_street(text):
    if not is_strictly_banqiao(text):
        return False
    return any(street in text for street in TARGET_STREETS)

def fetch_591_cases():
    cases = []
    status_log = ""
    api_url = "https://house.591.com.tw/stat/v1/web/list"
    params = {
        "region": 3,
        "section": 26,
        "type": 1,
        "firstRow": 0,
        "totalRows": 50,
        "sort": "firstRow_desc"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Device": "pc"
    }
    try:
        # 強制 verify=False 直接忽視 SSL 憑證問題
        res = requests.get(api_url, headers=headers, params=params, timeout=10, verify=False)
        if res.status_code == 200:
            data = res.json()
            items = data.get("data", {}).get("house_list", [])
            for item in items:
                title = item.get("title", "")
                address = item.get("address", "")
                price = f"{item.get('price')}萬"
                houseid = item.get("houseid") or item.get("id")
                url = f"https://sale.591.com.tw/home/{houseid}"
                
                full_text = f"{title} {address}"
                is_matched = matches_target_street(full_text)
                
                cases.append({
                    "source": "591房屋",
                    "title": title,
                    "address": address if address else "板橋區",
                    "price": price,
                    "url": url,
                    "matched": is_matched
                })
        else:
            status_log = f"591 HTTP {res.status_code}"
    except Exception as e:
        status_log = f"591: {e}"
        
    return cases, status_log

def fetch_sinyi_cases():
    cases = []
    status_log = ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(SEARCH_SINYI_URL, headers=headers, timeout=10, verify=False)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            links = soup.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                if "/buy/house/" in href:
                    title = link.get("title") or link.text.strip()
                    if not title or len(title) < 4 or "信義" in title or "瀏覽" in title:
                        continue
                    
                    full_url = f"https://www.sinyi.com.tw{href}" if href.startswith("/") else href
                    parent_text = link.parent.text if link.parent else title
                    
                    is_matched = matches_target_street(parent_text) or matches_target_street(title)
                    
                    if is_strictly_banqiao(title) and not any(c["url"] == full_url for c in cases):
                        cases.append({
                            "source": "信義房屋",
                            "title": title[:35],
                            "address": "新北市板橋區",
                            "price": "點擊連結查看",
                            "url": full_url,
                            "matched": is_matched
                        })
        else:
            status_log = f"信義 HTTP {res.status_code}"
    except Exception as e:
        status_log = f"信義: {e}"
        
    return cases, status_log

async def do_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 正在即時抓取【板橋 591 與 信義房屋】最新物件，請稍候...")
    
    cases_591, log_591 = fetch_591_cases()
    cases_sinyi, log_sinyi = fetch_sinyi_cases()
    all_cases = cases_591 + cases_sinyi

    matched_cases = [c for c in all_cases if c["matched"]]

    if matched_cases:
        reply_msg = f"🏠 【板橋指定路段】最新物件（共 {len(matched_cases)} 筆）：\n\n"
        display_cases = matched_cases
    elif all_cases:
        reply_msg = f"⚠️ 指定路段目前無最新上架，以下為【板橋區最新物件（共抓取 {len(all_cases)} 筆）】：\n\n"
        display_cases = all_cases[:5]
    else:
        err_msg = "⚠️ 抓取狀態紀錄：\n"
        if log_591:
            err_msg += f"- {log_591}\n"
        if log_sinyi:
            err_msg += f"- {log_sinyi}\n"
        await update.message.reply_text(err_msg)
        return

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
