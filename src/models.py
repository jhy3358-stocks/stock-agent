"""공통 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


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

    @classmethod
    def from_close(
        cls,
        name: str,
        symbol: str,
        market: str,
        close: pd.Series,
        volume: Optional[pd.Series],
        unit: str,
    ) -> "MarketItem":
        """종가 시계열의 마지막 두 값으로 현재가·전일대비 등락률을 채운다."""
        current_price = float(close.iloc[-1])
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
