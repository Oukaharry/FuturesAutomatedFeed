# -*- mode: python ; coding: utf-8 -*-
import certifi

a = Analysis(
    ['C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\trader_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\utils', 'utils'),
        ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\logo.png', '.'),
        (certifi.where(), 'certifi'),
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
    name='BallerQuotes_Trader_Companion_v1.2.0',
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
    icon=['C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\logo.png'],
)
