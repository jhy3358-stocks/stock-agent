"""GRAV(Growth Risk-Adjusted Valuation) 모델 기반 적정주가 계산.

적정주가 = 평균(Forward EPS) x 평균(Forward P/E) x (1 + g/100) / sqrt(beta)

Forward EPS/Forward P/E는 실행할 때마다 Yahoo Finance(yfinance)와 Finviz에서
라이브로 조회해 평균을 낸다 (둘 중 한쪽만 있으면 그 값을 그대로 쓴다).
g(3~5년 이익성장률)·beta(시장 대비 변동성 배수)는 두 값 모두 라이브로 안정적으로
구하기 어려워 config.VALUATION에 사람이 주기적으로 조사해 채워둔 값을 쓴다.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

import yfinance as yf

from config import VALUATION
from src.finviz_client import fetch_forward_metrics
from src.models import MarketItem


def _yahoo_ticker(item: MarketItem) -> str:
    return f"{item.symbol}.KS" if item.market == "KR" else item.symbol


@lru_cache(maxsize=None)
def _yahoo_forward_metrics(yahoo_ticker: str) -> tuple[Optional[float], Optional[float]]:
    """(forward_pe, forward_eps). yfinance 조회 실패 시 (None, None)."""
    try:
        info = yf.Ticker(yahoo_ticker).info
    except Exception:
        return (None, None)
    return (info.get("forwardPE"), info.get("forwardEps"))


@lru_cache(maxsize=None)
def _finviz_forward_metrics(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """(forward_pe, forward_eps). Finviz 조회 실패/미지원 시 (None, None)."""
    data = fetch_forward_metrics(symbol)
    return (data["forward_pe"], data["forward_eps"])


def _average(*values: Optional[float]) -> Optional[float]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def fair_value_inputs(item: MarketItem) -> Optional[dict]:
    """적정주가 계산에 필요한 forward_eps/forward_pe/growth_rate/beta 묶음.

    g/beta가 config에 없거나, Forward EPS/PE를 두 소스 모두에서 구하지
    못하면 None을 반환한다 (예: SPCX처럼 애널리스트 커버리지가 없는 종목).
    """
    valuation = VALUATION.get(item.symbol)
    if valuation is None:
        return None

    yahoo_pe, yahoo_eps = _yahoo_forward_metrics(_yahoo_ticker(item))
    # Finviz는 KRX 상장 종목을 다루지 않는다 (KR 종목은 Yahoo 단일 소스로 대체).
    if item.market == "KR":
        finviz_pe, finviz_eps = (None, None)
    else:
        finviz_pe, finviz_eps = _finviz_forward_metrics(item.symbol)

    # Yahoo가 forwardEps를 안 주는 종목(주로 KR)은 forwardPE와 현재가로 역산한다.
    if yahoo_eps is None and yahoo_pe:
        yahoo_eps = item.current_price / yahoo_pe

    forward_pe = _average(yahoo_pe, finviz_pe)
    forward_eps = _average(yahoo_eps, finviz_eps)
    if forward_pe is None or forward_eps is None:
        return None

    return {
        "forward_eps": forward_eps,
        "forward_pe": forward_pe,
        "growth_rate": valuation["growth_rate"],
        "beta": valuation["beta"],
    }


def target_price(forward_eps: float, forward_pe: float, growth_rate: float, beta: float) -> float:
    return forward_eps * forward_pe * (1 + growth_rate / 100) / math.sqrt(beta)
