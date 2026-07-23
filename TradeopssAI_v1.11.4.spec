# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:\\Users\\harry\\Music\\MT5HedgingEngine\\utils', 'utils'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\logo.png', '.'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\connectors', 'connectors'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\mt5_trading.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\mt5_market_feed.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\m1_bars_sync.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\tradovate.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\topstepx.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\prop_firm_manager.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\trade_limit_manager.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\broker_selection.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\mt5_dashboard_sync.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\mt5_comment_parser.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\fundednext.py', 'trader_companion'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\build\\_stage\\trader_companion\\signals', 'trader_companion/signals'), ('C:\\Users\\harry\\Music\\MT5HedgingEngine\\trader_companion\\strategies', 'trader_companion/strategies')]
binaries = []
hiddenimports = ['selenium', 'dotenv', 'psutil', 'pyperclip', 'pytz', 'zoneinfo', 'requests', 'urllib3', 'certifi', 'playwright', 'playwright.async_api', 'playwright.sync_api', 'connectors.alphatrader_connector', 'connectors.blackarrow_connector', 'sklearn', 'sklearn.ensemble', 'sklearn.ensemble._hist_gradient_boosting', 'sklearn.neural_network', 'sklearn.pipeline', 'sklearn.preprocessing', 'sklearn.impute', 'joblib', 'trader_companion.signals.ml_direction', 'trader_companion.signals.prediction_tracker', 'trader_companion.signals.trade_simulator', 'trader_companion.signals.strategy_tester_chart', 'trader_companion.signals.trade_learning_journal', 'trader_companion.signals.indicator_optimizer', 'trader_companion.signals.price_data', 'signals.ml_direction', 'signals.prediction_tracker', 'signals.trade_simulator', 'signals.strategy_tester_chart', 'signals.trade_learning_journal', 'signals.indicator_optimizer', 'signals.price_data']
tmp_ret = collect_all('MetaTrader5')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('numpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('selenium')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('scipy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sklearn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('joblib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\harry\\Music\\MT5HedgingEngine\\build\\_stage\\trader_app.py'],
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
    name='TradeopssAI_v1.11.4',
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
