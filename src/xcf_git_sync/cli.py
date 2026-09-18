"""CLI: one-shot export + watch loop."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import __version__
from .config import AppConfig, apply_cli_overrides, load_config
from .gitutils import commit_and_push
from .xcf import Gimp3NeededError, LayerFilter, export_xcf_layers


def build_filter(cfg: AppConfig) -> LayerFilter:
    return LayerFilter(
        tag_prefix=cfg.tag_prefix or "",
        include=list(cfg.include or []),
        include_regex=list(cfg.include_regex or []),
        exclude=list(cfg.exclude or []),
        exclude_regex=list(cfg.exclude_regex or []),
        group=list(cfg.group or []),
        only_visible=cfg.only_visible,
    )


class XcfHandler(FileSystemEventHandler):
    def __init__(self, repo: Path, out_root: Path, cfg: AppConfig):
        self.repo = repo
        self.out_root = out_root
        self.cfg = cfg
        self._last: dict[Path, float] = {}

    def on_modified(self, event):
        if event.is_directory:
            return
        p = Path(str(event.src_path))
        if p.suffix.lower() != ".xcf":
            return
        now = time.time()
        if p in self._last and now - self._last[p] < self.cfg.debounce:
            return
        self._last[p] = now
        time.sleep(0.8)  # let GIMP finish writing
        print(f"\n[watch] Change detected: {p}")
        try:
            exported = export_xcf_layers(
                p, self.out_root, build_filter(self.cfg),
                export_flattened=not self.cfg.no_flatten,
                via="gimp" if self.cfg.via_gimp else "auto",
            )
            commit_and_push(self.repo, exported, p, push=self.cfg.push)
        except Gimp3NeededError as e:
            print(f"[watch] Skipped: {e}")
        except Exception as e:  # keep watching despite one bad file
            print(f"[watch] Failed: {e}")
            import traceback
            traceback.print_exc()


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="xcf-git-sync",
        description="Watch GIMP XCF files, export layers to PNG, auto-commit/push.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--config", type=str, default=None, help="YAML config file")
    ap.add_argument("--xcf", type=str, default=None, help="Single XCF file to watch")
    ap.add_argument("--watch-dir", type=str, default=None, help="Directory to watch for XCFs")
    ap.add_argument("--repo", type=str, default=None, help="Git repo root")
    ap.add_argument("--out", type=str, default=None, help="PNG output root (default: <repo>/assets/xcf_layers)")
    ap.add_argument("--push", action="store_true", default=None, help="Auto git push")
    ap.add_argument("--no-flatten", action="store_true", default=None, help="Skip flattened composite")
    ap.add_argument("--no-only-visible", dest="only_visible", action="store_false", default=None,
                    help="Export hidden layers too")
    ap.add_argument("--tag-prefix", type=str, default=None)
    ap.add_argument("--include", type=str, default=None)
    ap.add_argument("--include-regex", type=str, default=None)
    ap.add_argument("--exclude", type=str, default=None)
    ap.add_argument("--exclude-regex", type=str, default=None)
    ap.add_argument("--group", type=str, default=None)
    ap.add_argument("--debounce", type=float, default=None)
    ap.add_argument("--via-gimp", action="store_true", default=None,
                    help="Export via headless GIMP instead of gimpformats "
                         "(needed for GIMP 3 XCFs, useful for testing)")
    ap.add_argument("--once", action="store_true", help="Export once, don't watch")
    return ap.parse_args(argv)


def resolve_config(args) -> AppConfig:
    cfg = load_config(args.config) if args.config else AppConfig()
    # repo default only when neither config nor CLI gave one
    if args.repo is None and not cfg.repo:
        cfg.repo = "."
    return apply_cli_overrides(cfg, args)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        cfg = resolve_config(args)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[config] {e}")
        return 2

    if not cfg.repo:
        print("Need --repo or repo: in config")
        return 2
    repo_path = Path(cfg.repo).resolve()
    out_root = Path(cfg.out).resolve() if cfg.out else repo_path / "assets" / "xcf_layers"
    out_root.mkdir(parents=True, exist_ok=True)
    layer_filter = build_filter(cfg)

    targets: list[Path] = []
    watch_path: Path | None = None
    if cfg.xcf:
        x = Path(cfg.xcf).resolve()
        targets = [x]
        watch_path = x.parent
    elif cfg.watch_dir:
        watch_path = Path(cfg.watch_dir).resolve()
        targets = sorted(watch_path.rglob("*.xcf"))
    else:
        print("Need --xcf or --watch-dir (or set in config)")
        return 2

    for x in targets:
        print(f"Exporting: {x}")
        try:
            exported = export_xcf_layers(
                x, out_root, layer_filter, export_flattened=not cfg.no_flatten,
                via="gimp" if cfg.via_gimp else "auto",
            )
            commit_and_push(repo_path, exported, x, push=cfg.push)
        except Gimp3NeededError as e:
            print(f"[skip] {e}")
        except FileNotFoundError:
            print(f"[skip] not found: {x}")
        except Exception as e:
            print(f"[error] {x}: {e}")

    if args.once:
        return 0
    if watch_path is None:
        return 0

    handler = XcfHandler(repo_path, out_root, cfg)
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()
    filt = cfg.tag_prefix or cfg.group or cfg.include or cfg.include_regex or "ALL"
    print(f"\n[watching] {watch_path} -> {out_root} (filter={filt})")
    print("Save your XCF in GIMP and it will auto-sync. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
