import os
import json
import requests
from bs4 import BeautifulSoup

ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
USER_ID = os.environ.get("LINE_USER_ID")
HISTORY_FILE = "history.json"

TARGET_REGION_NAME = "板橋區"
TARGET_STREETS = [
    "中山路二段",
    "三民路一段",
    "三民路二段",
    "翠華街",
    "林森街",
    "萬安街",
    "光復街"
]

SEARCH_SINYI_URL = "https://www.sinyi.com.tw/buy/list/NewTaipei-city/Banqiao-district/default-desc/1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def send_line_message(message):
    if not ACCESS_TOKEN or not USER_ID:
        print("未設定 LINE_ACCESS_TOKEN 或 LINE_USER_ID，測試輸出：")
        print(message)
        return
        
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    payload = {
        "to": USER_ID,
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=5)
        if res.status_code != 200:
            print(f"LINE 發送失敗: {res.text}")
    except Exception as e:
        print(f"LINE 發送異常: {e}")

def matches_target_street(text):
    if not text:
        return False
    return any(street in text for street in TARGET_STREETS)

def fetch_591_cases():
    cases = []
    api_url = "https://house.591.com.tw/stat/v1/web/list"
    params = {
        "region": 3,
        "section": 26,
        "type": 1,
        "firstRow": 0,
        "totalRows": 50
    }
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
                house_id = f"591_{item.get('houseid')}"
                price = f"{item.get('price')}萬"
                url = f"https://sale.591.com.tw/home/{item.get('houseid')}"
                cases.append({
                    "id": house_id,
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
                house_id_raw = href.split("/")[-1].replace(".html", "")
                house_id = f"sinyi_{house_id_raw}"
                address_elem = card.select_one(".buy-list-address") or card.select_one("span[class*='address']")
                address = address_elem.text.strip() if address_elem else ""
                if not (matches_target_street(address) or matches_target_street(title)):
                    continue
                price_elem = card.select_one(".buy-list-price") or card.select_one("span[class*='price']")
                price = price_elem.text.strip().replace("\n", "") if price_elem else "未知"
                cases.append({
                    "id": house_id,
                    "source": "信義房屋",
                    "title": title,
                    "address": address,
                    "price": price,
                    "url": url
                })
    except Exception as e:
        print(f"信義房屋 抓取異常: {e}")
    return cases

def main():
    history = load_history()
    updated_history = list(history)
    
    print(f"開始執行【{TARGET_REGION_NAME}】指定路段房屋監控...")
    cases_591 = fetch_591_cases()
    cases_sinyi = fetch_sinyi_cases()
    
    all_cases = cases_591 + cases_sinyi
    new_found_count = 0
    
    for case in all_cases:
        if case["id"] not in history:
            new_found_count += 1
            msg = (
                f"\n🏠 【{case['source']}】新案件上架！\n"
                f"標題：{case['title']}\n"
                f"地址：{case['address']}\n"
                f"總價：{case['price']}\n"
                f"連結：{case['url']}"
            )
            send_line_message(msg)
            updated_history.append(case["id"])
            
    if new_found_count > 0:
        save_history(updated_history)
        print(f"成功發現並推播 {new_found_count} 筆新物件！")
    else:
        print("目前未發現指定路段的新上架物件。")

if __name__ == "__main__":
    main()
