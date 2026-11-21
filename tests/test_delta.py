"""Differential (patch) updates download only changed files and never touch user folders."""

import json
import shutil

import pytest

from odwolania2json import delta


def make_app(root, version, extra=None):
    """Create a fake application folder."""
    (root / "_internal").mkdir(parents=True)
    (root / "_internal" / "big.bin").write_bytes(b"x" * 200_000)
    (root / "_internal" / "code.pyc").write_bytes(f"code {version}".encode())
    (root / "Odwolania2JSON").write_bytes(b"exe")
    (root / "config").mkdir()
    (root / "config" / "settings.yaml").write_text(f"user {version}")
    for name, content in (extra or {}).items():
        (root / name).write_bytes(content)


def local_reader(pack):
    """Range reader over a local pack file, counting requested bytes."""
    stats = {"bytes": 0}

    def read(url, start, end):
        stats["bytes"] += end - start + 1
        with open(pack, "rb") as handle:
            handle.seek(start)
            return handle.read(end - start + 1)

    return read, stats


def test_patch_downloads_only_changed_files(tmp_path):
    """Only the changed small file is fetched; the big unchanged file and user config are left alone."""
    installed = tmp_path / "installed"
    make_app(installed, "1", {"old.txt": b"stale"})
    release = tmp_path / "release_app"
    make_app(release, "2")
    pack, manifest_path = delta.build_pack(release, tmp_path / "dist", "Odwolania2JSON-linux", "0.2.0")
    manifest = json.loads(manifest_path.read_text())
    assert all(not e["path"].startswith("config/") for e in manifest["files"])

    plan = delta.plan(manifest, installed)
    assert [e["path"] for e in plan.changed] == ["_internal/code.pyc"]
    assert plan.removed == ["old.txt"]

    staging = tmp_path / "staging"
    reader, stats = local_reader(pack)
    delta.fetch(plan, "unused", staging, reader=reader)
    assert stats["bytes"] < 100
    shutil.copytree(staging, installed, dirs_exist_ok=True)
    assert (installed / "_internal" / "code.pyc").read_bytes() == b"code 2"
    assert (installed / "config" / "settings.yaml").read_text() == "user 1"
    assert delta.plan(manifest, installed).changed == []


def test_corrupted_download_is_rejected(tmp_path):
    """A pack whose content does not match the manifest checksum is refused."""
    release = tmp_path / "app"
    make_app(release, "2")
    pack, manifest_path = delta.build_pack(release, tmp_path / "dist", "x", "0.2.0")
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["sha256"] = "0" * 64
    plan = delta.plan(manifest, tmp_path / "empty")
    reader, _ = local_reader(pack)
    with pytest.raises(ValueError):
        delta.fetch(plan, "unused", tmp_path / "staging", reader=reader)


def test_manifest_paths_cannot_escape_install_dir(tmp_path):
    """Path traversal in a manifest is refused."""
    with pytest.raises(ValueError):
        delta.safe_path(tmp_path, "../evil.txt")


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX shell script")
def test_apply_script_moves_files_and_removes_stale(tmp_path):
    """The generated script waits for the given process, copies staged files in place and deletes stale ones."""
    import subprocess

    install = tmp_path / "app"
    (install / "_internal").mkdir(parents=True)
    (install / "_internal" / "code.pyc").write_bytes(b"old")
    (install / "stale.txt").write_text("x")
    staging = tmp_path / "upd" / "files"
    (staging / "_internal").mkdir(parents=True)
    (staging / "_internal" / "code.pyc").write_bytes(b"new")
    finished = subprocess.Popen(["true"])
    finished.wait()
    script = delta.apply_script(install, staging, ["stale.txt"], tmp_path / "missing-exe", pid=finished.pid)
    subprocess.run(["/bin/sh", str(script)], check=True, timeout=20)
    assert (install / "_internal" / "code.pyc").read_bytes() == b"new"
    assert not (install / "stale.txt").exists()
