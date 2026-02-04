import os
import sys
import shutil
import subprocess

# --- Build Helper for MT5 Trader Companion ---
# This script ensures the utils folder is copied to the build directory and calls PyInstaller with correct options.

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

TRADER_APP = os.path.join(PROJECT_ROOT, 'trader_companion', 'trader_app.py')
UTILS_SRC = os.path.join(PROJECT_ROOT, 'utils')
DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')

# Read version from trader_app.py
def get_version():
    with open(TRADER_APP, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('APP_VERSION'):
                return line.split('=')[1].strip().replace('"', '').replace("'", '')
    return 'unknown'

APP_VERSION = get_version()
BUILD_NAME = f'MT5TraderCompanion_v{APP_VERSION}'

# Clean previous build
if os.path.exists(DIST_DIR):
    print('Cleaning previous dist...')
    shutil.rmtree(DIST_DIR)

# PyInstaller command
pyi_cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--onefile', '--windowed',
    f'--name={BUILD_NAME}',
    f'--add-data={UTILS_SRC}{os.pathsep}utils',
    TRADER_APP
]

print('Running PyInstaller...')
subprocess.run(pyi_cmd, check=True)

print(f'Build complete! Executable is in dist/{BUILD_NAME}.exe')
