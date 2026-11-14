"""투자지표(물가/국채 금리/달러/유가) 수집·표시 테스트 (네트워크 없이)."""
from __future__ import annotations

import datetime as dt

from src import macro_indicators as mi
from src.html_report import build_html_report


def test_inflation_mom_from_sa_yoy_from_nsa(monkeypatch):
    oct26, sep26, oct25 = dt.date(2026, 10, 1), dt.date(2026, 9, 1), dt.date(2025, 10, 1)
    data = {
        "PPIFIS": [(sep26, 100.0), (oct26, 100.3)],
        "PPIFID": [(oct25, 100.0), (oct26, 102.7)],
        "PPIFES": [(sep26, 200.0), (oct26, 200.4)],
        "PPICOR": [(oct26, 210.0)],  # 전년 동월 없음
    }
    monkeypatch.setattr(mi, "_fred_series", lambda sid, start: data[sid])
    monkeypatch.setattr(mi, "_alfred_series", lambda sid, start, vintage: [(sep26, 1.0)])

    ind = mi._inflation_indicator("PPI", dt.date(2026, 11, 14), {})

    assert ind.month == oct26
    head, core = ind.lines
    assert round(head.mom, 2) == 0.30 and round(head.yoy, 2) == 2.70
    assert round(core.mom, 2) == 0.20 and core.yoy is None
    assert head.consensus_mom is None and ind.upcoming is None


def test_inflation_first_release_vs_revised_and_consensus(monkeypatch):
    aug, sep, oct_ = dt.date(2026, 8, 1), dt.date(2026, 9, 1), dt.date(2026, 10, 1)
    current = [(aug, 157.482), (sep, 159.699), (oct_, 160.254)]
    first = [(aug, 157.662), (sep, 159.780)]  # 9월이 최신이던 시점(10/25) 값
    vintages = []

    def alfred(sid, start, vintage):
        vintages.append(vintage)
        return first

    monkeypatch.setattr(mi, "_fred_series", lambda sid, start: current)
    monkeypatch.setattr(mi, "_alfred_series", alfred)
    consensus = {"PPI": {
        "2026-10": {"release": "2026-11-13T08:30:00-05:00", "헤드라인": 0.4, "근원": 0.3},
        "2026-11": {"release": "2026-12-11T08:30:00-05:00", "헤드라인": 0.2},
    }}

    ind = mi._inflation_indicator("PPI", dt.date(2026, 11, 14), consensus)

    head = ind.lines[0]
    assert set(vintages) == {dt.date(2026, 10, 25)}
    assert round(head.prev_first_mom, 1) == 1.3 and round(head.prev_mom, 1) == 1.4
    assert head.consensus_mom == 0.4 and ind.lines[1].consensus_mom == 0.3
    assert ind.release == dt.datetime(2026, 11, 13, 8, 30, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    assert ind.upcoming.month == dt.date(2026, 11, 1)
    assert ind.upcoming.consensus_mom == {"헤드라인": 0.2, "근원": None}

    ind.phase = "released"
    page = build_html_report([], [], [], macro=mi.MacroIndicators([ind], []))
    assert "+1.3% → +1.4%" in page
    assert "11/13 22:30 KST 발표" in page

    ind.phase = "preview"
    page = build_html_report([], [], [], macro=mi.MacroIndicators([ind], []))
    assert "2026년 11월분 · 12/11 22:30 KST 발표 예정" in page
    assert "<th>헤드라인<br>전월비</th><td>+0.2%</td><td>+0.3%</td>" in page  # 예상, 직전 발표치
    assert "속보치" not in page


def test_first_release_unknown_when_release_was_delayed(monkeypatch):
    # 10/25 vintage에 9월이 아직 없으면(발표 지연) 속보치를 모른다
    monkeypatch.setattr(mi, "_alfred_series",
                        lambda sid, start, vintage: [(dt.date(2026, 8, 1), 1.0)])
    assert mi._first_release_rows("PPIFIS", dt.date(2026, 9, 1), dt.date(2025, 1, 1)) == []


def test_merge_consensus_maps_release_to_previous_month():
    events = [
        {"title": "CPI m/m", "country": "USD", "date": "2026-11-10T08:30:00-05:00", "forecast": "0.3%"},
        {"title": "Core CPI m/m", "country": "USD", "date": "2026-11-10T08:30:00-05:00", "forecast": "0.2%"},
        {"title": "PPI m/m", "country": "USD", "date": "2026-11-13T08:30:00-05:00", "forecast": ""},
        {"title": "CPI y/y", "country": "CNY", "date": "2026-11-08T20:30:00-05:00", "forecast": "0.8%"},
    ]
    cache = mi.merge_consensus({"CPI": {"2026-09": {"헤드라인": 0.6}}}, events)

    assert cache == {"CPI": {
        "2026-09": {"헤드라인": 0.6},
        "2026-10": {"release": "2026-11-10T08:30:00-05:00", "헤드라인": 0.3, "근원": 0.2},
    }}


def test_load_consensus_keeps_cache_when_ff_fails(monkeypatch, tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"CPI": {"2026-10": {"헤드라인": 0.3}}}', encoding="utf-8")

    def boom():
        raise RuntimeError("429")

    monkeypatch.setattr(mi, "_ff_events", boom)

    assert mi.load_consensus(path) == {"CPI": {"2026-10": {"헤드라인": 0.3}}}


def test_treasury_uses_last_two_days_and_prev_year_in_january(monkeypatch):
    rows = {
        2027: [{"Date": "01/02/2027", "2 Yr": "4.00", "10 Yr": "4.50", "30 Yr": "4.90"}],
        2026: [
            {"Date": "12/31/2026", "2 Yr": "3.90", "10 Yr": "4.40", "30 Yr": "4.80"},
            {"Date": "12/30/2026", "2 Yr": "3.80", "10 Yr": "4.30", "30 Yr": ""},
        ],
    }
    monkeypatch.setattr(mi, "_treasury_rows", lambda year: rows[year])

    result = {r.name: r for r in mi.fetch_treasury_yields(dt.date(2027, 1, 3))}

    two = result["미국채 2년"]
    assert (two.value, two.prev, two.as_of) == (4.00, 3.90, dt.date(2027, 1, 2))
    assert round(two.change_bp) == 10


def test_report_places_macro_section_between_indices_and_us_stocks():
    macro = mi.MacroIndicators(
        inflation=[
            mi.InflationIndicator(
                "CPI", dt.date(2026, 10, 1),
                [mi.InflationLine("헤드라인", 0.35, None), mi.InflationLine("근원", 0.30, None)],
                prev_month=dt.date(2026, 9, 1),
            )
        ],
        rates=[
            mi.RateIndicator("미국채 10년", "10 Yr", 5.15, 5.10, dt.date(2026, 11, 13), "%"),
            mi.RateIndicator(
                "WTI 유가", "CL=F", 88.56, 88.74,
                dt.datetime(2026, 11, 13, 17, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5))), "$",
            ),
        ],
    )
    page = build_html_report([], [], [], macro=macro)

    assert page.index("주요 지수") < page.index("투자지표") < page.index("미국 종목")
    assert "<th>헤드라인<br>전월비</th><td>-</td><td>+0.3%</td>" in page
    assert "전년 동월 지수 미발표" in page
    assert "미국채 금리" in page
    assert '<tr><th>10년</th><td>5.15%</td><td class="up">+5bp (+0.98%)</td><td>5.10%</td></tr>' in page
    assert "국제 유가" in page
    assert '<tr><th>WTI</th><td>$88.56</td><td class="down">-0.20%</td><td>$88.74</td></tr>' in page
    assert "11/13 종가 기준" in page  # 재무부 대체값은 날짜만
    assert "11/14 07:00 KST 기준" in page  # 실시간 값은 한국 시각


