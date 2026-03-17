#!/usr/bin/env python3
"""
Build script — packages News Monitor into a standalone Windows app using PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Produces:
    dist/News Monitor/News Monitor.exe

Prerequisites (Windows + NVIDIA GPU):
    - Python 3.11+
    - NVIDIA GPU with CUDA support
    - CUDA Toolkit 12.x installed (or let faster-whisper pull cuBLAS/cuDNN via pip)
    - FFmpeg binaries (ffmpeg.exe + ffprobe.exe) in project root for bundling
"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
ICON_WIN = BASE_DIR / "icon.ico"


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name", "News Monitor",
    ]

    # Icon
    if ICON_WIN.exists():
        cmd += ["--icon", str(ICON_WIN)]

    # Bundle config.yaml
    config_path = BASE_DIR / "config.yaml"
    if config_path.exists():
        cmd += ["--add-data", f"{config_path};."]

    # Bundle FFmpeg/FFprobe if present in project root
    for binary in ("ffmpeg.exe", "ffprobe.exe"):
        bin_path = BASE_DIR / binary
        if bin_path.exists():
            cmd += ["--add-binary", f"{bin_path};."]
            print(f"  Bundling {binary}: {bin_path}")
        else:
            print(f"  NOTE: {binary} not found in project root — will use system PATH at runtime")

    # customtkinter needs its assets collected
    cmd += ["--collect-all", "customtkinter"]

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
    print("  App: dist/News Monitor/News Monitor.exe")


if __name__ == "__main__":
    build()
