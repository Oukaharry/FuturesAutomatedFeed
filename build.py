import os
import sys
import shutil
import subprocess

# --- Build Script for TradeOpssAI ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER_APP = os.path.join(PROJECT_ROOT, 'trader_companion', 'trader_app.py')
LOGO_SRC = os.path.join(PROJECT_ROOT, 'trader_companion', 'logo.png')
UTILS_SRC = os.path.join(PROJECT_ROOT, 'utils')
TRADER_COMPANION_DIR = os.path.join(PROJECT_ROOT, 'trader_companion')
DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')
BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')


def get_version():
    """Extract version from trader_app.py"""
    with open(TRADER_APP, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('APP_VERSION'):
                value = line.split('=', 1)[1]
                value = value.split('#', 1)[0]  # drop inline comment
                return value.strip().replace('"', '').replace("'", "")
    return '1.0.0'


VERSION = get_version()
BUILD_NAME = f'TradeopssAI_v{VERSION}'

# 1. Clean previous builds
print("Cleaning build directories...")
for d in [DIST_DIR, BUILD_DIR]:
    if os.path.exists(d):
        try:
            shutil.rmtree(d)
        except PermissionError:
            print(f"Warning: Could not remove {d}, continuing anyway...")

# 2. PyInstaller Command
print(f"Building {BUILD_NAME}...")

# Data includes:
# - utils folder -> utils/
# - logo.png -> . (root)
# - trading engine modules -> trader_companion/
data_args = [
    f'--add-data={UTILS_SRC}{os.pathsep}utils',
    f'--add-data={LOGO_SRC}{os.pathsep}.',
]

# Bundle all trading engine modules from trader_companion/
for module in [
    'mt5_trading.py', 'mt5_market_feed.py', 'm1_bars_sync.py', 'tradovate.py',
    'topstepx.py', 'prop_firm_manager.py', 'trade_limit_manager.py',
    'broker_selection.py', 'mt5_dashboard_sync.py', 'mt5_comment_parser.py',
    'fundednext.py',
]:
    src = os.path.join(TRADER_COMPANION_DIR, module)
    if os.path.exists(src):
        data_args.append(f'--add-data={src}{os.pathsep}trader_companion')

# Bundle signals/ and strategies/ directories (includes ml_direction, trade_simulator, …)
for subdir in ['signals', 'strategies', 'utils']:
    src_dir = os.path.join(TRADER_COMPANION_DIR, subdir)
    if os.path.isdir(src_dir):
        data_args.append(f'--add-data={src_dir}{os.pathsep}trader_companion/{subdir}')

# collect-all pulls binaries + hidden imports for heavy native/Python packages
collect_all = [
    'MetaTrader5',
    'numpy',
    'pandas',
    'scipy',
    'sklearn',
    'joblib',
    'selenium',
    'certifi',
]

hidden_imports = [
    'selenium',
    'dotenv',
    'psutil',
    'pyperclip',
    'pytz',
    'zoneinfo',
    'requests',
    'urllib3',
    'certifi',
    # ML ensemble (signals/ml_direction.py)
    'sklearn',
    'sklearn.ensemble',
    'sklearn.ensemble._hist_gradient_boosting',
    'sklearn.neural_network',
    'sklearn.pipeline',
    'sklearn.preprocessing',
    'sklearn.impute',
    'joblib',
    # Self-learning + simulation stack
    'trader_companion.signals.ml_direction',
    'trader_companion.signals.prediction_tracker',
    'trader_companion.signals.trade_simulator',
    'trader_companion.signals.strategy_tester_chart',
    'trader_companion.signals.trade_learning_journal',
    'trader_companion.signals.indicator_optimizer',
    'trader_companion.signals.price_data',
    'signals.ml_direction',
    'signals.prediction_tracker',
    'signals.trade_simulator',
    'signals.strategy_tester_chart',
    'signals.trade_learning_journal',
    'signals.indicator_optimizer',
    'signals.price_data',
]

cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--noconfirm',
    '--onefile',
    '--windowed',
    '--clean',
    f'--name={BUILD_NAME}',
    f'--icon={LOGO_SRC}',
]
for pkg in collect_all:
    cmd.append(f'--collect-all={pkg}')
for mod in hidden_imports:
    cmd.append(f'--hidden-import={mod}')
cmd.extend(data_args)
cmd.append(TRADER_APP)

print("Running command:", " ".join(cmd))

try:
    subprocess.run(cmd, check=True)
    exe_path = os.path.join(DIST_DIR, f'{BUILD_NAME}.exe')
    print(f"\nBuild SUCCESS! output: {exe_path}")
    if os.path.isfile(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"Size: {size_mb:.1f} MB")
except subprocess.CalledProcessError as e:
    print(f"\nBuild FAILED: {e}")
    sys.exit(1)
