# HyRead 九館公開搜尋網站｜V1 開發計畫與驗收紀錄

> **文件狀態（2026-10-31）**：這是 2026-10-30 的 V1.0 原始計畫，以下設計內容與驗收表保留作歷史紀錄，不代表目前排程或部署狀態。HyRead 在 GitHub runner 上回覆 HTTP 403 後，定時擷取工作流程已移除；目前使用 schema 4 輔助批次更新。現行操作見 [README](README.md) 與 [輔助更新規範](docs/ASSISTED_UPDATE.md)。

**版本**：V1.0（2026-10-30）  
**部署選擇**：Public GitHub Repository + GitHub Actions + GitHub Pages（Cloudflare Pages 亦可連接）  
**原始九館資料截止日**：2026/09/20（含）；**初始核對日**：2026/10/30。

## 目標與邊界

- 前端 UI 與原始來源資料分離：`docs/` 與 `docs/data/catalog.json`。
- 任意輸入書名；勾選任意組合的 1～9 館；指定圖書館並設定有／未列出。
- 每週五 08:00 臺灣時間自動擷取與驗證；登入 GitHub 的管理者可用 Actions 手動執行。
- 各館**最多額外重試 3 次（整館共用）**、每次排程最多運行 20 分鐘。
- 只呈現每館每書名最新發刊日期，不抓取全文、借閱歷史或使用者資料。
- 新書目累積；最新日期保留；180 天以外變動事件自動清理；過期的新刊仍可於書單檢視。
- 不確定資料不得誤標成確定無書：部分抓取失敗保留舊資料並標示過期。

## 執行設計

1. 擷取九館官方 `magazine-list.jsp?magazineclass=M01...M12`，共 108 個分類請求；每頁完整解析所有「書名／最新發刊」，並留存來源。
2. 各館所有類別都必須成功、總數合理，才採用該館新資料；異常數量驟降（低於歷史有效總量 55%）拒絕覆蓋。
3. 一館失敗不影響其他館；每館的 `last_success`、`last_attempt` 與失敗原因皆可查詢。
4. 新書首次列出、發刊日期更新以及連續三次完整核對未列出均記入歷史事件；事件滾動保留 180 天。
5. 寫入 `data/state.json`（長期書目）、`data/history.json`（變動）、`docs/data/catalog.json`（網站索引）、`docs/data/status.json`（健康狀態）。
6. GitHub Actions 只有在確實有檔案變動時才 commit。部署工作流程由 `docs/` 改變觸發；每週狀態更新通常也會觸發部署。
7. 網站載入 `catalog.json`；結果初始每頁顯示 30 種，點「顯示更多」繼續；CSV 匯出目前符合條件的所有列。

## 驗收項目與結果

| 項目 | 狀態 | 依據 |
|---|---|---|
| 九館設定與初始資料 | ✅ | 129 種不重複、110 種九館共同收錄 |
| 前端 HTML/JS/CSS 輸出 | ✅ | 原始碼及 `node --check` |
| JSON 不需 HTML 內嵌 | ✅ | `docs/data/catalog.json` 獨立 |
| 版別不合併 | ✅ | 測試 |
| 三次重試為每館總額度 | ✅ | 測試 |
| 發刊日期只增不回退 | ✅ | 測試（新刊日期保持已知最大值） |
| 三次完整核對未列出後停用 | ✅ | 測試 |
| 可疑縮減拒絕覆蓋 | ✅ | 測試 |
| 九館每週自動工作流程 | ⏸ 已移除 | GitHub runner 於 2026-10-30 對九館來源回覆 HTTP 403；目前沒有定時擷取 |
| GitHub Pages | ✅ 部署 workflow 已設定 | 實際部署狀態以 repository 的 Actions 與 Pages 設定為準 |
| HyRead runner 即時擷取 | ⏸ 不使用 | 來源拒絕 GitHub runner 存取；目前更新改用經核對的輔助批次 |
| 手機瀏覽器端到端測試 | ⏳ | Chromium 在本環境被管理政策禁止讀取本機頁面；JS 語法及資料檢查已通過 |

## 風險與決策

- HyRead HTML 可能更動；第一次 Actions 實跑若失敗，立即保留完整舊資料，依錯誤日誌修正解析器。
- 雜誌書名正規化 NFKC、全半形、空白、臺台差異；一般版與精華版維持不同實體。
- 先採 GitHub Pages，避免未授權的 Cloudflare 設定；上線後可無縫切至 Cloudflare Pages。
- 公開頁面不含任何 GitHub token，手動更新透過 GitHub Actions 原生授權執行。
- 公開頁面不提供匿名訪客直接更新資料的 API。管理者更新方式已改為依 [輔助更新規範](docs/ASSISTED_UPDATE.md) 提交經核對的批次。

## 原始部署計畫（歷史）

1. 在 GitHub 建立空的 Public repo：`chihsun/hyread-magazine-finder`。
2. 將本專案所有檔案上傳到預設 `main` 分支。
3. GitHub 設定 `Settings > Pages > Source > GitHub Actions`。
4. 手動執行 `Deploy HyRead search to GitHub Pages`，確認取得公開連結。
5. 原計畫中的 `Weekly HyRead magazine update` 已不再執行；目前 `update-magazines.yml` 只做驗證，不會向 HyRead 發送請求。依目前流程更新書目請看 [輔助更新規範](docs/ASSISTED_UPDATE.md)。

