from pathlib import Path

from xcf_git_sync.xcf import (
    LayerFilter,
    is_gimp3_xcf,
    read_xcf_version,
    slugify,
)


def test_slugify():
    assert slugify("Hello World!") == "Hello-World"
    assert slugify("[GH] Hero") == "GH-Hero"
    assert slugify("") == "untitled"


def test_filter_tag_prefix():
    f = LayerFilter(tag_prefix="[GH]")
    assert f.keep([], "[GH] Hero", True)
    assert not f.keep([], "Background", True)


def test_filter_include_exclude():
    f = LayerFilter(include=["hero"], exclude=["wip"])
    assert f.keep([], "Hero Sword", True)
    assert not f.keep([], "Background", True)
    assert not f.keep([], "Hero WIP sketch", True)


def test_filter_regex_and_group():
    f = LayerFilter(include_regex=[r".*_export$"], group=["Sprites"])
    assert f.keep(["Sprites"], "hero_export", True)
    assert not f.keep(["UI"], "hero_export", True)
    assert not f.keep(["Sprites"], "hero", True)


def test_filter_visibility():
    f = LayerFilter(only_visible=True)
    assert not f.keep([], "Hidden", False)
    assert f.keep([], "Shown", True)


def test_xcf_version_detection(tmp_path):
    v11 = tmp_path / "a.xcf"
    v11.write_bytes(b"gimp xcf v011\x00" + b"\x00" * 100)
    assert read_xcf_version(v11) == "v011"
    assert not is_gimp3_xcf(v11)
    v12 = tmp_path / "b.xcf"
    v12.write_bytes(b"gimp xcf v012\x00" + b"\x00" * 100)
    assert read_xcf_version(v12) == "v012"
    assert is_gimp3_xcf(v12)


def test_export_real_xcf(tmp_path):
    """Export the small bundled test XCF if present in the dev environment."""
    from xcf_git_sync.xcf import export_xcf_layers

    candidates = [
        Path(r"C:\Users\ricky\AppData\Local\Temp\opencode\dylanddragonblank.xcf"),
    ]
    src = next((p for p in candidates if p.exists()), None)
    if src is None:
        import pytest
        pytest.skip("no real XCF available")
    out = tmp_path / "out"
    exported = export_xcf_layers(src, out, LayerFilter())
    assert exported, "expected at least one PNG"
    assert all(p.suffix == ".png" and p.exists() for p in exported)
