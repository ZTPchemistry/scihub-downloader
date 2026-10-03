"""轻量级中英文切换。

零第三方依赖，只维护一份 ``_STR`` 字典（``zh`` / ``en`` 两种语言）。
GUI 与 CLI 通过 :func:`tr` 取文案，通过 :func:`set_lang` 切换语言；
语言偏好随 ``Config.lang`` 持久化（见 :mod:`scihub_dl.config`）。

约定：所有用户可见文案都经这里产出；其余模块（downloader 的 message、CLI、
GUI）不再各自硬编码中文。``theme.STATUS_LABELS`` 与 ``naming.PRESET_LABELS``
仍是旧的中文常量，仅作兼容保留，运行时以本模块为准。
"""

from __future__ import annotations

from .models import (
    AVAIL_AVAILABLE,
    AVAIL_CHECKING,
    AVAIL_NOT_FOUND,
    AVAIL_UNKNOWN,
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
    "LANGS",
    "LANG_NAMES",
    "get_lang",
    "set_lang",
    "tr",
    "status_label",
    "naming_labels",
    "search_avail_label",
    "search_sort_labels",
]

#: 支持的语言代码，顺序即语言菜单里的显示顺序。
LANGS: tuple[str, ...] = ("zh", "en")

#: 语言代码 → 各自语言下的名称（用于语言菜单项）。
LANG_NAMES: dict[str, str] = {"zh": "中文", "en": "English"}

_current: str = "zh"

# ── 状态码 → 翻译 key ──────────────────────────────
_STATUS_KEYS: dict[str, str] = {
    STATUS_PENDING: "status_pending",
    STATUS_QUEUED: "status_queued",
    STATUS_METADATA: "status_metadata",
    STATUS_SEARCHING: "status_searching",
    STATUS_DOWNLOADING: "status_downloading",
    STATUS_SAVED: "status_saved",
    STATUS_SKIPPED: "status_skipped",
    STATUS_FAILED: "status_failed",
    STATUS_NOT_FOUND: "status_not_found",
    STATUS_NETWORK_ERROR: "status_network_error",
    STATUS_CAPTCHA: "status_captcha",
    STATUS_NO_PDF: "status_no_pdf",
    STATUS_BAD_PDF: "status_bad_pdf",
    STATUS_CANCELLED: "status_cancelled",
}

# ── 命名模式 → 翻译 key ──────────────────────────────
_NAMING_KEYS: dict[str, str] = {
    "title": "naming_title",
    "doi": "naming_doi",
    "year": "naming_year",
    "author": "naming_author",
    "custom": "naming_custom",
}

# ── 检索排序 → 翻译 key ──────────────────────────────
_SORT_KEYS: dict[str, str] = {
    "relevance": "sort_relevance",
    "published": "sort_published",
}

# ── Sci-Hub 收录状态 → 翻译 key ──────────────────────
_AVAIL_KEYS: dict[str, str] = {
    AVAIL_UNKNOWN: "avail_unknown",
    AVAIL_CHECKING: "avail_checking",
    AVAIL_AVAILABLE: "avail_available",
    AVAIL_NOT_FOUND: "avail_not_found",
}

