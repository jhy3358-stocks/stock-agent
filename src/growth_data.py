"""Growth FV 모듈이 쓸 라이브 시장 데이터 조회 (yfinance).

src/growth_valuation.py, src/rsi50.py는 순수 계산 함수만 담아 fixture로
테스트하기 쉽게 만들어뒀다. 이 모듈이 yfinance에서 실제 값을 가져와 그
계산 함수들에 넘겨주는 배선 역할을 한다.

신규상장주는 재무제표 항목 자체가 누락되거나(분기 수 부족) 라벨이 회사마다
달라 파싱이 실패하기 쉽다. 기존 src/valuation.py와 같은 방식으로, 값을 못
구하면 예외를 던지지 않고 관대하게 None을 반환한다 - 호출부(src/signal.py)는
자연히 legacy MA/RSI 신호로 폴백한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import pandas as pd
import yfinance as yf

from src.growth_valuation import (
    GrowthAssumptions,
    classify_stage,
    compute_stage1,
    compute_stage2,
    compute_stage3,
    discount_rate,
    load_assumptions,
    select_beta,
    ticker_configured,
)
from src.models import MarketItem
from src.rsi50 import Rsi50Result, compute_rsi50

_UNIT_M = 1_000_000.0


@lru_cache(maxsize=None)
def _yahoo_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _risk_free_rate() -> Optional[float]:
    """미국 10년물 금리 (^TNX / 100)."""
    try:
        close = yf.Ticker("^TNX").history(period="5d")["Close"]
        return float(close.iloc[-1]) / 100 if len(close) else None
    except Exception:
        return None


@lru_cache(maxsize=None)
def _quarterly_financials(ticker: str) -> Optional[pd.DataFrame]:
    try:
        qf = yf.Ticker(ticker).quarterly_financials
        return qf if qf is not None and not qf.empty else None
    except Exception:
        return None


@lru_cache(maxsize=None)
def _quarterly_cashflow(ticker: str) -> Optional[pd.DataFrame]:
    try:
        qcf = yf.Ticker(ticker).quarterly_cashflow
        return qcf if qcf is not None and not qcf.empty else None
    except Exception:
        return None


@lru_cache(maxsize=None)
def _quarterly_balance_sheet(ticker: str) -> Optional[pd.DataFrame]:
    try:
        bs = yf.Ticker(ticker).quarterly_balance_sheet
        return bs if bs is not None and not bs.empty else None
    except Exception:
        return None


@lru_cache(maxsize=None)
def _full_history_close(ticker: str) -> Optional[pd.Series]:
    """RSI50(§7)이 필요로 하는 상장 이후 전체 종가 (일별 리포트용 6개월치보다 길게)."""
    try:
        close = yf.Ticker(ticker).history(period="max", interval="1d")["Close"]
        return close if len(close) else None
    except Exception:
        return None


def _row(df: Optional[pd.DataFrame], *labels: str) -> Optional[pd.Series]:
    if df is None:
        return None
    for label in labels:
        if label in df.index:
            return df.loc[label]
    return None


def _sum_last(series: Optional[pd.Series], n: int) -> Optional[float]:
    if series is None or len(series) < n:
        return None
    values = series.iloc[:n].dropna()
    if len(values) < n:
        return None
    return float(values.sum())


def _balance_value_m(bs: Optional[pd.DataFrame], info: dict, row_labels: tuple, info_key: str) -> Optional[float]:
    row = _row(bs, *row_labels)
    if row is not None and len(row) and pd.notna(row.iloc[0]):
        return float(row.iloc[0]) / _UNIT_M
    raw = info.get(info_key)
    return raw / _UNIT_M if raw else None


# ---------------------------------------------------------------------------
# §4.1 단계 분류에 필요한 입력
# ---------------------------------------------------------------------------

@dataclass
class ClassificationInputs:
    ttm_ebitda_margin: float
    ttm_revenue: float  # $M
    quarterly_revenues: list[float]  # $M, 최근 4개
    ttm_revenue_growth: float
    gross_margin: float


def fetch_classification_inputs(symbol: str) -> Optional[ClassificationInputs]:
    qf = _quarterly_financials(symbol)
    revenue = _row(qf, "Total Revenue")
    ebitda = _row(qf, "EBITDA", "Normalized EBITDA")
    if revenue is None or ebitda is None or len(revenue) < 4:
        return None

    quarterly_revenues_m = [float(v) / _UNIT_M for v in revenue.iloc[:4]]
    ttm_revenue = sum(quarterly_revenues_m)
    ttm_ebitda = _sum_last(ebitda, 4)
    if ttm_ebitda is None or ttm_revenue <= 0:
        return None
    ttm_ebitda_margin = (ttm_ebitda / _UNIT_M) / ttm_revenue

    gross_profit = _row(qf, "Gross Profit")
    gross_margin = None
    ttm_gross_profit = _sum_last(gross_profit, 4)
    if ttm_gross_profit is not None:
        gross_margin = (ttm_gross_profit / _UNIT_M) / ttm_revenue

    info = _yahoo_info(symbol)
    if gross_margin is None:
        gross_margin = info.get("grossMargins")
    if gross_margin is None:
        return None

    ttm_revenue_growth = info.get("revenueGrowth")
    if ttm_revenue_growth is None and len(revenue) >= 8:
        prior_ttm = _sum_last(revenue.iloc[4:8], 4)
        if prior_ttm:
            ttm_revenue_growth = (ttm_revenue - prior_ttm / _UNIT_M) / (prior_ttm / _UNIT_M)
    if ttm_revenue_growth is None:
        return None

    return ClassificationInputs(
        ttm_ebitda_margin=ttm_ebitda_margin,
        ttm_revenue=ttm_revenue,
        quarterly_revenues=quarterly_revenues_m,
        ttm_revenue_growth=ttm_revenue_growth,
        gross_margin=gross_margin,
    )


def _infer_stage_from_assumptions(assumptions: GrowthAssumptions) -> int:
    """재무제표를 못 구했을 때(초기 신규상장주 등) config 구성만으로 단계를 추정한다."""
    if assumptions.segments and assumptions.segments[0].multiple is not None:
        return 1
    if assumptions.segments and assumptions.segments[0].ev_s is not None:
        return 2
    return 3


# ---------------------------------------------------------------------------
# §3.3/§3.4 FV 계산에 필요한 시장 데이터
# ---------------------------------------------------------------------------

@dataclass
class MarketInputs:
    current_shares: float  # M주 (희석)
    net_cash: float  # $M, 현금 - 부채
    fcf_ttm: float  # $M
    capex_ratio: float  # capex / 매출


def fetch_market_inputs(symbol: str) -> Optional[MarketInputs]:
    info = _yahoo_info(symbol)
    bs = _quarterly_balance_sheet(symbol)

    shares = _balance_value_m(bs, info, ("Ordinary Shares Number", "Share Issued"), "sharesOutstanding")
    if not shares:
        return None

    cash = _balance_value_m(bs, info, ("Cash And Cash Equivalents",), "totalCash") or 0.0
    debt = _balance_value_m(bs, info, ("Total Debt",), "totalDebt") or 0.0
    net_cash = cash - debt

    qcf = _quarterly_cashflow(symbol)
    fcf_ttm = _sum_last(_row(qcf, "Free Cash Flow"), 4)
    fcf_ttm = fcf_ttm / _UNIT_M if fcf_ttm is not None else (info.get("freeCashflow") or 0) / _UNIT_M

    capex_ttm = _sum_last(_row(qcf, "Capital Expenditure"), 4)
    revenue_ttm_raw = _sum_last(_row(_quarterly_financials(symbol), "Total Revenue"), 4)
    capex_ratio = abs(capex_ttm) / revenue_ttm_raw if capex_ttm is not None and revenue_ttm_raw else 0.0

    return MarketInputs(current_shares=shares, net_cash=net_cash, fcf_ttm=fcf_ttm, capex_ratio=capex_ratio)


# ---------------------------------------------------------------------------
# §3.1 할인율
# ---------------------------------------------------------------------------

def _listed_over_1y(symbol: str) -> bool:
    close = _full_history_close(symbol)
    if close is None or len(close) < 2:
        return True  # 히스토리를 못 구하면 안전하게 "기존 상장주"로 취급
    span_days = (close.index[-1] - close.index[0]).days
    return span_days >= 365


def fetch_discount_rate(symbol: str, assumptions: GrowthAssumptions) -> Optional[float]:
    rf = _risk_free_rate()
    if rf is None:
        return None
    live_beta = _yahoo_info(symbol).get("beta")
    try:
        beta = select_beta(live_beta, _listed_over_1y(symbol), assumptions.peer_beta)
    except ValueError:
        return None
    return discount_rate(rf, beta, assumptions.erp, assumptions.r_floor)


# ---------------------------------------------------------------------------
# 종합
# ---------------------------------------------------------------------------

@dataclass
class GrowthFairValueSummary:
    stage: int
    fv: float
    gap_pct: float  # (현재가-FV)/FV * 100
    required: dict
    rsi50: Rsi50Result


def growth_fair_value(item: MarketItem) -> Optional[GrowthFairValueSummary]:
    """§1 라우팅에서 GRAV를 못 쓸 때의 대체 모듈 진입점.

    config/growth_assumptions.yaml에 종목 가정값이 없으면 이 함수는 아무것도
    하지 않고 None을 반환한다 (호출부가 legacy MA/RSI 신호로 폴백).
    """
    if not ticker_configured(item.symbol):
        return None
    assumptions = load_assumptions(item.symbol)
    if assumptions.P is None:
        return None

    r = fetch_discount_rate(item.symbol, assumptions)
    market = fetch_market_inputs(item.symbol)
    if r is None or market is None:
        return None

    classification = fetch_classification_inputs(item.symbol)
    if classification is not None:
        stage = classify_stage(
            classification.ttm_ebitda_margin,
            classification.ttm_revenue,
            classification.quarterly_revenues,
            classification.ttm_revenue_growth,
            classification.gross_margin,
        )
        r0_revenue, g0_growth = classification.ttm_revenue, classification.ttm_revenue_growth
    else:
        stage = _infer_stage_from_assumptions(assumptions)
        r0_revenue, g0_growth = 0.0, 0.0

    try:
        if stage == 1:
            result = compute_stage1(
                assumptions=assumptions,
                current_price=item.current_price,
                current_shares=market.current_shares,
                r0_revenue=r0_revenue,
                g0_growth=g0_growth,
                r=r,
                net_cash=market.net_cash,
                fcf_ttm=market.fcf_ttm,
                capex_ratio=market.capex_ratio,
            )
        elif stage == 2:
            result = compute_stage2(
                assumptions=assumptions,
                current_price=item.current_price,
                current_shares=market.current_shares,
                r0_revenue=r0_revenue,
                r=r,
                net_cash=market.net_cash,
                fcf_ttm=market.fcf_ttm,
            )
        else:
            result = compute_stage3(
                assumptions=assumptions,
                current_price=item.current_price,
                current_shares=market.current_shares,
                r=r,
                net_cash=market.net_cash,
                fcf_ttm=market.fcf_ttm,
            )
    except (TypeError, ZeroDivisionError, AttributeError):
        # segments/tam_T 등 해당 단계에 필요한 가정값이 config에 없는 경우
        return None

    if result.fv <= 0:
        return None

    close = _full_history_close(item.symbol)
    rsi50 = compute_rsi50(close) if close is not None else Rsi50Result(float("nan"), 0, float("nan"), True)

    gap_pct = (item.current_price - result.fv) / result.fv * 100
    return GrowthFairValueSummary(stage=stage, fv=result.fv, gap_pct=gap_pct, required=result.required, rsi50=rsi50)


def required_condition_text(summary: GrowthFairValueSummary) -> str:
    """§6 리포트 문구 - 현재가를 정당화하려면 무엇이 필요한지."""
    req = summary.required
    if summary.stage == 1 and req.get("revenue_req"):
        return f"현재가 정당화 조건: 매출 ${req['revenue_req']:,.0f}M 필요"
    if summary.stage == 2 and req.get("revenue_req"):
        cagr = req.get("cagr_req")
        cagr_txt = f", 필요 CAGR 약 {cagr * 100:.0f}%" if cagr is not None else ""
        multiple = req.get("multiple_of_current")
        multiple_txt = f" (현재의 약 {multiple:.1f}배)" if multiple is not None else ""
        return f"현재가 정당화 조건: 매출 ${req['revenue_req']:,.0f}M 필요{multiple_txt}{cagr_txt}"
    if summary.stage == 3 and req.get("market_share_req") is not None:
        return f"현재가 정당화 조건: 시장점유율 {req['market_share_req'] * 100:.1f}% 필요"
    return "역산 필요조건 계산 불가"
