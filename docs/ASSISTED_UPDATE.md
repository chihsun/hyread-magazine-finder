# HyRead 九館：ChatGPT 輔助增量更新流程

> **目前狀態：** 2026-10-30 的第一次 GitHub-hosted Runner 執行，九館的 HyRead 分類頁均回傳 HTTP 403。因此停止 GitHub Actions 每週直接擷取。**本文件描述新的人工輔助流程，不代表此時已完成任何一次新書單核對。**

## 你在 ChatGPT 的操作方式

在連接了此 GitHub 儲存庫的對話中，直接要求：

> 更新 HyRead 九館雜誌清單：從各館上次成功核對日與最近 14 天較早的日期開始查，逐館最多嘗試三次，短暫錯誤以隨機延遲再試兩次；無法存取則標示失敗或部分核對。只合併已確認的新書名與較新刊期，先驗證再推送 `chihsun/hyread-magazine-finder`，保留原資料，顯示來源及變動紀錄。

ChatGPT 必須在**當次對話中**完成檢索、比對與推送；不是一項自動排程或背景服務。不保證每次都能從搜尋服務完整取得九館資訊。

## 查詢與重試準則（每館獨立）

1. 使用九館公開雜誌書櫃／分類頁或合法可取得的官方索引；先核對書名、最新發刊日期、圖書館和來源網址。
2. **暫時性錯誤**（逾時、5xx、短暫失連）第一次失敗，隨機等待 **2–5 秒**後再試；第二次失敗隨機等待 **6–12 秒**後再試。每館最多 **3 次查詢機會＝首次＋重試 2 次**。遇 429，遵守 Retry-After；若來源要求較久或不允許請求，停止，不執行密集重試。
3. **明確拒絕**（401／403、要求登入或存取未獲允許）立即停止，不嘗試繞過。若來源只提供快取索引，須標示「索引／部分核對」，不冒充即時完整資料。
4. 遇失敗記錄 `attempts`、真實的等待秒數、`error` 和未核對範圍。**不要將失敗、缺頁、搜尋未命中當作「該館沒有」**。
5. 三態：`complete` = 指定**日期與來源範圍**完整查核（不是全部歷史館藏）；`partial` = 部分有效資料；`failed` = 無可用核對資料。未查的館別不必放進本批次，網站會標示為「本次未核對」。

## 更新保護

- **只增加／升級**有官方來源的書名×圖書館紀錄。日期相同不重複更新，舊日期不覆蓋新日期；不同版別分開。
- 不因增量查詢未找到而下架或增加 `misses`；失敗的館別保留先前資料和完整核對時間。
- 搜尋結果可用但不保證當次完整：網站顯示「範圍完成／部分核對／失敗／未核對」及每館實際查得筆數。
- 寫入 `data/state.json`、`data/history.json`、`docs/data/catalog.json`、`docs/data/update-report.json`、`docs/data/status.json`，網站仍由 GitHub Pages 推送後自動部署。
- 變動紀錄（增書名、新刊期等）保留最近 180 天；本次報表可展開具體書名及日期。
- `batch_id` 為唯一批次識別碼；相同批次不重複匯入；更新前一律跑測試與乾跑比較。

## 可供 ChatGPT／開發者匯入的 JSON 格式

先準備 `assisted-batch.json`（以下資料 **僅為格式示意，不是實際書目**）：

```json
{
  "schema": 1,
  "source": "chatgpt_assisted",
  "batch_id": "manual-20261106-001",
  "window_start": "2026-10-23",
  "window_end": "2026-11-06",
  "libraries": [
    {
      "id": "tpml", "status": "partial", "attempts": 3,
      "retry_wait_seconds": [3.1, 7.5],
      "notes": "只確認財經類，生活類分頁未取得。",
      "records": [
        {
          "title": "示範雜誌名稱", "date": "2026-11-06",
          "source_url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine-list.jsp?magazineclass=M02"
        }
      ]
    },
    {
      "id": "tnml", "status": "failed", "attempts": 1,
      "retry_wait_seconds": [],
      "error": "HTTP 403：來源拒絕存取，無再次嘗試。", "records": []
    }
  ]
}
```

成功完整核對指定範圍時，使用 `"status": "complete"` 並在 `notes` 寫明實際核對的分類／頁面和時間範圍。**不可僅憑搜尋結果未出現，即宣稱完整核對。**

```bash
python -m unittest discover -s tests -v
python -m src.assisted_update assisted-batch.json --dry-run
python -m src.assisted_update assisted-batch.json --apply
```

上方示意批次不要直接套用至正式資料。推送前應查看報表的每館狀態與異動清單，僅提交已驗證內容。完成推送後，確認 GitHub Pages 重新部署成功。

## GitHub Actions 分工

`.github/workflows/update-magazines.yml` 目前改為**手動執行單元測試／驗證**，不會自行抓取 HyRead 或更新書單。每週爬取排程已移除；網站的「重新載入資料」只是下載 GitHub Pages 上最新的 JSON。若未來找到獲許可的官方資料源，再另行評估排程。
