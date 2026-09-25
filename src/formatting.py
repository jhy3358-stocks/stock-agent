"""텍스트 리포트·HTML 리포트·적정주가 줄에서 공통으로 쓰는 표시 문구."""
from __future__ import annotations

from config import RSI_PERIOD
from src.indicators import rsi, volume_change_pct
from src.models import MarketItem


def format_price(value: float, unit: str) -> str:
    if unit == "원":
        return f"{value:,.0f}{unit}"
    if unit == "$":
        return f"{unit}{value:,.2f}"
    return f"{value:,.2f}{unit}"


def rsi_text(item: MarketItem) -> str:
    value = rsi(item.close, RSI_PERIOD)
    return f"{value:.1f}" if value is not None else "데이터부족"


def volume_text(item: MarketItem) -> str:
    if item.volume is None or len(item.volume) == 0:
        return "거래량 정보 없음"
    latest_volume = item.volume.iloc[-1]
    change = volume_change_pct(item.volume)
    if change is None:
        return f"거래량 {latest_volume:,.0f}"
    return f"거래량 {latest_volume:,.0f} (전일대비 {change:+.1f}%)"
