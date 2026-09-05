"""적정주가 계산 - GRAV 모델(기존) + DCF/상대가치를 합친 종합(median) 모델.

[기존] GRAV(Growth Risk-Adjusted Valuation) 모델
  적정주가 = 평균(Forward EPS) x 평균(Forward P/E) x (1 + g/100) / sqrt(beta)
  Forward EPS/Forward P/E는 실행할 때마다 Yahoo Finance(yfinance)와 Finviz에서
  라이브로 조회해 평균을 낸다 (둘 중 한쪽만 있으면 그 값을 그대로 쓴다).
  g(3~5년 이익성장률)·beta(시장 대비 변동성 배수)는 두 값 모두 라이브로 안정적으로
  구하기 어려워 config.VALUATION에 사람이 주기적으로 조사해 채워둔 값을 쓴다.

[신규] 종합(median) 모델 - 아래 4개 값 중 구할 수 있는 값들의 median:
  1) 위 GRAV 모델
  2) DCF (2단계: 개별 g -> terminal 3%로 5년 fade, CAPM 기반 WACC로 할인)
  3) 업종평균 PER 상대가치 = 자사 trailing EPS x 업종 피어그룹 평균 trailing PER
  4) 업종평균 EV/EBITDA 상대가치 = (자사 EBITDA x 업종 피어그룹 평균 EV/EBITDA - 순부채) / 발행주식수
  업종 피어그룹 평균(PER/EV-EBITDA)은 g/beta와 마찬가지로 라이브로 안정적으로
  구하기 어려워 config.RELATIVE_VALUATION에 사람이 주기적으로 조사해 채워둔 값을 쓴다.
"""
from __future__ import annotations

import math
import statistics
from functools import lru_cache
from typing import Optional

import yfinance as yf

from config import RELATIVE_VALUATION, VALUATION
from src.finviz_client import fetch_forward_metrics
from src.models import MarketItem

# DCF 가정치 (2026-09 기준): 무위험이자율(Rf)은 미 10년물, ERP는 통상적인 5%,
# 부채비용(Rd)은 Rf+스프레드 근사치, 세율은 미 법인세 실효세율 근사치를 사용.
RISK_FREE_RATE = 0.043
EQUITY_RISK_PREMIUM = 0.05
COST_OF_DEBT = 0.058
TAX_RATE = 0.21
TERMINAL_GROWTH = 0.03
DCF_EXPLICIT_YEARS = 5


def _yahoo_ticker(item: MarketItem) -> str:
    return f"{item.symbol}.KS" if item.market == "KR" else item.symbol


@lru_cache(maxsize=None)
def _yahoo_info(yahoo_ticker: str) -> dict:
    """yfinance .info 스냅샷. 실패 시 빈 dict (호출부에서 .get으로 안전하게 처리)."""
    try:
        return yf.Ticker(yahoo_ticker).info
    except Exception:
        return {}


def _yahoo_forward_metrics(yahoo_ticker: str) -> tuple[Optional[float], Optional[float]]:
    """(forward_pe, forward_eps). yfinance 조회 실패 시 (None, None)."""
    info = _yahoo_info(yahoo_ticker)
    return (info.get("forwardPE"), info.get("forwardEps"))


@lru_cache(maxsize=None)
def _trailing_eps(yahoo_ticker: str) -> Optional[float]:
    """trailing(실적 기준) EPS. info에 없으면(주로 KR) 손익계산서에서 직접 계산."""
    info = _yahoo_info(yahoo_ticker)
    eps = info.get("trailingEps")
    if eps is not None:
        return eps
    try:
        stmt = yf.Ticker(yahoo_ticker).get_income_stmt(freq="trailing")
        if "DilutedEPS" in stmt.index:
            value = stmt.loc["DilutedEPS"].iloc[0]
            if value == value:  # NaN 체크
                return float(value)
    except Exception:
        pass
    return None


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


# DCF/상대가치는 yfinance 재무제표(순이익·EBITDA·FCF·주식수) 원본에 의존하는데,
# ADR 종목(예: SKHY)처럼 통화/단위가 뒤섞여 자릿수 자체가 틀어지는 경우가
# 확인됐다. 결과가 현재가와 자릿수가 다르게 튀면(10배 이상 차이) 계산이 아니라
# 데이터 오염으로 보고 버린다.
_SANITY_BAND = 10


