"""按标题检索论文，并预判 Sci-Hub 是否收录。

与 :mod:`scihub_dl.metadata`（按 DOI 反向补全元数据）不同，这里做的是**检索**：
把用户输入的一串标题（或标题片段、作者+关键词）交给 CrossRef 的
``query.bibliographic`` 接口，拿回一批带 DOI 的候选文献；再用下载链路自身的
解析函数到镜像上探一次，把「能不能下」提前显示在结果列表里。

三条边界（都是为了不影响原有下载流程）：

1. 探测复用 :func:`~scihub_dl.downloader.resolve_pdf_url`，但**自带独立的**
   镜像池与限速器——探测过程中某个镜像的失败计数不该污染真正下载时的镜像优先级。
2. 检索与探测都是只读操作：不写配置、不落盘、不改任何全局状态。
3. 本模块与 UI 无关，只通过返回值、回调与 :class:`SearchError` 汇报
   （与 ``downloader`` 的约定一致）。
"""

from __future__ import annotations

import html
import json
import re
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Sequence

from . import __version__
from .doi import normalize_doi
from .downloader import resolve_pdf_url
from .metadata import crossref_user_agent
from .mirrors import DEFAULT_MIRRORS, MirrorPool
from .models import (
    AVAIL_AVAILABLE,
    AVAIL_CHECKING,
    AVAIL_NOT_FOUND,
    AVAIL_UNKNOWN,
    SearchResult,
)
from .net import BROWSER_UA, HttpSession, RateLimiter, RequestError

__all__ = [
    "CROSSREF_SEARCH_API",
    "DEFAULT_ROWS",
    "DEFAULT_SORT",
    "MAX_ROWS",
    "SORT_PUBLISHED",
    "SORT_RELEVANCE",
    "SORTS",
    "SearchError",
    "SearchService",
    "build_search_url",
    "parse_pick",
    "parse_search_results",
    "probe_availability",
    "search_works",
]

CROSSREF_SEARCH_API = "https://api.crossref.org/works"

#: 一次检索返回的条数。CrossRef 的 rows 上限是 1000，这里收紧到 100：
#: 列表再长也没人看得完，只会拖慢界面。
DEFAULT_ROWS = 20
MAX_ROWS = 100

SORT_RELEVANCE = "relevance"
SORT_PUBLISHED = "published"
SORTS: tuple[str, ...] = (SORT_RELEVANCE, SORT_PUBLISHED)
DEFAULT_SORT = SORT_RELEVANCE

SEARCH_TIMEOUT = 20.0
#: 探测要快：一条镜像卡住不该拖垮整张列表。
PROBE_TIMEOUT = 15.0
PROBE_WORKERS = 3
PROBE_INTERVAL = 1.0

#: 只取展示与下载需要的字段。不加 select 的话，Springer/ACS 这类出版商会把
#: 每条文献的完整参考文献表一起返回，20 条能到 1MB —— 白白慢好几秒。
_SELECT_FIELDS = ",".join(
    (
        "DOI",
        "title",
        "author",
        "issued",
        "published",
        "published-print",
        "published-online",
        "container-title",
        "URL",
    )
)

_JATS_TAG = re.compile(r"<[^>]+>")  # 标题里可能混入 <i>/<sub> 之类的 JATS 标记
_WHITESPACE = re.compile(r"\s+")


class SearchError(Exception):
    """检索失败（网络异常或响应无法解析）。

    与 ``metadata`` 的「静默回退」不同：检索是用户主动发起的，失败必须说清楚。
    """


# ─── URL 拼装 ─────────────────────────────────────────


def _clean_year(value: object) -> str:
    s = str(value or "").strip()
    return s if re.fullmatch(r"\d{4}", s) else ""


def build_search_url(
    query: str,
    *,
    rows: int = DEFAULT_ROWS,
    year_from: object = "",
    year_to: object = "",
    sort: str = SORT_RELEVANCE,
) -> str:
    """拼出 CrossRef 检索 URL（纯函数，便于离线测试）。

    ``query.bibliographic`` 会同时匹配标题、作者与年份，比只匹配标题的
    ``query.title`` 更宽容：用户记不全标题、只输入片段时也能找到。
    无效的年份会被丢弃而不是报错——筛选项是辅助，不该拦住检索。
    """
    params: list[tuple[str, str]] = [
        ("query.bibliographic", query),
        ("rows", str(max(1, min(int(rows or DEFAULT_ROWS), MAX_ROWS)))),
        # relevance 是默认值，显式写出来是为了让 URL 自解释。
        ("sort", SORT_PUBLISHED if sort == SORT_PUBLISHED else SORT_RELEVANCE),
        ("select", _SELECT_FIELDS),
    ]
    if sort == SORT_PUBLISHED:
        params.append(("order", "desc"))

    filters: list[str] = []
    year_from_s = _clean_year(year_from)
    year_to_s = _clean_year(year_to)
    if year_from_s:
        filters.append(f"from-pub-date:{year_from_s}-01-01")
    if year_to_s:
        filters.append(f"until-pub-date:{year_to_s}-12-31")
    if filters:
        params.append(("filter", ",".join(filters)))

    return CROSSREF_SEARCH_API + "?" + urllib.parse.urlencode(params)


