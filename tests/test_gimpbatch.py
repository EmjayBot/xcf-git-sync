"""Tests for headless GIMP batch export (uses a fake GIMP binary)."""
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from xcf_git_sync import gimpbatch
from xcf_git_sync.gimpbatch import (
    build_command,
    export_via_gimp_batch,
    find_gimp_binary,
    parse_manifest,
)
from xcf_git_sync.xcf import Gimp3NeededError, LayerFilter, export_xcf_layers

STUB = textwrap.dedent(
    """
    import json, os, sys, time
    from PIL import Image
    if os.environ.get("XCF_STUB_MODE") == "timeout":
        time.sleep(30)
    job = json.loads(open(os.environ["XCF_GIT_SYNC_JOB"], "rb").read().decode("utf-8"))
    stg = job["staging"]
    print("some startup noise")
    print("XCFGSYNC-GIMP\\t9.9.9-fake")
    layers = [
        (1, ["[GH] Hero"]),
        (1, ["Background"]),
        (0, ["[GH] Hidden"]),
        (1, ["Same Name"]),
        (1, ["Same Name"]),
        (1, ["Sprites", "Sidekick"]),
    ]
    for i, (vis, names) in enumerate(layers):
        p = os.path.join(stg, "%04d.png" % i)
        Image.new("RGBA", (8, 8), (i * 30 % 255, 0, 0, 255)).save(p)
        print("XCFGSYNC-EXPORT\\t%s\\t%d\\t%s" % (p, vis, json.dumps(names)))
    print("XCFGSYNC-BOGUS-LINE")
    print("XCFGSYNC-EXPORT\\tbroken")
    if job.get("flattened"):
        fp = os.path.join(stg, "_flattened.png")
        Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(fp)
        print("XCFGSYNC-FLAT\\t%s" % fp)
    sys.stdout.flush()
    """
)


@pytest.fixture()
def stub_bin(tmp_path):
    p = tmp_path / "fakegimp.py"
    p.write_text(STUB, encoding="utf-8")
    return str(p)


def _patch_gimp(monkeypatch, stub_bin):
    monkeypatch.setattr(gimpbatch, "find_gimp_binary", lambda: sys.executable)
    monkeypatch.setattr(
        gimpbatch, "build_command", lambda _bin: [sys.executable, stub_bin]
    )


def _dummy_xcf(tmp_path):
    xcf = tmp_path / "design.xcf"
    xcf.write_bytes(b"gimp xcf v011\x00" + b"\x00" * 64)
    return xcf


def test_parse_manifest_ignores_noise():
    out = "\n".join([
        "GIMP startup noise",
        "XCFGSYNC-GIMP\t2.10.32",
        "XCFGSYNC-EXPORT\t/s/a.png\t1\t" + json.dumps(["A B"]),
        "XCFGSYNC-EXPORT\t/s/b.png\t0\t" + json.dumps(["G", "C"]),
        "XCFGSYNC-EXPORT\tbroken",
        "XCFGSYNC-FLAT\t/s/_flattened.png",
        "XCFGSYNC-EXPORT\t/s/c.png\t1\tnot-json{{{",
    ])
    exports, flat, ver, layers = parse_manifest(out)
    assert ver == "2.10.32"
    assert flat == "/s/_flattened.png"
    assert layers == []
    assert [(e["path"], e["visible"], e["names"]) for e in exports] == [
        ("/s/a.png", True, ["A B"]),
        ("/s/b.png", False, ["G", "C"]),
    ]


def test_parse_manifest_list_mode():
    out = "\n".join([
        "XCFGSYNC-GIMP\t3.2.6",
        "XCFGSYNC-LAYER\t1\t" + json.dumps(["Labels", "National"]),
        "XCFGSYNC-LAYER\t0\t" + json.dumps(["Hidden"]),
    ])
    exports, flat, ver, layers = parse_manifest(out)
    assert ver == "3.2.6"
    assert exports == [] and flat is None
    assert layers == [(["Labels"], "National", True), ([], "Hidden", False)]


def test_build_command_variants():
    c2 = build_command(r"C:\Program Files\GIMP 2\bin\gimp-2.10.exe")
    assert "-i" in c2 and "--batch-interpreter=python-fu-eval" in c2
    c3 = build_command("gimp-3.0")
    assert "--no-interface" in c3 and "-i" not in c3
    assert any("XCF_GIT_SYNC_FU" in a for a in c3)


