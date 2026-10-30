"""Validate source provenance, pagination coverage, and per-library HyRead magazine links.

This module performs no network requests. A search result, cached index or a
claimed page number cannot by itself establish complete date-range coverage.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import parse_qs, urlparse
from .scan_evidence import (summarize_evidence, scan_id as check_scan_id,
                            digest as check_digest, error_code as check_error_code,
                            timestamp as check_timestamp)


def official_url(value: str, library_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError('必須附上有效的 HyRead 官方來源網址')
    u = urlparse(value)
    if (u.scheme != 'https' or u.hostname != f'{library_id}.ebook.hyread.com.tw'
            or u.username or u.password or u.port not in (None, 443)):
        raise ValueError(f'來源網址與圖書館不符：{value}')
    return value


def magazine_url(value: str | None, library_id: str) -> str | None:
    """Only preserve a real, library-specific magazine_more.jsp?jid=N URL.

    Do not infer a jid from a title or a catalog/category page.
    """
    if value is None or value == '':
        return None
    official_url(value, library_id)
    u = urlparse(value)
    query = parse_qs(u.query, keep_blank_values=True)
    if (u.path != '/Template/RWD3.0/magazine_more.jsp' or u.fragment
            or set(query) != {'jid'} or len(query['jid']) != 1
            or not query['jid'][0].isascii() or not query['jid'][0].isdigit()
            or not 1 <= len(query['jid'][0]) <= 16):
        raise ValueError(f'雜誌詳細網址必須是該館 magazine_more.jsp?jid=數字：{value}')
    return f'https://{library_id}.ebook.hyread.com.tw/Template/RWD3.0/magazine_more.jsp?jid={query["jid"][0]}'


def _iso_date(value: str) -> str:
    try:
        if not isinstance(value, str) or len(value) != 10 or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('分頁日期須為 YYYY-MM-DD') from None
    return value


def validate_coverage(payload: dict | None, library_id: str, window_start: str,
                      completed: bool, *, strict: bool = False, simple: bool = False) -> dict:
    """Validate claimed coverage, refusing unproven complete checks.

    Date boundary proof requires consecutive direct-source pages, starting at 1,
    observed in one scan with consistent date ordering and oldest <= lookback.
    A 12-category complete scan is also accepted if all categories were read.
    """
    if payload is None:
        if completed:
            raise ValueError(f'{library_id}: 完整核對必須提供 coverage 分頁與界線證據')
        return {'method':'unknown','pages':[],'date_boundary_reached':False,
                'pagination_contiguous':False,'checked_pages':0,'failed_pages':0}
    if not isinstance(payload, dict):
        raise ValueError('coverage 必須為物件')
    method = payload.get('method', 'search_index')
    if method not in ('latest_pages','categories','search_index'):
        raise ValueError(f'{library_id}: 不支援的 coverage method')
    pages = payload.get('pages', [])
    if not isinstance(pages, list) or len(pages) > 120:
        raise ValueError(f'{library_id}: pages 必須為最多 120 筆的陣列')
    verified=[]
    cleaned=[]
    for p in pages:
        if not isinstance(p, dict):
            raise ValueError(f'{library_id}: 分頁紀錄必須為物件')
        official_url(p.get('url'), library_id)
        page = p.get('page')
        if type(page) is not int or page < 1 or page > 200:
            raise ValueError(f'{library_id}: page 應為正整數')
        parsed_url=urlparse(p['url'])
        query=parse_qs(parsed_url.query,keep_blank_values=True)
        if method == 'latest_pages':
            page_values=query.get('nowpage')
            valid_path=parsed_url.path == '/Template/RWD3.0/magazine_view_more.jsp'
            valid_query=(not query and page==1) or (set(query)=={'nowpage'}
                         and page_values==[str(page)])
            if not valid_path or not valid_query or parsed_url.fragment:
                raise ValueError(f'{library_id}: 最新出刊分頁網址與頁碼不一致')
        elif method == 'categories':
            expected=f'M{page:02}'
            if (parsed_url.path != '/Template/RWD3.0/magazine-list.jsp'
                    or query.get('magazineclass') != [expected] or set(query)!={'magazineclass'}):
                raise ValueError(f'{library_id}: 分類分頁網址或頁碼不一致')
        status = p.get('status')
        if status not in ('ok','failed'):
            raise ValueError('分頁狀態必須是 ok 或 failed')
        source_type = p.get('source_type')
        if source_type not in ('direct','search_index'):
            raise ValueError('分頁來源必須是 direct 或 search_index')
        observed_at = p.get('observed_at')
        if not isinstance(observed_at, str):
            raise ValueError('分頁必須提供實際觀察時間')
        try:
            parsed = datetime.fromisoformat(observed_at)
            if parsed.tzinfo is None:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('分頁 observed_at 必須有時區') from None
        oldest = _iso_date(p['oldest_date']) if p.get('oldest_date') else None
        newest = _iso_date(p['newest_date']) if p.get('newest_date') else None
        if oldest and newest and oldest > newest:
            raise ValueError('分頁日期先後顛倒')
        if status == 'ok' and (not oldest or not newest) and method == 'latest_pages':
            raise ValueError('成功的最新出刊分頁須記錄最早及最晚刊期日期')
        category = p.get('category')
        if category is not None and (not isinstance(category,str) or category not in [f'M{i:02}' for i in range(1,13)]):
            raise ValueError('category 應為 M01..M12')
        record={'page':page,'url':p['url'],'status':status,'source_type':source_type,
                'observed_at':observed_at,'oldest_date':oldest,'newest_date':newest}
        if category: record['category']=category
        if p.get('error'): record['error']=str(p['error'])[:300]
        if 'scan_id' in p:
            record['scan_id']=check_scan_id(p['scan_id'])
        if 'content_digest' in p:
            record['content_digest']=check_digest(p['content_digest'], 'content_digest')
        if 'record_count' in p:
            if type(p['record_count']) is not int or p['record_count'] < 1 or p['record_count'] > 500:
                raise ValueError('record_count 應為 1–500 的整數')
            record['record_count']=p['record_count']
        if 'indexed_at' in p:
            check_timestamp(p['indexed_at'], 'indexed_at')
            if source_type != 'search_index':
                raise ValueError('indexed_at 僅適用於搜尋引擎索引')
            record['indexed_at']=p['indexed_at']
        if 'error_code' in p:
            record['error_code']=check_error_code(p['error_code'])
            if status == 'ok' and record['error_code']:
                raise ValueError('成功頁面不可設定 error_code')
        if 'http_status' in p:
            if type(p['http_status']) is not int or not 100 <= p['http_status'] <= 599:
                raise ValueError('http_status 必須是實際觀察到的 HTTP 狀態碼')
            record['http_status']=p['http_status']
        cleaned.append(record)
        if status == 'ok' and source_type == 'direct': verified.append(record)
    consecutive=(len({p['page'] for p in verified})==len(verified)
                 and sorted(p['page'] for p in verified)==list(range(1,len(verified)+1)))
    claimed_contiguous=payload.get('pagination_contiguous') is True
    claimed_boundary=payload.get('date_boundary_reached') is True
    direct_only=len(verified)==len(pages) and len(pages)>0
    ordered=all(a['newest_date'] >= b['newest_date'] and a['oldest_date'] >= b['oldest_date']
                for a,b in zip(sorted(verified,key=lambda x:x['page']),sorted(verified,key=lambda x:x['page'])[1:])
                if a['newest_date'] and b['newest_date'] and a['oldest_date'] and b['oldest_date'])
    # A complete observation must be from a coherent short-lived direct scan,
    # not a collection of unrelated search-engine caches from different days.
    scan_consistent=False
    if verified:
        times=[datetime.fromisoformat(x['observed_at']) for x in verified]
        scan_consistent=(max(times)-min(times)).total_seconds() <= 3600
    is_complete=False
    if method == 'latest_pages':
        ordered_pages=sorted(verified,key=lambda x:x['page'])
        is_complete=(scan_consistent and direct_only and consecutive and claimed_contiguous and claimed_boundary and ordered
                     and bool(ordered_pages) and ordered_pages[-1]['oldest_date'] <= window_start)
    elif method == 'categories':
        groups=[p.get('category') for p in verified]
        is_complete=(scan_consistent and direct_only and len(groups)==12 and len(set(groups))==12
                     and set(groups)=={f'M{i:02}' for i in range(1,13)})
    diagnostics, evidence_ok=summarize_evidence(payload,cleaned,method,strict=strict)
    if method == 'latest_pages' and strict:
        by_page=sorted(verified,key=lambda p:p['page'])
        if any(a['oldest_date'] < b['newest_date'] for a,b in zip(by_page,by_page[1:])):
            diagnostics['issues'].append('CROSS_PAGE_DATE_ORDER')
            evidence_ok=False
    if strict:
        is_complete=is_complete and evidence_ok
    elif any(x in diagnostics['issues'] for x in
             ('SCAN_ID_MISMATCH','DUPLICATE_PAGE_CONTENT','SNAPSHOT_DRIFT_OR_RECHECK_INVALID')):
        is_complete=False
    if simple:
        # V1.6: prefer operational usefulness over cross-snapshot guarantees.
        # A real page-by-page observation may be cached; only a continuous
        # series with enough publication-date coverage may be marked complete.
        # The cache warning stays in diagnostics but does not veto completion.
        readable=sorted([p for p in cleaned if p['status']=='ok'],
                        key=lambda p:p['page'])
        page_ids=[p['page'] for p in readable]
        uninterrupted=(bool(readable) and page_ids==list(range(1,len(readable)+1))
                       and len(readable)==len(cleaned))
        dates_ordered=all(
            a['newest_date'] >= b['newest_date'] and
            a['oldest_date'] >= b['oldest_date']
            for a,b in zip(readable,readable[1:])
        )
        is_complete=(method=='latest_pages' and uninterrupted and dates_ordered
                     and readable[-1]['oldest_date'] <= window_start)
        if not dates_ordered:
            diagnostics['issues'].append('CROSS_PAGE_DATE_ORDER')
        # A missing page number, an actual failed page, or an undetermined
        # last-page date must never accidentally become complete.
        if completed and not is_complete:
            raise ValueError(f'{library_id}: 最新出刊頁面未連續讀到要求日期，不能標示正常完成')
        first_page = next((p for p in readable if p['page']==1),None)
        return {'method':method,'pages':cleaned,
                'date_boundary_reached':is_complete,
                'pagination_contiguous':uninterrupted,
                'checked_pages':len(readable),
                'failed_pages':sum(p['status']=='failed' for p in cleaned),
                'direct_pages':len(verified),'diagnostics':diagnostics,
                'scan_id':diagnostics['scan_id'],
                'first_page_ok':bool(first_page),
                'first_book':payload.get('first_book'),
                'mode':'simple'}
    if completed and not is_complete:
        raise ValueError(f'{library_id}: 未達完整核對條件：缺頁、快取、日期界線或未完整檢查 12 分類')
    return {'method':method,'pages':cleaned,'date_boundary_reached':bool(is_complete),
            'pagination_contiguous':bool(is_complete if completed else consecutive and claimed_contiguous and direct_only),
            'checked_pages':sum(p['status']=='ok' for p in cleaned),
            'failed_pages':sum(p['status']=='failed' for p in cleaned),
            'direct_pages':len(verified),
            'diagnostics':diagnostics,'scan_id':diagnostics['scan_id']}
