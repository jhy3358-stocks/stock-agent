"""네트워크 조회 병렬 실행과 실패 격리.

종목·소스별 조회 하나가 실패해도(타임아웃, 응답 형식 변경, 차단 등) 전체
리포트 생성·카카오 발송이 멈추지 않도록, 실패한 건은 경고 로그만 남기고
기본값으로 대체한다. 조회 대상끼리 서로 독립적이라 스레드로 병렬 실행한다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Iterable, TypeVar

logger = logging.getLogger(__name__)

K = TypeVar("K")
T = TypeVar("T")

DEFAULT_MAX_WORKERS = 8


def safe_call(what: str, fn: Callable[..., T], *args, default: T, **kwargs) -> T:
    """fn(*args, **kwargs)를 실행하고, 예외가 나면 경고를 남기고 default를 돌려준다."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - 조회 실패는 종류와 무관하게 격리한다
        logger.warning("%s 실패: %s: %s", what, type(e).__name__, e)
        return default


def fetch_all(
    keys: Iterable[K],
    fn: Callable[[K], T],
    *,
    what: str,
    default: T,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> Dict[K, T]:
    """keys 각각에 fn(key)를 병렬로 실행해 {key: 결과}를 입력 순서대로 돌려준다.

    실패한 key는 "{what} {key} 실패" 경고를 남기고 default로 채운다.
    """
    keys = list(keys)
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(keys) or 1))) as pool:
        results = pool.map(lambda k: safe_call(f"{what} {k}", fn, k, default=default), keys)
        return dict(zip(keys, results))