def _is_sane(value: float, current_price: float) -> bool:
    return current_price / _SANITY_BAND <= value <= current_price * _SANITY_BAND


def dcf_fair_value(item: MarketItem) -> Optional[float]:
    """2단계 DCF: 5년 explicit(개별 g -> terminal 3% fade) + terminal value.

    FCF가 없거나 음수, WACC<=terminal_g, 결과가 음수인 경우 등 계산이
    의미 없는 상황에서는 None을 반환한다.
    """
    valuation = VALUATION.get(item.symbol)
    if valuation is None:
        return None

    info = _yahoo_info(_yahoo_ticker(item))
    fcf = info.get("freeCashflow")
    shares = info.get("sharesOutstanding")
    market_cap = info.get("marketCap")
    debt = info.get("totalDebt") or 0
    cash = info.get("totalCash") or 0
    if not fcf or fcf <= 0 or not shares or not market_cap:
        return None

    beta = valuation["beta"]
    g = valuation["growth_rate"] / 100
    net_debt = debt - cash
    cost_of_equity = RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM
    total_capital = debt + market_cap
    wacc = (
        (market_cap / total_capital) * cost_of_equity
        + (debt / total_capital) * COST_OF_DEBT * (1 - TAX_RATE)
        if total_capital > 0
        else cost_of_equity
    )
    if wacc <= TERMINAL_GROWTH:
        return None

    pv = 0.0
    for year in range(1, DCF_EXPLICIT_YEARS + 1):
        g_fade = g - (g - TERMINAL_GROWTH) * (year - 1) / (DCF_EXPLICIT_YEARS - 1)
        fcf *= 1 + g_fade
        pv += fcf / (1 + wacc) ** year
    terminal_value = fcf * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH)
    pv += terminal_value / (1 + wacc) ** DCF_EXPLICIT_YEARS

    equity_value = pv - net_debt
    if equity_value <= 0:
        return None
    result = equity_value / shares
    return result if _is_sane(result, item.current_price) else None


def relative_per_fair_value(item: MarketItem) -> Optional[float]:
    """업종평균 PER 상대가치 = 자사 trailing EPS x 업종 피어그룹 평균 trailing PER."""
    peers = RELATIVE_VALUATION.get(item.symbol)
    if not peers or peers.get("peer_per") is None:
        return None
    eps = _trailing_eps(_yahoo_ticker(item))
    if not eps:
        return None
    result = eps * peers["peer_per"]
    return result if _is_sane(result, item.current_price) else None


def relative_ev_ebitda_fair_value(item: MarketItem) -> Optional[float]:
    """업종평균 EV/EBITDA 상대가치.

    목표EV = 자사 EBITDA x 업종 피어그룹 평균 EV/EBITDA
    목표 시가총액 = 목표EV - 순부채, 적정주가 = 목표 시가총액 / 발행주식수
    """
    peers = RELATIVE_VALUATION.get(item.symbol)
    if not peers or peers.get("peer_ev_ebitda") is None:
        return None
    info = _yahoo_info(_yahoo_ticker(item))
    ebitda = info.get("ebitda")
    shares = info.get("sharesOutstanding")
    debt = info.get("totalDebt") or 0
    cash = info.get("totalCash") or 0
    if not ebitda or not shares:
        return None
    target_ev = ebitda * peers["peer_ev_ebitda"]
    equity_value = target_ev - (debt - cash)
    if equity_value <= 0:
        return None
    result = equity_value / shares
    return result if _is_sane(result, item.current_price) else None


def median_fair_value(item: MarketItem) -> Optional[float]:
    """GRAV 모델 + DCF + 업종평균 PER + 업종평균 EV/EBITDA 중 구할 수 있는
    값들의 median. 방법 하나가 데이터 오염 등으로 튀어도 나머지가 정상이면
    median이 어느 정도 걸러준다 (단, 여러 방법이 동시에 깨지면 못 걸러낸다)."""
    candidates = []
    inputs = fair_value_inputs(item)
    if inputs:
        candidates.append(target_price(**inputs))
    for fn in (dcf_fair_value, relative_per_fair_value, relative_ev_ebitda_fair_value):
        value = fn(item)
        if value:
            candidates.append(value)
    if not candidates:
        return None
    return statistics.median(candidates)
