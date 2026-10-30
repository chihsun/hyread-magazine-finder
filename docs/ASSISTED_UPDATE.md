# HyRead 九館：ChatGPT 輔助增量更新流程

> **目前狀態：** 2026-10-30 的第一次 GitHub-hosted Runner 執行，九館的 HyRead 分類頁均回傳 HTTP 403。因此停止 GitHub Actions 每週直接擷取。**本文件描述新的人工輔助流程，不代表此時已完成任何一次新書單核對。**

## V1.5：ChatGPT 同批次分頁核對（優先使用）

**維持 ChatGPT 網頁版更新，不需要本機爬蟲，也沒有恢復 GitHub Runner 對 HyRead 的擷取。** 請在本對話直接要求「更新九館最近 7 天雜誌，從最新出刊第 1 頁依序查到回查日期界線，保留同批次分頁、快取時間與具體錯誤原因；驗證後推送 GitHub」。來源查詢、資料比對、推送都要於該次互動完成，不能虛構已讀取分頁。

1. 每館建立獨立 `coverage.scan_id`（如 `tpml-20261030-190000`），由最新出刊第 1 頁開始，沿官方實際分頁連結依序讀取第 2、3…頁，直到回查日期界線。若無法直接取得，記錄所能確認的頁面；不得自行以搜尋引擎的查詢結果推定官方分頁內容。
2. 對每頁區分 **`observed_at`（ChatGPT 實際觀察時間）** 與 **`indexed_at`（搜尋服務明確提供的原始索引時間）**。無法確知索引時間就留空，**不要把觀察時間當成索引建立時間**。可取得的是搜尋摘要／索引時，一律標為 `search_index`，不能標為 `direct`。
3. 若可確認官方頁面是直接取得，保留該頁書目、頁碼、原始 URL、來源類型、`record_count` 與依書目生成的 SHA-256 `content_digest`。可由 `src/latest_pages.py` 的 `inspect_latest_html(..., scan_id=...)` 產生；**僅有搜尋快取摘要時，不得自行捏造 HTML 或摘要**。
4. 直接連續讀完必要分頁後，重新取得第 1 頁，將再次解析的證據填入 `coverage.first_page_recheck`。V1.5（schema 2）宣稱 `complete` 必須通過相同 `scan_id`、每頁摘要、10 分鐘內的同次觀察、跨頁日期排序、日期界線與第 1 頁前後一致性檢查。`scan_id` 和時間接近本身仍不等於伺服器快照保證。
5. 任一分頁缺漏、來源僅是搜尋索引、索引時間差異過大，或前後頁面不一致，都應標為 `partial`；保留已核實的書目與 `jid`，不得把拼接的搜尋快取當成完整核對。分類頁可補充個別已確認書目，但不能填補未知分頁的「完整」證明。

### V1.5 錯誤代碼與回報

- `ACCESS_DENIED`：實際觀察到的 HTTP 401／403 或明確拒絕存取（不能從「工具無法讀取」推斷）；`RATE_LIMITED`：429；`TIMEOUT`、`NETWORK_ERROR`、`SERVER_ERROR`：實際連線或回應失敗。
- `TOOL_UNAVAILABLE`：ChatGPT 讀取工具無法開啟、沒有可確認的 HTTP 回應；`PARSER_ERROR`：內容已取得但解析失敗；`PAGE_MISSING`：缺必要分頁。
- `CACHE_ONLY`、`STALE_CACHE`、`DATE_BOUNDARY_NOT_REACHED`、`SNAPSHOT_DRIFT`：快取、界線或掃描一致性問題；不確定的錯誤請用 `UNKNOWN`，並在 `error` 描述證據，不要編造狀態碼。
- V1.5 失敗館必須帶 `error_code`；失敗分頁可帶 `error_code`／`error`／實際觀察到的 `http_status`。保留每館 `attempts`、實際 `retry_wait_seconds`；臨時錯誤最多額外重試兩次，明確 401／403 不重試。
- 網站的「書單更新紀錄」會顯示每館診斷碼、直接來源與快取頁數、缺頁及相關警示；報告 JSON 的 `coverage.diagnostics` 另外保留掃描時間差、快取索引時間差與第 1 頁重查結果。

### schema 2 完整核對範例（僅示意欄位）

沿用下方既有的 `schema: 1` 範例作舊版相容；新批次改用 `schema: 2`，並將每館 `coverage` 補上以下結構。SHA-256 與時間必須來自實際取得的證據，以下符號不是可直接匯入的真實資料：

```json
{
  "scan_id": "tpml-20261030-190000",
  "method": "latest_pages",
  "pagination_contiguous": true,
  "date_boundary_reached": true,
  "pages": [
    {"page": 1, "url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage=1", "status": "ok", "source_type": "direct", "scan_id": "tpml-20261030-190000", "observed_at": "2026-10-30T19:00:00+08:00", "newest_date": "2026-10-30", "oldest_date": "2026-10-28", "record_count": 12, "content_digest": "<實際SHA256>"}
  ],
  "first_page_recheck": {"source_type": "direct", "scan_id": "tpml-20261030-190000", "observed_at": "2026-10-30T19:02:00+08:00", "content_digest": "<實際SHA256>"}
}
```

這個例子未包含到達查詢日期界線所需的所有分頁，因此也**不構成完整核對證明**。只有 `validate_batch` 實際通過才可以使用 `complete`。

**重要限制**：ChatGPT 的網頁讀取服務可能回傳快取或無法確認來源時間；V1.5 無法強迫外部網站提供同次即時分頁，只能優先直接取得並誠實記錄是否符合完整核對條件。

## 你在 ChatGPT 的操作方式

在連接了此 GitHub 儲存庫的對話中，直接要求：

