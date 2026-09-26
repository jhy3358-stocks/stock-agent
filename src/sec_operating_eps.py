"""SEC 기반 영업이익 EPS (연 환산) - GRAV·M-GRAV의 EPS.

    EPS = 분기 영업이익 x (1 - 실효세율) / 희석 주식수 x (365 / 분기 일수)

순이익 EPS는 투자주식 평가이익 같은 영업외 손익에 크게 흔들려서(2026-09 AMZN·GOOGL은
분기 순이익의 65~70%가 영업외 이익) 전 종목 같은 정의로 영업이익에서 EPS를 구한다.
분기 길이가 다른 회사(예: COST 4분기 16주)도 일수로 연 환산한다.

1) 10-Q/10-K XBRL(companyfacts)로 가장 최근 분기 영업이익·희석 주식수, 최근 4분기
   실효세율을 구한다.
2) 그보다 나중에 낸 실적 발표 8-K가 있으면 보도자료 손익표의 영업이익 행에서 새 분기
   영업이익을 읽어 먼저 반영한다. 전년 동분기 영업이익(XBRL)이 같은 행에 단위(원/천/
   백만/십억)만 다르게 들어 있을 때만 표를 제대로 읽었다고 보고 인정하고, 주식수·세율은
   XBRL 최근 값을 그대로 쓴다.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from functools import lru_cache
from typing import List, Optional, Tuple

from src.sec_client import all_ciks
from src.sec_eps import (
    ANNUAL_MIN_DAYS,
    COMPANY_FACTS_URL,
    PERIOD_TOLERANCE_DAYS,
    SecEps,
    _Fact,
    _cells,
    _exhibit_urls,
    _get,
    _latest_cumulative,
    _latest_earnings_release,
    _parse_facts,
    _release_context,
    _ROW_RE,
    _xbrl_latest_quarter,
)

logger = logging.getLogger(__name__)

OPERATING_INCOME = "OperatingIncomeLoss"
DILUTED_SHARES = "WeightedAverageNumberOfDilutedSharesOutstanding"
INCOME_TAX = "IncomeTaxExpenseBenefit"
PRETAX_CONCEPTS = (
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
)
# 분기 실효세율은 일회성 세금·영업외 손익에 크게 흔들려 최근 4분기 값을 이 범위로 제한한다.
TAX_RATE_RANGE = (0.10, 0.30)
DEFAULT_TAX_RATE = 0.21
QUARTER_MAX_DAYS = ANNUAL_MIN_DAYS / 3
# 영업이익 항목 이름을 바꿔 과거 값만 남은 회사(예: COHR은 2024-06 이후 미보고)는 쓰지 않는다.
STALE_AFTER_DAYS = 200
# 보도자료 금액 단위 후보와, 전년 동분기 영업이익(XBRL)과 맞춰볼 때 허용 오차(반올림)
SCALES = (1.0, 1e3, 1e6, 1e9)
AMOUNT_MATCH_TOLERANCE = 0.005

_OPERATING_LABELS = ("operating income", "income from operations", "operating profit")
_OPERATING_EXCLUDE = ("non-gaap", "adjusted", "margin", "%", "per share")
# 금액 행 숫자: 쉼표 정수/소수 모두. 괄호는 음수, %는 제외.
_AMOUNT_RE = re.compile(r"(\(\s*)?(\d[\d,]*(?:\.\d+)?)(?![\d.,]|\s*%)")


def _facts(us_gaap: dict, concept: str, unit: str = "USD") -> List[_Fact]:
    """기간별 가장 나중 제출본만 남긴 XBRL 값 (금액·주식수)."""
    latest = {}
    for fact in _parse_facts(us_gaap.get(concept, {}).get("units", {}).get(unit, [])):
        key = (fact.start, fact.end)
        if key not in latest or fact.filed >= latest[key].filed:
            latest[key] = fact
    return list(latest.values())


def _quarter_days(facts: List[_Fact], end: dt.date) -> Optional[int]:
    """end로 끝나는 분기의 일수 (3개월치 값이 없으면 직전 누적 시점과의 차이)."""
    direct = [f for f in facts if f.end == end and f.days < QUARTER_MAX_DAYS]
    if direct:
        return direct[0].days
    cumulative = max((f for f in facts if f.end == end), key=lambda f: f.days, default=None)
    if cumulative is None:
        return None
    earlier = [f.end for f in facts if f.start == cumulative.start and f.end < end]
    return (end - max(earlier)).days if earlier else None


def _ttm(facts: List[_Fact]) -> Optional[float]:
    """최근 4분기 합계 (직전 연간 + 올해 누적 - 전년 동기 누적)."""
    if not facts:
        return None
    latest = _latest_cumulative(facts)
    if latest.days >= ANNUAL_MIN_DAYS:
        return latest.val
    year_ago = latest.end - dt.timedelta(days=365)
    prior = next((f for f in facts if abs((f.end - year_ago).days) <= PERIOD_TOLERANCE_DAYS
                  and abs(f.days - latest.days) <= PERIOD_TOLERANCE_DAYS), None)
    if prior is None:
        return None
    annual = next((f for f in facts if f.start == prior.start and f.days >= ANNUAL_MIN_DAYS), None)
    return annual.val + latest.val - prior.val if annual else None


def _tax_rate(us_gaap: dict) -> float:
    tax = _ttm(_facts(us_gaap, INCOME_TAX))
    for concept in PRETAX_CONCEPTS:
        pretax = _ttm(_facts(us_gaap, concept))
        if tax is not None and pretax and pretax > 0:
            low, high = TAX_RATE_RANGE
            return min(max(tax / pretax, low), high)
    return DEFAULT_TAX_RATE


def _diluted_shares(us_gaap: dict, end: dt.date) -> Optional[float]:
    """end로 끝나는 분기 희석 가중평균 주식수 (없으면 같은 날 끝나는 누적 기간 값)."""
    facts = [f for f in _facts(us_gaap, DILUTED_SHARES, "shares") if f.end == end]
    return min(facts, key=lambda f: f.days).val if facts else None


def _amounts(cells: List[str]) -> List[float]:
    return [
        -float(m.group(2).replace(",", "")) if m.group(1) else float(m.group(2).replace(",", ""))
        for m in _AMOUNT_RE.finditer(" ".join(cells))
    ]


def _match_scale(numbers: List[float], target: float) -> Optional[Tuple[int, float]]:
    """numbers 중 target(원 단위)과 단위만 다른 값의 (위치, 단위)."""
    for i, n in enumerate(numbers):
        for scale in SCALES:
            if target and abs(n * scale - target) <= abs(target) * AMOUNT_MATCH_TOLERANCE:
                return i, scale
    return None


def operating_income_from_release(
    document_html: str, year_ago_quarter: float, prior_ytd: Optional[float]
) -> Optional[float]:
    """보도자료 손익표에서 새 분기 영업이익(원 단위).

    전년 동분기 영업이익이 같은 행에 있어야 인정한다(사업부별 영업이익 행은 여기서
    걸러진다). 그 값이 행 맨 앞이면 "전년, 올해" 순서로 보고 두 번째 값을, 아니면 첫 번째
    값을 새 분기로 본다. prior_ytd가 있으면 "새 분기 + prior_ytd"인 올해 누적 값까지 같은
    행에 있는 것을 우선한다 (sec_eps.quarter_eps_from_release와 같은 방식).
    """
    unconfirmed = None
    for row in _ROW_RE.findall(document_html):
        cells = [c for c in _cells(row) if c]
        if not cells:
            continue
        label = cells[0].lower()
        if not any(k in label for k in _OPERATING_LABELS) or any(k in label for k in _OPERATING_EXCLUDE):
            continue
        numbers = _amounts(cells[1:])
        match = _match_scale(numbers, year_ago_quarter)
        if match is None or len(numbers) < 2:
            continue
        index, scale = match
        quarter = (numbers[1] if index == 0 else numbers[0]) * scale
        if prior_ytd is None or _match_scale([n * scale - quarter for n in numbers], prior_ytd):
            return quarter
        if unconfirmed is None:
            unconfirmed = quarter
    return unconfirmed


def _release_operating_income(cik10: str, accession: str, facts: List[_Fact]) -> Optional[Tuple[float, int]]:
    """8-K 보도자료의 새 분기 영업이익과, 그 분기 일수(전년 동분기 일수로 추정)."""
    context = _release_context(facts)
    if context.year_ago_quarter is None:
        return None
    latest_end = _latest_cumulative(facts).end
    year_ago_end = min(
        (f.end for f in facts if f.end > latest_end - dt.timedelta(days=365 - PERIOD_TOLERANCE_DAYS)),
        default=None,
    )
    days = _quarter_days(facts, year_ago_end) if year_ago_end else None
    if days is None:
        return None
    for url in _exhibit_urls(cik10, accession):
        income = operating_income_from_release(_get(url).text, context.year_ago_quarter, context.prior_ytd)
        if income is not None:
            return income, days
    return None


@lru_cache(maxsize=None)
def annual_operating_eps(ticker: str) -> Optional[SecEps]:
    """영업이익 기반 연 환산 EPS. 영업이익을 XBRL로 보고하지 않는 회사(예: LLY)는 None."""
    cik10 = all_ciks().get(ticker)
    if cik10 is None:
        return None
    us_gaap = _get(COMPANY_FACTS_URL.format(cik10=cik10)).json().get("facts", {}).get("us-gaap", {})
    income_facts = _facts(us_gaap, OPERATING_INCOME)
    if not income_facts:
        return None
    latest = _latest_cumulative(income_facts)
    if (dt.date.today() - latest.end).days > STALE_AFTER_DAYS:
        return None
    shares = _diluted_shares(us_gaap, latest.end)
    quarter_income = _xbrl_latest_quarter(income_facts)
    days = _quarter_days(income_facts, latest.end)
    if not shares or quarter_income is None or not days:
        return None
    tax_rate = _tax_rate(us_gaap)
    source = f"SEC 10-Q/10-K ~{latest.end}"

    release = _latest_earnings_release(cik10)
    if release is not None and release[1] > latest.filed:
        accession, filed = release
        found = _release_operating_income(cik10, accession, income_facts)
        if found is not None:
            quarter_income, days = found
            source = f"SEC 8-K {filed}"
        else:
            logger.warning("%s 실적 발표 8-K(%s)에서 영업이익을 확인하지 못해 %s 기준을 사용",
                           ticker, filed, source)

    eps = quarter_income * (1 - tax_rate) / shares * 365 / days
    logger.info("%s 영업이익 EPS(연 환산) %.2f (%s, 세율 %.0f%%)", ticker, eps, source, tax_rate * 100)
    return SecEps(eps, source)
