"""정적 HTML 리포트 페이지 생성 (GitHub Pages 게시용)."""
from __future__ import annotations

import datetime as dt
import html
from typing import Dict, List

from config import MA_WINDOWS, RSI_PERIOD
from src.indicators import moving_average_diff, rsi, volume_change_pct
from src.models import MarketItem

DisclosureMap = Dict[str, List[dict]]


def _price_text(item: MarketItem) -> str:
    if item.unit == "원":
        return f"{item.current_price:,.0f}{item.unit}"
    if item.unit == "$":
        return f"{item.unit}{item.current_price:,.2f}"
    return f"{item.current_price:,.2f}{item.unit}"


def _ma_text(item: MarketItem) -> str:
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


def _volume_text(item: MarketItem) -> str:
    if item.volume is None or len(item.volume) == 0:
        return "거래량 정보 없음"
    latest_volume = item.volume.iloc[-1]
    change = volume_change_pct(item.volume)
    if change is None:
        return f"거래량 {latest_volume:,.0f}"
    return f"거래량 {latest_volume:,.0f} (전일대비 {change:+.1f}%)"


def _disclosures_html(disclosures: List[dict]) -> str:
    if not disclosures:
        return ""
    items = "\n".join(
        f'<li><a href="{html.escape(d["url"])}" target="_blank" rel="noopener">'
        f'{html.escape(d["date"].strftime("%m/%d"))} {html.escape(d["title"])}</a></li>'
        for d in disclosures
    )
    return f"""
      <div class="disclosures">
        <div class="disclosures-title">최근 공시</div>
        <ul>{items}</ul>
      </div>"""


def _item_card(item: MarketItem, disclosures: List[dict]) -> str:
    direction = "up" if item.change_pct >= 0 else "down"
    rsi_value = rsi(item.close, RSI_PERIOD)
    rsi_text = f"{rsi_value:.1f}" if rsi_value is not None else "데이터부족"
    return f"""
    <div class="card {direction}">
      <div class="card-title">{item.name} <span class="symbol">({item.symbol})</span></div>
      <div class="price">{_price_text(item)} <span class="change">({item.change_pct:+.2f}%)</span></div>
      <div class="row">{_ma_text(item)}</div>
      <div class="row">RSI({RSI_PERIOD}) {rsi_text}</div>
      <div class="row">{_volume_text(item)}</div>
      {_disclosures_html(disclosures)}
    </div>"""


def _section(title: str, items: List[MarketItem], disclosures_map: DisclosureMap) -> str:
    cards = "\n".join(
        _item_card(item, disclosures_map.get(item.symbol, [])) for item in items
    )
    return f"""
    <section>
      <h2>{title}</h2>
      <div class="grid">{cards}</div>
    </section>"""


def build_html_report(
    kr_stocks: List[MarketItem],
    us_stocks: List[MarketItem],
    indices: List[MarketItem],
    kr_disclosures: DisclosureMap = None,
    us_filings: DisclosureMap = None,
) -> str:
    date_str = dt.date.today().strftime("%Y-%m-%d")
    kr_disclosures = kr_disclosures or {}
    us_filings = us_filings or {}
    sections = "\n".join(
        [
            _section("주요 지수", indices, {}),
            _section("국내 종목", kr_stocks, kr_disclosures),
            _section("미국 종목", us_stocks, us_filings),
        ]
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>주식 리포트 {date_str}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280;
    --card-bg: #f7f7f8; --up: #d1373f; --down: #1a63d1; --border: #e5e7eb;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #14161a; --fg: #e8e8ea; --muted: #9a9ba3; --card-bg: #1d2026; --border: #2a2d34; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px 16px 60px; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
  }}
  h1 {{ font-size: 1.3rem; margin: 0 0 4px; }}
  .updated {{ color: var(--muted); font-size: .85rem; margin-bottom: 24px; }}
  h2 {{ font-size: 1.05rem; margin: 28px 0 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .card-title {{ font-weight: 600; margin-bottom: 6px; }}
  .symbol {{ color: var(--muted); font-weight: 400; font-size: .85rem; }}
  .price {{ font-size: 1.1rem; margin-bottom: 8px; }}
  .card.up .change {{ color: var(--up); }}
  .card.down .change {{ color: var(--down); }}
  .row {{ font-size: .85rem; color: var(--muted); margin-top: 4px; }}
  .disclosures {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }}
  .disclosures-title {{ font-size: .78rem; color: var(--muted); margin-bottom: 4px; }}
  .disclosures ul {{ margin: 0; padding-left: 18px; font-size: .82rem; }}
  .disclosures li {{ margin-top: 2px; }}
  .disclosures a {{ color: inherit; }}
</style>
</head>
<body>
  <h1>주식 리포트</h1>
  <div class="updated">{date_str} 기준</div>
  {sections}
</body>
</html>
"""
