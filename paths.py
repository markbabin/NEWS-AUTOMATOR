"""
Path resolution for News Monitor.
Handles both development (source) and bundled (PyInstaller) modes.

Bundled app layout:
  - Read-only assets (config.yaml) live inside the app bundle (sys._MEIPASS)
  - Writable data (transcripts, output, clips, settings) live in a user data directory

Development layout:
  - Everything lives alongside the source files
"""

import os
import platform
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

    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    return base / "News Monitor"


def _find_binary(name: str) -> str:
    """Find a binary by name: PATH first, then common install locations, then bundled."""
    found = shutil.which(name)
    if found:
        return found
    # macOS apps launched from Finder don't inherit shell PATH —
    # check common Homebrew/system locations directly
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        candidate = Path(prefix) / name
        if candidate.exists():
            return str(candidate)
    # Fall back to bundled binary (inside PyInstaller bundle)
    if is_frozen():
        bundled = get_bundle_dir() / name
        if bundled.exists():
            return str(bundled)
    return name


def get_ffmpeg_path() -> str:
    """Return path to ffmpeg binary."""
    return _find_binary("ffmpeg")


def get_ffprobe_path() -> str:
    """Return path to ffprobe binary."""
    return _find_binary("ffprobe")


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
