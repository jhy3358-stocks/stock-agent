"""네이버 뉴스 - 지수 뉴스 제목 필터 테스트."""
from __future__ import annotations

import src.naver_news_client as naver


class _Resp:
    def __init__(self, items):
        self._items = items

    def raise_for_status(self):
        pass

    def json(self):
        return {"items": self._items}


_ITEMS = [
    {"title": "“옵티머스 나온다며” 지석진, 테슬라 투자 후회", "originallink": "https://e.com/1",
     "pubDate": "Fri, 25 Sep 2026 17:36:00 +0900"},
    {"title": "추석 이후 <b>코스피</b>, 연말 랠리 이어질까", "originallink": "https://e.com/2",
     "pubDate": "Fri, 25 Sep 2026 14:20:00 +0900"},
]


def _patch(monkeypatch):
    monkeypatch.setattr(naver.requests, "get", lambda *a, **k: _Resp(_ITEMS))
    monkeypatch.setattr(naver.dt, "datetime", _FixedNow)


class _FixedNow(naver.dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return naver.dt.datetime(2026, 9, 25, 18, 0, tzinfo=naver.dt.timezone(naver.dt.timedelta(hours=9)))


def test_title_filter_drops_articles_without_query_in_title(monkeypatch):
    _patch(monkeypatch)
    news = naver.fetch_naver_news("id", "secret", "코스피", limit=3, require_query_in_title=True)
    assert [n["url"] for n in news] == ["https://e.com/2"]


def test_no_title_filter_by_default(monkeypatch):
    _patch(monkeypatch)
    news = naver.fetch_naver_news("id", "secret", "코스피", limit=3)
    assert len(news) == 2
