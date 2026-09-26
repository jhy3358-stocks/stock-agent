"""블룸버그 뉴스(구글 뉴스 RSS) - 제목 필터, 시간 필터, 출처 필터, 세 소스 최신순 병합."""
from __future__ import annotations

import datetime as dt

import src.news_client as news_client

_RSS = """<rss><channel>
<item><title>Micron Jumps as AI Memory Demand Surges - Bloomberg</title><link>https://news.google.com/a</link>
<pubDate>Fri, 25 Sep 2026 20:00:00 GMT</pubDate><source url="https://www.bloomberg.com">Bloomberg</source></item>
<item><title>Bloomberg Wall Street Week: September 25, 2026 - Bloomberg.com</title><link>https://news.google.com/b</link>
<pubDate>Fri, 25 Sep 2026 21:00:00 GMT</pubDate><source url="https://www.bloomberg.com">Bloomberg.com</source></item>
<item><title>Micron Supplier Update - Bloomberg.com</title><link>https://news.google.com/c</link>
<pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate><source url="https://www.bloomberg.com">Bloomberg.com</source></item>
<item><title>Micron Lee, Acme Inc: Profile and Biography - Bloomberg.com</title><link>https://news.google.com/e</link>
<pubDate>Fri, 25 Sep 2026 23:00:00 GMT</pubDate><source url="https://www.bloomberg.com">Bloomberg.com</source></item>
<item><title>Micron Memory Solutions Corp - Bloomberg.com</title><link>https://news.google.com/f</link>
<pubDate>Fri, 25 Sep 2026 23:30:00 GMT</pubDate><source url="https://www.bloomberg.com">Bloomberg.com</source></item>
<item><title>Micron beats estimates - Reuters</title><link>https://news.google.com/d</link>
<pubDate>Fri, 25 Sep 2026 22:00:00 GMT</pubDate><source url="https://www.reuters.com">Reuters</source></item>
</channel></rss>"""


def test_parse_keeps_recent_bloomberg_titles_with_company_name():
    cutoff = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
    news = news_client.parse_bloomberg_rss(_RSS.encode(), "Micron", cutoff, limit=5)
    assert [(n["title"], n["source"]) for n in news] == [("Micron Jumps as AI Memory Demand Surges", "Bloomberg")]


def test_three_sources_merged_newest_first(monkeypatch):
    def article(source, hour):
        return {"title": source, "url": source, "date": dt.datetime(2026, 9, 25, hour, tzinfo=dt.timezone.utc),
                "source": source}

    monkeypatch.setattr(news_client, "fetch_yahoo_news", lambda *a: [article("Yahoo Finance", 9)])
    monkeypatch.setattr(news_client, "fetch_seekingalpha_news", lambda *a: [article("Seeking Alpha", 11)])
    monkeypatch.setattr(news_client, "fetch_bloomberg_news", lambda *a: [article("Bloomberg", 10)])
    result = news_client.get_recent_news_for_tickers(["MU"], limit=2)
    assert [n["source"] for n in result["MU"]] == ["Seeking Alpha", "Bloomberg"]
