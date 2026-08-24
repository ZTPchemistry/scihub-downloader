#!/usr/bin/env python3
"""Sci-Hub Downloader 入口。

不带任何参数 → 启动 GUI；带参数 → 走命令行。
"""

from __future__ import annotations

import sys

from scihub_dl import cli, gui


def main() -> int:
    if len(sys.argv) > 1:
        return cli.main()
    gui.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
