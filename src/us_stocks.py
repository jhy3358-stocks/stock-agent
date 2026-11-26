"""미국 종목 및 나스닥/S&P500 지수 데이터 수집 (yfinance)."""
from __future__ import annotations

from config import INDEX_FUTURES, INDICES, LISTING_PRICES, US_STOCKS
from src.concurrency import fetch_all, safe_call
from src.extended_hours import index_futures_quote, stock_extended_quote
from src.models import MarketItem
from src.yf_data import price_history


def _fetch(ticker: str, name: str, market: str, unit: str) -> MarketItem:
    history = price_history(ticker, period="6mo", interval="1d")
    # 상장 첫날처럼 시세가 하루치뿐이면 전일 종가 대신 상장가(공모가) 대비로 등락률을 낸다
    prev_price = LISTING_PRICES.get(ticker) if len(history) < 2 else None
    item = MarketItem.from_close(
        name, ticker, market, history["Close"], history["Volume"], unit, prev_price=prev_price
    )
    # 시간외·선물 조회가 실패해도 정규장 시세는 그대로 보여준다
    if market == "US":
        item.extended = safe_call(f"{ticker} 시간외 시세", stock_extended_quote,
                                  ticker, item.current_price, default=None)
    elif ticker in INDEX_FUTURES:
        item.extended = safe_call(f"{ticker} 지수 선물 시세", index_futures_quote,
                                  ticker, default=None)
    return item


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
