"""Run build.py and write result to _build_result.txt"""
import subprocess, sys, os
os.chdir(r'C:\Users\harry\Music\MT5HedgingEngine')
result = subprocess.run(
    [sys.executable, 'build.py'],
    capture_output=True, text=True, timeout=600
)
with open('_build_result.txt', 'w') as f:
    f.write(f"RETURN CODE: {result.returncode}\n")
    f.write(f"STDOUT (last 2000 chars):\n{result.stdout[-2000:]}\n")
    f.write(f"STDERR (last 2000 chars):\n{result.stderr[-2000:]}\n")
    # Check exe
    exe = r'dist\Trader_Companion_v1.4.1.exe'
    if os.path.exists(exe):
        size = os.path.getsize(exe) / 1024 / 1024
        f.write(f"\nEXE EXISTS: {exe} ({size:.1f} MB)\n")
    else:
        f.write(f"\nEXE NOT FOUND\n")
print("Done - check _build_result.txt")