def test_report_without_macro_has_no_section():
    assert "투자지표" not in build_html_report([], [], [])


def test_live_yields_compute_change_from_last_and_prev_close(monkeypatch):
    def q(symbol, last, prev):
        # CNBC change_pct는 부호가 틀리기도 해서 일부러 엉뚱한 값을 넣어 무시되는지 본다
        return {"symbol": symbol, "last": last, "previous_day_closing": prev,
                "change_pct": "+9.99%", "last_time": "2026-11-13T17:05:00.000-0500"}

    monkeypatch.setattr(mi, "_cnbc_quotes", lambda symbols: [
        q("US30Y", "5.47%", "5.43%"), q("US2Y", "4.852%", "4.864%"), q("US10Y", "5.139%", "5.103%"),
    ])

    result = mi.fetch_live_treasury_yields()

    assert [r.name for r in result] == ["미국채 2년", "미국채 10년", "미국채 30년"]
    assert result[0].change_pct < 0 and round(result[0].change_bp, 1) == -1.2
    assert result[0].as_of == dt.datetime(2026, 11, 14, 7, 5, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def test_yields_fall_back_to_treasury_when_cnbc_fails(monkeypatch):
    def boom():
        raise RuntimeError("blocked")

    monkeypatch.setattr(mi, "fetch_live_treasury_yields", boom)
    monkeypatch.setattr(mi, "fetch_treasury_yields", lambda today: ["treasury"])

    assert mi._treasury_yields(dt.date(2026, 11, 14)) == ["treasury"]


def _series(points, tz):
    import pandas as pd
    return pd.DataFrame(
        {"Close": [v for _, v in points]},
        index=pd.DatetimeIndex([t for t, _ in points]).tz_localize(tz),
    )


def test_market_prev_close_when_today_bar_not_created_yet(monkeypatch):
    """일요일 저녁 선물 거래: 일봉은 금요일까지만 있으면 금요일 종가가 전일 종가."""
    daily = _series([(dt.datetime(2026, 11, 12), 88.74), (dt.datetime(2026, 11, 13), 88.56)],
                    "America/New_York")
    intraday = _series([(dt.datetime(2026, 11, 15, 18, 5), 89.10)], "America/New_York")
    monkeypatch.setattr(mi, "price_history",
                        lambda t, period, interval: daily if interval == "1d" else intraday)

    ind = mi._market_indicator("CL=F")

    assert (ind.value, ind.prev) == (89.10, 88.56)


def test_market_prev_close_when_today_bar_exists(monkeypatch):
    daily = _series([(dt.datetime(2026, 11, 12), 88.74), (dt.datetime(2026, 11, 13), 88.56)],
                    "America/New_York")
    intraday = _series([(dt.datetime(2026, 11, 13, 10, 0), 88.60)], "America/New_York")
    monkeypatch.setattr(mi, "price_history",
                        lambda t, period, interval: daily if interval == "1d" else intraday)

    ind = mi._market_indicator("CL=F")

    assert (ind.value, ind.prev) == (88.60, 88.74)


def test_initial_claims_latest_week_vs_previous(monkeypatch):
    monkeypatch.setattr(mi, "_fred_series", lambda sid, start: [
        (dt.date(2026, 10, 24), 195000.0), (dt.date(2026, 10, 31), 191000.0),
        (dt.date(2026, 11, 7), 200000.0),
    ])
    consensus = {"Claims": {"2026-11-07": {"release": "2026-11-12T08:30:00-05:00", "forecast": 194000.0}}}

    ind = mi.fetch_initial_claims(dt.date(2026, 11, 14), consensus)

    assert (ind.week_end, ind.value, ind.prev, ind.change) == (
        dt.date(2026, 11, 7), 200000.0, 191000.0, 9000.0
    )
    assert ind.consensus == 194000.0
    # 다음 주 일정은 아직 없어 목요일 08:30(미 동부)로 본다
    assert ind.next_release.astimezone(mi.KST) == dt.datetime(2026, 11, 19, 22, 30, tzinfo=mi.KST)

    ind.phase = "released"
    page = build_html_report([], [], [], macro=mi.MacroIndicators([], [], ind))
    assert "200,000건 <span class=\"change\">(+9,000건, +4.71%)" in page
    assert "예상 194,000건, 전주 191,000건" in page
    assert "11/07 마감 주간 · 11/12 22:30 KST 발표" in page

    ind.phase = "preview"
    page = build_html_report([], [], [], macro=mi.MacroIndicators([], [], ind))
    assert "예상 -" in page and "11/14 마감 주간 · 11/19 22:30 KST 발표 예정" in page


def test_merge_consensus_claims_keyed_by_week_end():
    events = [{"title": "Unemployment Claims", "country": "USD",
               "date": "2026-11-12T08:30:00-05:00", "forecast": "194K"}]
    assert mi.merge_consensus({}, events) == {"Claims": {
        "2026-11-07": {"release": "2026-11-12T08:30:00-05:00", "forecast": 194000.0},
    }}


def _kst(*args):
    return dt.datetime(*args, tzinfo=mi.KST)


def test_release_phase_release_day_and_next_day_only():
    release = _kst(2026, 11, 10, 22, 30)  # 미 동부 08:30
    assert mi.release_phase(_kst(2026, 11, 9, 21, 30), release) is None  # 전날
    assert mi.release_phase(_kst(2026, 11, 10, 8, 0), release) == "preview"
    assert mi.release_phase(_kst(2026, 11, 10, 21, 30), release) == "preview"
    assert mi.release_phase(_kst(2026, 11, 11, 8, 0), release) == "released"
    assert mi.release_phase(_kst(2026, 11, 11, 21, 30), release) == "released"
    assert mi.release_phase(_kst(2026, 11, 12, 8, 0), release) is None  # 이틀 뒤
    assert mi.release_phase(_kst(2026, 11, 12, 8, 0), None) is None
    # 주 초부터 미리 보기: 11/10(화) 발표면 11/9(월)부터, 전 주 토요일은 아님
    assert mi.release_phase(_kst(2026, 11, 9, 8, 0), release, preview_from_week_start=True) == "preview"
    assert mi.release_phase(_kst(2026, 11, 7, 6, 0), release, preview_from_week_start=True) is None


def test_inflation_phase_prefers_upcoming_preview():
    ind = mi.InflationIndicator(
        "CPI", dt.date(2026, 10, 1), [],
        release=_kst(2026, 11, 10, 22, 30),
        upcoming=mi.UpcomingRelease(dt.date(2026, 11, 1), _kst(2026, 12, 10, 22, 30), {}),
    )
    assert mi._inflation_phase(ind, _kst(2026, 11, 11, 8, 0)) == "released"
    assert mi._inflation_phase(ind, _kst(2026, 11, 20, 8, 0)) is None
    assert mi._inflation_phase(ind, _kst(2026, 12, 10, 17, 0)) == "preview"
    # 12/10(목) 발표 -> 그 주 월요일(12/7)부터 예상치, 전 주 금요일은 표시 안 함
    assert mi._inflation_phase(ind, _kst(2026, 12, 7, 8, 0)) == "preview"
    assert mi._inflation_phase(ind, _kst(2026, 12, 4, 21, 30)) is None
    # 발표 시각이 지났는데 FRED가 아직 갱신 전이면 계속 예상치로
    assert mi._inflation_phase(ind, _kst(2026, 12, 11, 8, 0)) == "preview"
