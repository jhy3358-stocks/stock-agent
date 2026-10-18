"""docs/growth_valuation_spec.md §7/§9 RSI50 평균가 테스트 케이스."""
from __future__ import annotations

import pandas as pd

from src.rsi50 import WARMUP, Rsi50Result, compute_rsi50, rsi50_fair_value, wilder_rsi_and_p50


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


def test_listing_warmup_excluded_from_p50_average():
    # 상장 직후처럼 이력이 짧은 시계열: 초기 Wilder 평활이 불안정해 P50이
    # 음수로 튀는 구간이 평균에 섞이면 안 된다.
    # 상장 이튿날 +50% 급등 후 잔등락 (SPCX 상장 초기와 유사한 형태)
    close = pd.Series([100.0, 150.0] + [150.0 + (i % 5) - (i % 3) for i in range(68)])
    _, p50 = wilder_rsi_and_p50(close)
    assert (p50.iloc[1:WARMUP] < 0).any()  # 워밍업 구간에 음수 P50이 실제로 존재

    result = compute_rsi50(close)
    assert abs(result.avg_p50 - p50.iloc[WARMUP:].mean()) < 1e-9


def test_too_short_history_returns_nan():
    close = pd.Series([100.0 + i for i in range(WARMUP)])
    result = compute_rsi50(close)
    assert pd.isna(result.avg_p50)
    assert result.data_insufficient is True


def test_long_history_result_unchanged_by_warmup():
    # 이력이 126 + WARMUP일 이상이면 평균 구간이 기존(최근 126일)과 같아야 한다.
    close = pd.Series([50.0 + (i % 7) - (i % 3) + i * 0.05 for i in range(300)])
    _, p50 = wilder_rsi_and_p50(close)
    result = compute_rsi50(close)
    assert abs(result.avg_p50 - p50.iloc[-126:].mean()) < 1e-9


def test_rsi50_fair_value_prefers_cross_then_p50():
    assert rsi50_fair_value(Rsi50Result(95.0, 3, 90.0, False)) == (95.0, "교차점 평균")
    assert rsi50_fair_value(Rsi50Result(float("nan"), 0, 90.0, False)) == (90.0, "P50 역산 평균")
    assert rsi50_fair_value(Rsi50Result(float("nan"), 0, float("nan"), True)) is None


def test_resample_120m_groups_from_session_open_and_across_dst():
    from src.growth_data import resample_120m

    # 서머타임 종료(2026-11-01) 전후 하루씩, 60분봉 09:30~15:30 7개
    days = ["2026-10-30", "2026-11-02"]
    idx = pd.DatetimeIndex(
        [pd.Timestamp(f"{d} {h}", tz="America/New_York") for d in days
         for h in ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]]
    )
    close = pd.Series(range(len(idx)), index=idx, dtype=float)
    bars = resample_120m(close)

    assert [t.strftime("%H:%M") for t in bars.index[:4]] == ["09:30", "11:30", "13:30", "15:30"]
    assert [t.strftime("%H:%M") for t in bars.index[4:]] == ["09:30", "11:30", "13:30", "15:30"]
    # 각 120분봉 종가는 그 구간 마지막 60분봉 종가
    assert bars.tolist() == [1.0, 3.0, 5.0, 6.0, 8.0, 10.0, 12.0, 13.0]


def test_intraday_window_covers_last_126_trading_days():
    # 120분봉 하루 4봉 x 300거래일: 평균 구간은 최근 126봉이 아니라 최근 126거래일(504봉)
    days = pd.bdate_range("2025-01-01", periods=300)
    idx = pd.DatetimeIndex([d + pd.Timedelta(minutes=m) for d in days for m in (570, 690, 810, 930)])
    close = pd.Series([50.0 + (i % 7) - (i % 3) + i * 0.01 for i in range(len(idx))], index=idx)
    _, p50 = wilder_rsi_and_p50(close)

    result = compute_rsi50(close, timeframe="120m")
    assert abs(result.avg_p50 - p50.iloc[-126 * 4:].mean()) < 1e-9
    assert result.data_insufficient is False  # 300거래일 >= 126 + 100

    short = compute_rsi50(close.iloc[: 200 * 4], timeframe="120m")
    assert short.data_insufficient is True  # 200거래일 < 226 (봉은 800개여도)
