"""병렬 조회 + 실패 격리 테스트."""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

import src.news_client as news_client
import src.us_stocks as us_stocks
import src.yf_data as yf_data
from src.concurrency import fetch_all, safe_call


def test_fetch_all_keeps_order_and_isolates_failures(caplog):
    def fn(k):
        if k == "BAD":
            raise TimeoutError("timed out")
        return k.lower()

    with caplog.at_level(logging.WARNING):
        result = fetch_all(["A", "BAD", "C"], fn, what="테스트", default=[])

    assert list(result) == ["A", "BAD", "C"]
    assert result == {"A": "a", "BAD": [], "C": "c"}
    assert "테스트 BAD 실패" in caplog.text


def test_safe_call_returns_default():
    assert safe_call("x", lambda: 1 / 0, default=None) is None


def test_one_news_source_failure_keeps_other(monkeypatch):
    article = {"title": "t", "url": "u", "date": dt.datetime(2026, 9, 25), "source": "Yahoo Finance"}
    monkeypatch.setattr(news_client, "fetch_yahoo_news", lambda *a: [article])

    def boom(*a):
        raise ConnectionError("SA down")

    monkeypatch.setattr(news_client, "fetch_seekingalpha_news", boom)
    monkeypatch.setattr(news_client, "fetch_bloomberg_news", lambda *a: [])
    assert news_client.get_recent_news_for_tickers(["AAPL"]) == {"AAPL": [article]}


class _FakeTicker:
    def __init__(self, ticker):
        self.ticker = ticker

    def history(self, **kwargs):
        if self.ticker == "BAD":
            raise ConnectionError("no data")
        return pd.DataFrame({"Close": [10.0, 11.0], "Volume": [1, 2]})


def test_failed_price_fetch_drops_only_that_stock(monkeypatch):
    monkeypatch.setattr(yf_data.yf, "Ticker", _FakeTicker)
    items = us_stocks._fetch_many({"AAA": "a", "BAD": "b", "CCC": "c"}, "US", "$")
    assert [i.symbol for i in items] == ["AAA", "CCC"]


def test_dart_http_error_does_not_leak_api_key(monkeypatch):
    import pytest

    import src.dart_client as dart

    class _Resp:
        status_code = 500
        url = "https://opendart.fss.or.kr/api/list.json?crtfc_key=SECRET"

    monkeypatch.setattr(dart.requests, "get", lambda *a, **k: _Resp())
    with pytest.raises(RuntimeError) as exc:
        dart.fetch_recent_disclosures("SECRET", "00126380")
    assert "SECRET" not in str(exc.value)
