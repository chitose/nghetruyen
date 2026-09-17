# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web', 'web'),
        ('assets', 'assets'),
        # Just the launch script and its requirement list, not vieneu's own
        # dependencies -- see ADR-0016 and ADR-0019.
        ('../sidecar/server.py', 'sidecar'),
        ('../sidecar/requirements.txt', 'sidecar'),
        # Written by build.bat/release.yml from `git describe` right before
        # this runs -- see version.py. Missing it is a build-setup error, not
        # something to default around here.
        ('VERSION', '.'),
    ],
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
    name='NgheTruyen',
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
    icon=['assets/nghetruyen.ico'],
)
