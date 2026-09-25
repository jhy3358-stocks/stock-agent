"""yfinance 조회 공용 헬퍼 (적정주가·성장주 모듈과 시세 수집이 함께 쓴다)."""
from __future__ import annotations

import logging
from functools import lru_cache

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def yahoo_ticker(symbol: str, market: str) -> str:
    """국내 종목코드는 Yahoo에서 '.KS' 접미사를 붙여 조회한다."""
    return f"{symbol}.KS" if market == "KR" else symbol


@lru_cache(maxsize=None)
def yahoo_info(ticker: str) -> dict:
    """yfinance .info 스냅샷. 실패 시 빈 dict (호출부에서 .get으로 안전하게 처리)."""
    try:
        return yf.Ticker(ticker).info
    except Exception as e:
        logger.warning("Yahoo .info 조회 실패 %s: %s: %s", ticker, type(e).__name__, e)
        return {}


def price_history(ticker: str, **kwargs) -> pd.DataFrame:
    """yfinance 일별 시세. 종가가 없는 행은 버린다.

    yfinance가 가장 최근 거래일을 거래량만 채우고 종가는 NaN인 행으로 돌려주는
    경우가 있어(2026-09-25 AAPL 등 미국 종목 전체), 그대로 쓰면 현재가가 NaN이
    되고 괴리율·적정주가까지 전부 깨진다.
    """
    history = yf.Ticker(ticker).history(**kwargs)
    return history.dropna(subset=["Close"])
