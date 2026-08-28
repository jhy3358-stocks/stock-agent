"""Finviz 스냅샷 페이지에서 Forward P/E, Forward EPS(EPS next Y)를 스크래핑."""
from __future__ import annotations

import re
from typing import Optional

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}

# Finviz 종목 스냅샷 페이지는 각 항목이 아래 형태의 고정 마크업으로 렌더링된다:
# <div class="snapshot-td-label">{label}</div></td><td ...><div class="snapshot-td-content"><b>{value}</b>
_FIELD_PATTERN = (
    r'snapshot-td-label">{label}</div></td>'
    r'<td[^>]*><div class="snapshot-td-content"><b>([^<]*)</b>'
)


def _parse_field(html: str, label: str) -> Optional[float]:
    match = re.search(_FIELD_PATTERN.format(label=re.escape(label)), html)
    if not match:
        return None
    raw = match.group(1).strip().rstrip("%")
    if raw in ("-", ""):
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def fetch_forward_metrics(ticker: str) -> dict:
    """{'forward_pe': float|None, 'forward_eps': float|None}.

    Finviz는 국내(KRX) 종목을 다루지 않고, 미국 종목도 페이지 구조 변경이나
    차단으로 실패할 수 있어 예외 상황에서는 항상 None을 채워 반환한다.
    """
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        return {"forward_pe": None, "forward_eps": None}

    html = resp.text
    return {
        "forward_pe": _parse_field(html, "Forward P/E"),
        "forward_eps": _parse_field(html, "EPS next Y"),
    }
