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

CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/{concept}.json"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"
# 희석 EPS를 따로 공시하지 않는(희석 효과 없음) 회사는 BasicAndDiluted 하나로 보고한다.
EPS_CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
PERIODIC_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

# 52/53주 회계연도(예: 코스트코)도 연간으로 잡히도록 여유를 둔다.
ANNUAL_MIN_DAYS = 350
# "1년 전 같은 기간"을 찾을 때 허용하는 기간 끝 날짜/길이 차이 (52/53주 회계연도 대응)
PERIOD_TOLERANCE_DAYS = 14
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


def _eps_facts(cik10: str) -> List[_Fact]:
    """10-Q/10-K XBRL 희석 EPS 값들. 같은 기간이 여러 번 보고됐으면 가장 나중 제출본을 쓴다
    (주식분할 등으로 과거 값이 재작성된 경우 최신 기준을 따르기 위해)."""
    for concept in EPS_CONCEPTS:
        try:
            data = _get(CONCEPT_URL.format(cik10=cik10, concept=concept)).json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        latest: dict[Tuple[dt.date, dt.date], _Fact] = {}
        for raw in data.get("units", {}).get("USD/shares", []):
            if raw.get("form") not in PERIODIC_FORMS or "start" not in raw:
                continue
            fact = _Fact(
                dt.date.fromisoformat(raw["start"]),
                dt.date.fromisoformat(raw["end"]),
                float(raw["val"]),
                dt.date.fromisoformat(raw["filed"]),
            )
            key = (fact.start, fact.end)
            if key not in latest or fact.filed >= latest[key].filed:
                latest[key] = fact
        if latest:
            return list(latest.values())
    return []


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
    # 전년 회계연도 누적값 중 prior 바로 다음 것 - prior = 다음 분기의 전년 동분기
    following = sorted(
        (f for f in facts if f.start == prior.start and f.end > prior.end),
        key=lambda f: f.end,
    )
    return _ReleaseContext(following[0].val - prior.val if following else None, latest.val)


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
