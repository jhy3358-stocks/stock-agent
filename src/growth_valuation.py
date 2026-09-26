"""중소형 성장주 적정가(Growth FV) 모듈.

docs/growth_valuation_spec.md 구현. 기존 GRAV(src/valuation.py)와는
독립된 모듈이며, Forward EPS가 없거나 음수인 성장주/신규상장주에 쓴다
(GRAV ↔ Growth FV 라우팅은 이 모듈을 호출하는 쪽의 책임이며, 이 모듈은
그 배선을 하지 않는다).

모든 계산 함수는 yfinance 등 외부 데이터를 직접 조회하지 않고 명시적인
숫자 입력을 받는 순수 함수로 작성한다 (spec §9가 "입력 시장 데이터는
fixture로 고정"해서 테스트하도록 요구하기 때문).

가정값(P, 멀티플, TAM, 점유율 등)은 모두 결과를 2~3배 흔들 수 있는
"가정 기반 추정"이다 (spec §10) - 이 모듈이 만드는 값을 리포트에 쓸 때는
그 사실을 함께 표기해야 한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "growth_assumptions.yaml"

# 3.3의 FV_prev 반복은 shortfall(증자 필요분)이 커서 issue_px가 낮아질수록
# 필요 증자주식수가 더 늘어나 FV가 다시 낮아지는 양의 피드백 구조라, 특정
# 입력에서는 고정점이 존재하지 않고 0으로 발산할 수 있다(예: RGTI처럼 누적
# 소진이 순현금을 크게 넘는 3단계 종목). "수렴 시 종료"를 문자 그대로
# "직전 값 대비 변화가 이 허용치를 넘으면 발산으로 보고 그 이전 값을 최종
# 값으로 유지한다"로 해석해 안전장치를 둔다.
_FV_PREV_MAX_ITERS = 2
_FV_PREV_DIVERGENCE_TOL = 0.20


@dataclass
class Segment:
    name: str
    # 1단계 SOTP(§5.1)
    share: Optional[float] = None
    ebitda_margin: Optional[float] = None
    capex_margin: Optional[float] = None  # capex/매출 > 30%일 때 대체 마진
    multiple: Optional[float] = None
    # 2단계 매출멀티플(§5.2)
    R_n: Optional[float] = None
    ev_s: Optional[float] = None
    gm_ratio: Optional[float] = None


@dataclass
class GrowthAssumptions:
    ticker: str
    erp: float
    r_floor: float
    g_cap: float
    decay: float
    sbc_rate: float
    issue_discount: float
    tax: float
    peer_beta: Optional[float] = None
    P: Optional[float] = None
    L: float = 0.0
    n_override: Optional[int] = None
    R_n_override: Optional[float] = None
    net_cash_n: Optional[float] = None
    burn_total: Optional[float] = None
    burn_years: Optional[float] = None
    ma_new_shares: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    tam_T: Optional[float] = None
    market_share: Optional[float] = None
    op_margin: Optional[float] = None
    pe_mature: Optional[float] = None


@lru_cache(maxsize=None)
def _load_config(path: Path) -> dict:
    """가정값 YAML은 실행 중 바뀌지 않아 경로별로 한 번만 읽는다."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ticker_configured(ticker: str, path: Path = _CONFIG_PATH) -> bool:
    """config/growth_assumptions.yaml에 이 티커의 가정값이 있는지.

    §1 라우팅(GRAV 불가 -> Growth FV)에서, 종목별 가정값이 없으면 이 모듈이
    아무것도 계산할 수 없으므로 호출부가 다음 폴백(RSI50 평균가)으로 넘어갈지
    판단하는 데 쓴다.
    """
    return ticker in _load_config(path) and ticker != "defaults"


def load_assumptions(ticker: str, path: Path = _CONFIG_PATH) -> GrowthAssumptions:
    """config/growth_assumptions.yaml에서 defaults + 종목별 값을 합쳐 읽는다."""
    raw = _load_config(path)
    merged = {**raw.get("defaults", {}), **raw.get(ticker, {})}
    segments = [Segment(**seg) for seg in merged.get("segments", [])]
    return GrowthAssumptions(
        ticker=ticker,
        erp=merged["erp"],
        r_floor=merged["r_floor"],
        g_cap=merged["g_cap"],
        decay=merged["decay"],
        sbc_rate=merged["sbc_rate"],
        issue_discount=merged["issue_discount"],
        tax=merged["tax"],
        peer_beta=merged.get("peer_beta"),
        P=merged.get("P"),
        L=merged.get("L", 0.0),
        n_override=merged.get("n_override"),
        R_n_override=merged.get("R_n_override"),
        net_cash_n=merged.get("net_cash_n"),
        burn_total=merged.get("burn_total"),
        burn_years=merged.get("burn_years"),
        ma_new_shares=merged.get("ma_new_shares", 0.0),
        segments=segments,
        tam_T=merged.get("tam_T"),
        market_share=merged.get("market_share"),
        op_margin=merged.get("op_margin"),
        pe_mature=merged.get("pe_mature"),
    )


