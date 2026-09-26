"""적정주가 계산 - GRAV 모델(기존) + M-GRAV(해자 반영) 모델.

[기존] GRAV(Growth Risk-Adjusted Valuation) 모델
  적정주가 = EPS x Target P/E x (1 + g/100) / beta
  EPS는 가장 최근 분기 영업이익 기반 EPS의 연 환산값이다:
    분기 영업이익 x (1 - 실효세율) / 희석 주식수 x (365 / 분기 일수)
  순이익 EPS는 영업외 손익(투자 평가이익 등)에 크게 흔들려 전 종목 같은 정의로 영업이익을
  쓴다. 미국 종목은 SEC XBRL + 실적 발표 8-K(src/sec_operating_eps.py), 국내 종목은 DART
  정기보고서(src/dart_client.py). 영업이익을 구할 수 없으면 분기 희석 EPS x 4, 그마저
  없으면 Yahoo 값으로 대체한다(_eps 참고).
  Target P/E는 현재가와 무관한 멀티플이어야 해서(현재가로 계산한 P/E를 쓰면 EPS x
  P/E가 그냥 현재가가 된다) 애널리스트 목표주가 평균 / 추정 EPS를 쓴다. 국내 종목은
  네이버페이 증권 값에 코리아 디스카운트(config.KOREA_DISCOUNT)를 적용하고
  (src/naver_finance_client.py), 미국 종목은 Yahoo 값을 쓴다(_target_pe 참고).
  g(3~5년 이익성장률)는 config.VALUATION에 사람이 주기적으로 조사해 채워둔 값을 쓰고,
  beta는 최근 2년 주간 베타에 블룸 보정한 값을 실행 시 계산한다(src/beta.py, 실패 시
  config 값).

[신규] M-GRAV(해자 반영 GRAV) 모델
  적정주가 = EPS x Target P/E x (1 + g/100) / beta^(1/M_factor)
  M_factor = 1 + M_score/100 (M_score 0~100, 기술독점성/락인/OPM체력/진입장벽
  4개 항목을 각 25점 배점으로 평가). 해자가 강할수록(M_score 높을수록) beta의
  지수(1/M_factor)가 작아져 변동성 페널티가 완화된다. Target P/E·M_score는
  config.M_GRAV 값을 쓰고, Target P/E는 GRAV와 같은 값을 쓴다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from config import BETA_FLOOR, KOREA_DISCOUNT, KR_DART_CORP_CODES, M_GRAV, VALUATION
from src.beta import adjusted_beta, prefetch_betas
from src.concurrency import fetch_all, safe_call
from src.dart_cache import cached
from src.finviz_client import fetch_forward_metrics
from src.dart_client import fetch_latest_quarter_eps as dart_latest_quarter_eps
from src.dart_client import fetch_latest_quarter_operating_eps as dart_operating_eps
from src.models import MarketItem
from src.naver_finance_client import fetch_target_pe
from src.sec_client import SEC_MAX_WORKERS
from src.sec_eps import latest_quarter_eps
from src.sec_operating_eps import annual_operating_eps
from src.yf_data import yahoo_info, yahoo_ticker


@lru_cache(maxsize=None)
def _finviz_forward_pe(symbol: str) -> Optional[float]:
    """Finviz Forward P/E. 조회 실패/미지원 시 None."""
    return fetch_forward_metrics(symbol)["forward_pe"]


def _average(*values: Optional[float]) -> Optional[float]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _forward_pe(item: MarketItem) -> Optional[float]:
    """Yahoo/Finviz 라이브 Forward P/E 평균. 둘 중 한쪽만 있으면 그 값을 그대로 쓴다."""
    yahoo_pe = yahoo_info(yahoo_ticker(item.symbol, item.market)).get("forwardPE")
    # Finviz는 KRX 상장 종목을 다루지 않는다 (KR 종목은 Yahoo 단일 소스로 대체).
    finviz_pe = None if item.market == "KR" else _finviz_forward_pe(item.symbol)
    return _average(yahoo_pe, finviz_pe)


# 영업이익 EPS를 못 구할 때 대체하는 분기 순이익 EPS의 연 환산 배수
QUARTERS_PER_YEAR = 4


def _dart_call(what: str, fn, stock_code: str):
    """DART_API_KEY나 corp_code가 없거나 조회 실패 시 None."""
    api_key = os.environ.get("DART_API_KEY")
    corp_code = KR_DART_CORP_CODES.get(stock_code)
    if not api_key or corp_code is None:
        return None
    return safe_call(f"{stock_code} {what}", fn, api_key, corp_code, default=None)


@lru_cache(maxsize=None)
def _dart_operating_eps(stock_code: str) -> Optional[tuple[float, str]]:
    """(영업이익 EPS 연 환산, 분기명). 조회 실패 시 마지막으로 저장한 값."""
    return cached("operating_eps", stock_code,
                  lambda: _dart_call("DART 영업이익 EPS 조회", dart_operating_eps, stock_code))


@lru_cache(maxsize=None)
def _dart_quarter_eps(stock_code: str) -> Optional[tuple[float, str]]:
    """(분기 희석 EPS, 분기명). 조회 실패 시 마지막으로 저장한 값."""
    return cached("quarter_eps", stock_code,
                  lambda: _dart_call("DART EPS 조회", dart_latest_quarter_eps, stock_code))


def _annual_operating_eps(item: MarketItem) -> Optional[float]:
    if item.market == "KR":
        result = _dart_operating_eps(item.symbol)
        return result[0] if result else None
    result = safe_call(f"{item.symbol} SEC 영업이익 EPS 조회", annual_operating_eps, item.symbol, default=None)
    return result.value if result else None


def _quarter_eps(item: MarketItem) -> Optional[float]:
    """가장 최근 발표 분기 희석 EPS - 미국은 SEC 8-K, 국내는 DART 정기보고서."""
    if item.market == "KR":
        result = _dart_quarter_eps(item.symbol)
        return result[0] if result else None
    result = safe_call(f"{item.symbol} SEC EPS 조회", latest_quarter_eps, item.symbol, default=None)
    return result.value if result else None


def _eps(item: MarketItem) -> Optional[float]:
    """연간 EPS - 영업이익 기반 EPS(연 환산) 우선, 없으면 분기 희석 EPS x 4, 없으면 Yahoo.

    Yahoo가 trailingEps를 안 주는 종목은 trailingPE와 현재가로 역산하고, 그마저
    없으면 적정주가가 아예 빠지지 않도록 Forward EPS(forwardEps 또는
    현재가/forwardPE)로 대체한다.
    """
    operating = _annual_operating_eps(item)
    if operating is not None:
        return operating
    quarter = _quarter_eps(item)
    if quarter is not None:
        return quarter * QUARTERS_PER_YEAR
    info = yahoo_info(yahoo_ticker(item.symbol, item.market))
    if info.get("trailingEps") is not None:
        return info["trailingEps"]
    if info.get("trailingPE"):
        return item.current_price / info["trailingPE"]
    if info.get("forwardEps") is not None:
        return info["forwardEps"]
    if info.get("forwardPE"):
        return item.current_price / info["forwardPE"]
    return None


def _naver_target_pe(stock_code: str) -> Optional[float]:
    return safe_call(f"{stock_code} 네이버 목표 P/E 조회", fetch_target_pe, stock_code, default=None)


def _yahoo_target_pe(symbol: str) -> Optional[float]:
    """Yahoo 애널리스트 목표주가 평균(targetMeanPrice) / 추정 EPS(forwardEps)."""
    info = yahoo_info(symbol)
    target_price, forward_eps = info.get("targetMeanPrice"), info.get("forwardEps")
    if not target_price or not forward_eps or forward_eps <= 0:
        return None
    return target_price / forward_eps


def _target_pe(item: MarketItem) -> Optional[float]:
    """GRAV·M-GRAV 공통 멀티플 = 애널리스트 목표주가 평균 / 추정 EPS.

    국내: 네이버페이 증권 값 x (1 - 코리아 디스카운트), 미국: Yahoo 값.
    조회 실패 시 config.M_GRAV target_pe, 그마저 없으면 라이브 Forward P/E.
    """
    if item.market == "KR":
        target_pe = _naver_target_pe(item.symbol)
        if target_pe is not None:
            return target_pe * (1 - KOREA_DISCOUNT)
    else:
        target_pe = _yahoo_target_pe(item.symbol)
        if target_pe is not None:
            return target_pe
    fallback = (M_GRAV.get(item.symbol) or {}).get("target_pe")
    if fallback is not None:
        return fallback
    # 적자 예상 종목은 Forward P/E가 음수라 멀티플로 쓸 수 없다.
    forward_pe = _forward_pe(item)
    return forward_pe if forward_pe is not None and forward_pe > 0 else None


def _beta(item: MarketItem) -> float:
    """조정 베타(주간 2년 + 블룸 보정, 구하지 못하면 config.VALUATION 값). 하한 BETA_FLOOR."""
    beta = adjusted_beta(item.symbol, item.market)
    if beta is None:
        beta = VALUATION[item.symbol]["beta"]
    return max(beta, BETA_FLOOR)


def fair_value_inputs(item: MarketItem) -> Optional[dict]:
    """적정주가 계산에 필요한 eps/target_pe/growth_rate/beta 묶음.

    g/beta가 config에 없거나, EPS 또는 Target P/E를 구하지 못하면
    None을 반환한다 (예: SPCX처럼 애널리스트 커버리지가 없는 종목).
    """
    valuation = VALUATION.get(item.symbol)
    if valuation is None:
        return None

    eps, target_pe = _eps(item), _target_pe(item)
    if target_pe is None or eps is None:
        return None

    return {
        "eps": eps,
        "target_pe": target_pe,
        "growth_rate": valuation["growth_rate"],
        "beta": _beta(item),
    }


def target_price(eps: float, target_pe: float, growth_rate: float, beta: float) -> float:
    return eps * target_pe * (1 + growth_rate / 100) / beta


# yfinance 원본 데이터는 ADR 종목(예: SKHY)처럼 통화/단위가 뒤섞여 자릿수
# 자체가 틀어지는 경우가 확인됐다. 적정주가가 현재가와 자릿수가 다르게
# 튀면(10배 이상 차이) 계산이 아니라 데이터 오염·가정 오류로 보고 버린다
# (GRAV·M-GRAV·Growth FV 공통, src/signal.py에서 적용).
SANITY_BAND = 10


def is_sane(value: float, current_price: float) -> bool:
    return current_price / SANITY_BAND <= value <= current_price * SANITY_BAND


def prefetch_valuation_inputs(items: list[MarketItem]) -> None:
    """리포트 렌더링 중 종목마다 순차로 일어나는 Yahoo .info / Finviz / SEC·DART
    EPS / 네이버 목표 P/E 조회를 미리 병렬로 채워둔다 (모두 lru_cache라 이후 호출은 캐시를 쓴다)."""
    targets = [item for item in items if item.symbol in VALUATION]
    prefetch_betas([(item.symbol, item.market) for item in targets])
    fetch_all(
        [yahoo_ticker(item.symbol, item.market) for item in targets],
        yahoo_info,
        what="Yahoo .info",
        default={},
    )
    us_symbols = [item.symbol for item in targets if item.market != "KR"]
    fetch_all(us_symbols, _finviz_forward_pe, what="Finviz", default=None)
    fetch_all(
        us_symbols, annual_operating_eps, what="SEC 영업이익 EPS", default=None,
        max_workers=SEC_MAX_WORKERS,
    )
    fetch_all(
        [item.symbol for item in targets if item.market == "KR"],
        _dart_operating_eps,
        what="DART 영업이익 EPS",
        default=None,
    )
    fetch_all(
        [item.symbol for item in targets if item.market == "KR"],
        fetch_target_pe,
        what="네이버 목표 P/E",
        default=None,
    )


def m_grav_fair_value(item: MarketItem) -> Optional[float]:
    """M-GRAV(해자 반영 GRAV): 적정주가 = EPS x Target PE x (1+g/100) / beta^(1/m_factor).

    Target PE는 GRAV와 같은 값(_target_pe), M_score는 config.M_GRAV, g/beta는
    config.VALUATION 값을 쓴다.
    필요한 값을 하나라도 못 구하면 None을 반환한다.
    """
    valuation = VALUATION.get(item.symbol)
    m_grav = M_GRAV.get(item.symbol)
    if valuation is None or m_grav is None:
        return None

    eps = _eps(item)
    if eps is None:
        return None

    target_pe = _target_pe(item)
    if target_pe is None:
        return None

    beta = _beta(item)
    g = valuation["growth_rate"]
    m_factor = 1 + m_grav["m_score"] / 100
    return eps * target_pe * (1 + g / 100) / (beta ** (1 / m_factor))
