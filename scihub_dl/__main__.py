"""支持 ``python -m scihub_dl`` 的入口。"""

from __future__ import annotations

import sys

from . import cli, gui


def main() -> int:
    if len(sys.argv) > 1:
        return cli.main()
    gui.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
