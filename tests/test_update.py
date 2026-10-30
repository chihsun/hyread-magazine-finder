import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from src.hyread import LibraryScanner,extract_category,key
from src.update import initialize,make_seed,ingest,published

SAMPLE = '''<html><body><nav>電子雜誌　財經商管</nav>
<h3>財經商管(3)</h3><ul><li>商業周刊</li><li>商業周刊(精華版)</li></ul>
<div>財經商管</div><h6><a href="/x">商業周刊</a></h6><div>最新發刊 :2026-10-29</div><p>雜誌類型 :周刊</p>
<h6><a href="/x2">商業周刊(精華版)</a></h6><div>最新發刊 :2026-11-02</div><p>雜誌類型 :周刊</p>
<h6><a href="/x3">長期停刊雜誌</a></h6><div>最新發刊 :2024-03-01</div><p>雜誌類型 :周刊</p>
</body></html>'''

class HyReadTests(unittest.TestCase):
    def test_parse_with_old_and_latest(self):
        rows=extract_category(SAMPLE,'https://tpml.example/M02','財經商管')
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['title'],'商業周刊')
        self.assertNotEqual(key(rows[0]['title']),key(rows[1]['title']))
        self.assertEqual(rows[-1]['date'],'2024-03-01')

    def test_reject_login_or_blocked(self):
        with self.assertRaises(ValueError):
            extract_category('<html><body>請登入</body></html>','https://example','財經商管')

    def test_seed_and_comparison(self):
        conf,state=initialize()
        self.assertEqual(len(conf),9)
        self.assertEqual(len(published(state,conf,'2026-10-30T12:30:00+08:00')['magazines']),129)
        self.assertEqual(published(state,conf,'2026-10-30T12:30:00+08:00')['distribution']['9'],110)

    def test_ingest_keeps_latest_and_misses(self):
        conf,state=initialize()
        lib=conf[0]
        originals=copy.deepcopy(state['libraries'][lib['id']]['items'])
        observed={k:{'title':r['title'],'date':r['latest_date'],'source_url':'https://example.com'} for k,r in originals.items()}
        first=next(iter(observed))
        old_date=observed[first]['date']
        observed[first]['date']='2026-12-01'
        events=ingest(state,lib,observed,'2026-12-01T08:00:00+08:00')
        self.assertTrue(any(e['type']=='new_issue' for e in events))
        observed[first]['date']=old_date
        ingest(state,lib,observed,'2026-12-08T08:00:00+08:00')
        self.assertEqual(state['libraries'][lib['id']]['items'][first]['latest_date'],'2026-12-01')
        del observed[first]
        for i in range(3):
            ingest(state,lib,observed,f'2026-12-{15+i:02}T08:00:00+08:00')
        self.assertFalse(state['libraries'][lib['id']]['items'][first]['active'])
        self.assertEqual(state['libraries'][lib['id']]['items'][first]['latest_date'],'2026-12-01')

    def test_reject_suspicious_loss_without_mutation(self):
        conf,state=initialize()
        lib=conf[0]
        copy_before=copy.deepcopy(state['libraries'][lib['id']]['items'])
        with self.assertRaises(ValueError):
            ingest(state,lib,{'only':{'title':'一','date':'2026-10-01','source_url':'http://e'}},'2026-12-01T08:00:00+08:00')
        self.assertEqual(copy_before,state['libraries'][lib['id']]['items'])

    def test_retry_budget_per_library_not_per_request(self):
        class FakeSession:
            headers={}
            def __init__(self):self.calls=0
            def get(self,u,timeout=18):
                self.calls+=1
                if self.calls in (1,2):raise ValueError('temporary failure')
                r=Mock();r.status_code=200;r.content=b'x'*1000
                r.raise_for_status=Mock()
                return r
        fake=FakeSession()
        scanner=LibraryScanner('tpml',retries=3,delay=0,session=fake)
        # Stub sleep to avoid test slowdown.
        from unittest.mock import patch
        with patch('src.hyread.time.sleep'):
            self.assertEqual(len(scanner.fetch('https://example')),1000)
        self.assertEqual(scanner.used_retries,2)
        self.assertEqual(fake.calls,3)

if __name__=='__main__':unittest.main()

class UpdateReportTests(unittest.TestCase):
    def test_summary_distinguishes_new_titles_from_new_issues_and_failed_scans(self):
        from src.update import build_report, initial_report
        conf,state=initialize()
        stamp='2026-11-06T08:00:00+08:00'
        per={}
        for lib in conf:
            item=state['libraries'][lib['id']]
            per[lib['id']]={'ok':True,'verified_count':len(item['items']),'events':[]}
        first=conf[0]['id']
        second=conf[1]['id']
        per[first]['events']=[
          {'at':stamp,'library':first,'type':'new','title':'新測試雜誌','to':'2026-11-06'},
          {'at':stamp,'library':first,'type':'new_issue','title':'既有雜誌','from':'2026-10-30','to':'2026-11-06'},
        ]
        per[second]={'ok':False,'verified_count':None,'events':[]}
        state['libraries'][second]['result']='stale'
        state['libraries'][second]['error']='read timeout'
        prev=initial_report(conf,state,'2026-10-30T12:30:00+08:00')
        report=build_report(conf,state,stamp,per,prev)
        self.assertEqual(report['summary']['successful'],8)
        self.assertEqual(report['summary']['new_titles'],1)
        self.assertEqual(report['summary']['new_issues'],1)
        self.assertIsNone(report['libraries'][1]['verified_count'])
        self.assertEqual(report['libraries'][1]['change_count'],0)
        self.assertEqual(report['libraries'][0]['changes']['new'][0]['title'],'新測試雜誌')
        self.assertFalse(report['complete'])
        self.assertEqual(report['history'][0]['summary']['changes_total'],2)

    def test_history_only_180_days_and_seed_not_pretend_scraped(self):
        from src.update import build_report, initial_report
        conf,state=initialize()
        seed=initial_report(conf,state,'2026-10-30T12:30:00+08:00')
        self.assertIsNone(seed['summary'])
        per={lib['id']:{'ok':True,'verified_count':len(state['libraries'][lib['id']]['items']),'events':[]} for lib in conf}
        previous={'history':[{'at':'2025-01-01T08:00:00+08:00','summary':{}}, {'at':'2026-11-01T08:00:00+08:00','summary':{}}]}
        report=build_report(conf,state,'2026-11-06T08:00:00+08:00',per,previous)
        self.assertEqual(len(report['history']),2)
        self.assertEqual(report['summary']['changes_total'],0)
        self.assertEqual(report['summary']['verified_records'],sum(len(state['libraries'][l['id']]['items']) for l in conf))
