#!/usr/bin/env python3
"""
News Monitor - Main entry point.

Processes all video files in the input directory:
1. Transcribes audio using faster-whisper (cached)
2. Detects topic segments using Claude
3. Writes results to Excel

Usage:
    python main.py                    # Process all new files
    python main.py --retranscribe     # Force re-transcription of all files
    python main.py --redetect         # Force re-run topic detection (keeps cached transcripts)
    python main.py --file <path>      # Process a single file only
    python main.py --list-topics      # Show configured topics
"""

import argparse
import os
import re
import sys
from pathlib import Path
from datetime import datetime

import yaml
import anthropic

from transcribe import transcribe_video
from detect_topics import detect_topics
from excel_output import append_rows, is_already_processed
from clip_segments import clip_all_segments


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".mts", ".m2ts", ".wmv", ".flv", ".webm"}


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_filename(stem: str) -> tuple[str, str, str] | None:
    """
    Parse date, channel, show from filename stem.
    Expected: YYYY-MM-DD_CHANNEL_SHOWNAME
    Returns (date_str, channel, show) or None if format doesn't match.
    """
    parts = stem.split("_", 2)
    if len(parts) < 3:
        return None
    date_str, channel, show = parts[0], parts[1], parts[2]
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    return date_str, channel, show.replace("_", " ")


def normalize_show_name(show: str, channel: str) -> str:
    """Normalize show names to standard display labels."""
    s = show.lower().strip()
    if "24ur" in s or "24 ur" in s:
        return "24Ur"
    # Šport / Sport followed by a timestamp — check the hour to assign the right show
    m = re.match(r".*[sš]port\D*(\d{1,2})", s)
    if m:
        hour = int(m.group(1))
        if hour >= 21:
            return "Odmevi"
        return "Dnevnik"
    ch = channel.lower().strip()
    if "planet" in ch or "planet" in s:
        return "Planet 18"
    if "kanal a" in ch:
        return "Svet"
    return show


def prompt_for_metadata(video_path: Path) -> tuple[str, str, str]:
    """Interactively ask user for date, channel, show name."""
    print(f"\n  Cannot parse metadata from filename: {video_path.name}")
    print("  Please enter the metadata manually:")
    date_str = input("  Date (YYYY-MM-DD): ").strip()
    channel = input("  Channel name (e.g. RTV, POP, NOVA24): ").strip()
    show = input("  Show name (e.g. Dnevnik, 24ur): ").strip()
    return date_str, channel, show


def get_video_files(input_dir: Path) -> list[Path]:
    files = sorted([
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ])
    return files


def process_video(
    video_path: Path,
    config: dict,
    client: anthropic.Anthropic,
    base_dir: Path,
    force_transcribe: bool = False,
    force_detect: bool = False,
    skip_clips: bool = False,
) -> int:
    """Process a single video file. Returns number of segments found."""
    transcripts_dir = base_dir / config["transcripts_dir"]
    output_path = base_dir / config["output_dir"] / config["output_file"]
    clips_dir = base_dir / config.get("clips_dir", "clips")
    topics = config["topics"]

    # Parse metadata
    meta = parse_filename(video_path.stem)
    if meta is None:
        meta = prompt_for_metadata(video_path)
    date_str, channel, show = meta
    show = normalize_show_name(show, channel)

    print(f"\n{'='*60}")
    print(f"  File   : {video_path.name}")
    print(f"  Date   : {date_str}  |  Channel: {channel}  |  Show: {show}")
    print(f"{'='*60}")

    # Skip if already in Excel (unless force redetect)
    if not force_detect and is_already_processed(output_path, date_str, channel, show):
        print("  [skip] Already processed — found in Excel. Use --redetect to rerun.")
        return 0

    # Look up per-show rules (case-insensitive match)
    show_rules = {}
    for rule_show, rule in config.get("show_rules", {}).items():
        if rule_show.lower() in show.lower():
            show_rules = rule
            break

    # Step 1: Transcribe
    segments = transcribe_video(
        video_path=video_path,
        transcripts_dir=transcripts_dir,
        model_size=config.get("whisper_model", "large-v3"),
        language=config.get("language", "sl"),
        force=force_transcribe,
        transcribe_last_minutes=show_rules.get("transcribe_last_minutes", 0),
    )
    print(f"  Transcript: {len(segments)} segments")

    # Step 2: Detect topics
    print(f"  Detecting topics...")
    topic_results = detect_topics(
        client=client,
        segments=segments,
        topics=topics,
        video_name=video_path.name,
        instructions=config.get("instructions", ""),
    )

    # Show summary
    found_any = False
    for topic_name, segs in topic_results.items():
        if segs:
            found_any = True
            for seg in segs:
                print(f"    [{topic_name}] {seg['start']} → {seg['end']}")
    if not found_any:
        print("    No matching segments found.")

    # Step 3: Write to Excel
    rows_added = append_rows(
        output_path=output_path,
        date=date_str,
        channel=channel,
        show=show,
        topic_segments=topic_results,
        topics=topics,
    )
    if rows_added:
        print(f"  Wrote {rows_added} row(s) to {output_path.name}")

    # Step 4: Cut video clips
    if not skip_clips and found_any:
        print(f"  Cutting clips...")
        clips_count = clip_all_segments(
            video_path=video_path,
            clips_dir=clips_dir,
            date_str=date_str,
            show=show,
            topic_segments=topic_results,
        )
        print(f"  Created {clips_count} clip(s) in {clips_dir}/")

    return rows_added


def main():
    parser = argparse.ArgumentParser(description="Slovenian TV News Monitor")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--file", help="Process a single video file")
    parser.add_argument("--retranscribe", action="store_true", help="Force re-transcription")
    parser.add_argument("--redetect", action="store_true", help="Force re-run topic detection")
    parser.add_argument("--no-clips", action="store_true", help="Skip cutting video clips")
    parser.add_argument("--list-topics", action="store_true", help="Show configured topics and exit")
    args = parser.parse_args()

    base_dir = Path(__file__).parent
    config_path = base_dir / args.config

    if not config_path.exists():
        print(f"Error: config file not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)

    if args.list_topics:
        print("\nConfigured topics:")
        for t in config["topics"]:
            print(f"  • {t['name']}: {t['description'][:80]}...")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    if args.file:
        video_path = Path(args.file)
        if not video_path.is_absolute():
            video_path = base_dir / video_path
        if not video_path.exists():
            print(f"Error: file not found: {video_path}")
            sys.exit(1)
        videos = [video_path]
    else:
        input_dir = base_dir / config["input_dir"]
        if not input_dir.exists():
            print(f"Error: input directory not found: {input_dir}")
            sys.exit(1)
        videos = get_video_files(input_dir)

    if not videos:
        print("No video files found. Drop .mp4/.mkv/etc files into the 'input/' folder.")
        return

    print(f"\nFound {len(videos)} video file(s).")

    total_segments = 0
    errors = []

    for video_path in videos:
        try:
            total_segments += process_video(
                video_path=video_path,
                config=config,
                client=client,
                base_dir=base_dir,
                force_transcribe=args.retranscribe,
                force_detect=args.redetect,
                skip_clips=args.no_clips,
            )
        except Exception as e:
            print(f"\n  ERROR processing {video_path.name}: {e}")
            errors.append((video_path.name, str(e)))

    print(f"\n{'='*60}")
    print(f"Done. Total segments written: {total_segments}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for name, err in errors:
            print(f"  • {name}: {err}")
    output_path = base_dir / config["output_dir"] / config["output_file"]
    if output_path.exists():
        print(f"Excel file: {output_path}")


if __name__ == "__main__":
    main()
