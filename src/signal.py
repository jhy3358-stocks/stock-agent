"""적정주가(GRAV 모델 + M-GRAV 모델 + 성장주 Growth FV) 기반 밸류에이션 표시와
RSI 결합 매수/매도 참고 신호."""
from __future__ import annotations

from typing import Optional

from config import MA_WINDOWS, RSI_PERIOD
from src.growth_data import growth_fair_value, item_rsi50, required_condition_text
from src.indicators import moving_average_diff, rsi
from src.models import MarketItem
from src.rsi50 import rsi50_fair_value
from src.valuation import fair_value_inputs, m_grav_fair_value, target_price

# 매수/매도 관점 판단 기준 (GRAV·M-GRAV·Growth FV 공통)
#   매수 관점 우세: RSI(14) < RSI_OVERSOLD  이고 적정주가 대비 괴리율 <= -FAIR_VALUE_GAP_THRESHOLD
#   매도 관점 우세: RSI(14) > RSI_OVERBOUGHT 이고 적정주가 대비 괴리율 >= +FAIR_VALUE_GAP_THRESHOLD
FAIR_VALUE_GAP_THRESHOLD = 10.0
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0

# 적정주가 표시에 쓰는 Growth FV 단계. 3단계(매출 미미, TAM·성공확률 가정에
# 거의 전적으로 의존)는 가정 민감도가 너무 커서 RSI50 평균가로 대신한다.
GROWTH_FV_STAGES = (1, 2)


def _format_price(value: float, unit: str) -> str:
    if unit == "원":
        return f"{value:,.0f}{unit}"
    if unit == "$":
        return f"{unit}{value:,.2f}"
    return f"{value:,.2f}{unit}"


def fair_value_line(item: MarketItem) -> str:
    """리포트에 표시할 적정주가 요약 한 줄.

    기존 GRAV 모델과 M-GRAV(해자 반영) 모델 값을 "적정주가(라벨) ..
    (괴리율 ..%)" 형태로 나란히 보여준다. 괴리율 = (현재가-적정주가)/적정주가.
    둘 다 못 구하는 종목(SPCX 등 forward EPS 커버리지가 없는 성장주)은
    docs/growth_valuation_spec.md의 Growth FV 모듈(1·2단계)로 대체하고, spec §10에
    따라 "가정 기반 추정"임을 함께 표시하며 역산 필요조건을 괴리율과 나란히 보여준다.
    그마저 안 되면 RSI50 평균가(추세 중심 가격)를 적정주가로 표시한다.
    """
    inputs = fair_value_inputs(item)
    original = target_price(**inputs) if inputs else None
    m_grav = m_grav_fair_value(item)

    parts = []
    for label, value in (("GRAV", original), ("M-GRAV", m_grav)):
        if value is None:
            continue
        gap = (item.current_price - value) / value * 100
        parts.append(f"적정주가({label}) {_format_price(value, item.unit)} (괴리율 {gap:+.1f}%)")

    if not parts:
        growth = growth_fair_value(item)
        if growth is not None and growth.stage in GROWTH_FV_STAGES:
            parts.append(
                f"적정주가(Growth FV, 가정 기반 추정) {_format_price(growth.fv, item.unit)} "
                f"(괴리율 {growth.gap_pct:+.1f}%) · {required_condition_text(growth)}"
            )

    if not parts:
        rsi50_line = _rsi50_fair_value_line(item)
        if rsi50_line is not None:
            parts.append(rsi50_line)

    if not parts:
        return "적정주가 데이터 없음"
    return ", ".join(parts)


