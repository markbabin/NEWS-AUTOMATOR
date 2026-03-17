#!/usr/bin/env python3
"""
News Monitor — GUI application (Windows).
Wraps the CLI pipeline in a customtkinter interface with progress tracking,
file preview, metadata dialogs, and API key persistence.
"""

import io
import os
import sys
import shutil
import subprocess
import threading
from pathlib import Path

import customtkinter as ctk
import yaml
import anthropic

from main import (
    VIDEO_EXTENSIONS,
    load_config,
    process_video,
)
from paths import (
    get_bundle_dir,
    get_user_data_dir,
    ensure_directories,
    ensure_config,
    save_api_key,
    load_api_key,
    get_ffmpeg_path,
)


DATA_DIR = get_user_data_dir()


class LogRedirector(io.TextIOBase):
    """Redirects print() output into a CTkTextbox widget."""

    def __init__(self, widget: ctk.CTkTextbox):
        self.widget = widget

    def write(self, text: str):
        self.widget.after(0, self._append, text)
        return len(text)

    def _append(self, text: str):
        self.widget.configure(state="normal")
        self.widget.insert("end", text)
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def flush(self):
        pass


class MetadataDialog(ctk.CTkToplevel):
    """Popup dialog for entering video metadata when filename can't be parsed."""

    def __init__(self, parent, filename: str):
        super().__init__(parent)
        self.title("Enter Video Metadata")
        self.geometry("420x260")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result = None

        ctk.CTkLabel(self, text=f"Cannot parse metadata from:", anchor="w").pack(
            padx=20, pady=(16, 0), fill="x"
        )
        ctk.CTkLabel(self, text=filename, font=("Consolas", 12), anchor="w").pack(
            padx=20, pady=(0, 12), fill="x"
        )

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(padx=20, fill="x")
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Date:").grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self.date_entry = ctk.CTkEntry(form, placeholder_text="YYYY-MM-DD")
        self.date_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ctk.CTkLabel(form, text="Channel:").grid(row=1, column=0, padx=(0, 8), pady=4, sticky="w")
        self.channel_entry = ctk.CTkEntry(form, placeholder_text="RTV, POP, NOVA24...")
        self.channel_entry.grid(row=1, column=1, sticky="ew", pady=4)

        ctk.CTkLabel(form, text="Show:").grid(row=2, column=0, padx=(0, 8), pady=4, sticky="w")
        self.show_entry = ctk.CTkEntry(form, placeholder_text="Dnevnik, 24ur...")
        self.show_entry.grid(row=2, column=1, sticky="ew", pady=4)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(padx=20, pady=16, fill="x")
        ctk.CTkButton(btn_frame, text="OK", width=100, command=self._on_ok).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_frame, text="Skip", width=100, fg_color="gray", command=self._on_skip).pack(side="right")

        self.date_entry.focus_set()
        self.bind("<Return>", lambda e: self._on_ok())

    def _on_ok(self):
        d = self.date_entry.get().strip()
        c = self.channel_entry.get().strip()
        s = self.show_entry.get().strip()
        if d and c and s:
            self.result = (d, c, s)
            self.destroy()

    def _on_skip(self):
        self.result = None
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("News Monitor")
        self.geometry("860x700")
        self.minsize(720, 540)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Ensure data directories exist
        ensure_directories(DATA_DIR)

        self._processing = False
        self._cancel_event = threading.Event()
        self._metadata_result = None
        self._metadata_event = threading.Event()

        self._build_ui()

    # ── UI layout ──────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)  # log area gets the stretch

        # --- Row 0: API key ---
        key_frame = ctk.CTkFrame(self, fg_color="transparent")
        key_frame.grid(row=0, column=0, padx=16, pady=(16, 4), sticky="ew")
        key_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(key_frame, text="API Key:").grid(row=0, column=0, padx=(0, 8))
        self.api_entry = ctk.CTkEntry(key_frame, show="*", placeholder_text="ANTHROPIC_API_KEY")
        self.api_entry.grid(row=0, column=1, sticky="ew")

        saved_key = load_api_key(DATA_DIR)
        if saved_key:
            self.api_entry.insert(0, saved_key)

        # --- Row 1: Input folder ---
        folder_frame = ctk.CTkFrame(self, fg_color="transparent")
        folder_frame.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        folder_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(folder_frame, text="Input:").grid(row=0, column=0, padx=(0, 8))
        self.folder_var = ctk.StringVar(value=str(DATA_DIR / "input"))
        self.folder_entry = ctk.CTkEntry(folder_frame, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(folder_frame, text="Browse", width=80, command=self._browse_folder).grid(
            row=0, column=2
        )

        # --- Row 2: Options + buttons ---
        opts_frame = ctk.CTkFrame(self, fg_color="transparent")
        opts_frame.grid(row=2, column=0, padx=16, pady=(4, 4), sticky="ew")

        self.retranscribe_var = ctk.BooleanVar()
        self.redetect_var = ctk.BooleanVar()
        self.no_clips_var = ctk.BooleanVar()

        ctk.CTkCheckBox(opts_frame, text="Re-transcribe", variable=self.retranscribe_var).pack(
            side="left", padx=(0, 16)
        )
        ctk.CTkCheckBox(opts_frame, text="Re-detect topics", variable=self.redetect_var).pack(
            side="left", padx=(0, 16)
        )
        ctk.CTkCheckBox(opts_frame, text="Skip clips", variable=self.no_clips_var).pack(
            side="left", padx=(0, 16)
        )

        self.cancel_btn = ctk.CTkButton(
            opts_frame, text="Cancel", width=90, fg_color="#8B0000",
            hover_color="#A52A2A", command=self._on_cancel, state="disabled"
        )
        self.cancel_btn.pack(side="right", padx=(8, 0))

        self.run_btn = ctk.CTkButton(opts_frame, text="Process", width=120, command=self._on_run)
        self.run_btn.pack(side="right")

        # --- Row 3: Progress bar ---
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.grid(row=3, column=0, padx=16, pady=(0, 4), sticky="ew")
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", width=120)
        self.progress_label.grid(row=0, column=1)

        # --- Row 4: Log area ---
        self.log_box = ctk.CTkTextbox(self, state="disabled", font=("Consolas", 12))
        self.log_box.grid(row=4, column=0, padx=16, pady=(0, 8), sticky="nsew")

        # --- Row 5: Bottom buttons ---
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=5, column=0, padx=16, pady=(0, 16), sticky="ew")

        ctk.CTkButton(bottom, text="Open Excel", width=120, command=self._open_excel).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(bottom, text="Open Clips", width=120, command=self._open_clips).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(bottom, text="Open Input", width=120, command=self._open_input).pack(
            side="left"
        )

        self.status_label = ctk.CTkLabel(bottom, text="Ready", text_color="gray")
        self.status_label.pack(side="right")

        # Show welcome on first run
        if not (DATA_DIR / ".api_key").exists() and not os.environ.get("ANTHROPIC_API_KEY"):
            self._log("Welcome to News Monitor!")
            self._log("Enter your Anthropic API key above, then drop video files into the input folder.")
            self._log(f"Input folder: {DATA_DIR / 'input'}\n")

        # Check FFmpeg
        ffmpeg = get_ffmpeg_path()
        if not shutil.which(ffmpeg) and ffmpeg == "ffmpeg":
            self._log("WARNING: FFmpeg not found on PATH. Install FFmpeg to enable transcription and clipping.")
            self._log("  Download from ffmpeg.org and add to PATH, or place ffmpeg.exe in the app folder.\n")

    # ── Actions ────────────────────────────────────────────────

    def _browse_folder(self):
        path = ctk.filedialog.askdirectory(initialdir=self.folder_var.get())
        if path:
            self.folder_var.set(path)

    def _log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_status(self, text: str, color: str = "gray"):
        self.status_label.configure(text=text, text_color=color)

    def _set_progress(self, value: float, label: str = ""):
        self.progress_bar.set(value)
        self.progress_label.configure(text=label)

    def _on_cancel(self):
        self._cancel_event.set()
        self._log("\nCancelling after current file finishes...")
        self.cancel_btn.configure(state="disabled")

    def _on_run(self):
        if self._processing:
            return

        api_key = self.api_entry.get().strip()
        if not api_key:
            self._log("ERROR: Please enter your Anthropic API key.")
            return

        input_dir = Path(self.folder_var.get())
        if not input_dir.is_dir():
            self._log(f"ERROR: Input folder not found: {input_dir}")
            return

        # Save API key for next launch
        save_api_key(DATA_DIR, api_key)

        # Scan for video files
        videos = sorted([
            f for f in input_dir.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
        ])

        if not videos:
            self._log("No video files found in the input folder.")
            self._log(f"Supported formats: {', '.join(sorted(VIDEO_EXTENSIONS))}")
            return

        # Clear log
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        # Show file list
        self._log(f"Found {len(videos)} video file(s):")
        for v in videos:
            size_mb = v.stat().st_size / (1024 * 1024)
            self._log(f"  {v.name} ({size_mb:.0f} MB)")
        self._log("")

        self._processing = True
        self._cancel_event.clear()
        self.run_btn.configure(state="disabled", text="Processing...")
        self.cancel_btn.configure(state="normal")
        self._set_status("Processing...", color="#3B8ED0")
        self._set_progress(0, f"0/{len(videos)}")

        thread = threading.Thread(
            target=self._run_pipeline,
            args=(api_key, videos),
            daemon=True,
        )
        thread.start()

    def _prompt_metadata_gui(self, filename: str) -> tuple[str, str, str] | None:
        """Show metadata dialog on the main thread and wait for result."""
        self._metadata_event.clear()
        self._metadata_result = None

        def _show():
            dialog = MetadataDialog(self, filename)
            self.wait_window(dialog)
            self._metadata_result = dialog.result
            self._metadata_event.set()

        self.after(0, _show)
        self._metadata_event.wait()
        return self._metadata_result

    def _run_pipeline(self, api_key: str, videos: list[Path]):
        redirector = LogRedirector(self.log_box)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = redirector
        sys.stderr = redirector

        try:
            config_path = ensure_config(DATA_DIR)
            config = load_config(config_path)
            client = anthropic.Anthropic(api_key=api_key)

            total_segments = 0
            errors = []

            for idx, video_path in enumerate(videos):
                if self._cancel_event.is_set():
                    print("\nCancelled by user.")
                    break

                # Update progress
                progress = idx / len(videos)
                self.after(0, self._set_progress, progress, f"{idx}/{len(videos)}")

                def _metadata_cb(vp):
                    return self._prompt_metadata_gui(vp.name)

                try:
                    total_segments += process_video(
                        video_path=video_path,
                        config=config,
                        client=client,
                        base_dir=DATA_DIR,
                        force_transcribe=self.retranscribe_var.get(),
                        force_detect=self.redetect_var.get(),
                        skip_clips=self.no_clips_var.get(),
                        metadata_callback=_metadata_cb,
                    )
                except Exception as e:
                    print(f"\nERROR processing {video_path.name}: {e}")
                    errors.append(video_path.name)

            # Final progress
            self.after(0, self._set_progress, 1.0, f"{len(videos)}/{len(videos)}")

            print(f"\n{'='*50}")
            if self._cancel_event.is_set():
                print(f"Cancelled. Segments written before cancel: {total_segments}")
            else:
                print(f"Done. Total segments written: {total_segments}")
            if errors:
                print(f"Errors in: {', '.join(errors)}")

            status = f"Done — {total_segments} segments"
            if errors:
                status += f", {len(errors)} error(s)"
            if self._cancel_event.is_set():
                status = f"Cancelled — {total_segments} segments"
            color = "#2FA572" if not errors else "orange"
            self.after(0, self._set_status, status, color)

        except Exception as e:
            print(f"\nFATAL ERROR: {e}")
            self.after(0, self._set_status, "Error", "red")

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.after(0, self._finish_processing)

    def _finish_processing(self):
        self._processing = False
        self.run_btn.configure(state="normal", text="Process")
        self.cancel_btn.configure(state="disabled")

    def _open_excel(self):
        config_path = ensure_config(DATA_DIR)
        config = load_config(config_path)
        path = DATA_DIR / config["output_dir"] / config["output_file"]
        if not path.exists():
            self._log("Excel file not found yet — run processing first.")
            return
        os.startfile(str(path))

    def _open_clips(self):
        config_path = ensure_config(DATA_DIR)
        config = load_config(config_path)
        path = DATA_DIR / config.get("clips_dir", "clips")
        path.mkdir(exist_ok=True)
        os.startfile(str(path))

    def _open_input(self):
        path = Path(self.folder_var.get())
        path.mkdir(exist_ok=True)
        os.startfile(str(path))


if __name__ == "__main__":
    app = App()
    app.mainloop()
