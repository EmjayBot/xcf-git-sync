"""config.yaml loading with CLI overrides."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    xcf: str = ""
    watch_dir: str = ""
    repo: str = "."
    out: str = ""
    push: bool = False
    no_flatten: bool = False
    only_visible: bool = True
    tag_prefix: str = ""
    include: list[str] = field(default_factory=list)
    include_regex: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    exclude_regex: list[str] = field(default_factory=list)
    group: list[str] = field(default_factory=list)
    debounce: float = 1.5
    via_gimp: bool = False
    timeout: float = 300
    list_layers: bool = False


def _split_csv(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip() for s in str(value).split(",") if s.strip()]


def load_config(path: str | Path | None) -> AppConfig:
    cfg = AppConfig()
    if not path:
        return cfg
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("pyyaml is required for --config (pip install pyyaml)") from e
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    watch = data.get("watch", {}) if isinstance(data, dict) else {}
    github = data.get("github", {}) if isinstance(data, dict) else {}
    _ = github  # reserved for branch/lfs settings
    for key in (
        "xcf", "watch_dir", "repo", "out", "tag_prefix",
    ):
        if watch.get(key) is not None:
            setattr(cfg, key, str(watch.get(key)))
    for key in ("push", "no_flatten", "only_visible", "via_gimp",
                "list_layers"):
        if watch.get(key) is not None:
            setattr(cfg, key, bool(watch.get(key)))
    if watch.get("timeout") is not None:
        cfg.timeout = float(watch.get("timeout"))
    if watch.get("auto_push") is not None and "push" not in watch:
        cfg.push = bool(watch.get("auto_push"))
    for key in ("include", "include_regex", "exclude", "exclude_regex", "group"):
        if watch.get(key) is not None:
            setattr(cfg, key, _split_csv(watch.get(key)))
    if watch.get("debounce") is not None:
        cfg.debounce = float(watch.get("debounce"))
    return cfg


def apply_cli_overrides(cfg: AppConfig, args) -> AppConfig:
    """CLI args win over config file. `args` is the argparse namespace."""
    for key in (
        "xcf", "watch_dir", "repo", "out", "tag_prefix",
        "push", "no_flatten", "only_visible", "via_gimp", "list_layers",
        "debounce", "timeout",
    ):
        val = getattr(args, key, None)
        if val is not None and val is not False or key in ("push", "no_flatten", "only_visible", "via_gimp", "list_layers") and val:
            # booleans: only override when the flag was actually passed
            setattr(cfg, key, val)
    # Fix-up: argparse gives None when flag absent for store_true with
    # default None; handle explicitly in cli by setting defaults None.
    for key in ("include", "include_regex", "exclude", "exclude_regex", "group"):
        val = getattr(args, key, None)
        if val:
            setattr(cfg, key, _split_csv(val))
    return cfg
