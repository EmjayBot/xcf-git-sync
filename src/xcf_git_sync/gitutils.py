"""Git add/commit/push helpers (no hard dependency on GitPython)."""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path


def _run(repo: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), cwd=repo, capture_output=True, text=True, timeout=120
    )


def commit_and_push(
    repo_path: Path,
    files: list[Path],
    xcf_path: Path,
    push: bool = True,
    label: str = "sync",
) -> bool:
    """Stage exported PNGs (+ the XCF if inside the repo), commit, push.

    Returns True if a commit was created.
    """
    repo_path = Path(repo_path)
    if not (repo_path / ".git").exists():
        print(f"[git] {repo_path} is not a git repo, skipping commit")
        return False

    rel_files: list[str] = []
    for f in list(files) + [xcf_path]:
        try:
            rel_files.append(str(Path(f).resolve().relative_to(repo_path.resolve())))
        except ValueError:
            continue
    if not rel_files:
        print("[git] Nothing inside repo to commit")
        return False

    r = _run(repo_path, "git", "add", "--", *rel_files)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return False
    status = _run(repo_path, "git", "status", "--porcelain", "--", *rel_files)
    if not status.stdout.strip():
        print("[git] No changes to commit")
        return False
    msg = (
        f"auto: {label} {xcf_path.name} "
        f"@ {datetime.now().isoformat(timespec='seconds')}"
    )
    r = _run(repo_path, "git", "commit", "-m", msg)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return False
    print(f"[git] Committed: {msg}")
    if push:
        r = _run(repo_path, "git", "push")
        if r.returncode == 0:
            print("[git] Pushed!")
        else:
            print("[git] Push failed - check credentials / remote")
            print(r.stdout, r.stderr)
    return True
