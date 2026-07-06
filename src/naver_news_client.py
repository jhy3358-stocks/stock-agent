"""국내 종목 뉴스 수집 (네이버 뉴스 검색 API, 무료 인증키 필요)."""
from __future__ import annotations

import datetime as dt
import html
import re
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import requests

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw: str) -> str:
    return html.unescape(_TAG_RE.sub("", raw))


def _parse_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def fetch_naver_news(
    client_id: str, client_secret: str, query: str, limit: int = 3, days: int = 2
) -> List[dict]:
    cutoff = dt.date.today() - dt.timedelta(days=days)
    response = requests.get(
        NAVER_NEWS_URL,
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
        params={"query": query, "display": 20, "sort": "date"},
        timeout=15,
    )
    response.raise_for_status()

    news = []
    for item in response.json().get("items", []):
        pub_date = _parse_date(item.get("pubDate"))
        if pub_date is None or pub_date < cutoff:
            continue
        news.append(
            {
                "title": _clean_text(item.get("title", "")),
                "url": item.get("originallink") or item.get("link"),
                "date": pub_date,
                "source": "네이버 뉴스",
            }
        )
        if len(news) >= limit:
            break
    return news


def get_recent_news_for_stocks(
    client_id: str, client_secret: str, stock_names: Dict[str, str], limit: int = 3, days: int = 2
) -> Dict[str, List[dict]]:
    """{종목코드: 종목명} 매핑을 받아 {종목코드: 뉴스목록}을 반환한다."""
    return {
        code: fetch_naver_news(client_id, client_secret, name, limit, days)
        for code, name in stock_names.items()
    }
