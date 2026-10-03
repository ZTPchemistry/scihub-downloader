"""主窗口。

线程模型：Tk 主线程 + 一个 worker 线程 + 一个 ``queue.Queue``。
worker 只做 ``queue.put``，绝不触碰任何 Tk 对象；消费队列的 ``_pump``
由 ``after()`` 调度，因此 ``_handle`` 天然运行在主线程。这是结构性保证。
检索（搜索论文页）遵循同一模型，只是用了第二条队列 ``search_events``：
两条事件流互不干扰，下载行事件的下标语义（任务列表下标）与检索结果下标
不会混淆。

中英文切换：所有文案经 :mod:`scihub_dl.i18n` 产出，语言菜单切换后调用
``_apply_lang`` 原地更新控件文本，不重建窗口、不丢已添加的任务。

界面结构：上方 Notebook（任务列表 / 搜索论文），下方是**两个页签共用**的
下载选项栏——这样在搜索页添加完文献，不用切页签就能直接点「开始下载」。
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__, resource_path
from ..config import Config, load_config, save_config
from ..doi import normalize_doi
from ..downloader import BatchEngine
from ..i18n import (
    LANGS,
    LANG_NAMES,
    get_lang,
    naming_labels,
    search_avail_label,
    search_sort_labels,
    set_lang,
    status_label,
    tr,
)
from ..metadata import MetadataCache
from ..models import (
    AVAIL_AVAILABLE,
    AVAIL_CHECKING,
    AVAIL_NOT_FOUND,
    Event,
    Paper,
    SearchResult,
    STATUS_PENDING,
    STATUS_QUEUED,
)
from ..naming import TEMPLATES, build_filename
from ..parsers import parse_file
from ..search import DEFAULT_ROWS, DEFAULT_SORT, MAX_ROWS, SORTS, SearchError, SearchService
from .theme import AVAIL_COLORS, STATUS_COLORS, apply_style, enable_high_dpi

COLS = ("index", "doi", "title", "status", "file")

#: 搜索结果表。``sel`` 用字符模拟复选框——Tk 的 Treeview 没有原生复选框。
SEARCH_COLS = ("sel", "title", "author", "year", "journal", "doi", "avail", "note")

_CHECK_ON = "☑"
_CHECK_OFF = "☐"
_CHECK_BLOCKED = "—"  # 无 DOI 或已确认未收录：不可勾选

#: 默认窗口尺寸。搜索结果有 8 列，比原来宽一些。
DEFAULT_GEOMETRY = "1000x700"


class App(tk.Tk):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        set_lang(cfg.lang)
        self.title(f"Sci-Hub Downloader v{__version__}")
        self.geometry(cfg.window_geometry or DEFAULT_GEOMETRY)

        self.events: "queue.Queue[Event]" = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.papers: list[Paper] = []
        self._row_iid: dict[int, str] = {}

        # 检索页自己的事件流与状态（与下载事件完全分开）。
        self.search_events: "queue.Queue[tuple]" = queue.Queue()
        self.search_results: list[SearchResult] = []
        self._search_checked: list[bool] = []
        self._search_token = 0          # 每次检索自增，用来丢弃过期线程的消息
        self._search_cancel: threading.Event | None = None
        self._search_worker: threading.Thread | None = None

        self._set_icon()
        apply_style(self)
        self._build_ui()
        self._build_menu()
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

    def _build_menu(self) -> None:
        self._lang_var = tk.StringVar(value=get_lang())
        self.menubar = tk.Menu(self)
        self.config(menu=self.menubar)
        self._refresh_menu()

    def _refresh_menu(self) -> None:
        self.menubar.delete(0, "end")
        lang_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label=tr("menu_language"), menu=lang_menu)
        for code in LANGS:
            lang_menu.add_radiobutton(
                label=LANG_NAMES[code],
                value=code,
                variable=self._lang_var,
                command=self._on_lang_change,
            )

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # 上方：任务列表 / 搜索论文 两个页签
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, **pad)
        self.tab_tasks = ttk.Frame(self.notebook)
        self.tab_search = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_tasks, text=tr("tab_tasks"))
        self.notebook.add(self.tab_search, text=tr("tab_search"))

        self._build_tasks_tab()
        self._build_search_tab()
        self._build_options(pad)

        self.status_lbl = ttk.Label(self, text=tr("ready"), anchor="w")
        self.status_lbl.pack(fill="x", padx=10, pady=(0, 6))

        self._on_naming_change()

    def _build_tasks_tab(self) -> None:
        pad = {"padx": 8, "pady": 4}
        parent = self.tab_tasks

        # 顶部：单条 DOI 输入 + 导入
        top = ttk.Frame(parent)
        top.pack(fill="x", **pad)
        self.doi_label = ttk.Label(top, text=tr("doi_url"))
        self.doi_label.pack(side="left")
        self.doi_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.doi_var)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.bind("<Return>", lambda _e: self._add_doi())
        self.add_btn = ttk.Button(top, text=tr("add"), command=self._add_doi)
        self.add_btn.pack(side="left", padx=2)
        self.import_btn = ttk.Button(top, text=tr("import_file"), command=self._import_file)
        self.import_btn.pack(side="left", padx=2)
        self.clear_btn = ttk.Button(top, text=tr("clear"), command=self._clear_papers)
        self.clear_btn.pack(side="left", padx=2)
        self.count_lbl = ttk.Label(top, text=tr("count_items", n=0))
        self.count_lbl.pack(side="right")

        # 中部：任务表
        mid = ttk.Frame(parent)
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
            "title": (tr("col_title"), 320, "w"),
            "status": (tr("col_status"), 90, "center"),
            "file": (tr("col_file"), 180, "w"),
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

    def _build_search_tab(self) -> None:
        """搜索论文页：条件行 + 结果表 + 底部操作行。"""
        pad = {"padx": 8, "pady": 4}
        parent = self.tab_search

        # 第一行：关键词 + 搜索/停止
        row0 = ttk.Frame(parent)
        row0.pack(fill="x", **pad)
        self.search_label = ttk.Label(row0, text=tr("search_label"))
        self.search_label.pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(row0, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.search_entry.bind("<Return>", lambda _e: self._do_search())
        self.search_btn = ttk.Button(
            row0, text=tr("search_button"), style="Accent.TButton", command=self._do_search
        )
        self.search_btn.pack(side="left", padx=2)
        self.search_stop_btn = ttk.Button(
            row0, text=tr("stop"), command=self._stop_search, state="disabled"
        )
        self.search_stop_btn.pack(side="left", padx=2)

        # 第二行：年份范围 + 排序 + 条数
        row1 = ttk.Frame(parent)
        row1.pack(fill="x", padx=8)
        self.year_label = ttk.Label(row1, text=tr("search_years"))
        self.year_label.pack(side="left")
        self.year_from_var = tk.StringVar()
        self.year_to_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.year_from_var, width=6).pack(side="left", padx=(4, 2))
        ttk.Label(row1, text="–").pack(side="left")
        ttk.Entry(row1, textvariable=self.year_to_var, width=6).pack(side="left", padx=(2, 14))
        self.sort_label = ttk.Label(row1, text=tr("search_sort"))
        self.sort_label.pack(side="left")
        self.sort_var = tk.StringVar(value=DEFAULT_SORT)
        self._sort_radios: list[tuple[str, ttk.Radiobutton]] = []
        for key in SORTS:
            rb = ttk.Radiobutton(
                row1,
                text=search_sort_labels()[key],
                value=key,
                variable=self.sort_var,
            )
            rb.pack(side="left", padx=4)
            self._sort_radios.append((key, rb))
        self.rows_label = ttk.Label(row1, text=tr("search_rows"))
        self.rows_label.pack(side="left", padx=(14, 0))
        self.rows_var = tk.IntVar(value=DEFAULT_ROWS)
        ttk.Spinbox(
            row1, from_=5, to=MAX_ROWS, increment=5, width=5, textvariable=self.rows_var
        ).pack(side="left", padx=4)

        # 结果表
        mid = ttk.Frame(parent)
        mid.pack(fill="both", expand=True, **pad)
        self.search_tree = ttk.Treeview(
            mid, columns=SEARCH_COLS, show="headings", selectmode="browse"
        )
        headings = {
            "sel": (tr("col_sel"), 48, "center"),
            "title": (tr("col_title"), 260, "w"),
            "author": (tr("col_author"), 90, "w"),
            "year": (tr("col_year"), 56, "center"),
            "journal": (tr("col_journal"), 120, "w"),
            "doi": ("DOI", 160, "w"),
            "avail": (tr("col_avail"), 84, "center"),
            "note": (tr("col_note"), 80, "w"),
        }
        for col, (text, width, anchor) in headings.items():
            self.search_tree.heading(col, text=text)
            self.search_tree.column(
                col, width=width, anchor=anchor, stretch=(col in ("title", "journal"))
            )
        for state, color in AVAIL_COLORS.items():
            self.search_tree.tag_configure(state, foreground=color)
        self.search_tree.bind("<Button-1>", self._on_search_click)
        self.search_tree.bind("<Double-1>", self._on_search_double)

        svsb = ttk.Scrollbar(mid, orient="vertical", command=self.search_tree.yview)
        shsb = ttk.Scrollbar(mid, orient="horizontal", command=self.search_tree.xview)
        self.search_tree.configure(yscrollcommand=svsb.set, xscrollcommand=shsb.set)
        self.search_tree.grid(row=0, column=0, sticky="nsew")
        svsb.grid(row=0, column=1, sticky="ns")
        shsb.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        # 底部操作行
        row2 = ttk.Frame(parent)
        row2.pack(fill="x", padx=8, pady=(0, 6))
        self.select_all_btn = ttk.Button(
            row2, text=tr("select_all"), command=self._select_all_results
        )
        self.select_all_btn.pack(side="left", padx=2)
        self.select_none_btn = ttk.Button(
            row2, text=tr("select_none"), command=self._select_no_results
        )
        self.select_none_btn.pack(side="left", padx=2)
        self.add_selected_btn = ttk.Button(
            row2, text=tr("add_selected"), style="Accent.TButton", command=self._add_selected_results
        )
        self.add_selected_btn.pack(side="left", padx=2)
        self.open_doi_btn = ttk.Button(row2, text=tr("open_doi"), command=self._open_selected_doi)
        self.open_doi_btn.pack(side="left", padx=2)
        self.search_hint_lbl = ttk.Label(row2, text=tr("search_hint"), foreground="#6e7781")
        self.search_hint_lbl.pack(side="right")

    def _build_options(self, pad: dict) -> None:
        # 底部：选项。刻意放在 Notebook 之外——两个页签共用同一份下载设置，
        # 于是在搜索页添加完文献可以直接点「开始下载」。
        self.opt_frame = ttk.LabelFrame(self, text=tr("download_options"))
        self.opt_frame.pack(fill="x", **pad)

        # 保存路径
        row0 = ttk.Frame(self.opt_frame)
        row0.pack(fill="x", padx=8, pady=4)
        self.outdir_label = ttk.Label(row0, text=tr("save_to"))
        self.outdir_label.pack(side="left")
        self.outdir_var = tk.StringVar(value=cfg_last_outdir(self.cfg))
        ttk.Entry(row0, textvariable=self.outdir_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        self.browse_btn = ttk.Button(row0, text=tr("browse"), command=self._pick_outdir)
        self.browse_btn.pack(side="left")

        # 命名方式
        row1 = ttk.Frame(self.opt_frame)
        row1.pack(fill="x", padx=8, pady=4)
        self.naming_label = ttk.Label(row1, text=tr("naming"))
        self.naming_label.pack(side="left")
        self.naming_var = tk.StringVar(value=cfg_naming(self.cfg))
        self._template_entry = None
        self._naming_radios: list[tuple[str, ttk.Radiobutton]] = []
        for key in naming_labels():
            rb = ttk.Radiobutton(
                row1,
                text=naming_labels()[key],
                value=key,
                variable=self.naming_var,
                command=self._on_naming_change,
            )
            rb.pack(side="left", padx=4)
            self._naming_radios.append((key, rb))

        # 自定义模板（命名选 custom 时可用）
        row2 = ttk.Frame(self.opt_frame)
        row2.pack(fill="x", padx=8, pady=2)
        self.template_label = ttk.Label(row2, text=tr("custom_template"))
        self.template_label.pack(side="left")
        self.template_var = tk.StringVar(value=self.cfg.custom_template)
        self._template_entry = ttk.Entry(row2, textvariable=self.template_var)
        self._template_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.template_hint_lbl = ttk.Label(
            row2, text=tr("template_hint"), foreground="#6e7781"
        )
        self.template_hint_lbl.pack(side="left")

        # 并发 + 按钮 + 进度
        row3 = ttk.Frame(self.opt_frame)
        row3.pack(fill="x", padx=8, pady=6)
        self.concurrency_label = ttk.Label(row3, text=tr("concurrency"))
        self.concurrency_label.pack(side="left")
        self.concurrency_var = tk.IntVar(value=max(1, min(self.cfg.concurrency, 8)))
        ttk.Spinbox(row3, from_=1, to=8, width=4, textvariable=self.concurrency_var).pack(
            side="left", padx=(0, 12)
        )
        self.progress = ttk.Progressbar(row3, maximum=1)
        self.progress.pack(side="left", fill="x", expand=True, padx=6)
        self.start_btn = ttk.Button(
            row3, text=tr("start"), style="Accent.TButton", command=self._start
        )
        self.start_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(row3, text=tr("stop"), command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=2)

    def _load_state(self) -> None:
        # 初始用配置里的命名模式与并发，其余控件已在上面的 StringVar 赋值
        pass

    # ── 语言切换 ──────────────────────────────

    def _on_lang_change(self) -> None:
        lang = self._lang_var.get()
        set_lang(lang)
        self.cfg.lang = lang
        self._apply_lang()
        self._persist()

    def _apply_lang(self) -> None:
        """原地更新所有控件的文案，不重建窗口、不丢任务。"""
        self._refresh_menu()
        self.notebook.tab(self.tab_tasks, text=tr("tab_tasks"))
        self.notebook.tab(self.tab_search, text=tr("tab_search"))
        self.doi_label.configure(text=tr("doi_url"))
        self.add_btn.configure(text=tr("add"))
        self.import_btn.configure(text=tr("import_file"))
        self.clear_btn.configure(text=tr("clear"))
        self._refresh_count()
        self.tree.heading("title", text=tr("col_title"))
        self.tree.heading("status", text=tr("col_status"))
        self.tree.heading("file", text=tr("col_file"))
        # 已存在行的状态列按新语言重渲染（tag 即状态码）。
        for iid in self.tree.get_children():
            tags = self.tree.item(iid, "tags")
            if tags:
                self.tree.set(iid, "status", status_label(tags[0]))
        self.opt_frame.configure(text=tr("download_options"))
        self.outdir_label.configure(text=tr("save_to"))
        self.browse_btn.configure(text=tr("browse"))
        self.naming_label.configure(text=tr("naming"))
        for key, rb in self._naming_radios:
            rb.configure(text=naming_labels()[key])
        self.template_label.configure(text=tr("custom_template"))
        self.template_hint_lbl.configure(text=tr("template_hint"))
        self.concurrency_label.configure(text=tr("concurrency"))
        self.start_btn.configure(text=tr("start"))
        self.stop_btn.configure(text=tr("stop"))
        self._apply_lang_search()
        self.status_lbl.configure(text=tr("ready"))

    def _apply_lang_search(self) -> None:
        """搜索页的文案更新，外加结果表的表头与已有行重渲染。"""
        self.search_label.configure(text=tr("search_label"))
        self.search_btn.configure(text=tr("search_button"))
        self.search_stop_btn.configure(text=tr("stop"))
        self.year_label.configure(text=tr("search_years"))
        self.sort_label.configure(text=tr("search_sort"))
        for key, rb in self._sort_radios:
            rb.configure(text=search_sort_labels()[key])
        self.rows_label.configure(text=tr("search_rows"))
        headings = {
            "sel": tr("col_sel"),
            "title": tr("col_title"),
            "author": tr("col_author"),
            "year": tr("col_year"),
            "journal": tr("col_journal"),
            "avail": tr("col_avail"),
            "note": tr("col_note"),
        }
        for col, text in headings.items():
            self.search_tree.heading(col, text=text)
        self.select_all_btn.configure(text=tr("select_all"))
        self.select_none_btn.configure(text=tr("select_none"))
        self.add_selected_btn.configure(text=tr("add_selected"))
        self.open_doi_btn.configure(text=tr("open_doi"))
        if not self.search_results:
            self.search_hint_lbl.configure(text=tr("search_hint"))
        for i in range(len(self.search_results)):
            self._update_result_row(i)

    # ── 数据增删 ──────────────────────────────

    def _refresh_count(self) -> None:
        self.count_lbl.configure(text=tr("count_items", n=len(self.papers)))

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
                status_label(STATUS_PENDING),
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
            messagebox.showwarning(tr("unrecognized"), tr("invalid_doi", raw=raw))
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
            title=tr("import_title"),
            filetypes=[
                (tr("filetype_list"), "*.txt *.md *.markdown *.json"),
                (tr("filetype_text"), "*.txt"),
                (tr("filetype_md"), "*.md *.markdown"),
                (tr("filetype_json"), "*.json"),
                (tr("filetype_all"), "*.*"),
            ],
        )
        if not path:
            return
        try:
            papers = parse_file(Path(path))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(tr("import_failed"), str(e))
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
        self.status_lbl.configure(text=tr("imported", added=added, n=len(papers) - added))

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
            messagebox.showinfo(tr("info"), tr("need_doi"))
            return
        outdir = self.outdir_var.get().strip() or "./papers"
        if self.worker and self.worker.is_alive():
            return

        self.cancel.clear()
        # 把「等待确认」的行改为「排队中」，引擎随后逐行更新真实状态。
        for iid in self._row_iid.values():
            self.tree.set(iid, "status", status_label(STATUS_QUEUED))
            self.tree.item(iid, tags=(STATUS_QUEUED,))
        self.progress.configure(value=0, maximum=len(self.papers))
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_lbl.configure(text=tr("starting"))

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
            self.events.put(Event(type="log", message=tr("engine_error", e=e)))
        finally:
            # 确保主线程一定收到收尾事件
            self.events.put(Event(type="done", status="cancelled" if self.cancel.is_set() else ""))

    def _stop(self) -> None:
        self.cancel.set()
        self.stop_btn.configure(state="disabled")
        self.status_lbl.configure(text=tr("stopping"))

    # ── 检索（搜索论文页）─────────────────────

    def _search_row_count(self) -> int:
        try:
            return int(self.rows_var.get())
        except Exception:  # noqa: BLE001 —— Spinbox 里被输入了非数字
            return DEFAULT_ROWS

    def _do_search(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            self.status_lbl.configure(text=tr("search_need_query"))
            return

        # 上一轮可能还在探测：让它停下并作废旧消息（token 变了就不再受理）。
        if self._search_cancel is not None:
            self._search_cancel.set()
        self._search_cancel = threading.Event()
        self._search_token += 1
        token = self._search_token

        service = SearchService(
            mailto=self.cfg.crossref_mailto,
            mirrors=self.cfg.mirrors or None,
            cancel_event=self._search_cancel,
        )
        self.search_btn.configure(state="disabled")
        self.search_stop_btn.configure(state="normal")
        self.search_hint_lbl.configure(text="")
        self.status_lbl.configure(text=tr("search_searching"))
        self._render_results([])

        self._search_worker = threading.Thread(
            target=self._search_run,
            args=(
                token,
                service,
                self._search_cancel,  # 捕获本轮的事件对象：新检索会替换属性
                query,
                self._search_row_count(),
                self.year_from_var.get(),
                self.year_to_var.get(),
                self.sort_var.get(),
            ),
            daemon=True,
        )
        self._search_worker.start()

    def _search_run(
        self,
        token: int,
        service: SearchService,
        cancel: threading.Event,
        query: str,
        rows: int,
        year_from: str,
        year_to: str,
        sort: str,
    ) -> None:
        """worker 线程：检索 → 回传结果 → 探测收录。全程只 put，不碰 Tk。"""
        try:
            results = service.search(
                query, rows=rows, year_from=year_from, year_to=year_to, sort=sort
            )
        except SearchError as e:
            self.search_events.put(("error", token, str(e)))
            return
        except Exception as e:  # noqa: BLE001 —— 任何意外都汇报，不留死界面
            self.search_events.put(("error", token, str(e)))
            return

        self.search_events.put(("results", token, results))
        if results and not cancel.is_set():
            service.probe(
                results,
                on_update=lambda i, r: self.search_events.put(("probe", token, i, r.avail)),
            )
        self.search_events.put(("done", token))

    def _handle_search(self, msg: tuple) -> None:
        kind = msg[0]
        if len(msg) < 2 or msg[1] != self._search_token:
            return  # 上一轮检索的迟到消息

        if kind == "results":
            self._render_results(msg[2])
            # 结果已经拿到，探测还在后台跑：立刻放开搜索按钮，用户想换关键词
            # 随时可以再搜一次（新一轮会取消上一轮的探测）。
            self.search_btn.configure(state="normal")
            if msg[2]:
                self.status_lbl.configure(text=tr("search_hits", n=len(msg[2])))
            else:
                self.status_lbl.configure(text=tr("search_empty"))
        elif kind == "probe":
            index, state = msg[2], msg[3]
            if 0 <= index < len(self.search_results):
                self.search_results[index].avail = state
                self._update_result_row(index)
        elif kind == "error":
            self.search_btn.configure(state="normal")
            self.search_stop_btn.configure(state="disabled")
            self.status_lbl.configure(text=tr("search_failed", e=msg[2]))
            messagebox.showwarning(tr("search_failed_title"), tr("search_failed", e=msg[2]))
        elif kind == "done":
            self.search_btn.configure(state="normal")
            self.search_stop_btn.configure(state="disabled")
            if self._search_cancel is not None and self._search_cancel.is_set():
                self.status_lbl.configure(text=tr("search_stopped"))
            else:
                self.status_lbl.configure(text=tr("search_done", n=len(self.search_results)))

    def _stop_search(self) -> None:
        if self._search_cancel is not None:
            self._search_cancel.set()
        self.search_stop_btn.configure(state="disabled")
        self.status_lbl.configure(text=tr("stopping"))

    # ── 检索结果表 ────────────────────────────

    def _render_results(self, results: list[SearchResult]) -> None:
        self.search_results = list(results)
        self._search_checked = [False] * len(self.search_results)
        self.search_tree.delete(*self.search_tree.get_children())
        for i, result in enumerate(self.search_results):
            self.search_tree.insert(
                "", "end", iid=str(i), values=self._result_values(i, result)
            )
            self._update_result_row(i)
        if self.search_results:
            self.search_hint_lbl.configure(text=tr("search_hint"))

    def _result_values(self, index: int, result: SearchResult) -> tuple:
        return (
            self._check_mark(index, result),
            result.title or "—",
            result.author or "",
            result.year or "",
            result.journal or "",
            result.doi or "—",
            search_avail_label(result.avail),
            self._result_note(result),
        )

    def _update_result_row(self, index: int) -> None:
        if not (0 <= index < len(self.search_results)):
            return
        iid = str(index)
        if not self.search_tree.exists(iid):
            return
        result = self.search_results[index]
        self.search_tree.item(iid, values=self._result_values(index, result))
        self.search_tree.item(iid, tags=self._result_tags(result))

    def _check_mark(self, index: int, result: SearchResult) -> str:
        if not result.selectable:
            return _CHECK_BLOCKED
        return _CHECK_ON if self._search_checked[index] else _CHECK_OFF

    def _result_note(self, result: SearchResult) -> str:
        if not result.doi:
            return tr("search_note_no_doi")
        if self._in_paper_list(result.doi):
            return tr("search_note_in_list")
        return ""

    def _result_tags(self, result: SearchResult) -> tuple[str, ...]:
        """一行只挂一个 tag——Tk 的 tag 叠加优先级不好把握，配色必须互斥。"""
        if not result.doi:
            return ("no_doi",)
        if result.avail == AVAIL_NOT_FOUND:
            return (AVAIL_NOT_FOUND,)
        if self._in_paper_list(result.doi):
            return ("in_list",)
        if result.avail == AVAIL_AVAILABLE:
            return (AVAIL_AVAILABLE,)
        if result.avail == AVAIL_CHECKING:
            return (AVAIL_CHECKING,)
        return ("unknown",)

    def _paper_doi_set(self) -> set[str]:
        return {normalize_doi(p.doi) or p.doi for p in self.papers}

    def _in_paper_list(self, doi: str) -> bool:
        if not doi:
            return False
        return (normalize_doi(doi) or doi) in self._paper_doi_set()

    def _on_search_click(self, event) -> None:
        """点勾选列切换选中状态；disabled 行给出原因提示。"""
        iid = self.search_tree.identify_row(event.y)
        if not iid or self.search_tree.identify_column(event.x) != "#1":
            return
        self._toggle_result(int(iid))

    def _toggle_result(self, index: int) -> None:
        if not (0 <= index < len(self.search_results)):
            return
        result = self.search_results[index]
        if not result.selectable:
            self.status_lbl.configure(
                text=tr(
                    "search_row_blocked",
                    title=(result.title or result.doi or "—")[:48],
                )
            )
            return
        self._search_checked[index] = not self._search_checked[index]
        self._update_result_row(index)

    def _on_search_double(self, event) -> None:
        iid = self.search_tree.identify_row(event.y)
        # 勾选列的双击已经在 _on_search_click 里处理过（两次切换正好抵消），
        # 这里不要再弹浏览器，否则用户勾选时会被打断。
        if not iid or self.search_tree.identify_column(event.x) == "#1":
            return
        self._open_doi(int(iid))

    def _open_doi(self, index: int) -> None:
        if not (0 <= index < len(self.search_results)):
            return
        url = self.search_results[index].doi_url
        if not url:
            self.status_lbl.configure(text=tr("search_no_doi_open"))
            return
        try:
            webbrowser.open(url)
            self.status_lbl.configure(text=url)
        except Exception as e:  # noqa: BLE001 —— 没装浏览器不该崩
            self.status_lbl.configure(text=tr("error", val=e))

    def _open_selected_doi(self) -> None:
        selection = self.search_tree.selection()
        if not selection:
            return
        self._open_doi(int(selection[0]))

    def _select_all_results(self) -> None:
        for i, result in enumerate(self.search_results):
            self._search_checked[i] = result.selectable
            self._update_result_row(i)

    def _select_no_results(self) -> None:
        for i in range(len(self.search_results)):
            self._search_checked[i] = False
            self._update_result_row(i)

    def _add_selected_results(self) -> None:
        """把勾选的结果加成任务记录（等待确认），不直接开始下载。"""
        chosen = [
            result
            for i, result in enumerate(self.search_results)
            if self._search_checked[i] and result.selectable
        ]
        if not chosen:
            self.status_lbl.configure(text=tr("search_none_selected"))
            return

        known = self._paper_doi_set()
        added = 0
        skipped = 0
        for result in chosen:
            doi = normalize_doi(result.doi) or result.doi
            if doi in known:
                skipped += 1
                continue
            paper = result.to_paper()
            paper.doi = doi
            self.papers.append(paper)
            self._insert_row(paper)
            known.add(doi)
            added += 1

        self._refresh_count()
        # 备注列要立刻反映「已在列表」。
        for i in range(len(self.search_results)):
            self._update_result_row(i)
        self.status_lbl.configure(text=tr("search_added", added=added, skipped=skipped))

    # ── 事件泵（唯一允许碰 Tk 的地方）────────────

    def _pump(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self._handle_search(self.search_events.get_nowait())
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
                    self.tree.set(iid, "status", status_label(ev.status))
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
            text = tr(
                "done_summary",
                saved=s.saved,
                skipped=s.skipped,
                not_found=s.not_found,
                failed=s.failed,
                total=s.total,
            )
        else:
            text = tr("cancelled") if self.cancel.is_set() else tr("done")
        self.status_lbl.configure(text=text)
        self._persist()

    def _persist(self) -> None:
        self.cfg.last_outdir = self.outdir_var.get()
        self.cfg.naming_mode = self.naming_var.get()
        self.cfg.custom_template = self.template_var.get()
        self.cfg.concurrency = self.concurrency_var.get()
        self.cfg.window_geometry = self.geometry()
        self.cfg.lang = get_lang()
        save_config(self.cfg)

    # ── 杂项 ──────────────────────────────

    def _on_naming_change(self) -> None:
        if self._template_entry is not None:
            custom = self.naming_var.get() == "custom"
            self._template_entry.configure(state="normal" if custom else "disabled")
        # 更新预览提示
        self.status_lbl.configure(text=tr("ready"))

    def _pick_outdir(self) -> None:
        d = filedialog.askdirectory(title=tr("save_dir_title"))
        if d:
            self.outdir_var.set(d)

    def _on_tk_error(self, exc, val, tb) -> None:
        # worker 线程里的异常会经由 events 汇报；这里兜底主线程回调错误。
        try:
            self.status_lbl.configure(text=tr("error", val=val))
        except Exception:  # noqa: BLE001
            pass

    def _on_close(self) -> None:
        self.cancel.set()
        if self._search_cancel is not None:
            self._search_cancel.set()  # 别让探测线程拖着进程不退出
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
