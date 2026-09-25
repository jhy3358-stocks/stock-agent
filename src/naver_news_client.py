"""국내 종목 뉴스 수집 (네이버 뉴스 검색 API, 무료 인증키 필요)."""
from __future__ import annotations

import html
import re
from typing import Dict, List

import requests

from src.concurrency import fetch_all
from src.news_client import newest_first, parse_rfc822_datetime, recent_cutoff

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(raw: str) -> str:
    return html.unescape(_TAG_RE.sub("", raw))


def fetch_naver_news(
    client_id: str,
    client_secret: str,
    query: str,
    limit: int = 3,
    hours: int = 24,
    require_query_in_title: bool = False,
) -> List[dict]:
    """require_query_in_title=True면 제목에 검색어가 들어간 기사만 남긴다.
    네이버는 본문에 검색어가 한 번만 나와도 결과에 넣어서, 지수명("코스피")
    검색에 연예 기사 등 무관한 기사가 섞이는 것을 막기 위한 옵션이다."""
    cutoff = recent_cutoff(hours)
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
        pub_date = parse_rfc822_datetime(item.get("pubDate"))
        if pub_date is None or pub_date < cutoff:
            continue
        title = _clean_text(item.get("title", ""))
        if require_query_in_title and query not in title:
            continue
        news.append(
            {
                "title": title,
                "url": item.get("originallink") or item.get("link"),
                "date": pub_date,
                "source": "네이버 뉴스",
            }
        )
    return newest_first(news)[:limit]


def get_recent_news_for_stocks(
    client_id: str,
    client_secret: str,
    stock_names: Dict[str, str],
    limit: int = 3,
    hours: int = 24,
    require_query_in_title: bool = False,
) -> Dict[str, List[dict]]:
    """{종목코드: 종목명} 매핑을 받아 {종목코드: 뉴스목록}을 반환한다."""
    return fetch_all(
        stock_names,
        lambda code: fetch_naver_news(
            client_id, client_secret, stock_names[code], limit, hours, require_query_in_title
        ),
        what="네이버 뉴스",
        default=[],
        max_workers=4,
    )
