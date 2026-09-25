"""미국 SEC EDGAR 공시 수집 (data.sec.gov, API 키 불필요).

SEC는 요청 시 연락 가능한 User-Agent를 요구한다 (Fair Access 정책).
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Dict, List

import requests

from src.concurrency import fetch_all, safe_call

SEC_HEADERS = {"User-Agent": "stock-agent-report (contact: jhy3358@gmail.com)"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
# SEC Fair Access 정책상 초당 10건 이하로 요청해야 해서 동시 요청 수를 낮게 둔다.
SEC_MAX_WORKERS = 3

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


@lru_cache(maxsize=1)
def all_ciks() -> Dict[str, str]:
    """SEC 전체 티커 -> 10자리 zero-padded CIK (공시 조회·EPS 조회가 함께 쓴다)."""
    response = requests.get(TICKERS_URL, headers=SEC_HEADERS, timeout=15)
    response.raise_for_status()
    return {entry["ticker"]: str(entry["cik_str"]).zfill(10) for entry in response.json().values()}


def fetch_cik_map(tickers: List[str]) -> Dict[str, str]:
    """티커 -> 10자리 zero-padded CIK 매핑을 만든다."""
    ciks = all_ciks()
    return {ticker: ciks[ticker] for ticker in tickers if ticker in ciks}


@lru_cache(maxsize=None)
def fetch_submissions(cik10: str) -> dict:
    """회사별 최근 제출 목록(filings.recent) 원본."""
    response = requests.get(
        SUBMISSIONS_URL.format(cik10=cik10), headers=SEC_HEADERS, timeout=15
    )
    response.raise_for_status()
    return response.json()["filings"]["recent"]


def fetch_recent_filings(cik10: str, days: int = 7) -> List[dict]:
    """최근 N일 이내의 주요 공시 목록을 반환한다."""
    recent = fetch_submissions(cik10)
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
    cik_map = safe_call("SEC 티커-CIK 매핑 조회", fetch_cik_map, tickers, default={})
    return fetch_all(
        tickers,
        lambda ticker: fetch_recent_filings(cik_map[ticker], days) if ticker in cik_map else [],
        what="SEC 공시",
        default=[],
        max_workers=SEC_MAX_WORKERS,
    )