# ---------------------------------------------------------------------------
# §3.1 할인율 r
# ---------------------------------------------------------------------------

def select_beta(live_beta: Optional[float], listed_over_1y: bool, peer_beta: Optional[float]) -> float:
    """상장 1년 미만이거나 live beta가 없으면 config의 peer_beta를 쓴다."""
    if live_beta is not None and listed_over_1y:
        return live_beta
    if peer_beta is not None:
        return peer_beta
    if live_beta is not None:
        return live_beta
    raise ValueError("beta를 구할 수 없습니다 (live_beta/peer_beta 모두 없음)")


def discount_rate(rf: float, beta: float, erp: float, r_floor: float) -> float:
    return max(rf + beta * erp, r_floor)


# ---------------------------------------------------------------------------
# §3.2 평가 기간 n, 미래 매출 R_n
# ---------------------------------------------------------------------------

@dataclass
class Horizon:
    n: int
    R_n: float


def _growth_path(g0: float, g_cap: float, decay: float, steps: int) -> list[float]:
    g = min(g0, g_cap)
    path = []
    for _ in range(steps):
        path.append(g)
        g *= decay
    return path


def compute_n(g0: float, g_cap: float, decay: float, stage: int) -> int:
    g = min(g0, g_cap)
    t = 1
    while g > 0.15:
        g *= decay
        t += 1
    lo, hi = (8, 10) if stage == 3 else (5, 10)
    return max(lo, min(t, hi))


def project_revenue(r0_revenue: float, g0: float, g_cap: float, decay: float, n: int) -> float:
    revenue = r0_revenue
    for g in _growth_path(g0, g_cap, decay, n):
        revenue *= 1 + g
    return revenue


def compute_horizon(r0_revenue: float, g0: float, stage: int, assumptions: GrowthAssumptions) -> Horizon:
    n = assumptions.n_override if assumptions.n_override is not None else compute_n(
        g0, assumptions.g_cap, assumptions.decay, stage
    )
    if assumptions.R_n_override is not None:
        R_n = assumptions.R_n_override
    else:
        R_n = project_revenue(r0_revenue, g0, assumptions.g_cap, assumptions.decay, n)
    return Horizon(n=n, R_n=R_n)


# ---------------------------------------------------------------------------
# §3.4 누적 현금소진 / NetCash_adj
# ---------------------------------------------------------------------------

def cumulative_burn(fcf_ttm: float, n: int, assumptions: GrowthAssumptions) -> float:
    if assumptions.burn_total is not None:
        return assumptions.burn_total
    if fcf_ttm >= 0:
        return 0.0
    burn_years = assumptions.burn_years if assumptions.burn_years is not None else min(n, 5)
    return abs(fcf_ttm) * burn_years


def net_cash_adjustment(
    net_cash: float, burn: float, stage: int, assumptions: GrowthAssumptions
) -> tuple[float, float]:
    """(NetCash_adj, shortfall). net_cash = 현금 − 부채.

    1단계는 음수를 허용하고(부채 조달), net_cash_n override가 있으면 그 값을
    그대로 쓴다. 2·3단계는 0 하한이고 부족분(shortfall)은 증자로 처리한다.
    """
    if stage == 1:
        if assumptions.net_cash_n is not None:
            return assumptions.net_cash_n, 0.0
        return net_cash - burn, 0.0
    raw = net_cash - burn
    shortfall = max(burn - net_cash, 0.0)
    return max(raw, 0.0), shortfall


# ---------------------------------------------------------------------------
# §3.3 희석주식수 S_D,n / §2 FV 조립 (공통 코어)
# ---------------------------------------------------------------------------

@dataclass
class FairValueResult:
    stage: int
    fv: float
    ev_n: float
    ev_req: float
    r: float
    n: int
    s_d_n: float
    net_cash_adj: float
    required: dict


def _solve_fv_and_shares(
    *,
    ev_n: float,
    P: float,
    L: float,
    r: float,
    n: int,
    net_cash_adj: float,
    shortfall: float,
    current_shares: float,
    sbc_rate: float,
    issue_discount: float,
    ma_new_shares: float,
    current_price: float,
) -> tuple[float, float]:
    s_base = current_shares * (1 + sbc_rate) ** n
    discounted = (ev_n * P + (1 - P) * L) / (1 + r) ** n

    def fv_for(fv_prev: float) -> tuple[float, float]:
        issue_px = min(current_price, fv_prev) * (1 - issue_discount)
        dilution = shortfall / issue_px if shortfall else 0.0
        s_d_n = s_base + dilution + ma_new_shares
        return (discounted + net_cash_adj) / s_d_n, s_d_n

    fv, s_d_n = fv_for(current_price)
    for _ in range(_FV_PREV_MAX_ITERS):
        candidate, candidate_s_d_n = fv_for(fv)
        if fv == 0 or abs(candidate - fv) / abs(fv) > _FV_PREV_DIVERGENCE_TOL:
            break
        fv, s_d_n = candidate, candidate_s_d_n
    return fv, s_d_n


