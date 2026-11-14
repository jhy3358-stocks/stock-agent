"""정적 HTML 리포트 페이지 생성 (GitHub Pages 게시용)."""
from __future__ import annotations

import datetime as dt
import html
from typing import Callable, Dict, List

from config import RSI_PERIOD
from src.formatting import format_price, rsi_text, volume_text
from src.macro_indicators import (
    ClaimsIndicator,
    InflationIndicator,
    MacroIndicators,
    RateIndicator,
)
from src.models import MarketItem
from src.signal import fair_value_line, grav_readiness_line, trading_signal

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
        readiness = grav_readiness_line(item)
        if readiness:
            valuation_rows += f"""
      <div class="row">{html.escape(readiness)}</div>"""
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


def _signed(value, suffix: str) -> str:
    return "-" if value is None else f"{value:+.1f}{suffix}"


def _revision_text(first, revised) -> str:
    """속보치 -> 수정치. 반올림 후 같거나 속보치를 모르면 수정치 하나만."""
    if first is None or revised is None or f"{first:+.1f}" == f"{revised:+.1f}":
        return _signed(revised, "%")
    return f"{_signed(first, '%')} → {_signed(revised, '%')}"


def _inflation_preview_card(ind: InflationIndicator) -> str:
    """발표일 발표 전: 이번 발표 예상치와 직전 발표치."""
    up = ind.upcoming
    month, last = f"{up.month.month}월", f"{ind.month.month}월"
    body = ""
    for line in ind.lines:
        body += (
            f"<tr><th>{line.label}<br>전월비</th>"
            f"<td>{_signed(up.consensus_mom.get(line.label), '%')}</td>"
            f"<td>{_signed(line.mom, '%')}</td></tr>"
            f"<tr><th>{line.label}<br>전년비</th><td>-</td><td>{_signed(line.yoy, '%')}</td></tr>"
        )
    return f"""
    <div class="card">
      <div class="card-title">미국 {ind.name} <span class="symbol">({up.month.year}년 {month}분 · {_kst(up.release)} 발표 예정)</span></div>
      <div class="table-wrap"><table class="macro">
        <tr><th></th><th>{month}<br>예상치</th><th>{last}<br>발표치</th></tr>
        {body}
      </table></div>
    </div>"""


def _inflation_card(ind: InflationIndicator) -> str:
    if ind.phase == "preview" and ind.upcoming:
        return _inflation_preview_card(ind)
    month, prev = f"{ind.month.month}월", f"{ind.prev_month.month}월"
    body = ""
    for line in ind.lines:
        body += (
            f"<tr><th>{line.label}<br>전월비</th><td>{_signed(line.consensus_mom, '%')}</td>"
            f"<td>{_signed(line.mom, '%')}</td>"
            f"<td>{_revision_text(line.prev_first_mom, line.prev_mom)}</td></tr>"
            f"<tr><th>{line.label}<br>전년비</th><td>-</td>"
            f"<td>{_signed(line.yoy, '%')}</td>"
            f"<td>{_revision_text(line.prev_first_yoy, line.prev_yoy)}</td></tr>"
        )
    released = f" · {_kst(ind.release)} 발표" if ind.release else ""
    notes = ""
    if any(line.yoy is None for line in ind.lines):
        # 예: 2025-10 CPI는 셧다운으로 미발표라 2026-10 전년비를 계산할 수 없다
        notes += '<div class="row">전년비 -: 전년 동월 지수 미발표</div>'
    return f"""
    <div class="card wide">
      <div class="card-title">미국 {ind.name} <span class="symbol">({ind.month.year}년 {month}분{released})</span></div>
      <div class="table-wrap"><table class="macro">
        <tr><th></th><th>예상치</th><th>{month}<br>속보치</th><th>{prev} 속보치<br>→ 수정치</th></tr>
        {body}
      </table></div>
      <div class="row">화살표가 없으면 수정 없음</div>{notes}
    </div>"""


def _count(value) -> str:
    return "-" if value is None else f"{value:,.0f}건"


def _claims_card(ind: ClaimsIndicator) -> str:
    title = '<div class="card-title">미국 신규 실업수당 청구 <span class="symbol">(ICSA)</span></div>'
    if ind.phase == "preview":
        return f"""
    <div class="card">
      {title}
      <div class="price">예상 {_count(ind.next_consensus)}</div>
      <div class="row">{ind.next_week_end:%m/%d} 마감 주간 · {_kst(ind.next_release)} 발표 예정</div>
      <div class="row">직전 {_count(ind.value)} ({ind.week_end:%m/%d} 마감 주간)</div>
    </div>"""
    direction = "up" if ind.change >= 0 else "down"
    return f"""
    <div class="card {direction}">
      {title}
      <div class="price">{ind.value:,.0f}건 <span class="change">({ind.change:+,.0f}건, {ind.change_pct:+.2f}%)</span></div>
      <div class="row">예상 {_count(ind.consensus)}, 전주 {ind.prev:,.0f}건</div>
      <div class="row">{ind.week_end:%m/%d} 마감 주간 · {_kst(ind.release)} 발표</div>
    </div>"""


