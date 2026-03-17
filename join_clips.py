"""
Join clips module.
After individual clips are cut, joins them into combined videos:
  - Qualification: all qualification jumps in chronological order
  - Run 1: all first-round Slovenian jumps in chronological order
  - Run 2: all second-round Slovenian jumps in chronological order
  - Victory Ceremony: podium ceremony clips (only if Slovenians placed top 3)
"""

import subprocess
import tempfile
from pathlib import Path

from paths import get_ffmpeg_path


def get_clips_sorted(clips_dir: Path, topic_dir_name: str) -> list[Path]:
    """Get all clips for a topic, sorted by filename (which includes timecode)."""
    topic_dir = clips_dir / topic_dir_name
    if not topic_dir.exists():
        return []
    return sorted(topic_dir.glob("*.mp4"))


def join_clips_ffmpeg(clips: list[Path], output_path: Path) -> bool:
    """
    Join multiple video clips into a single video using FFmpeg concat demuxer.
    Returns True on success.
    """
    if not clips:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write concat file list
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for clip in clips:
            escaped = str(clip).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        concat_file = Path(f.name)

    try:
        cmd = [
            get_ffmpeg_path(), "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Fallback: re-encode if stream copy fails (different codecs/resolutions)
            cmd_reencode = [
                get_ffmpeg_path(), "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                str(output_path),
            ]
            print("    Stream copy failed, re-encoding...")
            result = subprocess.run(cmd_reencode, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"    Re-encode failed: {result.stderr[-300:]}")
                return False
        return True
    finally:
        concat_file.unlink(missing_ok=True)


def join_all(clips_dir: Path, date_str: str) -> dict[str, Path]:
    """
    Join individual clips into combined videos for Run 1, Run 2, and Victory Ceremony.
    Looks for clip directories matching the topic names from config_skijumping.yaml.

    Returns dict of {"label": Path} for successfully created files.
    """
    joined_dir = clips_dir / "_joined"
    created = {}

    # Map topic directory names (sanitized) to output filenames
    join_map = {
        "Kvalifikacije": ("Kvalifikacije", f"{date_str}_kvalifikacije.mp4"),
        "Skok_1._serija": ("1. serija", f"{date_str}_1_serija.mp4"),
        "Skok_2._serija": ("2. serija", f"{date_str}_2_serija.mp4"),
        "Podelitev": ("Podelitev", f"{date_str}_podelitev.mp4"),
    }

    for topic_dir_name, (label, output_filename) in join_map.items():
        clips = get_clips_sorted(clips_dir, topic_dir_name)
        if not clips:
            continue

        output_path = joined_dir / output_filename
        print(f"    Joining {len(clips)} clips → {output_filename}")

        if join_clips_ffmpeg(clips, output_path):
            created[label] = output_path
            print(f"    Created: {output_path}")
        else:
            print(f"    Failed to join clips for {label}")

    return created
