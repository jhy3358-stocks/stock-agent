"""정규장 마감 후 시세 - 미국 지수는 지수 선물, 미국 종목은 시간외(프리·애프터마켓) 거래.

- 지수(^GSPC, ^IXIC)는 정규장에서만 계산돼 장 마감 후 값이 없다. 거의 24시간 거래되는
  지수 선물(config.INDEX_FUTURES: ES=F, NQ=F)로 마감 이후 흐름을 보여준다. 선물은 지수와
  가격 수준이 달라(2026-11-25 ES 7,196.75 vs S&P500 7,182.78) 수준이 아니라 "정규장 마감
  시점 선물 가격 대비 지금 선물 가격" 등락률만 쓴다. 마감 시점은 지수 5분봉의 마지막 봉
  시각이라 조기 폐장일(13:00 마감)도 맞게 잡힌다. 나스닥 종합지수 선물은 없어 나스닥100
  선물(NQ)을 쓴다.
- 종목은 yfinance 5분봉 prepost=True의 마지막 값을 정규장 종가와 비교한다. 정규장 마지막 봉은
  prepost=False 5분봉으로 구한다(조기 폐장일에 시각으로 거르면 13:00 이후가 정규장으로 잡힌다).
  시간외 거래는 04:00~20:00(미 동부)뿐이라, 그 밖의 시각(예: 한국 17:00 리포트)에는 가장
  최근 시간외 값이 거래 시각과 함께 나온다.
- 지금이 정규장이면(시간외·선물 봉이 정규장 마지막 봉보다 늦지 않으면) None.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from config import INDEX_FUTURES
from src.models import ExtendedQuote
from src.yf_data import price_history

INTRADAY = {"period": "5d", "interval": "5m"}


def _closes(ticker: str, **kwargs) -> pd.Series:
    return price_history(ticker, **INTRADAY, **kwargs)["Close"]


def index_futures_quote(index_symbol: str) -> Optional[ExtendedQuote]:
    futures, label = INDEX_FUTURES[index_symbol]
    index_bars, futures_bars = _closes(index_symbol), _closes(futures)
    if index_bars.empty or futures_bars.empty:
        return None
    cash_close = index_bars.index[-1]
    at_close = futures_bars[futures_bars.index <= cash_close]
    if at_close.empty or futures_bars.index[-1] <= cash_close:
        return None
    reference, last = float(at_close.iloc[-1]), float(futures_bars.iloc[-1])
    return ExtendedQuote(
        label=label,
        change_pct=(last / reference - 1) * 100,
        as_of=futures_bars.index[-1].to_pydatetime(),
    )


def stock_extended_quote(ticker: str, regular_close: float) -> Optional[ExtendedQuote]:
    regular, with_ext = _closes(ticker), _closes(ticker, prepost=True)
    if regular.empty or with_ext.empty or with_ext.index[-1] <= regular.index[-1]:
        return None
    price = float(with_ext.iloc[-1])
    return ExtendedQuote(
        label="시간외",
        change_pct=(price / regular_close - 1) * 100,
        as_of=with_ext.index[-1].to_pydatetime(),
        price=price,
    )
