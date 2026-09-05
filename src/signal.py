"""적정주가(GRAV 모델 + 종합 median 모델) 기반 밸류에이션 표시 및 RSI 결합 매수/매도 신호."""
from __future__ import annotations

from typing import Optional

from config import MA_WINDOWS, RSI_PERIOD
from src.indicators import moving_average_diff, rsi
from src.models import MarketItem
from src.valuation import fair_value_inputs, median_fair_value, target_price

# 과매수/과매도 판단에 쓰는 (기존 GRAV 모델) 적정주가 대비 괴리율 임계값(%)
FAIR_VALUE_GAP_THRESHOLD = 30.0


def _format_price(value: float, unit: str) -> str:
    if unit == "원":
        return f"{value:,.0f}{unit}"
    if unit == "$":
        return f"{unit}{value:,.2f}"
    return f"{value:,.2f}{unit}"


def fair_value_line(item: MarketItem) -> str:
    """리포트에 표시할 적정주가 요약 한 줄.

    기존 GRAV 모델과, DCF/업종평균 상대가치를 합친 종합(median) 모델 두 값을
    "적정주가 .. (괴리율 ..%)" 형태로 나란히 보여준다. 괴리율 = (현재가-적정주가)/적정주가.
    """
    inputs = fair_value_inputs(item)
    original = target_price(**inputs) if inputs else None
    combined = median_fair_value(item)

    parts = []
    for value in (original, combined):
        if value is None:
            continue
        gap = (item.current_price - value) / value * 100
        parts.append(f"적정주가 {_format_price(value, item.unit)} (괴리율 {gap:+.1f}%)")

    if not parts:
        return "적정주가 데이터 없음"
    return ", ".join(parts)


def _fair_value_gap_pct(item: MarketItem) -> Optional[float]:
    """(기존 GRAV 모델) 현재가가 적정주가 대비 몇 % 위/아래에 있는지."""
    inputs = fair_value_inputs(item)
    if inputs is None:
        return None
    tp = target_price(**inputs)
    return (item.current_price - tp) / tp * 100


def _legacy_ma_rsi_signal(item: MarketItem) -> Optional[str]:
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

    if (score >= 2 or score <= -2) and rsi_value is not None:
        return f"RSI {rsi_value:.1f}"
    return None


def trading_signal(item: MarketItem) -> Optional[str]:
    """(기존 GRAV 모델) 적정주가 대비 괴리율 + RSI 조합으로 매수/매도 관점을 판단한다.

    - 과매수(매도 관점 우세): 현재가가 적정주가보다 30%p 이상 높고 RSI > 70
    - 과매도(매수 관점 우세): 현재가가 적정주가보다 30%p 이상 낮고 RSI < 30
    - 그 외(중립/판단보류)에는 화면에 굳이 띄우지 않도록 None을 반환한다.
    """
    if fair_value_inputs(item) is None:
        return _legacy_ma_rsi_signal(item)

    gap_pct = _fair_value_gap_pct(item)
    rsi_value = rsi(item.close, RSI_PERIOD)
    if gap_pct is None or rsi_value is None:
        return None

    if gap_pct >= FAIR_VALUE_GAP_THRESHOLD and rsi_value > 70:
        return f"RSI {rsi_value:.1f}"
    if gap_pct <= -FAIR_VALUE_GAP_THRESHOLD and rsi_value < 30:
        return f"RSI {rsi_value:.1f}"
    return None
