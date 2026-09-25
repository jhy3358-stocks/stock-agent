"""DART 정기보고서 EPS - 최신 보고서 탐색과 4분기(연간 - 3분기 누적) 계산."""
from __future__ import annotations

import datetime as dt

import src.dart_client as dart


def _eps_rows(current: str, cumulative: str = "") -> list[dict]:
    return [
        {"sj_div": "IS", "account_id": "dart_DilutedEarningsLossPerSharePreferredStock",
         "thstrm_amount": "1", "thstrm_add_amount": "1"},
        {"sj_div": "IS", "account_id": "ifrs-full_DilutedEarningsLossPerShare",
         "thstrm_amount": current, "thstrm_add_amount": cumulative},
    ]


def _fake(reports: dict):
    return lambda api_key, corp_code, year, report_code: reports.get((year, report_code), [])


def test_latest_half_year_report(monkeypatch):
    monkeypatch.setattr(dart, "_fetch_financials", _fake({(2026, "11012"): _eps_rows("10,733", "17,768")}))
    assert dart.fetch_latest_quarter_eps("k", "c", dt.date(2026, 9, 25)) == (10733.0, "2026년 2분기")


def test_fourth_quarter_is_annual_minus_q3_cumulative(monkeypatch):
    monkeypatch.setattr(dart, "_fetch_financials", _fake({
        (2025, "11011"): _eps_rows("6,000"),
        (2025, "11014"): _eps_rows("1,500", "4,200"),
    }))
    assert dart.fetch_latest_quarter_eps("k", "c", dt.date(2026, 3, 20)) == (1800.0, "2025년 4분기")


def test_request_error_does_not_leak_api_key(monkeypatch):
    import pytest
    import requests

    calls = []

    def timeout(url, params, timeout):
        calls.append(url)
        raise requests.ConnectTimeout(f"{url}?crtfc_key={params['crtfc_key']}")

    monkeypatch.setattr(dart.requests, "get", timeout)
    with pytest.raises(RuntimeError) as err:
        dart._fetch_financials("SECRET-KEY", "c", 2026, "11012")
    assert "SECRET-KEY" not in str(err.value)
    assert "ConnectTimeout" in str(err.value)
    assert len(calls) == dart.REQUEST_ATTEMPTS
