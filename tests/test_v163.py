"""V1.6.3: queryless first listing and safe page-link/search-index fallback."""
import copy
import unittest

from src.assisted_update import validate_batch
from src.coverage import validate_coverage
from src.latest_pages import (
    build_latest_observations, inspect_latest_html, latest_page_url,
    next_page_link,
)
from src.update import initialize

LIB='tnml'
STAMP='2026-10-31T08:30:00+08:00'
FIRST=f'https://{LIB}.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp'
SECOND=FIRST+'?nowpage=2'


def page_html(entries, footer=''):
    return ('<html><body><h1>最新出刊電子雜誌</h1>'
        + ''.join(f'<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid={jid}">{title}</a></h6>'
                  f'<div>最新發刊 :{day}</div>'
                  for jid,title,day in entries)
        + footer+'</body></html>')


def sample():
    p1=inspect_latest_html(page_html([
        (187,'Camera攝影誌','2026-11-05'),
        (595,'Travel Plus 就醬玩旅行','2026-10-29')],
        '<nav><a href="?nowpage=2">2</a></nav>'),
        LIB,1,STAMP,'direct')
    p2=inspect_latest_html(page_html([
        (130,'乙號雜誌','2026-10-25'),
        (131,'丙號雜誌','2026-10-23')]),
        LIB,2,STAMP,'search_index')
    rows,cov=build_latest_observations([p1,p2],'2026-10-24','2026-10-30')
    batch={'schema':4,'source':'chatgpt_assisted',
           'batch_id':'v163-navigation-001','window_start':'2026-10-24',
           'window_end':'2026-10-30',
           'libraries':[{'id':LIB,'status':'complete','attempts':1,
                         'retry_wait_seconds':[],
                         'notes':'第 1 頁不帶參數；第 2 頁由搜尋索引取得完整書名及刊期。',
                         'coverage':cov,'records':rows}]}
    return batch


class QuerylessFirstPageV163(unittest.TestCase):
    def test_first_page_has_no_parameter_and_second_does(self):
        self.assertEqual(latest_page_url(LIB,1),FIRST)
        self.assertEqual(latest_page_url(LIB,2),SECOND)

    def test_only_real_navigation_href_may_be_reported(self):
        content=page_html([(187,'Camera攝影誌','2026-11-05')],
                          '<nav><a href="?nowpage=2">下一頁</a></nav>')
        self.assertEqual(next_page_link(content,LIB,1),SECOND)
        content=page_html([(187,'Camera攝影誌','2026-11-05')],
                          '<a href="https://example.org/?nowpage=2">下一頁</a>')
        self.assertIsNone(next_page_link(content,LIB,1))
        content=page_html([(187,'Camera攝影誌','2026-11-05')],
                          '<a href="javascript:goNext()">下一頁</a>')
        self.assertIsNone(next_page_link(content,LIB,1))
        self.assertIsNone(next_page_link(page_html([(187,'Camera攝影誌','2026-11-05')]),LIB,1))

    def test_source_evidence_and_cache_fallback_keep_full_coverage(self):
        batch=sample()
        lib=batch['libraries'][0]
        cov=lib['coverage']
        self.assertEqual(cov['pages'][0]['url'],FIRST)
        self.assertEqual(cov['pages'][0]['navigation_next_url'],SECOND)
        self.assertEqual(cov['pages'][1]['url'],SECOND)
        self.assertEqual(cov['pages'][1]['source_type'],'search_index')
        self.assertEqual(cov['first_book']['source_url'],FIRST)
        self.assertEqual(cov['first_book']['link_evidence']['source_url'],FIRST)
        self.assertEqual([r['date'] for r in lib['records']],
                         ['2026-11-05','2026-10-29','2026-10-25'])
        conf,_=initialize()
        validated=validate_batch(batch,conf)
        self.assertEqual(validated['libraries'][LIB]['status'],'complete')
        page=validated['libraries'][LIB]['coverage']['pages'][0]
        self.assertEqual(page['navigation_next_url'],SECOND)
        self.assertEqual(validated['libraries'][LIB]['coverage']['checked_pages'],2)

    def test_legacy_nowpage_one_alias_only_for_comparison(self):
        original=sample()
        lib=original['libraries'][0]
        lib['coverage']['pages'][0]['url']=FIRST+'?nowpage=1'
        lib['coverage']['first_book']['source_url']=FIRST
        lib['records'][0]['source_url']=FIRST+'?nowpage=1'
        lib['records'][0]['link_evidence']['source_url']=FIRST
        conf,_=initialize()
        checked=validate_batch(original,conf)
        self.assertEqual(checked['libraries'][LIB]['status'],'complete')
        # New sessions still generate only the unparameterized first-page URL.
        self.assertEqual(latest_page_url(LIB,1),FIRST)

    def test_wrong_navigation_link_rejected(self):
        batch=sample()
        batch['libraries'][0]['coverage']['pages'][0]['navigation_next_url']=FIRST+'?nowpage=3'
        with self.assertRaisesRegex(ValueError,'navigation_next_url'):
            validate_coverage(batch['libraries'][0]['coverage'],LIB,'2026-10-24',True,simple=True)

    def test_unreadable_second_page_stays_partial_without_fake_http_code(self):
        batch=sample()
        lib=batch['libraries'][0]
        lib['status']='partial'
        lib['notes']='第 1 頁成功，第 2 頁讀取工具回報 Internal Error，未收到 HTTP 狀態碼。'
        lib['coverage']['pages'][1]={
            'page':2,'url':SECOND,'status':'failed','source_type':'search_index',
            'observed_at':STAMP,'error_code':'TOOL_UNAVAILABLE',
            'error':'Internal Error: URL is not accessible via this tool'
        }
        lib['records']=[r for r in lib['records'] if r['source_url']==FIRST]
        conf,_=initialize()
        checked=validate_batch(batch,conf)
        self.assertEqual(checked['libraries'][LIB]['status'],'partial')
        self.assertEqual(checked['libraries'][LIB]['coverage']['failed_pages'],1)


if __name__=='__main__':
    unittest.main()
