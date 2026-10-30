import copy
import unittest

from src.coverage import magazine_url, validate_coverage
from src.hyread import extract_category, extract_latest_page, key
from src.assisted_update import validate_batch, merge_incremental, build_assisted_report
from src.update import initialize, published
from src.latest_pages import latest_page_url, inspect_latest_html, build_latest_observations

LIB='tpml'
URL='https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage=1'
DETAIL='https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=846'
STAMP='2026-11-06T08:50:00+08:00'

def page(n, newest, oldest, *, source_type='direct', status='ok', category=None):
    p={'page':n,'url':f'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage={n}',
       'status':status,'source_type':source_type,'observed_at':STAMP,
       'newest_date':newest,'oldest_date':oldest}
    if category:p['category']=category
    return p


class V14Tests(unittest.TestCase):
    def test_latest_page_priority_offline_inspection_and_boundary(self):
        def html(dates, label):
            return '<html><body><h1>最新出刊電子雜誌</h1>'+''.join(
                f'<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid={846+i}">雜誌{label}{i}</a></h6><div>最新發刊 :{day}</div>'
                for i,day in enumerate(dates))+'</body></html>'
        first=inspect_latest_html(html(['2026-10-30','2026-10-26'], 'A'),LIB,1,STAMP)
        second=inspect_latest_html(html(['2026-10-25','2026-10-22'], 'B'),LIB,2,STAMP)
        rows,coverage=build_latest_observations([second,first],'2026-10-23','2026-10-30')
        self.assertTrue(coverage['date_boundary_reached'])
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['magazine_url'],DETAIL)
        self.assertEqual(validate_coverage(coverage,LIB,'2026-10-23',True)['checked_pages'],2)

    def test_latest_page_stale_index_and_wrong_order_not_complete(self):
        html='''<h1>最新出刊電子雜誌</h1><h6>雜誌A</h6><div>最新發刊 :2026-10-22</div><h6>雜誌B</h6><div>最新發刊 :2026-10-26</div>'''
        with self.assertRaisesRegex(ValueError,'排序'):
            inspect_latest_html(html,LIB,1,STAMP)
        html=html.replace('2026-10-22','2026-10-30')
        _,evidence=inspect_latest_html(html,LIB,1,STAMP,source_type='search_index')
        _,cov=build_latest_observations([inspect_latest_html(html,LIB,1,STAMP,'search_index')],
                                         '2026-10-23','2026-10-30')
        self.assertFalse(validate_coverage(cov,LIB,'2026-10-23',False)['date_boundary_reached'])
        with self.assertRaisesRegex(ValueError,'完整核對'):
            validate_coverage({**cov,'date_boundary_reached':True},LIB,'2026-10-23',True)

    def test_complete_batch_updates_check_timestamp(self):
        from unittest.mock import patch
        from src import assisted_update as au
        batch={'schema':1,'source':'chatgpt_assisted','batch_id':'v14-complete-001',
          'window_start':'2026-10-23','window_end':'2026-10-30',
          'libraries':[{'id':LIB,'status':'complete','attempts':1,'retry_wait_seconds':[],
            'notes':'完整讀取最新出刊前兩頁、日期界線已核實。',
            'coverage':{'method':'latest_pages','pagination_contiguous':True,
              'date_boundary_reached':True,
              'pages':[page(1,'2026-10-30','2026-10-28'),page(2,'2026-10-28','2026-10-22')]},
            'records':[]}]}
        report=au.apply_batch(batch,persist=False,stamp=STAMP)
        l=next(x for x in report['libraries'] if x['id']==LIB)
        self.assertEqual(l['status'],'ok')
        self.assertEqual(l['last_complete_check'],STAMP)
        self.assertTrue(l['coverage']['date_boundary_reached'])

    def test_detail_url_normalize_and_security(self):
        self.assertEqual(magazine_url(DETAIL,LIB),DETAIL)
        self.assertEqual(magazine_url(None,LIB),None)
        for value in (
            'https://example.com/Template/RWD3.0/magazine_more.jsp?jid=846',
            'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine-list.jsp?jid=846',
            'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=abc',
            'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid=846&next=1',
            'javascript:alert(1)',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                magazine_url(value,LIB)

    def test_parser_preserves_title_specific_jid(self):
        html='''<body><h3>財經商管(1)</h3>
        <h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=846">商業周刊</a></h6>
        <div>最新發刊 :2026-10-29</div></body>'''
        result=extract_category(html,URL,'財經商管')
        self.assertEqual(result[0]['magazine_url'],DETAIL)
        html=html.replace('magazine_more.jsp?jid=846','magazine-list.jsp?magazineclass=M02')
        self.assertIsNone(extract_category(html,URL,'財經商管')[0]['magazine_url'])

    def test_latest_page_parser_supports_real_detail_url(self):
        html='''<html><body><h1>最新出刊電子雜誌</h1>
        <h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=846">商業周刊</a></h6>
        <div>最新發刊 :2026-10-29</div></body></html>'''
        rows=extract_latest_page(html,URL)
        self.assertEqual(rows[0]['magazine_url'],DETAIL)

    def test_complete_requires_strict_direct_consecutive_date_boundary(self):
        pages=[page(1,'2026-10-30','2026-10-28'),page(2,'2026-10-28','2026-10-22')]
        source={'method':'latest_pages','pages':pages,'pagination_contiguous':True,'date_boundary_reached':True}
        c=validate_coverage(source,LIB,'2026-10-23',True)
        self.assertEqual(c['checked_pages'],2)
        self.assertTrue(c['date_boundary_reached'])
        failures=[
            {'pages':[page(1,'2026-10-30','2026-10-28'),page(3,'2026-10-28','2026-10-22')]},
            {'pages':[page(1,'2026-10-30','2026-10-28'),page(2,'2026-10-28','2026-10-22',source_type='search_index')]},
            {'pages':[page(1,'2026-10-30','2026-10-28'),page(2,'2026-10-28','2026-10-25')]},
            {'date_boundary_reached':False},
        ]
        for change in failures:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_coverage({**source,**change},LIB,'2026-10-23',True)

    def test_partial_retains_failed_pages_and_unconfirmed_boundary(self):
        c=validate_coverage({'method':'latest_pages','pages':[page(1,'2026-10-30','2026-10-28'),
                             page(2,None,None,status='failed')],
                             'pagination_contiguous':False,'date_boundary_reached':False},LIB,'2026-10-23',False)
        self.assertEqual(c['failed_pages'],1)
        self.assertFalse(c['date_boundary_reached'])

    def test_existing_link_is_added_even_with_older_issue_but_never_regresses(self):
        conf,state=initialize()
        title='先探投資週刊'
        k=key(title)
        existing=state['libraries'][LIB]['items'][k]
        old_date=existing['latest_date']
        existing['magazine_url']=None
        events=merge_incremental(state,{'id':LIB},{k:{'title':title,'date':'2026-10-23',
                         'source_url':URL,'magazine_url':DETAIL}}, STAMP)
        self.assertEqual(existing['latest_date'],old_date)
        self.assertEqual(existing['magazine_url'],DETAIL)
        self.assertEqual([x['type'] for x in events],['link_added'])
        published_catalog=published(state,conf,STAMP)
        row=next(x for x in published_catalog['magazines'] if x['key']==k)
        self.assertEqual(row['by'][LIB]['magazine_url'],DETAIL)
        # A later observation without detail URL must not erase a good link.
        events=merge_incremental(state,{'id':LIB},{k:{'title':title,'date':'2026-10-24',
                         'source_url':URL,'magazine_url':None}}, STAMP)
        self.assertEqual(events,[])
        self.assertEqual(existing['magazine_url'],DETAIL)

    def test_batch_accepts_optional_valid_detail_and_rejects_fake_complete(self):
        conf,_=initialize()
        batch={'schema':1,'source':'chatgpt_assisted','batch_id':'v14test-001',
           'window_start':'2026-10-23','window_end':'2026-10-30','libraries':[
           {'id':LIB,'status':'partial','attempts':1,'retry_wait_seconds':[],
            'notes':'查詢只有第一頁','coverage':{'method':'search_index','pages':[]},
            'records':[{'title':'商業周刊','date':'2026-10-29','source_url':URL,'magazine_url':DETAIL}]}]}
        normalized=validate_batch(batch,conf)
        self.assertEqual(normalized['libraries'][LIB]['observed'][key('商業周刊')]['magazine_url'],DETAIL)
        batch['libraries'][0]['status']='complete'
        with self.assertRaisesRegex(ValueError,'完整核對'):
            validate_batch(batch,conf)
        batch['libraries'][0]['status']='partial'
        batch['libraries'][0]['records'][0]['magazine_url']=DETAIL.replace('tpml.','tnml.')
        with self.assertRaisesRegex(ValueError,'來源網址'):
            validate_batch(batch,conf)

if __name__=='__main__': unittest.main()
