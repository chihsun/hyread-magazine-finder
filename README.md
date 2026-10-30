# HyRead 九館電子雜誌搜尋 v1

搜尋九間臺灣公共圖書館 HyRead 電子雜誌的**最新發刊日期**，比較哪幾館列出特定雜誌。這是公開書目索引，不提供電子書內容下載，也不顯示即時借閱狀態。

## 主要功能

- **九館**：臺中、臺北、臺南、新北、高雄、桃園、新竹縣、新竹市、基隆。
- **搜尋**：書名搜尋、指定圖書館、該館有／未列出、最新發刊時間（30／90／180 天）。
- **收錄館數可複選**：9／8／7／6／5／4／3／2／1 館；可自由組合。
- **資料分離**：前端 `docs/` 靜態網站，資料 `docs/data/catalog.json`；不須資料庫服務。
- **每週更新**：GitHub Actions 每週五臺灣時間 08:00（實際啟動可能延遲）；支援 Actions `workflow_dispatch`。
- **限制重試**：**每館首次嘗試外，最多再重試三次**；共用整館額度，不會每頁三次造成指數放大。
- **失敗保護**：12 分類需全部驗證成功、異常大幅減少不覆蓋；若失敗保留該館上次成功資料、顯示過期警示。
- **保留策略**：不同圖書館、不同版別分開；只顯示每個書名每館最新一期；書目（包含最後已知發刊日）長期保存，最近 180 天變動歷史儲存在 `data/history.json`；連續三次完整核對仍不存在才標記不再列出。
- **CSV**：匯出當前篩選結果。
- **更新紀錄**：網站顯示最近一次各館成功/失敗、當次核對筆數、新增書名與最新刊期變化（逐筆可展開），附 180 天簡要執行歷史及 GitHub Actions 連結。初始資料不會冒充排程抓取成功。

## 資料定義

`data/initial-snapshot.json` 是 2026-10-30 手工核對的九館起始清單，共 129 種不重複雜誌；資料完整性及後續日期變化需要透過**實際排程執行**驗證。原始資料保留供稽核，不代表目前可借閱。後續更新從 12 類官方 HyRead 雜誌分類頁讀取每種雜誌的「最新發刊」。只有最新發刊日 >= `2026-09-20` 的新書目會加入可搜尋資料；已加入的書目即使超過 180 天，也不會因清理歷史而刪除。

某館本次成功完整抓取但未發現已知書目時，先累積「未列出」次數，連續三次才將其改成不再列出；保留原記錄而不是刪掉。某館抓取失敗時絕不增加未列出次數。網站中的「未列出」是索引意義，不表示沒有舊刊。

## 首次部署（只需要一次）

1. 在 GitHub 建立空白 **Public** repository，名稱建議 **`hyread-magazine-finder`**，預設分支 `main`。
2. 將此 ZIP 解壓後的**所有檔案（包括 `.github/` 及 `docs/`）**推送至 `main`。
3. 到 **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。
4. 此時 `.github/workflows/deploy-pages.yml` 可在 `main` 推送時自動發布；也可在 Actions 手動執行 **Deploy HyRead search to GitHub Pages**。網站網址預計為 `https://<你的帳號>.github.io/hyread-magazine-finder/`，以 Pages 顯示的實際連結為準。
5. 到 **Actions → Weekly HyRead magazine update → Run workflow** 可立即重新查九館；排程則自動每週五執行。網站右上方「管理者更新」連結指向此頁，**使用 GitHub 自身權限，不需要將 token 放在公開網站**。

備註：若 repo 不是 `chihsun/hyread-magazine-finder`，請同步修改 `docs/index.html` 的管理者更新網址。

**Cloudflare Pages 選項**：可以將此 repo 連接 Cloudflare Pages，Framework preset 選 `None`，Build command 留空，Build output directory 設 `docs`。不需要同時使用兩種網站部署，選擇一個即可。

## 本機開發與驗證

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.update --seed-only   # 僅把起始資料轉成網站 JSON，不對外連線
python -m src.update --once        # 擷取九館，需網路
python -m http.server 8000 -d docs
```

在瀏覽器開啟 `http://localhost:8000`。

## 目錄

```
.github/workflows/      定時更新與 Pages 部署
config/libraries.json   九館來源設定
data/state.json         永久累積的各館最新書目；失敗不覆蓋
data/history.json       180 天變動歷史
src/hyread.py           分類書單解析、共享重試額度
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
