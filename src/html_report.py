"""정적 HTML 리포트 페이지 생성 (GitHub Pages 게시용)."""
from __future__ import annotations

import datetime as dt
import html
from typing import Callable, Dict, List

from config import RSI_PERIOD
from src.formatting import format_price, rsi_text, volume_text
from src.models import MarketItem
from src.signal import fair_value_line, trading_signal

DisclosureMap = Dict[str, List[dict]]


def _link_list_html(title: str, entries: List[dict], prefix: Callable[[dict], str]) -> str:
    """카드 하단의 링크 목록(최근 공시/관련 뉴스). 각 항목 앞에 prefix(entry)를 붙인다."""
    items = "\n".join(
        f'<li><a href="{html.escape(e["url"])}" target="_blank" rel="noopener">'
        f'{html.escape(prefix(e))} {html.escape(e["title"])}</a></li>'
        for e in entries
        if e.get("url")
    )
    if not items:
        return ""
    return f"""
      <div class="disclosures">
        <div class="disclosures-title">{title}</div>
        <ul>{items}</ul>
      </div>"""


def _item_card(item: MarketItem, disclosures: List[dict], news: List[dict]) -> str:
    direction = "up" if item.change_pct >= 0 else "down"
    valuation_rows = ""
    if item.market != "INDEX":
        valuation_rows = f"""
      <div class="row">{fair_value_line(item)}</div>"""
        signal = trading_signal(item)
        if signal:
            valuation_rows += f"""
      <div class="row">{html.escape(signal)}</div>"""
    return f"""
    <div class="card {direction}">
      <div class="card-title">{item.name} <span class="symbol">({item.symbol})</span></div>
      <div class="price">{format_price(item.current_price, item.unit)} <span class="change">({item.change_pct:+.2f}%)</span></div>
      <div class="row">RSI({RSI_PERIOD}) {rsi_text(item)}</div>
      <div class="row">{volume_text(item)}</div>{valuation_rows}
      {_link_list_html("최근 공시", disclosures, lambda d: d["date"].strftime("%m/%d"))}
      {_link_list_html("관련 뉴스", news, lambda n: f"[{n['source']}]")}
    </div>"""


def _section(
    title: str,
    items: List[MarketItem],
    disclosures_map: DisclosureMap,
    news_map: DisclosureMap,
) -> str:
    cards = "\n".join(
        _item_card(item, disclosures_map.get(item.symbol, []), news_map.get(item.symbol, []))
        for item in items
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
    us_news: DisclosureMap = None,
    kr_news: DisclosureMap = None,
    index_news: DisclosureMap = None,
) -> str:
    date_str = dt.date.today().strftime("%Y-%m-%d")
    kr_disclosures = kr_disclosures or {}
    us_filings = us_filings or {}
    us_news = us_news or {}
    kr_news = kr_news or {}
    index_news = index_news or {}
    sections = "\n".join(
        [
            _section("주요 지수", indices, {}, index_news),
            _section("미국 종목", us_stocks, us_filings, us_news),
            _section("국내 종목", kr_stocks, kr_disclosures, kr_news),
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