> 更新 HyRead 九館雜誌清單：從各館上次成功核對日與最近 14 天較早的日期開始查，逐館最多嘗試三次，短暫錯誤以隨機延遲再試兩次；無法存取則標示失敗或部分核對。只合併已確認的新書名與較新刊期，先驗證再推送 `chihsun/hyread-magazine-finder`，保留原資料，顯示來源及變動紀錄。

ChatGPT 必須在**當次對話中**完成檢索、比對與推送；不是一項自動排程或背景服務。不保證每次都能從搜尋服務完整取得九館資訊。

## V1.4／V1.5 查詢來源優先順序與日期界線（每館獨立）

**第一順位不是一本一本搜尋，而是各館獨立的「最新出刊」書櫃**：

1. 先開 `https://<library>.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp`（第一頁）；後續依網站真實分頁連結查 `?nowpage=2`、`?nowpage=3` ……，**必須確認網址、頁碼與內容相符**，不能憑搜尋結果自行推定分頁。
2. 每一頁記錄書名、日期、雜誌專屬的詳細頁網址（如確實出現 `magazine_more.jsp?jid=846`）、直接取得或搜尋索引、實際取得時間、頁面最早／最新日期。直接來源盡量按頁序核對；如果是搜尋快取，記錄為 `search_index`。
3. 必須從第一頁開始、頁碼連續、同次取得的直接來源可信且依日期由新至舊，最後一頁最早發刊日 **≤ 查詢起日**，才可以把指定日期範圍標成 `complete`。各分頁查詢時間相差過大、分頁缺漏、無法確認排序、只有搜尋索引，都只能標示 `partial`。**不能因為同一本雜誌已有日期，就停止搜尋其他分頁。**
4. 如果最新出刊頁面缺漏、過時或不可讀，才用官方雜誌 12 類分類清單補查指定書名、補上 `jid`；備援只能增加已確認的觀察資料，不能把未讀取頁面的結果當成完整核對。
5. 為降低搜尋索引延遲造成的遺漏，最近 7 天更新可額外往前回查 7 天；日期界線以這個**實際回查起日**檢查，正式成果則標示使用者指定的期間。刊期不代表上架日期，舊刊延遲新增仍可能漏掉。

## 查詢與重試準則（每館獨立）

1. 使用合法可取得的 HyRead 官方資料或搜尋索引；不能繞過登入、403 或其他拒絕存取。若官方頁面直接讀取遭拒，搜尋引擎快取僅能作為部分核對，不假裝是即時直接掃描。
2. **暫時性錯誤**（逾時、5xx、短暫失連）第一次失敗，隨機等待 **2–5 秒**後再試；第二次失敗隨機等待 **6–12 秒**後再試。每館最多 **3 次嘗試＝首次＋重試 2 次**。遇 429，尊重 `Retry-After`；過長等待則停止。
3. **明確拒絕**（401／403、要求登入或存取未獲允許）立即停止，不以重試或變換身分規避。請記錄各次嘗試的時間、URL、狀態碼／錯誤與真實等待秒數；不能虛構重試紀錄。
4. `complete` 指已核實指定日期界線，`partial` 指部分可用資料，`failed` 指無可確認資料。若來源未含足以核實書名／日期的證據，不加入 `records`；未查到的書一律保留。

## 雜誌詳細頁連結的資料定義

- 各館每本書獨立儲存 `magazine_url`，僅允許該館 `https://<library>.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=<數字>` 的**真實網址**。
- `source_url` 指本次看到這本書的最新出刊／分類**來源頁**；`magazine_url` 則是雜誌的**專屬書目詳情頁**，兩者不能混用。`jid` **不能由書名推算，也不預設跨圖書館相同**。
- 初始資料尚未有詳細頁連結時 `magazine_url` 可以為 `null`，後續即使刊期不變、或來源是較舊的期刊觀察，只要核實該詳細連結就能補上；不會讓較舊刊期覆蓋較新刊期。記錄 `magazine_url_checked_at`。
- 將來如要擷取出版社、語言、作者、格式等欄位，另外新增 `metadata`，並記錄屬於**雜誌書目**還是**特定刊期**，避免混淆。

## 更新保護

- **只增加／升級**有官方來源的書名×圖書館紀錄。日期相同不重複更新，舊日期不覆蓋新日期；不同版別分開。
- 不因增量查詢未找到而下架或增加 `misses`；失敗的館別保留先前資料和完整核對時間。
- 搜尋結果可用但不保證當次完整：網站顯示「範圍完成／部分核對／失敗／未核對」及每館實際查得筆數。
- 寫入 `data/state.json`、`data/history.json`、`docs/data/catalog.json`、`docs/data/update-report.json`、`docs/data/status.json`，網站仍由 GitHub Pages 推送後自動部署。
- 變動紀錄（增書名、新刊期等）保留最近 180 天；本次報表可展開具體書名及日期。
- `coverage.method` 記錄 `latest_pages`（主要方式）、`categories`（備援）、`search_index`（只取得索引）。`coverage.pages` 記錄已查／失敗頁碼、來源 URL、查詢時間與日期界線。完整核對必須通過 `src/coverage.py` 的直接來源及分頁完整性驗證。
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
      "notes": "只核對到第一頁，其餘分頁未核實，不宣稱日期界線完整。",
      "coverage": {
        "method": "latest_pages", "pagination_contiguous": false,
        "date_boundary_reached": false,
        "pages": [{"page": 1, "url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage=1", "status": "ok", "source_type": "search_index", "observed_at": "2026-11-06T08:50:00+08:00", "newest_date": "2026-11-06", "oldest_date": "2026-11-04"}]
      },
      "records": [
        {
          "title": "示範雜誌名稱", "date": "2026-11-06",
          "source_url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage=1",
          "magazine_url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=846"
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
