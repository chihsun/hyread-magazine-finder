"""Import source-verified, ChatGPT-assisted incremental HyRead observations.

This module makes NO requests to HyRead. It receives an explicitly reviewed
observation file from a human-assisted research session. 'complete' means all
sources in the stated lookback WINDOW were checked, not the entire catalog.
A missing observation MUST NEVER remove or deactivate a known magazine.

Usage: python -m src.assisted_update input.json --dry-run
       python -m src.assisted_update input.json --apply
"""
from __future__ import annotations
import argparse
import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .hyread import key
from .coverage import official_url, magazine_url, validate_coverage
from .scan_evidence import error_code as check_error_code
from .update import (
    ROOT, CUTOFF, CONFIG, HISTORY, PUBLIC, REPORT, STATE, STATUS,
    atomic_json, initialize, load, now, published,
)

VALID_STATES = {'complete', 'partial', 'failed'}
CHANGE_TYPES = ('new', 'new_issue', 'returned', 'not_listed', 'link_added', 'link_changed')


def _require_date(s: str) -> str:
    if not isinstance(s, str) or len(s) != 10 or date.fromisoformat(s).isoformat() != s:
        raise ValueError(f'無效日期：{s!r}，須為 YYYY-MM-DD')
    return s


def verified_title_link(evidence: dict | None, title: str, url: str | None,
                        source_url: str, library_id: str) -> dict | None:
    """Accept a jid only when its original title anchor proves the association.

    Schema 4 uses this during every ChatGPT-assisted update; previous batch
    schemas remain importable for historical reproducibility. These are
    observations supplied by the user-visible source inspection, NOT guessed
    identifiers derived from a title or copied from another library.
    """
    if url is None:
        if evidence is not None:
            raise ValueError(f'{library_id}: 無書目網址不可提供 link_evidence')
        return None
    if not isinstance(evidence, dict):
        raise ValueError(f'{library_id}: 書目連結必須附上來源書名錨點 link_evidence')
    if set(evidence) != {'anchor_text','href','source_url'}:
        raise ValueError(f'{library_id}: link_evidence 須有 anchor_text、href、source_url')
    label=evidence.get('anchor_text')
    if not isinstance(label,str) or not label.strip() or key(label)!=key(title):
        raise ValueError(f'{library_id}: 書目網址的錨點文字與雜誌書名不一致')
    actual=magazine_url(evidence.get('href'),library_id)
    if actual != url:
        raise ValueError(f'{library_id}: 書目網址與錨點實際 href 不一致')
    origin=official_url(evidence.get('source_url'),library_id)
    normalized=lambda x: x+'?nowpage=1' if x.endswith('/magazine_view_more.jsp') else x
    if normalized(origin)!=normalized(source_url):
        raise ValueError(f'{library_id}: 來源錨點頁面與書目來源頁不一致')
    return {'anchor_text':label.strip(),'href':actual,'source_url':origin}


def first_book_checkpoint(data: dict, libid: str, coverage: dict, *, require_proof: bool = False) -> dict:
    """Save only the first title actually seen on page 1, never an inferred jid."""
    if not isinstance(data, dict):
        raise ValueError(f'{libid}: 正常／部分讀取需要最新出刊第 1 頁的 first_book')
    title=data.get('title')
    if not isinstance(title, str) or not title.strip() or len(title)>180:
        raise ValueError(f'{libid}: first_book 缺少有效書名')
    issue=_require_date(data.get('date'))
    url=magazine_url(data.get('magazine_url'),libid)
    jid=parse_qs(urlparse(url).query)['jid'][0] if url else None
    if data.get('jid') not in (None, jid):
        raise ValueError(f'{libid}: first_book jid 與實際書目網址不一致')
    source=official_url(data.get('source_url'),libid)
    first=next((p for p in coverage['pages'] if p['page']==1 and p['status']=='ok'),None)
    if not first or issue!=first['newest_date']:
        raise ValueError(f'{libid}: first_book 日期必須符合第 1 頁第一筆日期')
    canonical=source + '?nowpage=1' if source.endswith('/magazine_view_more.jsp') else source
    if source!=first['url'] and canonical!=first['url']:
        raise ValueError(f'{libid}: first_book 必須來自本次第 1 頁')
    if require_proof:
        verified_title_link(data.get('link_evidence'),title,url,source,libid)
    return {'title':title.strip(),'date':issue,
            'jid':jid,'magazine_url':url,'source_url':first['url']}


