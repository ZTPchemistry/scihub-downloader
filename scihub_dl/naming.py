"""文件命名模板。

模板整串渲染完再交给 :func:`~scihub_dl.sanitize.sanitize_filename` 统一清洗，
所以 ``{doi}`` 里的 ``/`` 会自然变成 ``_``，空字段留下的多余分隔符也会被折叠掉。
"""

from __future__ import annotations

import re

from .models import Paper
from .sanitize import sanitize_filename

__all__ = ["TEMPLATES", "PRESET_LABELS", "render_name", "build_filename"]

#: 命名模式 → 模板串。GUI 的单选按钮和 CLI 的 --naming 共用这份定义。
TEMPLATES: dict[str, str] = {
    "title": "{title}",
    "doi": "{doi}",
    "year": "{year} - {title}",
    "author": "{author} - {year} - {title}",
}

#: 给 GUI 用的中文标签。
PRESET_LABELS: dict[str, str] = {
    "title": "标题",
    "doi": "DOI",
    "year": "年份 - 标题",
    "author": "作者 - 年份 - 标题",
    "custom": "自定义",
}

_FIELDS = ("title", "doi", "year", "author", "journal")

# 字段为空时模板会留下 "  -  - Title" 这样的空档，这里把它们收拾干净。
_DUP_SEP = re.compile(r"(?:\s*[-_]\s*){2,}")
_EDGE_SEP = re.compile(r"^[\s\-_]+|[\s\-_]+$")


def _tidy(s: str) -> str:
    s = _DUP_SEP.sub(" - ", s)
    s = _EDGE_SEP.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def render_name(
    template: str,
    *,
    title: str = "",
    doi: str = "",
    year: str = "",
    author: str = "",
    journal: str = "",
) -> str:
    """渲染模板。未知占位符不会抛异常，原样保留以便用户看出自己写错了。"""
    values = {
        # 没标题时退回 DOI，避免产出一个只剩分隔符的名字。
        "title": title or doi,
        "doi": doi,
        "year": str(year or ""),
        "author": author,
        "journal": journal,
    }
    try:
        out = template.format(**values)
    except (KeyError, IndexError, ValueError):
        # 用户在自定义模板里写了 {foo} 或未配对的花括号——逐字段替换兜底。
        out = template
        for key in _FIELDS:
            out = out.replace("{" + key + "}", values[key])
    return _tidy(out)


def build_filename(
    paper: Paper,
    mode: str,
    custom_template: str = "",
    *,
    max_bytes: int | None = None,
    ext: str = ".pdf",
) -> str:
    """由记录和命名模式算出安全的文件名主干（不含扩展名）。"""
    template = custom_template if mode == "custom" else TEMPLATES.get(mode, "{title}")
    if not template.strip():
        template = "{title}"

    raw = render_name(
        template,
        title=paper.title or "",
        doi=paper.doi,
        year=paper.year,
        author=paper.author,
        journal=paper.journal,
    )
    if max_bytes is None:
        return sanitize_filename(raw)
    return sanitize_filename(raw, max_bytes)
