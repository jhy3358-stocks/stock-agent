"""RSI, 거래량 증감, 괴리율 계산."""
from __future__ import annotations

from typing import Optional

import pandas as pd


def gap_pct(price: float, reference: float) -> float:
    """reference(적정주가·이동평균 등) 대비 price의 괴리율(%)."""
    return (price - reference) / reference * 100


def rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    """Wilder's smoothing 방식의 RSI(기본 14일)를 계산한다."""
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    last_avg_loss = avg_loss.iloc[-1]
    if last_avg_loss == 0:
        return 100.0
    rs = avg_gain.iloc[-1] / last_avg_loss
    return float(100 - 100 / (1 + rs))


def volume_change_pct(volume: Optional[pd.Series]) -> Optional[float]:
    """전일 대비 거래량 증감률(%)을 계산한다."""
    if volume is None or len(volume) < 2:
        return None
    prev = volume.iloc[-2]
    if prev == 0:
        return None
    current = volume.iloc[-1]
    return float((current - prev) / prev * 100)
