"""主窗口。

线程模型：Tk 主线程 + 一个 worker 线程 + 一个 ``queue.Queue``。
worker 只做 ``queue.put``，绝不触碰任何 Tk 对象；消费队列的 ``_pump``
由 ``after()`` 调度，因此 ``_handle`` 天然运行在主线程。这是结构性保证。
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__, resource_path
from ..config import Config, load_config, save_config
from ..doi import normalize_doi
from ..downloader import BatchEngine
from ..metadata import MetadataCache
from ..models import Event, Paper, STATUS_PENDING, STATUS_QUEUED
from ..naming import PRESET_LABELS, TEMPLATES, build_filename
from ..parsers import parse_file
from .theme import STATUS_COLORS, STATUS_LABELS, apply_style, enable_high_dpi

COLS = ("index", "doi", "title", "status", "file")


class App(tk.Tk):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.title(f"Sci-Hub Downloader v{__version__}")
        self.geometry(cfg.window_geometry or "880x620")

        self.events: "queue.Queue[Event]" = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.papers: list[Paper] = []
        self._row_iid: dict[int, str] = {}

        self._set_icon()
        apply_style(self)
        self._build_ui()
        self._load_state()

        self.report_callback_exception = self._on_tk_error
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._pump)

    # ── 外观 / 状态 ──────────────────────────────

    def _set_icon(self) -> None:
        try:
            if sys.platform == "win32":
                ico = resource_path("assets/sci-hub.ico")
                if ico.exists():
                    self.iconbitmap(str(ico))
            else:
                png = resource_path("assets/sci-hub.png")
                if png.exists():
                    self._icon_img = tk.PhotoImage(file=str(png))  # 防被 GC
                    self.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001 —— 图标失败不该阻止启动
            pass

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # 顶部：单条 DOI 输入 + 导入
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="DOI / 链接:").pack(side="left")
        self.doi_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.doi_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", lambda _e: self._add_doi())
        ttk.Button(top, text="添加", command=self._add_doi).pack(side="left", padx=2)
        ttk.Button(top, text="导入 txt/md", command=self._import_file).pack(
            side="left", padx=2
        )
        ttk.Button(top, text="清空", command=self._clear_papers).pack(side="left", padx=2)
        self.count_lbl = ttk.Label(top, text="共 0 条")
        self.count_lbl.pack(side="right")

        # 中部：任务表
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(
            mid,
            columns=COLS,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "index": ("#", 44, "center"),
            "doi": ("DOI", 200, "w"),
            "title": ("标题", 320, "w"),
            "status": ("状态", 90, "center"),
            "file": ("文件名", 180, "w"),
        }
        for col, (text, width, anchor) in headings.items():
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("title", "file")))
        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status, foreground=color)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        # 底部：选项
        opt = ttk.LabelFrame(self, text="下载选项")
        opt.pack(fill="x", **pad)

        # 保存路径
        row0 = ttk.Frame(opt)
        row0.pack(fill="x", padx=8, pady=4)
        ttk.Label(row0, text="保存到:").pack(side="left")
        self.outdir_var = tk.StringVar(value=cfg_last_outdir(self.cfg))
        ttk.Entry(row0, textvariable=self.outdir_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(row0, text="浏览…", command=self._pick_outdir).pack(side="left")

        # 命名方式
        row1 = ttk.Frame(opt)
        row1.pack(fill="x", padx=8, pady=4)
        ttk.Label(row1, text="命名:").pack(side="left")
        self.naming_var = tk.StringVar(value=cfg_naming(self.cfg))
        self._template_entry = None
        for key, label in PRESET_LABELS.items():
            ttk.Radiobutton(
                row1,
                text=label,
                value=key,
                variable=self.naming_var,
                command=self._on_naming_change,
            ).pack(side="left", padx=4)

        # 自定义模板（命名选 custom 时可用）
        row2 = ttk.Frame(opt)
        row2.pack(fill="x", padx=8, pady=2)
        ttk.Label(row2, text="自定义模板:").pack(side="left")
        self.template_var = tk.StringVar(value=self.cfg.custom_template)
        self._template_entry = ttk.Entry(row2, textvariable=self.template_var)
        self._template_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(
            row2, text="可用: {title} {doi} {year} {author} {journal}", foreground="#6e7781"
        ).pack(side="left")

        # 并发 + 按钮 + 进度
        row3 = ttk.Frame(opt)
        row3.pack(fill="x", padx=8, pady=6)
        ttk.Label(row3, text="并发:").pack(side="left")
        self.concurrency_var = tk.IntVar(value=max(1, min(self.cfg.concurrency, 8)))
        ttk.Spinbox(row3, from_=1, to=8, width=4, textvariable=self.concurrency_var).pack(
            side="left", padx=(0, 12)
        )
        self.progress = ttk.Progressbar(row3, maximum=1)
        self.progress.pack(side="left", fill="x", expand=True, padx=6)
        self.start_btn = ttk.Button(
            row3, text="开始下载", style="Accent.TButton", command=self._start
        )
        self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(row3, text="停止", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=2)

        self.status_lbl = ttk.Label(self, text="就绪", anchor="w")
        self.status_lbl.pack(fill="x", padx=10, pady=(0, 6))

        self._on_naming_change()

    def _load_state(self) -> None:
        # 初始用配置里的命名模式与并发，其余控件已在上面的 StringVar 赋值
        pass

    # ── 数据增删 ──────────────────────────────

    def _refresh_count(self) -> None:
        self.count_lbl.configure(text=f"共 {len(self.papers)} 条")

    def _insert_row(self, paper: Paper) -> None:
        """把一条记录插入表格，状态为「等待确认」。"""
        index = len(self.papers) - 1  # 调用方已在 append 之后
        iid = self.tree.insert(
            "",
            "end",
            iid=str(index),
            values=(
                index + 1,
                paper.doi,
                paper.title or "—",
                STATUS_LABELS[STATUS_PENDING],
                "",
            ),
        )
        self._row_iid[index] = iid
        self.tree.item(iid, tags=(STATUS_PENDING,))

    def _add_doi(self) -> None:
        raw = self.doi_var.get().strip()
        if not raw:
            return
        doi = normalize_doi(raw)
        if not doi:
            messagebox.showwarning("无法识别", f"不是有效的 DOI：\n{raw}")
            return
        if any(p.doi == doi for p in self.papers):
            self.doi_var.set("")
            return
        self.papers.append(Paper(doi=doi))
        self._insert_row(self.papers[-1])
        self.doi_var.set("")
        self._refresh_count()

    def _import_file(self) -> None:
        path = filedialog.askopenfilename(
            title="导入 DOI 列表",
            filetypes=[
                ("文献列表", "*.txt *.md *.markdown *.json"),
                ("文本文件", "*.txt"),
                ("Markdown", "*.md *.markdown"),
                ("JSON", "*.json"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            papers = parse_file(Path(path))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("导入失败", str(e))
            return
        existing = {p.doi for p in self.papers}
        added = 0
        for p in papers:
            if p.doi not in existing:
                self.papers.append(p)
                self._insert_row(p)
                existing.add(p.doi)
                added += 1
        self._refresh_count()
        self.status_lbl.configure(text=f"导入 {added} 条（忽略 {len(papers) - added} 条重复）")

    def _clear_papers(self) -> None:
        self.papers.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_iid.clear()
        self.progress.configure(value=0, maximum=1)
        self._refresh_count()

    # ── 运行控制 ──────────────────────────────

    def _start(self) -> None:
        if not self.papers:
            messagebox.showinfo("提示", "请先添加或导入 DOI")
            return
        outdir = self.outdir_var.get().strip() or "./papers"
        if self.worker and self.worker.is_alive():
            return

        self.cancel.clear()
        # 把「等待确认」的行改为「排队中」，引擎随后逐行更新真实状态。
        for iid in self._row_iid.values():
            self.tree.set(iid, "status", STATUS_LABELS[STATUS_QUEUED])
            self.tree.item(iid, tags=(STATUS_QUEUED,))
        self.progress.configure(value=0, maximum=len(self.papers))
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_lbl.configure(text="开始下载…")

        cache_path = self._cache_path()
        engine = BatchEngine(
            outdir=outdir,
            naming_mode=self.naming_var.get(),
            custom_template=self.template_var.get(),
            concurrency=self.concurrency_var.get(),
            metadata_cache=MetadataCache(cache_path) if self.naming_var.get() != "doi" else None,
            cancel_event=self.cancel,
            mailto=self.cfg.crossref_mailto,
        )

        papers = [Paper(doi=p.doi, title=p.title, author=p.author,
                        year=p.year, journal=p.journal) for p in self.papers]
        self.worker = threading.Thread(
            target=self._run, args=(engine, papers), daemon=True
        )
        self.worker.start()

    def _cache_path(self) -> Path:
        from ..config import config_dir

        return config_dir() / "metadata_cache.json"

    def _run(self, engine: BatchEngine, papers: list[Paper]) -> None:
        try:
            engine.run(papers, on_event=self.events.put)
        except Exception as e:  # noqa: BLE001
            self.events.put(Event(type="log", message=f"引擎异常: {e}"))
        finally:
            # 确保主线程一定收到收尾事件
            self.events.put(Event(type="done", status="cancelled" if self.cancel.is_set() else ""))

    def _stop(self) -> None:
        self.cancel.set()
        self.stop_btn.configure(state="disabled")
        self.status_lbl.configure(text="正在停止…")

    # ── 事件泵（唯一允许碰 Tk 的地方）────────────

    def _pump(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def _handle(self, ev: Event) -> None:
        if ev.type == "row":
            iid = self._row_iid.get(ev.index)
            if iid:
                if ev.title:
                    self.tree.set(iid, "title", ev.title)
                if ev.status:
                    self.tree.set(iid, "status", STATUS_LABELS.get(ev.status, ev.status))
                    self.tree.item(iid, tags=(ev.status,))
                if ev.filename:
                    self.tree.set(iid, "file", ev.filename)
        elif ev.type == "overall":
            self.progress.configure(value=ev.done_bytes)
        elif ev.type == "log":
            self.status_lbl.configure(text=ev.message)
        elif ev.type == "done":
            self._on_done(ev)

    def _on_done(self, ev: Event) -> None:
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        s = ev.summary
        if s is not None:
            text = (
                f"完成: 成功 {s.saved} | 跳过 {s.skipped} | "
                f"未收录 {s.not_found} | 失败 {s.failed} | 总计 {s.total}"
            )
        else:
            text = "已取消" if self.cancel.is_set() else "完成"
        self.status_lbl.configure(text=text)
        self._persist()

    def _persist(self) -> None:
        self.cfg.last_outdir = self.outdir_var.get()
        self.cfg.naming_mode = self.naming_var.get()
        self.cfg.custom_template = self.template_var.get()
        self.cfg.concurrency = self.concurrency_var.get()
        self.cfg.window_geometry = self.geometry()
        save_config(self.cfg)

    # ── 杂项 ──────────────────────────────

    def _on_naming_change(self) -> None:
        if self._template_entry is not None:
            custom = self.naming_var.get() == "custom"
            self._template_entry.configure(state="normal" if custom else "disabled")
        # 更新预览提示
        self.status_lbl.configure(text="就绪")

    def _pick_outdir(self) -> None:
        d = filedialog.askdirectory(title="选择保存目录")
        if d:
            self.outdir_var.set(d)

    def _on_tk_error(self, exc, val, tb) -> None:
        # worker 线程里的异常会经由 events 汇报；这里兜底主线程回调错误。
        try:
            self.status_lbl.configure(text=f"错误: {val}")
        except Exception:  # noqa: BLE001
            pass

    def _on_close(self) -> None:
        self.cancel.set()
        self._persist()
        self.destroy()


def cfg_last_outdir(cfg: Config) -> str:
    return cfg.last_outdir or str(Path.home() / "Downloads")


def cfg_naming(cfg: Config) -> str:
    return cfg.naming_mode if cfg.naming_mode in TEMPLATES or cfg.naming_mode == "custom" else "title"


def main() -> None:
    enable_high_dpi()
    cfg = load_config()
    App(cfg).mainloop()


if __name__ == "__main__":
    main()
