
"""
xcf_git_sync.py
Watches XCF files and auto-syncs layers to GitHub.

Usage:
    python xcf_git_sync.py --xcf path/to/file.xcf --repo path/to/repo [--push] [--flatten]
    python xcf_git_sync.py --watch-dir path/to/art --repo path/to/repo --push
"""
import argparse
import time
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from gimpformats.gimpXcfDocument import GimpDocument, GimpLayer, GimpGroup
from PIL import Image
import subprocess

def slugify(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[^\w\- ]+', '', name)
    name = re.sub(r'\s+', '-', name)
    return name[:100] or "untitled"

def get_layers_recursive(root):
    stack = [(root, [])]
    while stack:
        node, prefix = stack.pop()
        children = []
        if hasattr(node, 'children'):
            children = node.children
        elif hasattr(node, 'layers'):
            children = node.layers
        else:
            children = [node]
        for child in reversed(children):
            if isinstance(child, GimpGroup) or getattr(child, 'isGroup', False):
                gname = getattr(child, 'name', 'group')
                stack.append((child, prefix + [gname]))
            else:
                yield (prefix, child)

def export_xcf_layers(xcf_path: Path, out_root: Path, export_flattened=True, only_visible=True):
    xcf_path = Path(xcf_path)
    out_dir = out_root / slugify(xcf_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[xcf] Parsing {xcf_path}")
    doc = GimpDocument(str(xcf_path))
    
    try:
        root = doc.walkTree()
        layer_iter = get_layers_recursive(root)
    except Exception:
        layer_iter = [([], l) for l in doc.layers]

    exported = []
    for prefix, layer in layer_iter:
        try:
            lname = getattr(layer, 'name', None) or getattr(layer, 'layer_name', 'layer')
            visible = getattr(layer, 'visible', True)
            if only_visible and not visible:
                continue
            
            pil_img = None
            if hasattr(layer, 'image'):
                pil_img = layer.image
            elif hasattr(layer, 'getImage'):
                pil_img = layer.getImage()
            elif hasattr(layer, 'imageData'):
                pil_img = layer.imageData
            
            if pil_img is None:
                print(f"  skip {lname}: no image data")
                continue
            
            if not isinstance(pil_img, Image.Image):
                continue

            group_path = "/".join(slugify(p) for p in prefix)
            if group_path:
                final_dir = out_dir / group_path
                final_dir.mkdir(parents=True, exist_ok=True)
            else:
                final_dir = out_dir

            fname = slugify(lname) + ".png"
            fpath = final_dir / fname
            counter = 1
            base = fpath
            while fpath.exists() and counter < 20:
                # avoid collision, overwrite if same name for now
                break

            pil_img.save(fpath, "PNG")
            exported.append(fpath)
            print(f"  -> {fpath.relative_to(out_root)}")

        except Exception as e:
            print(f"  [error] layer {getattr(layer,'name','?')}: {e}")
            continue

    if export_flattened:
        try:
            flat = None
            if hasattr(doc, 'getImage'):
                flat = doc.getImage()
            elif hasattr(doc, 'image'):
                flat = doc.image
            if isinstance(flat, Image.Image):
                flat_path = out_dir / "_flattened.png"
                flat.save(flat_path)
                exported.append(flat_path)
                print(f"  -> flattened: {flat_path.name}")
        except Exception as e:
            print(f"  [flatten error] {e}")

    return exported

def git_commit_push(repo_path: Path, files, xcf_path: Path, push=True):
    repo_path = Path(repo_path)
    rel_files = []
    for f in files + [xcf_path]:
        try:
            rel = f.relative_to(repo_path)
            rel_files.append(str(rel))
        except ValueError:
            continue

    if not rel_files:
        print("[git] Nothing inside repo to commit")
        return

    if not (repo_path / ".git").exists():
        print(f"[git] {repo_path} is not a git repo!")
        return

    def run(cmd):
        print(f"$ {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stdout, result.stderr)
        return result

    run(["git", "add"] + rel_files)
    status = run(["git", "status", "--porcelain"] + rel_files)
    if not status.stdout.strip():
        print("[git] No changes to commit")
        return

    msg = f"auto: sync {xcf_path.name} layers @ {datetime.now().isoformat(timespec='seconds')}"
    run(["git", "commit", "-m", msg])
    if push:
        r = run(["git", "push"])
        if r.returncode == 0:
            print("[git] Pushed!")
        else:
            print("[git] Push failed - check credentials / remote")

class XcfHandler(FileSystemEventHandler):
    def __init__(self, repo_path, out_root, push, debounce=1.5):
        self.repo_path = Path(repo_path)
        self.out_root = Path(out_root)
        self.push = push
        self.debounce = debounce
        self._last = {}

    def on_modified(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() != ".xcf":
            return
        now = time.time()
        if p in self._last and now - self._last[p] < self.debounce:
            return
        self._last[p] = now
        time.sleep(0.8)
        print(f"\n[watch] Change detected: {p}")
        try:
            exported = export_xcf_layers(p, self.out_root)
            git_commit_push(self.repo_path, exported, p, push=self.push)
        except Exception as e:
            print(f"[watch] Failed: {e}")
            import traceback; traceback.print_exc()

def main():
    ap = argparse.ArgumentParser(description="Watch XCF and auto-sync layers to git")
    ap.add_argument("--xcf", type=str, help="Single XCF file to watch")
    ap.add_argument("--watch-dir", type=str, help="Directory to watch recursively for XCFs")
    ap.add_argument("--repo", type=str, required=True, help="Path to git repo root")
    ap.add_argument("--out", type=str, default=None, help="Output root for PNG layers (default: <repo>/assets/xcf_layers)")
    ap.add_argument("--push", action="store_true", help="Auto git push")
    ap.add_argument("--no-flatten", action="store_true", help="Don't export flattened composite")
    args = ap.parse_args()

    repo_path = Path(args.repo).resolve()
    out_root = Path(args.out).resolve() if args.out else repo_path / "assets" / "xcf_layers"
    out_root.mkdir(parents=True, exist_ok=True)

    if args.xcf:
        xcf_path = Path(args.xcf).resolve()
        print(f"Exporting once: {xcf_path}")
        exported = export_xcf_layers(xcf_path, out_root, export_flattened=not args.no_flatten)
        git_commit_push(repo_path, exported, xcf_path, push=args.push)
        watch_path = xcf_path.parent
    elif args.watch_dir:
        watch_path = Path(args.watch_dir).resolve()
        for xcf in watch_path.rglob("*.xcf"):
            exported = export_xcf_layers(xcf, out_root, export_flattened=not args.no_flatten)
            git_commit_push(repo_path, exported, xcf, push=args.push)
    else:
        print("Need --xcf or --watch-dir")
        return

    handler = XcfHandler(repo_path, out_root, push=args.push)
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()
    print(f"\n[watching] {watch_path} -> {out_root}")
    print("Save your XCF in GIMP and it will auto-push. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
