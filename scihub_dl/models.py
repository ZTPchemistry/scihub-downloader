"""跨模块共享的数据结构。

单独成模块是为了让 ``parsers`` 与 ``downloader`` 互不依赖——
两边都只依赖这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# 下载状态机。GUI 用它做行着色，CLI 用它选图标。
STATUS_PENDING = "pending"  # 已添加/导入、尚未开始下载（等待确认）
STATUS_QUEUED = "queued"
STATUS_METADATA = "metadata"
STATUS_SEARCHING = "searching"
STATUS_DOWNLOADING = "downloading"
STATUS_SAVED = "saved"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_NOT_FOUND = "not_found"
STATUS_CANCELLED = "cancelled"

# 细分的失败原因（都是失败终态）。
STATUS_NETWORK_ERROR = "network_error"  # 连接超时/DNS/TLS/HTTP 错误
STATUS_CAPTCHA = "captcha"              # 被 Sci-Hub 反爬验证码拦截
STATUS_NO_PDF = "no_pdf"                # 页面正常但解析不出 PDF 链接
STATUS_BAD_PDF = "bad_pdf"              # 下载内容不是有效 PDF

#: 终态——引擎不会在这些状态之后再发同一行的事件。
TERMINAL_STATUSES = frozenset(
    {
        STATUS_SAVED,
        STATUS_SKIPPED,
        STATUS_FAILED,
        STATUS_NOT_FOUND,
        STATUS_CANCELLED,
        STATUS_NETWORK_ERROR,
        STATUS_CAPTCHA,
        STATUS_NO_PDF,
        STATUS_BAD_PDF,
    }
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
    reason: str = ""  # ok | bad_pdf | network_error | error


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


# ── 标题检索 ──────────────────────────────────────────

#: Sci-Hub 收录探测状态。这是检索列表里的**提示**，不是下载结果——
#: 探测只是提前告诉用户「能不能下」，真正的下载仍由引擎独立解析一次。
AVAIL_UNKNOWN = "unknown"      # 未探测 / 探测失败（验证码、网络、无 PDF 链接）
AVAIL_CHECKING = "checking"    # 探测进行中
AVAIL_AVAILABLE = "available"  # 已在镜像上解析出 PDF 链接
AVAIL_NOT_FOUND = "not_found"  # 镜像明确回复「未收录」


@dataclass
class SearchResult:
    """按标题检索到的一条候选文献（由 :mod:`scihub_dl.search` 产出）。

    ``doi`` 已经在解析阶段归一化，可以直接与 :class:`Paper` 去重；
    为空表示该条目没有 DOI（少数书籍章节/预印本），无法进入下载链路。
    """

    doi: str = ""
    title: str = ""
    author: str = ""
    year: str = ""
    journal: str = ""
    url: str = ""
    avail: str = AVAIL_UNKNOWN
    avail_reason: str = ""

    @property
    def selectable(self) -> bool:
        """能否被勾选加入任务列表。

        没有 DOI（下载链路是 DOI 驱动的）或已确认 Sci-Hub 未收录的都不可选；
        「未探测 / 探测失败」仍可选——探测只是提示，不该替用户下结论。
        """
        return bool(self.doi) and self.avail != AVAIL_NOT_FOUND

    @property
    def doi_url(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else ""

    def to_paper(self) -> Paper:
        """转成任务列表里的记录：标题/作者/年份/期刊都已就位，无需再查 CrossRef。"""
        return Paper(
            doi=self.doi,
            title=self.title or None,
            author=self.author,
            year=self.year,
            journal=self.journal,
        )
