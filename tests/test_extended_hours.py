"""장 마감 후 시세(지수 선물·종목 시간외) 테스트 (네트워크 없이)."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from src import extended_hours as eh
from src.html_report import _extended_row
from src.models import MarketItem
from src.report import build_kakao_summary


def _bars(times, closes):
    index = pd.DatetimeIndex(pd.to_datetime(times)).tz_localize("America/New_York")
    return pd.Series(closes, index=index)


def test_index_futures_change_since_cash_close(monkeypatch):
    bars = {
        "^GSPC": _bars(["2026-11-25 15:50", "2026-11-25 15:55"], [7180.0, 7182.78]),
        "ES=F": _bars(["2026-11-25 15:55", "2026-11-25 16:00", "2026-11-25 23:55"],
                      [7196.75, 7200.0, 7247.75]),
    }
    monkeypatch.setattr(eh, "_closes", lambda t, **kw: bars[t])

    quote = eh.index_futures_quote("^GSPC")

    # 기준은 정규장 마지막 봉(15:55) 시점 선물 가격. 선물 수준(7,247)은 쓰지 않는다
    assert round(quote.change_pct, 2) == round((7247.75 / 7196.75 - 1) * 100, 2)
    assert quote.price is None and quote.label == "S&P500 선물"
    assert quote.as_of.hour == 23


def test_index_futures_none_during_regular_session(monkeypatch):
    bars = {
        "^GSPC": _bars(["2026-11-25 10:00"], [7180.0]),
        "ES=F": _bars(["2026-11-25 09:55", "2026-11-25 10:00"], [7190.0, 7195.0]),
    }
    monkeypatch.setattr(eh, "_closes", lambda t, **kw: bars[t])
    assert eh.index_futures_quote("^GSPC") is None


def test_stock_after_hours_vs_regular_close_on_half_day(monkeypatch):
    # 조기 폐장일(13:00 마감): 13:00 이후 봉은 시간외
    regular = _bars(["2026-11-27 12:50", "2026-11-27 12:55"], [150.0, 149.5])
    extended = _bars(["2026-11-27 12:55", "2026-11-27 14:30"], [149.5, 151.0])
    monkeypatch.setattr(eh, "_closes",
                        lambda t, prepost=False: extended if prepost else regular)

    quote = eh.stock_extended_quote("NVDA", 149.27)

    assert quote.price == 151.0 and round(quote.change_pct, 2) == round((151.0 / 149.27 - 1) * 100, 2)
    assert quote.label == "시간외"

    monkeypatch.setattr(eh, "_closes", lambda t, prepost=False: regular)
    assert eh.stock_extended_quote("NVDA", 149.27) is None  # 시간외 거래 없음


def _item(name, symbol, market, unit, extended=None):
    close = pd.Series([100.0, 101.0])
    item = MarketItem.from_close(name, symbol, market, close, None, unit)
    item.extended = extended
    return item


def test_extended_rows_and_kakao_futures_text():
    as_of = dt.datetime(2026, 11, 25, 23, 55, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    index = _item("S&P500", "^GSPC", "INDEX", "pt", eh.ExtendedQuote("S&P500 선물", 0.71, as_of))
    stock = _item("엔비디아", "NVDA", "US", "$", eh.ExtendedQuote("시간외", -1.31, as_of, 151.22))

    assert "시간외(S&P500 선물) +0.71%" in _extended_row(index)
    assert "11/26 13:55 KST" in _extended_row(index)
    row = _extended_row(stock)
    assert 'class="ext down"' in row and "시간외 $151.22 (-1.31%)" in row
    assert _extended_row(_item("애플", "AAPL", "US", "$")) == ""

    summary = build_kakao_summary([], [], [index], "https://example.com")
    assert "S&P500+1.0%(선물+0.7%)" in summary
