# XCF Sync — GIMP XCF → GitHub Auto-Sync
### `xcf-git-sync` — Watch `.xcf` files, export only the layers you need as PNG, and auto-push.

[![PyPI](https://img.shields.io/pypi/v/xcf-git-sync)](https://pypi.org/project/xcf-git-sync/) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)

Built for large worldbuilding maps. Works on 11k x 11k XCFs by exporting cropped layers + tiles instead of full-canvas PNGs.

### Why XCF Sync?

GIMP is great for drawing world maps. Git is great for versioning them. But GIMP's `.xcf` is a 500MB binary blob — you can't diff it, and your maps app can't read it.

XCF Sync watches your XCF and syncs only tagged layers like `[GH] Borders`, `[GH] Rivers` as PNGs. Your team pushes the XCF, GitHub Actions exports the PNGs/tiles, your map auto-updates.

### Features

- **Selective export** by tag, group, name, or regex
- **GIMP 2.10 and GIMP 3 support** — fast `gimpformats` path for v011, headless GIMP 3 fallback for v012+
- **Large map ready** — cropped export + manifest + optional 256px tiles for 11k maps
- **Watch mode** — instant local export on save
- **Git auto-sync** — auto-commit and push changed layers
- **Cloud safety net** — GitHub Actions workflow that works even when no one is watching

### Install

```bash
pip install xcf-git-sync
# or for dev
pip install -e ".[dev]"
