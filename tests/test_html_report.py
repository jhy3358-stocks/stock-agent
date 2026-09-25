"""build_html_report - 주요 지수 카드 뉴스 표시 테스트."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from src.html_report import build_html_report
from src.models import MarketItem


def _index(symbol: str, name: str) -> MarketItem:
    close = pd.Series([100.0 + i for i in range(30)])
    return MarketItem(
        name=name, symbol=symbol, market="INDEX", close=close, volume=None,
        current_price=129.0, change_pct=0.78, unit="pt",
    )


def test_index_cards_show_news():
    news = {
        "^GSPC": [{"title": "S&P 500 hits record", "url": "https://example.com/a",
                   "date": dt.datetime(2026, 9, 25), "source": "Yahoo Finance"}],
        "^KS11": [{"title": "코스피 7000 돌파", "url": "https://example.com/b",
                   "date": dt.datetime(2026, 9, 25), "source": "네이버 뉴스"}],
    }
    page = build_html_report(
        [], [], [_index("^GSPC", "S&P500"), _index("^KS11", "코스피")], index_news=news
    )
    assert "[Yahoo Finance] S&amp;P 500 hits record" in page
    assert "[네이버 뉴스] 코스피 7000 돌파" in page


def test_index_cards_without_news_render():
    page = build_html_report([], [], [_index("^IXIC", "나스닥")])
    assert "나스닥" in page
    assert "관련 뉴스" not in page
