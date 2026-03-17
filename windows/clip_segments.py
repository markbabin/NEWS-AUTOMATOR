"""
Clip extraction module.
Cuts detected topic segments from the source video and saves them as MP4 files.
"""

import subprocess
from pathlib import Path

from paths import get_ffmpeg_path


def clip_segment(
    video_path: Path,
    output_path: Path,
    start: str,
    end: str,
) -> bool:
    """
    Extract a segment from a video file using FFmpeg.
    start/end are HH:MM:SS strings.
    Returns True on success.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        get_ffmpeg_path(), "-y",
        "-ss", start,
        "-to", end,
        "-i", str(video_path),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    FFmpeg error: {result.stderr[-200:]}")
        return False
    return True


def clip_all_segments(
    video_path: Path,
    clips_dir: Path,
    date_str: str,
    show: str,
    topic_segments: dict[str, list[dict]],
) -> int:
    """
    Cut all detected segments from the video and save as MP4 clips.
    Naming: clips_dir / TopicName / YYYY-MM-DD_Show_TopicName_HH-MM-SS.mp4
    Returns number of clips created.
    """
    clips_created = 0

    for topic_name, segments in topic_segments.items():
        for seg in segments:
            start = seg.get("start", "")
            end = seg.get("end", "")
            if not start or not end:
                continue

            # Use Oznaka (gender-tagged name) if available
            label = seg.get("Oznaka") or topic_name
            safe_label = label.replace("/", "-").replace(" ", "_")
            start_tag = start.replace(":", "-")

            topic_dir = clips_dir / safe_label
            filename = f"{date_str}_{show}_{safe_label}_{start_tag}.mp4"
            out_path = topic_dir / filename

            if out_path.exists():
                print(f"    [skip clip] {filename} already exists")
                clips_created += 1
                continue

            print(f"    Clipping [{label}] {start} → {end} ...")
            if clip_segment(video_path, out_path, start, end):
                clips_created += 1

    return clips_created
