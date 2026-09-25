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
