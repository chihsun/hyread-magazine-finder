"""V1.6: pragmatic ChatGPT-assisted latest-issue update rules."""
import unittest
from copy import deepcopy
from datetime import date
from unittest.mock import patch

from src.latest_pages import inspect_latest_html, build_latest_observations, requested_window
from src.coverage import validate_coverage
from src.assisted_update import apply_batch, validate_batch
from src.update import initialize, STATE


LIB='tpml'
STAMP='2026-10-30T23:29:00+08:00'


def page_html(*titles):
    return ('<html><body><h1>最新出刊電子雜誌</h1>' +
            ''.join(f'<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid={800+i}">{title}</a></h6>'
                    f'<div>最新發刊 :{day}</div>'
                    for i,(title,day) in enumerate(titles)) + '</body></html>')


def example():
    a=inspect_latest_html(page_html(('甲號雜誌','2026-10-30'),('乙號雜誌','2026-10-28')),
                          LIB,1,STAMP,source_type='search_index')
    b=inspect_latest_html(page_html(('丙號雜誌','2026-10-27'),('丁號雜誌','2026-10-23')),
                          LIB,2,STAMP,source_type='search_index')
    rows,cov=build_latest_observations([a,b],'2026-10-24','2026-10-30')
    return rows,cov


def batch(rows,cov,*,status='complete',attempts=1):
    return {'schema':3,'source':'chatgpt_assisted','batch_id':'v16-tests-20261030',
            'window_start':'2026-10-24','window_end':'2026-10-30',
            'libraries':[{'id':LIB,'status':status,'attempts':attempts,
                          'retry_wait_seconds':[3.0,7.0][:attempts-1],
                          'notes':'最新出刊頁面依指定日期查詢。',
                          'coverage':cov,'records':rows}]}


