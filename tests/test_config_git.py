import subprocess
from pathlib import Path

from xcf_git_sync.config import AppConfig, apply_cli_overrides, load_config
from xcf_git_sync.gitutils import commit_and_push


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_load_config(tmp_path):
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "watch:\n"
        "  xcf_file: ./design.xcf\n"
        "  repo: ./\n"
        "  out: ./assets/xcf_layers\n"
        "  auto_push: true\n"
        '  tag_prefix: "[GH]"\n'
        "  only_visible: true\n"
        "github:\n"
        "  branch: main\n",
        encoding="utf-8",
    )
    from xcf_git_sync.config import load_config as lc

    # legacy key xcf_file is tolerated (ignored); ensure no crash and defaults sane
    cfg = lc(cfg_file)
    assert cfg.tag_prefix == "[GH]"
    assert cfg.push is True


def test_cli_overrides():
    cfg = AppConfig()
    cfg.tag_prefix = "[GH]"

    class Args:
        xcf = None
        watch_dir = None
        repo = None
        out = None
        tag_prefix = "@export"
        push = None
        no_flatten = None
        only_visible = None
        debounce = None
        include = "Hero,Logo"
        include_regex = None
        exclude = None
        exclude_regex = None
        group = None

    out = apply_cli_overrides(cfg, Args())
    assert out.tag_prefix == "@export"
    assert out.include == ["Hero", "Logo"]


def test_git_commit_in_tmp_repo(tmp_path):
    if not _git_available():
        import pytest
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, capture_output=True, check=True)
    xcf = repo / "design.xcf"
    xcf.write_bytes(b"gimp xcf v011\x00fake")
    png = repo / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    created = commit_and_push(repo, [png], xcf, push=False)
    assert created is True
    # second run: no changes
    created2 = commit_and_push(repo, [png], xcf, push=False)
    assert created2 is False
