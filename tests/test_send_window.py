"""발송 구간(한국 시간 월 06:00 ~ 토 06:00)과 DART 값 캐시."""
from __future__ import annotations

import datetime as dt

from src.dart_cache import cached
from src.main import KST, in_send_window


def _kst(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, day, hour, minute, tzinfo=KST)  # 2026-09-21 월요일


def test_send_window_boundaries():
    assert not in_send_window(_kst(21, 5, 59))   # 월 05:59
    assert in_send_window(_kst(21, 6, 0))        # 월 06:00
    assert in_send_window(_kst(24, 23, 0))       # 목
    assert in_send_window(_kst(26, 5, 59))       # 토 05:59
    assert not in_send_window(_kst(26, 6, 0))    # 토 06:00
    assert not in_send_window(_kst(27, 12, 0))   # 일


def test_send_window_uses_kst_for_utc_time():
    # 일요일 21:30 UTC = 월요일 06:30 KST
    assert in_send_window(dt.datetime(2026, 9, 20, 21, 30, tzinfo=dt.timezone.utc))


def test_dart_cache_falls_back_to_last_saved_value(tmp_path):
    path = tmp_path / "dart_cache.json"
    assert cached("operating_eps", "005930", lambda: (41666.0, "2026년 2분기"), path) == (41666.0, "2026년 2분기")
    assert cached("operating_eps", "005930", lambda: None, path) == (41666.0, "2026년 2분기")
    assert cached("operating_eps", "000660", lambda: None, path) is None
