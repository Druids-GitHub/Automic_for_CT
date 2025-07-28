# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ZTP_GUI.py'],
    pathex=[],
    binaries=[],
    datas=[('ZTP_CONFIG_TEST.py', '.'), ('admin_manifest.xml', '.'), ('ztp_icon.ico', '.')],
    hiddenimports=['psutil'],
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
    name='ZTP',
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
    icon=['ztp_icon.ico'],
    manifest='admin_manifest.xml',
)
