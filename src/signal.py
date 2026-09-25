"""적정주가(GRAV 모델 + M-GRAV 모델 + 성장주 Growth FV, 최후 폴백으로 RSI50 평균가)
표시와 RSI 결합 매수/매도 참고 신호."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import RSI_PERIOD
from src.concurrency import safe_call
from src.formatting import format_price
from src.growth_data import growth_fair_value, item_rsi50, required_condition_text
from src.indicators import gap_pct, rsi
from src.models import MarketItem
from src.rsi50 import rsi50_fair_value
from src.valuation import fair_value_inputs, is_sane, m_grav_fair_value, target_price

logger = logging.getLogger(__name__)

# 매수/매도 관점 판단 기준 (GRAV·M-GRAV·Growth FV 공통)
#   매수 관점 우세: RSI(14) < RSI_OVERSOLD  이고 적정주가 대비 괴리율 <= -FAIR_VALUE_GAP_THRESHOLD
#   매도 관점 우세: RSI(14) > RSI_OVERBOUGHT 이고 적정주가 대비 괴리율 >= +FAIR_VALUE_GAP_THRESHOLD
FAIR_VALUE_GAP_THRESHOLD = 10.0
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0

# 적정주가 표시·매매 신호에 쓰는 Growth FV 단계. 3단계(매출 미미, TAM·성공확률
# 가정에 거의 전적으로 의존)는 가정 민감도가 너무 커서 RSI50 평균가로 대신한다.
GROWTH_FV_STAGES = (1, 2)


@dataclass
class _Valuation:
    label: str  # 매매 신호에 표시하는 모델명
    value: float
    gap: float  # (현재가-적정주가)/적정주가 * 100
    display_label: str  # 적정주가 줄에 표시하는 라벨
    suffix: str = ""  # 적정주가 줄 뒤에 덧붙이는 설명 (Growth FV 역산 필요조건)


def _valuations(item: MarketItem) -> list[_Valuation]:
    """기업가치 기반 적정주가 목록 (적정주가 줄과 매매 신호가 공유하는 우선순위).

    GRAV·M-GRAV 중 구할 수 있는 값을 모두 쓰고, 둘 다 없을 때만 Growth FV
    (1·2단계)를 쓴다. spec §10에 따라 Growth FV는 "가정 기반 추정"임을 표시하고
    역산 필요조건을 함께 보여준다. 여기까지가 기업가치 모델이고, 하나도 없으면
    _fair_values()가 RSI50 평균가로 넘어간다.

    한 종목의 계산 실패가 리포트 전체를 멈추지 않도록 예외는 격리하고(빈 목록),
    현재가 대비 10배 이상 벗어난 값은 데이터 오염·가정 오류로 보고 버린다.
    """
    return safe_call(f"{item.symbol} 적정주가 계산", _compute_valuations, item, default=[])


# 적정주가 줄·매매 신호를 텍스트/HTML 리포트에서 각각 계산해 같은 종목이 여러 번
# 검사되므로, 범위 이탈 경고는 (종목, 모델)당 한 번만 남긴다.
_warned_out_of_band: set[tuple[str, str]] = set()


def _sane(item: MarketItem, label: str, value: float) -> bool:
    if is_sane(value, item.current_price):
        return True
    if (item.symbol, label) in _warned_out_of_band:
        return False
    _warned_out_of_band.add((item.symbol, label))
    logger.warning(
        "%s %s 적정주가 %.2f가 현재가 %.2f 대비 범위를 벗어나 제외",
        item.symbol, label, value, item.current_price,
    )
    return False


def _compute_valuations(item: MarketItem) -> list[_Valuation]:
    inputs = fair_value_inputs(item)
    result = []
    for label, value in (
        ("GRAV", target_price(**inputs) if inputs else None),
        ("M-GRAV", m_grav_fair_value(item)),
    ):
        if value and _sane(item, label, value):
            result.append(_Valuation(label, value, gap_pct(item.current_price, value), label))
    if result:
        return result

    growth = growth_fair_value(item)
    if growth is not None and growth.stage in GROWTH_FV_STAGES and _sane(item, "Growth FV", growth.fv):
        return [
            _Valuation(
                "Growth FV",
                growth.fv,
                growth.gap_pct,
                "Growth FV, 가정 기반 추정",
                f" · {required_condition_text(growth)}",
            )
        ]
    return []


def _rsi50_valuation(item: MarketItem) -> Optional[_Valuation]:
    """RSI50 평균가 적정주가 - GRAV/M-GRAV/Growth FV(1·2단계) 모두 못 구할 때 쓴다.

    최근 126거래일 동안 RSI(14)가 50을 지나간 가격들의 평균(교차점이 없으면 역산
    P50 평균)으로, 기업가치가 아니라 추세의 중심 가격이라 라벨에 "추세 기준"을
    밝혀 다른 모델과 구분한다.
    """
    result = item_rsi50(item)
    fair = rsi50_fair_value(result)
    if fair is None:
        return None
    value, method = fair
    notes = [method]
    if result.data_insufficient:
        notes.append("이력 짧음")
    return _Valuation(
        "RSI50 평균가",
        value,
        gap_pct(item.current_price, value),
        f"RSI50 평균가, 추세 기준·{'/'.join(notes)}",
    )


def _fair_values(item: MarketItem) -> list[_Valuation]:
    """적정주가 줄과 매매 신호가 함께 쓰는 최종 적정주가 목록.

    GRAV·M-GRAV → Growth FV(1·2단계) → RSI50 평균가 순으로, 앞 단계가 하나도
    없을 때만 다음 단계로 넘어간다.
    """
    valuations = _valuations(item)
    if valuations:
        return valuations
    rsi50 = safe_call(f"{item.symbol} RSI50 평균가 계산", _rsi50_valuation, item, default=None)
    return [rsi50] if rsi50 is not None else []


def fair_value_line(item: MarketItem) -> str:
    """리포트에 표시할 적정주가 요약 한 줄: "적정주가(라벨) .. (괴리율 ..%)"를 나란히."""
    parts = [
        f"적정주가({v.display_label}) {format_price(v.value, item.unit)} (괴리율 {v.gap:+.1f}%){v.suffix}"
        for v in _fair_values(item)
    ]
    return ", ".join(parts) if parts else "적정주가 데이터 없음"


def trading_signal(item: MarketItem) -> Optional[str]:
    """적정주가(GRAV·M-GRAV·Growth FV·RSI50 평균가) 대비 괴리율 + RSI(14)로
    매수/매도 관점을 판단한다.

    - 매수 관점 우세: RSI < 30 이고, 적정주가보다 10% 이상 싼 모델이 하나 이상
    - 매도 관점 우세: RSI > 70 이고, 적정주가보다 10% 이상 비싼 모델이 하나 이상
    - 모델마다 따로 판정해 조건을 충족한 모델과 그 괴리율을 함께 표시한다.
    - 그 외(중립/판단보류)나 적정주가가 없는 종목은 화면에 띄우지 않도록 None.
    """
    valuations = _fair_values(item)
    if not valuations:
        return None

    rsi_value = rsi(item.close, RSI_PERIOD)
    if rsi_value is None:
        return None

    if rsi_value < RSI_OVERSOLD:
        view = "매수 관점 우세"
        hits = [v for v in valuations if v.gap <= -FAIR_VALUE_GAP_THRESHOLD]
    elif rsi_value > RSI_OVERBOUGHT:
        view = "매도 관점 우세"
        hits = [v for v in valuations if v.gap >= FAIR_VALUE_GAP_THRESHOLD]
    else:
        return None

    if not hits:
        return None
    detail = ", ".join(f"{v.label} 괴리율 {v.gap:+.1f}%" for v in hits)
    return f"{view} (RSI {rsi_value:.1f} · {detail})"
