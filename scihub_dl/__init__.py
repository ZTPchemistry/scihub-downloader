"""Sci-Hub Downloader — 跨平台文献批量下载器。

包内约定：只有 ``cli`` 和 ``gui`` 允许产生用户可见输出，
其余模块一律通过返回值或回调汇报，保持 UI 无关。
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.0.0"
__all__ = ["__version__", "resource_path", "APP_NAME"]

APP_NAME = "SciHubDownloader"


def resource_path(rel: str) -> Path:
    """定位静态资源，兼容三种运行模式。

    - PyInstaller 冻结：``--add-data`` 解压到 ``sys._MEIPASS``，资源在 ``_MEIPASS/assets/``。
    - 源码运行：资源在包内 ``scihub_dl/assets/``。
    - pip 安装：package-data 把 ``scihub_dl/assets/`` 装进 site-packages。

    三种情况都按 ``assets/<rel>`` 相对查找，因此统一放在包内。
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / rel
