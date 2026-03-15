# News Monitor

Automated Slovenian TV news monitoring system. Transcribes video broadcasts with Whisper, detects topic segments using Claude API, and outputs timestamped results to Excel.

## Quick Start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
python main.py
```

## Requirements

- Python 3.11+
- FFmpeg + FFprobe installed and on PATH
- `ANTHROPIC_API_KEY` environment variable set

## Architecture

3-step pipeline: **Transcribe → Detect → Export**

- `main.py` — Entry point and orchestration
- `transcribe.py` — Audio extraction (FFmpeg) + Whisper transcription
- `detect_topics.py` — Claude API topic detection (uses claude-haiku-4-5)
- `excel_output.py` — Excel output formatting (openpyxl)
- `config.yaml` — All topic definitions, keywords, per-topic rules, model settings

## Directories

- `input/` — Drop video files here (.mp4, .mkv, .avi, .mov, .mts, etc.)
- `transcripts/` — Cached transcript JSON files (expensive to regenerate)
- `output/` — Generated Excel files

## CLI Flags

```
python main.py                    # Process all new files
python main.py --retranscribe     # Force re-transcription
python main.py --redetect         # Force re-run topic detection only
python main.py --file <path>      # Process a single file
python main.py --list-topics      # Show configured topics
python main.py --config <path>    # Use alternate config file
```

## Key Conventions

- Input filenames follow `YYYY-MM-DD_CHANNEL_SHOWNAME.ext` format
- Transcripts are cached as JSON — avoid `--retranscribe` unless necessary
- Timestamps are rounded to nearest 5 seconds in output
- Topics and detection rules are configured in `config.yaml`, not in code
- Language is Slovenian (`sl`) — all prompts and output labels are in Slovenian
- Hardware acceleration: auto-detects Apple Silicon (mlx-whisper) or CUDA
- Large transcripts are chunked (40K chars with 2K overlap) for Claude context limits
