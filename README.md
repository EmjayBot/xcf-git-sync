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

The tool reads the XCF header (`gimp xcf v011` vs `v012`):

- v011 and earlier → parsed directly with `gimpformats` (fast, no GIMP needed)
- v012+ (GIMP 3) → exported via headless GIMP
  (`gimp --no-interface --batch-interpreter=python-fu-eval`), which works
  with GIMP 2.10+ and GIMP 3. GIMP must be installed (Windows: the default
  `C:\Program Files\GIMP *` location is auto-detected).

Force the GIMP path for any file (e.g. to test it) with `--via-gimp`:

```bash
xcf-git-sync --xcf design.xcf --repo . --once --via-gimp
```

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