# ─── 响应解析 ─────────────────────────────────────────


def _clean_text(value: object) -> str:
    """去掉 JATS 标记、还原实体、折叠空白。"""
    if not isinstance(value, str):
        return ""
    text = html.unescape(_JATS_TAG.sub(" ", value))
    return _WHITESPACE.sub(" ", text).strip()


def _first_text(value: object) -> str:
    """``title`` / ``container-title`` 是数组，取第一个非空字符串。"""
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
        return ""
    return _clean_text(value)


def _first_author(item: dict) -> str:
    """取第一作者。

    CrossRef 的作者项有两种写法：有 ``family`` 的（正常论文），
    以及只有 ``name`` 的整串署名（团体作者/数据集合），因此需要逐个兜底。
    """
    authors = item.get("author")
    if not isinstance(authors, list):
        return ""
    for author in authors:
        if not isinstance(author, dict):
            continue
        for key in ("family", "name", "given"):
            text = _clean_text(author.get(key))
            if text:
                return text
    return ""


def _year_of(item: dict) -> str:
    """年份：issued → published → published-print → published-online → created。"""
    for key in ("issued", "published", "published-print", "published-online", "created"):
        block = item.get(key)
        if not isinstance(block, dict):
            continue
        parts = block.get("date-parts")
        if not isinstance(parts, list) or not parts:
            continue
        first = parts[0]
        if isinstance(first, list) and first and isinstance(first[0], int) and first[0] > 0:
            return str(first[0])
    return ""


def _item_to_result(item: object) -> SearchResult | None:
    """单条 → :class:`SearchResult`；既无标题又无 DOI 的条目直接丢掉。"""
    if not isinstance(item, dict):
        return None

    title = _first_text(item.get("title"))
    raw_doi = _clean_text(item.get("DOI"))
    # 归一化（小写）以便与任务列表里的 DOI 去重；归一化失败就原样保留，
    # 毕竟 CrossRef 才是 DOI 的权威来源。
    doi = (normalize_doi(raw_doi) or raw_doi) if raw_doi else ""
    if not doi and not title:
        return None

    return SearchResult(
        doi=doi,
        title=title,
        author=_first_author(item),
        year=_year_of(item),
        journal=_first_text(item.get("container-title")),
        url=_clean_text(item.get("URL")),
        avail=AVAIL_UNKNOWN,
    )


def parse_search_results(text: str) -> list[SearchResult]:
    """把 CrossRef 响应体解析成结果列表。

    无法解析时抛 :class:`ValueError`，由 :func:`search_works` 统一转成
    :class:`SearchError`；缺字段的单条则尽量补齐，不整批失败。
    """
    try:
        payload = json.loads(text)
    except Exception as e:  # noqa: BLE001 —— 归一化成一种失败
        raise ValueError(f"invalid JSON: {e}") from e

    if not isinstance(payload, dict):
        raise ValueError("unexpected payload type")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ValueError("missing message")
    items = message.get("items")
    if not isinstance(items, list):
        return []

    results: list[SearchResult] = []
    for item in items:
        result = _item_to_result(item)
        if result is not None:
            results.append(result)
    return results


# ─── 检索 / 探测 ──────────────────────────────────────


def search_works(
    query: str,
    *,
    session: HttpSession,
    rows: int = DEFAULT_ROWS,
    year_from: object = "",
    year_to: object = "",
    sort: str = SORT_RELEVANCE,
    timeout: float = SEARCH_TIMEOUT,
) -> list[SearchResult]:
    """按标题检索，返回候选列表（可能为空）。失败抛 :class:`SearchError`。"""
    q = (query or "").strip()
    if not q:
        return []

    url = build_search_url(q, rows=rows, year_from=year_from, year_to=year_to, sort=sort)
    try:
        # strict=True：CrossRef 是正规服务，必须走校验 SSL 上下文。
        text = session.get(url, strict=True, timeout=timeout)
    except RequestError as e:
        raise SearchError(str(e)) from e
    except Exception as e:  # noqa: BLE001 —— 网络层意外异常同样归一化
        raise SearchError(str(e)) from e

    try:
        return parse_search_results(text)
    except ValueError as e:
        raise SearchError(str(e)) from e


