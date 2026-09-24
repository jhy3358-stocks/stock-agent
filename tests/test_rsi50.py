"""docs/growth_valuation_spec.md §7/§9 RSI50 평균가 테스트 케이스."""
from __future__ import annotations

import pandas as pd

from src.rsi50 import compute_rsi50, wilder_rsi_and_p50


def test_uptrend_series_has_no_crossings_and_nan_avg_cross():
    # 상승만 있는 시계열 -> RSI가 50을 통과하는 지점이 없음
    close = pd.Series([100.0 + i for i in range(300)])
    result = compute_rsi50(close)
    assert result.cross_count == 0
    assert pd.isna(result.avg_cross)
    # RSI50 평균가(방법 B)는 교차 여부와 무관하게 계산 가능해야 한다
    assert result.avg_p50 == result.avg_p50  # not NaN


def test_short_history_sets_data_insufficient_flag():
    close = pd.Series([50.0 + (i % 5) for i in range(50)])  # 126+100일 미만
    result = compute_rsi50(close)
    assert result.data_insufficient is True


def test_long_history_clears_data_insufficient_flag():
    close = pd.Series([50.0 + (i % 7) - (i % 3) for i in range(300)])
    result = compute_rsi50(close)
    assert result.data_insufficient is False


def test_p50_price_makes_next_day_rsi_50():
    # 등락이 섞인 시계열로 위밍업 확보 후, P50_t를 다음날 종가로 넣으면
    # 그날 RSI가 50 +- 0.01이 되는지 검증한다.
    pattern = [10.0, 10.5, 10.2, 10.8, 10.4, 11.0, 10.6, 11.3, 10.9, 11.6]
    close = pd.Series(pattern * 4)  # 40일치, RSI(14) 워밍업 충분

    rsi, p50 = wilder_rsi_and_p50(close)
    last_p50 = p50.iloc[-1]

    extended = pd.concat([close, pd.Series([last_p50])], ignore_index=True)
    rsi_ext, _ = wilder_rsi_and_p50(extended)

    assert abs(rsi_ext.iloc[-1] - 50.0) < 0.01