class SimpleUpdateV16(unittest.TestCase):
    def test_requested_n_days_no_seven_day_extension(self):
        self.assertEqual(requested_window(7,date(2026,10,30)),('2026-10-24','2026-10-30'))
        self.assertEqual(requested_window(1,date(2026,10,30)),('2026-10-30','2026-10-30'))
        with self.assertRaises(ValueError):
            requested_window(0,date(2026,10,30))

    def test_cache_pages_can_complete_without_recheck(self):
        rows,cov=example()
        self.assertEqual(len(rows),3)
        self.assertFalse('first_page_recheck' in cov)
        self.assertEqual(cov['first_book']['title'],'甲號雜誌')
        self.assertEqual(cov['first_book']['jid'],'800')
        checked=validate_coverage(cov,LIB,'2026-10-24',True,simple=True)
        self.assertTrue(checked['date_boundary_reached'])
        self.assertEqual(checked['diagnostics']['source_types']['search_index'],2)
        self.assertEqual(checked['first_book']['magazine_url'].split('jid=')[-1],'800')
        conf,_=initialize()
        validate_batch(batch(rows,cov),conf)

    def test_stop_after_first_page_if_boundary_reached(self):
        rows,cov=example()
        one=build_latest_observations([(
            [{'title':'甲','date':'2026-10-30','source_url':cov['pages'][0]['url'],'magazine_url':None},
             {'title':'乙','date':'2026-10-23','source_url':cov['pages'][0]['url'],'magazine_url':None}],
            {**cov['pages'][0],'oldest_date':'2026-10-23'}
        )],'2026-10-24','2026-10-30')[1]
        self.assertTrue(validate_coverage(one,LIB,'2026-10-24',True,simple=True)['date_boundary_reached'])

    def test_missing_next_page_cannot_claim_complete(self):
        rows,cov=example()
        cov['pages'][1]['page']=3
        cov['pages'][1]['url']=cov['pages'][1]['url'].replace('nowpage=2','nowpage=3')
        with self.assertRaises(ValueError):
            validate_coverage(cov,LIB,'2026-10-24',True,simple=True)
        self.assertFalse(validate_coverage(cov,LIB,'2026-10-24',False,simple=True)['date_boundary_reached'])

    def test_first_page_failed_requires_failed_status(self):
        rows,cov=example()
        cov['pages'][0]['status']='failed'
        cov['pages'][0]['error']='無法讀取'
        cov['pages'][0]['error_code']='TOOL_UNAVAILABLE'
        conf,_=initialize()
        with self.assertRaisesRegex(ValueError,'第一頁未正常讀取'):
            validate_batch(batch(rows,cov,status='partial'),conf)
        fail=batch([],{**cov,'pages':[]},status='failed')
        fail['libraries'][0]['error_code']='ACCESS_DENIED'
        fail['libraries'][0]['error']='HTTP 403，立即停止'
        validated=validate_batch(fail,conf)
        self.assertEqual(validated['libraries'][LIB]['status'],'failed')

    def test_complete_save_anchor_with_jid_and_old_book_protection(self):
        rows,cov=example()
        conf,state=initialize()
        state=deepcopy(state)
        state['libraries'][LIB]['items']={}
        writes={}
        def remember(path,data):
            writes[str(path)]=deepcopy(data)
        with patch('src.assisted_update.initialize',return_value=(conf,state)):
            with patch('src.assisted_update.atomic_json',side_effect=remember):
                result=apply_batch(batch(rows,cov),persist=True,stamp=STAMP)
        saved=writes[str(STATE)]['libraries'][LIB]
        self.assertEqual(saved['latest_page_anchor']['title'],'甲號雜誌')
        self.assertEqual(saved['latest_page_anchor']['jid'],'800')
        self.assertEqual(saved['latest_page_anchor']['date'],'2026-10-30')
        self.assertEqual(result['summary']['successful'],1)
        self.assertEqual(result['libraries'][1]['saved_first_book'] if result['libraries'][1]['id']==LIB
                         else next(x['saved_first_book'] for x in result['libraries'] if x['id']==LIB),
                         saved['latest_page_anchor'])

    def test_stale_requires_retries_then_marks_partial_without_downgrade(self):
        rows,cov=example()
        conf,state=initialize()
        state=deepcopy(state)
        state['libraries'][LIB]['items']={}
        state['libraries'][LIB]['latest_page_anchor']={
            'title':'較新紀錄','date':'2026-11-01','jid':'999','magazine_url':None}
        with patch('src.assisted_update.initialize',return_value=(conf,state)):
            with self.assertRaisesRegex(ValueError,'需重試'):
                apply_batch(batch(rows,cov),stamp=STAMP)
            report=apply_batch(batch(rows,cov,attempts=3),stamp=STAMP)
        item=next(x for x in report['libraries'] if x['id']==LIB)
        self.assertEqual(item['status'],'partial')
        self.assertEqual(item['error_code'],'STALE_CACHE')
        self.assertTrue(item['stale_observations'])
        self.assertEqual(item['saved_first_book']['date'],'2026-11-01')

    def test_same_book_older_issue_not_replace_newer(self):
        rows,cov=example()
        conf,state=initialize()
        state=deepcopy(state)
        from src.hyread import key
        state['libraries'][LIB]['items']={
            key('乙號雜誌'):{'title':'乙號雜誌','latest_date':'2026-10-29',
                           'source_url':'https://tpml.ebook.hyread.com.tw/index.jsp',
                           'active':True,'first_seen':'2026-10-01',
                           'last_seen':'2026-10-29','misses':0}}
        with patch('src.assisted_update.initialize',return_value=(conf,state)):
            with patch('src.assisted_update.atomic_json') as writes:
                report=apply_batch(batch(rows,cov,attempts=3),persist=True,stamp=STAMP)
        saved=next(x.args[1] for x in writes.call_args_list if x.args[0]==STATE)
        self.assertEqual(saved['libraries'][LIB]['items'][key('乙號雜誌')]['latest_date'],'2026-10-29')
        self.assertEqual(next(x for x in report['libraries'] if x['id']==LIB)['error_code'],'STALE_CACHE')

    def test_future_first_book_checkpoint_independent_of_day_filter(self):
        p=inspect_latest_html(page_html(('預告刊','2026-11-02'),('本週刊','2026-10-28'),
                                         ('上週刊','2026-10-23')),
                              LIB,1,STAMP,'search_index')
        rows,cov=build_latest_observations([p],'2026-10-24','2026-10-30')
        self.assertEqual(cov['first_book']['date'],'2026-11-02')
        self.assertEqual([x['title'] for x in rows],['本週刊'])


if __name__=='__main__':
    unittest.main()
