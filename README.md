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


## 預覽版獨立來源更新與失敗重試

- 既有 CLEAN workflow 每 10 分鐘檢查是否需要發動更新；正常來源至少間隔 180 分鐘才再次抓取。
- 已過期的來源若上次獨立抓取失敗，至少間隔 30 分鐘才重新嘗試。GitHub Actions 的實際啟動時間可能延遲。
- 591 繼續使用原本驗證完整七路段的 `591-warelist-preview.yml`；信義房屋、樂屋網、5168 使用 `preview-source-refresh.yml` 各自抓取。
- 信義房屋獨立成功資料寫到 `docs/preview/sinyi-source.json`；樂屋網與 5168 仍各自更新原本七路段來源快照。
- 來源資料只在完整驗證且比現有快照更新後發布，失敗時不會覆蓋既有資料；重複檢查與已在執行的工作不會重複發動。
- **來源快照更新不代表跨平台房屋整併已更新**：原本的 `/preview/` 整併、永慶庫存比對、上／下架仍由原有完整驗證流程負責，獨立來源不得憑廣告 ID 消失而確認下架。
- 以上更新只影響預覽版；正式版 `docs/index.html` 及 `docs/data/listings.json` 不由獨立來源 workflow 修改。

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