def _rsi50_fair_value_line(item: MarketItem) -> Optional[str]:
    """GRAV/M-GRAV/Growth FV(1·2단계) 모두 못 구할 때의 최후 폴백.

    기업가치가 아니라 최근 126거래일 추세의 중심 가격(RSI(14)가 50을 지나간
    가격들의 평균)이라, 라벨에 "추세 기준"임을 밝혀 다른 모델과 구분한다.
    """
    result = item_rsi50(item)
    fair = rsi50_fair_value(result)
    if fair is None:
        return None
    value, method = fair
    gap = (item.current_price - value) / value * 100
    notes = [method]
    if result.data_insufficient:
        notes.append("이력 짧음")
    return (
        f"적정주가(RSI50 평균가, 추세 기준·{'/'.join(notes)}) "
        f"{_format_price(value, item.unit)} (괴리율 {gap:+.1f}%)"
    )


def _model_gaps(item: MarketItem) -> list[tuple[str, float]]:
    """매수/매도 판단에 쓰는 (모델 라벨, 괴리율%) 목록.

    fair_value_line과 같은 우선순위로, GRAV·M-GRAV 중 구할 수 있는 값을 모두
    쓰고 둘 다 없을 때만 Growth FV(1·2단계)를 쓴다. RSI50 평균가는 추세 중심
    가격이지 기업가치 추정이 아니라서 판단에 넣지 않는다(legacy 신호로 폴백).
    """
    inputs = fair_value_inputs(item)
    gaps = []
    for label, value in (
        ("GRAV", target_price(**inputs) if inputs else None),
        ("M-GRAV", m_grav_fair_value(item)),
    ):
        if value:
            gaps.append((label, (item.current_price - value) / value * 100))
    if gaps:
        return gaps

    growth = growth_fair_value(item)
    if growth is not None and growth.stage in GROWTH_FV_STAGES:
        return [("Growth FV", growth.gap_pct)]
    return []


def _legacy_ma_rsi_signal(item: MarketItem) -> Optional[str]:
    """적정주가 데이터가 없는 종목(예: SPCX)에 대한 RSI/이동평균 기반 대체 신호."""
    score = 0

    rsi_value = rsi(item.close, RSI_PERIOD)
    if rsi_value is not None:
        if rsi_value < 30:
            score += 1
        elif rsi_value > 70:
            score -= 1

    for window in MA_WINDOWS:
        result = moving_average_diff(item.close, window)
        if result is None:
            continue
        _, diff_pct = result
        score += 1 if diff_pct >= 0 else -1

    if (score >= 2 or score <= -2) and rsi_value is not None:
        return f"RSI {rsi_value:.1f}"
    return None


def trading_signal(item: MarketItem) -> Optional[str]:
    """적정주가(GRAV·M-GRAV·Growth FV) 대비 괴리율 + RSI(14)로 매수/매도 관점을 판단한다.

    - 매수 관점 우세: RSI < 30 이고, 적정주가보다 10% 이상 싼 모델이 하나 이상
    - 매도 관점 우세: RSI > 70 이고, 적정주가보다 10% 이상 비싼 모델이 하나 이상
    - 모델마다 따로 판정해 조건을 충족한 모델과 그 괴리율을 함께 표시한다.
    - 그 외(중립/판단보류)에는 화면에 굳이 띄우지 않도록 None을 반환한다.

    적정주가 모델을 하나도 못 쓰는 종목은 legacy MA/RSI 신호로 폴백한다.
    """
    gaps = _model_gaps(item)
    if not gaps:
        return _legacy_ma_rsi_signal(item)

    rsi_value = rsi(item.close, RSI_PERIOD)
    if rsi_value is None:
        return None

    if rsi_value < RSI_OVERSOLD:
        view = "매수 관점 우세"
        hits = [(label, gap) for label, gap in gaps if gap <= -FAIR_VALUE_GAP_THRESHOLD]
    elif rsi_value > RSI_OVERBOUGHT:
        view = "매도 관점 우세"
        hits = [(label, gap) for label, gap in gaps if gap >= FAIR_VALUE_GAP_THRESHOLD]
    else:
        return None

    if not hits:
        return None
    detail = ", ".join(f"{label} 괴리율 {gap:+.1f}%" for label, gap in hits)
    return f"{view} (RSI {rsi_value:.1f} · {detail})"
