"""Headless GIMP batch export.

Works with GIMP 2.10 and GIMP 3 (both support ``--batch-interpreter
python-fu-eval``). The GIMP-side script (:mod:`fu_script`) exports every
layer to a staging dir and prints a manifest; this module applies
:class:`LayerFilter`, renames into the final layout, and returns paths.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .fu_script import get_fu_source
from .xcf import Gimp3NeededError, LayerFilter, read_xcf_version, slugify

JOB_ENV = "XCF_GIT_SYNC_JOB"
FU_ENV = "XCF_GIT_SYNC_FU"
BIN_ENV = "XCF_GIT_SYNC_GIMP_BIN"
DEFAULT_TIMEOUT = 300

FLATPAK_CONSOLE_COMMANDS = (
    "gimp-console-3.2",
    "gimp-console-3.0",
    "gimp-console-3",
    "gimp-console",
)


def _windows_candidates() -> list[str]:
    """Well-known GIMP install locations on Windows (newest first)."""
    cands: list[str] = []
    roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"),
            "Programs",
        ),
    ]
    for root in roots:
        for pat in ("GIMP 3", "GIMP 2", "GIMP*"):
            for exe in glob.glob(os.path.join(root, pat, "bin", "gimp*.exe")):
                base = os.path.basename(exe).lower()
                if not (base.startswith(("gimp-3", "gimp-2", "gimp-console", "gimp"))
                        and base.endswith(".exe")):
                    continue
                if "debug" in base or "tool" in base or "test" in base:
                    continue
                cands.append(exe)
    # Prefer console binaries (no window flash in batch), then newest.
    def rank(p: str) -> tuple:
        b = os.path.basename(p).lower()
        return ("console" in b, b)

    return sorted(set(cands), key=rank, reverse=True)


def find_gimp_binary() -> str | None:
    """Return a GIMP binary path, or None if GIMP isn't installed."""
    import shutil as _shutil

    for cand in ("gimp-3.2", "gimp-3.0", "gimp-3", "gimp",
                 "gimp-console-3.2", "gimp-console-3", "gimp-2.10"):
        found = _shutil.which(cand)
        if found:
            return found
    for cand in _windows_candidates():
        if os.path.exists(cand):
            return cand
    # Flatpak installs are common on Linux. Prefer a console command
    # (headless-safe); fall back to the GUI binary.
    try:
        r = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application"],
            capture_output=True, text=True, timeout=10,
        )
        if "org.gimp.GIMP" in (r.stdout or ""):
            for cmd in FLATPAK_CONSOLE_COMMANDS:
                try:
                    t = subprocess.run(
                        ["flatpak", "run", "--command=" + cmd,
                         "org.gimp.GIMP", "--version"],
                        capture_output=True, text=True, timeout=60,
                    )
                    if t.returncode == 0:
                        return "flatpak run --command=%s org.gimp.GIMP" % cmd
                except Exception:
                    continue
            return "flatpak run org.gimp.GIMP"
    except Exception:
        pass
    return None


def split_gimp_command(gimp_bin: str) -> list[str]:
    """Split a configured GIMP command into argv parts.

    Plain paths pass through; compound commands (e.g. flatpak) are split
    on whitespace (quoting respected on POSIX).
    """
    import shlex

    gimp_bin = (gimp_bin or "").strip()
    if not gimp_bin:
        return []
    if os.name == "nt" and os.path.exists(gimp_bin):
        return [gimp_bin]
    if " " not in gimp_bin and "\t" not in gimp_bin:
        return [gimp_bin]
    try:
        return shlex.split(gimp_bin, posix=(os.name != "nt"))
    except ValueError:
        return [gimp_bin]


def effective_gimp_bin(explicit: str | None = None) -> str | None:
    """Explicit --gimp-bin / env override wins, else auto-detect."""
    if explicit:
        return explicit
    env = os.environ.get(BIN_ENV, "").strip()
    if env:
        return env
    return find_gimp_binary()


def build_command(gimp_bin: str) -> list[str]:
    """Argv (without the final -b program) for headless python-fu-eval."""
    parts = split_gimp_command(gimp_bin)
    low = gimp_bin.lower()
    if "2.10" in low or "gimp-2" in low or low.endswith("gimp 2\\bin\\gimp-2.10.exe"):
        iface = ["-i"]
    else:
        iface = ["--no-interface"]
    batch_code = (
        "import os;"
        "exec(open(os.environ['" + FU_ENV + "']).read());"
    )
    return parts + iface + [
        "--batch-interpreter=python-fu-eval",
        "-b", batch_code,
    ]


def parse_manifest(output: str):
    """Parse GIMP stdout.

    Returns (exports, flat_path, gimp_version, layers) where
    exports: [{path, visible(bool), names([group..., name])}]
    layers: [(group_path, name, visible)] (list mode; else [])
    Unknown lines (startup noise, warnings) are ignored.
    """
    exports: list[dict] = []
    layers: list[tuple] = []
    flat: str | None = None
    version: str | None = None
    for line in (output or "").splitlines():
        if not line.startswith("XCFGSYNC-"):
            continue
        parts = line.split("\t")
        kind = parts[0]
        try:
            if kind == "XCFGSYNC-EXPORT" and len(parts) == 4:
                exports.append({
                    "path": parts[1],
                    "visible": parts[2].strip() == "1",
                    "names": json.loads(parts[3]),
                })
            elif kind == "XCFGSYNC-LAYER" and len(parts) == 3:
                names = json.loads(parts[2])
                layers.append((names[:-1], names[-1],
                               parts[1].strip() == "1"))
            elif kind == "XCFGSYNC-FLAT" and len(parts) == 2:
                flat = parts[1]
            elif kind == "XCFGSYNC-GIMP" and len(parts) == 2:
                version = parts[1]
        except (ValueError, IndexError):
            continue
    return exports, flat, version, layers


