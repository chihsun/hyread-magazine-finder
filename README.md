# HyRead 九館電子雜誌搜尋 v1

搜尋九間臺灣公共圖書館 HyRead 電子雜誌的**最新發刊日期**，比較哪幾館列出特定雜誌。這是公開書目索引，不提供電子書內容下載，也不顯示即時借閱狀態。

## 主要功能

- **九館**：臺中、臺北、臺南、新北、高雄、桃園、新竹縣、新竹市、基隆。
- **搜尋**：書名搜尋、指定圖書館、該館有／未列出、最新發刊時間（30／90／180 天）。
- **收錄館數可複選**：9／8／7／6／5／4／3／2／1 館；可自由組合。
- **資料分離**：前端 `docs/` 靜態網站，資料 `docs/data/catalog.json`；不須資料庫服務。
- **輔助增量更新**：目前暫停 GitHub Runner 的 HyRead 抓取排程（九館皆遭 HTTP 403）；改由 ChatGPT 檢索後提交經驗證的增量批次。操作見 [`docs/ASSISTED_UPDATE.md`](docs/ASSISTED_UPDATE.md)。
- **限制重試**：輔助查詢遇暫時性錯誤時每館最多額外重試 **2 次**，並在 2–5／6–12 秒範圍隨機等待；403、401 等存取拒絕立即停止。舊版程式自動擷取已停用排程。分類頁正常請求間隨機等待 1.5～3.5 秒；暫時錯誤依序隨機退避 2～5、5～10、10～20 秒；遇到 HTTP 429 遵守 `Retry-After`（若要求等待超過 60 秒則停止該館本次掃描），遇到 HTTP 401／403 立即停止、不再重試。這是降低伺服器負擔的禮貌節流，不能繞過存取限制。
- **失敗保護**：12 分類需全部驗證成功、異常大幅減少不覆蓋；若失敗保留該館上次成功資料、顯示過期警示。
- **保留策略**：不同圖書館、不同版別分開；只顯示每個書名每館最新一期；書目（包含最後已知發刊日）長期保存，最近 180 天變動歷史儲存在 `data/history.json`；連續三次完整核對仍不存在才標記不再列出。
- **CSV**：匯出當前篩選結果。
- **V1.6 預設簡化更新**：ChatGPT 手動查詢每館「最新出刊」第 1 頁起，按指令最近 N 天的確切日期界線翻頁，**不加 7 天、不重查第 1 頁**。快取分頁也能列入，但若同書刊期比資料庫舊須按規定重試兩次並提醒。每館正常完成後儲存第 1 頁首本書的書名／jid／日期／網址作為下次接續參考。未查到舊書不刪除；保留原詳細連結。ChatGPT schema 3 說明見 `docs/ASSISTED_UPDATE.md`。
- **歷史模式保留**：V1.4／V1.5 的嚴格批次格式相容，僅供舊資料與測試使用。
- **V1.5 ChatGPT 分頁證據與診斷**：依然由 ChatGPT 查詢九館並合併 GitHub；新增 schema 2 同批次 `scan_id`、每頁 SHA-256 書目摘要、第 1 頁重查、快取建立時間（若可得）、缺頁與錯誤碼診斷。非直接來源或跨時快取只能部分核對，保留舊資料。詳見 `docs/ASSISTED_UPDATE.md`。
- **V1.4 最新出刊優先**：每館先查 `magazine_view_more.jsp`，連續分頁查到日期界線；搜索引擎舊索引不作完整核對證據。只在無法連續讀取時補查分類頁。
- **雜誌詳細頁**：逐本逐館保留官方 `magazine_more.jsp?jid=...` 於 `magazine_url`，原資料缺乏 `jid` 則保留空值，不推測或捏造。
- **更新紀錄**：網站顯示最近一次各館成功/失敗、當次核對筆數、新增書名與最新刊期變化（逐筆可展開），附 180 天簡要執行歷史及 GitHub Actions 連結。初始資料不會冒充排程抓取成功。

## 資料定義

