"""Sci-Hub 镜像列表与择优策略。

原来的实现是「重试次数 × 镜像数」全量串行，一篇失败要打 33 次请求。
这里改成：上次成功的域名排最前，本次运行内连续失败的域名降权，
一轮镜像走完即止，速度快得多、也更不容易被屏蔽。
"""

from __future__ import annotations

import threading

__all__ = ["DEFAULT_MIRRORS", "MirrorPool"]

DEFAULT_MIRRORS: list[str] = [
    "https://sci-hub.vg",
    "https://sci-hub.ee",
    "https://sci-hub.ren",
    "https://sci-hub.mk",
    "https://sci-hub.al",
    "https://sci-hub.se",
    "https://sci-hub.ru",
    "https://sci-hub.st",
    "https://sci-hub.shop",
    "https://sci-hub.wf",
    "https://sci-hub.love",
]


class MirrorPool:
    def __init__(self, mirrors: list[str] | None = None, last_good: str | None = None):
        self.mirrors: list[str] = list(mirrors or DEFAULT_MIRRORS)
        self._last_good = last_good
        self._fails: dict[str, int] = {}
        self._lock = threading.Lock()

    def order(self) -> list[str]:
        """返回本轮尝试顺序：上次成功者最前，其后按失败次数升序。"""
        with self._lock:
            def key(m: str) -> tuple[int, int, int]:
                return (0 if m == self._last_good else 1, self._fails.get(m, 0), 0)

            ordered = sorted(self.mirrors, key=key)
        # 保持稳定但把排序结果缓存到 next 调用之间无必要；直接返回。
        return ordered

    def mark_ok(self, mirror: str) -> None:
        with self._lock:
            self._last_good = mirror
            self._fails[mirror] = 0

    def mark_fail(self, mirror: str) -> None:
        with self._lock:
            self._fails[mirror] = self._fails.get(mirror, 0) + 1

    def last_good(self) -> str | None:
        with self._lock:
            return self._last_good

    @property
    def ordered(self) -> list[str]:
        return self.order()
