"""DART 조회 결과를 저장소 파일에 남겨두고, 조회 실패 시 마지막 성공 값을 쓴다.

GitHub Actions(해외 IP)에서 opendart.fss.or.kr 접속이 재시도까지 모두 시간 초과되는
경우가 있다(2026-09-26). 분기 EPS는 정기보고서가 나올 때(3개월마다)만 바뀌므로 며칠 전
값을 써도 문제가 없다. 워크플로가 리포트 페이지와 함께 이 파일도 커밋한다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "dart_cache.json"
_lock = threading.Lock()


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cached(key: str, stock_code: str, fetch: Callable[[], Optional[Any]], path: Path = CACHE_PATH) -> Optional[Any]:
    """fetch()가 값을 주면 저장하고 돌려주고, 실패(None)하면 마지막으로 저장한 값을 돌려준다."""
    value = fetch()
    with _lock:
        cache = _load(path)
        if value is not None:
            cache.setdefault(stock_code, {})[key] = {"value": value, "saved": dt.date.today().isoformat()}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return value
        entry = cache.get(stock_code, {}).get(key)
    if entry is None:
        return None
    logger.warning("%s %s DART 조회 실패 - %s에 저장한 값 사용", stock_code, key, entry["saved"])
    return tuple(entry["value"]) if isinstance(entry["value"], list) else entry["value"]
