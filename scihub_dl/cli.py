"""命令行入口。这里（以及 GUI）是仅有的两处允许 print 的地方。

保留原脚本的 ``--doi/--title/--batch/--markdown/--outdir/--dry-run``，
新增 ``--file/--naming/--template/--concurrency/--plain/--no-metadata``，
以及 ``--lang`` 切换中英文。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import load_config, save_config
from .downloader import BatchEngine
from .i18n import LANGS, get_lang, set_lang, tr
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
        description=tr("cli_description"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            tr("cli_epilog_examples") + "\n"
            "  %(prog)s --doi 10.1063/1.1674820 --title \"WCA Theory\" --outdir ./papers\n"
            "  %(prog)s --file dois.txt --outdir ./papers\n"
            "  %(prog)s --file refs.md --naming author --outdir ./papers\n"
            "  %(prog)s --batch batch.json --dry-run\n"
            "\n"
            + tr("cli_epilog_naming") + ": " + ", ".join(TEMPLATES) + ", custom (--template)"
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--doi", type=str, help=tr("cli_doi"))
    src.add_argument("--batch", type=str, help=tr("cli_batch"))
    src.add_argument("--markdown", type=str, help=tr("cli_markdown"))
    src.add_argument("--file", type=str, help=tr("cli_file"))

    p.add_argument("--title", type=str, default="", help=tr("cli_title"))
    p.add_argument("--outdir", type=str, default="./papers", help=tr("cli_outdir"))
    p.add_argument(
        "--naming",
        type=str,
        default=None,
        choices=list(TEMPLATES) + ["custom"],
        help=tr("cli_naming"),
    )
    p.add_argument("--template", type=str, default="", help=tr("cli_template"))
    p.add_argument("--concurrency", type=int, default=None, help=tr("cli_concurrency"))
    p.add_argument("--plain", action="store_true", help=tr("cli_plain"))
    p.add_argument("--no-metadata", action="store_true", help=tr("cli_no_metadata"))
    p.add_argument("--dry-run", action="store_true", help=tr("cli_dry_run"))
    p.add_argument("--lang", type=str, default=None, choices=list(LANGS), help=tr("cli_lang"))
    return p


def _collect(args) -> list[Paper]:
    if args.doi:
        return [Paper(doi=args.doi, title=args.title or None)]
    path = Path(args.file or args.markdown or args.batch)
    if not path.exists():
        print(f"❌ {tr('cli_file_missing', path=path)}")
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
        summary = tr(
            "cli_summary",
            saved=s.saved,
            skipped=s.skipped,
            not_found=s.not_found,
            failed=s.failed,
            total=s.total,
        )
        print("=" * 60)
        print(f"📊 {summary}")
        if s.cancelled:
            print(f"⏹ {tr('cancelled')}")
        if s.failures:
            for doi, reason in s.failures:
                print(f"  ❌ {doi}: {reason}")
        print("=" * 60)


def _lang_from_argv(argv: list[str] | None) -> str | None:
    args = sys.argv[1:] if argv is None else list(argv)
    for i, a in enumerate(args):
        if a == "--lang" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


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

    cfg = load_config()
    # 先确定语言再构建 parser，这样 --help 文案也能跟随语言。
    lang = _lang_from_argv(argv) or cfg.lang or "zh"
    set_lang(lang)

    args = build_parser().parse_args(argv)

    papers = _collect(args)
    if not papers:
        print(f"❌ {tr('cli_no_doi')}")
        return 1

    naming = args.naming or cfg.naming_mode or "title"
    concurrency = args.concurrency or cfg.concurrency

    if args.dry_run:
        from .naming import build_filename
        from .sanitize import sanitize_filename

        print(f"\n{'=' * 60}")
        print(f"🏷 {tr('cli_preview_header', n=len(papers), naming=naming)}")
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
    print(f"📚 {tr('cli_banner_title')}")
    print(f"   {tr('cli_banner_meta', n=len(papers), outdir=args.outdir, naming=naming)}")
    print(f"{'=' * 60}\n")

    summary = engine.run(papers, on_event=lambda ev: _print_event(ev, cfg))

    # 记住用户偏好
    cfg.last_outdir = args.outdir
    cfg.naming_mode = naming
    cfg.concurrency = concurrency
    cfg.lang = get_lang()
    cfg.last_good_mirror = engine.pool.last_good()
    save_config(cfg)

    return 0 if summary.failed == 0 and not summary.cancelled else 1


if __name__ == "__main__":
    raise SystemExit(main())
