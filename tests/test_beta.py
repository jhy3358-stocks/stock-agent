"""조정 베타 - 주간 수익률 베타에 블룸 보정."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.beta import BLUME_WEIGHT, blume_adjusted_beta


def _series(returns, start="2024-01-01"):
    index = pd.bdate_range(start, periods=len(returns))
    return pd.Series(100 * np.cumprod(1 + np.asarray(returns)), index=index)


def test_blume_adjustment_pulls_toward_one():
    rng = np.random.default_rng(0)
    market = rng.normal(0, 0.01, 600)
    stock = 2.0 * market  # 원래 베타 2
    beta = blume_adjusted_beta(_series(stock), _series(market))
    assert abs(beta - (BLUME_WEIGHT * 2.0 + (1 - BLUME_WEIGHT))) < 0.01  # 1.67


def test_too_few_weeks_returns_none():
    market = np.full(100, 0.001)
    assert blume_adjusted_beta(_series(market), _series(market)) is None  # 약 20주


def test_valuation_beta_has_floor(monkeypatch):
    import pandas as pd

    import src.valuation as valuation
    from src.models import MarketItem

    item = MarketItem(name="코스트코", symbol="COST", market="US", close=pd.Series([1.0]),
                      volume=None, current_price=900.0, change_pct=0.0, unit="$")
    monkeypatch.setattr(valuation, "adjusted_beta", lambda symbol, market: 0.57)
    assert valuation._beta(item) == valuation.BETA_FLOOR
    monkeypatch.setattr(valuation, "adjusted_beta", lambda symbol, market: 1.3)
    assert valuation._beta(item) == 1.3
