"""적정주가(GRAV 모델) 기반 밸류에이션 표시."""
from __future__ import annotations

from src.models import MarketItem
from src.valuation import fair_value_inputs, target_price


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
