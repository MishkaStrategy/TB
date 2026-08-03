#!/usr/bin/env python3
"""Validate and safely stage a CI-built Telegram Mini App artifact."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def safe_relative(name: str) -> Path:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe artifact path: {name}")
    return Path(*path.parts)


def copy_directory(source: Path, output: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"artifact symlink is not allowed: {path}")
        relative = path.relative_to(source)
        target = output / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        else:
            raise ValueError(f"unsupported artifact entry: {path}")


def extract_zip(source: Path, output: Path) -> None:
    total = 0
    with zipfile.ZipFile(source) as archive:
        for item in archive.infolist():
            relative = safe_relative(item.filename)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"artifact symlink is not allowed: {item.filename}")
            total += item.file_size
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError("artifact expands beyond the size limit")
            target = output / relative
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source_file, target.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)


def extract_tar(source: Path, output: Path) -> None:
    total = 0
    with tarfile.open(source, "r:*") as archive:
        for item in archive.getmembers():
            relative = safe_relative(item.name)
            if item.issym() or item.islnk() or item.isdev():
                raise ValueError(f"unsafe artifact member: {item.name}")
            total += item.size
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError("artifact expands beyond the size limit")
            target = output / relative
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not item.isfile():
                raise ValueError(f"unsupported artifact member: {item.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source_file = archive.extractfile(item)
            if source_file is None:
                raise ValueError(f"cannot read artifact member: {item.name}")
            with source_file, target.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)


def validate_manifest(output: Path, commit: str, domain: str, api_base_url: str) -> None:
    index = output / "index.html"
    manifest_path = output / "manifest.json"
    if not index.is_file():
        raise ValueError("artifact does not contain index.html")
    if not manifest_path.is_file():
        raise ValueError("artifact does not contain manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "commit": commit,
        "domain": domain,
        "apiBaseUrl": api_base_url,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"manifest {key} does not match the approved deployment")
    built_at = manifest.get("builtAt")
    if not isinstance(built_at, str) or not built_at.endswith("Z"):
        raise ValueError("manifest builtAt must be a UTC ISO timestamp")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--api-base-url", required=True)
    args = parser.parse_args()
    if not SHA_PATTERN.fullmatch(args.commit):
        raise ValueError("expected commit must be a full lowercase SHA-1")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("artifact output directory must be empty")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.artifact.is_dir():
        copy_directory(args.artifact, args.output)
    elif zipfile.is_zipfile(args.artifact):
        extract_zip(args.artifact, args.output)
    elif tarfile.is_tarfile(args.artifact):
        extract_tar(args.artifact, args.output)
    else:
        raise ValueError("artifact must be a directory, ZIP, or tar archive")
    validate_manifest(args.output, args.commit, args.domain, args.api_base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
