# Sci-Hub Downloader

[English](README-en.md) | [中文](README.md)

A cross-platform (Windows / Linux) batch literature downloader with both a GUI and a CLI, **zero third-party runtime dependencies** — clone it and run `python main.py`.

Downloads paper PDFs from Sci-Hub by DOI, automatically names them by title (or DOI / author-year-title templates), and supports batch import from `txt` / `md` / `json` files. The interface supports both Chinese and English.

---

## ✨ Features

- 🖥 **GUI**: add DOIs, import files, choose output directory, switch naming modes, live progress and stop
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

1. Paste a DOI or URL (e.g. `10.1063/1.1674820` or `https://doi.org/10.1063/1.1674820`) into the top input box and click **Add**;
2. Or click **Import txt/md** to batch-import a file (one DOI / DOI URL per line);
3. Choose the output directory and naming mode;
4. Click **Start** to download; you can **Stop** at any time.

Use the **Language** menu to switch between Chinese and English.

## ⌨️ Command Line

```
python main.py --doi 10.1063/1.1674820 --title "WCA Theory" --outdir ./papers
python main.py --file dois.txt --outdir ./papers
python main.py --file refs.md --naming author --outdir ./papers
python main.py --batch batch.json --dry-run
```

Common options:

| Option | Description |
| --- | --- |
| `--doi` | A single DOI |
| `--file` | Import `txt` / `md` / `json` (auto-detected) |
| `--markdown` | Structured parsing of Markdown reference lists |
| `--batch` | JSON batch file |
| `--outdir` | Output directory (default `./papers`) |
| `--naming` | `title` / `doi` / `year` / `author` / `custom` |
| `--template` | Used with `--naming custom` |
| `--concurrency` | Concurrency 1–8 (default 2) |
| `--no-metadata` | Do not query CrossRef for titles |
| `--plain` | Parse md files line-by-line as plain text |
| `--dry-run` | Preview filenames only, no download |
| `--lang` | Interface language (`zh` / `en`) |

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
python build.py            # current platform, single-file GUI build
python build.py --console  # with console, can run the CLI
python build.py --one-dir  # directory mode (faster startup)
```

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

## 📄 License

[MIT](LICENSE)
