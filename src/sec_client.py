"""미국 SEC EDGAR 공시 수집 (data.sec.gov, API 키 불필요).

SEC는 요청 시 연락 가능한 User-Agent를 요구한다 (Fair Access 정책).
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

import requests

SEC_HEADERS = {"User-Agent": "stock-agent-report (contact: jhy3358@gmail.com)"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

# 매우 빈번하게 제출되는 내부자 거래/지분 매각 신고서는 "주요 소식"으로 보기 어려워 제외한다.
EXCLUDED_FORMS = {"3", "4", "5", "3/A", "4/A", "5/A", "144", "144/A"}

FORM_LABELS = {
    "8-K": "주요사항보고 (8-K)",
    "10-Q": "분기보고서 (10-Q)",
    "10-K": "연차보고서 (10-K)",
    "11-K": "종업원지주제도 보고서 (11-K)",
    "DEF 14A": "주주총회 안건 (DEF 14A)",
    "PX14A6G": "주주제안 관련 (PX14A6G)",
}


def _describe_form(form: str) -> str:
    return FORM_LABELS.get(form, form)


def fetch_cik_map(tickers: List[str]) -> Dict[str, str]:
    """티커 -> 10자리 zero-padded CIK 매핑을 만든다."""
    response = requests.get(TICKERS_URL, headers=SEC_HEADERS, timeout=15)
    response.raise_for_status()
    wanted = set(tickers)
    result: Dict[str, str] = {}
    for entry in response.json().values():
        ticker = entry["ticker"]
        if ticker in wanted:
            result[ticker] = str(entry["cik_str"]).zfill(10)
    return result


def fetch_recent_filings(cik10: str, days: int = 7) -> List[dict]:
    """최근 N일 이내의 주요 공시 목록을 반환한다."""
    response = requests.get(
        SUBMISSIONS_URL.format(cik10=cik10), headers=SEC_HEADERS, timeout=15
    )
    response.raise_for_status()
    recent = response.json()["filings"]["recent"]
    cutoff = dt.date.today() - dt.timedelta(days=days)

    filings = []
    for i, form in enumerate(recent["form"]):
        if form in EXCLUDED_FORMS:
            continue
        filing_date = dt.date.fromisoformat(recent["filingDate"][i])
        if filing_date < cutoff:
            continue
        accession = recent["accessionNumber"][i].replace("-", "")
        cik_no_padding = str(int(cik10))
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_no_padding}/{accession}/{recent['primaryDocument'][i]}"
        )
        filings.append({"title": _describe_form(form), "date": filing_date, "url": url})
    return filings


def get_recent_filings_for_tickers(tickers: List[str], days: int = 7) -> Dict[str, List[dict]]:
    cik_map = fetch_cik_map(tickers)
    result: Dict[str, List[dict]] = {}
    for ticker in tickers:
        cik10 = cik_map.get(ticker)
        result[ticker] = fetch_recent_filings(cik10, days) if cik10 else []
    return result
