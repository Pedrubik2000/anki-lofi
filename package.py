#!/usr/bin/env python3
"""Build lofi-<version>.ankiaddon from this folder.

Usage: python package.py [--version 1.2.0] [--out DIR]
The version defaults to manifest.json's human_version (a leading "v" is dropped, so a
git tag can be passed as is). Output goes to dist/ next to this file.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
EXCLUDED_TOP = {".git", ".github", "dist", "package.py", "meta.json", ".gitignore"}
EXCLUDED_FILES = {"user_files/state.json"}


def _included(rel: Path) -> bool:
    if rel.parts[0] in EXCLUDED_TOP or rel.as_posix() in EXCLUDED_FILES:
        return False
    return "__pycache__" not in rel.parts and rel.suffix != ".pyc"


def build(version: str | None, out_dir: Path) -> Path:
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    version = (version or manifest["human_version"]).removeprefix("v")
    manifest["human_version"] = version
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{manifest['package']}-{version}.ankiaddon"
    # .ankiaddon = zip with the add-on's files at the root (no top folder)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SRC.rglob("*")):
            rel = path.relative_to(SRC)
            if path.is_dir() or not _included(rel):
                continue
            if rel.as_posix() == "manifest.json":
                zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
            else:
                zf.write(path, rel.as_posix())
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version")
    ap.add_argument("--out", type=Path, default=SRC / "dist")
    args = ap.parse_args()
    print(build(args.version, args.out))
