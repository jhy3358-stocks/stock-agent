"""SEC EDGAR 기반 최근 분기 희석 EPS - 가장 최근 실적 발표 8-K(Item 2.02) 기준.

가장 최근 실적 발표 8-K의 보도자료(EX-99.x) 손익계산서에서 발표된 분기의 희석
EPS를 읽는다 (GRAV/M-GRAV는 이 값 x 4를 연간 EPS로 쓴다, src/valuation.py).

보도자료 서식은 회사마다 달라서(올해/전년 열 순서, 직전 분기 열, 분기 추이표 등),
10-Q/10-K XBRL(data.sec.gov companyconcept)로 구한 전년 동분기 EPS가 "Diluted"
행에 함께 들어 있을 때만 표 구조를 제대로 읽었다고 보고 값을 인정한다. 올해
누적(YTD) 열이 있으면 "새 누적 - 새 분기 = XBRL 직전 누적"까지 맞는 행을
우선한다. 보도자료에 손익표가 없어(예: TSLA) 읽지 못하면 10-Q/10-K XBRL의
가장 최근 분기 EPS로 대신한다.
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple

import requests

from src.sec_client import SEC_HEADERS, all_ciks, fetch_submissions

logger = logging.getLogger(__name__)

# 개별 항목(companyconcept) API는 최근 값이 빠져 있는 경우가 있어(2026-09 CDNS 확인)
# 회사 전체 XBRL(companyfacts)에서 찾는다.
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"
# 희석 EPS 항목 이름 (우선순위 순). 희석 효과가 없는 회사는 BasicAndDiluted 하나로,
# 중단영업이 없는 일부 회사(예: ABNB)는 계속영업 희석 EPS로 보고한다.
EPS_CONCEPTS = (
    "EarningsPerShareDiluted",
    "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
)
PERIODIC_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

# 52/53주 회계연도(예: 코스트코)도 연간으로 잡히도록 여유를 둔다.
ANNUAL_MIN_DAYS = 350
# "1년 전 같은 기간"을 찾을 때 허용하는 기간 끝 날짜/길이 차이 (52/53주 회계연도 대응)
PERIOD_TOLERANCE_DAYS = 14
# 같은 기간 EPS가 최신 공시와 이전 공시에서 이 배수 이상 다르면 주식분할로 본다.
# EPS가 작으면 재작성·반올림만으로도 비율이 크게 흔들려(예: -0.10 -> -0.07) 절댓값이
# SPLIT_MIN_EPS 이상인 값만, 그런 기간이 SPLIT_MIN_PERIODS개 이상일 때만 비교한다.
SPLIT_MIN_RATIO = 1.9
SPLIT_MIN_EPS = 0.25
SPLIT_MIN_PERIODS = 2
# 보도자료 표의 전년 동분기 EPS와 XBRL로 계산한 값의 허용 오차 (반올림 누적 대비)
EPS_MATCH_TOLERANCE = 0.02


@dataclass(frozen=True)
class SecEps:
    value: float
    source: str  # 어느 공시 기준인지 (로그용)


@dataclass(frozen=True)
class _Fact:
    start: dt.date
    end: dt.date
    val: float
    filed: dt.date

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True)
class _ReleaseContext:
    """8-K가 발표한 분기를 검증하는 데 쓰는 XBRL 값."""
    year_ago_quarter: Optional[float]  # 전년 동분기 EPS
    prior_ytd: Optional[float]  # 발표 분기 직전까지의 올해 누적 EPS (1분기 발표면 None)


def _get(url: str) -> requests.Response:
    response = requests.get(url, headers=SEC_HEADERS, timeout=15)
    response.raise_for_status()
    return response


def _parse_facts(raws: List[dict]) -> List[_Fact]:
    return [
        _Fact(
            dt.date.fromisoformat(raw["start"]),
            dt.date.fromisoformat(raw["end"]),
            float(raw["val"]),
            dt.date.fromisoformat(raw["filed"]),
        )
        for raw in raws
        if raw.get("form") in PERIODIC_FORMS and "start" in raw
    ]


def _split_adjusted_latest(facts: List[_Fact]) -> List[_Fact]:
    """기간별로 가장 나중 제출본만 남기고, 최신 공시 이후로 다시 보고되지 않은 과거 값은
    주식분할 비율로 나눠 최신 기준에 맞춘다.

    분할 후 첫 10-Q/10-K는 비교 기간(전년 등)만 분할 기준으로 재작성하고, 올해 앞선
    분기 누적값은 분할 전 제출본에만 남는다. 그대로 쓰면 "연간 - 3분기 누적" 같은
    계산이 틀어진다(2026-09 KLAC 10:1 분할에서 4분기 EPS가 -22.6으로 계산됨).
    분할 비율은 같은 기간을 최신 공시와 그 직전 공시가 각각 보고한 값의 비로 구한다.
    """
    newest = max(f.filed for f in facts)
    by_period: dict[Tuple[dt.date, dt.date], List[_Fact]] = {}
    for fact in facts:
        by_period.setdefault((fact.start, fact.end), []).append(fact)

    ratios = []
    for group in by_period.values():
        restated = [f for f in group if f.filed == newest]
        earlier = [f for f in group if f.filed < newest]
        if not restated or not earlier:
            continue
        previous = max(earlier, key=lambda f: f.filed)
        if min(abs(previous.val), abs(restated[0].val)) >= SPLIT_MIN_EPS and (
            (previous.val > 0) == (restated[0].val > 0)
        ):
            ratios.append(previous.val / restated[0].val)
    ratio = sorted(ratios)[len(ratios) // 2] if len(ratios) >= SPLIT_MIN_PERIODS else 1.0
    split = ratio >= SPLIT_MIN_RATIO or ratio <= 1 / SPLIT_MIN_RATIO

    result = []
    for group in by_period.values():
        latest = max(group, key=lambda f: f.filed)
        if split and latest.filed < newest:
            latest = _Fact(latest.start, latest.end, latest.val / ratio, latest.filed)
        result.append(latest)
    return result


def _eps_facts(cik10: str) -> List[_Fact]:
    """10-Q/10-K XBRL 희석 EPS 값들 (기간별 최신 제출본, 주식분할 보정).

    회사가 EPS 항목 이름을 중간에 바꾸는 경우가 있어(예: BKR은 2024년 이후
    EarningsPerShareDiluted 미보고) 후보 항목 중 가장 최근 기간까지 보고된 것을 쓴다.
    """
    us_gaap = _get(COMPANY_FACTS_URL.format(cik10=cik10)).json().get("facts", {}).get("us-gaap", {})
    best: List[_Fact] = []
    for concept in EPS_CONCEPTS:
        facts = _parse_facts(us_gaap.get(concept, {}).get("units", {}).get("USD/shares", []))
        if facts and (not best or max(f.end for f in facts) > max(f.end for f in best)):
            best = facts
    return _split_adjusted_latest(best) if best else []


def _near(a: dt.date, b: dt.date) -> bool:
    return abs((a - b).days) <= PERIOD_TOLERANCE_DAYS


def _first(facts: Iterable[_Fact]) -> Optional[_Fact]:
    return next(iter(facts), None)


def _latest_cumulative(facts: List[_Fact]) -> _Fact:
    """가장 최근 보고 기간의 회계연도 누적(YTD) 또는 연간 값 (같은 날 끝나는 값 중 가장 긴 기간)."""
    period_end = max(f.end for f in facts)
    return max((f for f in facts if f.end == period_end), key=lambda f: f.days)


def _release_context(facts: List[_Fact]) -> _ReleaseContext:
    """facts의 마지막 보고 기간 "다음 분기"를 발표한 8-K를 검증할 값."""
    latest = _latest_cumulative(facts)
    if latest.days >= ANNUAL_MIN_DAYS:
        # 다음 발표는 새 회계연도 1분기 -> 전년 동분기는 방금 끝난 회계연도의 1분기
        quarters = sorted(
            (f for f in facts if f.start == latest.start and f.days < ANNUAL_MIN_DAYS),
            key=lambda f: f.end,
        )
        return _ReleaseContext(quarters[0].val if quarters else None, None)

    year_ago_end = latest.end - dt.timedelta(days=365)
    prior = _first(
        f for f in facts
        if _near(f.end, year_ago_end) and abs(f.days - latest.days) <= PERIOD_TOLERANCE_DAYS
    )
    if prior is None:
        return _ReleaseContext(None, latest.val)
    # 전년 회계연도 누적값 중 prior 바로 다음 것 = 다음 분기의 전년 동분기가 끝나는 시점.
    # 그 분기 3개월치 값이 따로 공시돼 있으면 그대로 쓴다 - 과거 누적값이 일부만
    # 재작성되면 누적값끼리 빼서 구한 값이 틀어진다(2026-09 CRWD 확인).
    following = sorted(
        (f for f in facts if f.start == prior.start and f.end > prior.end),
        key=lambda f: f.end,
    )
    if not following:
        return _ReleaseContext(None, latest.val)
    direct = _first(
        f for f in facts if f.end == following[0].end and f.days < ANNUAL_MIN_DAYS / 3
    )
    year_ago = direct.val if direct else following[0].val - prior.val
    return _ReleaseContext(year_ago, latest.val)


def _xbrl_latest_quarter(facts: List[_Fact]) -> Optional[float]:
    """10-Q/10-K XBRL의 가장 최근 분기 EPS (4분기는 연간 - 3분기 누적)."""
    latest = _latest_cumulative(facts)
    quarter = min((f for f in facts if f.end == latest.end), key=lambda f: f.days)
    if quarter.days < ANNUAL_MIN_DAYS / 3:
        return quarter.val
    earlier = [f for f in facts if f.start == latest.start and f.end < latest.end]
    if not earlier:
        return None
    return latest.val - max(earlier, key=lambda f: f.end).val


def _latest_earnings_release(cik10: str) -> Optional[Tuple[str, dt.date]]:
    """가장 최근 실적 발표 8-K의 (접수번호, 제출일)."""
    recent = fetch_submissions(cik10)
    for i, form in enumerate(recent["form"]):  # 최신순
        if form == "8-K" and "2.02" in recent["items"][i].split(","):
            return recent["accessionNumber"][i], dt.date.fromisoformat(recent["filingDate"][i])
    return None


_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r'href="([^"]+)"', re.I)
# 소수점이 있는 숫자만 EPS 후보로 본다 (주식수·금액은 정수 표기). 괄호는 음수, %는 증감률이라 제외.
_NUM_RE = re.compile(r"(\(\s*)?(\d[\d,]*\.\d+)(?![\d.]|\s*%)")


def _cells(row_html: str) -> List[str]:
    cells = (html_lib.unescape(_TAG_RE.sub(" ", c)) for c in _CELL_RE.findall(row_html))
    return [" ".join(c.split()) for c in cells]


def _exhibit_urls(cik10: str, accession: str) -> List[str]:
    """8-K 첨부 중 EX-99.x(보도자료 등) 문서 URL, 번호 순."""
    base = ARCHIVE_BASE.format(cik=int(cik10), accession_nodash=accession.replace("-", ""))
    index_html = _get(f"{base}{accession}-index.htm").text
    urls = []
    for row in _ROW_RE.findall(index_html):
        cells = _cells(row)
        href = _HREF_RE.search(row)
        if href and any(c.upper().startswith("EX-99") for c in cells):
            urls.append("https://www.sec.gov" + href.group(1).replace("/ix?doc=", ""))
    return urls


def _diluted_eps_rows(document_html: str) -> List[List[float]]:
    """보도자료 표에서 희석 EPS로 보이는 행들의 숫자 목록."""
    rows = []
    for row in _ROW_RE.findall(document_html):
        cells = [c for c in _cells(row) if c]
        if not cells:
            continue
        label = cells[0].lower()
        if "diluted" not in label or "shares" in label or "weighted" in label:
            continue
        numbers = [
            -float(m.group(2).replace(",", "")) if m.group(1) else float(m.group(2).replace(",", ""))
            for m in _NUM_RE.finditer(" ".join(cells[1:]))
        ]
        if numbers:
            rows.append(numbers)
    return rows


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= EPS_MATCH_TOLERANCE


def quarter_eps_from_release(
    document_html: str, year_ago_quarter: float, prior_ytd: Optional[float]
) -> Optional[float]:
    """보도자료에서 새 분기 희석 EPS.

    전년 동분기 값이 같은 행에 있어야 인정한다. 그 값이 행 맨 앞이면 "전년, 올해"
    순서의 표(예: AMZN·GOOGL)로 보고 두 번째 값을, 아니면 첫 번째 값을 새 분기로
    본다. prior_ytd(XBRL 직전 누적)가 있으면 같은 행에 "새 분기 + prior_ytd"인
    올해 누적 값까지 있는 행을 우선한다 - 분기 추이표(오래된 분기부터 나열)처럼
    열 순서를 잘못 읽은 행을 걸러내기 위해서다.
    """
    unconfirmed = None
    for numbers in _diluted_eps_rows(document_html):
        if len(numbers) < 2:
            continue
        matches = [i for i, n in enumerate(numbers) if _close(n, year_ago_quarter)]
        if not matches:
            continue
        quarter = numbers[1] if matches[0] == 0 else numbers[0]
        if prior_ytd is None or any(_close(n - quarter, prior_ytd) for n in numbers):
            return quarter
        if unconfirmed is None:
            unconfirmed = quarter
    return unconfirmed


def _release_quarter_eps(cik10: str, accession: str, context: _ReleaseContext) -> Optional[float]:
    if context.year_ago_quarter is None:
        return None
    for url in _exhibit_urls(cik10, accession):
        eps = quarter_eps_from_release(_get(url).text, context.year_ago_quarter, context.prior_ytd)
        if eps is not None:
            return eps
    return None


@lru_cache(maxsize=None)
def latest_quarter_eps(ticker: str) -> Optional[SecEps]:
    """가장 최근 실적 발표 8-K의 분기 희석 EPS. SEC에 us-gaap XBRL로 보고하지 않는 종목은 None."""
    cik10 = all_ciks().get(ticker)
    if cik10 is None:
        return None
    facts = _eps_facts(cik10)
    if not facts:
        return None
    latest = _latest_cumulative(facts)
    xbrl_quarter = SecEps(_xbrl_latest_quarter(facts), f"SEC 10-Q/10-K ~{latest.end}")

    release = _latest_earnings_release(cik10)
    if release is None:
        return xbrl_quarter if xbrl_quarter.value is not None else None
    accession, filed = release
    # 8-K가 10-Q/10-K보다 먼저 나왔으면 그 10-Q/10-K와 같은 분기를 발표한 것이다
    if filed <= latest.filed:
        context_facts = [f for f in facts if f.end < latest.end]
    else:
        context_facts = facts
    quarter = (
        _release_quarter_eps(cik10, accession, _release_context(context_facts))
        if context_facts else None
    )
    if quarter is not None:
        result = SecEps(quarter, f"SEC 8-K {filed}")
    else:
        logger.warning(
            "%s 실적 발표 8-K(%s)에서 분기 EPS를 확인하지 못해 %s 기준 EPS를 사용",
            ticker, filed, xbrl_quarter.source,
        )
        if xbrl_quarter.value is None:
            return None
        result = xbrl_quarter
    logger.info("%s 분기 EPS %.2f (%s)", ticker, result.value, result.source)
    return result
