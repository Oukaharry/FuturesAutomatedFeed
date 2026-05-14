# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\utils', 'utils'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\logo.png', '.'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\mt5_trading.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\tradovate.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\topstepx.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\prop_firm_manager.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\trade_limit_manager.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\broker_selection.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\mt5_dashboard_sync.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\mt5_comment_parser.py', 'trader_companion'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\signals', 'trader_companion/signals'), ('C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\strategies', 'trader_companion/strategies')]
binaries = []
hiddenimports = ['selenium', 'dotenv', 'psutil', 'pyperclip', 'pytz']
tmp_ret = collect_all('MetaTrader5')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('numpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\trader_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='TradeopssAI_v1.5.9',
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
    icon=['C:\\Users\\njihi\\Downloads\\Flask\\FuturesAutomatedFeed\\trader_companion\\logo.png'],
)
