# PyInstaller build of the desktop package: one folder with two executables sharing the same libraries.
#   Odwolania2JSON(.exe)       window application, no console window on Windows
#   odwolania2json-cli(.exe)   console program for the command line (run, extract, eval, check, anonymize, ...)
# Built by tools/build.py; run directly with: pyinstaller --noconfirm --clean packaging/odwolania2json.spec

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
NAME = "Odwolania2JSON"
ICON = str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.png"))

datas = [(str(ROOT / "odwolania2json" / "web" / "static"), "odwolania2json/web/static"), (str(ROOT / "config"), "config")]
if sys.platform.startswith("linux"):
    datas += [(str(ROOT / "packaging" / name), "packaging") for name in ("linux_window.py", "icon.png")]
binaries = []
hiddenimports = ["odwolania2json.extractors"]
for package in ("rapidocr", "onnxruntime", "pypdfium2", "pypdfium2_raw", "morfeusz2"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
if sys.platform == "win32":
    hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium"]
    datas += collect_data_files("webview", includes=["js/**", "lib/**"])
hiddenimports += collect_submodules("uvicorn")
datas += collect_data_files("wordfreq")

analysis = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas, hiddenimports=hiddenimports)
pyz = PYZ(analysis.pure)
window = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=ICON)
console = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="odwolania2json-cli", console=True, icon=ICON)
COLLECT(window, console, analysis.binaries, analysis.datas, name=NAME)