def older_observations(saved: dict, entry: dict) -> list[str]:
    """V1.6: detect stale page-1 head and titles older than stored issues."""
    problems=[]
    anchor=saved.get('latest_page_anchor')
    known=[x.get('latest_date') for x in saved.get('items',{}).values() if x.get('latest_date')]
    baseline=anchor.get('date') if isinstance(anchor,dict) and anchor.get('date') else max(known,default=None)
    first=entry.get('first_book')
    if first and baseline and first['date']<baseline:
        problems.append(f"第一頁最新刊期 {first['date']} 早於既有紀錄 {baseline}")
    for k,obs in entry['observed'].items():
        prev=saved.get('items',{}).get(k)
        if prev and obs['date']<prev['latest_date']:
            problems.append(f"{obs['title']}：讀到 {obs['date']}，已存 {prev['latest_date']}")
    return problems


def validate_batch(batch: dict, conf: list[dict]) -> dict:
    if not isinstance(batch, dict) or batch.get('schema') not in (1, 2, 3, 4):
        raise ValueError('輸入資料須為 schema=1、2、3 或 4 的 JSON 物件')
    strict = batch['schema'] == 2
    simple = batch['schema'] in (3, 4)
    require_link_evidence = batch['schema'] == 4
    if batch.get('source') != 'chatgpt_assisted':
        raise ValueError('source 必須是 chatgpt_assisted')
    batch_id = batch.get('batch_id')
    if not isinstance(batch_id, str) or not 6 <= len(batch_id) <= 96 or not all(c.isalnum() or c in '-_.' for c in batch_id):
        raise ValueError('batch_id 必須是 6–96 字元的英數、-、_ 或 .（避免重複匯入）')
    started = _require_date(batch.get('window_start'))
    ended = _require_date(batch.get('window_end'))
    if started > ended:
        raise ValueError('window_start 不得晚於 window_end')
    if (date.fromisoformat(ended) - date.fromisoformat(started)).days > 366:
        raise ValueError('單次查詢期間不可超過 366 天')
    records = batch.get('libraries')
    if not isinstance(records, list) or not records:
        raise ValueError('libraries 不可為空')
    known = {l['id'] for l in conf}
    seen = set()
    normalized = {}
    for entry in records:
        if not isinstance(entry, dict) or entry.get('id') not in known or entry['id'] in seen:
            raise ValueError('館別必須有效且不能重複')
        libid = entry['id']; seen.add(libid)
        status = entry.get('status')
        if status not in VALID_STATES:
            raise ValueError(f'{libid}: status 必須是 complete/partial/failed')
        attempts = entry.get('attempts')
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise ValueError(f'{libid}: 嘗試次數只能 1、2 或 3（最多額外重試兩次）')
        waits = entry.get('retry_wait_seconds', [])
        if not isinstance(waits, list) or len(waits) != attempts-1 or any(type(x) not in (int, float) or not 0 < x <= 60 for x in waits):
            raise ValueError(f'{libid}: retry_wait_seconds 須對應每次重試的實際等待秒數')
        notes = entry.get('notes', '')
        if not isinstance(notes, str) or len(notes) > 600:
            raise ValueError(f'{libid}: notes 太長或不是字串')
        error = entry.get('error', '')
        if not isinstance(error, str) or len(error) > 600:
            raise ValueError(f'{libid}: error 太長或不是字串')
        diagnostic_code = check_error_code(entry.get('error_code'))
        if (strict or simple) and status == 'failed' and not diagnostic_code:
            raise ValueError(f'{libid}: schema=2 的失敗館必須記錄 error_code')
        rows = entry.get('records', [])
        if not isinstance(rows, list):
            raise ValueError(f'{libid}: records 必須為陣列')
        if status == 'failed' and (rows or not error):
            raise ValueError(f'{libid}: 失敗館不能提交書目，而且必須記錄錯誤')
        if status == 'complete' and not notes:
            raise ValueError(f'{libid}: complete 需要描述已核對哪些來源與範圍')
        if status == 'partial' and not notes:
            raise ValueError(f'{libid}: partial 需要說明尚缺的頁面或類別')
        observed={}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('書目記錄應為物件')
            title = row.get('title')
            if not isinstance(title, str) or not title.strip() or len(title) > 180:
                raise ValueError(f'{libid}: 無效書名')
            publish_date = _require_date(row.get('date'))
            official_url(row.get('source_url'), libid)
            # Observations may be outside lookback because newer/older issue is
            # visible on a source page. Never invent issue history from them.
            detail=magazine_url(row.get('magazine_url'),libid)
            proof=(verified_title_link(row.get('link_evidence'),title.strip(),detail,
                                       row['source_url'],libid)
                   if require_link_evidence else None)
            normalized_row={'title':title.strip(),'date':publish_date,'source_url':row['source_url'],
                            'magazine_url':detail}
            if proof is not None:
                normalized_row['link_evidence']=proof
            k=key(title)
            if (k not in observed or observed[k]['date'] < publish_date
                    or (observed[k]['date']==publish_date and not observed[k]['magazine_url'] and normalized_row['magazine_url'])):
                observed[k]=normalized_row
        coverage=validate_coverage(entry.get('coverage'),libid,started,
                                   status=='complete',strict=strict,simple=simple)
        first_book=None
        if simple:
            if status!='failed':
                if coverage['method']!='latest_pages' or not coverage.get('first_page_ok'):
                    raise ValueError(f'{libid}: 第一頁未正常讀取應標為 failed')
                first_book=first_book_checkpoint(coverage.get('first_book'),libid,coverage,
                                                require_proof=require_link_evidence)
                successful_urls={p['url'] for p in coverage['pages'] if p['status']=='ok'}
                for item in observed.values():
                    source=item['source_url']
                    canonical=source+'?nowpage=1' if source.endswith('/magazine_view_more.jsp') else source
                    if source not in successful_urls and canonical not in successful_urls:
                        raise ValueError(f'{libid}: 書目來源不在本次已讀取的最新出刊分頁中')
            elif coverage.get('first_page_ok'):
                raise ValueError(f'{libid}: 第一頁已成功但標示 failed，應改為 partial')
        if strict and status == 'complete' and coverage['method'] == 'latest_pages':
            # All accepted observations must originate in one of the actual,
            # verified direct pages (query-less page 1 is the same as nowpage=1).
            verified_urls = {p['url'] for p in coverage['pages'] if
                             p['status'] == 'ok' and p['source_type'] == 'direct'}
            for observed_row in observed.values():
                source = observed_row['source_url']
                if source not in verified_urls and not (
                    source.endswith('/magazine_view_more.jsp') and
                    source + '?nowpage=1' in verified_urls
                ):
                    raise ValueError(f'{libid}: 完整核對的書目來源不在本次直接取得的分頁中')
        normalized[libid]={
            'coverage':coverage,'status':status,'attempts':attempts,'retry_wait_seconds':waits,
            'notes':notes,'error':error,'error_code':diagnostic_code,'observed':observed,
            'first_book':first_book,'simple':simple,
            'link_evidence_required':require_link_evidence,
        }
    return {'schema':batch['schema'],'batch_id':batch_id,'window_start':started,'window_end':ended,'libraries':normalized}


