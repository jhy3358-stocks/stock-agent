"""미국 종목 뉴스 수집 (Yahoo Finance, Seeking Alpha, Bloomberg — 모두 로그인 불필요).

Seeking Alpha는 공개 RSS 피드(개인/비상업적 용도 명시 허용)를 사용한다.
Bloomberg는 공식 무료 API가 없고 공식 RSS는 분야별(종목별 아님)이라, 구글 뉴스 RSS
검색("회사명" site:bloomberg.com)으로 헤드라인과 링크만 가져온다. 기사 본문은 대부분
블룸버그 유료 구독이 필요하다.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree

import requests
import yfinance as yf

from config import BLOOMBERG_NEWS_NAMES
from src.concurrency import fetch_all, safe_call

logger = logging.getLogger(__name__)

SEEKING_ALPHA_RSS_URL = "https://seekingalpha.com/api/sa/combined/{ticker}.xml"
SA_HEADERS = {"User-Agent": "Mozilla/5.0 (stock-agent personal use RSS reader)"}
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
BLOOMBERG_TITLE_SUFFIXES = (" - Bloomberg.com", " - Bloomberg")
# 기사가 아닌 블룸버그 페이지(인물 프로필, 주제 모음, 회사 정보) - 제목 패턴으로 거른다
_NON_ARTICLE_TITLE = re.compile(r"Profile and Biography|Trending News, Latest Updates|\b(Corp|Inc|Ltd|LLC|Co)\.?$")


def fetch_yahoo_news(ticker: str, limit: int = 3, hours: int = 24) -> List[dict]:
    cutoff = recent_cutoff(hours)
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
    cutoff = recent_cutoff(hours)
    response = requests.get(
        SEEKING_ALPHA_RSS_URL.format(ticker=ticker), headers=SA_HEADERS, timeout=15
    )
    if response.status_code != 200:
        return []
    root = ElementTree.fromstring(response.content)
    news = []
    for item in root.findall(".//item"):
        pub_date = parse_rfc822_datetime(item.findtext("pubDate"))
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


def parse_bloomberg_rss(xml: bytes, name: str, cutoff: dt.datetime, limit: int) -> List[dict]:
    """구글 뉴스 RSS 검색 결과에서 제목에 회사 이름이 들어간 블룸버그 기사만 최신순으로.

    구글 검색은 본문에만 이름이 나오는 기사나 방송 편성표·인물 프로필 같은 블룸버그
    페이지도 섞어 주므로(2026-09 "Micron" 검색 56건 중 대부분 무관) 제목으로 거른다.
    """
    root = ElementTree.fromstring(xml)
    news = []
    for item in root.findall(".//item"):
        pub_date = parse_rfc822_datetime(item.findtext("pubDate"))
        if pub_date is None or pub_date < cutoff:
            continue
        if "bloomberg" not in (item.findtext("source") or "").lower():
            continue
        title = item.findtext("title", "")
        for suffix in BLOOMBERG_TITLE_SUFFIXES:
            if title.endswith(suffix):
                title = title[: -len(suffix)]
                break
        if name.lower() not in title.lower() or _NON_ARTICLE_TITLE.search(title):
            continue
        news.append({"title": title, "url": item.findtext("link"), "date": pub_date, "source": "Bloomberg"})
    return newest_first(news)[:limit]


def fetch_bloomberg_news(ticker: str, limit: int = 3, hours: int = 24) -> List[dict]:
    name = BLOOMBERG_NEWS_NAMES.get(ticker)
    if name is None:
        return []
    response = requests.get(
        GOOGLE_NEWS_RSS_URL,
        params={"q": f'"{name}" site:bloomberg.com when:1d', "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers=SA_HEADERS,
        timeout=15,
    )
    # 구글이 요청을 거부(차단·요청 과다)하면 조용히 빈 결과가 되지 않도록 예외로 올려
    # 호출부 safe_call이 경고를 남기게 한다.
    if response.status_code != 200:
        raise RuntimeError(f"구글 뉴스 RSS HTTP {response.status_code}")
    return parse_bloomberg_rss(response.content, name, recent_cutoff(hours), limit)


# 최종적으로는 세 소스를 합쳐 최신순 상위 limit개만 남기므로, 소스별로는
# 넉넉히 모아둔다 (너무 적게 모으면 한쪽 소스 기사가 실제로는 더 최신인데도
# 개수 제한에 걸려 후보에서 빠질 수 있다).
_SOURCE_POOL_SIZE = 10


def get_recent_news_for_tickers(
    tickers: List[str], limit: int = 3, hours: int = 24
) -> dict:
    bloomberg_found: dict = {}

    def fetch(ticker: str) -> List[dict]:
        # 한 소스가 실패해도 다른 소스 기사는 살린다.
        yahoo = safe_call(f"Yahoo 뉴스 {ticker}", fetch_yahoo_news, ticker, _SOURCE_POOL_SIZE, hours, default=[])
        seeking_alpha = safe_call(
            f"Seeking Alpha 뉴스 {ticker}", fetch_seekingalpha_news, ticker, _SOURCE_POOL_SIZE, hours, default=[]
        )
        bloomberg = safe_call(
            f"Bloomberg 뉴스 {ticker}", fetch_bloomberg_news, ticker, _SOURCE_POOL_SIZE, hours, default=[]
        )
        bloomberg_found[ticker] = len(bloomberg)
        return newest_first(yahoo + seeking_alpha + bloomberg)[:limit]

    result = fetch_all(tickers, fetch, what="미국 종목 뉴스", default=[])
    shown = sum(1 for news in result.values() for n in news if n["source"] == "Bloomberg")
    logger.info(
        "Bloomberg 뉴스 후보 %d건(%d개 종목), 최신순 선택 후 표시 %d건",
        sum(bloomberg_found.values()), sum(1 for c in bloomberg_found.values() if c), shown,
    )
    return result


def get_recent_yahoo_news_for_tickers(
    tickers: List[str], limit: int = 3, hours: int = 24
) -> dict:
    """Yahoo Finance 단일 소스 뉴스 (Seeking Alpha가 다루지 않는 지수 티커용).

    Yahoo 피드는 발행 시각 순서가 아니어서(예: 08:17 다음에 08:29 기사) 최신순으로
    다시 정렬한다. 피드 앞쪽에서 limit개만 받으면 더 최신 기사가 빠질 수 있어,
    호출부는 limit을 넉넉히 줘야 한다."""
    return fetch_all(
        tickers, lambda t: newest_first(fetch_yahoo_news(t, limit, hours)), what="Yahoo 뉴스", default=[]
    )


def dedupe_news_across(news_map: dict, order: List[str], limit: int = 3) -> dict:
    """여러 카드(지수)에 같은 기사가 반복되지 않게, order 순서대로 앞 카드에
    이미 나온 기사(URL 기준)를 뒤 카드 후보에서 빼고 limit개씩 채운다.
    news_map의 각 목록은 limit보다 넉넉한 후보 풀이어야 빈자리가 채워진다."""
    seen = set()
    result = {}
    for key in order:
        picked = []
        for news in news_map.get(key, []):
            url = news.get("url")
            if url in seen:
                continue
            picked.append(news)
            if len(picked) >= limit:
                break
        seen.update(n.get("url") for n in picked)
        result[key] = picked
    return result


def recent_cutoff(hours: int) -> dt.datetime:
    """최근 hours시간 기사만 남길 때의 기준 시각(UTC)."""
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)


def newest_first(news: List[dict]) -> List[dict]:
    return sorted(news, key=lambda n: n["date"], reverse=True)


def _parse_iso_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_rfc822_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
