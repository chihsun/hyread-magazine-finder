"""V1.5 provenance diagnostics for ChatGPT-assisted HyRead observations.

This module is offline: it never fetches HyRead or upgrades cached/search
results into a verified direct capture. A scan_id groups observations but does
not itself prove a server-side snapshot.
"""
from __future__ import annotations

from datetime import datetime
import re

ERROR_CODES = frozenset({
    'ACCESS_DENIED', 'RATE_LIMITED', 'TIMEOUT', 'NETWORK_ERROR',
    'SERVER_ERROR', 'PARSER_ERROR', 'PAGE_MISSING', 'SNAPSHOT_DRIFT',
    'CACHE_ONLY', 'STALE_CACHE', 'DATE_BOUNDARY_NOT_REACHED',
    'TOOL_UNAVAILABLE', 'UNKNOWN',
})
ID_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{6,96}$')
DIGEST_PATTERN = re.compile(r'^[a-f0-9]{64}$')


def timestamp(value: str, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f'{label} 必須是含時區的 ISO 時間')
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise ValueError(f'{label} 必須是含時區的 ISO 時間') from None


def scan_id(value: str | None) -> str | None:
    if value is not None and (not isinstance(value, str) or not ID_PATTERN.fullmatch(value)):
        raise ValueError('scan_id 必須是 6–96 字元英數、-、_ 或 .')
    return value


def digest(value: str | None, label: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value)):
        raise ValueError(f'{label} 必須是 SHA-256 十六進位摘要')
    return value


def error_code(value: str | None) -> str | None:
    if value is not None and value not in ERROR_CODES:
        raise ValueError('error_code 不在允許的診斷代碼中')
    return value


def summarize_evidence(payload: dict, pages: list[dict], method: str, *,
                       strict: bool = False) -> tuple[dict, bool]:
    """Return inspectable diagnostics plus V1.5 complete-readiness.

    Strict mode is used for schema 2. Schema 1 remains readable for older
    reports, but must never be retroactively advertised as V1.5 evidence.
    """
    group = scan_id(payload.get('scan_id'))
    issues: list[str] = []
    def flag(issue: str) -> None:
        if issue not in issues:
            issues.append(issue)

    successful = [p for p in pages if p['status'] == 'ok']
    direct = [p for p in successful if p['source_type'] == 'direct']
    cached = [p for p in successful if p['source_type'] == 'search_index']
    dates = [timestamp(p['observed_at'], 'observed_at') for p in pages]
    observed_span = int((max(dates) - min(dates)).total_seconds()) if dates else None
    page_numbers = {p['page'] for p in pages}
    missing = [n for n in range(1, max(page_numbers) + 1) if n not in page_numbers] if page_numbers else []
    if missing:
        flag('PAGE_MISSING')
    if cached:
        flag('CACHE_ONLY')
    if any(p['status'] == 'failed' for p in pages):
        flag('PAGE_FAILED')
    if observed_span is not None and observed_span > (600 if strict else 3600):
        flag('CAPTURE_SPAN_EXCEEDED')
    ids = {p.get('scan_id') for p in pages}
    if group and any(x != group for x in ids):
        flag('SCAN_ID_MISMATCH')
    if strict and (not group or any(x != group for x in ids)):
        flag('SCAN_ID_MISSING_OR_MISMATCHED')

    hashes = [p.get('content_digest') for p in successful if p.get('content_digest')]
    if len(hashes) != len(set(hashes)):
        flag('DUPLICATE_PAGE_CONTENT')
    if strict and any(not p.get('content_digest') or not p.get('record_count') for p in successful):
        flag('PAGE_FINGERPRINT_MISSING')

    indexed = [timestamp(p['indexed_at'], 'indexed_at') for p in cached if p.get('indexed_at')]
    indexed_span = int((max(indexed) - min(indexed)).total_seconds()) if len(indexed) > 1 else 0 if indexed else None
    if cached and len(indexed) != len(cached):
        flag('CACHE_TIMESTAMP_UNKNOWN')
    if indexed_span is not None and indexed_span > 600:
        flag('MIXED_CACHE_EPOCHS')
    if any((timestamp(p['observed_at'], 'observed_at') - timestamp(p['indexed_at'], 'indexed_at')).total_seconds() > 86400
           for p in cached if p.get('indexed_at')):
        flag('STALE_CACHE')

    recheck = payload.get('first_page_recheck')
    stable = None
    if recheck is not None:
        if not isinstance(recheck, dict):
            raise ValueError('first_page_recheck 必須是物件')
        recheck_time = timestamp(recheck.get('observed_at'), 'first_page_recheck.observed_at')
        recheck_hash = digest(recheck.get('content_digest'), 'first_page_recheck.content_digest')
        recheck_group = scan_id(recheck.get('scan_id'))
        page1 = next((p for p in direct if p['page'] == 1), None)
        stable = bool(page1 and recheck.get('source_type') == 'direct'
                      and recheck_group == group
                      and page1.get('content_digest') and recheck_hash == page1['content_digest']
                      and dates and recheck_time >= max(dates)
                      and (recheck_time - min(dates)).total_seconds() <= 600)
        if not stable:
            flag('SNAPSHOT_DRIFT_OR_RECHECK_INVALID')
    elif strict and method == 'latest_pages':
        flag('FIRST_PAGE_RECHECK_MISSING')

    strict_ready = not issues if strict else True
    # A cached-only or failed capture is never complete, regardless of mode.
    if cached or any(p['status'] != 'ok' for p in pages):
        strict_ready = False
    diag = {
        'scan_id': group,
        'source_types': {'direct': len(direct), 'search_index': len(cached)},
        'observed_span_seconds': observed_span,
        'cache_index_span_seconds': indexed_span,
        'first_page_stable': stable,
        'missing_pages': missing,
        'issues': issues,
    }
    return diag, strict_ready
