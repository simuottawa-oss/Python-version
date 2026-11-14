# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import gmsh
from PyInstaller.utils.hooks import collect_submodules
project_root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(project_root / 'src' / 'main.py')],
    pathex=[str(project_root / 'src')],
    binaries=[(str(Path(gmsh.lib._name).resolve()), '.')],
    datas=[(str(project_root / 'Images'), 'Images'),
           (str(project_root / 'Assets'), 'Assets'),
           (str(project_root / 'src/simuo/resources/styles'), 'simuo/resources/styles')],
    hiddenimports=collect_submodules('skfem') + collect_submodules('simuo.structural'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SimuO',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
