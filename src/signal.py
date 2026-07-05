"""RSI/이동평균 기반 규칙형 기술적 신호 코멘트.

애널리스트 의견이 아니라 지표값을 기계적으로 조합한 참고용 코멘트다.
"""
from __future__ import annotations

from config import MA_WINDOWS, RSI_PERIOD
from src.indicators import moving_average_diff, rsi
from src.models import MarketItem


def trading_signal(item: MarketItem) -> str:
    score = 0

    rsi_value = rsi(item.close, RSI_PERIOD)
    if rsi_value is not None:
        if rsi_value < 30:
            score += 1
        elif rsi_value > 70:
            score -= 1

    for window in MA_WINDOWS:
        result = moving_average_diff(item.close, window)
        if result is None:
            continue
        _, diff_pct = result
        score += 1 if diff_pct >= 0 else -1

    if score >= 2:
        return "매수 관점 우세 (기술적 신호 참고용)"
    if score <= -2:
        return "매도 관점 우세 (기술적 신호 참고용)"
    return "중립/관망 (기술적 신호 참고용)"
