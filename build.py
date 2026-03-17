#!/usr/bin/env python3
"""
Build script — packages News Monitor into a standalone app using PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Produces:
    macOS:   dist/News Monitor.app
    Windows: dist/News Monitor/News Monitor.exe

Size budget (~10 GB max):
    Whisper large-v2 model: ~3 GB   (downloaded at runtime, NOT bundled)
    Python + all deps:      ~500 MB
    FFmpeg binaries:        ~80 MB  (bundled if present)
    App code + config:      ~1 MB
    Total bundle:           ~600 MB (model downloaded separately on first run)
"""

import platform
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Icon paths (create these files before building for a custom icon)
ICON_MAC = BASE_DIR / "icon.icns"
ICON_WIN = BASE_DIR / "icon.ico"

SEP = ";" if platform.system() == "Windows" else ":"


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name", "News Monitor",
    ]

    # macOS bundle identifier
    if platform.system() == "Darwin":
        cmd += ["--osx-bundle-identifier", "com.newsmonitor.app"]

    # Icon
    if platform.system() == "Darwin" and ICON_MAC.exists():
        cmd += ["--icon", str(ICON_MAC)]
    elif platform.system() == "Windows" and ICON_WIN.exists():
        cmd += ["--icon", str(ICON_WIN)]

    # Bundle all config*.yaml files
    for config_file in BASE_DIR.glob("config*.yaml"):
        cmd += ["--add-data", f"{config_file}{SEP}."]
        print(f"  Bundling config: {config_file.name}")

    # Bundle FFmpeg/FFprobe if present in project root
    for binary in ("ffmpeg", "ffprobe"):
        bin_path = BASE_DIR / binary
        if not bin_path.exists() and platform.system() == "Windows":
            bin_path = BASE_DIR / f"{binary}.exe"
        if bin_path.exists():
            cmd += ["--add-binary", f"{bin_path}{SEP}."]
            print(f"  Bundling {binary}: {bin_path}")
        else:
            print(f"  NOTE: {binary} not found in project root — will use system PATH at runtime")

    # customtkinter needs its assets collected
    cmd += ["--collect-all", "customtkinter"]

    # faster_whisper needs its VAD model asset bundled
    cmd += ["--collect-data", "faster_whisper"]

    # Hidden imports that PyInstaller often misses
    hidden_imports = [
        "anthropic",
        "faster_whisper",
        "openpyxl",
        "yaml",
        "tqdm",
        "PIL",
    ]
    for hi in hidden_imports:
        cmd += ["--hidden-import", hi]

    # Exclude heavy packages that aren't needed (keep bundle small)
    excludes = [
        "matplotlib",
        "scipy",
        "pandas",
        "notebook",
        "jupyterlab",
        "pytest",
        "setuptools",
    ]
    for ex in excludes:
        cmd += ["--exclude-module", ex]

    # Entry point
    cmd.append(str(BASE_DIR / "gui.py"))

    print("\nRunning PyInstaller:")
    print(" ".join(cmd))
    print()
    subprocess.run(cmd, check=True)

    print("\nBuild complete!")
    if platform.system() == "Darwin":
        app_path = BASE_DIR / "dist" / "News Monitor.app"
        print(f"  App: {app_path}")
        # Show size
        if app_path.exists():
            size = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file())
            print(f"  Size: {size / (1024**3):.2f} GB")
    else:
        print("  App: dist/News Monitor/News Monitor.exe")


if __name__ == "__main__":
    build()