def merge_incremental(state: dict, library: dict, observations: dict, stamp: str) -> list[dict]:
    """Positive observations only: never increase misses or remove entries."""
    host=library['id']; row=state['libraries'][host]; items=row['items']
    events=[]
    for k, obs in observations.items():
        # Preserve original project cutoff for newly indexed magazines.
        if obs['date'] < state.get('start_date', CUTOFF):
            continue
        cur=items.get(k)
        if cur is None:
            items[k]={
                'title':obs['title'],'latest_date':obs['date'],
                'source_url':obs['source_url'],'first_seen':stamp[:10],
                'last_seen':stamp[:10],'misses':0,'active':True,
                'magazine_url':obs.get('magazine_url'),
            }
            if obs.get('link_evidence'):
                items[k]['magazine_url_checked_at']=stamp
                items[k]['magazine_url_verified_by']='source_title_anchor'
            events.append({'at':stamp,'library':host,'type':'new','title':obs['title'],'to':obs['date']})
            continue
        if obs['date'] > cur['latest_date']:
            events.append({'at':stamp,'library':host,'type':'new_issue','title':cur['title'],
                           'from':cur['latest_date'],'to':obs['date']})
            cur['latest_date']=obs['date']
            cur['source_url']=obs['source_url']
        # Metadata link is independent of the newest issue date: an older
        # source can validly supply the permanent magazine detail page.
        old_link=cur.get('magazine_url')
        new_link=obs.get('magazine_url')
        if new_link and new_link != old_link:
            # Schema 4 observations have a matching title anchor on the
            # corresponding scanned page. A corrected link replaces a
            # previously wrong jid even when the issue date is unchanged.
            cur['magazine_url']=new_link
            cur['magazine_url_checked_at']=stamp
            if obs.get('link_evidence'):
                cur['magazine_url_verified_by']='source_title_anchor'
            events.append({'at':stamp,'library':host,'type':'link_changed' if old_link else 'link_added',
                           'title':cur['title'],'from':old_link or '', 'to':new_link})
        elif new_link and obs.get('link_evidence'):
            # Reconfirmed link, not a new book/issue change.
            cur['magazine_url_checked_at']=stamp
            cur['magazine_url_verified_by']='source_title_anchor'
        if not cur['active']:
            events.append({'at':stamp,'library':host,'type':'returned','title':cur['title'],'to':cur['latest_date']})
            cur['active']=True
            cur['misses']=0
        cur['last_seen']=stamp[:10]
    return events


