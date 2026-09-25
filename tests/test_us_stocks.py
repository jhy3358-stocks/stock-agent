"""src.us_stocks._fetch 테스트 - yfinance가 종가 NaN 행을 섞어 줄 때."""
from __future__ import annotations

import math

import pandas as pd

import src.us_stocks as us_stocks
import src.yf_data as yf_data


class _FakeTicker:
    def __init__(self, history: pd.DataFrame):
        self._history = history

    def history(self, **kwargs) -> pd.DataFrame:
        return self._history


def test_trailing_nan_close_row_is_dropped(monkeypatch):
    # 2026-09-25 실제 사례: 최근 행이 거래량만 있고 종가는 NaN
    history = pd.DataFrame(
        {"Close": [339.75, 337.02, float("nan")], "Volume": [40_711_800, 31_658_800, 24_364_559]},
        index=pd.to_datetime(["2026-09-22", "2026-09-23", "2026-09-24"]),
    )
    monkeypatch.setattr(yf_data.yf, "Ticker", lambda ticker: _FakeTicker(history))

    item = us_stocks._fetch("AAPL", "애플", "US", "$")

    assert item.current_price == 337.02
    assert not math.isnan(item.change_pct)
    assert len(item.close) == len(item.volume) == 2
