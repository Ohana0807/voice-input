"""Voice Input — オフライン文字起こしアプリ（Windows 向け GUI）。"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path

import numpy as np

from .recorder import Recorder, save_wav
from .transcriber import Transcriber, app_dir, format_time, list_models, models_dir

APP_NAME = "Voice Input"
LANGUAGES = {"日本語": "ja", "英語": "en", "自動判定": None}
AUDIO_TYPES = [
    ("音声・動画ファイル", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.webm *.mp4 *.mov *.mkv"),
    ("すべてのファイル", "*.*"),
]


class App:
    def __init__(self, root, initial_file: str | None = None) -> None:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        self.tk = tk
        self.root = root
        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.stop_flag = threading.Event()
        self.last_recording: np.ndarray | None = None

        root.title(APP_NAME)
        root.geometry("900x620")
        root.minsize(640, 420)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        ui_font = ("Yu Gothic UI", 10)
        root.option_add("*Font", ui_font)

        # --- 上段：操作 ---
        bar = ttk.Frame(root, padding=(10, 10, 10, 4))
        bar.pack(fill="x")
        self.rec_btn = ttk.Button(bar, text="● 録音開始", width=14, command=self.toggle_record)
        self.rec_btn.pack(side="left")
        self.open_btn = ttk.Button(bar, text="ファイルを開く…", command=self.open_file)
        self.open_btn.pack(side="left", padx=(6, 16))

        ttk.Label(bar, text="モデル").pack(side="left")
        models = list_models()
        self.model_var = tk.StringVar(value=models[0] if models else "")
        self.model_box = ttk.Combobox(bar, textvariable=self.model_var, values=models, width=14, state="readonly")
        self.model_box.pack(side="left", padx=(4, 12))

        ttk.Label(bar, text="言語").pack(side="left")
        self.lang_var = tk.StringVar(value="日本語")
        ttk.Combobox(bar, textvariable=self.lang_var, values=list(LANGUAGES), width=8, state="readonly").pack(
            side="left", padx=(4, 12)
        )
        self.ts_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="時刻を付ける", variable=self.ts_var).pack(side="left")
        self.vad_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="無音を飛ばす", variable=self.vad_var).pack(side="left", padx=(8, 0))

        # --- 状態表示 ---
        status = ttk.Frame(root, padding=(10, 2, 10, 6))
        status.pack(fill="x")
        self.status_var = tk.StringVar()
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.cancel_btn = ttk.Button(status, text="中止", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right")
        self.progress = ttk.Progressbar(status, length=220, maximum=1.0)
        self.progress.pack(side="right", padx=8)

        # --- 本文 ---
        self.text = ScrolledText(root, wrap="word", font=("Meiryo", 11), undo=True, padx=8, pady=6)
        self.text.pack(fill="both", expand=True, padx=10)

        # --- 下段 ---
        bottom = ttk.Frame(root, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="すべてコピー", command=self.copy_all).pack(side="left")
        ttk.Button(bottom, text="テキストを保存…", command=self.save_text).pack(side="left", padx=6)
        self.save_wav_btn = ttk.Button(bottom, text="録音を保存…", command=self.save_recording, state="disabled")
        self.save_wav_btn.pack(side="left")
        ttk.Button(bottom, text="クリア", command=lambda: self.text.delete("1.0", "end")).pack(side="right")

        if not models:
            self.set_status(f"モデルがありません。{models_dir()} にモデルを置いてください。")
            self.rec_btn.state(["disabled"])
            self.open_btn.state(["disabled"])
        else:
            self.set_status("準備完了。録音するか、音声ファイルを開いてください。")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        if initial_file and models:
            root.after(300, lambda: self.start_transcription(initial_file, Path(initial_file).name))

    # ---------- 共通 ----------
    def set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        self.open_btn.state(state)
        self.model_box.state(["disabled"] if busy else ["!disabled", "readonly"])
        if not self.recorder.recording:
            self.rec_btn.state(state)
        self.cancel_btn.state(["!disabled"] if busy else ["disabled"])
        if not busy:
            self.progress["value"] = 0

    def poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.set_status(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "text":
                    self.text.insert("end", payload)
                    self.text.see("end")
                elif kind == "done":
                    self.set_busy(False)
                    self.set_status(payload)
                elif kind == "error":
                    self.set_busy(False)
                    self.set_status("エラーが発生しました")
                    from tkinter import messagebox

                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        if self.recorder.recording:
            bars = "▮" * int(self.recorder.level * 10)
            self.set_status(f"録音中… {format_time(self.recorder.elapsed())}  {bars}")
        self.root.after(100, self.poll)

    # ---------- 録音 ----------
    def toggle_record(self) -> None:
        if self.recorder.recording:
            audio = self.recorder.stop()
            self.rec_btn.config(text="● 録音開始")
            if audio.size < 16000 * 0.5:
                self.set_status("録音が短すぎます。")
                self.set_busy(False)
                return
            self.last_recording = audio
            self.save_wav_btn.state(["!disabled"])
            self.start_transcription(audio, "録音")
        else:
            try:
                self.recorder.start()
            except Exception as e:  # noqa: BLE001
                from tkinter import messagebox

                messagebox.showerror(APP_NAME, f"マイクを開けませんでした。\n\n{e}")
                return
            self.rec_btn.config(text="■ 録音停止")
            self.open_btn.state(["disabled"])
            self.model_box.state(["disabled"])

    # ---------- ファイル ----------
    def open_file(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(title="音声ファイルを開く", filetypes=AUDIO_TYPES)
        if path:
            self.start_transcription(path, Path(path).name)

    # ---------- 文字起こし ----------
    def start_transcription(self, audio, label: str) -> None:
        if self.busy:
            return
        self.stop_flag.clear()
        self.set_busy(True)
        model = self.model_var.get()
        language = LANGUAGES[self.lang_var.get()]
        with_ts = self.ts_var.get()
        vad = self.vad_var.get()
        if self.text.get("1.0", "end-1c").strip():
            self.text.insert("end", "\n")
        self.text.insert("end", f"―― {label} ――\n")

        def work() -> None:
            try:
                self.events.put(("status", f"モデル「{model}」を読み込み中…"))
                self.transcriber.load(model)
                self.events.put(("status", f"「{label}」を文字起こし中…"))
                count = 0
                for seg in self.transcriber.transcribe(
                    audio,
                    language=language,
                    vad=vad,
                    progress=lambda p: self.events.put(("progress", p)),
                    should_stop=self.stop_flag.is_set,
                ):
                    if not seg.text:
                        continue
                    count += 1
                    line = f"[{format_time(seg.start)} → {format_time(seg.end)}] {seg.text}" if with_ts else seg.text
                    self.events.put(("text", line + "\n"))
                if self.stop_flag.is_set():
                    self.events.put(("done", "中止しました。"))
                elif count == 0:
                    self.events.put(("done", "音声を聞き取れませんでした。"))
                else:
                    self.events.put(("done", f"完了しました（{count} 行）。"))
            except Exception:  # noqa: BLE001
                self.events.put(("error", traceback.format_exc(limit=3)))

        threading.Thread(target=work, daemon=True).start()

    def cancel(self) -> None:
        self.stop_flag.set()
        self.set_status("中止しています…")

    # ---------- 保存 ----------
    def copy_all(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.set_status("クリップボードにコピーしました。")

    def save_text(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            title="テキストを保存", defaultextension=".txt", filetypes=[("テキスト", "*.txt")]
        )
        if path:
            Path(path).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8-sig")
            self.set_status(f"保存しました: {path}")

    def save_recording(self) -> None:
        from tkinter import filedialog

        if self.last_recording is None:
            return
        path = filedialog.asksaveasfilename(
            title="録音を保存", defaultextension=".wav", filetypes=[("WAV 音声", "*.wav")]
        )
        if path:
            save_wav(path, self.last_recording)
            self.set_status(f"保存しました: {path}")

    def on_close(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()
        self.stop_flag.set()
        self.root.destroy()


def selftest() -> int:
    """配布物が正しく組み立てられているかを確認する（CI 用）。結果は selftest.log に書く。"""
    log = app_dir() / "selftest.log"
    lines: list[str] = []
    try:
        import tkinter  # noqa: F401

        import sounddevice  # noqa: F401  PortAudio の DLL が読めるか

        models = list_models()
        lines.append(f"models: {models}")
        if not models:
            raise RuntimeError("no models bundled")
        t = Transcriber()
        t.load(models[0])
        sr = 16000
        tt = np.arange(sr * 2) / sr
        tone = (0.1 * np.sin(2 * np.pi * 440 * tt)).astype(np.float32)
        segs = list(t.transcribe(tone, language="ja", vad=False))
        lines.append(f"transcribe ok: {len(segs)} segments")
        lines.append("SELFTEST OK")
        code = 0
    except Exception:  # noqa: BLE001
        lines.append(traceback.format_exc())
        lines.append("SELFTEST FAILED")
        code = 1
    log.write_text("\n".join(lines), encoding="utf-8")
    return code


def main() -> None:
    args = sys.argv[1:]
    if "--selftest" in args:
        sys.exit(selftest())
    import tkinter as tk

    initial = args[0] if args and Path(args[0]).is_file() else None
    root = tk.Tk()
    App(root, initial)
    root.mainloop()


if __name__ == "__main__":
    main()
