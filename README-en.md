# Sci-Hub Downloader

[English](README-en.md) | [中文](README.md)

A cross-platform (Windows / Linux) batch literature downloader with both a GUI and a CLI, **zero third-party runtime dependencies** — clone it and run `python main.py`.

Downloads paper PDFs from Sci-Hub by DOI, automatically names them by title (or DOI / author-year-title templates), and supports batch import from `txt` / `md` / `json` files. If all you remember is the title, the **Search papers** tab looks it up on CrossRef and adds the hits to the download queue. The interface supports both Chinese and English.

---

## ✨ Features

- 🖥 **GUI**: add DOIs, import files, choose output directory, switch naming modes, live progress and stop
- 🔍 **Title search**: query CrossRef with a title or keywords, get candidates with DOI, author, year and journal, and add the ticked ones to the task list in one click
- 📡 **Availability check**: after a search, each result is checked against Sci-Hub in the background (available / not found / unconfirmed), so you don't find out only after a failed download
- 📚 **Batch import**: `txt` / `md` with one DOI or DOI URL per line; `json` supports `[{"doi": "...", "title": "..."}]`
- 🏷 **Multiple naming**: Title / DOI / Year-Title / Author-Year-Title / custom template
- 🔎 **Metadata completion**: pure-DOI lists auto-query CrossRef for title/author/year, with graceful fallback
- 🛡 **Robust downloads**: multi-mirror auto-selection, streaming writes + `%PDF` header validation, dedup and name-conflict handling, cross-platform safe filenames (byte-level truncation + Windows reserved names)
- ⚡ **Zero dependencies**: Python standard library only (`tkinter` + `urllib`)
- 🌐 **Bilingual UI**: switch between Chinese and English (GUI menu or `--lang` on the CLI)

## 📦 Installation

Requires Python 3.10+. Linux also needs Tk:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

```bash
git clone https://github.com/ZTPchemistry/scihub-downloader.git
cd scihub-downloader
python main.py          # launch GUI
```

Or install as a package:

```bash
pip install .
scihub-dl --doi 10.1063/1.1674820 --outdir ./papers   # CLI
scihub-dl-gui                                          # GUI
```

## 🖥 GUI

```
python main.py
```

The window has two tabs — **Tasks** and **Search papers** — with a shared download-options bar (output directory / naming / concurrency / start-stop) below them.

### Tasks tab

1. Paste a DOI or URL (e.g. `10.1063/1.1674820` or `https://doi.org/10.1063/1.1674820`) into the top input box and click **Add**;
2. Or click **Import txt/md** to batch-import a file (one DOI / DOI URL per line);
3. Choose the output directory and naming mode;
4. Click **Start** to download; you can **Stop** at any time.

### Search papers tab (when you only remember the title)

1. Enter a title or keywords — a fragment is fine, e.g. `WCA perturbation theory` — and optionally restrict the year range, switch the order (relevance / newest) or change the number of results;
2. Click **Search**; the result table lists title / author / year / journal / DOI;
3. Once results arrive, each row is checked against Sci-Hub in the background: the `Sci-Hub` column goes from *Checking…* to *Available* / *Not found* / *Unconfirmed*. Press **Stop** if you don't want to wait;
4. Tick the papers you want in the first column (`☐`), or use **Select available**, then click **Add to task list**;
5. Switch to the **Tasks** tab (or just use the shared bar below) and click **Start**.

Notes:

- **Rows you cannot tick**: entries without a DOI (some book chapters / preprints) can't enter the download pipeline and show `—` with a reason; rows confirmed as *Not found* on Sci-Hub are blocked as well, to save a pointless request. Rows marked *Unconfirmed* (captcha, network error, no PDF link on the mirror) remain selectable — the tool does not draw conclusions for you.
- **Double-click a row** to open its DOI page in your browser for a manual check.
- **The availability check is only a hint**: the real download resolves the PDF link independently. Probe results are never written to config and cannot change the mirror priority used for downloads — the probe keeps its own mirror pool, rate limiter and HTTP session.
- **Searching uses CrossRef**, with a trimmed field list (title/author/year/journal/DOI) that makes the response two orders of magnitude smaller than the default payload.

Use the **Language** menu to switch between Chinese and English.

## ⌨️ Command Line

```
python main.py --doi 10.1063/1.1674820 --title "WCA Theory" --outdir ./papers
python main.py --file dois.txt --outdir ./papers
python main.py --file refs.md --naming author --outdir ./papers
python main.py --batch batch.json --dry-run

python main.py --search "WCA perturbation theory"                       # list candidates only
python main.py --search "WCA perturbation theory" --pick 1 --outdir ./papers
python main.py --search "sticky hard spheres" --year-from 2010 --sort published --pick 1-3 --dry-run
```

Common options:

| Option | Description |
| --- | --- |
| `--doi` | A single DOI |
| `--file` | Import `txt` / `md` / `json` (auto-detected) |
| `--markdown` | Structured parsing of Markdown reference lists |
| `--batch` | JSON batch file |
| `--search` | Search CrossRef by title/keywords and list numbered candidates |
| `--pick` | With `--search`: the result numbers to download, e.g. `1,3` or `1-3` |
| `--search-limit` | Number of results (default 20, max 100) |
| `--year-from` / `--year-to` | Restrict the search to a publication-year range |
| `--sort` | Result order: `relevance` (default) / `published` |
| `--outdir` | Output directory (default `./papers`) |
| `--naming` | `title` / `doi` / `year` / `author` / `custom` |
| `--template` | Used with `--naming custom` |
| `--concurrency` | Concurrency 1–8 (default 2) |
| `--no-metadata` | Do not query CrossRef for titles |
| `--plain` | Parse md files line-by-line as plain text |
| `--dry-run` | Preview filenames only, no download |
| `--lang` | Interface language (`zh` / `en`) |

