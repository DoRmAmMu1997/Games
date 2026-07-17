# -*- mode: python ; coding: utf-8 -*-

# PyInstaller reads this file to build a single windowed executable. The app
# window draws most art procedurally, while the bundled Windows executable uses
# `ludo_icon.ico` for its file/taskbar icon.


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # Bundle the icon so the running window can load it via _resource_path.
    datas=[('ludo_icon.ico', '.')],
    hiddenimports=[],
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
    name='Ludo Game',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # open as a normal desktop app without a terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ludo_icon.ico'],
)
