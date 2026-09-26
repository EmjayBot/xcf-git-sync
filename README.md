# XCF Sync — GIMP XCF → GitHub Auto-Sync

### `xcf-git-sync` — Watch `.xcf` files, export only the layers you need as PNG, and auto-push.

[![PyPI](https://img.shields.io/pypi/v/xcf-git-sync)](https://pypi.org/project/xcf-git-sync/) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)

Built for large worldbuilding maps and multi-layer XCFs. GIMP is great for
drawing world maps, and Git is great for versioning them — but a GIMP `.xcf` is
a big binary blob you can't diff, and your maps app can't read it. XCF Sync
watches your XCF and syncs only the tagged layers you want (like `[GH] Borders`,
`[GH] Rivers`) as PNGs. Push the XCF, and the PNGs update themselves.

## How it works

```
your.xcf --(watch)--> filter layers --> PNGs in assets/xcf_layers/ --> git commit/push
```

- GIMP 2.10 files (`gimp xcf v011` and earlier) are parsed directly with
  `gimpformats` — no GIMP install needed.
- GIMP 3 files (`v012+`, e.g. `v019`) are exported by driving headless GIMP.
- One XCF maps to one output folder; re-exports overwrite their own PNGs.

## Features

- **Selective export** by tag, group, name, or regex.
- **GIMP 2.10 and GIMP 3 support** — fast `gimpformats` path for v011, headless
  GIMP fallback for v012+.
- **Large-map friendly** — each layer is written as its own PNG instead of one
  giant composite, so pipelines can consume layers individually.
- **Watch mode** — instant local export when you save in GIMP.
- **Git auto-sync** — auto-commit and push changed layers.
- **Cloud safety net** — a GitHub Actions workflow that syncs even when no one
  is running the watcher locally.

## Requirements

- Python 3.9+
- Git
- GIMP 2.10+ **only** if you use GIMP 3 XCFs (auto-detected, or forced with
  `--via-gimp`). Auto-detect checks `PATH`, `C:\Program Files\GIMP *`,
  `%LOCALAPPDATA%\Programs\GIMP *`, and Flatpak.

## Install

```bash
pip install xcf-git-sync
# or install it isolated so it doesn't touch your project environment:
pipx install xcf-git-sync
```

Verify:

```bash
xcf-git-sync --version
```

To work on the tool itself, install from a clone instead:

```bash
git clone https://github.com/EmjayBot/xcf-git-sync.git
cd xcf-git-sync
pip install -e ".[dev]"
```

## Your first export

Work from your art repo (the folder with `.git` in it).

**1. Inspect the layer tree.** Before exporting, see every layer and preview
which ones your filters would keep:

```bash
xcf-git-sync --xcf maps/source/urth.xcf --list-layers
```

Each line is `Group/Sub/Layer`, with `(hidden)` and `[keep]` marks. This step
uses headless GIMP, so GIMP must be installed even for a GIMP 2.10 file.

**2. Export once.** `--once` exports and exits without watching:

```bash
xcf-git-sync --xcf maps/source/urth.xcf --repo . --once
```

PNGs land in `assets/xcf_layers/urth/` by default. Nothing is committed yet, so
open them and check the result.

**3. Keep only the layers you want.** XCFs usually contain sketches, references,
and UI layers you don't want to ship. Combine filters (all comma-separated):

```bash
xcf-git-sync --xcf maps/source/urth.xcf --repo . --once \
  --include "National,Cities,Sub-National,Political,Ocean" \
  --exclude "Sketch,WIP"
```

**4. Watch and auto-push.** Drop `--once` to keep running:

```bash
xcf-git-sync --xcf maps/source/urth.xcf --repo . --push
```

Now every time GIMP saves the XCF, the matching layers are re-exported,
committed, and pushed. Leave it running while you draw; press Ctrl+C to stop.
To cover a whole folder (recursively), use `--watch-dir ./maps/source` instead
of `--xcf`.

## Output layout

For `maps/source/urth.xcf` with the default output root:

```
assets/xcf_layers/
└── urth/
    ├── National.png
    ├── Cities.png
    ├── Political/
    │   └── Borders.png
    └── _flattened.png
```

- The folder is the XCF's filename (slugified), so two XCFs never collide.
- Layer groups become subfolders.
- Names are **slugified**: characters that aren't letters, digits, `_`, `-`, or
  space are dropped, runs of spaces become `-`, and names are capped at 100
  chars. `National #2` → `National-2.png`.
- If two different layers slugify to the same name in one folder, the tool adds
  `-2`, `-3`, and so on. A re-export overwrites the file it made before.
- `_flattened.png` is the merged visible composite. Skip it with `--no-flatten`.

## Filtering layers

Filters are applied in this order, and `--include*` only kicks in when you set
it (otherwise everything visible is eligible):

| Flag | Config key | Effect |
| --- | --- | --- |
| `--tag-prefix "[GH]"` | `tag_prefix` | keep only layers whose **name starts with** the prefix |
| `--group "Sprites,UI"` | `group` | keep only layers whose **group path** starts with or contains one of these |
| `--include "Hero,Logo"` | `include` | if set, keep only layers whose name **or** full `Group/Layer` path contains one of these substrings (case-insensitive) |
| `--include-regex ".*_export$"` | `include_regex` | same idea, but each entry is a Python regex (`re.search`, case-sensitive) |
| `--exclude "Sketch,WIP"` | `exclude` | drop layers matching these substrings (case-insensitive) |
| `--exclude-regex "^temp"` | `exclude_regex` | drop layers matching these regexes |
| `--no-only-visible` | `only_visible: false` | include hidden layers (default is visible only) |

Notes:

- Order is: visibility → tag prefix → group → include → exclude. Exclude always
  wins.
- `--include` is a substring match, not exact: `Hero` also matches `HeroBackup`.
  Use `--include-regex "^Hero$"` for exact names.
- Multiple values are comma-separated, including regexes:
  `--include-regex ".*_export$,^UI_"`.

Always confirm with `--list-layers` plus the same filter flags before a long run.

## Using a config file

Copy `config.example.yaml` to `config.yaml` (it's git-ignored) and run with
`--config`. CLI flags override the file.

```yaml
watch:
  xcf: ./maps/source/urth.xcf     # or watch_dir: ./maps/source
  # watch_dir: ./art
  repo: ./
  out: ./assets/xcf_layers
  push: true                      # auto_push: true is an alias
  only_visible: true
  no_flatten: false
  debounce: 1.5
  tag_prefix: ""
  include: "National,Cities,Political,Ocean"
  exclude: "Sketch,WIP"
  # include_regex: ".*_export$"
  # exclude_regex: "^temp"
  # group: "Sprites,UI"
  via_gimp: false
  timeout: 300
  # gimp_bin: "flatpak run org.gimp.GIMP"
```

```bash
xcf-git-sync --config config.yaml
```

`xcf` or `watch_dir` is required. The `github:` section in the example
(`branch`, `lfs`) is reserved and not wired up yet.

## GIMP 3 support

The tool reads the XCF header to decide:

- `v011` and earlier → parsed directly with `gimpformats` (fast, no GIMP needed).
- `v012+` (GIMP 3, e.g. `v019`) → exported via headless GIMP with
  `--batch-interpreter=python-fu-eval`. Verified on GIMP 3.2.6 and 2.10.32.

Force the GIMP path for any file (useful for testing) with `--via-gimp`:

```bash
xcf-git-sync --xcf design.xcf --repo . --once --via-gimp
```

If GIMP isn't found, or lives somewhere unusual, point at it explicitly. The
value may be a full path or a compound command:

```bash
xcf-git-sync --xcf design.xcf --repo . --once \
  --gimp-bin "flatpak run org.gimp.GIMP"
```

The environment variable `XCF_GIT_SYNC_GIMP_BIN` does the same.

## Auto-sync in the cloud (GitHub Actions)

The local watcher is instant, but it only runs while someone runs it. As a
safety net, run the export in CI: any push touching the XCF regenerates the
PNGs and commits them back.

1. Copy `examples/urthmaps-sync.yaml` into your art repo as
   `.github/workflows/xcf-sync.yaml`.
2. Adjust `XCF_PATH`, `FILTERS`, and branch names at the top.
3. Push an XCF change — the PNGs update themselves a few minutes later.

It installs headless GIMP 3 from the official Flatpak, so even GIMP 3 XCFs
work. The `paths:` trigger means the bot's own PNG commit never re-triggers the
workflow (no loops). Free on public repos.

> Why not Cloudflare? Workers can't run GIMP — no custom native binaries, tight
> CPU/memory limits, no GTK stack. The compute has to live where GIMP can run
> (GitHub runners, a VM, or a container).

## Command reference

| Flag | Description |
| --- | --- |
| `--xcf PATH` | Single XCF to export / watch. |
| `--watch-dir DIR` | Export all `*.xcf` under DIR, then watch it recursively. |
| `--repo DIR` | Git repo root (default `.`). Only files inside it are committed. |
| `--out DIR` | PNG output root. Default `<repo>/assets/xcf_layers`. |
| `--once` | Export once and exit (no watcher). |
| `--push` | `git push` after each commit. |
| `--config FILE` | Load a YAML config file (CLI flags override it). |
| `--list-layers` | Print the layer tree (via headless GIMP) and exit. |
| `--tag-prefix S` | Keep only layers whose name starts with `S`. |
| `--include LIST` | Comma-separated substrings to include. |
| `--include-regex LIST` | Comma-separated regexes to include. |
| `--exclude LIST` | Comma-separated substrings to exclude. |
| `--exclude-regex LIST` | Comma-separated regexes to exclude. |
| `--group LIST` | Only layers inside these groups. |
| `--no-only-visible` | Include hidden layers. |
| `--no-flatten` | Skip `_flattened.png`. |
| `--debounce SEC` | Seconds to ignore rapid saves (default 1.5). |
| `--via-gimp` | Always export via headless GIMP. |
| `--gimp-bin CMD` | GIMP binary/command override. |
| `--timeout SEC` | Headless GIMP timeout (default 300). |
| `--version` | Print the version. |

## Troubleshooting

- **`needs headless GIMP to export, but no GIMP binary was found`** — install
  GIMP 2.10+ / GIMP 3, or pass `--gimp-bin`.
- **`GIMP batch export produced nothing`** — run `--list-layers` first to confirm
  GIMP can open the file. The last 15 lines of GIMP output are printed to help.
- **Timeout on the first run** — GIMP's first launch builds caches. Retry, or
  raise `--timeout`.
- **`is not a git repo, skipping commit`** — `--repo` points at the wrong folder.
- **`Push failed`** — check the remote and credentials. On Windows, Git
  Credential Manager is the usual fix; on CI the `contents: write` permission
  and `GITHUB_TOKEN` do it.
- **A hidden layer didn't export** — hidden layers are skipped by default; add
  `--no-only-visible`.
- **A GIMP 3 file fails with no GIMP installed** — `gimpformats` can't read
  `v012+` XCFs, so GIMP 3 files always need headless GIMP. Install GIMP or point
  `--gimp-bin` at it.

## Security notes

- **Only open XCF files you trust.** The whole file is parsed (by `gimpformats`
  or, for GIMP 3 files, inside headless GIMP). A crafted XCF can crash the tool
  or target a parser bug, so don't point it at files from untrusted sources.
- **Your environment and config are trusted input.** `XCF_GIT_SYNC_GIMP_BIN`
  chooses which GIMP binary runs, and the batch job is `exec`'d inside GIMP. Run
  the tool only with an environment you control — not a shared runner or CI job
  fed by strangers.
- **The example workflow is pinned.** It installs xcf-git-sync at a fixed
  version and its actions at fixed commit SHAs because the job holds
  `contents: write`. If you copy it, keep the pins and bump them deliberately.
- Layer/group names are sanitized with `slugify` and git arguments are passed as
  argv after `--`, so an XCF's contents can't inject shell or git options.

## Releasing (maintainers)

Publishing runs in `.github/workflows/release.yml` using PyPI **Trusted
Publishing** (OIDC), so there is no API token to store or leak.

One-time setup on PyPI: add a trusted publisher for the `xcf-git-sync` project
with owner `EmjayBot`, repository `xcf-git-sync`, workflow `release.yml`, and
environment `pypi`.

To cut a release, bump the version in **both** `pyproject.toml`
(`[project].version`) and `src/xcf_git_sync/__init__.py` (`__version__`), then
tag it:

```bash
git commit -am "release: v0.1.1"
git tag v0.1.1
git push origin main --tags
```

The tag triggers the workflow, which verifies the tag matches `pyproject.toml`,
builds the sdist + wheel, and publishes to PyPI. `workflow_dispatch` is enabled
for manual runs.

## Legacy scripts

`legacy/xcf_git_sync.py` and `legacy/xcf_git_sync_selective.py` are the original
prototypes (built for `gimpformats==1.1.3`; current `gimpformats>=2025` changed
its API). They are kept for reference — the supported code is the
`xcf_git_sync` package (`src/xcf_git_sync/`) with the `xcf-git-sync` command.

## Contribute

```bash
pip install -e ".[dev]"
pytest -q
```

PRs welcome: GIMP 3 batch export hardening, tests with more XCF fixtures, tray app.
