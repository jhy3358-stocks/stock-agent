"""네이버페이 증권(m.stock.naver.com) 컨센서스에서 국내 종목의 목표 P/E 조회.

목표 P/E = 애널리스트 목표주가 평균 / 추정 EPS(컨센서스). 애널리스트가 목표주가를
낼 때 적용한 멀티플이라 현재가와 무관하다 (추정PER = 현재가 / 추정EPS와 다름).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import requests

INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _number(raw: Optional[str]) -> Optional[float]:
    """"493,864", "47,922원", "5.98배" 같은 표기를 숫자로. 값이 없으면 None."""
    if not raw:
        return None
    try:
        return float(raw.replace(",", "").rstrip("원배"))
    except ValueError:
        return None


def target_pe_from_integration(data: dict) -> Optional[float]:
    """목표주가 평균 / 추정 EPS. 둘 중 하나가 없거나 추정 EPS가 0 이하면 None."""
    target_price = _number((data.get("consensusInfo") or {}).get("priceTargetMean"))
    infos = {info["code"]: info["value"] for info in data.get("totalInfos", [])}
    consensus_eps = _number(infos.get("cnsEps"))
    if target_price is None or consensus_eps is None or consensus_eps <= 0:
        return None
    return target_price / consensus_eps


@lru_cache(maxsize=None)
def fetch_target_pe(code: str) -> Optional[float]:
    """국내 종목코드의 목표 P/E (목표주가 평균 / 추정 EPS)."""
    response = requests.get(INTEGRATION_URL.format(code=code), headers=_HEADERS, timeout=10)
    response.raise_for_status()
    return target_pe_from_integration(response.json())
