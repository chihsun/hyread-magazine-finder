"""V1.6.2: source-bound magazine detail links, safe correction on future updates."""
import copy
import unittest
from unittest.mock import patch

from src.assisted_update import apply_batch, validate_batch
from src.hyread import extract_latest_page, key
from src.latest_pages import inspect_latest_html, build_latest_observations
from src.update import initialize, STATE


LIB='tpml'
PAGE='https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_view_more.jsp?nowpage=1'
DETAIL=lambda jid: f'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid={jid}'
STAMP='2026-10-31T08:17:00+08:00'


def html(*, with_anchor=True):
    head=(f'<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=187">Camera攝影誌</a></h6>'
          if with_anchor else '<h6>Camera攝影誌</h6>')
    return ('<html><body><h1>最新出刊電子雜誌</h1>'
            +head+'<div>最新發刊 :2026-11-05</div>'
            +'<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=595">Travel Plus 就醬玩旅行</a></h6>'
            +'<div>最新發刊 :2026-11-01</div>'
            +'<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=846">舊刊雜誌</a></h6>'
            +'<div>最新發刊 :2026-10-23</div>'
            +'</body></html>')


def sample_batch():
    parsed=inspect_latest_html(html(),LIB,1,STAMP,'search_index')
    rows,coverage=build_latest_observations([parsed],'2026-10-24','2026-10-30')
    return {'schema':4,'source':'chatgpt_assisted',
            'batch_id':'v162-link-update-001','window_start':'2026-10-24',
            'window_end':'2026-10-30',
            'libraries':[{'id':LIB,'status':'complete','attempts':1,
                          'retry_wait_seconds':[],
                          'notes':'第 1 頁直接確認每本書名標題錨點與網址。',
                          'coverage':coverage,'records':rows}]}


class LinkProofV162(unittest.TestCase):
    def test_heading_link_extraction_has_per_title_provenance(self):
        rows=extract_latest_page(html(),PAGE)
        self.assertEqual([r['title'] for r in rows],['Camera攝影誌','Travel Plus 就醬玩旅行','舊刊雜誌'])
        self.assertEqual([r['magazine_url'] for r in rows],[DETAIL(187),DETAIL(595),DETAIL(846)])
        self.assertEqual(rows[0]['link_evidence'],{
            'anchor_text':'Camera攝影誌','href':DETAIL(187),'source_url':PAGE})
        self.assertEqual(rows[1]['link_evidence']['anchor_text'],'Travel Plus 就醬玩旅行')

    def test_navigation_link_same_name_cannot_be_misassigned(self):
        page=html(with_anchor=False).replace('<h1>最新出刊電子雜誌</h1>',
            '<h1>最新出刊電子雜誌</h1><nav>'
            '<a href="/Template/RWD3.0/magazine_more.jsp?jid=999">Camera攝影誌</a></nav>')
        rows=extract_latest_page(page,PAGE)
        camera=next(x for x in rows if x['title']=='Camera攝影誌')
        self.assertIsNone(camera['magazine_url'])
        self.assertNotIn('link_evidence',camera)

    def test_parent_anchor_and_conflicting_links(self):
        page=html().replace('<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=187">Camera攝影誌</a></h6>',
            '<a href="/Template/RWD3.0/magazine_more.jsp?jid=187"><h6>Camera攝影誌</h6></a>')
        self.assertEqual(extract_latest_page(page,PAGE)[0]['magazine_url'],DETAIL(187))
        page=html().replace(
            '<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=187">Camera攝影誌</a></h6>',
            '<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=187">Camera攝影誌</a>'
            '<a href="/Template/RWD3.0/magazine_more.jsp?jid=999">Camera攝影誌</a></h6>')
        self.assertIsNone(extract_latest_page(page,PAGE)[0]['magazine_url'])

    def test_first_book_and_each_row_require_source_link_evidence(self):
        b=sample_batch()
        rows=b['libraries'][0]['records']
        cov=b['libraries'][0]['coverage']
        self.assertEqual(cov['first_book']['link_evidence']['href'],DETAIL(187))
        self.assertEqual(len(rows),2)  # Historical issue before the cutoff is excluded.
        conf,_=initialize()
        checked=validate_batch(b,conf)
        self.assertEqual(checked['libraries'][LIB]['observed'][key('Camera攝影誌')]['link_evidence']['href'],DETAIL(187))
        for change in (
            lambda d: d['libraries'][0]['records'][0].pop('link_evidence'),
            lambda d: d['libraries'][0]['records'][0]['link_evidence'].update({'href':DETAIL(999)}),
            lambda d: d['libraries'][0]['records'][0]['link_evidence'].update({'anchor_text':'其他雜誌'}),
            lambda d: d['libraries'][0]['records'][0]['link_evidence'].update({'source_url':'https://tpml.ebook.hyread.com.tw/index.jsp'}),
            lambda d: d['libraries'][0]['coverage']['first_book'].pop('link_evidence'),
        ):
            with self.subTest(change=change):
                invalid=copy.deepcopy(b)
                change(invalid)
                with self.assertRaises(ValueError):
                    validate_batch(invalid,conf)

    def test_update_corrects_wrong_jid_and_fills_missing_only_on_next_scan(self):
        b=sample_batch()
        conf,state=initialize()
        state=copy.deepcopy(state)
        items=state['libraries'][LIB]['items']
        a=items[key('Camera攝影誌')]
        a['latest_date']='2026-11-05'
        a['magazine_url']=DETAIL(214)  # Old wrong link, only corrected when a title anchor is observed.
        travel=items[key('Travel Plus 就醬玩旅行')]
        travel['latest_date']='2026-11-01'
        travel['magazine_url']=None
        writes={}
        def collect(path,data): writes[str(path)]=copy.deepcopy(data)
        with patch('src.assisted_update.initialize',return_value=(conf,state)):
            with patch('src.assisted_update.atomic_json',side_effect=collect):
                report=apply_batch(b,persist=True,stamp=STAMP)
        saved=writes[str(STATE)]['libraries'][LIB]['items']
        self.assertEqual(saved[key('Camera攝影誌')]['magazine_url'],DETAIL(187))
        self.assertEqual(saved[key('Travel Plus 就醬玩旅行')]['magazine_url'],DETAIL(595))
        self.assertEqual(saved[key('Camera攝影誌')]['latest_date'],'2026-11-05')
        self.assertEqual(saved[key('Camera攝影誌')]['magazine_url_verified_by'],'source_title_anchor')
        self.assertEqual(saved[key('Travel Plus 就醬玩旅行')]['magazine_url_checked_at'],STAMP)
        self.assertEqual(report['summary']['new_issues'],0)
        self.assertEqual(report['summary']['links_added'],1)
        self.assertEqual(report['summary']['links_changed'],1)
        self.assertEqual(report['batch_schema'],4)

    def test_without_anchor_do_not_overwrite_an_old_link(self):
        from src.assisted_update import merge_incremental
        _,state=initialize()
        state=copy.deepcopy(state)
        current=state['libraries'][LIB]['items'][key('Camera攝影誌')]
        old_url=current['magazine_url']
        events=merge_incremental(state,{'id':LIB},{
            key('Camera攝影誌'):{'title':'Camera攝影誌','date':current['latest_date'],
                'source_url':PAGE,'magazine_url':None}},STAMP)
        self.assertEqual(current['magazine_url'],old_url)
        self.assertFalse(any(x['type'].startswith('link_') for x in events))


if __name__=='__main__':
    unittest.main()
