"""적정주가(GRAV·M-GRAV)용 베타 - 최근 2년 주간 수익률 베타에 블룸(Blume) 보정.

    조정 베타 = BLUME_WEIGHT x 주간 베타 + (1 - BLUME_WEIGHT)

Finviz 등의 5년 월간 베타는 상장 기간이 짧은 종목에서 표본이 너무 적어(예: SNDK
19개월, 5.20 +-2.58) 노이즈가 크다. 주간 2년(약 104개)으로 표본을 늘리고, 베타가
장기적으로 1에 수렴하는 성질을 반영하는 블룸 보정으로 극단값을 누그러뜨린다
(공식이 beta로 나누는 구조라 0에 가까운 베타는 적정주가를 폭증시킨다 - 예: COST 0.35).

기준 지수는 미국 종목 S&P500, 국내 종목 코스피(국내 종목을 S&P500과 비교하면 거래
시간 차이로 베타가 왜곡된다). ADR 등 자체 주가 이력이 부실한 종목은
config.BETA_PROXY로 본주 베타를 쓴다.
"""
from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache
from typing import Dict, Optional, Tuple

import pandas as pd
import yfinance as yf

from config import BETA_PROXY
from src.yf_data import yahoo_ticker

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 365 * 2
MIN_WEEKS = 52
BLUME_WEIGHT = 0.67
MARKET_INDEX = {"US": "^GSPC", "KR": "^KS11"}


def blume_adjusted_beta(stock_close: pd.Series, market_close: pd.Series) -> Optional[float]:
    """일별 종가 두 개로 주간(금요일 종가) 수익률 베타를 구해 블룸 보정한다.
    겹치는 주가 MIN_WEEKS 미만이면 None."""
    weekly = pd.concat([stock_close, market_close], axis=1).resample("W-FRI").last()
    returns = weekly.dropna().pct_change().dropna()
    if len(returns) < MIN_WEEKS:
        return None
    stock, market = returns.iloc[:, 0], returns.iloc[:, 1]
    raw = stock.cov(market) / market.var()
    return BLUME_WEIGHT * raw + (1 - BLUME_WEIGHT)


@lru_cache(maxsize=None)
def _closes(tickers: Tuple[str, ...]) -> pd.DataFrame:
    start = dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)
    data = yf.download(list(tickers), start=start.isoformat(), auto_adjust=True, progress=False)
    return data["Close"]


_betas: Dict[Tuple[str, str], Optional[float]] = {}


def prefetch_betas(symbols: list[tuple[str, str]]) -> None:
    """(종목코드, 시장) 목록의 베타를 한 번의 yfinance 일괄 조회로 미리 계산해 둔다."""
    targets = [BETA_PROXY.get(symbol, (symbol, market)) for symbol, market in symbols]
    tickers = {yahoo_ticker(s, m) for s, m in targets} | {MARKET_INDEX[m] for _, m in targets}
    try:
        closes = _closes(tuple(sorted(tickers)))
    except Exception as e:  # noqa: BLE001 - 조회 실패 시 config 베타로 대체된다
        logger.warning("베타 계산용 주가 조회 실패: %s: %s", type(e).__name__, e)
        return
    for symbol, market in targets:
        ticker = yahoo_ticker(symbol, market)
        if ticker in closes and MARKET_INDEX[market] in closes:
            _betas[(symbol, market)] = blume_adjusted_beta(closes[ticker], closes[MARKET_INDEX[market]])


def adjusted_beta(symbol: str, market: str) -> Optional[float]:
    """prefetch_betas로 계산해 둔 조정 베타. 없으면 None (호출부에서 config 베타로 대체)."""
    return _betas.get(BETA_PROXY.get(symbol, (symbol, market)))