def build_assisted_report(conf, state, stamp, batch, results, previous):
    details=[]
    for lib in conf:
        host=lib['id']; info=results.get(host)
        saved=state['libraries'][host]
        changes={t:[] for t in CHANGE_TYPES}
        if info is None:
            status='not_checked'; events=[]; attempts=0; notes='本次未排入核對'; error=''; diagnostic_code=None; reviewed=None; waits=[]; coverage={'method':'unknown','pages':[],'checked_pages':0,'failed_pages':0,'date_boundary_reached':False}
        else:
            status={'complete':'ok','partial':'partial','failed':'stale'}[info['status']]
            events=info['events']; attempts=info['attempts']; notes=info['notes']; error=info['error']
            reviewed=info['verified_count'] if info['status']!='failed' else None
            waits=info['retry_wait_seconds']; coverage=info['coverage']; diagnostic_code=info.get('error_code')
        for event in events:
            changes[event['type']].append({k:v for k,v in event.items() if k in ('title','from','to')})
        details.append({
            'id':host,'name':lib['name'],'status':status,'attempted_at':stamp if info else None,
            'last_success':saved.get('last_success'), 'last_assisted_success':saved.get('last_assisted_success'),
            'last_complete_check':saved.get('last_complete_check'), 'last_partial_check':saved.get('last_partial_check'),
            'verified_count':reviewed,'active_count':sum(v['active'] for v in saved['items'].values()),
            'attempts':attempts,'retries':max(attempts-1,0),'retry_wait_seconds':waits,
            'notes':notes,'error':error,'error_code':diagnostic_code,'coverage':coverage,
            'first_book':info.get('first_book') if info else None,
            'saved_first_book':saved.get('latest_page_anchor'),
            'stale_observations':info.get('stale_observations',[]) if info else [],
            'changes':changes,'change_count':len(events),
        })
    complete=sum(x['status']=='ok' for x in details)
    partial=sum(x['status']=='partial' for x in details)
    failed=sum(x['status']=='stale' for x in details)
    totals={t:sum(len(l['changes'][t]) for l in details) for t in CHANGE_TYPES}
    codes={}
    for x in details:
        if x.get('error_code'):
            codes[x['error_code']]=codes.get(x['error_code'],0)+1
    summary={
        'error_code_counts':codes,
        'cached_pages':sum(l['coverage'].get('diagnostics',{}).get('source_types',{}).get('search_index',0) for l in details),
        'successful':complete,'partial':partial,'failed':failed,'not_checked':len(details)-complete-partial-failed,
        'total':len(details),'verified_records':sum(l['verified_count'] or 0 for l in details),
        'active_records':sum(l['active_count'] for l in details),
        'new_titles':totals['new'],'new_issues':totals['new_issue'],
        'returned':totals['returned'],'not_listed':0,
        'links_added':totals['link_added'],'links_changed':totals['link_changed'],
        'pages_checked':sum(l['coverage'].get('checked_pages',0) for l in details),
        'pages_failed':sum(l['coverage'].get('failed_pages',0) for l in details),
        'changes_total':sum(totals.values()),
    }
    complete_run=complete==len(details)
    line={'at':stamp,'batch_id':batch['batch_id'],'source':'chatgpt_assisted',
          'summary':summary,'complete':complete_run}
    threshold=(datetime.fromisoformat(stamp).date()-timedelta(days=180)).isoformat()
    past=[x for x in (previous or {}).get('history', [])
          if isinstance(x,dict) and x.get('at','')[:10]>=threshold and x.get('batch_id')!=batch['batch_id']]
    return {'schema':1,'batch_schema':batch.get('schema',1),
            'type':'chatgpt_assisted','batch_id':batch['batch_id'],
            'generated_at':stamp,'window_start':batch['window_start'],'window_end':batch['window_end'],
            'complete':complete_run,'summary':summary,'libraries':details,
            'history':([line]+past)[:40]}


