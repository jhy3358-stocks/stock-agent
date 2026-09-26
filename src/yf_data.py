"""yfinance 조회 공용 헬퍼 (적정주가·성장주 모듈과 시세 수집이 함께 쓴다)."""
from __future__ import annotations

import logging
import time
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
    history = _with_cache_lock_retry(lambda: yf.Ticker(ticker).history(**kwargs))
    return history.dropna(subset=["Close"])


# yfinance는 시간대 등 내부 캐시를 로컬 sqlite 파일에 두는데, 여러 종목을 병렬로 조회하면
# 이 파일이 잠겨 "database is locked"로 종목 하나가 통째로 빠질 수 있다(2026-09-26 AVGO).
# 잠금은 잠깐이라 조금 기다렸다 다시 시도한다.
CACHE_LOCK_RETRIES = 3


def _with_cache_lock_retry(fn):
    for attempt in range(CACHE_LOCK_RETRIES):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - sqlite3.OperationalError 등 잠금 오류만 재시도
            if "database is locked" not in str(e) or attempt == CACHE_LOCK_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