KST = dt.timezone(dt.timedelta(hours=9))


def _kst(moment: dt.datetime) -> str:
    return f"{moment.astimezone(KST):%m/%d %H:%M} KST"


def _as_of_text(as_of) -> str:
    """실시간 값은 한국 시간 시각, 종가 대체값은 날짜만."""
    if isinstance(as_of, dt.datetime):
        return f"{as_of.astimezone(KST):%m/%d %H:%M} KST 기준"
    return f"{as_of:%m/%d} 종가 기준"


def _rate_card(ind: RateIndicator) -> str:
    direction = "up" if ind.value >= ind.prev else "down"
    if ind.unit == "%":
        value = f"{ind.value:.2f}%"
        change = f"{ind.change_bp:+.0f}bp, {ind.change_pct:+.2f}%"
    else:
        value = format_price(ind.value, ind.unit)
        change = f"{ind.change_pct:+.2f}%"
    return f"""
    <div class="card {direction}">
      <div class="card-title">{ind.name} <span class="symbol">({html.escape(ind.symbol)})</span></div>
      <div class="price">{value} <span class="change">({change})</span></div>
      <div class="row">{_as_of_text(ind.as_of)}, 전일 종가 {ind.prev:.2f}</div>
    </div>"""


def _rate_table_card(title: str, items: List[RateIndicator], label_header: str, label) -> str:
    """같은 종류 지표(미국채 만기별, 유종별)를 한 카드에 한 행씩."""

    def value(ind: RateIndicator) -> str:
        return f"{ind.value:.2f}%" if ind.unit == "%" else format_price(ind.value, ind.unit)

    def change(ind: RateIndicator) -> str:
        if ind.unit == "%":
            return f"{ind.change_bp:+.0f}bp ({ind.change_pct:+.2f}%)"
        return f"{ind.change_pct:+.2f}%"

    def prev(ind: RateIndicator) -> str:
        return f"{ind.prev:.2f}%" if ind.unit == "%" else format_price(ind.prev, ind.unit)

    rows = "".join(
        f'<tr><th>{label(i)}</th><td>{value(i)}</td>'
        f'<td class="{"up" if i.value >= i.prev else "down"}">{change(i)}</td><td>{prev(i)}</td></tr>'
        for i in items
    )
    # 항목별 시각이 몇 분씩 다를 수 있어 가장 늦은 시각을 대표로 쓴다
    as_of = max(i.as_of for i in items)
    return f"""
    <div class="card wide">
      <div class="card-title">{title}</div>
      <div class="table-wrap"><table class="macro nowrap">
        <tr><th>{label_header}</th><th>{"금리" if items[0].unit == "%" else "가격"}</th><th>전일 대비</th><th>전일 종가</th></tr>
        {rows}
      </table></div>
      <div class="row">{_as_of_text(as_of)}</div>
    </div>"""


OIL_LABELS = {"CL=F": "WTI", "BZ=F": "브렌트유"}


def _macro_section(macro: MacroIndicators) -> str:
    if not macro or not (macro.inflation or macro.rates or macro.claims):
        return ""
    yields = [r for r in macro.rates if r.unit == "%"]
    oil = [r for r in macro.rates if r.symbol in OIL_LABELS]
    others = [r for r in macro.rates if r not in yields and r not in oil]
    cards = "\n".join(
        [_inflation_card(i) for i in macro.inflation]
        + ([_claims_card(macro.claims)] if macro.claims else [])
        + ([_rate_table_card("미국채 금리", yields, "만기", lambda y: y.name.replace("미국채 ", ""))]
           if yields else [])
        + [_rate_card(r) for r in others]
        + ([_rate_table_card("국제 유가", oil, "유종", lambda o: OIL_LABELS[o.symbol])] if oil else [])
    )
    return f"""
    <section>
      <h2>투자지표</h2>
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
    macro: MacroIndicators = None,
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
            _macro_section(macro),
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
  .card {{ min-width: 0; background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
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
  @media (min-width: 520px) {{ .card.wide {{ grid-column: span 2; }} }}
  table.macro {{ width: 100%; border-collapse: collapse; font-size: .8rem; margin-top: 6px; }}
  table.macro th, table.macro td {{ padding: 3px 4px; text-align: right; border-top: 1px solid var(--border); white-space: nowrap; }}
  table.macro tr:first-child th {{ border-top: none; color: var(--muted); font-weight: 500; white-space: normal; vertical-align: bottom; }}
  .table-wrap {{ overflow-x: auto; }}
  table.macro.nowrap tr:first-child th {{ white-space: nowrap; }}
  table.macro td.up {{ color: var(--up); }}
  table.macro td.down {{ color: var(--down); }}
  table.macro th:first-child {{ text-align: left; font-weight: 500; }}
</style>
</head>
<body>
  <h1>주식 리포트</h1>
  <div class="updated">{date_str} 기준</div>
  {sections}
</body>
</html>
"""
