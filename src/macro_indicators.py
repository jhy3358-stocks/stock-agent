"""투자지표(미국 물가·국채 금리·달러 인덱스·유가) 수집.

- 물가(CPI/PPI): FRED 공개 CSV(API 키 불필요). 월간 지표라 가장 최근 발표월 값을 보여준다.
  BLS 발표 관행대로 전월비는 계절조정(SA), 전년비는 원계열(NSA) 시리즈로 계산한다.
  가장 최근 발표월은 예상치(시장 컨센서스, ForexFactory)와 속보치를, 그 전월은 속보치(ALFRED
  vintage로 처음 발표된 값)와 수정치(현재 값)를 함께 보여준다. PPI는 발표 후 4개월간 수정되고,
  CPI는 계절조정 계열만 연 1회 수정된다. 값은 지수로 직접 계산해 BLS 발표 반올림과 0.1%p
  다를 수 있다.
    CPI 헤드라인 CPIAUCSL / CPIAUCNS, 근원(식품·에너지 제외) CPILFESL / CPILFENS
    PPI 헤드라인(최종수요) PPIFIS / PPIFID, 근원(식품·에너지 제외) PPIFES / PPICOR
- 신규 실업수당 청구 건수: FRED ICSA(주간, 계절조정). 매주 목요일 발표되는 직전 주(토요일
  마감) 값과 전주 대비 증감, 예상치(ForexFactory)를 보여준다.
- 물가·실업수당은 발표일(한국 날짜) 리포트(발표 전: 예상치)와 그다음 날 리포트(발표치)에만
  넣는다. 발표 시각은 ForexFactory 일정에서 받고(컨센서스 캐시에 함께 저장), 실업수당은 일정을
  못 받으면 목요일 08:30(미 동부)으로 본다. CPI·PPI는 일정을 못 받으면 표시하지 않는다.
- 국채 금리(2년/10년/30년): 리포트 발송 시점의 실시간 값을 CNBC 시세(US2Y/US10Y/US30Y)로
  받는다. 국채는 아시아·유럽 시간에도 거래돼 한국 시간 08:00/17:00/21:30 어느 때든 그 시점
  금리가 나온다. Yahoo는 2년물 금리 티커가 없어 쓰지 않는다. CNBC 조회가 실패하면 미 재무부
  일별 Par Yield Curve CSV의 최근 종가로 대체한다(FRED DGS*는 하루 늦게 올라와 쓰지 않는다).
  CNBC 응답의 change_pct는 부호가 틀리는 경우가 있어(2026-11-13 US2Y 하락인데 +) 등락은
  last와 previous_day_closing으로 직접 계산한다.
- 달러 인덱스(DX-Y.NYB), WTI(CL=F), 브렌트(BZ=F): yfinance 5분봉의 마지막 값(발송 시점 시세,
  유가는 근월물 선물)을 쓰고, 전일 종가는 일봉에서 가져온다.

조회 하나가 실패해도 리포트 전체가 멈추지 않도록 항목별로 실패를 격리한다(빈 값으로 대체).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union
from zoneinfo import ZoneInfo

import requests

from src.concurrency import fetch_all, safe_call
from src.yf_data import price_history

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ALFRED_CSV_URL = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
CNBC_QUOTE_URL = "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
TREASURY_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
)
HTTP_TIMEOUT = 20
KST = dt.timezone(dt.timedelta(hours=9))
ET = ZoneInfo("America/New_York")

# (표시명, 전월비용 SA 시리즈, 전년비용 NSA 시리즈)
INFLATION_SERIES = {
    "CPI": (("헤드라인", "CPIAUCSL", "CPIAUCNS"), ("근원", "CPILFESL", "CPILFENS")),
    "PPI": (("헤드라인", "PPIFIS", "PPIFID"), ("근원", "PPIFES", "PPICOR")),
}

# 재무부 CSV 컬럼명 -> 표시명
TREASURY_TENORS = {"2 Yr": "미국채 2년", "10 Yr": "미국채 10년", "30 Yr": "미국채 30년"}
# CNBC 심볼 -> 재무부 CSV 컬럼명
CNBC_TENORS = {"US2Y": "2 Yr", "US10Y": "10 Yr", "US30Y": "30 Yr"}

MARKET_TICKERS = {
    "DX-Y.NYB": ("달러 인덱스", "pt"),
    "CL=F": ("WTI 유가", "$"),
    "BZ=F": ("브렌트유", "$"),
}


@dataclass
class InflationLine:
    """헤드라인/근원 한 줄. 값은 모두 % (없으면 None)."""

    label: str  # 헤드라인 / 근원
    mom: Optional[float]  # 기준월 전월비(속보치)
    yoy: Optional[float]  # 기준월 전년비(속보치)
    consensus_mom: Optional[float] = None  # 기준월 전월비 예상치(시장 컨센서스)
    prev_first_mom: Optional[float] = None  # 전월 전월비 속보치(처음 발표된 값)
    prev_mom: Optional[float] = None  # 전월 전월비 수정치(현재 값)
    prev_first_yoy: Optional[float] = None
    prev_yoy: Optional[float] = None


@dataclass
class UpcomingRelease:
    """다음 발표 예정(이번 주 일정에 잡힌 경우)과 그 예상치."""

    month: dt.date  # 대상월
    release: dt.datetime
    consensus_mom: Dict[str, Optional[float]]  # {"헤드라인": 0.3, "근원": 0.2}


@dataclass
class InflationIndicator:
    name: str  # CPI / PPI
    month: dt.date  # 기준월(1일): 가장 최근 발표분
    lines: List[InflationLine]
    prev_month: Optional[dt.date] = None
    release: Optional[dt.datetime] = None  # 기준월 발표 시각(컨센서스 캐시에 있을 때)
    upcoming: Optional[UpcomingRelease] = None
    # 리포트에 보일 때: "preview"(발표 당일, 발표 전 - 예상치), "released"(발표 후 - 발표치)
    phase: Optional[str] = None


@dataclass
class ClaimsIndicator:
    """신규 실업수당 청구 건수(주간)."""

    week_end: dt.date  # 집계 주 마감일(토)
    value: float
    prev: float  # 전주
    release: Optional[dt.datetime] = None  # week_end 주 발표 시각
    consensus: Optional[float] = None  # week_end 주 예상치(건)
    next_week_end: Optional[dt.date] = None
    next_release: Optional[dt.datetime] = None
    next_consensus: Optional[float] = None
    phase: Optional[str] = None  # InflationIndicator.phase와 같음

    @property
    def change(self) -> float:
        return self.value - self.prev

    @property
    def change_pct(self) -> float:
        return (self.value / self.prev - 1) * 100


@dataclass
class RateIndicator:
    """전일 대비 등락이 있는 지표(국채 금리, 달러 인덱스, 유가)."""

    name: str
    symbol: str
    value: float
    prev: float  # 전일 종가
    # 실시간 값이면 시각(timezone 포함 datetime), 종가 대체값이면 날짜(date)
    as_of: Union[dt.datetime, dt.date]
    unit: str  # "%"(금리) / "pt" / "$"

    @property
    def change_pct(self) -> float:
        return (self.value / self.prev - 1) * 100

    @property
    def change_bp(self) -> float:
        """금리 전용: 전일 대비 변화폭(bp)."""
        return (self.value - self.prev) * 100


@dataclass
class MacroIndicators:
    inflation: List[InflationIndicator]
    rates: List[RateIndicator]
    claims: Optional[ClaimsIndicator] = None


def _parse_fred_csv(text: str, column: str) -> List[tuple[dt.date, float]]:
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        value = row.get(column, "")
        if value in ("", "."):
            continue
        rows.append((dt.date.fromisoformat(row["observation_date"]), float(value)))
    if not rows:
        raise ValueError(f"FRED {column} 응답에 값이 없음")
    return rows


def _fred_series(series_id: str, start: dt.date) -> List[tuple[dt.date, float]]:
    resp = requests.get(
        FRED_CSV_URL, params={"id": series_id, "cosd": start.isoformat()}, timeout=HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return _parse_fred_csv(resp.text, series_id)


def _alfred_series(series_id: str, start: dt.date, vintage: dt.date) -> List[tuple[dt.date, float]]:
    """vintage 날짜 시점에 공개돼 있던 값(ALFRED, API 키 불필요). 속보치 계산용."""
    resp = requests.get(
        ALFRED_CSV_URL,
        params={"id": series_id, "cosd": start.isoformat(), "vintage_date": vintage.isoformat()},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _parse_fred_csv(resp.text, f"{series_id}_{vintage:%Y%m%d}")


def _pct(new: float, old: float) -> float:
    return (new / old - 1) * 100


def _add_months(month: dt.date, n: int) -> dt.date:
    index = month.year * 12 + month.month - 1 + n
    return dt.date(index // 12, index % 12 + 1, 1)


def _change(rows: List[tuple[dt.date, float]], month: dt.date, months_back: int) -> Optional[float]:
    values = dict(rows)
    cur, base = values.get(month), values.get(_add_months(month, -months_back))
    return _pct(cur, base) if cur and base else None


def _first_release_rows(series_id: str, month: dt.date, start: dt.date) -> List[tuple[dt.date, float]]:
    """month가 가장 최근 관측월이던 시점의 값. month는 보통 다음 달 중순에 발표되고 그다음 달은
    그 다음 달 중순에 나오므로, 발표 다음 달 25일 vintage를 쓴다. 발표가 밀려 그 vintage의
    마지막 관측월이 month가 아니면 속보치를 알 수 없어 빈 값을 돌려준다."""
    vintage = _add_months(month, 1).replace(day=25)
    rows = _alfred_series(series_id, start, vintage)
    return rows if rows[-1][0] == month else []


def _inflation_indicator(name: str, today: dt.date, consensus: dict) -> InflationIndicator:
    start = dt.date(today.year - 2, 1, 1)
    ids = [sid for _, sa, nsa in INFLATION_SERIES[name] for sid in (sa, nsa)]
    current = fetch_all(ids, lambda sid: _fred_series(sid, start), what="FRED 물가", default=[])
    # 기준월: 헤드라인 SA 시리즈의 가장 최근 관측월 (시리즈끼리 발표월이 같다)
    head_sa = current[INFLATION_SERIES[name][0][1]]
    if not head_sa:
        raise ValueError(f"{name} 헤드라인 시리즈 조회 실패")
    month = head_sa[-1][0]
    prev_month = _add_months(month, -1)
    first = fetch_all(
        ids, lambda sid: _first_release_rows(sid, prev_month, start),
        what="ALFRED 물가 속보치", default=[],
    )

    month_consensus = consensus.get(name, {}).get(f"{month:%Y-%m}", {})
    lines = []
    for label, sa, nsa in INFLATION_SERIES[name]:
        lines.append(
            InflationLine(
                label=label,
                mom=_change(current[sa], month, 1),
                yoy=_change(current[nsa], month, 12),
                consensus_mom=month_consensus.get(label),
                prev_first_mom=_change(first[sa], prev_month, 1),
                prev_mom=_change(current[sa], prev_month, 1),
                prev_first_yoy=_change(first[nsa], prev_month, 12),
                prev_yoy=_change(current[nsa], prev_month, 12),
            )
        )
    release = month_consensus.get("release")
    return InflationIndicator(
        name=name,
        month=month,
        lines=lines,
        prev_month=prev_month,
        release=dt.datetime.fromisoformat(release) if release else None,
        upcoming=_upcoming_release(consensus.get(name, {}), month),
    )


def _upcoming_release(entries: dict, latest_month: dt.date) -> Optional[UpcomingRelease]:
    """기준월 이후 달 중 컨센서스 캐시에 잡힌 가장 이른 발표."""
    later = sorted(k for k in entries if k > f"{latest_month:%Y-%m}")
    if not later:
        return None
    entry = entries[later[0]]
    return UpcomingRelease(
        month=dt.date.fromisoformat(later[0] + "-01"),
        release=dt.datetime.fromisoformat(entry["release"]),
        consensus_mom={label: entry.get(label) for label in ("헤드라인", "근원")},
    )


# ForexFactory 주간 일정(로그인·키 불필요). 이번 주(일~토) 일정만 주고 발표 후에도 forecast가
# 남아 있다. 지난 주 일정은 받을 수 없어, 리포트가 돌 때마다(하루 3회) 본 예상치를
# CONSENSUS_CACHE_PATH에 쌓아두고 워크플로가 커밋한다. 발표월의 전달을 대상월로 본다.
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_CLAIMS_EVENT = "Unemployment Claims"
FF_EVENTS = {
    "CPI m/m": ("CPI", "헤드라인"),
    "Core CPI m/m": ("CPI", "근원"),
    "PPI m/m": ("PPI", "헤드라인"),
    "Core PPI m/m": ("PPI", "근원"),
}
CONSENSUS_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "consensus_cache.json"


def _ff_events() -> List[dict]:
    resp = requests.get(FF_CALENDAR_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _parse_percent(text: str) -> Optional[float]:
    text = (text or "").strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_count(text: str) -> Optional[float]:
    """'194K' -> 194000."""
    text = (text or "").strip().upper()
    scale = {"K": 1e3, "M": 1e6}.get(text[-1:], 1) if text else 1
    try:
        return float(text.rstrip("KM").replace(",", "")) * scale
    except ValueError:
        return None


def merge_consensus(cache: dict, events: List[dict]) -> dict:
    for event in events:
        if event.get("country") == "USD" and event.get("title") == FF_CLAIMS_EVENT:
            forecast = _parse_count(event.get("forecast"))
            if forecast is not None:
                release = dt.datetime.fromisoformat(event["date"])
                # 목요일 발표 = 직전 토요일 마감 주 (공휴일로 수요일 발표여도 직전 토요일)
                week_end = release.date() - dt.timedelta(days=(release.weekday() - 5) % 7)
                cache.setdefault("Claims", {})[week_end.isoformat()] = {
                    "release": release.isoformat(), "forecast": forecast,
                }
            continue
        key = FF_EVENTS.get(event.get("title"))
        if event.get("country") != "USD" or not key:
            continue
        forecast = _parse_percent(event.get("forecast"))
        if forecast is None:
            continue
        name, label = key
        release = dt.datetime.fromisoformat(event["date"])
        month = _add_months(release.date().replace(day=1), -1)
        entry = cache.setdefault(name, {}).setdefault(f"{month:%Y-%m}", {})
        entry["release"] = release.isoformat()
        entry[label] = forecast
    return cache


def load_consensus(path: Path = CONSENSUS_CACHE_PATH) -> dict:
    """캐시를 읽고, 이번 주 일정의 예상치로 갱신해 저장한다. 조회 실패 시 캐시 그대로."""
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    events = safe_call("ForexFactory 경제 일정 조회", _ff_events, default=None)
    if events:
        cache = merge_consensus(cache, events)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    return cache


CLAIMS_SERIES = "ICSA"


def _default_claims_release(week_end: dt.date) -> dt.datetime:
    """일정을 못 받았을 때: 집계 주 다음 목요일 08:30(미 동부)."""
    return dt.datetime.combine(week_end + dt.timedelta(days=5), dt.time(8, 30), tzinfo=ET)


def fetch_initial_claims(today: dt.date, consensus: Optional[dict] = None) -> Optional[ClaimsIndicator]:
    rows = _fred_series(CLAIMS_SERIES, today - dt.timedelta(days=60))
    if len(rows) < 2:
        return None
    (_, prev), (week_end, value) = rows[-2], rows[-1]
    entries = (consensus or {}).get("Claims", {})
    cur, nxt = entries.get(week_end.isoformat(), {}), week_end + dt.timedelta(days=7)
    upcoming = entries.get(nxt.isoformat(), {})
    return ClaimsIndicator(
        week_end=week_end, value=value, prev=prev,
        release=_release_time(cur) or _default_claims_release(week_end),
        consensus=cur.get("forecast"),
        next_week_end=nxt,
        next_release=_release_time(upcoming) or _default_claims_release(nxt),
        next_consensus=upcoming.get("forecast"),
    )


def _release_time(entry: dict) -> Optional[dt.datetime]:
    return dt.datetime.fromisoformat(entry["release"]) if entry.get("release") else None


def release_phase(now: dt.datetime, release: Optional[dt.datetime]) -> Optional[str]:
    """발표일(한국 날짜) 리포트와 그다음 날 리포트에만 보인다.

    미국 지표는 한국 시간 밤 22:30(서머타임 해제 시 23:30)에 나와 발표일 리포트(08:00/17:00/
    21:30)는 발표 전이라 예상치만, 다음 날 리포트는 발표치를 보여준다."""
    if release is None:
        return None
    day, release_day = now.astimezone(KST).date(), release.astimezone(KST).date()
    if now < release:
        return "preview" if day == release_day else None
    return "released" if day in (release_day, release_day + dt.timedelta(days=1)) else None


def _inflation_phase(ind: InflationIndicator, now: dt.datetime) -> Optional[str]:
    if ind.upcoming and release_phase(now, ind.upcoming.release):
        # 발표 시각이 지났는데 FRED에 아직 안 올라온 경우도 예상치로 보여준다
        return "preview"
    return "released" if release_phase(now, ind.release) == "released" else None


def _claims_phase(ind: ClaimsIndicator, now: dt.datetime) -> Optional[str]:
    if release_phase(now, ind.next_release):
        return "preview"
    return "released" if release_phase(now, ind.release) == "released" else None


def _treasury_rows(year: int) -> List[dict]:
    resp = requests.get(
        TREASURY_CSV_URL.format(year=year),
        params={
            "type": "daily_treasury_yield_curve",
            "field_tdr_date_value": str(year),
            "_format": "csv",
        },
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def _parse_treasury(rows: List[dict]) -> List[tuple[dt.date, dict]]:
    """재무부 CSV 행을 (날짜, {컬럼: 값}) 오름차순으로. 값이 빈 칸이면 제외."""
    parsed = []
    for row in rows:
        try:
            date = dt.datetime.strptime(row["Date"], "%m/%d/%Y").date()
        except (KeyError, ValueError):
            continue
        values = {k: float(row[k]) for k in TREASURY_TENORS if row.get(k) not in (None, "")}
        parsed.append((date, values))
    return sorted(parsed, key=lambda r: r[0])


def fetch_treasury_yields(today: dt.date) -> List[RateIndicator]:
    rows = _parse_treasury(_treasury_rows(today.year))
    if len(rows) < 2:  # 연초에는 올해 데이터가 1건 이하라 전년도 끝을 붙인다
        rows = _parse_treasury(_treasury_rows(today.year - 1)) + rows
    result = []
    for column, name in TREASURY_TENORS.items():
        points = [(d, v[column]) for d, v in rows if column in v]
        if len(points) < 2:
            continue
        (_, prev), (date, value) = points[-2], points[-1]
        result.append(RateIndicator(name, column, value, prev, date, "%"))
    return result


def _cnbc_quotes(symbols) -> List[dict]:
    resp = requests.get(
        CNBC_QUOTE_URL,
        params={
            "symbols": "|".join(symbols), "requestMethod": "itv", "noform": "1",
            "partnerId": "2", "fund": "1", "exthrs": "1", "output": "json",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    quotes = resp.json()["FormattedQuoteResult"]["FormattedQuote"]
    return quotes if isinstance(quotes, list) else [quotes]


def _percent_value(text: str) -> float:
    return float(text.strip().rstrip("%").replace(",", ""))


def fetch_live_treasury_yields() -> List[RateIndicator]:
    result = []
    for quote in _cnbc_quotes(CNBC_TENORS):
        column = CNBC_TENORS.get(quote.get("symbol"))
        if not column:
            continue
        result.append(
            RateIndicator(
                TREASURY_TENORS[column],
                column,
                _percent_value(quote["last"]),
                _percent_value(quote["previous_day_closing"]),
                # 예: 2026-11-13T17:05:00.000-0500 (3.9의 fromisoformat은 -0500 형식을 못 읽음)
                dt.datetime.strptime(quote["last_time"], "%Y-%m-%dT%H:%M:%S.%f%z"),
                "%",
            )
        )
    order = list(TREASURY_TENORS)
    result.sort(key=lambda r: order.index(r.symbol))
    if len(result) != len(TREASURY_TENORS):
        raise ValueError(f"CNBC 금리 응답 누락: {[r.symbol for r in result]}")
    return result


def _treasury_yields(today: dt.date) -> List[RateIndicator]:
    """실시간(CNBC) 우선, 실패하면 재무부 최근 종가."""
    live = safe_call("미국채 실시간 금리(CNBC) 조회", fetch_live_treasury_yields, default=[])
    if live:
        return live
    return safe_call("미국채 금리(재무부) 조회", fetch_treasury_yields, today, default=[])


def _market_indicator(ticker: str) -> Optional[RateIndicator]:
    """발송 시점 시세(5분봉 마지막 값)와 전일 종가.

    전일 종가는 마지막 5분봉이 속한 거래일 직전 일봉의 종가다. 선물은 일요일 저녁(미 동부)
    거래가 월요일 일봉으로 잡히기도 하고 아직 일봉이 안 생겨 있기도 해서, 마지막 일봉 날짜가
    5분봉 날짜 이후면(이미 오늘 일봉이 있음) 그 전 일봉을, 아니면 마지막 일봉을 쓴다.
    """
    name, unit = MARKET_TICKERS[ticker]
    daily = price_history(ticker, period="10d", interval="1d")["Close"]
    intraday = price_history(ticker, period="5d", interval="5m")["Close"]
    if intraday.empty or len(daily) < 2:
        return None
    as_of = intraday.index[-1].to_pydatetime()
    today_bar_exists = daily.index[-1].date() >= as_of.date()
    prev = float(daily.iloc[-2] if today_bar_exists else daily.iloc[-1])
    return RateIndicator(name, ticker, float(intraday.iloc[-1]), prev, as_of, unit)


def fetch_macro_indicators(now: Optional[dt.datetime] = None) -> MacroIndicators:
    """투자지표. 물가·실업수당은 발표일과 그다음 날 리포트에만 넣는다(release_phase)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(KST).date()
    consensus = load_consensus()
    inflation = fetch_all(
        INFLATION_SERIES, lambda name: _inflation_indicator(name, today, consensus),
        what="물가 지표", default=None,
    )
    for ind in inflation.values():
        if ind is not None:
            ind.phase = _inflation_phase(ind, now)
    claims = safe_call("신규 실업수당 청구 조회", fetch_initial_claims, today, consensus, default=None)
    if claims is not None:
        claims.phase = _claims_phase(claims, now)
        if claims.phase is None:
            claims = None
    yields = _treasury_yields(today)
    markets = fetch_all(MARKET_TICKERS, _market_indicator, what="시장 지표", default=None)
    return MacroIndicators(
        inflation=[i for i in inflation.values() if i is not None and i.phase],
        rates=yields + [m for m in markets.values() if m is not None],
        claims=claims,
    )
