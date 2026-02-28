import os
import sys
import shutil
import subprocess

# --- Build Script for TradeOpps Trader Companion ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER_APP = os.path.join(PROJECT_ROOT, 'trader_companion', 'trader_app.py')
LOGO_SRC = os.path.join(PROJECT_ROOT, 'trader_companion', 'logo.png')
UTILS_SRC = os.path.join(PROJECT_ROOT, 'utils')
DIST_DIR = os.path.join(PROJECT_ROOT, 'dist')
BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')

def get_version():
    """Extract version from trader_app.py"""
    with open(TRADER_APP, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('APP_VERSION'):
                return line.split('=')[1].strip().replace('"', '').replace("'", "")
    return '1.0.0'

VERSION = get_version()
BUILD_NAME = f'Trader_Companion_v{VERSION}'

# 1. Clean previous builds
print("Cleaning build directories...")
if os.path.exists(DIST_DIR):
    shutil.rmtree(DIST_DIR)
if os.path.exists(BUILD_DIR):
    shutil.rmtree(BUILD_DIR)

# 2. PyInstaller Command
print(f"Building {BUILD_NAME}...")

# Data includes:
# - utils folder -> utils/
# - logo.png -> . (root)
data_args = [
    f'--add-data={UTILS_SRC}{os.pathsep}utils',
    f'--add-data={LOGO_SRC}{os.pathsep}.'
]

cmd = [
    sys.executable, '-m', 'PyInstaller',
    '--noconfirm',
    '--onefile',
    '--windowed',
    '--clean',
    f'--name={BUILD_NAME}',
    f'--icon={LOGO_SRC}',
] + data_args + [TRADER_APP]

print("Running command:", " ".join(cmd))

try:
    subprocess.run(cmd, check=True)
    print(f"\n✅ Build SUCCESS! output: dist/{BUILD_NAME}.exe")
except subprocess.CalledProcessError as e:
    print(f"\n❌ Build FAILED: {e}")
    sys.exit(1)
