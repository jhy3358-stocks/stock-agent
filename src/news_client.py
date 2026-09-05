"""미국 종목 뉴스 수집 (Yahoo Finance, Seeking Alpha — 둘 다 로그인 불필요).

Seeking Alpha는 공개 RSS 피드(개인/비상업적 용도 명시 허용)를 사용한다.
"""
from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree

import requests
import yfinance as yf

SEEKING_ALPHA_RSS_URL = "https://seekingalpha.com/api/sa/combined/{ticker}.xml"
SA_HEADERS = {"User-Agent": "Mozilla/5.0 (stock-agent personal use RSS reader)"}


def fetch_yahoo_news(ticker: str, limit: int = 3, hours: int = 24) -> List[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    raw_items = yf.Ticker(ticker).news or []
    news = []
    for raw in raw_items:
        content = raw.get("content", {})
        pub_date = _parse_iso_datetime(content.get("pubDate"))
        if pub_date is None or pub_date < cutoff:
            continue
        url = (content.get("canonicalUrl") or {}).get("url") or (
            content.get("clickThroughUrl") or {}
        ).get("url")
        news.append(
            {
                "title": content.get("title", ""),
                "url": url,
                "date": pub_date,
                "source": "Yahoo Finance",
            }
        )
        if len(news) >= limit:
            break
    return news


def fetch_seekingalpha_news(ticker: str, limit: int = 3, hours: int = 24) -> List[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    response = requests.get(
        SEEKING_ALPHA_RSS_URL.format(ticker=ticker), headers=SA_HEADERS, timeout=15
    )
    if response.status_code != 200:
        return []
    root = ElementTree.fromstring(response.content)
    news = []
    for item in root.findall(".//item"):
        pub_date = _parse_rfc822_datetime(item.findtext("pubDate"))
        if pub_date is None or pub_date < cutoff:
            continue
        news.append(
            {
                "title": item.findtext("title", ""),
                "url": item.findtext("link"),
                "date": pub_date,
                "source": "Seeking Alpha",
            }
        )
        if len(news) >= limit:
            break
    return news


# 최종적으로는 두 소스를 합쳐 최신순 상위 limit개만 남기므로, 소스별로는
# 넉넉히 모아둔다 (너무 적게 모으면 한쪽 소스 기사가 실제로는 더 최신인데도
# 개수 제한에 걸려 후보에서 빠질 수 있다).
_SOURCE_POOL_SIZE = 10


def get_recent_news_for_tickers(
    tickers: List[str], limit: int = 3, hours: int = 24
) -> dict:
    result = {}
    for ticker in tickers:
        yahoo = fetch_yahoo_news(ticker, _SOURCE_POOL_SIZE, hours)
        seeking_alpha = fetch_seekingalpha_news(ticker, _SOURCE_POOL_SIZE, hours)
        combined = sorted(yahoo + seeking_alpha, key=lambda n: n["date"], reverse=True)
        result[ticker] = combined[:limit]
    return result


def _parse_iso_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_rfc822_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
