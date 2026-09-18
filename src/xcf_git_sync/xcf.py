"""XCF parsing and layer export.

Supports GIMP 2.10 (xcf v011 and earlier) via gimpformats.
Detects GIMP 3 (xcf v012+) and falls back to headless GIMP batch export
when a GIMP binary is available, otherwise raises a clear error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from PIL import Image

HEADER_LEN = 14  # e.g. b'gimp xcf v011\x00'


def read_xcf_version(xcf_path: Path) -> str:
    """Return the version string like 'v011', or 'unknown'."""
    try:
        with open(xcf_path, "rb") as f:
            header = f.read(HEADER_LEN)
        m = re.search(rb"v(\d{3})", header)
        if m:
            return "v" + m.group(1).decode("ascii")
    except OSError:
        pass
    return "unknown"


def is_gimp3_xcf(xcf_path: Path) -> bool:
    """True if the file needs GIMP 3 to parse (xcf v012+)."""
    ver = read_xcf_version(xcf_path)
    if ver == "unknown":
        return False
    try:
        return int(ver[1:]) >= 12
    except ValueError:
        return False


def slugify(name: str) -> str:
    name = re.sub(r"[^\w\- ]+", "", name.strip())
    return re.sub(r"\s+", "-", name)[:100] or "untitled"


@dataclass
class LayerFilter:
    tag_prefix: str = ""
    include: list[str] = field(default_factory=list)
    include_regex: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    exclude_regex: list[str] = field(default_factory=list)
    group: list[str] = field(default_factory=list)
    only_visible: bool = True

    def __post_init__(self) -> None:
        self._inc_rx = [re.compile(p) for p in self.include_regex if p]
        self._exc_rx = [re.compile(p) for p in self.exclude_regex if p]

    @staticmethod
    def _match_any(name: str, patterns: list[str]) -> bool:
        low = name.lower()
        return any(p.lower() in low for p in patterns)

    @staticmethod
    def _match_rx(name: str, regexes: list[re.Pattern]) -> bool:
        return any(rx.search(name) for rx in regexes)

    def keep(self, group_path: list[str], layer_name: str, visible: bool) -> bool:
        if self.only_visible and not visible:
            return False
        if self.tag_prefix and not layer_name.startswith(self.tag_prefix):
            return False
        if self.group:
            joined = "/".join(group_path)
            if not any(joined.startswith(w) or w in joined for w in self.group):
                return False
        full_path = "/".join(group_path + [layer_name])
        if self.include or self._inc_rx:
            if not (
                self._match_any(layer_name, self.include)
                or self._match_any(full_path, self.include)
                or self._match_rx(layer_name, self._inc_rx)
                or self._match_rx(full_path, self._inc_rx)
            ):
                return False
        if self.exclude and (
            self._match_any(layer_name, self.exclude)
            or self._match_any(full_path, self.exclude)
        ):
            return False
        if self._exc_rx and (
            self._match_rx(layer_name, self._exc_rx)
            or self._match_rx(full_path, self._exc_rx)
        ):
            return False
        return True


def _iter_gimpformats_layers(doc) -> Iterator[tuple[list[str], object]]:
    """Yield (group_path, layer) using the gimpformats>=2025 API."""
    tree = doc.walkTree()
    stack: list[tuple[object, list[str]]] = [(tree, [])]
    while stack:
        node, prefix = stack.pop()
        children = getattr(node, "children", []) or []
        for child in reversed(children):
            if getattr(child, "isGroup", False) or hasattr(child, "children"):
                # A group node: descend (groups also appear as children lists)
                gname = getattr(child, "name", "group") or "group"
                stack.append((child, prefix + [gname]))
            else:
                yield (prefix, child)


def _layer_image(layer) -> Image.Image | None:
    img = getattr(layer, "image", None)
    if isinstance(img, Image.Image):
        return img
    get_image = getattr(layer, "getImage", None)
    if callable(get_image):
        try:
            img = get_image()
        except Exception:
            return None
        if isinstance(img, Image.Image):
            return img
    return None


class Gimp3NeededError(RuntimeError):
    """Raised when an XCF needs headless GIMP but no GIMP binary was found."""


def export_xcf_layers(
    xcf_path: Path,
    out_root: Path,
    layer_filter: LayerFilter | None = None,
    export_flattened: bool = True,
    via: str = "auto",
) -> list[Path]:
    """Export layers of one XCF to PNGs. Returns list of written files.

    via: "auto" (gimpformats for GIMP <=2.10 files, headless GIMP for
    GIMP 3 files), "gimp" (always headless GIMP), "gimpformats" (never
    headless GIMP; raises Gimp3NeededError on GIMP 3 files).
    """
    xcf_path = Path(xcf_path)
    out_root = Path(out_root)
    layer_filter = layer_filter or LayerFilter()
    out_dir = out_root / slugify(xcf_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    if via == "gimp" or (via == "auto" and is_gimp3_xcf(xcf_path)):
        # Local import: gimpbatch needs only stdlib at import time, but
        # keep the dependency direction xcf -> gimpbatch one-way.
        from .gimpbatch import export_via_gimp_batch

        return export_via_gimp_batch(
            xcf_path, out_root, layer_filter,
            export_flattened=export_flattened,
        )
    if via == "gimpformats" and is_gimp3_xcf(xcf_path):
        raise Gimp3NeededError(
            "%s looks like a GIMP 3 XCF (%s), which gimpformats cannot "
            "parse. Re-run with --via-gimp." % (xcf_path.name,
                                                read_xcf_version(xcf_path))
        )

    from gimpformats.gimpXcfDocument import GimpDocument

    doc = GimpDocument(str(xcf_path))
    exported: list[Path] = []

    for group_path, layer in _iter_gimpformats_layers(doc):
        lname = getattr(layer, "name", None) or "layer"
        visible = bool(getattr(layer, "visible", True))
        if not layer_filter.keep(group_path, lname, visible):
            continue
        img = _layer_image(layer)
        if img is None:
            continue
        group_dir = out_dir
        if group_path:
            group_dir = out_dir / "/".join(slugify(p) for p in group_path)
            group_dir.mkdir(parents=True, exist_ok=True)
        # De-duplicate: 'Hero.png', 'Hero-2.png', ...
        base = slugify(lname)
        fpath = group_dir / f"{base}.png"
        counter = 2
        while fpath.exists():
            # Overwrite check: same stem from re-export should just overwrite.
            # Only de-dupe when two different layers slugify identically in
            # the same folder. We detect that by tracking this run's outputs.
            if fpath in exported:
                fpath = group_dir / f"{base}-{counter}.png"
                counter += 1
            else:
                break
        img.save(fpath, "PNG")
        if fpath not in exported:
            exported.append(fpath)

    if export_flattened:
        try:
            flat = getattr(doc, "image", None)
            if isinstance(flat, Image.Image):
                flat_path = out_dir / "_flattened.png"
                flat.save(flat_path, "PNG")
                exported.append(flat_path)
        except Exception:
            pass
    return exported
