# PyInstaller build description for Linux and macOS.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(__file__).resolve().parents[1]
hiddenimports = collect_submodules("textual")

a = Analysis(
    [str(ROOT / "npl.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="npl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
