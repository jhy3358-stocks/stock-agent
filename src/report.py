"""리포트 텍스트 포맷팅."""
from __future__ import annotations

import datetime as dt
from typing import List

from config import MA_WINDOWS, RSI_PERIOD
from src.indicators import moving_average_diff, rsi, volume_change_pct
from src.models import MarketItem
from src.signal import trading_signal


def _format_price(item: MarketItem) -> str:
    if item.unit == "원":
        return f"{item.current_price:,.0f}{item.unit}"
    if item.unit == "$":
        return f"{item.unit}{item.current_price:,.2f}"
    return f"{item.current_price:,.2f}{item.unit}"


def _format_ma_line(item: MarketItem) -> str:
    parts = []
    for window in MA_WINDOWS:
        result = moving_average_diff(item.close, window)
        if result is None:
            parts.append(f"MA{window} 데이터부족")
            continue
        _, diff_pct = result
        position = "위" if diff_pct >= 0 else "아래"
        parts.append(f"MA{window} {position} ({diff_pct:+.1f}%)")
    return " / ".join(parts)


def _format_volume_line(item: MarketItem) -> str:
    if item.volume is None or len(item.volume) == 0:
        return "거래량 정보 없음"
    latest_volume = item.volume.iloc[-1]
    change = volume_change_pct(item.volume)
    if change is None:
        return f"거래량 {latest_volume:,.0f}"
    return f"거래량 {latest_volume:,.0f} (전일대비 {change:+.1f}%)"


def format_item(item: MarketItem) -> str:
    rsi_value = rsi(item.close, RSI_PERIOD)
    rsi_text = f"{rsi_value:.1f}" if rsi_value is not None else "데이터부족"
    lines = [
        f"■ {item.name} ({item.symbol})",
        f"현재가 {_format_price(item)} ({item.change_pct:+.2f}%)",
        _format_ma_line(item),
        f"RSI({RSI_PERIOD}) {rsi_text}",
        _format_volume_line(item),
        trading_signal(item),
    ]
    return "\n".join(lines)


def format_section(title: str, items: List[MarketItem]) -> str:
    header = f"[{title}] {dt.date.today().strftime('%Y-%m-%d')}"
    body = "\n\n".join(format_item(item) for item in items)
    return f"{header}\n\n{body}"


def build_report_sections(
    kr_stocks: List[MarketItem],
    us_stocks: List[MarketItem],
    indices: List[MarketItem],
) -> List[str]:
    return [
        format_section("국내 종목", kr_stocks),
        format_section("미국 종목", us_stocks),
        format_section("주요 지수", indices),
    ]


# 카카오톡 "나에게 보내기" 기본 텍스트 템플릿은 글자수 200자 제한이 있어,
# 전체 상세는 GitHub Pages에 게시하고(build_report_sections/html_report 참고),
# 카카오톡에는 지수/등락 상위·하위 종목만 담은 요약 1건만 보낸다.
def build_kakao_summary(
    kr_stocks: List[MarketItem],
    us_stocks: List[MarketItem],
    indices: List[MarketItem],
    report_url: str,
    top_n: int = 2,
) -> str:
    # 카카오 앱이 메시지 API 검수 전에는 template의 button/link가 렌더링되지 않으므로,
    # 카카오톡이 자동으로 링크화하는 일반 URL 텍스트를 본문에 직접 포함시킨다.
    date_str = dt.date.today().strftime("%Y-%m-%d")
    all_stocks = kr_stocks + us_stocks
    gainers = sorted(all_stocks, key=lambda i: i.change_pct, reverse=True)[:top_n]
    losers = sorted(all_stocks, key=lambda i: i.change_pct)[:top_n]

    index_line = " ".join(f"{i.name}{i.change_pct:+.1f}%" for i in indices)
    gainer_line = " ".join(f"{i.name}{i.change_pct:+.1f}%" for i in gainers)
    loser_line = " ".join(f"{i.name}{i.change_pct:+.1f}%" for i in losers)

    lines = [
        f"[주식 리포트] {date_str}",
        index_line,
        f"상승 {gainer_line}",
        f"하락 {loser_line}",
        f"상세: {report_url}",
    ]
    return "\n".join(lines)
