"""미국 종목 및 나스닥/S&P500 지수 데이터 수집 (yfinance)."""
from __future__ import annotations

import yfinance as yf

from config import INDICES, US_STOCKS
from src.models import MarketItem


def _fetch(ticker: str, name: str, market: str, unit: str) -> MarketItem:
    history = yf.Ticker(ticker).history(period="6mo", interval="1d")
    close = history["Close"]
    volume = history["Volume"]
    current_price = float(close.iloc[-1])
    prev_price = float(close.iloc[-2])
    change_pct = (current_price - prev_price) / prev_price * 100
    return MarketItem(
        name=name,
        symbol=ticker,
        market=market,
        close=close,
        volume=volume,
        current_price=current_price,
        change_pct=change_pct,
        unit=unit,
    )


def fetch_all_us_stocks() -> list[MarketItem]:
    return [_fetch(ticker, name, "US", "$") for ticker, name in US_STOCKS.items()]


def fetch_indices() -> list[MarketItem]:
    return [_fetch(ticker, name, "INDEX", "pt") for ticker, name in INDICES.items()]
