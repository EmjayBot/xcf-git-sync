
"""
xcf_git_sync_selective.py - same watcher but with layer filters
Allows pulling only certain layers

New args:
  --include "Background,Hero"          -> only those names (comma list, substring match)
  --include-regex ".*_export$"         -> regex
  --group "Sprites/UI"                 -> only layers inside group path
  --tag-prefix "[GH]"                  -> only layers whose name starts with [GH] or @export
  --exclude "Sketch, WIP"
  --exclude-regex "^temp"
"""

import argparse, time, re, subprocess
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from gimpformats.gimpXcfDocument import GimpDocument, GimpGroup
from PIL import Image

def slugify(name): 
    import re
    name = re.sub(r'[^\w\- ]+', '', name.strip())
    return re.sub(r'\s+', '-', name)[:100] or "untitled"

def match_any(name, patterns):
    if not patterns: return False
    name_low = name.lower()
    for p in patterns:
        if p.lower() in name_low:
            return True
    return False

def match_regex_any(name, regexes):
    for rx in regexes:
        if rx.search(name):
            return True
    return False

def should_export(layer_path, layer_name, args):
    # layer_path = list of group names, e.g. ["Sprites","Hero"]
    full_path = "/".join(layer_path + [layer_name])
    
    # Tag prefix filter - common in game art pipelines
    if args.tag_prefix:
        if not layer_name.startswith(args.tag_prefix):
            return False

    # Group filter
    if args.group:
        # args.group is like "Sprites/UI" - require layer be inside that group path
        wanted_groups = [g.strip() for g in args.group.split(",")]
        if not any("/".join(layer_path).startswith(w) or w in "/".join(layer_path) for w in wanted_groups):
            # if group filter set, only allow if in that group
            return False

    # Include filters - if any include set, layer must match one
    if args.include or args.include_regex:
        inc = [s.strip() for s in args.include.split(",")] if args.include else []
        inc_rx = [re.compile(p) for p in args.include_regex.split(",")] if args.include_regex else []
        if not (match_any(layer_name, inc) or match_any(full_path, inc) or match_regex_any(layer_name, inc_rx) or match_regex_any(full_path, inc_rx)):
            return False

    # Exclude filters
    if args.exclude:
        exc = [s.strip() for s in args.exclude.split(",")]
        if match_any(layer_name, exc) or match_any(full_path, exc):
            return False
    if args.exclude_regex:
        exc_rx = [re.compile(p) for p in args.exclude_regex.split(",")]
        if match_regex_any(layer_name, exc_rx) or match_regex_any(full_path, exc_rx):
            return False

    return True

def export_xcf_layers(xcf_path: Path, out_root: Path, args):
    xcf_path = Path(xcf_path)
    out_dir = out_root / slugify(xcf_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[xcf] Parsing {xcf_path}")
    doc = GimpDocument(str(xcf_path))
    try:
        root = doc.walkTree()
        # walk
        stack = [(root, [])]
        exported=[]
        while stack:
            node, prefix = stack.pop()
            children = getattr(node, 'children', getattr(node, 'layers', [node]))
            for child in reversed(children):
                if isinstance(child, GimpGroup) or getattr(child, 'isGroup', False):
                    gname = getattr(child, 'name', 'group')
                    stack.append((child, prefix + [gname]))
                else:
                    lname = getattr(child, 'name', 'layer')
                    visible = getattr(child, 'visible', True)
                    if args.only_visible and not visible:
                        continue
                    if not should_export(prefix, lname, args):
                        print(f"  skip (filter): {'/'.join(prefix+[lname])}")
                        continue
                    pil_img = getattr(child, 'image', None) or getattr(child, 'getImage', lambda: None)()
                    if not isinstance(pil_img, Image.Image):
                        continue
                    group_path = "/".join(slugify(p) for p in prefix)
                    final_dir = out_dir / group_path if group_path else out_dir
                    final_dir.mkdir(parents=True, exist_ok=True)
                    fpath = final_dir / (slugify(lname) + ".png")
                    pil_img.save(fpath, "PNG")
                    exported.append(fpath)
                    print(f"  -> {fpath.relative_to(out_root)}")
        return exported
    except Exception as e:
        print(f"[error] {e}")
        import traceback; traceback.print_exc()
        return []

# Git helpers (same as before)
def git_commit_push(repo_path: Path, files, xcf_path: Path, push=True):
    repo_path = Path(repo_path)
    rel_files=[]
    for f in files + [xcf_path]:
        try: rel_files.append(str(f.relative_to(repo_path)))
        except: continue
    if not rel_files: return
    def run(cmd):
        r=subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
        if r.returncode!=0: print(r.stdout, r.stderr)
        return r
    run(["git","add"]+rel_files)
    status=run(["git","status","--porcelain"]+rel_files)
    if not status.stdout.strip():
        print("[git] No changes")
        return
    msg=f"auto: sync {xcf_path.name} filtered @ {datetime.now().isoformat(timespec='seconds')}"
    run(["git","commit","-m",msg])
    if push:
        run(["git","push"])

class XcfHandler(FileSystemEventHandler):
    def __init__(self, repo, out_root, args):
        self.repo=Path(repo); self.out_root=Path(out_root); self.args=args; self._last={}
    def on_modified(self, event):
        if event.is_directory: return
        p=Path(event.src_path)
        if p.suffix.lower()!=".xcf": return
        now=time.time()
        if p in self._last and now-self._last[p]<1.5: return
        self._last[p]=now
        time.sleep(0.8)
        print(f"\n[watch] {p}")
        exported=export_xcf_layers(p, self.out_root, self.args)
        git_commit_push(self.repo, exported, p, push=self.args.push)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--xcf", type=str)
    ap.add_argument("--watch-dir", type=str)
    ap.add_argument("--repo", required=True, type=str)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--only-visible", action="store_true", default=True)
    ap.add_argument("--include", type=str, help="Comma list substrings to INCLUDE, e.g. 'Hero,Background'")
    ap.add_argument("--include-regex", type=str, help="Comma list regex, e.g. '.*_export$,^UI_'")
    ap.add_argument("--exclude", type=str, help="Comma list to EXCLUDE")
    ap.add_argument("--exclude-regex", type=str)
    ap.add_argument("--group", type=str, help="Only from group(s), e.g. 'Sprites' or 'Sprites,UI'")
    ap.add_argument("--tag-prefix", type=str, help="Only layers starting with this, e.g. '[GH]' or '@export'")
    args=ap.parse_args()
    repo=Path(args.repo).resolve()
    out_root=Path(args.out).resolve() if args.out else repo/"assets"/"xcf_layers"
    out_root.mkdir(parents=True, exist_ok=True)
    watch_path=None
    if args.xcf:
        x=Path(args.xcf).resolve()
        export_xcf_layers(x, out_root, args)
        git_commit_push(repo, [], x, push=args.push)
        watch_path=x.parent
    elif args.watch_dir:
        watch_path=Path(args.watch_dir).resolve()
        for f in watch_path.rglob("*.xcf"):
            export_xcf_layers(f, out_root, args)
    else:
        print("need --xcf or --watch-dir"); return
    handler=XcfHandler(repo, out_root, args)
    obs=Observer(); obs.schedule(handler, str(watch_path), recursive=True); obs.start()
    print(f"[watching] {watch_path} filter={args.include or args.include_regex or args.tag_prefix or args.group or 'ALL'}")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()

if __name__=="__main__": main()
