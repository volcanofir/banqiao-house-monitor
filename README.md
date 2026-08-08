# 板橋房屋爬蟲 Telegram Bot

這個 Bot 會即時抓取 591 房屋與信義房屋的板橋最新物件，並優先篩選指定路段：

- 中山路二段 / 中山路2段
- 三民路一段 / 三民路1段
- 三民路二段 / 三民路2段
- 翠華街
- 林森街
- 萬安街
- 光復街

## 使用方式

1. 到 Telegram 找 `@BotFather` 建立 Bot，取得 Token。
2. 設定環境變數：

```bash
TG_TOKEN=你的TelegramBotToken
MAX_RESULTS=10
VERIFY_SSL=false
```

3. 安裝套件：

```bash
pip install -r requirements.txt
```

4. 啟動：

```bash
python main.py
```

## Telegram 指令

- `/start`：顯示說明
- `/help`：顯示說明
- `/search`：開始抓取
- `/check`：開始抓取
- 直接傳任何文字：也會開始抓取

## 部署到 Render

1. 將整包檔案上傳到 GitHub。
2. 在 Render 建立 Web Service。
3. Build Command 使用：

```bash
pip install -r requirements.txt
```

4. Start Command 使用：

```bash
python main.py
```

5. Environment Variables 加上：

```bash
TG_TOKEN=你的TelegramBotToken
MAX_RESULTS=10
VERIFY_SSL=false
```

## 注意

591 與信義房屋可能會調整網站版型、API 或防爬蟲規則。如果突然抓不到資料，通常是網站端有變動，需要更新解析方式。
