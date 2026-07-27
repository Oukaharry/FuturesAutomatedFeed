import argparse
import os
import re
import shutil
import subprocess
import sys

# --- Build Script for TradeOpssAI / Tradeopss (trader) ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER_APP_SRC = os.path.join(PROJECT_ROOT, 'trader_companion', 'trader_app.py')
LOGO_SRC = os.path.join(PROJECT_ROOT, 'trader_companion', 'logo.png')
UTILS_SRC = os.path.join(PROJECT_ROOT, 'utils')
CONNECTORS_SRC = os.path.join(PROJECT_ROOT, 'connectors')
TRADER_COMPANION_DIR = os.path.join(PROJECT_ROOT, 'trader_companion')
DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')
BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')
STAGE_DIR = os.path.join(BUILD_DIR, '_stage')

# ML-only signal artifacts — omitted from trader (no-AI) builds.
TRADER_EXCLUDE_SIGNALS = frozenset({
    'ml_model_ustech_m5.pkl',
    'ml_prediction_journal_ustech.jsonl',
    'sim_batch_history.jsonl',
    'trade_sim_journal.jsonl',
    '__pycache__',
})


def get_version(app_path):
    """Extract APP_VERSION from trader_app.py."""
    with open(app_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('APP_VERSION'):
                value = line.split('=', 1)[1]
                value = value.split('#', 1)[0]
                return value.strip().replace('"', '').replace("'", "")
    return '1.0.0'


def stage_trader_app(trader_release: bool) -> str:
    """Write a staged trader_app.py (optionally with RELEASE_DISABLE_ML=True)."""
    with open(TRADER_APP_SRC, 'r', encoding='utf-8') as f:
        content = f.read()
    if trader_release:
        content, n = re.subn(
            r'^RELEASE_DISABLE_ML\s*=\s*False\b',
            'RELEASE_DISABLE_ML = True',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RuntimeError('Could not patch RELEASE_DISABLE_ML in trader_app.py')
    os.makedirs(STAGE_DIR, exist_ok=True)
    staged = os.path.join(STAGE_DIR, 'trader_app.py')
    with open(staged, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    return staged


def stage_signals_dir(trader_release: bool) -> str | None:
    """Copy signals/ to staging; strip ML-only files for trader builds."""
    src_dir = os.path.join(TRADER_COMPANION_DIR, 'signals')
    if not os.path.isdir(src_dir):
        return None
    dst_dir = os.path.join(STAGE_DIR, 'trader_companion', 'signals')
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    shutil.copytree(
        src_dir,
        dst_dir,
        ignore=shutil.ignore_patterns(*TRADER_EXCLUDE_SIGNALS) if trader_release else None,
    )
    return dst_dir


def build(trader_release: bool = False):
    trader_app = stage_trader_app(trader_release)
    version = get_version(trader_app)
    build_name = f'Tradeopss_v{version}' if trader_release else f'TradeopssAI_v{version}'

    print("Cleaning build directories...")
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
            except PermissionError:
                print(f"Warning: Could not remove {d}, continuing anyway...")

    # Re-stage after clean (clean removed _stage)
    trader_app = stage_trader_app(trader_release)
    staged_signals = stage_signals_dir(trader_release)

    print(f"Building {build_name}...")
    if trader_release:
        print("  Profile: TRADER (RELEASE_DISABLE_ML=True, no sklearn bundle)")

    data_args = [
        f'--add-data={UTILS_SRC}{os.pathsep}utils',
        f'--add-data={LOGO_SRC}{os.pathsep}.',
        f'--add-data={CONNECTORS_SRC}{os.pathsep}connectors',
    ]

    for module in [
        'mt5_trading.py', 'mt5_symbol_policy.py', 'mt5_market_feed.py', 'm1_bars_sync.py', 'tradovate.py',
        'topstepx.py', 'prop_firm_manager.py', 'trade_limit_manager.py',
        'broker_selection.py', 'mt5_dashboard_sync.py', 'mt5_comment_parser.py',
        'fundednext.py',
    ]:
        src = os.path.join(TRADER_COMPANION_DIR, module)
        if os.path.exists(src):
            data_args.append(f'--add-data={src}{os.pathsep}trader_companion')

    if staged_signals:
        data_args.append(f'--add-data={staged_signals}{os.pathsep}trader_companion/signals')
    else:
        src_dir = os.path.join(TRADER_COMPANION_DIR, 'signals')
        if os.path.isdir(src_dir):
            data_args.append(f'--add-data={src_dir}{os.pathsep}trader_companion/signals')

    for subdir in ['strategies', 'utils']:
        src_dir = os.path.join(TRADER_COMPANION_DIR, subdir)
        if os.path.isdir(src_dir):
            data_args.append(f'--add-data={src_dir}{os.pathsep}trader_companion/{subdir}')

    collect_all = ['MetaTrader5', 'numpy', 'pandas', 'selenium', 'certifi', 'playwright']
    if not trader_release:
        collect_all.extend(['scipy', 'sklearn', 'joblib'])

    hidden_imports = [
        'selenium', 'dotenv', 'psutil', 'pyperclip', 'pytz', 'zoneinfo',
        'requests', 'urllib3', 'certifi',
        'playwright', 'playwright.async_api', 'playwright.sync_api',
        'connectors.alphatrader_connector', 'connectors.blackarrow_connector',
    ]
    if not trader_release:
        hidden_imports.extend([
            'sklearn',
            'sklearn.ensemble',
            'sklearn.ensemble._hist_gradient_boosting',
            'sklearn.neural_network',
            'sklearn.pipeline',
            'sklearn.preprocessing',
            'sklearn.impute',
            'joblib',
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
        ])

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--onefile', '--windowed', '--clean',
        f'--name={build_name}',
        f'--icon={LOGO_SRC}',
    ]
    for pkg in collect_all:
        cmd.append(f'--collect-all={pkg}')
    for mod in hidden_imports:
        cmd.append(f'--hidden-import={mod}')
    cmd.extend(data_args)
    cmd.append(trader_app)

    print("Running command:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        exe_path = os.path.join(DIST_DIR, f'{build_name}.exe')
        print(f"\nBuild SUCCESS! output: {exe_path}")
        if os.path.isfile(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"Size: {size_mb:.1f} MB")
    except subprocess.CalledProcessError as e:
        print(f"\nBuild FAILED: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Build Tradeopss desktop exe')
    parser.add_argument(
        '--trader',
        action='store_true',
        help='Trader release: no ML/AI (RELEASE_DISABLE_ML), outputs Tradeopss_v*.exe',
    )
    args = parser.parse_args()
    build(trader_release=args.trader)


if __name__ == '__main__':
    main()
