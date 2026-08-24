"""核心下载引擎。

这里的每一行都不碰 UI、不直接 print，只通过 ``on_event`` 回调往外汇报
（``Event`` 类型）。CLI 和 GUI 是它的两个驱动器。

对原 ``scihub_download.py`` 的修复：
- 根相对 PDF 链接改为拼接**实际响应的镜像** origin（原来硬编码 sci-hub.se）。
- PDF 提取不再强制 ``src`` 含 ``.pdf``，补充 ``/downloads/`` 兜底。
- 流式写 ``.part``，首块校验 ``%PDF``，逐块支持取消与进度。
- 重试不再「次数 × 镜像」全量串行，而是一轮镜像走完即止。
"""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from . import __version__
from .metadata import MetadataCache, crossref_user_agent, crossref_works
from .mirrors import DEFAULT_MIRRORS, MirrorPool
from .models import (
    STATUS_BAD_PDF,
    STATUS_CANCELLED,
    STATUS_CAPTCHA,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    STATUS_METADATA,
    STATUS_NETWORK_ERROR,
    STATUS_NOT_FOUND,
    STATUS_NO_PDF,
    STATUS_QUEUED,
    STATUS_SAVED,
    STATUS_SEARCHING,
    STATUS_SKIPPED,
    BatchSummary,
    DownloadResult,
    Event,
    Paper,
    ResolveResult,
)
from .naming import build_filename
from .net import BROWSER_UA, HttpSession, RateLimiter, RequestError
from .sanitize import stem_budget, unique_stem

__all__ = ["extract_pdf_url", "resolve_pdf_url", "download_pdf", "BatchEngine"]

MIN_VALID_BYTES = 10 * 1024  # 大于 10KB 才认为有效
CHUNK = 64 * 1024
PDF_MAGIC = b"%PDF"


# ─── PDF 链接提取 ──────────────────────────────────────