`data/initial-snapshot.json` 是 2026-10-30 手工核對的九館起始清單，共 129 種不重複雜誌；資料完整性及後續日期變化需要透過**實際排程執行**驗證。原始資料保留供稽核，不代表目前可借閱。輔助更新優先從官方「最新出刊」書櫃依序核對頁面與日期界線，缺漏時才利用 12 類分類頁補查。只有最新發刊日 >= `2026-09-20` 的新書目會加入可搜尋資料；已加入的書目即使超過 180 天，也不會因清理歷史而刪除。

某館本次成功完整抓取但未發現已知書目時，先累積「未列出」次數，連續三次才將其改成不再列出；保留原記錄而不是刪掉。某館抓取失敗時絕不增加未列出次數。網站中的「未列出」是索引意義，不表示沒有舊刊。

## 首次部署（只需要一次）

1. 在 GitHub 建立空白 **Public** repository，名稱建議 **`hyread-magazine-finder`**，預設分支 `main`。
2. 將此 ZIP 解壓後的**所有檔案（包括 `.github/` 及 `docs/`）**推送至 `main`。
3. 到 **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。
4. 此時 `.github/workflows/deploy-pages.yml` 可在 `main` 推送時自動發布；也可在 Actions 手動執行 **Deploy HyRead search to GitHub Pages**。網站網址預計為 `https://<你的帳號>.github.io/hyread-magazine-finder/`，以 Pages 顯示的實際連結為準。
5. 目前請在 ChatGPT 對話中要求核對／合併九館書目；GitHub Actions 的 `Validate HyRead assisted updates` 只執行單元測試，**不會重新抓取 HyRead**。

備註：若 repo 不是 `chihsun/hyread-magazine-finder`，請同步修改 `docs/index.html` 的管理者更新網址。

**Cloudflare Pages 選項**：可以將此 repo 連接 Cloudflare Pages，Framework preset 選 `None`，Build command 留空，Build output directory 設 `docs`。不需要同時使用兩種網站部署，選擇一個即可。

## 本機開發與驗證

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.update --seed-only   # 僅把起始資料轉成網站 JSON，不對外連線
python -m src.assisted_update assisted-batch.json --dry-run  # 檢查增量批次
python -m src.assisted_update assisted-batch.json --apply    # 驗證後套用
python -m http.server 8000 -d docs
```

在瀏覽器開啟 `http://localhost:8000`。

## 目錄

```
.github/workflows/      定時更新與 Pages 部署
config/libraries.json   九館來源設定
data/state.json         永久累積的各館最新書目；失敗不覆蓋
data/history.json       180 天變動歷史
src/hyread.py           最新出刊及分類書單解析、共享重試額度
src/coverage.py         分頁完整性、日期界線及詳細頁網址檢查
src/update.py           核對、合併、完整性保護、發布
scripts/                （尚無額外指令）
docs/                   靜態網頁、資料 JSON（含 update-report.json；可直接部署）
tests/                  資料與爬蟲邏輯測試
```

## 使用量與安全

公開儲存庫搭配標準 GitHub Actions runner、每週 9 館 × 12 類（約 108 個網站請求＋少量失敗重試）。有 20 分鐘執行上限、`concurrency` 防重疊。請遵守 HyRead 使用規範並避免頻繁手動刷新。GitHub Actions scheduler 可能延遲，或因 GitHub inactivity policy 而停用；建議偶爾確認 Actions 紀錄。

## 限制

- HyRead 隨時可能改版，分類頁的解析規則需跟著修改；**首次排程必須實際執行以驗證抓取是否成功**。
- 這個 repo 僅索引公開 metadata，不登入、不繞過封鎖、不抓取雜誌正文或封面。
- 若 GitHub Pages 尚未啟用，網站不會自動取得公開網址。
- Github Actions 的成功與否以 workflow 執行結果為準，網站發布 JSON 會標示過期的館別。

## 2026-10-30：輔助更新模式（重要）

首次 GitHub 雲端執行九館皆回覆 HTTP 403，因此暫停原本的週更爬蟲排程；用 ChatGPT 助理每次取得來源明確的部分資料、確認後合併，並由 GitHub Pages 發布。**增量核對不等於完整掃描**；既有雜誌未查到仍保留。每館暫時性失敗最多再試 2 次（共 3 次），使用隨機間隔；拒絕存取的 401／403 立即停止。詳見 [`輔助更新操作規範`](docs/ASSISTED_UPDATE.md)。
