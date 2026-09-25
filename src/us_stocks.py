"""미국 종목 및 나스닥/S&P500 지수 데이터 수집 (yfinance)."""
from __future__ import annotations

from config import INDICES, US_STOCKS
from src.concurrency import fetch_all
from src.models import MarketItem
from src.yf_data import price_history


def _fetch(ticker: str, name: str, market: str, unit: str) -> MarketItem:
    history = price_history(ticker, period="6mo", interval="1d")
    return MarketItem.from_close(name, ticker, market, history["Close"], history["Volume"], unit)


def _fetch_many(names: dict, market: str, unit: str) -> list[MarketItem]:
    """시세를 병렬로 받는다. 조회에 실패한 종목은 경고를 남기고 리포트에서 뺀다."""
    items = fetch_all(
        names,
        lambda ticker: _fetch(ticker, names[ticker], market, unit),
        what=f"{market} 시세",
        default=None,
    )
    return [item for item in items.values() if item is not None]


def fetch_all_us_stocks() -> list[MarketItem]:
    return _fetch_many(US_STOCKS, "US", "$")


def fetch_indices() -> list[MarketItem]:
    return _fetch_many(INDICES, "INDEX", "pt")
