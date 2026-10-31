# HyRead 九館電子雜誌搜尋

搜尋臺灣九間公共圖書館 HyRead 電子雜誌的最新發刊日期，並比較哪些館列出指定雜誌。網站是公開書目索引，不提供雜誌全文、借閱狀態或使用者資料。

## 功能

- 搜尋雜誌名稱，篩選指定圖書館、該館有／未列出，以及最近 30／90／180 天的最新發刊日期。
- 任意選擇 1～9 間圖書館；目前包括臺中、臺北、臺南、新北、高雄、桃園、新竹縣、新竹市與基隆。
- 將目前篩選結果匯出為 CSV。
- 使用靜態網站與 JSON 資料：`docs/` 是網站內容，`docs/data/catalog.json` 是書目索引，無須資料庫服務。
- 顯示各館最近核對狀態、查得筆數、資料異動與更新歷史。增量更新未找到的舊書仍保留，不會據此判定下架。

## 目前的書目更新方式

由於 HyRead 針對自動化連線有驗證保護，**不使用 GitHub Runner 每週抓取書目**。目前由使用者在正常 Chrome／Edge 瀏覽器人工取得最新書單，透過 Windows 本機工具離線整理、驗證及增量合併後，將 `data/`、`docs/data/` 等更新結果推送至 GitHub。GitHub Actions 仍可做程式測試與網站部署，但不會自行連線取得 HyRead 書目。schema 4 欄位與歷史核對規則保存在 [`docs/ASSISTED_UPDATE.md`](docs/ASSISTED_UPDATE.md)。

本機採集器應記錄每館官方最新出刊清單的頁碼、書名、刊期與同館詳細連結；第 1 頁網址不帶 `?nowpage=1`。依查詢起日確認連續分頁與日期界線。所有書目與錯誤狀態須有來源證據；頁面缺漏時只能標記部分核對，不能宣稱已完整更新。

只合併本次有來源證據的書目。較舊刊期不會覆蓋已知新刊期；未核實的書目連結不會猜測或覆蓋舊值。schema 4 的新連結須有同頁書名錨點證據。最近 N 天以臺灣日期計算為最早紙本刊期下限，提前上架的未來刊期也會納入。

舊版 `python -m src.update --once` 入口僅供歷史相容／開發測試，不是正式更新方式，也沒有任何 Actions 排程呼叫它。每次 `docs/data/update-report.json` 會顯示新增書名、刊期更新與各館異動，歷史批次也能展開查看曾記錄的書名。

## GitHub Actions

| Workflow | 觸發方式與工作 |
|---|---|
| `Validate HyRead catalog data` | 手動執行，或程式／測試／前端變更時進行回歸測試；不連線 HyRead。 |
| `Import verified local HyRead batch (optional)` | **舊版相容、選用**：非 `main` 分支新增 `data/assisted-batches/*.json` 時驗證並合併該批次，將結果 commit 回同一分支；不抓取 HyRead，`main` 分支不執行。一般本機合併後直接推送 `main` 不需使用此 workflow。 |
| `Deploy HyRead search to GitHub Pages` | `main` 分支的 `docs/**` 或部署 workflow 變更時部署；也可手動執行。輸出目錄是 `docs/`。 |

本機完成合併、驗證並直接推送 `main` 後，若變更包含 `docs/`，Pages 部署 workflow 會觸發。**這是網站發布，不是自動抓取書目。** 只有特別使用非 `main` 分支批次匯入流程，才會觸發上述選用的資料匯入 workflow。

## 部署

在 repository 設定 **Settings → Pages → Build and deployment → Source → GitHub Actions**。`main` 上 `docs/` 內容更新後，部署 workflow 會發布該目錄；網站 URL 以 Pages 設定頁顯示的網址為準。也可改用 Cloudflare Pages，Framework preset 選 `None`、Build command 留空、Build output directory 設為 `docs`。

## 本機開發與驗證

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.update --seed-only
python -m src.assisted_update assisted-batch.json --dry-run
python -m src.assisted_update assisted-batch.json --apply
python -m http.server 8000 -d docs
```

`--dry-run` 驗證批次並預覽異動，不寫入資料；檢查結果後才使用 `--apply`。本機開啟 `http://localhost:8000` 可預覽網站。手動批次的來源檔案位於 `data/assisted-batches/`。

## 主要檔案

```text
config/libraries.json         九館設定
data/state.json               長期保存的各館書目狀態
data/history.json             最近 180 天書目異動
src/assisted_update.py        輔助批次驗證、增量合併與報表
src/coverage.py               日期界線、分頁與來源證據驗證
src/latest_pages.py           最新出刊頁面的網址與 HTML 證據解析
src/hyread.py                 網頁解析及舊版分類擷取邏輯
src/update.py                 直接擷取與網站 JSON 產生入口
docs/                         靜態網站與公開 JSON 資料
tests/                        Python 與前端回歸測試
.github/workflows/            測試、輔助批次匯入與 Pages 部署
```

`data/initial-snapshot.json` 是 2026-10-30 核對的初始資料快照，不代表即時館藏或目前借閱狀況。完整核對、部分核對與失敗狀態請以網站資料中的最近更新紀錄為準。

## 使用範圍與限制

- 僅索引公開書目 metadata；不登入、不下載雜誌內容或封面，也不嘗試繞過存取限制。
- HyRead 頁面結構可能變動；讀取不完整時保留舊資料並如實標示狀態。
- 最近發刊日期不是即時借閱狀態，也不代表尚未列出的館藏不存在。
- GitHub Pages 須先啟用，並等待對應部署 workflow 成功，網站資料才會更新。