def required_ev(current_price: float, s_d_n: float, net_cash_adj: float, r: float, n: int, P: float, L: float) -> float:
    """§6 역산: 현재가를 정당화하는 데 필요한 EV_n."""
    return ((current_price * s_d_n - net_cash_adj) * (1 + r) ** n - (1 - P) * L) / P


# ---------------------------------------------------------------------------
# §5 단계별 EV_n
# ---------------------------------------------------------------------------

def stage1_ev(segments: list[Segment], R_n_total: float, capex_ratio: float = 0.0) -> float:
    use_capex_margin = capex_ratio > 0.30
    total = 0.0
    for seg in segments:
        r_n_i = R_n_total * seg.share
        margin = seg.ebitda_margin
        if use_capex_margin and seg.capex_margin is not None:
            margin = seg.capex_margin
        total += r_n_i * margin * seg.multiple
    return total


def stage2_ev(segments: list[Segment]) -> float:
    return sum(seg.R_n * seg.ev_s * seg.gm_ratio for seg in segments)


def stage3_ev(tam_T: float, market_share: float, op_margin: float, tax: float, pe_mature: float) -> float:
    return tam_T * market_share * op_margin * (1 - tax) * pe_mature


# ---------------------------------------------------------------------------
# 단계별 종합 계산
# ---------------------------------------------------------------------------

def compute_stage1(
    *,
    assumptions: GrowthAssumptions,
    current_price: float,
    current_shares: float,
    r0_revenue: float,
    g0_growth: float,
    r: float,
    net_cash: float,
    fcf_ttm: float,
    capex_ratio: float = 0.0,
) -> FairValueResult:
    stage = 1
    horizon = compute_horizon(r0_revenue, g0_growth, stage, assumptions)
    n = horizon.n
    burn = cumulative_burn(fcf_ttm, n, assumptions)
    net_cash_adj, shortfall = net_cash_adjustment(net_cash, burn, stage, assumptions)
    P, L = assumptions.P, assumptions.L

    ev_n = stage1_ev(assumptions.segments, horizon.R_n, capex_ratio)
    fv, s_d_n = _solve_fv_and_shares(
        ev_n=ev_n, P=P, L=L, r=r, n=n, net_cash_adj=net_cash_adj, shortfall=shortfall,
        current_shares=current_shares, sbc_rate=assumptions.sbc_rate,
        issue_discount=assumptions.issue_discount, ma_new_shares=assumptions.ma_new_shares,
        current_price=current_price,
    )

    ev_req = required_ev(current_price, s_d_n, net_cash_adj, r, n, P, L)
    # EV_n = R_n x Σ(비중 x 마진 x 멀티플)이라 필요 매출은 EV_req를 이 "매출 1달러당 EV"로
    # 나눈다. 멀티플을 매출 비중으로 가중평균하면(Σ 비중 x 멀티플) 마진이 높은 사업부의
    # 멀티플이 과소 반영돼 필요 매출이 틀어진다(2026-09 TSLA 낙관안 $600B -> $699B로 표시).
    weighted_margin = sum(
        seg.share * (seg.capex_margin if capex_ratio > 0.30 and seg.capex_margin is not None else seg.ebitda_margin)
        for seg in assumptions.segments
    )
    ev_per_revenue = stage1_ev(assumptions.segments, 1.0, capex_ratio)
    revenue_req = ev_req / ev_per_revenue
    ebitda_req = revenue_req * weighted_margin

    return FairValueResult(
        stage=stage, fv=fv, ev_n=ev_n, ev_req=ev_req, r=r, n=n, s_d_n=s_d_n,
        net_cash_adj=net_cash_adj,
        required={"ebitda_req": ebitda_req, "revenue_req": revenue_req},
    )


