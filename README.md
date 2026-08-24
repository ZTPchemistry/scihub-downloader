# Sci-Hub Downloader

跨平台（Windows / Linux）的文献批量下载器，带图形界面与命令行两种入口，**零第三方运行时依赖**——克隆下来 `python main.py` 即可运行。

根据 DOI 从 Sci-Hub 下载论文 PDF，自动按标题（或 DOI / 作者-年份-标题等模板）命名，支持从 `txt` / `md` / `json` 文件批量导入。

---

## ✨ 功能

- 🖥 **图形界面**：添加 DOI、导入文件、选择保存目录、切换命名方式、实时进度与停止
- 📚 **批量导入**：`txt` / `md` 每行一个 DOI 或 DOI 网址；`json` 支持 `[{"doi": "...", "title": "..."}]`
- 🏷 **多种命名**：标题 / DOI / 年份-标题 / 作者-年份-标题 / 自定义模板
- 🔎 **元数据补全**：纯 DOI 时自动调 CrossRef 查标题/作者/年份，失败自动回退
- 🛡 **稳健下载**：多镜像自动择优、流式写入 + `%PDF` 文件头校验、去重与同名冲突处理、跨平台安全文件名（字节级截断 + Windows 保留名）
- ⚡ **零依赖**：只用 Python 标准库（`tkinter` + `urllib`）

## 📦 安装

要求 Python 3.10+。Linux 还需安装 Tk：

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

```bash
git clone https://github.com/ZTPchemistry/scihub-downloader.git
cd scihub-downloader
python main.py          # 启动 GUI
```

或作为包安装：

```bash
pip install .
scihub-dl --doi 10.1063/1.1674820 --outdir ./papers   # CLI
scihub-dl-gui                                          # GUI
```

## 🖥 图形界面

```
python main.py
```

1. 在顶部输入框粘贴 DOI 或链接（如 `10.1063/1.1674820` 或 `https://doi.org/10.1063/1.1674820`），点「添加」；
2. 或点「导入 txt/md」选择一个文件批量导入（每行一个 DOI / DOI 网址）；
3. 选择保存目录与命名方式；
4. 点「开始下载」，随时可「停止」。

## ⌨️ 命令行

```
python main.py --doi 10.1063/1.1674820 --title "WCA Theory" --outdir ./papers
python main.py --file dois.txt --outdir ./papers
python main.py --file 文献汇总.md --naming author --outdir ./papers
python main.py --batch batch.json --dry-run
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--doi` | 单个 DOI |
| `--file` | 导入 `txt` / `md` / `json`（自动识别） |
| `--markdown` | 结构化解析中文文献汇总 Markdown |
| `--batch` | JSON 批量文件 |
| `--outdir` | 输出目录（默认 `./papers`） |
| `--naming` | `title` / `doi` / `year` / `author` / `custom` |
| `--template` | 配合 `--naming custom` 使用 |
| `--concurrency` | 并发数 1–8（默认 2） |
| `--no-metadata` | 不查 CrossRef 补全标题 |
| `--plain` | md 文件按纯文本逐行解析 |
| `--dry-run` | 仅预览文件名，不下载 |

### 命名模板

模板可用占位符：`{title}` `{doi}` `{year}` `{author}` `{journal}`

```bash
python main.py --file dois.txt --naming custom --template "{year} - {author} - {title}"
```

## 🧪 测试

```bash
python -m unittest discover -s tests -v
```

## 📦 打包（可选）

```bash
pip install pyinstaller
python build.py            # 当前平台，GUI 版单文件
python build.py --console  # 带控制台，可跑 CLI
python build.py --one-dir  # 目录模式（启动更快）
```

产物在 `dist/`：

| 平台 | 产物 | 说明 |
| --- | --- | --- |
| Windows | `dist/SciHubDownloader.exe` | 双击即用 |
| Linux | `dist/SciHubDownloader`（二进制）<br>`dist/SciHubDownloader-<版本>-linux-x86_64.tar.gz` | tar.gz 解压后 `./install.sh` 装到 `~/.local`，应用菜单可见 |

> ⚠️ **PyInstaller 不支持交叉编译**：Windows 版要在 Windows 上构建，Linux 版要在 Linux 上构建（在 Linux 上跑同一命令 `python build.py` 即可，脚本会自动识别平台并额外生成 `.desktop` 桌面入口 + 安装脚本）。Linux 构建机需装 `python3-tk` 与 `python3-venv`，产物 glibc 版本取决于构建机，建议在较老发行版上构建以扩大兼容范围。

## ⚙️ 配置

配置保存在（自动创建）：

- Windows：`%APPDATA%\SciHubDownloader\config.json`
- Linux：`$XDG_CONFIG_HOME/scihub-downloader/config.json`

可在其中设置 `crossref_mailto`（填入你的邮箱后，CrossRef 会把你纳入礼貌请求池，速度更快更稳；见下方说明）。

### 邮箱（`crossref_mailto`）的作用？

本工具在「按标题命名」且导入的是纯 DOI 列表时，会调用 CrossRef 的公开 API 查询文献标题/作者/年份。CrossRef 的[礼貌池（polite pool）](https://github.com/CrossRef/rest-api-doc#etiquette)约定：请求的 `User-Agent` 里带上 `mailto:`（邮箱）和/或项目链接的，会被路由到更快更稳的服务器池，CrossRef 也方便在检测到异常时联系你。

- **填邮箱（推荐）**：进礼貌池，查询更快、更少被限流。
- **不填**：仍可正常查询，走公共池，偶尔更慢或被限流。

填的是你自己的邮箱，仅用于上述目的，不会上传或用于任何其他用途。改成你的邮箱即可：

```json
{ "crossref_mailto": "you@example.com" }
```

## ⚠️ 声明

- Sci-Hub 的可用性、合法性在不同地区存在差异，镜像地址也可能变动；若全部镜像失效，请自行更新 `scihub_dl/mirrors.py` 中的 `DEFAULT_MIRRORS`。
- 请优先通过所在机构的正规订阅渠道获取文献。本工具仅供个人学术检索使用，请遵守当地法律，**尊重版权**，使用者自行承担合规责任。

## 📁 项目结构

```
scihub_dl/
  assets/        软件图标文件夹
  gui/           Tkinter 图形界面
  __init__.py    包初始化
  __main__.py    应用打包入口
  doi.py         DOI 识别与规范化
  sanitize.py    跨平台安全文件名
  naming.py      命名模板
  net.py         HTTP 会话（双 SSL 上下文）+ 速率限制
  models.py      跨模块共享的数据结构
  mirrors.py     镜像列表与择优
  metadata.py    CrossRef 元数据补全
  parsers.py     txt/md/json 导入解析
  downloader.py  下载引擎（UI 无关）
  config.py      配置持久化
  cli.py         命令行入口
 tests/           测试用脚本
```

## 历史版本

  v1.0.0  初始版本；
  v1.0.1  修复导入DOI后的界面显示问题，增加下载失败原因提示；

## 📄 License

[MIT](LICENSE)