def probe_availability(
    doi: str,
    *,
    pool: MirrorPool,
    session: HttpSession,
    limiter: RateLimiter,
    cancel_event: threading.Event,
) -> tuple[str, str]:
    """探测一篇文献在 Sci-Hub 上能不能下，返回 ``(状态, 原因)``。

    刻意复用下载链路的 :func:`~scihub_dl.downloader.resolve_pdf_url` 而不是另写
    一套判断——「探测得到就等于下载得到」，否则列表里的提示会骗人。
    """
    if not doi:
        return AVAIL_UNKNOWN, "no_doi"

    resolved = resolve_pdf_url(
        doi, pool=pool, session=session, limiter=limiter, cancel_event=cancel_event
    )
    if resolved.ok:
        return AVAIL_AVAILABLE, "ok"
    if resolved.reason == "not_found":
        return AVAIL_NOT_FOUND, "not_found"
    # 验证码 / 网络 / 无 PDF 链接都属于「说不准」，不能据此禁用勾选。
    return AVAIL_UNKNOWN, resolved.reason or "unknown"


def parse_pick(text: str, total: int) -> list[int]:
    """解析 ``--pick`` 写法，返回去重后的 1 基序号列表。

    支持 ``1,3``、``1-4``、``1 3 5`` 及混写；非法片段与越界序号一律忽略，
    因此用户多打一个逗号不会让整条命令失败。
    """
    picked: list[int] = []
    for chunk in re.split(r"[,，、\s]+", (text or "").strip()):
        if not chunk:
            continue
        span = re.fullmatch(r"(\d+)\s*[-–~]\s*(\d+)", chunk)
        if span:
            start, end = int(span.group(1)), int(span.group(2))
            if start > end:
                start, end = end, start
            candidates: Sequence[int] = range(start, end + 1)
        elif chunk.isdigit():
            candidates = (int(chunk),)
        else:
            continue
        for n in candidates:
            if 1 <= n <= total and n not in picked:
                picked.append(n)
    return picked


class SearchService:
    """检索 + 收录探测的一体化服务（GUI 与 CLI 共用）。

    刻意与 :class:`~scihub_dl.downloader.BatchEngine` 分开持有镜像池、限速器与
    会话：探测产生的失败计数、限速节拍都不应影响真正的下载流程。
    """

    def __init__(
        self,
        *,
        mailto: str = "",
        session: HttpSession | None = None,
        probe_session: HttpSession | None = None,
        mirrors: list[str] | None = None,
        max_workers: int = PROBE_WORKERS,
        cancel_event: threading.Event | None = None,
    ):
        # 检索走 CrossRef：与 metadata 一样带 mailto 的 UA 进礼貌池。
        self.session = session or HttpSession(
            crossref_user_agent(__version__, mailto=mailto), timeout=30.0
        )
        self.probe_session = probe_session or HttpSession(BROWSER_UA, timeout=PROBE_TIMEOUT)
        self.pool = MirrorPool(mirrors or DEFAULT_MIRRORS)
        self.limiter = RateLimiter(interval=PROBE_INTERVAL)
        self.max_workers = max(1, min(max_workers, 8))
        self.cancel_event = cancel_event or threading.Event()

    def search(
        self,
        query: str,
        *,
        rows: int = DEFAULT_ROWS,
        year_from: object = "",
        year_to: object = "",
        sort: str = SORT_RELEVANCE,
    ) -> list[SearchResult]:
        return search_works(
            query,
            session=self.session,
            rows=rows,
            year_from=year_from,
            year_to=year_to,
            sort=sort,
        )

    def probe(
        self,
        results: Sequence[SearchResult],
        on_update: Callable[[int, SearchResult], None],
    ) -> None:
        """并发探测 ``results`` 里带 DOI 的条目，每完成一条回调一次。

        ``on_update(index, result)`` 的 ``index`` 是 ``results`` 里的下标，
        因此调用方可以按行更新界面；``result.avail`` 已在调用前写好新状态。
        被取消时，未探完的条目会被显式重置为「未知」并回调一次。
        """
        targets = [(i, r) for i, r in enumerate(results) if r.doi]
        if not targets:
            return

        for i, result in targets:
            result.avail = AVAIL_CHECKING
            on_update(i, result)

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {
                ex.submit(
                    probe_availability,
                    result.doi,
                    pool=self.pool,
                    session=self.probe_session,
                    limiter=self.limiter,
                    cancel_event=self.cancel_event,
                ): i
                for i, result in targets
            }
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    break
                index = futures[future]
                result = results[index]
                try:
                    state, reason = future.result()
                except Exception as e:  # noqa: BLE001 —— 单条探测失败不该中断整批
                    state, reason = AVAIL_UNKNOWN, str(e)
                result.avail = state
                result.avail_reason = reason
                on_update(index, result)

        if self.cancel_event.is_set():
            # 提示「检查中…」的行要落到一个确定状态，否则会永远转下去。
            for i, result in targets:
                if result.avail == AVAIL_CHECKING:
                    result.avail = AVAIL_UNKNOWN
                    result.avail_reason = "cancelled"
                    on_update(i, result)
