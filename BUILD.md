# How to build / run

1. Clone or copy this folder into your git repo
2. pip install -r requirements.txt
3. Test export once (no push):
   python xcf_git_sync_selective.py --xcf /path/to/file.xcf --repo /path/to/repo
4. Check assets/xcf_layers/<name>/ for PNGs
5. Enable auto-push:
   python xcf_git_sync_selective.py --xcf /path/to/file.xcf --repo /path/to/repo --push --tag-prefix "[GH]"
6. Keep it running while you work in GIMP. Every Save triggers export + push.

Troubleshooting:
- No image data? Your GIMP is 3.0 format, gimpformats supports up to 2.10. Use headless export via gimp -i batch.
- Git push fails? Set up git credential manager or set GITHUB_TOKEN env var.
- Too many commits? Increase debounce from 1.5 to 3.0 sec in XcfHandler.