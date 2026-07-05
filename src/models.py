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
