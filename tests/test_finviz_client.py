"""Finviz 스냅샷 파싱 - 색상 <span>으로 감싼 값도 읽어야 한다."""
from __future__ import annotations

from src.finviz_client import _parse_field

_CELL = (
    '<div class="snapshot-td-label">{label}</div></td>'
    '<td class="snapshot-td2" align="left"><div class="snapshot-td-content"><b>{value}</b></div></td>'
)


def test_plain_value():
    html = _CELL.format(label="EPS next Y", value="7.42")
    assert _parse_field(html, "EPS next Y") == 7.42


def test_span_wrapped_value():
    html = _CELL.format(label="Forward P/E", value='<span class="color-text is-negative">44.39</span>')
    assert _parse_field(html, "Forward P/E") == 44.39


def test_span_wrapped_percent_and_missing():
    html = _CELL.format(label="EPS next 5Y", value='<span class="color-text is-positive">76.36%</span>')
    html += _CELL.format(label="Beta", value="-")
    assert _parse_field(html, "EPS next 5Y") == 76.36
    assert _parse_field(html, "Beta") is None
