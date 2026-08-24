"""命令行入口。这里（以及 GUI）是仅有的两处允许 print 的地方。

保留原脚本的 ``--doi/--title/--batch/--markdown/--outdir/--dry-run``，
新增 ``--file/--naming/--template/--concurrency/--plain/--no-metadata``。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import load_config, save_config
from .downloader import BatchEngine
from .metadata import MetadataCache
from .models import (
    STATUS_BAD_PDF,
    STATUS_CANCELLED,
    STATUS_CAPTCHA,
    STATUS_FAILED,
    STATUS_NETWORK_ERROR,
    STATUS_NOT_FOUND,
    STATUS_NO_PDF,
    STATUS_SAVED,
    STATUS_SKIPPED,
    Event,
    Paper,
)
from .naming import TEMPLATES
from .parsers import parse_file

_EMOJI = {
    STATUS_SAVED: "✅",
    STATUS_SKIPPED: "⏭",
    STATUS_FAILED: "❌",
    STATUS_NOT_FOUND: "🔍",
    STATUS_NETWORK_ERROR: "🌐",
    STATUS_CAPTCHA: "🛡",
    STATUS_NO_PDF: "📄",
    STATUS_BAD_PDF: "📄",
    STATUS_CANCELLED: "⏹",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scihub-dl",
        description="Sci-Hub 文献下载器 — 根据 DOI 下载论文 PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s --doi 10.1063/1.1674820 --title \"WCA Theory\" --outdir ./papers\n"
            "  %(prog)s --file dois.txt --outdir ./papers\n"
            "  %(prog)s --file 文献汇总.md --naming author --outdir ./papers\n"
            "  %(prog)s --batch batch.json --dry-run\n"
            "\n"
            "命名方式: " + ", ".join(TEMPLATES) + ", custom（配合 --template）"
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--doi", type=str, help="单个 DOI")
    src.add_argument("--batch", type=str, help="JSON 批处理文件路径")
    src.add_argument("--markdown", type=str, help="从 Markdown 文献汇总提取 DOI")
    src.add_argument("--file", type=str, help="txt/md/json 导入文件（自动识别格式）")

    p.add_argument("--title", type=str, default="", help="文献标题（与 --doi 配合）")
    p.add_argument("--outdir", type=str, default="./papers", help="输出目录（默认 ./papers）")
    p.add_argument(
        "--naming",
        type=str,
        default=None,
        choices=list(TEMPLATES) + ["custom"],
        help="命名方式（默认沿用上次或 title）",
    )
    p.add_argument("--template", type=str, default="", help="--naming custom 时使用")
    p.add_argument("--concurrency", type=int, default=None, help="并发数 1-8（默认 2）")
    p.add_argument("--plain", action="store_true", help="md 文件按纯文本逐行解析")
    p.add_argument("--no-metadata", action="store_true", help="不查 CrossRef 补全标题")
    p.add_argument("--dry-run", action="store_true", help="仅预览，不实际下载")
    return p


def _collect(args) -> list[Paper]:
    if args.doi:
        return [Paper(doi=args.doi, title=args.title or None)]
    path = Path(args.file or args.markdown or args.batch)
    if not path.exists():
        print(f"❌ 文件不存在: {path}")
        return []
    return parse_file(path, plain=args.plain)


def _print_event(ev: Event, cfg) -> None:
    if ev.type == "overall":
        return  # 进度由 done 汇总
    if ev.type == "row":
        icon = _EMOJI.get(ev.status, "·")
        title = ev.title[:60] if ev.title else ev.doi
        extra = f"  ({ev.message})" if ev.message else ""
        if ev.filename:
            extra = f"  [{ev.filename}]"
        print(f"  {icon} {title}{extra}")
    elif ev.type == "done":
        s = ev.summary
        print("=" * 60)
        print(f"📊 完成: 成功 {s.saved} | 跳过 {s.skipped} | "
              f"未收录 {s.not_found} | 失败 {s.failed} | 总计 {s.total}")
        if s.cancelled:
            print("⏹ 已取消")
        if s.failures:
            for doi, reason in s.failures:
                print(f"  ❌ {doi}: {reason}")
        print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    # windowed 打包下 stdout 可能是 None，防止 print 抛异常。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    # Windows 控制台默认 GBK，无法编码 emoji/特殊字符。
    for stream in (sys.stdout, sys.stderr):
        try:
            if sys.platform == "win32" and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    args = build_parser().parse_args(argv)
    cfg = load_config()

    papers = _collect(args)
    if not papers:
        print("❌ 未找到任何 DOI")
        return 1

    naming = args.naming or cfg.naming_mode or "title"
    concurrency = args.concurrency or cfg.concurrency

    if args.dry_run:
        from .naming import build_filename
        from .sanitize import sanitize_filename

        print(f"\n{'=' * 60}")
        print(f"🏷 预览（共 {len(papers)} 篇，命名方式: {naming}）")
        print(f"{'=' * 60}")
        for i, p in enumerate(papers, 1):
            stem = build_filename(p, naming, args.template)
            print(f"  {i:>3}. [{p.doi}] -> {sanitize_filename(stem)}.pdf")
        print(f"{'=' * 60}\n")
        return 0

    cache_path = None
    from .config import config_dir

    cache_path = config_dir() / "metadata_cache.json"
    engine = BatchEngine(
        outdir=args.outdir,
        naming_mode=naming,
        custom_template=args.template or cfg.custom_template,
        concurrency=concurrency,
        metadata_cache=MetadataCache(cache_path) if not args.no_metadata else None,
        use_metadata=not args.no_metadata,
        mailto=cfg.crossref_mailto,
    )

    print(f"\n{'=' * 60}")
    print(f"📚 Sci-Hub 文献下载")
    print(f"   总计: {len(papers)} 篇 | 输出: {args.outdir} | 命名: {naming}")
    print(f"{'=' * 60}\n")

    summary = engine.run(papers, on_event=lambda ev: _print_event(ev, cfg))

    # 记住用户偏好
    cfg.last_outdir = args.outdir
    cfg.naming_mode = naming
    cfg.concurrency = concurrency
    cfg.last_good_mirror = engine.pool.last_good()
    save_config(cfg)

    return 0 if summary.failed == 0 and not summary.cancelled else 1


if __name__ == "__main__":
    raise SystemExit(main())
