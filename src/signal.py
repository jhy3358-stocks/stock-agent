"""적정주가(GRAV 모델 + 종합 median 모델) 기반 밸류에이션 표시."""
from __future__ import annotations

from src.models import MarketItem
from src.valuation import fair_value_inputs, median_fair_value, target_price


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
