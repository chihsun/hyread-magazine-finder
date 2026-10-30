"""V1.5 regression tests: keep ChatGPT evidence honest and backward compatible."""
import unittest
from copy import deepcopy
from datetime import timedelta, datetime

from src.latest_pages import inspect_latest_html, build_latest_observations
from src.coverage import validate_coverage
from src.assisted_update import validate_batch, apply_batch
from src.update import initialize

LIB = 'tpml'
T0 = '2026-10-30T19:00:00+08:00'
T1 = '2026-10-30T19:01:00+08:00'
T2 = '2026-10-30T19:02:00+08:00'
SCAN = 'tpml-20261030-190000'


def html(*entries):
    return '<html><body><h1>最新出刊電子雜誌</h1>' + ''.join(
        '<h6><a href="/Template/RWD3.0/magazine_more.jsp?jid=' + str(900+i) +
        '">' + title + '</a></h6><div>最新發刊 :' + day + '</div>'
        for i, (title, day) in enumerate(entries)) + '</body></html>'


def sample():
    first_html = html(('甲刊','2026-10-30'),('乙刊','2026-10-28'))
    second_html = html(('丙刊','2026-10-27'),('丁刊','2026-10-22'))
    first = inspect_latest_html(first_html, LIB, 1, T0, scan_id=SCAN)
    second = inspect_latest_html(second_html, LIB, 2, T1, scan_id=SCAN)
    replay = inspect_latest_html(first_html, LIB, 1, T2, scan_id=SCAN)[1]
    rows, evidence = build_latest_observations(
        [first, second], '2026-10-23','2026-10-30',
        scan_id=SCAN, first_page_recheck=replay)
    return rows, evidence


class ProvenanceV15(unittest.TestCase):
    def test_schema2_complete_direct_scan_with_recheck(self):
        rows, evidence = sample()
        self.assertEqual(len(rows), 3)
        checked = validate_coverage(evidence, LIB, '2026-10-23', True, strict=True)
        self.assertEqual(checked['scan_id'], SCAN)
        self.assertEqual(checked['diagnostics']['first_page_stable'], True)
        self.assertEqual(checked['diagnostics']['issues'], [])
        self.assertEqual(checked['checked_pages'], 2)

    def test_schema2_rejects_missing_or_drifted_recheck(self):
        _, e = sample()
        removed = deepcopy(e)
        removed.pop('first_page_recheck')
        with self.assertRaisesRegex(ValueError, '完整核對'):
            validate_coverage(removed, LIB, '2026-10-23', True, strict=True)
        altered = deepcopy(e)
        altered['first_page_recheck']['content_digest'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, '完整核對'):
            validate_coverage(altered, LIB, '2026-10-23', True, strict=True)

    def test_missing_page_and_mismatched_run_are_partial(self):
        _, e = sample()
        e['pages'][1]['page'] = 3
        e['pages'][1]['url'] = e['pages'][1]['url'].replace('nowpage=2','nowpage=3')
        e['pages'][1]['scan_id'] = 'different-run-001'
        result = validate_coverage(e, LIB, '2026-10-23', False, strict=True)
        self.assertEqual(result['diagnostics']['missing_pages'], [2])
        self.assertIn('SCAN_ID_MISMATCH',result['diagnostics']['issues'])
        self.assertFalse(result['date_boundary_reached'])

    def test_cache_epoch_mismatch_exposed_not_complete(self):
        _, e = sample()
        e['pages'][0]['source_type'] = 'search_index'
        e['pages'][1]['source_type'] = 'search_index'
        e['pages'][0]['indexed_at'] = '2026-10-28T08:00:00+08:00'
        e['pages'][1]['indexed_at'] = '2026-10-29T09:00:00+08:00'
        e.pop('first_page_recheck')
        result = validate_coverage(e, LIB, '2026-10-23', False, strict=True)
        self.assertFalse(result['date_boundary_reached'])
        self.assertIn('MIXED_CACHE_EPOCHS',result['diagnostics']['issues'])
        self.assertGreater(result['diagnostics']['cache_index_span_seconds'], 3600)
        with self.assertRaisesRegex(ValueError, '完整核對'):
            validate_coverage(e, LIB, '2026-10-23', True, strict=True)

    def test_duplicate_page_fingerprint_cannot_be_complete(self):
        _, e = sample()
        e['pages'][1]['content_digest'] = e['pages'][0]['content_digest']
        with self.assertRaisesRegex(ValueError, '完整核對'):
            validate_coverage(e, LIB, '2026-10-23', True, strict=True)

    def test_schema2_update_pipeline_and_failure_code(self):
        rows, e = sample()
        conf, _ = initialize()
        batch={'schema':2,'source':'chatgpt_assisted','batch_id':'v15-test-valid-001',
               'window_start':'2026-10-23','window_end':'2026-10-30',
               'libraries':[{'id':LIB,'status':'complete','attempts':1,
                 'retry_wait_seconds':[],'notes':'本次直接讀取連續兩頁',
                 'coverage':e,'records':rows},
                {'id':'tnml','status':'failed','attempts':1,'retry_wait_seconds':[],
                 'error_code':'TOOL_UNAVAILABLE',
                 'error':'讀取工具無法開啟；未取得 HTTP 狀態碼','records':[]}]}
        normalized=validate_batch(batch,conf)
        self.assertEqual(normalized['libraries']['tnml']['error_code'],'TOOL_UNAVAILABLE')
        report=apply_batch(batch,persist=False,stamp=T2)
        self.assertEqual(report['summary']['error_code_counts']['TOOL_UNAVAILABLE'],1)
        self.assertEqual(report['summary']['successful'],1)
        self.assertEqual(report['summary']['failed'],1)
        self.assertEqual(report['summary']['cached_pages'],0)
        self.assertEqual(report['libraries'][1]['error_code'] if report['libraries'][1]['id']=='tnml'
                         else next(x['error_code'] for x in report['libraries'] if x['id']=='tnml'),
                         'TOOL_UNAVAILABLE')

    def test_schema2_bad_source_not_accepted_as_complete(self):
        rows, e = sample()
        conf,_ = initialize()
        rows[0]['source_url'] = 'https://tpml.ebook.hyread.com.tw/index.jsp'
        batch={'schema':2,'source':'chatgpt_assisted','batch_id':'v15-test-badsrc-001',
               'window_start':'2026-10-23','window_end':'2026-10-30',
               'libraries':[{'id':LIB,'status':'complete','attempts':1,
                 'retry_wait_seconds':[],'notes':'測試不合規來源',
                 'coverage':e,'records':rows}]}
        with self.assertRaisesRegex(ValueError, '來源不在本次'):
            validate_batch(batch,conf)

    def test_schema1_legacy_remains_importable(self):
        _, e=sample()
        e.pop('scan_id')
        e.pop('first_page_recheck')
        for page in e['pages']:
            page.pop('scan_id')
            page.pop('content_digest')
            page.pop('record_count')
        self.assertTrue(validate_coverage(e, LIB,'2026-10-23',True)['date_boundary_reached'])

    def test_invalid_http_status_and_code_are_rejected(self):
        _, e=sample()
        e['pages'][0]['http_status']=999
        with self.assertRaisesRegex(ValueError,'http_status'):
            validate_coverage(e,LIB,'2026-10-23',False,strict=True)
        e['pages'][0].pop('http_status')
        e['pages'][1]['error_code']='HYPOTHETICAL_403'
        with self.assertRaisesRegex(ValueError,'error_code'):
            validate_coverage(e,LIB,'2026-10-23',False,strict=True)


if __name__ == '__main__':
    unittest.main()
