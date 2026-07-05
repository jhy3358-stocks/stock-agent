"""국내 DART 공시 수집 (OpenDART Open API, 무료 인증키 필요)."""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

import requests

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
    response.raise_for_status()
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
    return {
        stock_code: fetch_recent_disclosures(api_key, corp_code, days)
        for stock_code, corp_code in corp_codes.items()
    }
