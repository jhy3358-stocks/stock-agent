"""공통 데이터 모델."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class ExtendedQuote:
    """정규장 마감 후 시세 (src/extended_hours.py)."""

    label: str  # "시간외" / "S&P500 선물" 등
    change_pct: float  # 정규장 종가(지수는 정규장 마감 시점 선물 가격) 대비
    as_of: dt.datetime
    price: Optional[float] = None  # 종목 시간외 가격. 지수(선물)는 수준이 달라 쓰지 않는다


@dataclass
class MarketItem:
    name: str
    symbol: str
    market: str  # "KR" | "US" | "INDEX"
    close: pd.Series
    volume: Optional[pd.Series]
    current_price: float
    change_pct: float
    unit: str  # "원" | "$" | "pt"
    extended: Optional[ExtendedQuote] = None  # 시간외(종목)·선물(지수) 등락

    @classmethod
    def from_close(
        cls,
        name: str,
        symbol: str,
        market: str,
        close: pd.Series,
        volume: Optional[pd.Series],
        unit: str,
        prev_price: Optional[float] = None,
    ) -> "MarketItem":
        """종가 시계열의 마지막 두 값으로 현재가·전일대비 등락률을 채운다.

        prev_price를 주면 직전 종가 대신 그 값을 기준으로 등락률을 계산한다 (신규상장 첫날).
        """
        current_price = float(close.iloc[-1])
        if prev_price is None:
            prev_price = float(close.iloc[-2])
        return cls(
            name=name,
            symbol=symbol,
            market=market,
            close=close,
            volume=volume,
            current_price=current_price,
            change_pct=(current_price - prev_price) / prev_price * 100,
            unit=unit,
        )