`--search` only lists candidates: without `--pick` it prints the results and exits (status 0); with `--pick` it turns the numbered hits into the very same download flow as before (naming, preview, summary and exit codes are unchanged). The CLI deliberately skips the Sci-Hub availability probe to keep scripts fast.

### Naming templates

Available placeholders: `{title}` `{doi}` `{year}` `{author}` `{journal}`

```bash
python main.py --file dois.txt --naming custom --template "{year} - {author} - {title}"
```

## 🧪 Tests

```bash
python -m unittest discover -s tests -v
```

## 📦 Packaging (optional)

```bash
pip install pyinstaller
python build.py              # current platform, single-file GUI build
python build.py --console    # with console, can run the CLI
python build.py --one-dir    # directory mode: fastest startup
python build.py --benchmark  # time the artifact's startup after building
```

The build script already optimises for **runtime efficiency** — the reasoning for each flag lives in `build.py`:

| Flag | Effect |
| --- | --- |
| `--optimize 2` | Compile bytecode with `-OO` (docstrings and `assert`s dropped): smaller bundle, faster imports (skipped automatically on PyInstaller versions without the flag) |
| `--noupx` | No UPX: it only saves size while slowing startup, and it very often trips antivirus heuristics |
| `--exclude-module` | Keeps out unused stdlib (`unittest` / `pydoc` / `sqlite3` / `asyncio` / `xml` / `multiprocessing`…) and third-party libraries that merely happen to be installed on the build machine (`numpy` / `pandas` / `PIL`…) — the single-file build unpacks less on every launch |
| `--strip` (Linux only) | Strips shared-library symbols, shrinking what has to be unpacked |

**Use `--one-dir` for the fastest startup**: single-file mode unpacks the whole ~12 MB archive into a temp directory on *every* launch (and antivirus scans it the first time), while directory mode just reads from disk. Add `--benchmark` to measure it yourself. Measured here (Windows / Python 3.14): with the optimisations above, the single-file build is 12.1 MB and directory mode starts in ~0.15 s.

> Use `--no-optimize` to disable the bytecode optimisation when debugging something odd (`-OO` also removes `assert`s).

Artifacts are in `dist/`:

| Platform | Artifact | Notes |
| --- | --- | --- |
| Windows | `dist/SciHubDownloader.exe` | Double-click to run |
| Linux | `dist/SciHubDownloader` (binary)<br>`dist/SciHubDownloader-<version>-linux-x86_64.tar.gz` | Unpack the tar.gz then `./install.sh` installs to `~/.local`, visible in the app menu |

> ⚠️ **PyInstaller does not support cross-compilation**: build the Windows version on Windows and the Linux version on Linux (run the same `python build.py` on Linux — the script auto-detects the platform and additionally generates a `.desktop` entry + installer). Linux build machines need `python3-tk` and `python3-venv`; the artifact's glibc version depends on the build machine, so building on an older distro broadens compatibility.

## ⚙️ Configuration

Config is stored at (auto-created):

- Windows: `%APPDATA%\SciHubDownloader\config.json`
- Linux: `$XDG_CONFIG_HOME/scihub-downloader/config.json`

You can set `crossref_mailto` here (filling in your email puts you in CrossRef's polite pool for faster, more stable queries; see below).

### What is the `crossref_mailto` email for?

When naming by title and importing a pure-DOI list, this tool queries CrossRef's public API for the paper's title/author/year. CrossRef's [polite pool](https://github.com/CrossRef/rest-api-doc#etiquette) convention: requests whose `User-Agent` carries a `mailto:` (email) and/or project link are routed to a faster, more stable server pool, and CrossRef can reach you if it detects anomalies.

- **Set an email (recommended)**: enter the polite pool for faster, less-throttled queries.
- **Leave it empty**: still works, goes through the public pool, occasionally slower or throttled.

It is your own email, used only for the purpose above — never uploaded or used for anything else. Just set it to your email:

```json
{ "crossref_mailto": "you@example.com" }
```

## ⚠️ Disclaimer

- Sci-Hub's availability and legality vary by region, and mirror addresses may change; if all mirrors fail, update `DEFAULT_MIRRORS` in `scihub_dl/mirrors.py` yourself.
- Please prefer your institution's legitimate subscription channels. This tool is for personal academic research only — comply with local laws, **respect copyright**, and the user bears full compliance responsibility.

## 📁 Project structure

```
scihub_dl/
  assets/        app icon folder
  gui/           Tkinter GUI
  __init__.py    package init
  __main__.py    app entry point
  doi.py         DOI recognition and normalization
  sanitize.py    cross-platform safe filenames
  naming.py      naming templates
  net.py         HTTP session (dual SSL contexts) + rate limiting
  models.py      shared data structures
  mirrors.py     mirror list and selection
  metadata.py    CrossRef metadata completion
  search.py      title search (CrossRef) + Sci-Hub availability probe
  parsers.py     txt/md/json import parsing
  downloader.py  download engine (UI-independent)
  config.py      config persistence
  i18n.py        Chinese / English localization
  cli.py         command-line entry point
 tests/          test scripts
```

## Version history

    v1.0.0  initial release;
    v1.0.1  fix the UI display issue after importing DOIs, add download-failure reason hints;
    v1.0.2  fix the Linux packaging failure;
    v1.1.0  a new function for switching between Chinese and English has been added;
    v1.2.0  search papers by title (CrossRef search + Sci-Hub availability probe; GUI tab and CLI `--search/--pick`);

## 📄 License

[MIT](LICENSE)
