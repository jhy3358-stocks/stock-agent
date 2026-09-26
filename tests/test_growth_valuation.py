"""docs/growth_valuation_spec.md §9 테스트 케이스.

입력 시장 데이터는 모두 fixture(고정값)이고, config/growth_assumptions.yaml의
SPCX/IONQ/RGTI 항목을 그대로 읽어서 쓴다 (n_override/R_n_override 등 override
포함). 실제 yfinance 조회는 하지 않는다.
"""
from __future__ import annotations

from src.growth_valuation import (
    classify_stage,
    compute_stage1,
    compute_stage2,
    compute_stage3,
    interpolate_1_2,
    interpolate_2_3,
    load_assumptions,
    required_ev,
)


def test_spcx_stage1_fv_in_range():
    assumptions = load_assumptions("SPCX")
    result = compute_stage1(
        assumptions=assumptions,
        current_price=149.0,
        current_shares=13_500.0,
        r0_revenue=13_000.0,  # n_override/R_n_override가 있어 실제로는 안 쓰임
        g0_growth=0.35,
        r=0.11,
        net_cash=-3_300.0,  # net_cash_n override가 우선하므로 실제로는 안 쓰임
        fcf_ttm=-1_000.0,
    )
    assert result.stage == 1
    assert 22.0 <= result.fv <= 28.0


def test_ionq_stage2_fv_in_range():
    assumptions = load_assumptions("IONQ")
    result = compute_stage2(
        assumptions=assumptions,
        current_price=37.5,
        current_shares=400.0,
        r0_revenue=63.0,
        r=0.14,
        net_cash=2_000.0,
        fcf_ttm=-300.0,  # burn_total override가 우선하므로 실제로는 안 쓰임
    )
    assert result.stage == 2
    assert 7.0 <= result.fv <= 9.0


def test_rgti_stage3_fv_in_range():
    assumptions = load_assumptions("RGTI")
    result = compute_stage3(
        assumptions=assumptions,
        current_price=16.0,
        current_shares=312.0,
        r=0.145,
        net_cash=541.0,
        fcf_ttm=-140.0,  # burn_total override가 우선하므로 실제로는 안 쓰임
    )
    assert result.stage == 3
    assert 1.0 <= result.fv <= 1.4


def test_stage_classification_spcx_is_stage1():
    # TTM EBITDA 마진 > +5%
    assert classify_stage(
        ttm_ebitda_margin=0.20,
        ttm_revenue=13_000.0,
        quarterly_revenues=[3_000.0, 3_200.0, 3_300.0, 3_500.0],
        ttm_revenue_growth=0.35,
        gross_margin=0.45,
    ) == 1


def test_stage_classification_ionq_is_stage2():
    # TTM 매출 약 $247M, 4개 분기 모두 $10M 이상, 성장/매출총이익률 양수
    assert classify_stage(
        ttm_ebitda_margin=-0.5,
        ttm_revenue=247.0,
        quarterly_revenues=[55.0, 60.0, 65.0, 67.0],
        ttm_revenue_growth=0.90,
        gross_margin=0.40,
    ) == 2


def test_stage_classification_rgti_is_stage3():
    # TTM 매출 약 $10M - 2단계 매출 조건($60M) 미달
    assert classify_stage(
        ttm_ebitda_margin=-3.0,
        ttm_revenue=10.0,
        quarterly_revenues=[2.0, 2.5, 2.5, 3.0],
        ttm_revenue_growth=0.50,
        gross_margin=0.30,
    ) == 3


def test_stage_classification_subcondition_failure_forces_stage3():
    # TTM 매출 $80M(2단계 매출 조건은 충족)이지만 분기 1개만 $10M 이상
    # -> 매출 규모와 무관하게 3단계
    assert classify_stage(
        ttm_ebitda_margin=-0.2,
        ttm_revenue=80.0,
        quarterly_revenues=[15.0, 5.0, 5.0, 5.0],
        ttm_revenue_growth=0.30,
        gross_margin=0.20,
    ) == 3


def test_interpolation_1_2_boundary_continuity():
    fv1, fv2 = 25.0, 8.0
    assert interpolate_1_2(fv1, fv2, 0.05) == fv1
    assert interpolate_1_2(fv1, fv2, -0.05) == fv2
    # 경계에 다가갈수록 순수 단계값에 근접해야 한다 (끊기지 않음)
    just_inside_hi = interpolate_1_2(fv1, fv2, 0.0499)
    just_inside_lo = interpolate_1_2(fv1, fv2, -0.0499)
    assert abs(just_inside_hi - fv1) < 0.02
    assert abs(just_inside_lo - fv2) < 0.02


def test_interpolation_2_3_boundary_continuity():
    fv2, fv3 = 8.0, 1.2
    assert interpolate_2_3(fv2, fv3, 60.0) == fv2
    assert interpolate_2_3(fv2, fv3, 40.0) == fv3
    just_inside_hi = interpolate_2_3(fv2, fv3, 59.99)
    just_inside_lo = interpolate_2_3(fv2, fv3, 40.01)
    assert abs(just_inside_hi - fv2) < 0.01
    assert abs(just_inside_lo - fv3) < 0.01


def test_reverse_ev_is_consistent_with_forward_fv():
    """EV_req를 다시 FV 공식에 넣으면 현재가로 복원돼야 한다 (오차 1% 이내)."""
    assumptions = load_assumptions("IONQ")
    current_price = 37.5
    result = compute_stage2(
        assumptions=assumptions,
        current_price=current_price,
        current_shares=400.0,
        r0_revenue=63.0,
        r=0.14,
        net_cash=2_000.0,
        fcf_ttm=-300.0,
    )

    ev_req = required_ev(
        current_price, result.s_d_n, result.net_cash_adj, result.r, result.n, assumptions.P, assumptions.L
    )
    assert ev_req == result.ev_req

    discounted = (ev_req * assumptions.P + (1 - assumptions.P) * assumptions.L) / (1 + result.r) ** result.n
    fv_roundtrip = (discounted + result.net_cash_adj) / result.s_d_n
    assert abs(fv_roundtrip - current_price) / current_price < 0.01


def test_stage1_required_revenue_matches_fair_value_at_that_revenue():
    """필요 매출로 다시 계산하면 FV가 현재가와 같아져야 한다 (사업부 마진·멀티플이 다른 경우)."""
    from src.growth_valuation import GrowthAssumptions, Segment, compute_stage1

    def assumptions(R_n):
        return GrowthAssumptions(
            ticker="T", erp=0.05, r_floor=0.12, g_cap=1.0, decay=0.75, sbc_rate=0.0,
            issue_discount=0.2, tax=0.21, P=0.9, n_override=5, R_n_override=R_n,
            segments=[Segment(name="a", share=0.7, ebitda_margin=0.1, multiple=10),
                      Segment(name="b", share=0.3, ebitda_margin=0.5, multiple=25)],
        )

    common = dict(current_price=100.0, current_shares=100.0, r0_revenue=1000.0, g0_growth=0.2,
                  r=0.12, net_cash=0.0, fcf_ttm=10.0)
    first = compute_stage1(assumptions=assumptions(5000.0), **common)
    again = compute_stage1(assumptions=assumptions(first.required["revenue_req"]), **common)
    assert abs(again.fv - 100.0) < 0.01
