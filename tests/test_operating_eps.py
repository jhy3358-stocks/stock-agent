"""영업이익 기반 EPS - 보도자료 영업이익 파싱, 분기 일수, DART 역산."""
from __future__ import annotations

import datetime as dt

import src.dart_client as dart
from src.sec_eps import _Fact
from src.sec_operating_eps import _quarter_days, operating_income_from_release


def _table(*rows):
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    ) + "</table>"


def test_release_operating_income_in_millions_skips_segment_rows():
    # 아마존처럼 사업부별 영업이익 행이 먼저 나와도 전년 동분기 연결 영업이익이 있는 행만 인정
    doc = _table(
        ["Operating income", "$", "7,100", "$", "5,200"],          # 사업부
        ["Operating income", "$", "19,171", "$", "27,461"],        # 연결 (전년, 올해 순서)
    )
    assert operating_income_from_release(doc, 19_171e6, None) == 27_461e6


def test_release_operating_income_confirms_ytd():
    doc = _table(["Operating income", "3,801", "3,341", "11,685", "10,383"])  # 코스트코 16주/52주
    assert operating_income_from_release(doc, 3_341e6, 7_884e6) == 3_801e6


def test_quarter_days_from_cumulative_difference():
    d = dt.date.fromisoformat
    facts = [
        _Fact(d("2024-09-02"), d("2025-05-11"), 1.0, d("2025-06-05")),
        _Fact(d("2024-09-02"), d("2025-08-31"), 1.0, d("2025-10-08")),
    ]
    assert _quarter_days(facts, d("2025-08-31")) == 112  # 코스트코 4분기 16주


def test_dart_operating_eps_uses_implied_shares(monkeypatch):
    def row(account_id, current, cumulative=""):
        return {"sj_div": "IS", "account_id": account_id, "thstrm_amount": current, "thstrm_add_amount": cumulative}

    rows = [
        row("dart_OperatingIncomeLoss", "1,000", "1,800"),
        row("ifrs-full_IncomeTaxExpenseContinuingOperations", "200", "400"),
        row("ifrs-full_ProfitLossBeforeTax", "1,000", "2,000"),
        row("ifrs-full_ProfitLossAttributableToOwnersOfParent", "800", "1,600"),
        row("ifrs-full_DilutedEarningsLossPerShare", "8", "16"),
    ]
    monkeypatch.setattr(dart, "_fetch_financials",
                        lambda k, c, year, code: rows if (year, code) == (2026, "11012") else [])
    eps, label = dart.fetch_latest_quarter_operating_eps("k", "c", dt.date(2026, 9, 26))
    # 주식수 1,600/16 = 100, 세율 20% -> 1,000 x 0.8 / 100 x 4 = 32
    assert (round(eps, 6), label) == (32.0, "2026년 2분기")
