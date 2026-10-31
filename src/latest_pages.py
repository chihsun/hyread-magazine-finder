"""Offline, verified parsing for the preferred HyRead '最新出刊' page series.

Pass HTML legitimately obtained from a source: this module does not fetch pages,
change network identity, or bypass an HTTP 403. Its evidence can be embedded in
an assisted update batch, whose completeness is checked by src.coverage.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
from urllib.parse import parse_qs, urlparse

from .hyread import extract_latest_page, key
from .coverage import official_url
from .scan_evidence import scan_id as check_scan_id, timestamp as check_timestamp


def requested_window(days: int, today: date | None = None) -> tuple[str,str]:
    """Exactly N inclusive calendar days in Taiwan; no automatic overlap."""
    if type(days) is not int or not 1 <= days <= 366:
        raise ValueError('查詢天數須為 1–366 天')
    today = today or datetime.now(ZoneInfo('Asia/Taipei')).date()
    return ((today-timedelta(days=days-1)).isoformat(),today.isoformat())


def library_groups(libraries: list[dict], size: int = 2) -> list[list[dict]]:
    """Plan sequential small batches of libraries for a ChatGPT-assisted scan.

    Return consecutive groups in the configured order. This is a planning
    helper, not a concurrent scraper and makes no network requests.
    """
    if type(size) is not int or size < 1:
        raise ValueError('每組館數須為正整數')
    return [libraries[i:i+size] for i in range(0, len(libraries), size)]


def latest_page_url(library_id: str, page: int) -> str:
    if type(page) is not int or not 1 <= page <= 200:
        raise ValueError('最新出刊頁碼須為 1–200')
    return (f'https://{library_id}.ebook.hyread.com.tw/Template/RWD3.0/'
            f'magazine_view_more.jsp?nowpage={page}')


def inspect_latest_html(html: str | bytes, library_id: str, page: int,
                        observed_at: str, source_type: str = 'direct', *,
                        scan_id: str | None = None, indexed_at: str | None = None) -> tuple[list[dict], dict]:
    """Extract observed titles, issue dates, individual jid links and page evidence.

    Callers must label search-engine caches as `search_index`, never `direct`.
    In-page issue date order is verified before a page can support a boundary.
    """
    if source_type not in ('direct','search_index'):
        raise ValueError('source_type 必須是 direct 或 search_index')
    try:
        d=datetime.fromisoformat(observed_at)
        if d.tzinfo is None:raise ValueError()
    except (TypeError,ValueError):
        raise ValueError('observed_at 必須是含時區的實際觀察時間') from None
    check_scan_id(scan_id)
    if indexed_at is not None:
        if source_type != 'search_index':
            raise ValueError('indexed_at 僅能用於搜尋索引')
        check_timestamp(indexed_at, 'indexed_at')
    url=latest_page_url(library_id,page)
    official_url(url,library_id)
    records=extract_latest_page(html,url)
    if not records:
        raise ValueError('最新出刊頁面沒有可辨識的書名與刊期，不能當成已核對頁面')
    dates=[x['date'] for x in records]
    if dates!=sorted(dates,reverse=True):
        raise ValueError('最新出刊頁面的日期並未由新至舊排序，不能用來判斷日期界線')
    # Digest page records (not the response time) so a later page-1 recheck
    # can detect drift even if HTML presentation has changed slightly.
    normalized=[{'title':key(x['title']),'date':x['date'],
                 'magazine_url':x.get('magazine_url')} for x in records]
    fingerprint=hashlib.sha256(json.dumps(normalized,ensure_ascii=False,
                                         sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    evidence={'page':page,'url':url,'status':'ok','source_type':source_type,
              'observed_at':observed_at,'newest_date':dates[0], 'oldest_date':dates[-1],
              'content_digest':fingerprint,'record_count':len(records)}
    if scan_id is not None: evidence['scan_id']=scan_id
    if indexed_at is not None: evidence['indexed_at']=indexed_at
    return records,evidence


def build_latest_observations(pages: list[tuple[list[dict],dict]], window_start: str,
                              window_end: str, *, scan_id: str | None = None,
                              first_page_recheck: dict | None = None) -> tuple[list[dict],dict]:
    """Combine all issues on scanned pages dated on/after window_start.

    window_end is the user's scan reference date, NOT an issue-date ceiling:
    HyRead e-magazines can appear before the printed issue date. Older
    publications outside the requested lookback are omitted.
    Completeness is validated separately by src.coverage.
    """
    if not pages: raise ValueError('未提供任何最新出刊頁面')
    mapping={}
    evidence=[]
    first_book=None
    for rows,meta in sorted(pages,key=lambda x:x[1]['page']):
        evidence.append(meta)
        if meta['page']==1 and rows:
            first=rows[0]
            url=first.get('magazine_url')
            jid=parse_qs(urlparse(url).query).get('jid',[None])[0] if url else None
            first_book={'title':first['title'],'date':first['date'],
                        'magazine_url':url,'jid':jid,
                        'source_url':meta['url']}
            if url and first.get('link_evidence'):
                first_book['link_evidence']=first['link_evidence']
        for row in rows:
            # Only the start date limits accepted issue dates. The reference
            # day (window_end) is NOT an upper bound on printed issue dates.
            # Do not infer absence or removal from missing observations.
            if row['date'] < window_start:
                continue
            k=key(row['title'])
            if k not in mapping or mapping[k]['date']<row['date'] or (
                    mapping[k]['date']==row['date'] and not mapping[k].get('magazine_url') and row.get('magazine_url')):
                mapping[k]=row
    sorted_pages=sorted(evidence,key=lambda x:x['page'])
    contiguous=[x['page'] for x in sorted_pages]==list(range(1,len(sorted_pages)+1))
    reached=contiguous and sorted_pages[-1]['oldest_date']<=window_start
    coverage={'method':'latest_pages','pages':sorted_pages,
              'pagination_contiguous':contiguous,'date_boundary_reached':reached}
    if first_book is not None: coverage['first_book']=first_book
    if scan_id is not None:
        coverage['scan_id']=check_scan_id(scan_id)
    if first_page_recheck is not None:
        # Call inspect_latest_html again for page 1, after collecting the last
        # page; supply the returned evidence here, not a search result snippet.
        coverage['first_page_recheck']={
            k:first_page_recheck[k] for k in ('source_type','observed_at','content_digest','scan_id')
            if k in first_page_recheck
        }
    return list(mapping.values()),coverage