# ── 翻译表 ────────────────────────────────────────
# key 用英文语义命名；每个语言给出对应文案，缺失时回退到 key 本身。
_STR: dict[str, dict[str, str]] = {
    "zh": {
        # 状态
        "status_pending": "等待确认",
        "status_queued": "排队中",
        "status_metadata": "查询标题",
        "status_searching": "搜索中",
        "status_downloading": "下载中",
        "status_saved": "已完成",
        "status_skipped": "已跳过",
        "status_failed": "失败",
        "status_not_found": "未收录",
        "status_network_error": "网络失败",
        "status_captcha": "验证码拦截",
        "status_no_pdf": "无 PDF 链接",
        "status_bad_pdf": "内容异常",
        "status_cancelled": "已取消",
        # 命名方式
        "naming_title": "标题",
        "naming_doi": "DOI",
        "naming_year": "年份 - 标题",
        "naming_author": "作者 - 年份 - 标题",
        "naming_custom": "自定义",
        # GUI 通用
        "doi_url": "DOI / 链接:",
        "add": "添加",
        "import_file": "导入 txt/md",
        "clear": "清空",
        "count_items": "共 {n} 条",
        "col_title": "标题",
        "col_status": "状态",
        "col_file": "文件名",
        "download_options": "下载选项",
        "save_to": "保存到:",
        "browse": "浏览…",
        "naming": "命名:",
        "custom_template": "自定义模板:",
        "template_hint": "可用: {title} {doi} {year} {author} {journal}",
        "concurrency": "并发:",
        "start": "开始下载",
        "stop": "停止",
        "ready": "就绪",
        "menu_language": "语言",
        # 对话框 / 提示
        "unrecognized": "无法识别",
        "invalid_doi": "不是有效的 DOI：\n{raw}",
        "import_failed": "导入失败",
        "import_title": "导入 DOI 列表",
        "filetype_list": "文献列表",
        "filetype_text": "文本文件",
        "filetype_md": "Markdown",
        "filetype_json": "JSON",
        "filetype_all": "所有文件",
        "imported": "导入 {added} 条（忽略 {n} 条重复）",
        "info": "提示",
        "need_doi": "请先添加或导入 DOI",
        "starting": "开始下载…",
        "stopping": "正在停止…",
        "engine_error": "引擎异常: {e}",
        "error": "错误: {val}",
        "done_summary": "完成: 成功 {saved} | 跳过 {skipped} | 未收录 {not_found} | 失败 {failed} | 总计 {total}",
        "cancelled": "已取消",
        "done": "完成",
        "save_dir_title": "选择保存目录",
        # 下载引擎 message
        "msg_prepare": "准备",
        "msg_query_meta": "查询 CrossRef 标题…",
        "msg_exists": "已存在，跳过",
        "msg_search": "搜索 Sci-Hub…",
        "msg_not_found": "Sci-Hub 未收录",
        "msg_captcha": "被验证码拦截",
        "msg_network": "网络连接失败",
        "msg_no_pdf": "未找到 PDF 链接",
        "msg_downloading": "下载中…",
        "msg_bad_pdf": "内容不是有效 PDF",
        "msg_download_fail": "下载连接失败",
        "msg_download_error": "下载失败",
        "msg_saved": "完成 {kb} KB",
        # 检索（搜索论文页）
        "tab_tasks": "任务列表",
        "tab_search": "搜索论文",
        "search_label": "标题 / 关键词:",
        "search_button": "搜索文献",
        "search_years": "年份:",
        "search_sort": "排序:",
        "sort_relevance": "相关度",
        "sort_published": "最新发表",
        "search_rows": "条数:",
        "col_sel": "选择",
        "col_author": "作者",
        "col_year": "年份",
        "col_journal": "期刊",
        "col_avail": "Sci-Hub",
        "col_note": "备注",
        "select_all": "全选可下载",
        "select_none": "取消全选",
        "add_selected": "添加到任务列表",
        "open_doi": "打开 DOI",
        "search_hint": "双击结果行可用浏览器打开 DOI 页面",
        "search_need_query": "请输入标题或关键词",
        "search_searching": "正在检索 CrossRef…",
        "search_hits": "共 {n} 条结果，正在检查 Sci-Hub 收录情况…",
        "search_done": "检索完成：共 {n} 条结果",
        "search_stopped": "已停止检索",
        "search_empty": "没有找到匹配的文献",
        "search_failed_title": "检索失败",
        "search_failed": "检索失败: {e}",
        "search_none_selected": "请先勾选要下载的文献",
        "search_added": "已添加 {added} 条到任务列表（忽略 {skipped} 条重复）",
        "search_note_in_list": "已在列表",
        "search_note_no_doi": "无 DOI",
        "search_row_blocked": "该条不可选：{title}",
        "search_no_doi_open": "该条没有 DOI，无法打开",
        "avail_unknown": "未确定",
        "avail_checking": "检查中…",
        "avail_available": "可下载",
        "avail_not_found": "未收录",
        # CLI
        "cli_description": "Sci-Hub 文献下载器 — 根据 DOI 下载论文 PDF",
        "cli_epilog_examples": "示例:",
        "cli_epilog_naming": "命名方式",
        "cli_doi": "单个 DOI",
        "cli_batch": "JSON 批处理文件路径",
        "cli_markdown": "从 Markdown 文献汇总提取 DOI",
        "cli_file": "txt/md/json 导入文件（自动识别格式）",
        "cli_title": "文献标题（与 --doi 配合）",
        "cli_outdir": "输出目录（默认 ./papers）",
        "cli_naming": "命名方式（默认沿用上次或 title）",
        "cli_template": "--naming custom 时使用",
        "cli_concurrency": "并发数 1-8（默认 2）",
        "cli_plain": "md 文件按纯文本逐行解析",
        "cli_no_metadata": "不查 CrossRef 补全标题",
        "cli_dry_run": "仅预览，不实际下载",
        "cli_lang": "界面语言（zh / en）",
        "cli_search": "按标题/关键词检索 CrossRef（用 --pick 选择要下载的条目）",
        "cli_search_limit": "检索返回条数（默认 20，最大 100）",
        "cli_pick": "从检索结果中挑选序号下载，如 1,3 或 1-3",
        "cli_year_from": "只检索该年份及以后（如 2015）",
        "cli_year_to": "只检索该年份及以前（如 2024）",
        "cli_sort": "检索排序（默认 relevance）",
        "cli_search_header": "检索「{query}」：共 {n} 条候选",
        "cli_search_hint": "用 --pick 选择要下载的序号，例如：--pick 1,3",
        "cli_search_empty": "没有找到匹配的文献",
        "cli_search_pick_none": "--pick 没有选中任何有效序号",
        "cli_search_failed": "检索失败: {e}",
        "cli_pick_selected": "已选中 {n} 条（序号 {picks}），开始处理",
        "cli_file_missing": "文件不存在: {path}",
        "cli_no_doi": "未找到任何 DOI",
        "cli_preview_header": "预览（共 {n} 篇，命名方式: {naming}）",
        "cli_banner_title": "Sci-Hub 文献下载",
        "cli_banner_meta": "总计: {n} 篇 | 输出: {outdir} | 命名: {naming}",
        "cli_summary": "完成: 成功 {saved} | 跳过 {skipped} | 未收录 {not_found} | 失败 {failed} | 总计 {total}",
    },
    "en": {
        "status_pending": "Pending",
        "status_queued": "Queued",
        "status_metadata": "Fetching title",
        "status_searching": "Searching",
        "status_downloading": "Downloading",
        "status_saved": "Done",
        "status_skipped": "Skipped",
        "status_failed": "Failed",
        "status_not_found": "Not found",
        "status_network_error": "Network error",
        "status_captcha": "Captcha blocked",
        "status_no_pdf": "No PDF link",
        "status_bad_pdf": "Bad content",
        "status_cancelled": "Cancelled",
        "naming_title": "Title",
        "naming_doi": "DOI",
        "naming_year": "Year - Title",
        "naming_author": "Author - Year - Title",
        "naming_custom": "Custom",
        "doi_url": "DOI / URL:",
        "add": "Add",
        "import_file": "Import txt/md",
        "clear": "Clear",
        "count_items": "{n} items",
        "col_title": "Title",
        "col_status": "Status",
        "col_file": "File",
        "download_options": "Download options",
        "save_to": "Save to:",
        "browse": "Browse…",
        "naming": "Naming:",
        "custom_template": "Custom template:",
        "template_hint": "Available: {title} {doi} {year} {author} {journal}",
        "concurrency": "Concurrency:",
        "start": "Start",
        "stop": "Stop",
        "ready": "Ready",
        "menu_language": "Language",
        "unrecognized": "Unrecognized",
        "invalid_doi": "Not a valid DOI:\n{raw}",
        "import_failed": "Import failed",
        "import_title": "Import DOI list",
        "filetype_list": "Reference list",
        "filetype_text": "Text files",
        "filetype_md": "Markdown",
        "filetype_json": "JSON",
        "filetype_all": "All files",
        "imported": "Imported {added} ({n} duplicates skipped)",
        "info": "Info",
        "need_doi": "Please add or import a DOI first",
        "starting": "Starting…",
        "stopping": "Stopping…",
        "engine_error": "Engine error: {e}",
        "error": "Error: {val}",
        "done_summary": "Done: saved {saved} | skipped {skipped} | not found {not_found} | failed {failed} | total {total}",
        "cancelled": "Cancelled",
        "done": "Done",
        "save_dir_title": "Select output directory",
        "msg_prepare": "Preparing",
        "msg_query_meta": "Fetching title from CrossRef…",
        "msg_exists": "Already exists, skipped",
        "msg_search": "Searching Sci-Hub…",
        "msg_not_found": "Not available on Sci-Hub",
        "msg_captcha": "Blocked by captcha",
        "msg_network": "Network connection failed",
        "msg_no_pdf": "No PDF link found",
        "msg_downloading": "Downloading…",
        "msg_bad_pdf": "Content is not a valid PDF",
        "msg_download_fail": "Download connection failed",
        "msg_download_error": "Download failed",
        "msg_saved": "Done {kb} KB",
        # 检索（搜索论文页）
        "tab_tasks": "Tasks",
        "tab_search": "Search papers",
        "search_label": "Title / keywords:",
        "search_button": "Search",
        "search_years": "Year:",
        "search_sort": "Sort:",
        "sort_relevance": "Relevance",
        "sort_published": "Newest",
        "search_rows": "Rows:",
        "col_sel": "Pick",
        "col_author": "Author",
        "col_year": "Year",
        "col_journal": "Journal",
        "col_avail": "Sci-Hub",
        "col_note": "Note",
        "select_all": "Select available",
        "select_none": "Clear selection",
        "add_selected": "Add to task list",
        "open_doi": "Open DOI",
        "search_hint": "Double-click a row to open its DOI page in the browser",
        "search_need_query": "Enter a title or keyword first",
        "search_searching": "Searching CrossRef…",
        "search_hits": "{n} results — checking Sci-Hub availability…",
        "search_done": "Search finished: {n} results",
        "search_stopped": "Search stopped",
        "search_empty": "No matching papers found",
        "search_failed_title": "Search failed",
        "search_failed": "Search failed: {e}",
        "search_none_selected": "Tick the papers you want first",
        "search_added": "Added {added} to the task list ({skipped} duplicates skipped)",
        "search_note_in_list": "In list",
        "search_note_no_doi": "No DOI",
        "search_row_blocked": "Not selectable: {title}",
        "search_no_doi_open": "This entry has no DOI to open",
        "avail_unknown": "Unconfirmed",
        "avail_checking": "Checking…",
        "avail_available": "Available",
        "avail_not_found": "Not found",
        "cli_description": "Sci-Hub literature downloader — download PDF by DOI",
        "cli_epilog_examples": "Examples:",
        "cli_epilog_naming": "Naming modes",
        "cli_doi": "Single DOI",
        "cli_batch": "Path to a JSON batch file",
        "cli_markdown": "Extract DOIs from a Markdown reference list",
        "cli_file": "Import file (txt/md/json, auto-detected)",
        "cli_title": "Paper title (used with --doi)",
        "cli_outdir": "Output directory (default ./papers)",
        "cli_naming": "Naming mode (default: last used or title)",
        "cli_template": "Used with --naming custom",
        "cli_concurrency": "Concurrency 1-8 (default 2)",
        "cli_plain": "Parse md files line-by-line as plain text",
        "cli_no_metadata": "Do not query CrossRef for titles",
        "cli_dry_run": "Preview only, do not download",
        "cli_lang": "Interface language (zh / en)",
        "cli_search": "Search CrossRef by title/keywords (use --pick to choose)",
        "cli_search_limit": "Number of results (default 20, max 100)",
        "cli_pick": "Download the given result numbers, e.g. 1,3 or 1-3",
        "cli_year_from": "Only papers published in this year or later",
        "cli_year_to": "Only papers published in this year or earlier",
        "cli_sort": "Result order (default relevance)",
        "cli_search_header": "Search \"{query}\": {n} candidates",
        "cli_search_hint": "Pick the numbers to download, e.g. --pick 1,3",
        "cli_search_empty": "No matching papers found",
        "cli_search_pick_none": "--pick selected no valid result number",
        "cli_search_failed": "Search failed: {e}",
        "cli_pick_selected": "Selected {n} result(s) ({picks}), starting",
        "cli_file_missing": "File not found: {path}",
        "cli_no_doi": "No DOI found",
        "cli_preview_header": "Preview ({n} papers, naming: {naming})",
        "cli_banner_title": "Sci-Hub Downloader",
        "cli_banner_meta": "Total: {n} | Output: {outdir} | Naming: {naming}",
        "cli_summary": "Done: saved {saved} | skipped {skipped} | not found {not_found} | failed {failed} | total {total}",
    },
}


