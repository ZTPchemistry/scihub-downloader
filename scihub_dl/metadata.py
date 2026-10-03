"""通过 CrossRef 补全 DOI 的元数据（标题/作者/年份/期刊）。

只在「命名需要标题、而来源文件没给标题」时才会调用；任何失败都静默返回
None，由上层回退到 DOI 命名。查询走校验 SSL 上下文，与 Sci-Hub 分开。
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from pathlib import Path

from .net import HttpSession

__all__ = ["crossref_works", "MetadataCache", "crossref_user_agent"]

CROSSREF_API = "https://api.crossref.org/works/"


def crossref_user_agent(version: str, mailto: str = "", repo: str = "") -> str:
    """CrossRef 礼貌池要求带 mailto 的 UA。

    mailto 为空时退回通用 UA——宁可走公共池，也不预置一个假邮箱
    （假 mailto 对 CrossRef 而言比不填更糟）。
    """
    contact = f"mailto:{mailto}" if mailto else ""
    parts = [p for p in (f"SciHubDownloader/{version}", contact, repo) if p]
    return "; ".join(parts) if parts else "SciHubDownloader"


def crossref_works(
    doi: str,
    *,
    session: HttpSession,
    cache: "MetadataCache | None" = None,
    timeout: float = 10.0,
) -> dict[str, str] | None:
    """返回 {"title","author","year","journal"} 或 None。"""
    if cache is not None:
        hit = cache.get(doi)
        if hit:
            return hit

    url = CROSSREF_API + urllib.parse.quote(doi, safe="")
    try:
        text = session.get(url, strict=True, timeout=timeout)
        message = json.loads(text)["message"]
    except Exception:  # noqa: BLE001 —— 任何失败都回退
        return None

    title = (message.get("title") or [""])[0]
    authors = message.get("author") or []
    author = (authors[0].get("family") or "") if authors else ""
    issued = (message.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None
    journal = (message.get("container-title") or [""])[0]

    meta = {
        "title": title or "",
        "author": author or "",
        "year": str(year) if year is not None else "",
        "journal": journal or "",
    }

    if cache is not None:
        cache.put(doi, meta)
    return meta


class MetadataCache:
    """单 JSON 文件读穿缓存，键为归一化 DOI。"""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception:  # noqa: BLE001 —— 缓存损坏不应阻止程序启动
            self._data = {}

    def get(self, doi: str) -> dict[str, str] | None:
        with self._lock:
            return self._data.get(doi)

    def put(self, doi: str, meta: dict[str, str]) -> None:
        with self._lock:
            self._data[doi] = meta
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            tmp.replace(self.path)
        except Exception:  # noqa: BLE001
            pass
