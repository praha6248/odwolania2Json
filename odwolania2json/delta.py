"""Differential updates: download only the files that changed since the installed version.

Release side (build_pack): every file of the built application folder is compressed on its own and appended to one
pack file; a manifest lists path, size, SHA-256 and the byte range of each file inside the pack.

App side (plan, fetch): installed files are hashed and compared with the manifest; only the byte ranges of changed or
missing files are requested from the pack with HTTP Range requests, decompressed and verified. The staged files are
then copied over the installation by a small script after the application exits (apply_script). User folders
(config, input, output) are never part of the manifest, so they are never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_DIRS = {"config", "input", "output", "traces", "logs"}
GAP = 64 * 1024
USER_AGENT = "odwolania2json-updater"


def sha256_file(path: Path) -> str:
    """Hash a file in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def app_files(root: Path) -> list[Path]:
    """List files of an application folder, skipping user data folders."""
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.relative_to(root).parts[0] not in USER_DIRS:
            files.append(path)
    return files


def build_pack(app_dir: Path, out_dir: Path, base_name: str, version: str) -> tuple[Path, Path]:
    """Write <base>.pack and <base>.manifest.json for an application folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_path = out_dir / f"{base_name}.pack"
    entries = []
    offset = 0
    with pack_path.open("wb") as pack:
        for path in app_files(app_dir):
            raw = path.read_bytes()
            blob = zlib.compress(raw, 6)
            pack.write(blob)
            entries.append({
                "path": path.relative_to(app_dir).as_posix(),
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "offset": offset,
                "length": len(blob),
                "mode": path.stat().st_mode & 0o777,
            })
            offset += len(blob)
    manifest = {"version": version, "pack": pack_path.name, "pack_size": offset, "files": entries}
    manifest_path = out_dir / f"{base_name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return pack_path, manifest_path


def safe_path(root: Path, relative: str) -> Path:
    """Resolve a manifest path inside root, refusing absolute paths and parent traversal."""
    target = (root / relative).resolve()
    if Path(relative).is_absolute() or ".." in Path(relative).parts or root.resolve() not in target.parents:
        raise ValueError(f"Unsafe path in manifest: {relative}")
    return target


@dataclass
class Plan:
    """Files to download and files to delete to reach the manifest version."""

    changed: list[dict[str, Any]]
    removed: list[str]
    total_files: int

    @property
    def download_bytes(self) -> int:
        """Compressed bytes that will be downloaded."""
        return sum(e["length"] for e in self.changed)


def plan(manifest: dict[str, Any], install_root: Path) -> Plan:
    """Compare installed files with a manifest; size is checked first, hashes only when sizes match."""
    changed = []
    wanted = set()
    for entry in manifest["files"]:
        wanted.add(entry["path"])
        target = safe_path(install_root, entry["path"])
        if not target.exists() or target.stat().st_size != entry["size"] or sha256_file(target) != entry["sha256"]:
            changed.append(entry)
    removed = [p.relative_to(install_root).as_posix() for p in app_files(install_root) if p.relative_to(install_root).as_posix() not in wanted]
    return Plan(changed, removed, len(manifest["files"]))


def groups(entries: list[dict[str, Any]], gap: int = GAP) -> list[list[dict[str, Any]]]:
    """Merge entries lying close together in the pack into one Range request."""
    out: list[list[dict[str, Any]]] = []
    for entry in sorted(entries, key=lambda e: e["offset"]):
        if out and entry["offset"] - (out[-1][-1]["offset"] + out[-1][-1]["length"]) <= gap:
            out[-1].append(entry)
        else:
            out.append([entry])
    return out


def read_range(url: str, start: int, end: int, timeout: float = 60) -> bytes:
    """Download bytes [start, end] of a remote file."""
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        if response.status == 200 and len(data) > end - start + 1:
            data = data[start:end + 1]
    if len(data) != end - start + 1:
        raise OSError(f"Range {start}-{end}: got {len(data)} bytes")
    return data


def fetch(plan_: Plan, pack_url: str, staging: Path, progress: Callable[[int, int], None] = lambda done, total: None,
          reader: Callable[[str, int, int], bytes] = read_range) -> None:
    """Download, decompress and verify the changed files into a staging folder."""
    total = plan_.download_bytes
    done = 0
    for group in groups(plan_.changed):
        start = group[0]["offset"]
        end = group[-1]["offset"] + group[-1]["length"] - 1
        chunk = reader(pack_url, start, end)
        for entry in group:
            blob = chunk[entry["offset"] - start: entry["offset"] - start + entry["length"]]
            raw = zlib.decompress(blob)
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError(f"Checksum mismatch: {entry['path']}")
            target = safe_path(staging, entry["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            os.chmod(target, entry.get("mode", 0o644) or 0o644)
            done += entry["length"]
            progress(done, total)


def apply_script(install_root: Path, staging: Path, removed: list[str], executable: Path, pid: int | None = None) -> Path:
    """Write a script that waits for the app to exit, copies staged files in place, deletes stale files and restarts."""
    pid = os.getpid() if pid is None else pid
    if sys.platform == "win32":
        script = staging.parent / "o2j_update.bat"
        deletes = "\n".join(f'del /f /q "{install_root / p}" 2>nul' for p in removed)
        script.write_text(
            "@echo off\n"
            f":wait\ntasklist /fi \"PID eq {pid}\" | find \"{pid}\" >nul && (timeout /t 1 /nobreak >nul & goto wait)\n"
            f'robocopy "{staging}" "{install_root}" /E /MOVE /NFL /NDL /NJH /NJS >nul\n'
            f"{deletes}\n"
            f'start "" "{executable}"\n'
            'del "%~f0"\n',
            encoding="utf-8",
        )
    else:
        script = staging.parent / "o2j_update.sh"
        deletes = "\n".join(f"rm -f '{install_root / p}'" for p in removed)
        script.write_text(
            "#!/bin/sh\n"
            f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done\n"
            f"cp -a '{staging}'/. '{install_root}'/ && rm -rf '{staging}'\n"
            f"{deletes}\n"
            f"nohup '{executable}' >/dev/null 2>&1 &\n"
            'rm -f "$0"\n',
            encoding="utf-8",
        )
        script.chmod(0o755)
    return script
