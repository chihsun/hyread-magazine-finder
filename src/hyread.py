"""Fetch public HyRead magazine metadata; do not attempt login or bypass access limits.

We fetch 12 complete category pages instead of depending on fragile latest-issue
pagination. Any incomplete category rejects the *whole* library's current scan.
The three retries are a *per-library budget*, NOT three retries per page.
"""
from __future__ import annotations
from dataclasses import dataclass
import datetime as dt
import re
import random
import time
import unicodedata
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CATEGORY_LABELS = [
    '新聞新知','財經商管','數位資訊','語言學習','親子教育','生活居家',
    '旅遊行腳','時尚風格','影視娛樂','知識專業','人文藝術','休閒運動',
]
DATE_RE = re.compile(r'(20\d{2})[-/.]([01]?\d)[-/.]([0-3]?\d)')
LATEST_RE = re.compile(r'最新發刊\s*[:：]?|最新刊\s*[:：]?')


class AccessDeniedError(RuntimeError):
    """The source explicitly denied access; do not retry or disguise the client."""


class RateLimitPause(RuntimeError):
    """A source requested a longer cooling period than one job can safely wait."""


class RetryableRateLimit(RuntimeError):
    """HTTP 429, with an optional Retry-After delay in seconds."""

    def __init__(self, seconds: float | None):
        self.seconds = seconds
        super().__init__('HTTP 429 Too Many Requests')


RETRY_WINDOWS = ((2.0, 5.0), (5.0, 10.0), (10.0, 20.0))
MAX_RETRY_AFTER = 60.0   # Stop this library rather than ignore a longer server cooling period.


def retry_after_seconds(value: str | None) -> float | None:
    """Parse HTTP Retry-After in delta-seconds or RFC 7231 date format."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (date - dt.datetime.now(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def key(title: str) -> str:
    """Normalize typography but do *not* merge ordinary and abridged editions."""
    s=unicodedata.normalize('NFKC',title).casefold().replace('臺','台')
    return re.sub(r'\s+','',s).replace('（','(').replace('）',')')


def extract_category(html: bytes | str, url: str, category: str) -> list[dict]:
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text('\n',strip=True)
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    # Navigation contains category names but no latest issues; a genuine category
    # page has its heading and a repeated latest-publication marker per issue.
    if not any(re.search(re.escape(category)+r'\s*\(\s*\d+\s*\)',v) for v in lines):
        raise ValueError(f'分類「{category}」標題不存在（可能是阻擋頁）')
    dates=[]
    for i,line in enumerate(lines):
        if not LATEST_RE.search(line):
            continue
        m=DATE_RE.search(' '.join(lines[i:i+2]))
        if not m or i<1:
            continue
        try:
            day=dt.date(int(m.group(1)),int(m.group(2)),int(m.group(3))).isoformat()
        except ValueError:
            raise ValueError(f'無效日期: {line}')
        title=lines[i-1]
        if not title or len(title)>180 or title.startswith(('最新','雜誌類型','新刊')):
            raise ValueError(f'無法辨識標題: {title}')
        dates.append({'title':title,'date':day,'source_url':url})
    if not dates:
        # Some empty categories exist; reject pages listing catalog entries but
        # missing dates, because treating them as empty would erase coverage.
        match=next((re.search(re.escape(category)+r'\s*\(\s*(\d+)\s*\)',v) for v in lines if re.search(re.escape(category)+r'\s*\(\s*\d+\s*\)',v)),None)
        if not match or int(match.group(1))>0:
            raise ValueError('分類頁沒有最新發刊日期')
    result={}
    for row in dates:
        k=key(row['title'])
        if k not in result or row['date']>result[k]['date']:
            result[k]=row
    return list(result.values())


@dataclass
class LibraryScanner:
    host: str
    retries: int = 3   # maximum ADDITIONAL attempts shared by all requests for a library
    timeout: int = 18
    delay: float | tuple[float, float] = (1.5, 3.5)
    session: requests.Session | None = None

    def __post_init__(self):
        self.session=self.session or requests.Session()
        self.session.headers.update({
            'User-Agent':'Mozilla/5.0 (compatible; HyReadCatalogIndex/1.0; public metadata only)',
            'Accept-Language':'zh-TW,zh;q=0.9,en;q=0.7',
        })
        self.used_retries=0
        self.requests_made=0

    def _wait_retry(self, hint: float | None = None):
        """Randomized backoff only for transient failures; honor server Retry-After."""
        low, high = RETRY_WINDOWS[min(self.used_retries, len(RETRY_WINDOWS)) - 1]
        seconds = random.uniform(low, high)
        if hint is not None:
            seconds = max(seconds, hint)
        time.sleep(seconds)

    def _wait_between_categories(self):
        if isinstance(self.delay, tuple):
            seconds = random.uniform(*self.delay)
        else:
            seconds = float(self.delay)
        if seconds > 0:
            time.sleep(seconds)

    def fetch(self,url):
        while True:
            self.requests_made+=1
            try:
                r=self.session.get(url,timeout=self.timeout)
                # HTTP 401/403 is an explicit denial, not a transient error.
                # Do not repeatedly request a blocked endpoint.
                if r.status_code in (401, 403):
                    raise AccessDeniedError(
                        f'HyRead 回應 HTTP {r.status_code}，拒絕此執行環境存取；'
                        f'已停止重試。請使用取得授權的官方資料來源。{url}'
                    )
                if r.status_code == 429:
                    hint = retry_after_seconds(r.headers.get('Retry-After'))
                    if hint is not None and hint > MAX_RETRY_AFTER:
                        raise RateLimitPause(
                            f'HyRead 回應 HTTP 429，要求至少等待 {hint:.0f} 秒；'
                            '本次停止核對以遵守 Retry-After。'
                        )
                    raise RetryableRateLimit(hint)
                r.raise_for_status()
                if len(r.content)<900:
                    raise ValueError('回應頁面異常短')
                return r.content
            except (AccessDeniedError, RateLimitPause):
                raise
            except (requests.RequestException, ValueError, RetryableRateLimit) as e:
                if self.used_retries>=self.retries:
                    raise RuntimeError(f'全館重試額度已用盡({self.retries}次): {url}: {e}') from e
                self.used_retries+=1
                self._wait_retry(e.seconds if isinstance(e, RetryableRateLimit) else None)

    def scan(self):
        records={}
        for no,cat in enumerate(CATEGORY_LABELS,1):
            url=f'https://{self.host}.ebook.hyread.com.tw/Template/RWD3.0/magazine-list.jsp?magazineclass=M{no:02}'
            # A page that downloads but fails to parse also consumes the shared retry budget.
            while True:
                try:
                    batch=extract_category(self.fetch(url),url,cat)
                    break
                except (AccessDeniedError, RateLimitPause):
                    raise
                except Exception:
                    if self.used_retries>=self.retries:
                        raise
                    self.used_retries+=1
                    self._wait_retry()
            for rec in batch:
                k=key(rec['title'])
                if k not in records or rec['date']>records[k]['date']:
                    records[k]=rec
            if no<len(CATEGORY_LABELS):
                self._wait_between_categories()
        if len(records)<30:
            raise ValueError(f'擷取總量僅{len(records)}筆，低於可信門檻30')
        return records