def test_find_gimp_binary_uses_path(monkeypatch):
    monkeypatch.setattr(
        gimpbatch.shutil, "which", lambda name: "/usr/bin/" + name
    )
    assert find_gimp_binary() == "/usr/bin/gimp-3.2"


def test_export_e2e_with_filter(monkeypatch, tmp_path, stub_bin):
    _patch_gimp(monkeypatch, stub_bin)
    out = tmp_path / "out"
    got = export_via_gimp_batch(
        _dummy_xcf(tmp_path), out, LayerFilter(tag_prefix="[GH]"))
    names = sorted(p.name for p in got)
    # visible + matching layer, flattened; hidden + non-matching dropped
    assert "GH-Hero.png" in names
    assert "_flattened.png" in names
    assert not any("Hidden" in n or "Background" in n for n in names)
    assert all(p.exists() for p in got)


def test_export_e2e_dedup_and_groups(monkeypatch, tmp_path, stub_bin):
    _patch_gimp(monkeypatch, stub_bin)
    out = tmp_path / "out"
    got = export_via_gimp_batch(_dummy_xcf(tmp_path), out,
                                LayerFilter(only_visible=False))
    names = sorted(p.relative_to(out).as_posix() for p in got)
    assert "design/Same-Name.png" in names
    assert "design/Same-Name-2.png" in names
    assert "design/Sprites/Sidekick.png" in names
    # hidden layer exported when filter allows it
    assert "design/GH-Hidden.png" in names


def test_no_binary_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(gimpbatch, "find_gimp_binary", lambda: None)
    with pytest.raises(Gimp3NeededError):
        export_via_gimp_batch(_dummy_xcf(tmp_path), tmp_path / "out")


def test_empty_manifest_raises(monkeypatch, tmp_path):
    quiet = tmp_path / "quiet.py"
    quiet.write_text("import sys; print('nothing useful'); sys.exit(1)",
                     encoding="utf-8")
    monkeypatch.setattr(gimpbatch, "find_gimp_binary", lambda: sys.executable)
    monkeypatch.setattr(
        gimpbatch, "build_command", lambda _bin: [sys.executable, str(quiet)])
    with pytest.raises(RuntimeError, match="produced nothing"):
        export_via_gimp_batch(_dummy_xcf(tmp_path), tmp_path / "out")


def test_timeout_raises(monkeypatch, tmp_path, stub_bin):
    _patch_gimp(monkeypatch, stub_bin)
    monkeypatch.setenv("XCF_STUB_MODE", "timeout")
    with pytest.raises(RuntimeError, match="timed out"):
        export_via_gimp_batch(_dummy_xcf(tmp_path), tmp_path / "out",
                              timeout=1)


def test_fu_source_is_polyglot_safe():
    import ast
    from xcf_git_sync.fu_script import get_fu_source

    src = get_fu_source()
    for banned in ["encoding=", "async ", "await ",
                   "FileNotFoundError", "keyword-only", "nonlocal"]:
        assert banned not in src, banned
    tree = ast.parse(src)
    fstrings = [n for n in ast.walk(tree)
                if n.__class__.__name__ == "JoinedStr"]
    assert not fstrings, "f-strings are Python 3 only"
    for needed in ("XCF_GIT_SYNC_JOB", "gimp_file_load", "gimp_file_save",
                   "gimp_layer_new_from_drawable", "gimp_layer_set_offsets",
                   "XCFGSYNC-EXPORT", "XCFGSYNC-LAYER", "gimp_quit",
                   "gi.repository", "merge_visible_layers", "file_load"):
        assert needed in src, needed
    compile(src, "export_fu.py", "exec")  # py3 syntax must hold


def test_via_routing(monkeypatch, tmp_path):
    v12 = tmp_path / "g3.xcf"
    v12.write_bytes(b"gimp xcf v012\x00" + b"\x00" * 64)
    with pytest.raises(Gimp3NeededError):
        export_xcf_layers(v12, tmp_path / "out", via="gimpformats")

    calls = []
    monkeypatch.setattr(
        gimpbatch, "export_via_gimp_batch",
        lambda *a, **k: calls.append((a, k)) or [])
    export_xcf_layers(_dummy_xcf(tmp_path), tmp_path / "out", via="gimp")
    assert len(calls) == 1
