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
from urllib.parse import urlparse

from .hyread import key
from .update import (
    ROOT, CUTOFF, CONFIG, HISTORY, PUBLIC, REPORT, STATE, STATUS,
    atomic_json, initialize, load, now, published,
)

VALID_STATES = {'complete', 'partial', 'failed'}
CHANGE_TYPES = ('new', 'new_issue', 'returned', 'not_listed')


def _require_date(s: str) -> str:
    if not isinstance(s, str) or len(s) != 10 or date.fromisoformat(s).isoformat() != s:
        raise ValueError(f'無效日期：{s!r}，須為 YYYY-MM-DD')
    return s


def _require_official_url(s: str, library_id: str) -> str:
    if not isinstance(s, str) or not s:
        raise ValueError('每筆確認書目必須附官方來源網址')
    u = urlparse(s)
    if u.scheme != 'https' or u.hostname != f'{library_id}.ebook.hyread.com.tw' or u.username or u.password:
        raise ValueError(f'來源網址與圖書館不符：{s}')
    return s


def validate_batch(batch: dict, conf: list[dict]) -> dict:
    if not isinstance(batch, dict) or batch.get('schema') != 1:
        raise ValueError('輸入資料須為 schema=1 的 JSON 物件')
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
            _require_official_url(row.get('source_url'), libid)
            # Observations may be outside lookback because newer/older issue is
            # visible on a source page. Never invent issue history from them.
            normalized_row={'title':title.strip(),'date':publish_date,'source_url':row['source_url']}
            k=key(title)
            if k not in observed or observed[k]['date'] < publish_date:
                observed[k]=normalized_row
        normalized[libid]={
            'status':status,'attempts':attempts,'retry_wait_seconds':waits,
            'notes':notes,'error':error,'observed':observed,
        }
    return {'batch_id':batch_id,'window_start':started,'window_end':ended,'libraries':normalized}


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
            }
            events.append({'at':stamp,'library':host,'type':'new','title':obs['title'],'to':obs['date']})
            continue
        if obs['date'] > cur['latest_date']:
            events.append({'at':stamp,'library':host,'type':'new_issue','title':cur['title'],
                           'from':cur['latest_date'],'to':obs['date']})
            cur['latest_date']=obs['date']
            cur['source_url']=obs['source_url']
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
            status='not_checked'; events=[]; attempts=0; notes='本次未排入核對'; error=''; reviewed=None; waits=[]
        else:
            status={'complete':'ok','partial':'partial','failed':'stale'}[info['status']]
            events=info['events']; attempts=info['attempts']; notes=info['notes']; error=info['error']
            reviewed=info['verified_count'] if info['status']!='failed' else None
            waits=info['retry_wait_seconds']
        for event in events:
            changes[event['type']].append({k:v for k,v in event.items() if k in ('title','from','to')})
        details.append({
            'id':host,'name':lib['name'],'status':status,'attempted_at':stamp if info else None,
            'last_success':saved.get('last_success'), 'last_assisted_success':saved.get('last_assisted_success'),
            'verified_count':reviewed,'active_count':sum(v['active'] for v in saved['items'].values()),
            'attempts':attempts,'retries':max(attempts-1,0),'retry_wait_seconds':waits,
            'notes':notes,'error':error, 'changes':changes,'change_count':len(events),
        })
    complete=sum(x['status']=='ok' for x in details)
    partial=sum(x['status']=='partial' for x in details)
    failed=sum(x['status']=='stale' for x in details)
    totals={t:sum(len(l['changes'][t]) for l in details) for t in CHANGE_TYPES}
    summary={
        'successful':complete,'partial':partial,'failed':failed,'not_checked':len(details)-complete-partial-failed,
        'total':len(details),'verified_records':sum(l['verified_count'] or 0 for l in details),
        'active_records':sum(l['active_count'] for l in details),
        'new_titles':totals['new'],'new_issues':totals['new_issue'],
        'returned':totals['returned'],'not_listed':0,'changes_total':sum(totals.values()),
    }
    complete_run=complete==len(details)
    line={'at':stamp,'batch_id':batch['batch_id'],'source':'chatgpt_assisted',
          'summary':summary,'complete':complete_run}
    threshold=(datetime.fromisoformat(stamp).date()-timedelta(days=180)).isoformat()
    past=[x for x in (previous or {}).get('history', [])
          if isinstance(x,dict) and x.get('at','')[:10]>=threshold and x.get('batch_id')!=batch['batch_id']]
    return {'schema':1,'type':'chatgpt_assisted','batch_id':batch['batch_id'],
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
        if status=='failed':
            # No mutation to existing books or previous good verification stamp.
            saved.update({'result':'stale','error':entry['error']})
            events=[]
        else:
            events=merge_incremental(state,libmap[host],entry['observed'],stamp)
            saved.update({'result':'partial','error':entry['notes'] if status=='partial' else '',
                          'last_assisted_success':stamp})
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
