# 板橋房屋監控

這個專案會定期抓取 591 與信義房屋的板橋指定路段案件，整理上架、下架與價格變化後寫入網站資料，並透過 GitHub Pages 顯示正式版監控頁面。

## 監控路段

- 中山路二段 / 中山路2段
- 三民路一段 / 三民路1段
- 三民路二段 / 三民路2段
- 翠華街
- 林森街
- 萬安街
- 光復街

## 正式版架構

- 網頁：`docs/index.html`
- 監控排程：`.github/workflows/monitor-clean.yml`
- 快速抓取：`scripts/monitor_fast.py`
- 共用抓取核心：`scripts/monitor_pages.py`
- 案件資料：`docs/data/listings.json`
- 信義首次顯示快取：`docs/data/sinyi-first-display-cache.json`
- 公司案件比對與驗證：`docs/preview/`

## 自動更新流程

1. GitHub Actions 定期檢查資料新鮮度。
2. 先更新信義房屋案件。
3. 591 在 VPN 連線成功後更新。
4. 執行案件去重、時間正規化與價格變化追蹤。
5. 將最新資料寫回 `docs/data/`。
6. 執行正式比對與驗證流程，網站讀取最新結果。

## 本機執行

安裝套件：

```bash
pip install -r requirements.txt
```

只抓信義房屋：

```bash
MONITOR_SOURCE=sinyi python scripts/monitor_fast.py
```

只抓 591：

```bash
MONITOR_SOURCE=591 python scripts/monitor_fast.py
```

591 的正式環境另使用 Chrome 與 VPN 網路環境；本機執行時需自行具備相同條件。

## 注意

591、信義房屋或公司比對來源若調整網站版型、API 或防爬機制，可能需要更新解析方式。正式網站本身只讀取已產生的資料檔，因此單一來源暫時抓取失敗時，會盡量沿用上一輪有效資料，避免直接把既有案件清空。
