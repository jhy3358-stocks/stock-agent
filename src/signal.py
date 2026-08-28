"""적정주가(GRAV 모델) 및 RSI 기반 매수/중립/매도 신호."""
from __future__ import annotations

from typing import Optional

from config import MA_WINDOWS, RSI_PERIOD
from src.indicators import moving_average_diff, rsi
from src.models import MarketItem
from src.valuation import fair_value_inputs, target_price

# 과매수/과매도 판단에 쓰는 적정주가 대비 괴리율 임계값(%)
FAIR_VALUE_GAP_THRESHOLD = 30.0


def fair_value_gap_pct(item: MarketItem) -> Optional[float]:
    """현재가가 적정주가 대비 몇 % 위/아래에 있는지. 데이터 부족하면 None."""
    inputs = fair_value_inputs(item)
    if inputs is None:
        return None
    tp = target_price(**inputs)
    return (item.current_price - tp) / tp * 100


def fair_value_line(item: MarketItem) -> str:
    """리포트에 표시할 적정주가 요약 한 줄."""
    inputs = fair_value_inputs(item)
    if inputs is None:
        return "적정주가 데이터 없음"

    tp = target_price(**inputs)
    gap = (item.current_price - tp) / tp * 100
    if item.unit == "원":
        tp_text = f"{tp:,.0f}{item.unit}"
    elif item.unit == "$":
        tp_text = f"{item.unit}{tp:,.2f}"
    else:
        tp_text = f"{tp:,.2f}{item.unit}"

    if gap >= 0:
        gap_text = f"현재가가 적정주가 대비 {gap:.1f}% 높음 (고평가)"
    else:
        gap_text = f"현재가가 적정주가 대비 {abs(gap):.1f}% 낮음 (상승여력 {abs(gap):.1f}%)"

    return f"적정주가 {tp_text} ({gap_text})"


def _legacy_ma_rsi_signal(item: MarketItem) -> str:
    """적정주가 데이터가 없는 종목(예: SPCX)에 대한 RSI/이동평균 기반 대체 신호."""
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
        return "매수 관점 우세 (기술적 신호 참고용, 적정주가 데이터 없음)"
    if score <= -2:
        return "매도 관점 우세 (기술적 신호 참고용, 적정주가 데이터 없음)"
    return None


def trading_signal(item: MarketItem) -> Optional[str]:
    """적정주가 대비 괴리율 + RSI 조합으로 매수/매도 관점을 판단한다.

    - 과매수(매도 관점 우세): 현재가가 적정주가보다 30%p 이상 높고 RSI > 70
    - 과매도(매수 관점 우세): 현재가가 적정주가보다 30%p 이상 낮고 RSI < 30
    - 그 외(중립/관망, 데이터 부족)에는 표시할 문구가 없으므로 None을 반환한다.
    """
    valuation_available = fair_value_inputs(item) is not None
    if not valuation_available:
        return _legacy_ma_rsi_signal(item)

    gap_pct = fair_value_gap_pct(item)
    rsi_value = rsi(item.close, RSI_PERIOD)
    if gap_pct is None or rsi_value is None:
        return None

    if gap_pct >= FAIR_VALUE_GAP_THRESHOLD and rsi_value > 70:
        return "매도 관점 우세 (과매수: 적정주가 대비 +30%↑ & RSI 70↑)"
    if gap_pct <= -FAIR_VALUE_GAP_THRESHOLD and rsi_value < 30:
        return "매수 관점 우세 (과매도: 적정주가 대비 -30%↓ & RSI 30↓)"
    return None
