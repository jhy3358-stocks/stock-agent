"""국내 DART 공시 수집 (OpenDART Open API, 무료 인증키 필요)."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import requests

from src.concurrency import fetch_all

LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# 매우 빈번하게 제출되는 임원/주요주주 지분 변동 보고서는 "주요 소식"으로 보기 어려워 제외한다.
EXCLUDED_KEYWORDS = ("임원ㆍ주요주주특정증권등소유상황보고서",)


def fetch_recent_disclosures(api_key: str, corp_code: str, days: int = 7) -> List[dict]:
    """최근 N일 이내의 주요 공시 목록을 반환한다."""
    end_date = dt.date.today()
    begin_date = end_date - dt.timedelta(days=days)
    response = requests.get(
        LIST_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": begin_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "page_count": 30,
        },
        timeout=15,
    )
    # raise_for_status()의 오류 메시지에는 인증키(crtfc_key)가 담긴 요청 URL이
    # 그대로 들어가 로그(GitHub Actions)에 노출되므로 상태 코드만 남긴다.
    if response.status_code != 200:
        raise RuntimeError(f"DART 공시 조회 실패: HTTP {response.status_code}")
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
    response = requests.get(
        FINANCIALS_URL,
        params={
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
            "fs_div": "CFS",
        },
        timeout=15,
    )
    # 오류 메시지에 인증키가 담긴 URL이 노출되지 않도록 상태 코드만 남긴다 (위와 동일).
    if response.status_code != 200:
        raise RuntimeError(f"DART 재무제표 조회 실패: HTTP {response.status_code}")
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
