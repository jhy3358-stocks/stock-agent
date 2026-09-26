"""국내 DART 공시 수집 (OpenDART Open API, 무료 인증키 필요)."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import requests

from src.concurrency import fetch_all

LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# 매우 빈번하게 제출되는 임원/주요주주 지분 변동 보고서는 "주요 소식"으로 보기 어려워 제외한다.
EXCLUDED_KEYWORDS = ("임원ㆍ주요주주특정증권등소유상황보고서",)


# 해외(GitHub Actions) 러너에서 DART 접속이 가끔 시간 초과되어(2026-09-25 확인) 한 번 더 시도한다.
REQUEST_ATTEMPTS = 2


def _get(url: str, params: dict, what: str) -> requests.Response:
    """DART GET 요청. 실패 시 인증키(crtfc_key)가 담긴 요청 URL이 예외 메시지로
    로그(GitHub Actions 포함)에 노출되지 않도록, 예외 종류와 상태 코드만 남긴다."""
    error = ""
    for _ in range(REQUEST_ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            error = type(e).__name__
            continue
        if response.status_code == 200:
            return response
        error = f"HTTP {response.status_code}"
    raise RuntimeError(f"{what} 실패: {error}")


def fetch_recent_disclosures(api_key: str, corp_code: str, days: int = 7) -> List[dict]:
    """최근 N일 이내의 주요 공시 목록을 반환한다."""
    end_date = dt.date.today()
    begin_date = end_date - dt.timedelta(days=days)
    response = _get(
        LIST_URL,
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": begin_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "page_count": 30,
        },
        "DART 공시 조회",
    )
    data = response.json()

    # status "013"은 "조회된 데이터가 없습니다" (정상적인 무공시 상태)
    if data.get("status") not in ("000", "013"):
        raise RuntimeError(f"DART 공시 조회 실패: {data.get('status')} {data.get('message')}")

    disclosures = []
    for item in data.get("list", []):
        report_nm = item["report_nm"]
        if any(keyword in report_nm for keyword in EXCLUDED_KEYWORDS):
            continue
        disclosures.append(
            {
                "title": report_nm,
                "date": dt.datetime.strptime(item["rcept_dt"], "%Y%m%d").date(),
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item['rcept_no']}",
            }
        )
    return disclosures


def get_recent_disclosures_for_stocks(
    api_key: str, corp_codes: Dict[str, str], days: int = 7
) -> Dict[str, List[dict]]:
    """{종목코드: corp_code} 매핑을 받아 {종목코드: 공시목록}을 반환한다."""
    return fetch_all(
        corp_codes,
        lambda stock_code: fetch_recent_disclosures(api_key, corp_codes[stock_code], days),
        what="DART 공시",
        default=[],
    )


# ---------------------------------------------------------------------------
# 정기보고서(분기·반기·사업보고서) 재무제표에서 최근 분기 EPS
# ---------------------------------------------------------------------------

FINANCIALS_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
# 보고서 코드: 1분기 11013, 반기 11012, 3분기 11014, 사업보고서 11011
Q1_REPORT, HALF_REPORT, Q3_REPORT, ANNUAL_REPORT = "11013", "11012", "11014", "11011"
# 최신순 탐색 순서 (올해 3분기 -> 반기 -> 1분기 -> 작년 사업보고서 -> 작년 3분기 ...)
_REPORTS_NEWEST_FIRST = (
    (0, Q3_REPORT, "3분기"), (0, HALF_REPORT, "2분기"), (0, Q1_REPORT, "1분기"),
    (1, ANNUAL_REPORT, "4분기"), (1, Q3_REPORT, "3분기"), (1, HALF_REPORT, "2분기"),
)
# 보통주 희석주당이익을 우선하고, 없으면 기본주당이익 (우선주 EPS는 dart_ 접두 계정이라 제외된다)
_EPS_ACCOUNT_IDS = ("ifrs-full_DilutedEarningsLossPerShare", "ifrs-full_BasicEarningsLossPerShare")


def _fetch_financials(api_key: str, corp_code: str, year: int, report_code: str) -> List[dict]:
    """연결재무제표 전체 계정. 해당 보고서가 아직 없으면 빈 목록."""
    response = _get(
        FINANCIALS_URL,
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
            "fs_div": "CFS",
        },
        "DART 재무제표 조회",
    )
    data = response.json()
    if data.get("status") == "013":  # 조회된 데이터 없음 (아직 제출 전)
        return []
    if data.get("status") != "000":
        raise RuntimeError(f"DART 재무제표 조회 실패: {data.get('status')} {data.get('message')}")
    return data.get("list", [])


def _eps_amounts(rows: List[dict]) -> Optional[Tuple[Optional[float], Optional[float]]]:
    """손익계산서 EPS 행의 (당기 금액, 당기 누적 금액). 분기·반기보고서의 당기 금액은
    3개월치, 사업보고서의 당기 금액은 연간이다."""
    for account_id in _EPS_ACCOUNT_IDS:
        row = next(
            (r for r in rows if r["account_id"] == account_id and r["sj_div"] in ("IS", "CIS")),
            None,
        )
        if row is not None:
            return _amount(row.get("thstrm_amount")), _amount(row.get("thstrm_add_amount"))
    return None


def _amount(raw: Optional[str]) -> Optional[float]:
    try:
        return float(raw.replace(",", "")) if raw else None
    except ValueError:
        return None


_OPERATING_INCOME_IDS = ("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities")
_INCOME_TAX_IDS = ("ifrs-full_IncomeTaxExpenseContinuingOperations",)
_PRETAX_IDS = ("ifrs-full_ProfitLossBeforeTax",)
_OWNERS_PROFIT_IDS = ("ifrs-full_ProfitLossAttributableToOwnersOfParent",)
# 분기 실효세율 제한 범위 (src/sec_operating_eps.py와 같은 이유)
TAX_RATE_RANGE = (0.10, 0.30)
DEFAULT_TAX_RATE = 0.24
QUARTERS_PER_YEAR = 4


def _account(rows: List[dict], ids: Tuple[str, ...]) -> Optional[Tuple[Optional[float], Optional[float]]]:
    """손익계산서 계정의 (당기 금액, 당기 누적 금액). 누적이 비어 있으면(1분기·사업보고서) 당기 금액."""
    for account_id in ids:
        row = next(
            (r for r in rows if r["account_id"] == account_id and r["sj_div"] in ("IS", "CIS")),
            None,
        )
        if row is not None:
            current = _amount(row.get("thstrm_amount"))
            cumulative = _amount(row.get("thstrm_add_amount"))
            return current, cumulative if cumulative is not None else current
    return None


def fetch_latest_quarter_operating_eps(
    api_key: str, corp_code: str, today: Optional[dt.date] = None
) -> Optional[Tuple[float, str]]:
    """가장 최근 정기보고서 기준 영업이익 EPS(연 환산)와 분기명.

        EPS = 분기 영업이익 x (1 - 실효세율) / 희석 주식수 x 4

    희석 주식수는 DART가 따로 주지 않아 지배주주 순이익 누적 / 희석 EPS 누적으로 역산한다
    (보통주·우선주를 합친 주식수가 된다 - 현대차 약 2.6억 주로 확인). 실효세율은 올해
    누적 법인세비용 / 세전이익. 4분기는 사업보고서(연간) - 3분기보고서 누적으로 구한다.
    """
    this_year = (today or dt.date.today()).year
    for years_ago, report_code, quarter_name in _REPORTS_NEWEST_FIRST:
        year = this_year - years_ago
        rows = _fetch_financials(api_key, corp_code, year, report_code)
        income = _account(rows, _OPERATING_INCOME_IDS)
        if income is None:
            continue
        tax, pretax = _account(rows, _INCOME_TAX_IDS), _account(rows, _PRETAX_IDS)
        profit, eps = _account(rows, _OWNERS_PROFIT_IDS), _eps_amounts(rows)
        if eps is not None:
            eps = (eps[0], eps[1] if eps[1] is not None else eps[0])
        if None in (profit, eps) or not eps[1]:
            return None
        quarter_income = income[0]
        if report_code == ANNUAL_REPORT:
            q3 = _account(_fetch_financials(api_key, corp_code, year, Q3_REPORT), _OPERATING_INCOME_IDS)
            if q3 is None or q3[1] is None:
                return None
            quarter_income = income[0] - q3[1]
        shares = profit[1] / eps[1]
        tax_rate = DEFAULT_TAX_RATE
        if tax and pretax and pretax[1] and pretax[1] > 0:
            low, high = TAX_RATE_RANGE
            tax_rate = min(max(tax[1] / pretax[1], low), high)
        if quarter_income is None or shares <= 0:
            return None
        annual_eps = quarter_income * (1 - tax_rate) / shares * QUARTERS_PER_YEAR
        return annual_eps, f"{year}년 {quarter_name}"
    return None


def fetch_latest_quarter_eps(
    api_key: str, corp_code: str, today: Optional[dt.date] = None
) -> Optional[Tuple[float, str]]:
    """가장 최근 정기보고서 기준 (분기 EPS, "2026년 2분기" 같은 분기명). 없으면 None.

    4분기는 따로 보고되지 않아 사업보고서 연간 EPS - 3분기보고서 누적 EPS로 구한다.
    """
    this_year = (today or dt.date.today()).year
    for years_ago, report_code, quarter_name in _REPORTS_NEWEST_FIRST:
        year = this_year - years_ago
        amounts = _eps_amounts(_fetch_financials(api_key, corp_code, year, report_code))
        if amounts is None:
            continue
        current, cumulative = amounts
        label = f"{year}년 {quarter_name}"
        if report_code != ANNUAL_REPORT:
            return (current, label) if current is not None else None
        q3 = _eps_amounts(_fetch_financials(api_key, corp_code, year, Q3_REPORT))
        if current is None or q3 is None or q3[1] is None:
            return None
        return current - q3[1], label
    return None
