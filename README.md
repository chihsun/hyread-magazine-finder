# HyRead 九館電子雜誌搜尋

搜尋臺灣九間公共圖書館 HyRead 電子雜誌的最新發刊日期，並比較哪些館列出指定雜誌。網站是公開書目索引，不提供雜誌全文、借閱狀態或使用者資料。

## 功能

- 搜尋雜誌名稱，篩選指定圖書館、該館有／未列出，以及最近 30／90／180 天的最新發刊日期。
- 任意選擇 1～9 間圖書館；目前包括臺中、臺北、臺南、新北、高雄、桃園、新竹縣、新竹市與基隆。
- 將目前篩選結果匯出為 CSV。
- 使用靜態網站與 JSON 資料：`docs/` 是網站內容，`docs/data/catalog.json` 是書目索引，無須資料庫服務。
- 顯示各館最近核對狀態、查得筆數、資料異動與更新歷史。增量更新未找到的舊書仍保留，不會據此判定下架。

## 目前的書目更新方式

GitHub Actions 不會定時抓取 HyRead。GitHub runner 曾遭 HyRead 拒絕存取，因此每週抓取排程已移除；目前以使用者核對來源後提供的 **schema 4** 增量批次更新資料。詳細欄位及步驟見 [`docs/ASSISTED_UPDATE.md`](docs/ASSISTED_UPDATE.md)。

目前流程從每館不帶 `?nowpage=1` 的最新出刊第 1 頁開始，再按順序檢查必要分頁。若網頁工具無法讀取，可使用內容、館別與頁碼都能辨認的搜尋索引頁面；連續頁面涵蓋日期下限時可以完成日期範圍核對，但必須把來源記為 `search_index`，不可說成即時 HTTP 回應。沒有實際收到 HTTP 狀態碼時，不要把工具錯誤寫成 HTTP 403。

只合併本次有來源證據的書目。較舊刊期不會覆蓋已知新刊期；未核實的書目連結不會猜測或覆蓋舊值。schema 4 的新連結須有同頁書名錨點證據。最近 N 天以臺灣日期計算為最早紙本刊期下限，提前上架的未來刊期也會納入。

程式仍保留 `python -m src.update --once` 的直接擷取入口，但目前沒有 GitHub Actions 排程呼叫它。這個入口使用 12 類分類頁；GitHub Actions 不會因此自動抓取 HyRead。

## GitHub Actions

| Workflow | 觸發方式與工作 |
|---|---|
| `Validate HyRead assisted updates` | 手動執行，或在程式／測試／前端程式變更時執行測試與語法檢查；不連線 HyRead。 |
| `Import verified ChatGPT HyRead batch` | 非 `main` 分支新增輔助批次 JSON 時執行；每次推送必須剛好新增一個批次。通過測試與乾跑後套用批次，並將產生的資料檔 commit 回同一分支。`main` 分支不執行此匯入 workflow。 |
| `Deploy HyRead search to GitHub Pages` | `main` 分支的 `docs/**` 或部署 workflow 變更時部署；也可手動執行。輸出目錄是 `docs/`。 |

直接把人工驗證後的資料與網站 JSON 更新推送到 `main` 時，匯入 workflow 會略過該次推送；若要使用分支上的自動匯入，新增批次後等待 workflow 在該分支產生資料更新，再將分支合併到 `main`。包含 `docs/` 變更的 `main` 更新會觸發 Pages 部署。

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

