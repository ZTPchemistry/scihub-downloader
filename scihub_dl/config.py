"""零依赖的跨平台配置持久化。

- Windows: ``%APPDATA%\\SciHubDownloader\\config.json``
- macOS:   ``~/Library/Application Support/SciHubDownloader/config.json``
- Linux:   ``$XDG_CONFIG_HOME/scihub-downloader/config.json``（回退 ``~/.config``）

写入用临时文件 + ``os.replace`` 原子替换，崩溃也不会留下半个 JSON。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

__all__ = ["Config", "config_dir", "load_config", "save_config"]


@dataclass
class Config:
    last_outdir: str = ""
    naming_mode: str = "title"
    custom_template: str = "{year} - {title}"
    mirrors: list[str] = field(default_factory=list)  # 空列表 => 用内置默认镜像
    concurrency: int = 2
    last_good_mirror: str | None = None
    crossref_mailto: str = ""
    window_geometry: str = ""
    lang: str = "zh"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "scihub-downloader"


def _config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> Config:
    cfg = Config()
    try:
        p = _config_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            known = {f: data[f] for f in asdict(cfg) if f in data}
            cfg = Config(**known)
    except Exception:  # noqa: BLE001 —— 配置损坏回退默认值
        cfg = Config()
    # 合法性兜底
    if not 1 <= cfg.concurrency <= 8:
        cfg.concurrency = 2
    if cfg.naming_mode not in ("title", "doi", "year", "author", "custom"):
        cfg.naming_mode = "title"
    if cfg.lang not in ("zh", "en"):
        cfg.lang = "zh"
    return cfg


def save_config(cfg: Config) -> None:
    try:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "config.json.tmp"
        tmp.write_text(
            json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, _config_path())
    except Exception:  # noqa: BLE001 —— 保存失败不该中断程序
        pass
