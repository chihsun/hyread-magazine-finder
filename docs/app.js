'use strict';
const $=id=>document.getElementById(id);
const state={payload:null,records:[],libMap:{},limit:30};
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(s,type=''){const e=$('alert');e.textContent=s;e.className='alert '+type;}
function countLabel(n){return n===9?'九館都有':n===1?'只有一館有':`${['','一','兩','三','四','五','六','七','八','九'][n]}館有`;}
function renderOptions(){
 const p=state.payload;
 $('libtotal').textContent=p.libraries.length;
 $('total').textContent=p.magazines.length;
 $('common').textContent=p.distribution[String(p.libraries.length)]||0;
 $('updated').textContent=p.generated_at?.slice(0,16).replace('T',' ')||'—';
 $('library').innerHTML='<option value="">全部圖書館</option>'+p.libraries.map(x=>`<option value="${safe(x.id)}">${safe(x.name)}</option>`).join('');
 $('counts').innerHTML=Array.from({length:p.libraries.length},(_,i)=>p.libraries.length-i).map(n=>`<label class="pill"><input type="checkbox" name="count" value="${n}" checked><span>${countLabel(n)}</span><em>${p.distribution[String(n)]||0} 種</em></label>`).join('');
 $('source-links').innerHTML=p.libraries.map(x=>`<a href="https://${encodeURIComponent(x.id)}.ebook.hyread.com.tw/Template/RWD3.0/magazine.jsp" target="_blank" rel="noopener noreferrer">${safe(x.name)} ↗</a>`).join('');
}
function recentMatch(row,value,lib){
 if(value==='all')return true;
 const dates=lib ? (row.by[lib]?[row.by[lib].date]:[]) : Object.values(row.by).map(x=>x.date);
 if(!dates.length)return false;
 const latest=dates.sort().at(-1);
 const today=new Date(); today.setHours(0,0,0,0);
 const ago=Math.floor((today-new Date(`${latest}T00:00:00`))/86400000);
 if(value==='old')return ago>180;
 return ago>=0&&ago<=Number(value); // exclude future preview dates from 'recent' filters
}
function query(){
 const p=state.payload;if(!p)return;
 const wanted=new Set([...document.querySelectorAll('input[name=count]:checked')].map(x=>Number(x.value)));
 const needle=$('query').value.trim().toLocaleLowerCase(),selected=$('library').value,presence=$('presence').value,fresh=$('freshness').value;
 state.records=p.magazines.filter(r=>wanted.has(r.count)&&r.title.toLocaleLowerCase().includes(needle)&&(
   !selected||presence==='all'||(presence==='yes'?Boolean(r.by[selected]):!r.by[selected])
 )&&recentMatch(r,fresh,selected));
 state.limit=30;drawRecords();
}
function drawRecords(){
 const p=state.payload;
 $('matched').textContent=`符合條件 ${state.records.length} 種雜誌`;
 $('more').hidden=state.records.length<=state.limit;
 $('more').textContent=`顯示更多（已顯示 ${Math.min(state.limit,state.records.length)} / ${state.records.length} 種）`;
 if(state.records.length===0){$('results').innerHTML='<div class="empty">沒有符合條件的雜誌。可調整館數勾選或清除搜尋字詞。</div>';return;}
 $('results').innerHTML=state.records.slice(0,state.limit).map(r=>`<article class="item"><div class="item-top"><h3>${safe(r.title)}</h3><span class="count-chip">${r.count} / ${p.libraries.length} 館</span></div><div class="libs">${p.libraries.map(l=>{
 const v=r.by[l.id];const stale=l.status==='stale';
 return `<div class="lib-row"><span>${safe(l.name)}</span>${v?`<a class="${stale?'stale':''}" href="${safe(v.source_url)}" target="_blank" rel="noopener noreferrer" title="${stale?'本館本次更新失敗，沿用上次核對資料':'官方來源'}">✓ ${safe(v.date)} ${stale?'⚠':''} ↗</a>`:'<span class="missing">— 未列出</span>'}</div>`;
 }).join('')}</div></article>`).join('');
}
function exportCSV(){
 const p=state.payload;if(!p)return;
 const rows=[['雜誌名稱','收錄館數',...p.libraries.map(x=>x.name)],...state.records.map(r=>[r.title,r.count,...p.libraries.map(x=>r.by[x.id]?.date||'未列出')])];
 const csv='\ufeff'+rows.map(r=>r.map(v=>{
   let x=String(v??''); if(/^[=+@\-\t\r]/.test(x))x="'"+x;
   return '"'+x.replace(/"/g,'""')+'"';
 }).join(',')).join('\r\n');
 const u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
 const a=document.createElement('a');a.href=u;a.download='HyRead_九館雜誌_篩選結果.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),3000);
}
async function load(){
 notice('正在載入最新雜誌資料…');
 try{
  const response=await fetch('data/catalog.json?ts='+Date.now(),{cache:'no-store'});
  if(!response.ok)throw new Error('HTTP '+response.status);
  const data=await response.json();
  if(!Array.isArray(data.libraries)||!Array.isArray(data.magazines))throw new Error('JSON 欄位不符');
  state.payload=data;state.libMap=Object.fromEntries(data.libraries.map(x=>[x.id,x]));
  renderOptions();query();
  const bad=data.libraries.filter(x=>x.status==='stale');
  notice(bad.length?`⚠ ${bad.length} 間圖書館本次擷取失敗，沿用最後成功資料：${bad.map(x=>x.name).join('、')}`:`✅ 已讀取 ${data.magazines.length} 種雜誌；九館資料可搜尋`,bad.length?'warning':'');
 }catch(e){notice('讀取資料失敗：'+e.message+'。請檢查網站部署或重新整理。','error');}
}
for(const id of ['query','library','presence','freshness']) $(id).addEventListener('input',query);
$('counts').addEventListener('change',query);
$('allcounts').addEventListener('click',()=>{document.querySelectorAll('input[name=count]').forEach(x=>x.checked=true);query()});
$('nonecounts').addEventListener('click',()=>{document.querySelectorAll('input[name=count]').forEach(x=>x.checked=false);query()});
$('reset').addEventListener('click',()=>{ $('query').value='';$('library').value='';$('presence').value='all';$('freshness').value='all';document.querySelectorAll('input[name=count]').forEach(x=>x.checked=true);query()});
$('refresh').addEventListener('click',load);
$('export').addEventListener('click',exportCSV);
$('more').addEventListener('click',()=>{state.limit+=30;drawRecords()});
load();