def get_lang() -> str:
    """当前语言代码（``zh`` 或 ``en``）。"""
    return _current


def set_lang(lang: str) -> None:
    """切换语言；未知代码会被忽略，保持原语言不变。"""
    global _current
    if lang in _STR:
        _current = lang


def tr(key: str, **kwargs) -> str:
    """取当前语言下的文案，可选地用 ``kwargs`` 做占位符替换。"""
    text = _STR.get(_current, _STR["zh"]).get(key, _STR["zh"].get(key, key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def status_label(status: str) -> str:
    """状态码 → 当前语言的状态文案；未知状态原样返回。"""
    return tr(_STATUS_KEYS.get(status, status))


def naming_labels() -> dict[str, str]:
    """命名模式 → 当前语言的标签（供 GUI 单选按钮用）。"""
    return {k: tr(key) for k, key in _NAMING_KEYS.items()}


def search_sort_labels() -> dict[str, str]:
    """检索排序 → 当前语言的标签（供 GUI 单选按钮用）。"""
    return {k: tr(key) for k, key in _SORT_KEYS.items()}


def search_avail_label(state: str) -> str:
    """Sci-Hub 收录状态 → 当前语言的文案；未知状态原样返回。"""
    return tr(_AVAIL_KEYS.get(state, state))
