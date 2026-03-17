"""
Transcription module using faster-whisper.
Extracts audio from video, transcribes with timestamps, caches results as JSON.
Uses NVIDIA GPU (CUDA) when available, falls back to CPU.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from tqdm import tqdm

from paths import get_ffmpeg_path, get_ffprobe_path


_model_cache: dict = {}


def get_model(model_size: str):
    """Load and cache the Whisper model with optimal settings for the current hardware."""
    if model_size not in _model_cache:
        print(f"Loading Whisper model '{model_size}'...")
        from faster_whisper import WhisperModel
        try:
            _model_cache[model_size] = WhisperModel(model_size, device="cuda", compute_type="float16")
            print("    Using NVIDIA GPU (CUDA)")
        except Exception:
            cpu_threads = min(os.cpu_count() or 4, 8)
            _model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
            print(f"    Using CPU ({cpu_threads} threads)")
        print("Model loaded.")
    return _model_cache[model_size]


def get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds using ffprobe."""
    cmd = [
        get_ffprobe_path(), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {video_path.name}:\n{result.stderr}")
    return float(result.stdout.strip())


def extract_audio(video_path: Path, audio_path: Path, start_seconds: float = 0.0) -> None:
    """Extract audio from video file as 16kHz mono WAV using ffmpeg.
    If start_seconds > 0, only extract from that point onwards.
    """
    cmd = [get_ffmpeg_path(), "-y"]
    if start_seconds > 0:
        cmd += ["-ss", str(start_seconds)]
    cmd += [
        "-i", str(video_path),
        "-ar", "16000", "-ac", "1", "-f", "wav",
        str(audio_path),
        "-loglevel", "error"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {video_path.name}:\n{result.stderr}")


def transcribe_video(
    video_path: Path,
    transcripts_dir: Path,
    model_size: str = "large-v3",
    language: str = "sl",
    force: bool = False,
    transcribe_last_minutes: int = 0,
) -> list[dict]:
    """
    Transcribe a video file, caching the result as JSON.

    Returns a list of segments: [{"start": float, "end": float, "text": str}, ...]
    """
    transcript_path = transcripts_dir / (video_path.stem + ".json")

    if transcript_path.exists() and not force:
        print(f"  [cache] Using cached transcript: {transcript_path.name}")
        with open(transcript_path) as f:
            return json.load(f)

    print(f"  [transcribe] {video_path.name}")

    # Calculate start offset for partial transcription
    start_offset = 0.0
    if transcribe_last_minutes > 0:
        duration = get_video_duration(video_path)
        start_offset = max(0.0, duration - transcribe_last_minutes * 60)
        print(f"    Partial transcription: last {transcribe_last_minutes} min (from {format_timestamp(start_offset)})")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = Path(tmp.name)

    try:
        print("    Extracting audio...")
        extract_audio(video_path, audio_path, start_seconds=start_offset)

        print("    Transcribing (this may take a while)...")
        model = get_model(model_size)

        segments_gen, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        segments = []
        with tqdm(total=info.duration, unit="s", unit_scale=True, desc="    Progress") as pbar:
            prev_end = 0.0
            for seg in segments_gen:
                segments.append({
                    "start": round(seg.start + start_offset, 2),
                    "end": round(seg.end + start_offset, 2),
                    "text": seg.text.strip(),
                })
                pbar.update(seg.end - prev_end)
                prev_end = seg.end

        # Cache transcript
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)

        print(f"    Saved transcript: {transcript_path.name}")
        return segments

    finally:
        audio_path.unlink(missing_ok=True)


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
