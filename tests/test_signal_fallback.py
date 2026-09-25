"""signal.fair_value_line의 GRAV -> M-GRAV -> Growth FV(1·2단계) -> RSI50 폴백 순서 테스트."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import src.signal as signal
from src.models import MarketItem
from src.rsi50 import Rsi50Result


def _item() -> MarketItem:
    return MarketItem(
        name="테스트", symbol="TEST", market="US", close=pd.Series([100.0] * 30),
        volume=None, current_price=110.0, change_pct=0.0, unit="$",
    )


def _no_grav(monkeypatch):
    monkeypatch.setattr(signal, "fair_value_inputs", lambda item: None)
    monkeypatch.setattr(signal, "m_grav_fair_value", lambda item: None)


def test_rsi50_used_when_all_models_fail(monkeypatch):
    _no_grav(monkeypatch)
    monkeypatch.setattr(signal, "growth_fair_value", lambda item: None)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(100.0, 5, 98.0, False))
    line = signal.fair_value_line(_item())
    assert "RSI50 평균가" in line
    assert "$100.00" in line
    assert "+10.0%" in line


def test_growth_stage3_falls_back_to_rsi50(monkeypatch):
    _no_grav(monkeypatch)
    stage3 = SimpleNamespace(stage=3, fv=500.0, gap_pct=-78.0, required={})
    monkeypatch.setattr(signal, "growth_fair_value", lambda item: stage3)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(float("nan"), 0, 120.0, True))
    line = signal.fair_value_line(_item())
    assert "Growth FV" not in line
    assert "P50 역산 평균/이력 짧음" in line


def test_growth_stage1_takes_precedence_over_rsi50(monkeypatch):
    _no_grav(monkeypatch)
    stage1 = SimpleNamespace(stage=1, fv=100.0, gap_pct=10.0, required={})
    monkeypatch.setattr(signal, "growth_fair_value", lambda item: stage1)
    monkeypatch.setattr(signal, "required_condition_text", lambda g: "조건")
    monkeypatch.setattr(signal, "item_rsi50", lambda item: (_ for _ in ()).throw(AssertionError("호출되면 안 됨")))
    line = signal.fair_value_line(_item())
    assert "Growth FV" in line
    assert "RSI50" not in line


def test_no_data_message_when_rsi50_also_fails(monkeypatch):
    _no_grav(monkeypatch)
    monkeypatch.setattr(signal, "growth_fair_value", lambda item: None)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(float("nan"), 0, float("nan"), True))
    assert signal.fair_value_line(_item()) == "적정주가 데이터 없음"


# ---------------------------------------------------------------------------
# trading_signal: GRAV·M-GRAV·Growth FV 공통 매수/매도 관점 조건
#   매수: RSI < 30 & 괴리율 <= -10%, 매도: RSI > 70 & 괴리율 >= +10%
# ---------------------------------------------------------------------------

def _set_models(monkeypatch, grav=None, m_grav=None, growth=None, rsi_value=50.0):
    monkeypatch.setattr(
        signal, "fair_value_inputs",
        lambda item: None if grav is None else {"eps": grav, "target_pe": 1.0, "growth_rate": 0.0, "beta": 1.0},
    )
    monkeypatch.setattr(signal, "m_grav_fair_value", lambda item: m_grav)
    monkeypatch.setattr(signal, "growth_fair_value", lambda item: growth)
    monkeypatch.setattr(signal, "rsi", lambda close, period: rsi_value)


def test_buy_when_rsi_below_30_and_each_model_10pct_cheap(monkeypatch):
    # 현재가 110: GRAV 125 -> -12.0%, M-GRAV 200 -> -45.0%
    _set_models(monkeypatch, grav=125.0, m_grav=200.0, rsi_value=25.0)
    assert signal.trading_signal(_item()) == "매수 관점 우세 (RSI 25.0 · GRAV 괴리율 -12.0%, M-GRAV 괴리율 -45.0%)"


def test_buy_lists_only_models_meeting_gap(monkeypatch):
    # GRAV 115 -> -4.3%(미충족), M-GRAV 200 -> -45.0%(충족)
    _set_models(monkeypatch, grav=115.0, m_grav=200.0, rsi_value=25.0)
    assert signal.trading_signal(_item()) == "매수 관점 우세 (RSI 25.0 · M-GRAV 괴리율 -45.0%)"


def test_sell_when_rsi_above_70_and_model_10pct_expensive(monkeypatch):
    # GRAV 100 -> +10.0%(경계 포함)
    _set_models(monkeypatch, grav=100.0, rsi_value=75.0)
    assert signal.trading_signal(_item()) == "매도 관점 우세 (RSI 75.0 · GRAV 괴리율 +10.0%)"


def test_no_signal_when_rsi_neutral(monkeypatch):
    _set_models(monkeypatch, grav=200.0, m_grav=200.0, rsi_value=45.0)
    assert signal.trading_signal(_item()) is None


def test_no_signal_when_gap_within_10pct(monkeypatch):
    _set_models(monkeypatch, grav=105.0, m_grav=115.0, rsi_value=80.0)  # +4.8%, -4.3%
    assert signal.trading_signal(_item()) is None


def test_growth_fv_uses_same_30_70_thresholds(monkeypatch):
    growth = SimpleNamespace(stage=2, fv=80.0, gap_pct=37.5, required={})
    _set_models(monkeypatch, growth=growth, rsi_value=72.0)
    assert signal.trading_signal(_item()) == "매도 관점 우세 (RSI 72.0 · Growth FV 괴리율 +37.5%)"
    _set_models(monkeypatch, growth=growth, rsi_value=60.0)  # 예전 RSI50 기준이면 신호였음
    assert signal.trading_signal(_item()) is None


def test_growth_stage3_not_used_for_signal(monkeypatch):
    # 3단계 Growth FV는 쓰지 않고 RSI50 평균가(100 -> 괴리율 +10.0%)로 판정
    growth = SimpleNamespace(stage=3, fv=80.0, gap_pct=37.5, required={})
    _set_models(monkeypatch, growth=growth, rsi_value=72.0)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(100.0, 5, 98.0, False))
    assert signal.trading_signal(_item()) == "매도 관점 우세 (RSI 72.0 · RSI50 평균가 괴리율 +10.0%)"


def test_rsi50_fair_value_buy_signal(monkeypatch):
    # 기업가치 모델이 모두 없는 종목: RSI50 평균가 125 대비 -12.0% & RSI 25 -> 매수 관점
    _set_models(monkeypatch, rsi_value=25.0)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(125.0, 5, 120.0, False))
    assert signal.trading_signal(_item()) == "매수 관점 우세 (RSI 25.0 · RSI50 평균가 괴리율 -12.0%)"


def test_no_signal_line_when_rsi50_neutral(monkeypatch):
    # 예전 이평선·RSI 점수제("RSI 58.9"만 표시)는 없어졌다: 조건 미충족이면 아무것도 안 띄움
    _set_models(monkeypatch, rsi_value=58.9)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(86.62, 5, 85.0, False))
    assert signal.trading_signal(_item()) is None


# ---------------------------------------------------------------------------
# 적정가 범위 검사 (현재가 대비 0.1~10배, GRAV·M-GRAV·Growth FV 공통)
# ---------------------------------------------------------------------------

def test_out_of_band_grav_dropped_keeps_m_grav(monkeypatch):
    # 현재가 110: GRAV 1,200(10.9배) 제외, M-GRAV 125 유지
    _set_models(monkeypatch, grav=1200.0, m_grav=125.0)
    line = signal.fair_value_line(_item())
    assert "GRAV)" not in line.replace("M-GRAV)", "")
    assert "적정주가(M-GRAV) $125.00" in line


def test_out_of_band_growth_fv_falls_back_to_rsi50(monkeypatch):
    # 현재가 110: Growth FV 5(22배 차이) 제외 -> RSI50 평균가로 폴백
    growth = SimpleNamespace(stage=2, fv=5.0, gap_pct=2100.0, required={})
    _set_models(monkeypatch, growth=growth)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(100.0, 5, 98.0, False))
    line = signal.fair_value_line(_item())
    assert "Growth FV" not in line
    assert "RSI50 평균가" in line


def test_valuation_exception_is_isolated(monkeypatch):
    def boom(item):
        raise KeyError("forwardEps")

    monkeypatch.setattr(signal, "fair_value_inputs", boom)
    monkeypatch.setattr(signal, "item_rsi50", lambda item: Rsi50Result(float("nan"), 0, float("nan"), True))
    assert signal.fair_value_line(_item()) == "적정주가 데이터 없음"
    assert signal.trading_signal(_item()) is None
