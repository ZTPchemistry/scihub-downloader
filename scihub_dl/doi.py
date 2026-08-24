"""DOI 识别与规范化。

采用两级策略，原因见 ``extract_from_line``：单一正则无法同时兼顾
「DOI 里合法出现的 ``<>``」和「HTML/Markdown 里的 ``<>`` 是边界」这两件矛盾的事。
"""

from __future__ import annotations

import re

__all__ = ["normalize_doi", "extract_from_line", "extract_dois", "looks_like_doi"]

_URL_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_PREFIX = re.compile(r"^doi\s*[:：]\s*", re.IGNORECASE)

# 整行判定：允许除空白外的一切字符，因此 Wiley 的 SICI DOI
# （形如 10.1002/(SICI)1097-0258(19970815)16:15<1705::AID-SIM609>3.0.CO;2-Y）
# 能完整保留。
_FULL_DOI = re.compile(r"^10\.\d{4,9}/\S+$")

# 行内扫描：必须排除 " < > 以免吞掉 HTML 属性，
# 排除 [ ] 以免把 Markdown 链接 [10.x](https://doi.org/10.x) 整体吞成一个畸形 DOI。
_SCAN_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>\[\]]+", re.IGNORECASE)

# 结尾若是这些字符，一律视为句读而非 DOI 的一部分。
_TRAILING_PUNCT = ".,;:!?'\"、，。；：）】"

# 成对符号：只有在「右侧多于左侧」时才剥离，
# 否则会毁掉 10.1016/S0022-2836(05)80360-2 这类合法带括号的 DOI。
_PAIRS = {")": "(", "]": "[", "}": "{", "＞": "＜"}


def _strip_trailing(s: str) -> str:
    """剥掉尾部句读，但保留 DOI 自身配平的括号。"""
    while s:
        c = s[-1]
        if c in _TRAILING_PUNCT:
            s = s[:-1]
            continue
        opener = _PAIRS.get(c)
        if opener is not None and s.count(c) > s.count(opener):
            s = s[:-1]
            continue
        break
    return s


def normalize_doi(raw: str) -> str | None:
    """把任意写法的 DOI 归一化为裸 DOI；不是 DOI 则返回 None。

    可识别：``10.x/y``、``https://doi.org/10.x/y``、``http://dx.doi.org/10.x/y``、
    ``doi:10.x/y``、``DOI：10.x/y``（含中文冒号）。
    """
    if not raw:
        return None
    s = raw.strip().strip("<>")  # 邮件/Markdown 里常见的 <url> 包裹
    s = _DOI_PREFIX.sub("", s).strip()
    s = _URL_PREFIX.sub("", s).strip()
    s = _DOI_PREFIX.sub("", s).strip()  # 形如 "doi: https://doi.org/10.x" 的双重前缀
    s = _strip_trailing(s)
    if not _FULL_DOI.match(s):
        return None
    # DOI 大小写不敏感，统一小写以便去重。
    return s.lower()


def looks_like_doi(raw: str) -> bool:
    return normalize_doi(raw) is not None


def extract_from_line(line: str) -> list[str]:
    """从单行中提取 DOI。

    先尝试把整行当作一个 DOI——这条路径不排除 ``<>``，
    所以 SICI 型 DOI 不会被截断。整行不成立时才退回行内扫描。
    """
    whole = normalize_doi(line)
    if whole:
        return [whole]

    found: list[str] = []
    for m in _SCAN_DOI.finditer(line):
        doi = normalize_doi(m.group(0))
        if doi and doi not in found:
            found.append(doi)
    return found


def extract_dois(text: str) -> list[str]:
    """从多行文本中按出现顺序提取去重后的 DOI 列表。"""
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        for doi in extract_from_line(line):
            if doi not in seen:
                seen.add(doi)
                out.append(doi)
    return out
