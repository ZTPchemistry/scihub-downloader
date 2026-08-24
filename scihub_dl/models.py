"""跨模块共享的数据结构。

单独成模块是为了让 ``parsers`` 与 ``downloader`` 互不依赖——
两边都只依赖这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# 下载状态机。GUI 用它做行着色，CLI 用它选图标。
STATUS_QUEUED = "queued"
STATUS_METADATA = "metadata"
STATUS_SEARCHING = "searching"
STATUS_DOWNLOADING = "downloading"
STATUS_SAVED = "saved"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_NOT_FOUND = "not_found"
STATUS_CANCELLED = "cancelled"

#: 终态——引擎不会在这些状态之后再发同一行的事件。
TERMINAL_STATUSES = frozenset(
    {STATUS_SAVED, STATUS_SKIPPED, STATUS_FAILED, STATUS_NOT_FOUND, STATUS_CANCELLED}
)


@dataclass
class Paper:
    """一条待下载记录。

    ``title`` 为 None 表示来源文件没提供标题，需要时再走 CrossRef 补全。
    """

    doi: str
    title: str | None = None
    author: str = ""
    year: str = ""
    journal: str = ""

    def has_metadata(self) -> bool:
        return bool(self.title)


@dataclass
class Event:
    """引擎 → 驱动器（CLI/GUI）的单向汇报。

    引擎绝不直接调用 UI；它只构造 Event 交给 ``on_event`` 回调。
    GUI 侧那个回调就是 ``queue.Queue.put``，因此必须保持本类可安全跨线程传递
    （纯数据、无引用回引擎内部可变状态）。
    """

    type: str  # "row" | "overall" | "log" | "done"
    index: int = -1
    doi: str = ""
    status: str = ""
    message: str = ""
    title: str = ""
    filename: str | None = None
    done_bytes: int = 0
    total_bytes: int = 0
    summary: "BatchSummary | None" = None


@dataclass
class ResolveResult:
    """在 Sci-Hub 上定位 PDF 链接的结果。"""

    pdf_url: str | None = None
    mirror: str | None = None
    reason: str = ""  # ok | not_found | captcha | network_error | cancelled

    @property
    def ok(self) -> bool:
        return self.pdf_url is not None


@dataclass
class DownloadResult:
    ok: bool = False
    path: Path | None = None
    size: int = 0
    cancelled: bool = False
    error: str = ""


@dataclass
class BatchSummary:
    total: int = 0
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    not_found: int = 0
    cancelled: bool = False
    failures: list[tuple[str, str]] = field(default_factory=list)  # (doi, 原因)

    @property
    def done(self) -> int:
        return self.saved + self.skipped + self.failed + self.not_found
