"""Build the desktop package of the current platform with PyInstaller and pack it for a GitHub release.

Usage: python tools/build.py [--installer]

Outputs into dist/release:
    Odwolania2JSON-<version>-<platform>.zip|.tar.gz   portable package (config, input, output included)
    Odwolania2JSON-<version>-windows-setup.exe          Windows installer (with --installer, needs Inno Setup)
    Odwolania2JSON-<platform>.pack / .manifest.json     per-file pack for in-app patch updates (only changed files)
    *.sha256                                            checksums the updater and the download page show
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DIST = ROOT / "dist"
RELEASE = DIST / "release"
NAME = "Odwolania2JSON"


def version() -> str:
    """Read the version from the package."""
    text = (ROOT / "odwolania2json" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def platform_name() -> str:
    """Return windows, macos or linux."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def pyinstaller() -> Path:
    """Run PyInstaller in one-folder mode and return the built folder."""
    sep = os.pathsep
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", NAME,
            "--icon", str(ROOT / "packaging" / ("icon.ico" if platform_name() == "windows" else "icon.png")),
            "--add-data", f"{ROOT / 'odwolania2json' / 'web' / 'static'}{sep}odwolania2json/web/static",
            "--add-data", f"{ROOT / 'config'}{sep}config",
            "--collect-all", "rapidocr",
            "--collect-all", "onnxruntime",
            "--collect-submodules", "uvicorn",
            "--collect-all", "pypdfium2",
            "--collect-all", "pypdfium2_raw",
            "--collect-data", "wordfreq",
            "--collect-all", "morfeusz2",
            "--hidden-import", "odwolania2json.extractors",
            "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
            str(ROOT / "packaging" / "launcher.py"),
        ],
        check=True,
        cwd=ROOT,
    )
    app = DIST / NAME
    shutil.copytree(ROOT / "config", app / "config", dirs_exist_ok=True)
    for folder in ("input", "output"):
        (app / folder).mkdir(exist_ok=True)
    for script in ("README.md", "LICENSE"):
        if (ROOT / script).exists():
            shutil.copy2(ROOT / script, app / script)
    return app


def sha256(path: Path) -> str:
    """Hash a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum(path: Path) -> None:
    """Write <file>.sha256 next to a release file."""
    path.with_name(path.name + ".sha256").write_text(f"{sha256(path)}  {path.name}\n", encoding="utf-8")


def pack(app: Path) -> Path:
    """Pack the built folder into a zip (Windows) or tar.gz (others)."""
    RELEASE.mkdir(parents=True, exist_ok=True)
    base = RELEASE / f"{NAME}-{version()}-{platform_name()}"
    if platform_name() == "windows":
        target = Path(f"{base}.zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in app.rglob("*"):
                archive.write(file, Path(NAME) / file.relative_to(app))
    else:
        target = Path(f"{base}.tar.gz")
        with tarfile.open(target, "w:gz") as archive:
            archive.add(app, arcname=NAME)
    write_checksum(target)
    return target


def patch_assets(app: Path) -> None:
    """Write the pack and manifest used by in-app differential (patch) updates."""
    from odwolania2json.delta import build_pack

    build_pack(app, RELEASE, f"{NAME}-{platform_name()}", version())


def installer() -> Path:
    """Compile the Windows installer with Inno Setup."""
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    subprocess.run([iscc, f"/DAppVersion={version()}", str(ROOT / "packaging" / "installer.iss")], check=True, cwd=ROOT / "packaging")
    target = RELEASE / f"{NAME}-{version()}-windows-setup.exe"
    write_checksum(target)
    return target


def main(argv: list[str] | None = None) -> int:
    """Build, pack and optionally create the installer."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--installer", action="store_true", help="also build the Windows installer")
    args = parser.parse_args(argv)
    app = pyinstaller()
    print(pack(app))
    patch_assets(app)
    if args.installer and platform_name() == "windows":
        print(installer())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
