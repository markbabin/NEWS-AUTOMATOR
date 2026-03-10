# Windows Setup Guide

## 1. Install Python
Download Python 3.11 or newer from https://python.org
During installation, check **"Add Python to PATH"**

## 2. Install ffmpeg
1. Download ffmpeg from https://ffmpeg.org/download.html → Windows builds (e.g. gyan.dev)
2. Extract the zip anywhere (e.g. `C:\ffmpeg`)
3. Add `C:\ffmpeg\bin` to your system PATH:
   - Search "Environment Variables" in Start menu
   - Edit "Path" under System Variables
   - Add new entry: `C:\ffmpeg\bin`
4. Verify: open Command Prompt and run `ffmpeg -version`

## 3. Install Python dependencies
Open Command Prompt and run:
```
pip install faster-whisper anthropic openpyxl pyyaml tqdm
```
> Do NOT install mlx-whisper — it is Apple Silicon only and won't work on Windows.

## 4. Set your API key permanently
In Command Prompt (run as Administrator):
```
setx ANTHROPIC_API_KEY "sk-ant-your-key-here"
```
Close and reopen Command Prompt after running this.

## 5. Run the script
```
cd C:\path\to\news-monitor
python main.py
```

## Notes
- If you have an **Nvidia GPU**, transcription will be much faster automatically (no extra setup needed)
- If CPU-only, transcription will be slower than Apple Silicon — consider using `whisper_model: "medium"` in config.yaml for faster runs
- File naming works the same: `YYYY-MM-DD_CHANNEL_SHOWNAME.mp4`
