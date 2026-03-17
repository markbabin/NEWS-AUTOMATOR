"""
Path resolution for News Monitor (Windows).
Handles both development (source) and bundled (PyInstaller) modes.

Bundled app layout:
  - Read-only assets (config.yaml) live inside the app bundle (sys._MEIPASS)
  - Writable data (transcripts, output, clips, settings) live in %APPDATA%/News Monitor

Development layout:
  - Everything lives alongside the source files
"""

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def get_bundle_dir() -> Path:
    """Directory containing bundled assets (config.yaml, etc.)."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_user_data_dir() -> Path:
    """Writable directory for user data (output, transcripts, clips, settings)."""
    if not is_frozen():
        return Path(__file__).parent

    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "News Monitor"


def get_ffmpeg_path() -> str:
    """Return path to ffmpeg binary — bundled first, then system PATH."""
    if is_frozen():
        bundled = get_bundle_dir() / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)
    return shutil.which("ffmpeg") or "ffmpeg"


def get_ffprobe_path() -> str:
    """Return path to ffprobe binary — bundled first, then system PATH."""
    if is_frozen():
        bundled = get_bundle_dir() / "ffprobe.exe"
        if bundled.exists():
            return str(bundled)
    return shutil.which("ffprobe") or "ffprobe"


def ensure_directories(data_dir: Path) -> None:
    """Create required subdirectories in the user data directory."""
    for subdir in ("input", "transcripts", "output", "clips"):
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)


def ensure_config(data_dir: Path) -> Path:
    """
    Ensure config.yaml exists in user data dir.
    On first run of a bundled app, copies the default from the bundle.
    Returns path to the config file.
    """
    user_config = data_dir / "config.yaml"

    if not user_config.exists():
        bundled_config = get_bundle_dir() / "config.yaml"
        if bundled_config.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled_config, user_config)
        else:
            raise FileNotFoundError("config.yaml not found in bundle or user data directory")

    return user_config


def save_api_key(data_dir: Path, key: str) -> None:
    """Persist API key to user data directory."""
    key_file = data_dir / ".api_key"
    key_file.write_text(key.strip())


def load_api_key(data_dir: Path) -> str:
    """Load saved API key, falling back to environment variable."""
    key_file = data_dir / ".api_key"
    if key_file.exists():
        key = key_file.read_text().strip()
        if key:
            return key
    return os.environ.get("ANTHROPIC_API_KEY", "")
