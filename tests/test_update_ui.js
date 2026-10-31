// Regression tests for book-name and issue-date change lists on GitHub Pages.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const page = fs.readFileSync('docs/index.html', 'utf8');
const script = fs.readFileSync('docs/app.js', 'utf8');
assert.match(page, /id="update-changes"/);
assert.doesNotMatch(page, /輔助更新說明/);
function pick(name) {
  const start = script.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'Missing ' + name);
  const after = script.slice(start + 1);
  const offsets = [after.indexOf('\nfunction '), after.indexOf('\nasync function ')].filter(x => x >= 0);
  const end = offsets.length ? start + 1 + Math.min(...offsets) : script.length;
  return script.slice(start, end);
}
const safe = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx = vm.createContext({ safe, collator: new Intl.Collator('zh-Hant-TW', {numeric:true}) });
vm.runInContext(['titleChangeGroups','renderTitleChanges'].map(pick).join('\n'),ctx);
const entries = [
  {type:'new',title:'新書 A',library:'臺北',to:'2026-11-05'},
  {type:'new',title:'新書 A',library:'臺南',to:'2026-11-05'},
  {type:'new_issue',title:'商業周刊',library:'臺北',from:'2026-10-01',to:'2026-11-01'},
  {type:'new_issue',title:'商業周刊',library:'臺南',from:'2026-10-01',to:'2026-11-01'},
  {type:'link_added',title:'只補連結',library:'臺北'},
  {type:'new',title:'<script>alert(1)</script>',library:'臺北',to:'2026-11-01'},
];
const html = ctx.renderTitleChanges(entries);
assert.match(html, /新增書名 · 2 種書名／3 筆館別異動/);
assert.match(html, /刊期更新 · 1 種書名／2 筆館別異動/);
assert.match(html, /2026-10-01 → 2026-11-01/);
assert.doesNotMatch(html, /只補連結/);
assert.doesNotMatch(html, /<script>/);
assert.match(html, /&lt;script&gt;/);
const report = JSON.parse(fs.readFileSync('docs/data/update-report.json', 'utf8'));
for (const row of report.history || []) {
  const details = row.title_changes || [];
  const expected = (Number(row.summary?.new_titles)||0)+(Number(row.summary?.new_issues)||0);
  assert.equal(details.length, expected, 'history title list mismatch: ' + row.at);
}
console.log('Update title change list: passed');
