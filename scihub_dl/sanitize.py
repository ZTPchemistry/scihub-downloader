"""跨平台安全文件名。

要同时满足 Windows 与 Linux 的限制，其中最容易被忽略的是
**长度上限按字节算**：ext4 的 NAME_MAX 是 255 *字节*，
一个中文字符占 3 字节，所以「120 个字符」的朴素截断在中文标题上必然溢出。
"""

from __future__ import annotations

import re
import sys
import threading
import unicodedata

__all__ = [
    "truncate_bytes",
    "sanitize_filename",
    "unique_stem",
    "stem_budget",
    "MAX_STEM_BYTES",
]

# ext4 NAME_MAX = 255 字节，减去 ".pdf" 的 4 字节。
MAX_STEM_BYTES = 251

# Windows 保留设备名，加不加扩展名都不能用。
_WIN_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Windows 非法字符 + 所有 C0 控制字符。
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
# 空格和下划线分开折叠：保留空格能让 "Weeks - 1971 - Title.pdf" 保持可读，
# 全折成下划线会得到难看的 "Weeks_-_1971_-_Title.pdf"。
_COLLAPSE_SPACE = re.compile(r"\s+")
_COLLAPSE_USCORE = re.compile(r"_+")


def truncate_bytes(s: str, max_bytes: int) -> str:
    """按 UTF-8 字节数截断，不产生半个码位。"""
    data = s.encode("utf-8")
    if len(data) <= max_bytes:
        return s
    # errors="ignore" 会丢掉末尾被切断的不完整多字节序列。
    return data[:max_bytes].decode("utf-8", errors="ignore")


def stem_budget(outdir: str, ext: str = ".pdf") -> int:
    """算出在给定输出目录下，文件名主干还能占多少字节。

    Windows 默认 MAX_PATH=260（未开长路径），深目录下 251 字节的主干会让
    完整路径溢出，所以要按目录长度动态收缩。
    """
    budget = MAX_STEM_BYTES - (len(ext.encode("utf-8")) - 4)
    if sys.platform == "win32":
        # 预留分隔符、扩展名和 ".part" 后缀的余量。
        remaining = 250 - len(outdir) - len(ext) - 6
        budget = min(budget, remaining)
    return max(40, budget)


def sanitize_filename(name: str, max_bytes: int = MAX_STEM_BYTES) -> str:
    """把任意字符串转成安全的文件名**主干**（不含扩展名）。"""
    if not name:
        return "untitled"

    # NFKC 会把全角 ＣＯＮ 归一成 CON，否则可绕过下面的保留名检查。
    s = unicodedata.normalize("NFKC", name).strip()
    s = _INVALID.sub("_", s)
    s = _COLLAPSE_SPACE.sub(" ", s)
    s = _COLLAPSE_USCORE.sub("_", s)
    s = s.strip("._ ")

    if not s:
        return "untitled"

    # 保留名判断要去掉扩展名部分：CON.pdf 在 Windows 上同样非法。
    if s.split(".")[0].upper() in _WIN_RESERVED:
        s = "_" + s

    s = truncate_bytes(s, max_bytes)
    # 字节截断后可能又露出尾部的点或空格，Windows 不允许。
    s = s.rstrip("._ ")
    return s or "untitled"


def unique_stem(
    stem: str,
    ext: str,
    used: set[str],
    lock: threading.Lock | None = None,
) -> str:
    """避免同一批次内两条记录清洗出同名文件而互相覆盖。

    ``used`` 存的是 casefold 后的完整文件名——Windows 和 macOS 的文件系统
    大小写不敏感，只比对原样会漏判。引擎从线程池里调用，故需加锁。
    """

    def _claim() -> str:
        key = (stem + ext).casefold()
        if key not in used:
            used.add(key)
            return stem
        i = 2
        while f"{stem} ({i}){ext}".casefold() in used:
            i += 1
        used.add(f"{stem} ({i}){ext}".casefold())
        return f"{stem} ({i})"

    if lock is None:
        return _claim()
    with lock:
        return _claim()
