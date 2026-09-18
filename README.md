# xcf-git-sync — GIMP XCF → GitHub Auto-Sync

Watch `.xcf` files, export only the layers you want as PNG, and auto-commit/push to git.

![ci](https://github.com/EmjayBot/xcf-git-sync/actions/workflows/ci.yml/badge.svg)
License: MIT

## Install

```bash
pip install -e .
# or: pip install xcf-git-sync  (once published)
```

Requires Python 3.9+. For GIMP 3 `.xcf` files (v012+), install GIMP 3 so the
headless fallback can export; GIMP 2.10 files work with no GIMP install.

## Quick start

```bash
# One-shot export (no watch):
xcf-git-sync --xcf design.xcf --repo . --once

# Watch and auto-push filtered layers:
xcf-git-sync --xcf design.xcf --repo . --push --tag-prefix "[GH]"

# Watch a whole folder + config file:
xcf-git-sync --config config.yaml --watch-dir ./art --push
```

See `config.example.yaml` for all options. Copy it to `config.yaml` and edit.

## Filtering

- `--tag-prefix "[GH]"` — only layers starting with `[GH]`
- `--include "Hero,Logo"` — substring match on `Group/Layer`
- `--include-regex ".*_export$"` — regex match
- `--exclude "Sketch,WIP"` / `--exclude-regex "^temp"`
- `--group "Sprites,UI"` — only layers inside those groups
- `--no-only-visible` — include hidden layers (default: visible only)
- `--no-flatten` — skip `_flattened.png`

## GIMP 3 support

The tool reads the XCF header (`gimp xcf v011` vs `v012+`):

- v011 and earlier → parsed directly with `gimpformats` (fast, no GIMP needed)
- v012+ (GIMP 3, e.g. v019) → exported via headless GIMP
  (`--batch-interpreter=python-fu-eval`), verified on GIMP 3.2.6 and 2.10.32.
  GIMP is auto-detected (PATH, `C:\Program Files\GIMP *`,
  `%LOCALAPPDATA%\Programs\GIMP *`, Flatpak).

Force the GIMP path for any file (e.g. to test it) with `--via-gimp`:

```bash
xcf-git-sync --xcf design.xcf --repo . --once --via-gimp
```

## Inspecting layers

Not sure what to filter? Print the layer tree with `[keep]` marks showing
what your current filters would export:

```bash
xcf-git-sync --xcf maps/source/urth.xcf --repo . --list-layers \
  --include "National,Cities,Sub-National,Political,Ocean"
```

## Cloud auto-sync (GitHub Actions)

The local watcher is instant, but layers only sync while someone runs it.
As a safety net, run the export in CI: any push touching the XCF
regenerates the PNGs and commits them back.

1. Copy `examples/urthmaps-sync.yaml` into your art repo as
   `.github/workflows/xcf-sync.yaml`.
2. Adjust `XCF_PATH`, `FILTERS`, and branch names at the top.
3. Push an XCF change — the PNGs update themselves a few minutes later.

It installs headless GIMP 3 from the official Flatpak, so even GIMP 3
XCFs work. The `paths:` trigger means the bot's own PNG commit never
re-triggers the workflow (no loops). Free on public repos.

> Why not Cloudflare? Workers can't run GIMP — no custom native
> binaries, tight CPU/memory limits, no GTK stack. The compute has
> to live where GIMP can run (GitHub runners, a VM, or a container);
> Cloudflare could front a status page, but it adds nothing here.

## Legacy scripts

`legacy/xcf_git_sync.py` and `legacy/xcf_git_sync_selective.py` are the original prototypes
(built for `gimpformats==1.1.3`; current `gimpformats>=2025` changed its API).
They are kept for reference — the supported code is the `xcf_git_sync` package
(`src/xcf_git_sync/`) with the `xcf-git-sync` command.

## Contribute

```bash
pip install -e ".[dev]"
pytest -q
```

PRs welcome: GIMP 3 batch export, tests with more XCF fixtures, tray app.
