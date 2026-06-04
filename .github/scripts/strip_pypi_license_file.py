#!/usr/bin/env python3
"""Remove Metadata 2.4 ``License-File`` lines that PyPI upload still rejects."""

from __future__ import annotations

import argparse
import io
import re
import tarfile
import zipfile
from pathlib import Path

_STRIP_LINES = re.compile(
    r"^(License-File:|Dynamic: license-file)\s*.+\n?",
    re.MULTILINE,
)


def _clean_metadata(text: str) -> str:
    return _STRIP_LINES.sub("", text)


def _patch_wheel(path: Path) -> None:
    buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith(".dist-info/METADATA"):
                cleaned = _clean_metadata(data.decode()).encode()
                if cleaned != data:
                    changed = True
                    data = cleaned
            zout.writestr(info, data)
    if changed:
        path.write_bytes(buf.getvalue())


def _patch_sdist(path: Path) -> None:
    if not path.name.endswith(".tar.gz"):
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tarfile.open(path, "r:gz") as src, tarfile.open(tmp, "w:gz") as dst:
        for member in src.getmembers():
            fileobj = src.extractfile(member)
            if fileobj is not None and member.name.endswith("/PKG-INFO"):
                raw = fileobj.read()
                cleaned = _clean_metadata(raw.decode()).encode()
                if cleaned != raw:
                    member.size = len(cleaned)
                    dst.addfile(member, io.BytesIO(cleaned))
                    continue
            if fileobj is not None:
                dst.addfile(member, fileobj)
            else:
                dst.addfile(member)
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    for artifact in args.artifacts:
        if artifact.suffix == ".whl":
            _patch_wheel(artifact)
        elif artifact.name.endswith(".tar.gz"):
            _patch_sdist(artifact)


if __name__ == "__main__":
    main()
