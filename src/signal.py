"""적정주가(GRAV 모델 + M-GRAV 모델 + 성장주 Growth FV) 기반 밸류에이션 표시와
RSI 결합 매수/매도 참고 신호."""
from __future__ import annotations

from typing import Optional

from config import MA_WINDOWS, RSI_PERIOD
from src.growth_data import growth_fair_value, required_condition_text
from src.indicators import moving_average_diff, rsi
from src.models import MarketItem
from src.valuation import fair_value_inputs, m_grav_fair_value, target_price

# 과매수/과매도 판단에 쓰는 (기존 GRAV 모델) 적정주가 대비 괴리율 임계값(%)
FAIR_VALUE_GAP_THRESHOLD = 30.0


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
    docs/growth_valuation_spec.md의 Growth FV 모듈로 대체하고, spec §10에
    따라 "가정 기반 추정"임을 함께 표시하며 역산 필요조건을 괴리율과 나란히 보여준다.
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
        if growth is not None:
            parts.append(
                f"적정주가(Growth FV, 가정 기반 추정) {_format_price(growth.fv, item.unit)} "
                f"(괴리율 {growth.gap_pct:+.1f}%) · {required_condition_text(growth)}"
            )

    if not parts:
        return "적정주가 데이터 없음"
    return ", ".join(parts)


def _fair_value_gap_pct(item: MarketItem) -> Optional[float]:
    """(기존 GRAV 모델) 현재가가 적정주가 대비 몇 % 위/아래에 있는지."""
    inputs = fair_value_inputs(item)
    if inputs is None:
        return None
    tp = target_price(**inputs)
    return (item.current_price - tp) / tp * 100


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


def _growth_fv_signal(item: MarketItem) -> Optional[str]:
    """Growth FV 역산 괴리 + RSI50(중심선 50 기준) 조합 참고 신호.

    GRAV의 RSI(14) 70/30 과매수/과매도 임계값과 달리, Growth FV 대상 성장주는
    RSI(14)가 추세 중심선인 50을 기준으로 방향을 봐야 자연스러워(spec §7의
    RSI50 관점과 동일선상) 여기서는 50을 임계값으로 쓴다. spec §10에 따라
    FV 자체는 가정값에 크게 흔들리는 추정치라 확정 매수/매도 신호가 아니라
    참고 신호로만 노출한다.
    """
    growth = growth_fair_value(item)
    if growth is None:
        return None

    rsi_value = rsi(item.close, RSI_PERIOD)
    if rsi_value is None:
        return None

    rsi50 = growth.rsi50
    ref_price = rsi50.avg_cross if rsi50.avg_cross == rsi50.avg_cross else rsi50.avg_p50
    ref_note = ""
    if ref_price == ref_price:  # NaN이 아니면
        ref_gap = (item.current_price - ref_price) / ref_price * 100
        ref_note = f", RSI50 평균가 대비 {ref_gap:+.1f}%"

    if growth.gap_pct >= FAIR_VALUE_GAP_THRESHOLD and rsi_value > 50:
        return f"RSI {rsi_value:.1f}{ref_note}"
    if growth.gap_pct <= -FAIR_VALUE_GAP_THRESHOLD and rsi_value < 50:
        return f"RSI {rsi_value:.1f}{ref_note}"
    return None


def trading_signal(item: MarketItem) -> Optional[str]:
    """(기존 GRAV 모델) 적정주가 대비 괴리율 + RSI 조합으로 매수/매도 관점을 판단한다.

    - 과매수(매도 관점 우세): 현재가가 적정주가보다 30%p 이상 높고 RSI > 70
    - 과매도(매수 관점 우세): 현재가가 적정주가보다 30%p 이상 낮고 RSI < 30
    - 그 외(중립/판단보류)에는 화면에 굳이 띄우지 않도록 None을 반환한다.

    GRAV를 못 쓰는 종목은 Growth FV + RSI50 참고 신호(_growth_fv_signal)로,
    그마저 안 되면(성장주 가정값도 없는 종목) legacy MA/RSI 신호로 폴백한다.
    """
    if fair_value_inputs(item) is None:
        growth_signal = _growth_fv_signal(item)
        if growth_signal is not None:
            return growth_signal
        return _legacy_ma_rsi_signal(item)

    gap_pct = _fair_value_gap_pct(item)
    rsi_value = rsi(item.close, RSI_PERIOD)
    if gap_pct is None or rsi_value is None:
        return None

    if gap_pct >= FAIR_VALUE_GAP_THRESHOLD and rsi_value > 70:
        return f"RSI {rsi_value:.1f}"
    if gap_pct <= -FAIR_VALUE_GAP_THRESHOLD and rsi_value < 30:
        return f"RSI {rsi_value:.1f}"
    return None
