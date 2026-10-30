"""Atomic nine-library update. Example: python -m src.update --once

Only commit trustworthy complete-library scans. Preserve latest observation per
magazine per library. Store 180d change history and a lightweight site snapshot.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
from datetime import datetime,date,timedelta,timezone
import json
import os
from pathlib import Path
import sys

from .hyread import LibraryScanner,key

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'config/libraries.json'
STATE=ROOT/'data/state.json'
HISTORY=ROOT/'data/history.json'
PUBLIC=ROOT/'docs/data/catalog.json'
STATUS=ROOT/'docs/data/status.json'
REPORT=ROOT/'docs/data/update-report.json'
CUTOFF='2026-09-20'
MIN_ACTIVE=30
TZ=timezone(timedelta(hours=8))


def load(path,default):
    return json.loads(path.read_text('utf-8')) if path.exists() else copy.deepcopy(default)


def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    os.replace(temp,path)


def now():
    return datetime.now(TZ).isoformat(timespec='seconds')


def make_seed(snapshot,config):
    result={'version':1,'start_date':CUTOFF,'libraries':{}}
    for lib in config:
        name=lib['name']; host=lib['id']
        prev=snapshot['libraries'].get(name,[])
        items={}
        for r in prev:
            k=key(r['title'])
            items[k]={
                'title':r['title'],'latest_date':r['date'],
                'source_url':r.get('source_page') or r.get('url') or '',
                'magazine_url':r.get('magazine_url'),
                'first_seen':'2026-10-30','last_seen':'2026-10-30',
                'misses':0,'active':True,
            }
        result['libraries'][host]={
            'name':name,'items':items,'last_success':'2026-10-30',
            'last_attempt':'2026-10-30','result':'seed','error':'',
            'retry_count':0,'verified_count':len(items),
        }
    return result


def initialize():
    conf=load(CONFIG,[])
    state=load(STATE,None)
    if state is None:
        state=make_seed(load(ROOT/'data/initial-snapshot.json',{}),conf)
    return conf,state


def ingest(state,lib,observed,when,cutoff=CUTOFF):
    """Update one library ONLY after its entire scan succeeded; no partial commits."""
    row=state['libraries'][lib['id']]
    all_items=row['items']
    before=sum(1 for v in all_items.values() if v['active'])
    qualifying={k:r for k,r in observed.items() if r['date']>=cutoff}
    if len(qualifying)<MIN_ACTIVE or (before>=MIN_ACTIVE and len(qualifying)<before*.55):
        raise ValueError(f'完整性保護：本次{len(qualifying)}筆，過去{before}筆；拒絕覆蓋')
    events=[]
    for k,r in qualifying.items():
        cur=all_items.get(k)
        if cur is None:
            all_items[k]={
                'title':r['title'],'latest_date':r['date'],'source_url':r['source_url'],
                'first_seen':when[:10],'last_seen':when[:10],'misses':0,'active':True,
                'magazine_url':r.get('magazine_url'),
            }
            events.append({'at':when,'library':lib['id'],'type':'new','title':r['title'],'to':r['date']})
        else:
            # Never regress latest issue due to stale cache / website delay.
            if r['date']>cur['latest_date']:
                events.append({'at':when,'library':lib['id'],'type':'new_issue',
                               'title':cur['title'],'from':cur['latest_date'],'to':r['date']})
                cur['latest_date']=r['date']
            if r.get('magazine_url'):
                cur['magazine_url']=r['magazine_url']
            if not cur['active']:
                events.append({'at':when,'library':lib['id'],'type':'returned','title':cur['title'],'to':cur['latest_date']})
            cur.update({'source_url':r['source_url'],'last_seen':when[:10],'misses':0,'active':True})
    for k,v in all_items.items():
        if k in qualifying or not v['active']:continue
        v['misses']=v.get('misses',0)+1
        if v['misses']>=3:
            v['active']=False
            events.append({'at':when,'library':lib['id'],'type':'not_listed','title':v['title'],'from':v['latest_date']})
    row.update({'last_success':when,'last_attempt':when,'result':'ok','error':'',
                'verified_count':len(qualifying)})
    return events


def published(state,conf,stamp):
    names={x['id']:x['name'] for x in conf}
    series={}
    statuses=[]
    for l in conf:
        lib=state['libraries'][l['id']]
        statuses.append({
            'id':l['id'],'name':l['name'],'status':lib['result'],
            'last_success':lib.get('last_success'),'last_attempt':lib.get('last_attempt'),
            'count':sum(1 for v in lib['items'].values() if v['active']),
            'error':lib.get('error',''), 'retries':lib.get('retry_count',0),
        })
        for k,r in lib['items'].items():
            if not r['active']:continue
            if k not in series: series[k]={'title':r['title'],'key':k,'by':{}}
            series[k]['by'][l['id']]={'date':r['latest_date'],'source_url':r['source_url'],
                                      'magazine_url':r.get('magazine_url')}
    matrix=list(series.values())
    for r in matrix:r['count']=len(r['by'])
    matrix.sort(key=lambda r:(-r['count'],r['key']))
    return {'schema':1,'generated_at':stamp,'start_date':state['start_date'],
            'libraries':statuses,'magazines':matrix,
            'distribution':{str(i):sum(r['count']==i for r in matrix) for i in range(1,len(conf)+1)}}


def build_report(conf, state, stamp, per_library, previous=None):
    """Summarize actual changes in this crawl; never infer additions from counts."""
    details=[]
    for lib in conf:
        item=state['libraries'][lib['id']]
        outcome=per_library[lib['id']]
        changes={t:[] for t in ('new','new_issue','returned','not_listed')}
        for event in outcome['events']:
            changes[event['type']].append({k:v for k,v in event.items() if k in ('title','from','to')})
        details.append({
            'id':lib['id'], 'name':lib['name'],
            'status':'ok' if outcome['ok'] else 'stale',
            'attempted_at':stamp, 'last_success':item.get('last_success'),
            # Never reuse a prior successful scan's verified count on a failed run.
            'verified_count':outcome['verified_count'] if outcome['ok'] else None,
            'active_count':sum(v['active'] for v in item['items'].values()),
            'retries':item.get('retry_count',0),
            'error':item.get('error','') if not outcome['ok'] else '',
            'changes':changes,
            'change_count':len(outcome['events']),
        })
    successful=sum(v['status']=='ok' for v in details)
    totals={name:sum(len(v['changes'][name]) for v in details) for name in ('new','new_issue','returned','not_listed')}
    summary={
        'successful':successful,'failed':len(details)-successful,'total':len(details),
        'verified_records':sum(v['verified_count'] or 0 for v in details),
        'active_records':sum(v['active_count'] for v in details),
        'new_titles':totals['new'],'new_issues':totals['new_issue'],
        'returned':totals['returned'],'not_listed':totals['not_listed'],
        'changes_total':sum(totals.values()),
    }
    # Retain compact summaries for 180d; only the latest run contains book titles.
    item={'at':stamp,'summary':summary,'complete':successful==len(details)}
    previous_history=(previous or {}).get('history',[])
    threshold=(datetime.fromisoformat(stamp).date()-timedelta(days=180)).isoformat()
    past=[r for r in previous_history if isinstance(r,dict) and r.get('at','')[:10]>=threshold and r.get('at')!=stamp]
    return {'schema':1,'type':'crawl','generated_at':stamp,
            'complete':item['complete'],'summary':summary,
            'libraries':details,'history':([item]+past)[:40]}


def initial_report(conf,state,stamp):
    """Seeded historic data is not evidence of an automated nine-library scan."""
    return {'schema':1,'type':'seed','generated_at':stamp,'complete':None,
            'summary':None,'libraries':[{'id':l['id'],'name':l['name'],
            'active_count':sum(v['active'] for v in state['libraries'][l['id']]['items'].values()),
            'status':'seed'} for l in conf], 'history':[]}


def action_summary(report):
    """Also emit actionable summary in the Actions run without requiring site access."""
    s=report['summary']
    lines=[f"## HyRead 更新結果 · {report['generated_at']}",
           f"- 成功 {s['successful']}/{s['total']} 館；失敗 {s['failed']} 館",
           f"- 本次成功核對書目筆數：{s['verified_records']}；目前各館已收錄紀錄：{s['active_records']}",
           f"- 新增館藏書名 {s['new_titles']}、新刊期 {s['new_issues']}、恢復列出 {s['returned']}、停止列出 {s['not_listed']}",
           '', '| 圖書館 | 結果 | 核對筆數 | 新書名 | 新刊期 |',
           '|---|---|---:|---:|---:|']
    for l in report['libraries']:
        lines.append(f"| {l['name']} | {'成功' if l['status']=='ok' else '失敗（保留舊資料）'} | {l['verified_count'] if l['verified_count'] is not None else '—'} | {len(l['changes']['new'])} | {len(l['changes']['new_issue'])} |")
    path=os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path,'a',encoding='utf-8') as out:out.write('\n'.join(lines)+'\n')


def run(scanner_factory=LibraryScanner,when=None):
    stamp=when or now()
    conf,state=initialize()
    history=load(HISTORY,{'version':1,'events':[]})
    results=[]
    per_library={}
    for lib in conf:
        print(f"[{lib['name']}] scanning 12 categories...",flush=True)
        scanner=scanner_factory(lib['id'])
        record=state['libraries'][lib['id']]
        record['last_attempt']=stamp
        try:
            observed=scanner.scan()
            events=ingest(state,lib,observed,stamp)
            history['events'].extend(events)
            record['retry_count']=scanner.used_retries
            results.append(True)
            per_library[lib['id']]={'ok':True,'events':events,'verified_count':record['verified_count']}
            print(f"  ✓ verified {record['verified_count']}; changes {len(events)}; retries {scanner.used_retries}",flush=True)
        except Exception as exc:
            record.update({'result':'stale','error':str(exc)[:300],
                           'retry_count':scanner.used_retries})
            results.append(False)
            per_library[lib['id']]={'ok':False,'events':[],'verified_count':None}
            print(f"  ! stale: {exc}",flush=True)
        # Even when one library fails, proceed to other libraries; only this
        # library's last good records are preserved.
    threshold=(datetime.fromisoformat(stamp).date()-timedelta(days=180)).isoformat()
    history['events']=[e for e in history['events'] if e.get('at','')[:10]>=threshold]
    payload=published(state,conf,stamp)
    report=build_report(conf,state,stamp,per_library,load(REPORT,{}))
    action_summary(report)
    # Publish only once, after all libraries have finished and validated.
    atomic_json(STATE,state)
    atomic_json(HISTORY,history)
    atomic_json(PUBLIC,payload)
    atomic_json(REPORT,report)
    atomic_json(STATUS,{'generated_at':stamp,'results':payload['libraries'],
                        'complete':all(results),'successful':sum(results),'total':len(results)})
    return all(results)


def main():
    args=argparse.ArgumentParser()
    args.add_argument('--seed-only',action='store_true',help='Build initial site data without any network')
    args.add_argument('--once',action='store_true',help='Fetch and update all 9 libraries')
    parsed=args.parse_args()
    if parsed.seed_only:
        conf,state=initialize()
        if not STATE.exists():atomic_json(STATE,state)
        if not HISTORY.exists():atomic_json(HISTORY,{'version':1,'events':[]})
        initial=published(state,conf,'2026-10-30T12:30:00+08:00')
        atomic_json(PUBLIC,initial)
        if not REPORT.exists():atomic_json(REPORT,initial_report(conf,state,initial['generated_at']))
        atomic_json(STATUS,{'generated_at':initial['generated_at'],'results':initial['libraries'],
                            'complete':True,'successful':9,'total':9,'note':'2026-10-30 手工核對初始資料快照；後續每週由爬蟲核對'})
        print('Seed generated',len(initial['magazines']))
        return
    if not parsed.once:raise SystemExit('Specify --once or --seed-only')
    ok=run()
    if not ok:raise SystemExit(1)  # mark workflow failure even when partial updates are safe

if __name__=='__main__':main()
