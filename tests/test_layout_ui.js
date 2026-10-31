// UI contract regression: compact filters, library cards and optional update audit.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('docs/index.html', 'utf8');
const js = fs.readFileSync('docs/app.js', 'utf8');
const css = fs.readFileSync('docs/styles.css', 'utf8');
const mustHave = ['query','library','presence','freshness','counts','count-selected','sortby','sortdir',
  'hideMissing','theme','refresh','updates','updates-link','update-peek','update-summary',
  'update-changes','update-libraries','update-history','results','matched','export','source-links'];
for(const id of mustHave) assert.equal((html.match(new RegExp('id="'+id+'"','g'))||[]).length, 1, id + ' must occur once');
assert.ok(html.indexOf('class="panel filters"') < html.indexOf('class="panel update-board"'),
  'Search must appear before update history');
assert.ok(html.indexOf('class="panel update-board"') < html.indexOf('aria-label="搜尋結果"'),
  'Updates should be accessible above result cards without dominating the page');
assert.match(html, /<details class="filter-disclosure"/);
assert.match(html, /<details class="panel update-board" id="updates">/);
assert.match(html, /資料範圍與來源/);
assert.doesNotMatch(html, /輔助更新說明/);
assert.match(css, /\.libs\s*\{[^}]*grid-template-columns:repeat\(2/);
assert.match(css, /\.sr-only\s*\{/);
function pick(name) {
  const begin = js.indexOf('function '+name+'(');
  assert.ok(begin>=0, 'Missing '+name);
  const slice = js.slice(begin+1);
  const boundaries = [slice.indexOf('\nfunction '),slice.indexOf('\nasync function ')].filter(x=>x>=0);
  return js.slice(begin, boundaries.length ? begin+1+Math.min(...boundaries) : js.length);
}
const elements = Object.fromEntries(['matched','more','results','hideMissing'].map(id=>[id,{textContent:'',innerHTML:'',hidden:false,checked:false}]));
const payload = { libraries:[
    {id:'tpml', name:'臺北市立圖書館', status:'ok'},
    {id:'tnml', name:'臺南市立圖書館', status:'partial'},
    {id:'ksml', name:'高雄市立圖書館', status:'ok'},
  ]};
const item = {title:'書名 <特殊>', count:2, by:{
  tpml: {date:'2026-11-01',source_url:'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp',magazine_url:'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=123'},
  tnml: {date:'2026-11-02',source_url:'https://tnml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp'}
}};
const safe = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx=vm.createContext({$,safe,URL,state:{payload,records:[item],limit:30}});
function $(id){return elements[id];}
vm.runInContext([pick('officialLink'),pick('drawRecords')].join('\n'),ctx);
ctx.drawRecords();
assert.match(elements.results.innerHTML,/&lt;特殊&gt;/);
assert.match(elements.results.innerHTML,/書目詳情/);
assert.match(elements.results.innerHTML,/2026-11-02 ⚠/);
assert.match(elements.results.innerHTML,/未列出/);
assert.match(elements.matched.textContent,/1 種/);
elements.hideMissing.checked=true;
ctx.drawRecords();
assert.doesNotMatch(elements.results.innerHTML,/未列出/);
assert.match(elements.results.innerHTML,/臺北市立圖書館/);
console.log('Compact UI structure and library cards: passed');
