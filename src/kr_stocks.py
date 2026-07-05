"""국내 종목 및 코스피 지수 데이터 수집 (pykrx)."""
from __future__ import annotations

import datetime as dt

from pykrx import stock

from config import HISTORY_DAYS, KR_STOCKS
from src.models import MarketItem


def _date_range() -> tuple[str, str]:
    today = dt.date.today()
    fromdate = (today - dt.timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
    todate = today.strftime("%Y%m%d")
    return fromdate, todate


def fetch_kr_stock(code: str, name: str) -> MarketItem:
    fromdate, todate = _date_range()
    df = stock.get_market_ohlcv_by_date(fromdate, todate, code)
    df = df[df["종가"] > 0]
    close = df["종가"]
    volume = df["거래량"]
    current_price = float(close.iloc[-1])
    prev_price = float(close.iloc[-2])
    change_pct = (current_price - prev_price) / prev_price * 100
    return MarketItem(
        name=name,
        symbol=code,
        market="KR",
        close=close,
        volume=volume,
        current_price=current_price,
        change_pct=change_pct,
        unit="원",
    )


def fetch_all_kr_stocks() -> list[MarketItem]:
    return [fetch_kr_stock(code, name) for code, name in KR_STOCKS.items()]