def _place(staging_path: str, dest_dir: Path, slug_base: str,
           taken: set[Path]) -> Path:
    """Move a staged PNG into its final name (de-duped)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    fpath = dest_dir / (slug_base + ".png")
    counter = 2
    while fpath.exists() or fpath in taken:
        fpath = dest_dir / ("%s-%d.png" % (slug_base, counter))
        counter += 1
    shutil.move(staging_path, str(fpath))
    taken.add(fpath)
    return fpath


def _require_gimp(xcf_path: Path, explicit: str | None = None) -> str:
    gimp_bin = effective_gimp_bin(explicit)
    if not gimp_bin:
        raise Gimp3NeededError(
            "%s (%s) needs headless GIMP to export, but no GIMP binary was "
            "found. Install GIMP 2.10+ or GIMP 3, or point --gimp-bin at it."
            % (xcf_path.name, read_xcf_version(xcf_path))
        )
    return gimp_bin


def _run_fu_job(xcf_path: Path, job_extra: dict, timeout: int,
                gimp_bin: str | None = None) -> tuple[str, str]:
    """Run the Fu script with the given job; return (output, gimp_bin)."""
    xcf_path = Path(xcf_path)
    gimp_bin = gimp_bin or _require_gimp(xcf_path)
    tmpdir = Path(tempfile.mkdtemp(prefix="xcfgsync-"))
    try:
        job = {"xcf": str(xcf_path)}
        job.update(job_extra)
        job_path = tmpdir / "job.json"
        fu_path = tmpdir / "export_fu.py"
        job_path.write_text(json.dumps(job), encoding="utf-8")
        fu_path.write_text(get_fu_source(), encoding="utf-8")

        env = dict(os.environ)
        env[JOB_ENV] = str(job_path)
        env[FU_ENV] = str(fu_path)
        cmd = build_command(gimp_bin)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                "GIMP batch job timed out after %ds for %s "
                "(first launch can be slow; retry, it reuses caches)."
                % (timeout, xcf_path.name)
            ) from e
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return output, gimp_bin
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def list_layers(xcf_path: Path, timeout: int = DEFAULT_TIMEOUT,
                gimp_bin: str | None = None):
    """List (group_path, name, visible) for every layer via headless GIMP."""
    xcf_path = Path(xcf_path)
    output, gimp_bin = _run_fu_job(xcf_path, {"mode": "list"},
                                   timeout, gimp_bin)
    _exports, _flat, version, layers = parse_manifest(output)
    if version:
        print("[gimp] via %s (GIMP %s)" % (gimp_bin, version))
    if not layers:
        tail = "\n".join(output.splitlines()[-15:])
        raise RuntimeError(
            "GIMP layer listing produced nothing for %s.\n%s"
            % (xcf_path.name, tail)
        )
    return layers


def export_via_gimp_batch(
    xcf_path: Path,
    out_root: Path,
    layer_filter: LayerFilter | None = None,
    export_flattened: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
    gimp_bin: str | None = None,
) -> list[Path]:
    """Export one XCF's layers via headless GIMP. Returns written PNGs."""
    xcf_path = Path(xcf_path)
    out_root = Path(out_root)
    layer_filter = layer_filter or LayerFilter()

    gimp_bin = _require_gimp(xcf_path, gimp_bin)

    out_dir = out_root / slugify(xcf_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="xcfgsync-"))
    staging = tmpdir / "staging"
    staging.mkdir()
    try:
        output, _bin = _run_fu_job(xcf_path, {
            "mode": "export",
            "staging": str(staging),
            "flattened": bool(export_flattened),
        }, timeout, gimp_bin)
        exports, flat, gimp_version, _layers = parse_manifest(output)
        if gimp_version:
            print("[gimp] via %s (GIMP %s)" % (gimp_bin, gimp_version))
        if not exports and not flat:
            tail = "\n".join(output.splitlines()[-15:])
            raise RuntimeError(
                "GIMP batch export produced nothing for %s.\n%s"
                % (xcf_path.name, tail)
            )

        exported: list[Path] = []
        taken: set[Path] = set()
        for item in exports:
            names = item.get("names") or ["layer"]
            group_path, lname = names[:-1], names[-1]
            if not layer_filter.keep(group_path, lname, item.get("visible", True)):
                continue
            src = item["path"]
            if not os.path.exists(src):
                print("[gimp] missing staged file (skipped): %s" % src)
                continue
            group_dir = out_dir
            if group_path:
                group_dir = out_dir.joinpath(
                    *[slugify(p) for p in group_path])
            exported.append(_place(src, group_dir, slugify(lname), taken))
        if export_flattened and flat and os.path.exists(flat):
            flat_dest = out_dir / "_flattened.png"
            shutil.move(flat, str(flat_dest))
            exported.append(flat_dest)
        print("[gimp] exported %d layer(s) from %s"
              % (len(exported), xcf_path.name))
        return exported
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)
