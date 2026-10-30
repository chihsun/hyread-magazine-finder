# HyRead 九館：ChatGPT 輔助增量更新流程

> **目前預設採 V1.6.1 簡化規則（schema 3）**。仍由使用者在 ChatGPT 對話手動發出更新指令，ChatGPT 查詢九館「最新出刊」清單，將已取得的新資料合併至 GitHub 並部署；並非 GitHub Runner 自動爬取。舊的 V1.4/V1.5 嚴格模式只留作歷史相容，**不再是新更新指令的預設規則**。

## V1.6.1：下次在 ChatGPT 直接這樣說

> 更新 HyRead 九館**最近 7 天**的雜誌，**每次連續處理兩館，完成該組再處理下一組**。從每館最新出刊第 1 頁開始，依序讀到指定起日即可停止；**指定日期只作為下限，11 月等未來紙本發刊日期也要收錄，不得以查詢當日為上限**。不額外回查 7 天、不重查第 1 頁。允許搜尋快取，但僅採用確實可辨識的書名與刊期；遇 HTTP 401/403 立即停止該館，暫時性錯誤或比資料庫舊的刊期隨機間隔再重試最多兩次。正常完成時保存第一本書的書名、jid（若有）、日期及連結。保留既有較新刊期及所有舊書，九館完成後將已確認資料合併 GitHub 並部署。

### 工作規則（取代舊版嚴格來源驗證）

1. **日期界線（只有下限）：** 最近 N 天含當天，以臺灣日期計；例如 2026-10-30 查最近 7 天，**2026-10-24 是要翻到的最早刊期**。2026-10-30 僅為本次查詢基準日，**不是雜誌收錄的日期上限**。凡讀到日期 ≥ 10/24 的期刊（包含紙本刊期 11/01、11/05 等未來日期）都可依正常規則新增或升級。電子版提前上架是正常現象；不額外往前增加 7 天。
2. **逐頁：** 優先讀各館 `/Template/RWD3.0/magazine_view_more.jsp`（第 1 頁），看該頁最後一筆出版日期。若日期 **大於** 查詢起日才讀第 2 頁，持續直到有一頁最後一筆 **小於或等於** 起日。該頁中日期早於起日的項目可略過，其餘包含未來日期全部保留。每頁應能辨識真實書名、刊期及其分頁來源，不以零碎搜尋摘要猜測整頁。
3. **不重查第一頁：** 結束後不要求再取得同一頁，也不要求掃描摘要、索引時間或全部頁面為同時快照；快取只要內容明確可讀，即可作為分頁資料。若缺頁、日期未達界線或頁面根本無法辨識，改記「部分更新」。
4. **完成接續點：** 每館僅在本次**正常完成**指定日期頁面查詢、且沒有舊刊期異常時，寫入 `latest_page_anchor`：第 1 頁第一筆的書名、日期、經實際來源確認的 `jid`（無則 `null`）、`magazine_url`、`source_url`、`checked_at`。這是未來接續比較參考，**目前仍是每次從第 1 頁開始**。
5. **舊刊期：** 若第 1 頁最新日期落後先前接續點（沒有接續點則比較資料庫該館已知最晚刊期），或某書刊期比資料庫已存刊期舊，請先重新讀取有問題的來源頁（最多額外 2 次，每次如有等待須記下實際秒數）。重試後仍舊，只記為 `STALE_CACHE`／部分更新；可安全合併其他已確認較新資料，**舊日期永遠不覆蓋新日期**。
6. **失敗定義：** 實際確認 HTTP 401/403 或要求登入，該館立即停止，不再重試，記錄 `ACCESS_DENIED`。超時、偶發斷線、頁面內容不完整則允許隨機等待後重試兩次。第 1 頁始終沒辦法正常取得就是 `failed`，第 1 頁有取得但後續分頁不完整就是 `partial`。
7. **書目保存：** 原有 `magazine_url`、`source_url`、書名與各館最新刊期照舊；同一書／同一館只有新日期才能升級，舊日期不覆蓋，新取得的合法書目連結可補齊缺值。增量未查到的舊書不刪除、不增加未收錄次數。
8. **兩館一組、逐組處理：** 預設館別順序為 **臺中＋臺北 → 臺南＋新北 → 高雄＋桃園 → 新竹縣＋新竹市 → 基隆**（最後一館單獨處理）。在 ChatGPT 對話中先完成該組兩館各自的「第 1 頁 → 必要分頁 → 筆數與較新刊期比對／失敗原因」，再開始下一組；避免同時開啟九館分頁造成混淆。此方式**不保證消除搜尋快取**。程式中的 `src.latest_pages.library_groups(config, 2)` 可生成順序分組。
9. **操作模式：** ChatGPT 在本次對話查詢並把核實的資料包送入 `src.assisted_update` 的 schema 3，再驗證、乾跑、推送 GitHub；不要求 Windows 或本機爬蟲。不保證 ChatGPT 頁面取得工具每次都能抓完所有分頁；無法讀取必須如實記錄。

### schema 3（V1.6.1，兼容 V1.6）資料格式

沿用目前批次欄位 `source`、`batch_id`、`window_start`、`window_end`、`libraries`；維持 `schema` 為 **3**。其中 `window_start` 是可納入書目的**最早紙本刊期**，`window_end` 是**查詢基準日**，不是發刊日期的上限。各館使用 `coverage.method: latest_pages`。每個可確認頁面在 `coverage.pages` 記錄 `page`、`url`、`status`、`source_type`（`direct`／`search_index`）、`observed_at`、`newest_date`、`oldest_date`。第一頁成功時必須有：

```json
"first_book": {
  "title": "示範書名",
  "date": "2026-10-30",
  "jid": "846",
  "magazine_url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=846",
  "source_url": "https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage=1"
}
```

這段應放在該館 `coverage` 下，**僅為欄位範例，不能當作真實書目匯入**。沒有實際確認的 `jid` 與詳細書目網址，請填 `null`；不要用書名或其他館的 `jid` 推算。頁面 `source_type=search_index` 可以完成 V1.6 日期邊界，前提是每頁內容及頁碼確實可辨識。若只有片段索引，請改列 `partial`。

當某館 `complete`，日期界線與連續頁碼由 `src/coverage.py` 自動檢查。若讀到已存資料更舊，更新器會要求最多兩次重試；送入的批次在三次嘗試後仍舊，將降級為 `partial`，保留既有較新資料與接續點，並顯示警示。

**以下是歷史 V1.4/V1.5 內容，供查閱舊規則，不是目前預設執行流程。**

---

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
