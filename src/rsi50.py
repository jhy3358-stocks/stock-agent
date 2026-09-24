"""RSI 50 평균가 (docs/growth_valuation_spec.md §7).

기존 GRAV 리포트가 쓰는 src/indicators.rsi()는 "현재" RSI 한 값만 계산하는
반면, 이 모듈은 최근 126거래일 구간 전체에 대해 RSI=50을 지나간 지점들의
평균가(방법 A)와, 역산으로 구한 "다음날 RSI가 정확히 50이 되는 종가"의
평균(방법 B)을 구한다. 성장주 리포트 전용이라 growth_valuation과 마찬가지로
독립 모듈로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

RSI_PERIOD = 14
WINDOW = 126
MIN_WARMUP = 100


@dataclass
class Rsi50Result:
    avg_cross: float  # 교차점이 없으면 NaN
    cross_count: int
    avg_p50: float
    data_insufficient: bool


def wilder_rsi_and_p50(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Wilder RSI(14)와, 다음날 RSI가 정확히 50이 되는 종가(P50_t) 시계열."""
    delta = close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)
    p50 = close + (RSI_PERIOD - 1) * (avg_loss - avg_gain)
    return rsi, p50


def compute_rsi50(close: pd.Series) -> Rsi50Result:
    close = close.dropna()
    data_insufficient = len(close) < WINDOW + MIN_WARMUP

    rsi, p50 = wilder_rsi_and_p50(close)

    window = rsi.index[-min(WINDOW, len(close)):]
    rsi_prev = rsi.shift(1)
    close_prev = close.shift(1)

    crossed = [
        t for t in window
        if pd.notna(rsi_prev[t]) and pd.notna(rsi[t]) and (rsi[t] - 50) * (rsi_prev[t] - 50) < 0
    ]
    if crossed:
        p_cross = close_prev[crossed] + (close[crossed] - close_prev[crossed]) * (50 - rsi_prev[crossed]) / (
            rsi[crossed] - rsi_prev[crossed]
        )
        avg_cross = float(p_cross.mean())
    else:
        avg_cross = float("nan")

    avg_p50 = float(p50.loc[window].mean())

    return Rsi50Result(
        avg_cross=avg_cross,
        cross_count=len(crossed),
        avg_p50=avg_p50,
        data_insufficient=data_insufficient,
    )