def apply_batch(batch: dict, *, persist: bool=False, stamp: str|None=None) -> dict:
    conf, original=initialize()
    validated=validate_batch(batch, conf)
    previous=load(REPORT,{})
    if previous.get('batch_id')==validated['batch_id'] or any(x.get('batch_id')==validated['batch_id'] for x in previous.get('history',[])):
        raise ValueError(f'批次 {validated["batch_id"]} 已匯入，拒絕重複執行')
    state=copy.deepcopy(original)
    history=load(HISTORY, {'version':1,'events':[]})
    stamp=stamp or now()
    datetime.fromisoformat(stamp)
    results={}
    libmap={l['id']:l for l in conf}
    for host, entry in validated['libraries'].items():
        saved=state['libraries'][host]
        saved['last_attempt']=stamp
        saved['retry_count']=entry['attempts']-1
        status=entry['status']
        if entry.get('simple') and status!='failed':
            stale=older_observations(saved,entry)
            if stale:
                # ChatGPT should first retry the offending page twice.
                # A batch with exhausted attempts is still allowed to merge
                # *newer* observations safely, but is never 'complete'.
                if entry['attempts']<3:
                    raise ValueError(f'{host}: 讀到比原資料舊的刊期，需重試最多兩次後以 partial 提交')
                status='partial'
                entry['status']='partial'
                entry['error_code']='STALE_CACHE'
                entry['stale_observations']=stale
                summary='；'.join(stale[:5])
                entry['notes']=(entry['notes']+'；舊刊期警示：'+summary)[:600]
                entry['error']=('重試後仍讀到舊刊期；'+summary)[:600]
        if status=='failed':
            # No mutation to existing books or previous good verification stamp.
            saved.update({'result':'stale','error':entry['error']})
            events=[]
        else:
            events=merge_incremental(state,libmap[host],entry['observed'],stamp)
            saved.update({'result':'ok' if status=='complete' else 'partial',
                          'error':entry['notes'] if status=='partial' else '',
                          'last_assisted_success':stamp})
            if status=='complete':
                saved['last_complete_check']=stamp
                if entry.get('simple') and entry.get('first_book'):
                    saved['latest_page_anchor']={**entry['first_book'],'checked_at':stamp}
            else:
                saved['last_partial_check']=stamp
            history['events'].extend(events)
        results[host]={**entry,'events':events,'verified_count':len(entry['observed'])}
    threshold=(datetime.fromisoformat(stamp).date()-timedelta(days=180)).isoformat()
    history['events']=[x for x in history['events'] if x.get('at','')[:10]>=threshold]
    catalog=published(state,conf,stamp)
    report=build_assisted_report(conf,state,stamp,validated,results,previous)
    status={
        'generated_at':stamp,'source':'chatgpt_assisted','results':catalog['libraries'],
        'complete':report['complete'],'successful':report['summary']['successful'],
        'partial':report['summary']['partial'],'failed':report['summary']['failed'],
        'total':len(conf),'note':'增量核對：未找到的書目均保留，不代表完整館藏下架。',
    }
    if persist:
        atomic_json(STATE,state)
        atomic_json(HISTORY,history)
        atomic_json(PUBLIC,catalog)
        atomic_json(REPORT,report)
        atomic_json(STATUS,status)
    return report


def main():
    parser=argparse.ArgumentParser(description='Merge verified ChatGPT-assisted observations; never scrape or remove missing titles')
    parser.add_argument('input',type=Path,help='Verified JSON batch file')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    batch=json.loads(args.input.read_text('utf-8'))
    result=apply_batch(batch,persist=args.apply)
    print(json.dumps({'mode':'apply' if args.apply else 'dry-run','batch_id':result['batch_id'],
                      'summary':result['summary'],'libraries':[{'name':l['name'],'status':l['status'],
                      'verified':l['verified_count'],'changes':l['change_count']} for l in result['libraries']]},
                     ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
