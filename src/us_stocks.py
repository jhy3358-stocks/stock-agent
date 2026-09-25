"""미국 종목 및 나스닥/S&P500 지수 데이터 수집 (yfinance)."""
from __future__ import annotations

from config import INDICES, US_STOCKS
from src.models import MarketItem
from src.yf_data import price_history


def _fetch(ticker: str, name: str, market: str, unit: str) -> MarketItem:
    history = price_history(ticker, period="6mo", interval="1d")
    return MarketItem.from_close(name, ticker, market, history["Close"], history["Volume"], unit)


def fetch_all_us_stocks() -> list[MarketItem]:
    return [_fetch(ticker, name, "US", "$") for ticker, name in US_STOCKS.items()]


def fetch_indices() -> list[MarketItem]:
    return [_fetch(ticker, name, "INDEX", "pt") for ticker, name in INDICES.items()]
