"""In-app update flow for the packaged desktop application, built on differential downloads (delta.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Any

from . import delta
from .update_check import check_for_update


def platform_name() -> str:
    """Return windows, macos or linux."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def install_root() -> Path | None:
    """Folder of the installed application, or None when running from source."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None


def _asset(info: dict[str, Any], suffix: str) -> dict[str, Any] | None:
    """Find the release asset of this platform with the given suffix."""
    return next((a for a in info.get("assets", []) if a["name"].endswith(f"-{platform_name()}{suffix}")), None)


class Updater:
    """Holds the state of one update: check, plan, download in the background, then restart to apply."""

    def __init__(self) -> None:
        """Start idle."""
        self.state: dict[str, Any] = {"stage": "idle"}
        self._lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        """Return the current state for the UI."""
        with self._lock:
            return dict(self.state)

    def _set(self, **values: Any) -> None:
        """Update the state atomically."""
        with self._lock:
            self.state.update(values)

    def check(self) -> dict[str, Any]:
        """Look for a newer release and, in the packaged app, compute how much would be downloaded."""
        info = check_for_update()
        result = {**info, "installed": install_root() is not None, "delta": None}
        root = install_root()
        manifest_asset = _asset(info, ".manifest.json")
        if info.get("available") and root and manifest_asset:
            request = urllib.request.Request(manifest_asset["url"], headers={"User-Agent": delta.USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                manifest = json.loads(response.read().decode())
            plan = delta.plan(manifest, root)
            result["delta"] = {"files": len(plan.changed), "bytes": plan.download_bytes, "total_files": plan.total_files}
            self._set(manifest=manifest, plan=plan, info=info)
        return result

    def start(self) -> dict[str, Any]:
        """Download the changed files in a background thread."""
        root = install_root()
        if root is None or "plan" not in self.state:
            return {"stage": "error", "error": "Aktualizacja w miejscu działa tylko w zainstalowanej aplikacji."}
        pack = _asset(self.state["info"], ".pack")
        if pack is None:
            return {"stage": "error", "error": "Wydanie nie zawiera paczki różnicowej."}
        staging = Path(tempfile.mkdtemp(prefix="o2j-update-")) / "files"
        staging.mkdir()
        self._set(stage="downloading", done=0, total=self.state["plan"].download_bytes, staging=str(staging))

        def run() -> None:
            try:
                delta.fetch(self.state["plan"], pack["url"], staging, lambda d, t: self._set(done=d, total=t))
                self._set(stage="ready")
            except Exception as exc:
                shutil.rmtree(staging.parent, ignore_errors=True)
                self._set(stage="error", error=str(exc))

        threading.Thread(target=run, daemon=True).start()
        return self.status()

    def restart(self) -> dict[str, Any]:
        """Launch the apply script and exit so files can be replaced."""
        if self.state.get("stage") != "ready":
            return {"stage": "error", "error": "Aktualizacja nie jest gotowa."}
        root = install_root()
        executable = Path(sys.executable)
        script = delta.apply_script(root, Path(self.state["staging"]), self.state["plan"].removed, executable)
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x00000008 | 0x00000200, close_fds=True)
        else:
            subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True)
        self._set(stage="restarting")
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return self.status()