def compute_stage2(
    *,
    assumptions: GrowthAssumptions,
    current_price: float,
    current_shares: float,
    r0_revenue: float,
    r: float,
    net_cash: float,
    fcf_ttm: float,
    n_years: Optional[int] = None,
) -> FairValueResult:
    stage = 2
    n = assumptions.n_override if assumptions.n_override is not None else n_years
    burn = cumulative_burn(fcf_ttm, n, assumptions)
    net_cash_adj, shortfall = net_cash_adjustment(net_cash, burn, stage, assumptions)
    P, L = assumptions.P, assumptions.L

    ev_n = stage2_ev(assumptions.segments)
    fv, s_d_n = _solve_fv_and_shares(
        ev_n=ev_n, P=P, L=L, r=r, n=n, net_cash_adj=net_cash_adj, shortfall=shortfall,
        current_shares=current_shares, sbc_rate=assumptions.sbc_rate,
        issue_discount=assumptions.issue_discount, ma_new_shares=assumptions.ma_new_shares,
        current_price=current_price,
    )

    ev_req = required_ev(current_price, s_d_n, net_cash_adj, r, n, P, L)
    R_n_total = sum(seg.R_n for seg in assumptions.segments)
    weighted_multiple = sum((seg.R_n / R_n_total) * seg.ev_s * seg.gm_ratio for seg in assumptions.segments)
    revenue_req = ev_req / weighted_multiple
    multiple_of_current = revenue_req / r0_revenue if r0_revenue else None
    cagr_req = (revenue_req / r0_revenue) ** (1 / n) - 1 if r0_revenue and n else None

    return FairValueResult(
        stage=stage, fv=fv, ev_n=ev_n, ev_req=ev_req, r=r, n=n, s_d_n=s_d_n,
        net_cash_adj=net_cash_adj,
        required={
            "revenue_req": revenue_req,
            "multiple_of_current": multiple_of_current,
            "cagr_req": cagr_req,
        },
    )


def compute_stage3(
    *,
    assumptions: GrowthAssumptions,
    current_price: float,
    current_shares: float,
    r: float,
    net_cash: float,
    fcf_ttm: float,
) -> FairValueResult:
    stage = 3
    n = assumptions.n_override if assumptions.n_override is not None else 8
    burn = cumulative_burn(fcf_ttm, n, assumptions)
    net_cash_adj, shortfall = net_cash_adjustment(net_cash, burn, stage, assumptions)
    P, L = assumptions.P, assumptions.L

    ev_n = stage3_ev(
        assumptions.tam_T, assumptions.market_share, assumptions.op_margin, assumptions.tax, assumptions.pe_mature
    )
    fv, s_d_n = _solve_fv_and_shares(
        ev_n=ev_n, P=P, L=L, r=r, n=n, net_cash_adj=net_cash_adj, shortfall=shortfall,
        current_shares=current_shares, sbc_rate=assumptions.sbc_rate,
        issue_discount=assumptions.issue_discount, ma_new_shares=assumptions.ma_new_shares,
        current_price=current_price,
    )

    ev_req = required_ev(current_price, s_d_n, net_cash_adj, r, n, P, L)
    denom = assumptions.tam_T * assumptions.op_margin * (1 - assumptions.tax) * assumptions.pe_mature
    market_share_req = ev_req / denom

    return FairValueResult(
        stage=stage, fv=fv, ev_n=ev_n, ev_req=ev_req, r=r, n=n, s_d_n=s_d_n,
        net_cash_adj=net_cash_adj,
        required={"market_share_req": market_share_req},
    )


# ---------------------------------------------------------------------------
# §4 단계 분류 및 경계 보간
# ---------------------------------------------------------------------------

def classify_stage(
    ttm_ebitda_margin: float,
    ttm_revenue: float,
    quarterly_revenues: list[float],
    ttm_revenue_growth: float,
    gross_margin: float,
) -> int:
    if ttm_ebitda_margin > 0.05:
        return 1
    qualifies_stage2 = (
        ttm_revenue >= 60
        and sum(1 for q in quarterly_revenues if q >= 10) >= 3
        and ttm_revenue_growth > 0
        and gross_margin > 0
    )
    return 2 if qualifies_stage2 else 3


def interpolate_1_2(fv_stage1: float, fv_stage2: float, ebitda_margin: float) -> float:
    """EBITDA 마진 [-5%, +5%] 구간에서 1↔2단계 주당 FV를 선형 보간한다."""
    lo, hi = -0.05, 0.05
    if ebitda_margin <= lo:
        return fv_stage2
    if ebitda_margin >= hi:
        return fv_stage1
    return fv_stage2 * (hi - ebitda_margin) / (hi - lo) + fv_stage1 * (ebitda_margin - lo) / (hi - lo)


def interpolate_2_3(fv_stage2: float, fv_stage3: float, ttm_revenue: float) -> float:
    """TTM 매출 [$40M, $60M] 구간에서 2↔3단계 주당 FV를 선형 보간한다."""
    lo, hi = 40.0, 60.0
    if ttm_revenue <= lo:
        return fv_stage3
    if ttm_revenue >= hi:
        return fv_stage2
    return fv_stage3 * (hi - ttm_revenue) / (hi - lo) + fv_stage2 * (ttm_revenue - lo) / (hi - lo)
