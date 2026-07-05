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


def fetch_yahoo_news(ticker: str, limit: int = 3) -> List[dict]:
    raw_items = yf.Ticker(ticker).news or []
    news = []
    for raw in raw_items[:limit]:
        content = raw.get("content", {})
        pub_date_str = content.get("pubDate")
        pub_date = _parse_iso_date(pub_date_str)
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
    return news


def fetch_seekingalpha_news(ticker: str, limit: int = 3) -> List[dict]:
    response = requests.get(
        SEEKING_ALPHA_RSS_URL.format(ticker=ticker), headers=SA_HEADERS, timeout=15
    )
    if response.status_code != 200:
        return []
    root = ElementTree.fromstring(response.content)
    news = []
    for item in root.findall(".//item")[:limit]:
        pub_date_raw = item.findtext("pubDate")
        news.append(
            {
                "title": item.findtext("title", ""),
                "url": item.findtext("link"),
                "date": _parse_rfc822_date(pub_date_raw),
                "source": "Seeking Alpha",
            }
        )
    return news


def get_recent_news_for_tickers(tickers: List[str], limit_per_source: int = 3) -> dict:
    result = {}
    for ticker in tickers:
        yahoo = fetch_yahoo_news(ticker, limit_per_source)
        seeking_alpha = fetch_seekingalpha_news(ticker, limit_per_source)
        result[ticker] = yahoo + seeking_alpha
    return result


def _parse_iso_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_rfc822_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None