_IFRAME = re.compile(
    r'(?:iframe|embed|object)\s[^>]*?src\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
)
_BUTTON = re.compile(r"""location\.href\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
_DOWNLOADS = re.compile(r'["\']([^"\']*?/downloads/[^"\']+)["\']', re.IGNORECASE)
_ABS_PDF = re.compile(r"https?://[^\"'\s<>]+?\.pdf[^\"'\s<>]*", re.IGNORECASE)


def _absolutize(url: str, base: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base.rstrip("/") + url
    if url.startswith(("http://", "https://")):
        return url
    # 相对路径：相对于镜像站点根
    return base.rstrip("/") + "/" + url.lstrip("/")


def extract_pdf_url(html: str, base: str) -> str | None:
    """从 Sci-Hub 页面找出 PDF 下载链接；``base`` 是响应页面的镜像 origin。"""

    m = _IFRAME.search(html)
    if m:
        return _absolutize(m.group(1), base)

    m = _BUTTON.search(html)
    if m:
        return _absolutize(m.group(1), base)

    # 当前 Sci-Hub 常把 PDF 藏在 /downloads/ 路径下，且未必带 .pdf 后缀。
    m = _DOWNLOADS.search(html)
    if m:
        return _absolutize(m.group(1), base)

    m = _ABS_PDF.search(html)
    if m:
        url = m.group(0)
        if "sci-hub" not in url.lower():
            return url

    return None


# ─── 单篇：解析 + 下载 ──────────────────────────────────


def resolve_pdf_url(
    doi: str,
    *,
    pool: MirrorPool,
    session: HttpSession,
    limiter: RateLimiter,
    cancel_event: threading.Event,
) -> ResolveResult:
    """在镜像里找 PDF 链接。一轮镜像走完即止，失败原因尽量精确。"""
    saw_captcha = False
    saw_network = False
    saw_no_pdf = False

    for mirror in pool.order():
        if cancel_event.is_set():
            return ResolveResult(reason="cancelled")
        limiter.wait(mirror)
        url = f"{mirror}/{doi.strip()}"
        try:
            html = session.get(url)
        except RequestError:
            pool.mark_fail(mirror)
            saw_network = True
            continue
        except Exception:  # noqa: BLE001
            pool.mark_fail(mirror)
            saw_network = True
            continue

        pdf_url = extract_pdf_url(html, mirror)
        if pdf_url:
            pool.mark_ok(mirror)
            return ResolveResult(pdf_url=pdf_url, mirror=mirror, reason="ok")

        low = html.lower()
        # 明确「未收录」是确定性信号，立即返回。
        if "article not found" in low or "не найдена" in low or "not found" in low:
            return ResolveResult(reason="not_found")
        if "captcha" in low:
            pool.mark_fail(mirror)
            saw_captcha = True
            continue
        pool.mark_fail(mirror)
        saw_no_pdf = True

    # 按可操作性排序：验证码 > 网络 > 无 PDF 链接。
    if saw_captcha:
        return ResolveResult(reason="captcha")
    if saw_network:
        return ResolveResult(reason="network_error")
    if saw_no_pdf:
        return ResolveResult(reason="no_pdf")
    return ResolveResult(reason="network_error")


def download_pdf(
    pdf_url: str,
    path: Path,
    *,
    session: HttpSession,
    cancel_event: threading.Event,
    on_progress: Callable[[int, int], None] | None = None,
) -> DownloadResult:
    """流式下载到 ``path``。先写 ``.part``，首块校验后逐块落盘，完成原子改名。"""
    part = path.with_name(path.name + ".part")
    try:
        resp = session.open(pdf_url, timeout=120.0)
        total = int(resp.headers.get("Content-Length") or 0)
        written = 0
        with open(part, "wb") as f:
            while True:
                if cancel_event.is_set():
                    return DownloadResult(cancelled=True)
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                # 首块即校验文件头，避免把 HTML 报错页当成 PDF 存下来。
                if written == 0 and not chunk.startswith(PDF_MAGIC):
                    return DownloadResult(reason="bad_pdf", error="下载内容不是有效 PDF")
                f.write(chunk)
                written += len(chunk)
                if on_progress:
                    on_progress(written, total)
        resp.close()

        os.replace(part, path)
        return DownloadResult(ok=True, path=path, size=written)
    except RequestError as e:
        return DownloadResult(reason="network_error", error=str(e))
    except Exception as e:  # noqa: BLE001
        return DownloadResult(reason="error", error=str(e))
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


# ─── 批处理引擎 ─────────────────────────────────────────


class BatchEngine:
    """UI 无关的批量下载引擎。"""

    def __init__(
        self,
        *,
        outdir: str,
        naming_mode: str = "title",
        custom_template: str = "",
        mirrors: list[str] | None = None,
        concurrency: int = 2,
        session: HttpSession | None = None,
        metadata_cache: MetadataCache | None = None,
        cancel_event: threading.Event | None = None,
        skip_existing: bool = True,
        use_metadata: bool = True,
        mailto: str = "",
    ):
        self.outdir = Path(outdir)
        self.naming_mode = naming_mode
        self.custom_template = custom_template
        self.concurrency = max(1, min(concurrency, 8))
        self.cancel_event = cancel_event or threading.Event()
        self.skip_existing = skip_existing
        self.use_metadata = use_metadata and naming_mode != "doi"

        self.session = session or HttpSession(BROWSER_UA)
        self.pool = MirrorPool(mirrors or DEFAULT_MIRRORS)
        self.limiter = RateLimiter(interval=1.0)
        self.metadata_cache = metadata_cache
        self.crossref_session = HttpSession(
            crossref_user_agent(__version__, mailto=mailto), timeout=30.0
        )

        # 批内文件名去重
        self._used_names: set[str] = set()
        self._name_lock = threading.Lock()

    # —— 内部 ——

    def _needs_metadata(self, paper: Paper) -> bool:
        return self.use_metadata and not paper.has_metadata()

    def _make_filename(self, paper: Paper) -> str:
        budget = stem_budget(str(self.outdir))
        stem = build_filename(
            paper,
            self.naming_mode,
            self.custom_template,
            max_bytes=budget,
        )
        stem = unique_stem(stem, ".pdf", self._used_names, self._name_lock)
        return stem + ".pdf"

    def _process(self, paper: Paper, index: int, emit: Callable[[Event], None]) -> str:
        """处理单篇，返回终态 status。"""

        def row(status: str, message: str = "", filename: str | None = None):
            emit(
                Event(
                    type="row",
                    index=index,
                    doi=paper.doi,
                    status=status,
                    message=message,
                    title=paper.title or "",
                    filename=filename,
                )
            )

        row(STATUS_QUEUED if not self._needs_metadata(paper) else STATUS_METADATA, "准备")

        # 1) 需要时补全元数据
        if self._needs_metadata(paper):
            row(STATUS_METADATA, "查询 CrossRef 标题…")
            try:
                meta = crossref_works(
                    paper.doi,
                    session=self.crossref_session,
                    cache=self.metadata_cache,
                )
            except Exception:  # noqa: BLE001
                meta = None
            if meta and meta.get("title"):
                paper.title = meta["title"]
                paper.author = meta.get("author", "")
                paper.year = meta.get("year", "")
                paper.journal = meta.get("journal", "")

        # 2) 目标文件名
        filename = self._make_filename(paper)
        target = self.outdir / filename

        # 3) 已存在且有效 → 跳过
        if self.skip_existing and target.exists() and target.stat().st_size > MIN_VALID_BYTES:
            row(STATUS_SKIPPED, "已存在，跳过", filename)
            return STATUS_SKIPPED

        # 4) 找 PDF
        row(STATUS_SEARCHING, "搜索 Sci-Hub…")
        resolved = resolve_pdf_url(
            paper.doi,
            pool=self.pool,
            session=self.session,
            limiter=self.limiter,
            cancel_event=self.cancel_event,
        )
        if self.cancel_event.is_set() or resolved.reason == "cancelled":
            row(STATUS_CANCELLED, "已取消", filename)
            return STATUS_CANCELLED
        if resolved.reason == "not_found":
            row(STATUS_NOT_FOUND, "Sci-Hub 未收录", filename)
            return STATUS_NOT_FOUND
        if resolved.reason == "captcha":
            row(STATUS_CAPTCHA, "被验证码拦截", filename)
            return STATUS_CAPTCHA
        if resolved.reason == "network_error":
            row(STATUS_NETWORK_ERROR, "网络连接失败", filename)
            return STATUS_NETWORK_ERROR
        if not resolved.ok:
            row(STATUS_NO_PDF, "未找到 PDF 链接", filename)
            return STATUS_NO_PDF

        # 5) 下载
        row(STATUS_DOWNLOADING, "下载中…", filename)
        self.outdir.mkdir(parents=True, exist_ok=True)
        result = download_pdf(
            resolved.pdf_url,
            target,
            session=self.session,
            cancel_event=self.cancel_event,
        )
        if result.cancelled:
            row(STATUS_CANCELLED, "已取消", filename)
            return STATUS_CANCELLED
        if not result.ok:
            if result.reason == "bad_pdf":
                row(STATUS_BAD_PDF, result.error or "内容不是有效 PDF", filename)
                return STATUS_BAD_PDF
            if result.reason == "network_error":
                row(STATUS_NETWORK_ERROR, result.error or "下载连接失败", filename)
                return STATUS_NETWORK_ERROR
            row(STATUS_FAILED, result.error or "下载失败", filename)
            return STATUS_FAILED

        row(STATUS_SAVED, f"完成 {result.size // 1024} KB", filename)
        return STATUS_SAVED

    # —— 对外 ——

    def run(
        self,
        papers: list[Paper],
        on_event: Callable[[Event], None],
    ) -> BatchSummary:
        self.outdir.mkdir(parents=True, exist_ok=True)
        total = len(papers)
        summary = BatchSummary(total=total)

        # 拷贝一份，避免多线程下修改共享对象
        items = [Paper(doi=p.doi, title=p.title, author=p.author,
                       year=p.year, journal=p.journal) for p in papers]

        if total == 0:
            on_event(Event(type="done", summary=summary))
            return summary

        on_event(Event(type="overall", index=-1, done_bytes=0, total_bytes=total))
        done_count = 0

        def _handle(result: tuple[int, str]) -> None:
            nonlocal done_count
            index, status = result
            done_count += 1
            if status == STATUS_SAVED:
                summary.saved += 1
            elif status == STATUS_SKIPPED:
                summary.skipped += 1
            elif status == STATUS_NOT_FOUND:
                summary.not_found += 1
            elif status == STATUS_CANCELLED:
                summary.cancelled = True
            else:
                summary.failed += 1
            on_event(Event(type="overall", index=-1, done_bytes=done_count,
                           total_bytes=total))

        try:
            with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
                futures = {
                    ex.submit(self._process, item, idx, on_event): idx
                    for idx, item in enumerate(items)
                }
                for fut in as_completed(futures):
                    if self.cancel_event.is_set():
                        # 不再等待剩余任务；shutdown 时 cancel_futures 兜底。
                        break
                    try:
                        status = fut.result()
                    except Exception as e:  # noqa: BLE001
                        status = STATUS_FAILED
                        on_event(
                            Event(
                                type="row",
                                index=futures[fut],
                                doi=items[futures[fut]].doi,
                                status=status,
                                message=str(e),
                            )
                        )
                    _handle((futures[fut], status))
        finally:
            if self.cancel_event.is_set():
                summary.cancelled = True
            on_event(Event(type="done", summary=summary))

        return summary
