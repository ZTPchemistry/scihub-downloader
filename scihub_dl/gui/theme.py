"""GUI 的跨平台外观处理：DPI、中文字体、ttk 样式与状态配色。"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..models import (
    STATUS_BAD_PDF,
    STATUS_CANCELLED,
    STATUS_CAPTCHA,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    STATUS_METADATA,
    STATUS_NETWORK_ERROR,
    STATUS_NOT_FOUND,
    STATUS_NO_PDF,
    STATUS_PENDING,
    STATUS_QUEUED,
    STATUS_SAVED,
    STATUS_SEARCHING,
    STATUS_SKIPPED,
)

__all__ = [
    "enable_high_dpi",
    "pick_font_family",
    "apply_style",
    "STATUS_COLORS",
    "STATUS_LABELS",
]

# 状态 → 前景色（clam 主题下 tag 前景色生效）。
STATUS_COLORS: dict[str, str] = {
    STATUS_PENDING: "#6e7781",
    STATUS_QUEUED: "#57606a",
    STATUS_SAVED: "#1a7f37",
    STATUS_SKIPPED: "#6e7781",
    STATUS_FAILED: "#cf222e",
    STATUS_NOT_FOUND: "#9a6700",
    STATUS_NETWORK_ERROR: "#cf222e",
    STATUS_CAPTCHA: "#bc4c00",
    STATUS_NO_PDF: "#9a6700",
    STATUS_BAD_PDF: "#cf222e",
    STATUS_DOWNLOADING: "#0969da",
    STATUS_SEARCHING: "#0969da",
    STATUS_METADATA: "#8250df",
    STATUS_CANCELLED: "#bc4c00",
}

# 状态 → 界面中文文案。
STATUS_LABELS: dict[str, str] = {
    STATUS_PENDING: "等待确认",
    STATUS_QUEUED: "排队中",
    STATUS_METADATA: "查询标题",
    STATUS_SEARCHING: "搜索中",
    STATUS_DOWNLOADING: "下载中",
    STATUS_SAVED: "已完成",
    STATUS_SKIPPED: "已跳过",
    STATUS_FAILED: "失败",
    STATUS_NOT_FOUND: "未收录",
    STATUS_NETWORK_ERROR: "网络失败",
    STATUS_CAPTCHA: "验证码拦截",
    STATUS_NO_PDF: "无 PDF 链接",
    STATUS_BAD_PDF: "内容异常",
    STATUS_CANCELLED: "已取消",
}

_CJK_CANDIDATES = (
    "Noto Sans CJK SC",
    "WenQuanYi Micro Hei",
    "Source Han Sans CN",
    "Source Han Sans SC",
    "PingFang SC",
    "Microsoft YaHei",
    "Microsoft JhengHei",
    "SimHei",
    "DejaVu Sans",
)


def enable_high_dpi() -> None:
    """必须在创建任何 Tk 对象之前调用，否则 Windows 缩放屏上字会糊。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 逐显示器感知
    except Exception:  # noqa: BLE001 —— 老系统不支持就退回默认
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def pick_font_family(root: tk.Misc, base: int = 10) -> tuple[str, int]:
    """探测一个能显示中文的字体族，找不到就退回 Tk 默认。"""
    available = set(tkfont.families(root))
    for name in _CJK_CANDIDATES:
        if name in available:
            return name, base
    return "TkDefaultFont", base


def apply_style(root: tk.Misc) -> ttk.Style:
    """统一两平台观感，并给每种下载状态配置 tag 颜色。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    family, _ = pick_font_family(root)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try:
            tkfont.nametofont(name).configure(family=family)
        except tk.TclError:
            pass
    style.configure("Treeview", rowheight=24)
    style.configure("Accent.TButton", font=(family, 10, "bold"))
    return style
