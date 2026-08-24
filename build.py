#!/usr/bin/env python3
"""用 PyInstaller 打包（Windows / Linux）。

用法：
  python build.py             # 当前平台，默认 GUI 单文件
  python build.py --console   # 带控制台，可运行 CLI 子命令
  python build.py --one-dir   # 目录模式（启动更快，便于调试）

产物：
  Windows → dist/SciHubDownloader.exe
  Linux   → dist/SciHubDownloader（二进制）
            + dist/linux-package/（.desktop + install.sh，桌面菜单集成）
            + dist/SciHubDownloader-<版本>-linux-x86_64.tar.gz

重要：PyInstaller 不支持交叉编译。Windows 版必须在 Windows 上构建，
Linux 版必须在 Linux 上构建（在 Linux 上跑本脚本即可）。

需要先安装 PyInstaller：``pip install pyinstaller``。
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from scihub_dl import __version__

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "scihub_dl" / "assets"
ICON_ICO = ASSETS / "sci-hub.ico"
ICON_PNG = ASSETS / "sci-hub.png"
NAME = "SciHubDownloader"

# Linux 下 PyInstaller 会忽略 --icon（仅 Win/macOS 支持嵌入图标），
# 桌面图标靠 .desktop 的 Icon 字段指向 PNG 实现。
_PLATFORM_ICON = {"win32": ICON_ICO, "linux": ICON_PNG, "darwin": ICON_ICO}


def _current_platform() -> str:
    return sys.platform  # "win32" | "linux" | "darwin"


def _arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64"}.get(m, m)


def _run_pyinstaller(windowed: bool, one_file: bool) -> int:
    sep = ";" if sys.platform == "win32" else ":"
    add_data = f"{ASSETS}{sep}assets"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name",
        NAME,
        "--add-data",
        add_data,
    ]

    # 仅 Windows/macOS 支持把图标嵌入可执行文件。
    icon = _PLATFORM_ICON.get(sys.platform)
    if icon is not None and sys.platform != "linux" and icon.exists():
        cmd += ["--icon", str(icon)]

    if one_file:
        cmd.append("--onefile")
    if windowed:
        cmd.append("--windowed")

    cmd.append(str(ROOT / "main.py"))

    print("[BUILD]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


_DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Sci-Hub Downloader
Name[zh_CN]=Sci-Hub 文献下载器
Comment=Download papers by DOI from Sci-Hub
Comment[zh_CN]=根据 DOI 批量下载文献 PDF
Exec=@BIN@
Icon=sci-hub
Terminal=false
Categories=Education;Science;Network;
StartupNotify=false
"""

_INSTALL_TEMPLATE = """#!/usr/bin/env bash
# Sci-Hub Downloader 安装脚本（仅当前用户，无需 sudo）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
ICON_DIR="${HOME}/.local/share/icons/hicolor/256x256/apps"
APP_DIR="${HOME}/.local/share/applications"

mkdir -p "$BIN_DIR" "$ICON_DIR" "$APP_DIR"

install -m 755 "$HERE/{name}" "$BIN_DIR/{name}"
install -m 644 "$HERE/sci-hub.png" "$ICON_DIR/sci-hub.png"
sed "s|@BIN@|$BIN_DIR/{name}|" "$HERE/{name}.desktop" > "$APP_DIR/{name}.desktop"

update-desktop-database "$APP_DIR" 2>/dev/null || true

echo "安装完成。"
echo "  命令行: $BIN_DIR/{name}"
echo "  应用菜单: Sci-Hub Downloader（如未刷新，注销后重登）"
"""


def _package_linux() -> int:
    """生成 .desktop、install.sh 并打成 tar.gz。"""
    binary = ROOT / "dist" / NAME
    if not binary.exists():
        print("[ERROR] 找不到 dist/SciHubDownloader，请先完成 PyInstaller 构建")
        return 1

    pkg = ROOT / "dist" / "linux-package"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)

    shutil.copy2(binary, pkg / NAME)
    if ICON_PNG.exists():
        shutil.copy2(ICON_PNG, pkg / "sci-hub.png")

    (pkg / f"{NAME}.desktop").write_text(_DESKTOP_TEMPLATE, encoding="utf-8")
    install = pkg / "install.sh"
    install.write_text(_INSTALL_TEMPLATE.format(name=NAME), encoding="utf-8")
    install.chmod(0o755)

    tarball = ROOT / "dist" / f"{NAME}-{__version__}-linux-{_arch()}.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(pkg, arcname="SciHubDownloader")
    print(f"[DONE] Linux 包: {tarball}")
    print(f"[DONE] 解压后进入目录运行 ./install.sh 即可安装到用户目录")
    return 0


def build(windowed: bool, one_file: bool, target: str | None) -> int:
    target = target or _current_platform()

    # PyInstaller 不支持交叉编译：目标平台必须等于当前平台。
    if target != sys.platform:
        print(
            f"[ERROR] 当前在 {sys.platform} 上，无法交叉构建 {target}。\n"
            f"        请到 {target} 机器上运行 `python build.py`。"
        )
        return 1

    rc = _run_pyinstaller(windowed, one_file)
    if rc != 0:
        return rc

    if target == "linux" and one_file:
        rc = _package_linux()

    out = ROOT / "dist"
    print(f"[DONE] 产物在 {out}")
    return rc


def main() -> int:
    # Windows 控制台默认 GBK，避免中文 print 乱码。
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    p = argparse.ArgumentParser(description="Sci-Hub Downloader 打包脚本")
    p.add_argument("--console", action="store_true", help="保留控制台（支持 CLI）")
    p.add_argument("--one-dir", action="store_true", help="目录模式而非单文件")
    p.add_argument(
        "--target",
        choices=("win32", "linux", "darwin"),
        default=None,
        help="目标平台（默认当前平台；不支持交叉编译）",
    )
    args = p.parse_args()

    if shutil.which("pyinstaller") is None and not _has_pyinstaller():
        print("[ERROR] 未安装 PyInstaller，请先: pip install pyinstaller")
        return 1

    return build(windowed=not args.console, one_file=not args.one_dir, target=args.target)


def _has_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401

        return True
    except ImportError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
