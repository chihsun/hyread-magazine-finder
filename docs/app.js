'use strict';
const $ = id => document.getElementById(id);
const state = { payload: null, records: [], limit: 30 };
const safe = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const collator = new Intl.Collator('zh-Hant-TW', { numeric: true, sensitivity: 'base' });
function notice(s, type = '') { const e = $('alert'); e.textContent = s; e.className = 'alert ' + type; }
function countLabel(n, total) { return n === total ? `${total === 9 ? '九' : total}館都有` : n === 1 ? '只有一館有' : `${['', '一', '兩', '三', '四', '五', '六', '七', '八', '九'][n] || n}館有`; }
function renderOptions() {
  const p = state.payload;
  $('libtotal').textContent = p.libraries.length;
  $('total').textContent = p.magazines.length;
  $('common').textContent = p.distribution[String(p.libraries.length)] || 0;
  $('updated').textContent = p.generated_at?.slice(0, 16).replace('T', ' ') || '—';
  $('library').innerHTML = '<option value="">全部圖書館</option>' + p.libraries.map(x => `<option value="${safe(x.id)}">${safe(x.name)}</option>`).join('');
  $('counts').innerHTML = Array.from({ length: p.libraries.length }, (_, i) => p.libraries.length - i).map(n => `<label class="pill"><input type="checkbox" name="count" value="${n}" checked><span>${countLabel(n, p.libraries.length)}</span><em>${p.distribution[String(n)] || 0} 種</em></label>`).join('');
  $('source-links').innerHTML = p.libraries.map(x => `<a href="https://${encodeURIComponent(x.id)}.ebook.hyread.com.tw/Template/RWD3.0/magazine.jsp" target="_blank" rel="noopener noreferrer">${safe(x.name)} ↗</a>`).join('');
}
// Calendar-day difference in Asia/Taipei; avoids UTC / browser-time-zone off-by-one errors.
function taiwanToday() {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const vals = Object.fromEntries(parts.filter(p => p.type !== 'literal').map(p => [p.type, p.value]));
  return `${vals.year}-${vals.month}-${vals.day}`;
}
function dayNumber(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || '')) return NaN;
  const [y, m, d] = iso.split('-').map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 86400000);
}
function latestDate(row, selected) {
  if (selected) return row.by[selected]?.date || '';
  let max = '';
  for (const v of Object.values(row.by || {})) if (v.date > max) max = v.date;
  return max;
}
function recentMatch(row, value, lib, todayNumber) {
  if (value === 'all') return true;
  const date = latestDate(row, lib);
  const n = dayNumber(date);
  if (!Number.isFinite(n)) return false;
  const age = todayNumber - n;
  if (value === 'old90') return age > 90;
  return age >= 0 && age <= Number(value);
}
function updateSortLabels() {
  const byTitle = $('sortby').value === 'title';
  $('sortdir').options[0].textContent = byTitle ? '書名 Z → A（降冪）' : '由新至舊（降冪）';
  $('sortdir').options[1].textContent = byTitle ? '書名 A → Z（升冪）' : '由舊至新（升冪）';
}
function query() {
  const p = state.payload;
  if (!p) return;
  const wanted = new Set([...document.querySelectorAll('input[name=count]:checked')].map(x => Number(x.value)));
  const needle = $('query').value.trim().toLocaleLowerCase();
  const selected = $('library').value, presence = $('presence').value, fresh = $('freshness').value;
  const sortBy = $('sortby').value, dir = $('sortdir').value === 'asc' ? 1 : -1;
  const today = dayNumber(taiwanToday());
  state.records = p.magazines.filter(r => wanted.has(r.count) && r.title.toLocaleLowerCase().includes(needle) &&
    (!selected || presence === 'all' || (presence === 'yes' ? Boolean(r.by[selected]) : !r.by[selected])) &&
    recentMatch(r, fresh, selected, today));
  state.records.sort((a, b) => {
    if (sortBy === 'title') return collator.compare(a.title, b.title) * dir;
    const dateA = latestDate(a, selected), dateB = latestDate(b, selected);
    // Missing dates always last, independent of ascending/descending order.
    if (!dateA && dateB) return 1;
    if (!dateB && dateA) return -1;
    if (dateA !== dateB) return (dateA < dateB ? -1 : 1) * dir;
    return collator.compare(a.title, b.title);
  });
  state.limit = 30;
  drawRecords();
}
function officialLink(url) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && u.hostname.endsWith('.ebook.hyread.com.tw') ? u.href : '';
  } catch (_) { return ''; }
}
function drawRecords() {
  const p = state.payload;
  $('matched').textContent = `符合條件 ${state.records.length} 種雜誌`;
  $('more').hidden = state.records.length <= state.limit;
  $('more').textContent = `顯示更多（已顯示 ${Math.min(state.limit, state.records.length)} / ${state.records.length} 種）`;
  if (!state.records.length) {
    $('results').innerHTML = '<div class="empty">沒有符合條件的雜誌。可調整館數勾選或清除搜尋字詞。</div>';
    return;
  }
  const hideMissing = $('hideMissing').checked;
  $('results').innerHTML = state.records.slice(0, state.limit).map(r => `<article class="item"><div class="item-top"><h3>${safe(r.title)}</h3><span class="count-chip">${r.count} / ${p.libraries.length} 館</span></div><div class="libs">${p.libraries.filter(l => !hideMissing || Boolean(r.by[l.id])).map(l => {
    const v = r.by[l.id], stale = l.status === 'stale' || l.status === 'partial';
    if (!v) return `<div class="lib-row"><span>${safe(l.name)}</span><span class="missing">— 未列出</span></div>`;
    const link = officialLink(v.source_url);
    const detail = officialLink(v.magazine_url);
    const label = `✓ ${safe(v.date)} ${stale ? '⚠' : ''} ${link ? '↗' : ''}`;
    const source = link ? `<a class="${stale ? 'stale' : ''}" href="${safe(link)}" target="_blank" rel="noopener noreferrer" title="${stale ? '本館部分核對或更新失敗；舊有資料可能需要重新確認' : '來源書櫃'}">${label}</a>` : `<span>${label}</span>`;
    const detailLink = detail ? `<a class="detail-link" href="${safe(detail)}" target="_blank" rel="noopener noreferrer" title="開啟該館此雜誌的書目詳情">書目詳情 ↗</a>` : '';
    return `<div class="lib-row"><span>${safe(l.name)}</span><span class="lib-links">${source}${detailLink}</span></div>`;
  }).join('')}</div></article>`).join('');
}
function exportCSV() {
  const p = state.payload;
  if (!p) return;
  // Keep the full nine-library comparison in exported CSV, even if empty rows are hidden on screen.
  const rows = [['雜誌名稱', '收錄館數', ...p.libraries.map(x => x.name)], ...state.records.map(r => [r.title, r.count, ...p.libraries.map(x => r.by[x.id]?.date || '未列出')])];
  const csv = '\ufeff' + rows.map(r => r.map(v => {
    let x = String(v ?? ''); if (/^[=+@\-\t\r]/.test(x)) x = "'" + x;
    return '"' + x.replace(/"/g, '""') + '"';
  }).join(',')).join('\r\n');
  const u = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a'); a.href = u; a.download = 'HyRead_九館雜誌_篩選結果.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(u), 3000);
}
function themeMode() { return $('theme').value === 'auto' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : $('theme').value; }
function syncThemeColor() { $('theme-color').setAttribute('content', themeMode() === 'dark' ? '#111e2d' : '#0b3552'); }
function setTheme(mode) {
  if (mode === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = mode;
  try { localStorage.setItem('hyread-theme', mode); } catch (_) { /* private browsing */ }
  syncThemeColor();
}
function initTheme() {
  let mode = 'auto';
  try { mode = localStorage.getItem('hyread-theme') || 'auto'; } catch (_) { /* localStorage unavailable */ }
  if (!['auto', 'light', 'dark'].includes(mode)) mode = 'auto';
  $('theme').value = mode;
  setTheme(mode);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncThemeColor);
}
function fmtStamp(value) {
  if (!value) return '—';
  const m=String(value).match(/^(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?/);
  return m ? `${m[1]} ${m[2] || ''}`.trim() + (String(value).includes('+08:00') ? '（臺灣）' : '') : String(value);
}
function changeLines(entries, kind) {
  if (!entries?.length) return '';
  const labels={new:'新增書名',new_issue:'新刊期',returned:'恢復列出',not_listed:'停止列出',link_added:'補上書目連結',link_changed:'修正書目連結'};
  const body=entries.map(e => `<li>${safe(e.title)}${kind==='new_issue'?`：${safe(e.from)} → ${safe(e.to)}`:e.to?`（${safe(e.to)}）`:''}</li>`).join('');
  return `<div class="change-group"><strong>${labels[kind]} ${entries.length} 筆</strong><ul>${body}</ul></div>`;
}
function renderReport(report) {
  const summary=$('update-summary'), libraries=$('update-libraries'), history=$('update-history');
  if (report.type === 'seed' || !report.summary) {
    summary.innerHTML='<div class="report-status"><span class="status-badge seed">初始資料</span><strong>尚無正式核對的增量更新紀錄</strong></div><p>目前顯示的是先前核對的九館初始書單；不是最近一次自動完整擷取。</p>';
    libraries.innerHTML=(report.libraries||[]).map(l=>`<div class="report-library"><strong>${safe(l.name)}</strong><span>初始收錄 ${Number(l.active_count)||0} 筆</span></div>`).join('');
    history.textContent='尚無正式的增量核對紀錄。';
    return;
  }
  const s=report.summary, assisted=report.type==='chatgpt_assisted', all=report.complete;
  const partial=Number(s.partial)||0, failed=Number(s.failed)||0, unchecked=Number(s.not_checked)||0;
  const badge=assisted?'人工輔助增量':'自動完整擷取';
  summary.innerHTML=`<div class="report-status"><span class="status-badge ${all?'ok':'stale'}">${safe(badge)}${all?' · 範圍完成':' · 未完全核對'}</span><strong>${Number(s.successful)||0} 館範圍完成 · ${partial} 館部分 · ${failed} 館失敗${unchecked?' · '+unchecked+' 館未查':''}</strong><small>執行時間：${safe(fmtStamp(report.generated_at))}</small></div>
    ${assisted?`<p class="report-note">本次核對刊期範圍：${safe(report.window_start)} ～ ${safe(report.window_end)}。完成僅指該日期範圍；並非所有舊刊、全部分類都已重新確認。未查到的書名一律保留。</p>`:''}
    <div class="update-stats"><span>本次確認 <b>${Number(s.verified_records)||0}</b> 筆</span><span>資料庫現有 <b>${Number(s.active_records)||0}</b> 筆（含沿用）</span><span>新增書名 <b>${Number(s.new_titles)||0}</b> 筆</span><span>新刊期 <b>${Number(s.new_issues)||0}</b> 筆</span><span>恢復列出 <b>${Number(s.returned)||0}</b> 筆</span><span>停止列出 <b>${Number(s.not_listed)||0}</b> 筆</span><span>補上書目連結 <b>${Number(s.links_added)||0}</b> 筆</span><span>修正書目連結 <b>${Number(s.links_changed)||0}</b> 筆</span><span>已檢查頁面 <b>${Number(s.pages_checked)||0}</b> 頁</span><span>失敗頁面 <b>${Number(s.pages_failed)||0}</b> 頁</span></div>
    <p class="report-note">新增與新刊期以「雜誌 × 圖書館」計算。未完整核對的館別保留已確認的變動，其他書目不刪除、不視為下架；最新資料日期不等於全部九館均完成核查。</p>`;
  libraries.innerHTML=(report.libraries||[]).map(l=>{
    const c=l.changes||{}, changeCount=Number(l.change_count)||0;
    const kind=l.status==='ok'?'ok':l.status==='partial'?'partial':l.status==='not_checked'?'not_checked':'stale';
    const wording={ok:'✓ 範圍已核對',partial:'◐ 部分核對',stale:'⚠ 查詢失敗／沿用',not_checked:'— 本次未核對'}[kind];
    const changes=['new','new_issue','returned','not_listed','link_added','link_changed'].map(k=>changeLines(c[k],k)).join('');
    const count=typeof l.verified_count==='number'?`本次確認 ${l.verified_count} 筆`:'本次無有效核對筆數';
    const coverage=l.coverage||{};
    const pages=Array.isArray(coverage.pages)?coverage.pages:[];
    const verifiedPages=Number(coverage.checked_pages)||0;
    const failedPages=Number(coverage.failed_pages)||0;
    const boundary=coverage.date_boundary_reached?'✓ 已驗證日期界線':'日期界線未確認';
    const coverageLine=assisted?`<p class="report-muted">頁面核對：${verifiedPages} 頁通過，${failedPages} 頁失敗 · ${boundary} · 來源 ${safe(coverage.method||'unknown')} ${pages.length?` · 已記錄 ${pages.length} 頁來源`:''}</p>`:'';
    const diagnostic=coverage.diagnostics||{};
    const problems=Array.isArray(diagnostic.issues)?diagnostic.issues:[];
    const gaps=Array.isArray(diagnostic.missing_pages)?diagnostic.missing_pages:[];
    const sourceKinds=diagnostic.source_types||{};
    const diagnosticLine=assisted && (l.error_code || coverage.scan_id || problems.length || gaps.length || sourceKinds.search_index)?
      `<p class="report-muted">診斷：${l.error_code?`<strong>${safe(l.error_code)}</strong> · `:''}${coverage.scan_id?`批次 ${safe(coverage.scan_id)} · `:''}直接來源 ${Number(sourceKinds.direct)||0} 頁、搜尋快取 ${Number(sourceKinds.search_index)||0} 頁${gaps.length?` · 缺頁 ${safe(gaps.join(', '))}`:''}${problems.length?` · 警示 ${safe(problems.join('、'))}`:''}</p>`:'';
    const pagesLine=pages.length?`<details class="change-details"><summary>查看已查／缺漏分頁（${pages.length}）</summary><ul>${pages.map(p=>`<li>${safe('第'+p.page+'頁')} · ${safe(p.status)} · ${safe(p.source_type)} · ${safe(p.oldest_date||'?')}～${safe(p.newest_date||'?')}${p.error_code?` · <strong>${safe(p.error_code)}</strong>`:''}${p.http_status?` · HTTP ${Number(p.http_status)}`:''}${p.indexed_at?` · 索引時間 ${safe(fmtStamp(p.indexed_at))}`:''}${p.error?` · ${safe(p.error)}`:''}${officialLink(p.url)?` · <a href="${safe(officialLink(p.url))}" rel="noopener noreferrer" target="_blank">來源 ↗</a>`:''}</li>`).join('')}</ul></details>`:'';
    const attempt=assisted?` · 嘗試 ${Number(l.attempts)||0} 次`:` · 重試 ${Number(l.retries)||0} 次`;
    return `<div class="report-library"><div class="report-lib-head"><strong>${safe(l.name)}</strong><span class="status-badge ${kind==='ok'?'ok':kind==='partial'?'seed':'stale'}">${wording}</span></div>
    <div class="report-lib-stats">${count} · 現有 ${Number(l.active_count)||0} 筆${attempt} · 最近完整核對 ${safe(fmtStamp(l.last_complete_check||l.last_success))} · 最近部分核對 ${safe(fmtStamp(l.last_partial_check))}<br>
    新增書名 ${(c.new||[]).length} · 新刊期 ${(c.new_issue||[]).length} · 恢復 ${(c.returned||[]).length} · 停止列出 ${(c.not_listed||[]).length}</div>
    ${coverageLine}${diagnosticLine}${pagesLine}
    ${l.notes?`<p class="report-muted">核對範圍：${safe(l.notes)}</p>`:''}
    ${l.error?`<p class="report-error">${safe(l.error)}</p>`:''}
    ${changeCount?`<details class="change-details"><summary>展開 ${changeCount} 筆異動書名</summary>${changes}</details>`:`<p class="report-muted">${kind==='stale'?'本次未取得可確認的更新。':kind==='not_checked'?'本次未安排查詢。':'本次無新書目異動（不代表全館沒有更新）。'}</p>`}
    </div>`;
  }).join('');
  history.innerHTML=(report.history||[]).map(r=>`<div class="history-row"><strong>${safe(fmtStamp(r.at))}</strong><span>${safe(r.source==='chatgpt_assisted'?'輔助更新':'爬蟲更新')}：完成 ${r.summary?.successful??0}、部分 ${r.summary?.partial??0}、失敗 ${r.summary?.failed??0}</span><span>新書名 ${r.summary?.new_titles??0} · 新刊期 ${r.summary?.new_issues??0} · 變動 ${r.summary?.changes_total??0}</span></div>`).join('')||'尚無歷史紀錄';
}
async function loadReport() {
  try {
    const response=await fetch('data/update-report.json?ts='+Date.now(),{cache:'no-store'});
    if (!response.ok) throw new Error('HTTP '+response.status);
    const report=await response.json();
    if (!report || !Array.isArray(report.libraries)) throw new Error('更新紀錄格式不符');
    renderReport(report);
  } catch (e) {
    $('update-summary').textContent='目前無法讀取更新紀錄；不影響雜誌搜尋。';
    $('update-libraries').textContent='更新紀錄暫時無法取得。';
    $('update-history').textContent='—';
  }
}
async function load() {
  loadReport();
  notice('正在載入最新雜誌資料…');
  try {
    const response = await fetch('data/catalog.json?ts=' + Date.now(), { cache: 'no-store' });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (!Array.isArray(data.libraries) || !Array.isArray(data.magazines)) throw new Error('JSON 欄位不符');
    state.payload = data;
    renderOptions(); query();
    const flagged = data.libraries.filter(x => x.status === 'stale' || x.status === 'partial');
    notice(flagged.length ? `⚠ ${flagged.length} 館尚未完成近期全面核對（含沿用資料）：${flagged.map(x => x.name).join('、')}` : `✅ 已讀取 ${data.magazines.length} 種雜誌；請查看各館核對狀態`, flagged.length ? 'warning' : '');
  } catch (e) { notice('讀取資料失敗：' + e.message + '。請檢查網站部署或重新整理。', 'error'); }
}
for (const id of ['query', 'library', 'presence', 'freshness', 'sortdir']) $(id).addEventListener('input', query);
$('sortby').addEventListener('change', () => { $('sortdir').value = $('sortby').value === 'title' ? 'asc' : 'desc'; updateSortLabels(); query(); });
$('hideMissing').addEventListener('change', () => { if (state.payload) drawRecords(); });
$('theme').addEventListener('change', e => setTheme(e.target.value));
$('counts').addEventListener('change', query);
$('allcounts').addEventListener('click', () => { document.querySelectorAll('input[name=count]').forEach(x => x.checked = true); query(); });
$('nonecounts').addEventListener('click', () => { document.querySelectorAll('input[name=count]').forEach(x => x.checked = false); query(); });
$('reset').addEventListener('click', () => {
  $('query').value = ''; $('library').value = ''; $('presence').value = 'all'; $('freshness').value = 'all';
  $('sortby').value = 'date'; $('sortdir').value = 'desc'; $('hideMissing').checked = false; updateSortLabels();
  document.querySelectorAll('input[name=count]').forEach(x => x.checked = true); query();
});
$('refresh').addEventListener('click', load);
$('export').addEventListener('click', exportCSV);
$('more').addEventListener('click', () => { state.limit += 30; drawRecords(); });
initTheme();
load();
