"""SEC 최근 분기 EPS - 실적 발표 보도자료(8-K) 파싱과 XBRL 검증값."""
from __future__ import annotations

import datetime as dt

from src.sec_eps import _Fact, _release_context, _xbrl_latest_quarter, quarter_eps_from_release


def _fact(start: str, end: str, val: float, filed: str = "2026-06-03") -> _Fact:
    return _Fact(dt.date.fromisoformat(start), dt.date.fromisoformat(end), val, dt.date.fromisoformat(filed))


# 코스트코 실제 공시값 (52/53주 회계연도, FY2026 3분기 10-Q까지)
COST_FACTS = [
    _fact("2024-09-02", "2024-11-24", 4.04),
    _fact("2024-09-02", "2025-02-16", 8.06),
    _fact("2024-09-02", "2025-05-11", 12.34),
    _fact("2024-09-02", "2025-08-31", 18.21, "2025-10-08"),
    _fact("2025-09-01", "2025-11-23", 4.50),
    _fact("2025-09-01", "2026-02-15", 9.08),
    _fact("2025-11-24", "2026-02-15", 4.58),
    _fact("2025-09-01", "2026-05-10", 14.01),
    _fact("2026-02-16", "2026-05-10", 4.93),
]


def test_context_after_quarterly_report():
    context = _release_context(COST_FACTS)
    assert round(context.year_ago_quarter, 2) == 5.87  # FY25 4분기 = 18.21 - 12.34
    assert context.prior_ytd == 14.01


def test_context_after_annual_report_is_first_quarter():
    facts = COST_FACTS + [_fact("2025-09-01", "2026-08-30", 20.76, "2026-10-08")]
    context = _release_context(facts)
    assert context.year_ago_quarter == 4.50  # 다음 발표(FY27 1분기)의 전년 동분기
    assert context.prior_ytd is None


def test_xbrl_latest_quarter():
    assert _xbrl_latest_quarter(COST_FACTS) == 4.93
    facts = COST_FACTS + [_fact("2025-09-01", "2026-08-30", 20.76, "2026-10-08")]
    assert round(_xbrl_latest_quarter(facts), 2) == 6.75  # 20.76 - 14.01


def _table(*rows: list[str]) -> str:
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    ) + "</table>"


def test_current_first_layout():
    # 코스트코: 이번 분기, 전년 분기, 올해 누적, 전년 누적
    doc = _table(
        ["Diluted", "$", "6.75", "$", "5.87", "$", "20.76", "$", "18.21"],
        ["Diluted", "444,364", "444,706", "444,427", "444,803"],
    )
    assert quarter_eps_from_release(doc, 5.87, 14.01) == 6.75


def test_prior_year_first_layout_and_trend_table():
    # 아마존: 전년/올해 순서 표 뒤에, 오래된 분기부터 나열한 추이표가 따로 있다
    doc = _table(
        ["Net income per diluted share", "$", "1.59", "$", "1.68", "$", "1.95", "$", "1.95", "$", "2.78", "$", "5.75"],
        ["Diluted earnings per share", "$", "1.68", "$", "5.75", "$", "3.27", "$", "8.53"],
    )
    assert quarter_eps_from_release(doc, 1.68, 2.78) == 5.75


def test_negative_values_and_percent_columns():
    doc = _table(["Diluted Net Income (Loss) Per Share", "$43.97", "$(0.16)", "*", "$39.25", "up 91.5%"])
    assert quarter_eps_from_release(doc, -0.16, None) == 43.97


def test_unconfirmed_layout_is_rejected():
    doc = _table(["Diluted", "$", "2.10", "$", "1.90"])
    assert quarter_eps_from_release(doc, 5.87, 14.01) is None



def test_naver_target_pe_is_target_price_over_consensus_eps():
    from src.naver_finance_client import target_pe_from_integration

    data = {
        "consensusInfo": {"priceTargetMean": "493,864"},
        "totalInfos": [{"code": "cnsPer", "value": "5.98배"}, {"code": "cnsEps", "value": "47,922원"}],
    }
    assert round(target_pe_from_integration(data), 2) == 10.31
    assert target_pe_from_integration({"consensusInfo": None, "totalInfos": []}) is None
