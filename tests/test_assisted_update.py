import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import assisted_update as au
from src.update import initialize


def sample_batch():
    return {'schema':1,'source':'chatgpt_assisted','batch_id':'manual-20261106-a',
            'window_start':'2026-10-23','window_end':'2026-11-06',
            'libraries':[
                {'id':'tpml','status':'partial','attempts':3,'retry_wait_seconds':[3.2,8.4],
                 'notes':'只查到新聞類與財經類；其他分類頁無法讀取。',
                 'records':[{'title':'測試新雜誌','date':'2026-11-06',
                             'source_url':'https://tpml.ebook.hyread.com.tw/Template/RWD3.0/magazine.jsp'}]},
                {'id':'tnml','status':'failed','attempts':1,'retry_wait_seconds':[],
                 'error':'HTTP 403：來源禁止存取，不再重試。','records':[]},
            ]}


class AssistedUpdateTests(unittest.TestCase):
    def test_partial_positive_only_existing_books_unchanged(self):
        conf, state=initialize()
        original=copy.deepcopy(state['libraries']['tpml']['items'])
        incoming={'foo':{'title':'測試新雜誌','date':'2026-11-06','source_url':'https://tpml.ebook.hyread.com.tw/a'}}
        events=au.merge_incremental(state, {'id':'tpml'}, incoming, '2026-11-06T09:00:00+08:00')
        self.assertEqual(events[0]['type'],'new')
        self.assertTrue(all(state['libraries']['tpml']['items'][k]==value for k,value in original.items()))
        self.assertEqual(len(state['libraries']['tpml']['items']),len(original)+1)

    def test_batch_validates_retries_and_sources(self):
        conf,_=initialize()
        b=sample_batch()
        b['libraries'][0]['attempts']=4
        with self.assertRaisesRegex(ValueError,'嘗試次數'): au.validate_batch(b, conf)
        b=sample_batch()
        b['libraries'][0]['records'][0]['source_url']='https://example.com/hi'
        with self.assertRaisesRegex(ValueError,'來源網址'): au.validate_batch(b, conf)

    def test_reject_failed_with_observations(self):
        conf,_=initialize()
        b=sample_batch()
        b['libraries'][1]['records']=[b['libraries'][0]['records'][0]]
        with self.assertRaisesRegex(ValueError,'失敗館'): au.validate_batch(b, conf)

    def test_dry_run_does_not_write_and_has_correct_status(self):
        b=sample_batch()
        stamp='2026-11-06T09:00:00+08:00'
        report=au.apply_batch(b, persist=False, stamp=stamp)
        self.assertEqual(report['summary']['new_titles'],1)
        self.assertEqual(report['summary']['partial'],1)
        self.assertEqual(report['summary']['failed'],1)
        self.assertEqual(report['summary']['not_checked'],7)
        self.assertEqual(report['summary']['not_listed'],0)
        self.assertFalse(report['complete'])
        self.assertIsNone(next(l for l in report['libraries'] if l['id']=='tnml')['verified_count'])
        self.assertEqual(next(l for l in report['libraries'] if l['id']=='tpml')['attempts'],3)
        self.assertEqual(report['libraries'][0]['status'],'not_checked')
        self.assertEqual(next(l for l in report['libraries'] if l['id']=='tpml')['status'],'partial')
        self.assertEqual(next(l for l in report['libraries'] if l['id']=='tnml')['status'],'stale')

    def test_no_fake_missing_increment_or_old_date_downgrade(self):
        conf,state=initialize()
        lib={'id':'tpml'}
        k=next(iter(state['libraries']['tpml']['items']))
        old=state['libraries']['tpml']['items'][k]
        older={'title':old['title'],'date':'2026-09-20','source_url':'https://tpml.ebook.hyread.com.tw/a'}
        au.merge_incremental(state,lib,{k:older},'2026-11-06T09:00:00+08:00')
        self.assertEqual(state['libraries']['tpml']['items'][k]['latest_date'],old['latest_date'])
        self.assertEqual(state['libraries']['tpml']['items'][k]['misses'],0)

    def test_duplicate_batch_refused(self):
        b=sample_batch()
        with patch.object(au,'load',side_effect=lambda path,default: {'batch_id':b['batch_id'],'history':[]} if path==au.REPORT else default):
            with self.assertRaisesRegex(ValueError,'重複'):au.apply_batch(b,persist=False)

if __name__=='__main__': unittest.main()
