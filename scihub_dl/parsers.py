"""把导入文件解析成 Paper 列表。

支持三种来源：
- ``.txt`` —— 每行一个 DOI 或 DOI 网址（走通用逐行提取）。
- ``.md``  —— 优先用结构化解析（原脚本的中文文献汇总格式，能直接拿到标题），
  解析不出带标题的记录时回退到通用逐行提取。
- ``.json``—— ``[{"doi": "...", "title": "..."}]`` 批量格式。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .doi import extract_from_line
from .models import Paper

__all__ = ["parse_file", "parse_txt", "parse_md", "parse_json", "parse_lines"]


def parse_lines(lines: list[str]) -> list[Paper]:
    """通用逐行提取：把每行里的 DOI 拿出来，不带标题。"""
    papers: list[Paper] = []
    seen: set[str] = set()
    for line in lines:
        for doi in extract_from_line(line):
            if doi not in seen:
                seen.add(doi)
                papers.append(Paper(doi=doi))
    return papers


def parse_txt(path: Path) -> list[Paper]:
    return parse_lines(path.read_text(encoding="utf-8", errors="replace").splitlines())


def parse_json(path: Path) -> list[Paper]:
    raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    # 防御：顶层传了单个对象而非列表。
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    papers: list[Paper] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        doi = str(item.get("doi", "")).strip()
        if not doi:
            continue
        # DOI 统一走规范化，避免脏数据
        from .doi import normalize_doi

        norm = normalize_doi(doi)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        title = str(item.get("title", "") or "").strip() or None
        papers.append(
            Paper(
                doi=norm,
                title=title,
                author=str(item.get("author", "") or "").strip(),
                year=str(item.get("year", "") or "").strip(),
                journal=str(item.get("journal", "") or "").strip(),
            )
        )
    return papers


# ── 结构化 Markdown 解析（保留自原脚本 extract_dois_from_markdown）────────

_DOI_IN_LINE = re.compile(
    r"(?:\*{0,2}DOI\*{0,2}|doi)\s*[：:]\s*\[?(10\.\d{4,}/[^\s\]\)]+)"
)
_TITLE_LINE = re.compile(r"-\s*\*{0,2}标题\*{0,2}[：:]\s*(.+)")


_COMPANION_PREFIX = re.compile(r">\s*\*{0,2}配套论文\*{0,2}[：:]\s*")


def parse_md(path: Path, *, plain: bool = False) -> list[Paper]:
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    if plain:
        return parse_lines(lines)

    papers: list[Paper] = []
    seen: set[str] = set()
    current_title: str | None = None
    companion_pending = False  # 配套论文行的 DOI 可能在下一行

    for line in lines:
        m = _TITLE_LINE.match(line)
        if m:
            t = m.group(1).strip()
            # 去掉结尾的 * 和书名号
            current_title = re.sub(r"[\*《》]+$", "", t).strip()
            companion_pending = False
            continue

        # 配套论文行：标题不在这里猜（作者缩写格式太杂），交给 CrossRef 补全。
        # DOI 可能在本行，也可能在下一行（" > DOI: ..."）。
        if _COMPANION_PREFIX.match(line):
            companion_pending = True
            dm = re.search(r"DOI\s*[：:]\s*\[?(10\.\d{4,}/[^\s\]\)]+)", line)
            if dm:
                from .doi import normalize_doi

                doi = normalize_doi(dm.group(1))
                if doi and doi not in seen:
                    seen.add(doi)
                    papers.append(Paper(doi=doi, title=None))
                companion_pending = False
            current_title = None
            continue

        dm = _DOI_IN_LINE.search(line)
        if dm:
            from .doi import normalize_doi

            doi = normalize_doi(dm.group(1))
            if doi and doi not in seen and (current_title or companion_pending):
                seen.add(doi)
                # 配套论文下一行的 DOI 没有标题，交给 CrossRef 补全。
                papers.append(Paper(doi=doi, title=current_title or None))
            companion_pending = False
            continue

    # 结构化解析没抓到任何带标题的记录 → 回退通用提取。
    if not papers:
        return parse_lines(lines)
    return papers


def parse_file(path: Path, *, plain: bool = False) -> list[Paper]:
    ext = path.suffix.lower()
    if ext == ".json":
        return parse_json(path)
    if ext == ".md" or ext == ".markdown":
        return parse_md(path, plain=plain)
    return parse_txt(path)
