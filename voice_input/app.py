"""Voice Input — 録音して文字起こしするだけの軽量オフラインアプリ（Windows 向け）。"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path

import numpy as np

from .live import LiveSession
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

        self.root = root
        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.stop_flag = threading.Event()
        self.last_recording: np.ndarray | None = None
        self.backlog = 0.0  # 録音中、まだ文字起こししていない秒数

        root.title(APP_NAME)
        root.geometry("760x560")
        root.minsize(560, 380)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        root.option_add("*Font", ("Yu Gothic UI", 10))

        # --- 上部：操作 ---
        bar = ttk.Frame(root, padding=(10, 10, 10, 4))
        bar.pack(fill="x")
        self.rec_btn = ttk.Button(bar, text="● 録音開始", width=14, command=self.toggle_record)
        self.rec_btn.pack(side="left")
        self.open_btn = ttk.Button(bar, text="ファイルを開く…", command=self.open_file)
        self.open_btn.pack(side="left", padx=(6, 16))

        ttk.Label(bar, text="モデル").pack(side="left")
        models = list_models()
        self.model_var = tk.StringVar(value=models[0] if models else "")
        self.model_box = ttk.Combobox(bar, textvariable=self.model_var, values=models, width=12, state="readonly")
        self.model_box.pack(side="left", padx=(4, 12))

        ttk.Label(bar, text="言語").pack(side="left")
        self.lang_var = tk.StringVar(value="日本語")
        self.lang_box = ttk.Combobox(bar, textvariable=self.lang_var, values=list(LANGUAGES), width=8, state="readonly")
        self.lang_box.pack(side="left", padx=(4, 12))

        self.ts_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="時刻を付ける", variable=self.ts_var).pack(side="left")

        # --- 状態表示 ---
        status = ttk.Frame(root, padding=(10, 2, 10, 6))
        status.pack(fill="x")
        self.status_var = tk.StringVar()
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.cancel_btn = ttk.Button(status, text="中止", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right")
        self.progress = ttk.Progressbar(status, length=200, maximum=1.0)
        self.progress.pack(side="right", padx=8)

        # --- 本文 ---
        self.text = ScrolledText(root, wrap="word", font=("Meiryo", 11), undo=True, padx=8, pady=6)
        self.text.pack(fill="both", expand=True, padx=10)

        # --- 下部 ---
        bottom = ttk.Frame(root, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="すべてコピー", command=self.copy_all).pack(side="left")
        ttk.Button(bottom, text="テキストを保存…", command=self.save_text).pack(side="left", padx=6)
        self.save_wav_btn = ttk.Button(bottom, text="録音を保存…", command=self.save_recording, state="disabled")
        self.save_wav_btn.pack(side="left")
        ttk.Button(bottom, text="クリア", command=lambda: self.text.delete("1.0", "end")).pack(side="right")

        if not models:
            self.status_var.set(f"モデルがありません。{models_dir()} にモデルを置いてください。")
            self.rec_btn.state(["disabled"])
            self.open_btn.state(["disabled"])
        else:
            self.status_var.set("準備完了。「● 録音開始」を押すと、話した内容がその場で文字になります。")
            # 最初の文字起こしを待たせないよう、裏でモデルを先読みしておく
            threading.Thread(target=self._preload, args=(models[0],), daemon=True).start()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        if initial_file and models:
            root.after(300, lambda: self.start_transcription(initial_file, Path(initial_file).name))

    def _preload(self, name: str) -> None:
        try:
            self.transcriber.load(name)
        except Exception:  # noqa: BLE001  失敗しても本番の読み込み時にエラー表示される
            pass

    # ---------- 状態 ----------
    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        st = ["disabled"] if busy else ["!disabled"]
        self.open_btn.state(st)
        if not self.recorder.recording:
            self.rec_btn.state(st)
        combo = ["disabled"] if busy else ["!disabled", "readonly"]
        self.model_box.state(combo)
        self.lang_box.state(combo)
        self.cancel_btn.state(["!disabled"] if busy else ["disabled"])
        if not busy:
            self.progress["value"] = 0

    def poll(self) -> None:
        from tkinter import messagebox

        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "text":
                    self.text.insert("end", payload)
                    self.text.see("end")
                elif kind == "done":
                    self.set_busy(False)
                    self.status_var.set(payload)
                elif kind == "rec_reset":
                    self.rec_btn.config(text="● 録音開始")
                elif kind == "error":
                    self.set_busy(False)
                    self.status_var.set("エラーが発生しました")
                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        if self.recorder.recording:
            bars = "▮" * int(self.recorder.level * 10)
            msg = f"録音中… {format_time(self.recorder.elapsed())}  {bars}"
            if self.backlog >= 15:
                msg += f"（文字起こしが {int(self.backlog)} 秒遅れています）"
            self.status_var.set(msg)
        self.root.after(100, self.poll)

    def cancel(self) -> None:
        self.stop_flag.set()
        self.status_var.set("中止しています…")

    # ---------- 録音・文字起こし ----------
    def toggle_record(self) -> None:
        from tkinter import messagebox

        if self.recorder.recording:
            self.last_recording = self.recorder.stop()
            self.rec_btn.config(text="● 録音開始")
            self.rec_btn.state(["disabled"])  # 残りの文字起こしが終わるまで
            self.cancel_btn.state(["!disabled"])
            if self.last_recording.size >= 16000 * 0.5:
                self.save_wav_btn.state(["!disabled"])
            self.events.put(("status", "残りを文字起こし中…"))
            return
        if self.busy:
            return
        try:
            self.recorder.start()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"マイクを開けませんでした。\n\n{e}")
            return
        self.stop_flag.clear()
        self.set_busy(True)
        self.rec_btn.state(["!disabled"])
        self.cancel_btn.state(["disabled"])
        self.rec_btn.config(text="■ 録音停止")
        self.backlog = 0.0
        model = self.model_var.get()
        language = LANGUAGES[self.lang_var.get()]
        with_ts = self.ts_var.get()
        if self.text.get("1.0", "end-1c").strip():
            self.text.insert("end", "\n")
        self.text.insert("end", f"―― 録音 {_now()} ――\n")

        def emit(seg) -> None:
            line = f"[{format_time(seg.start)}] {seg.text}" if with_ts else seg.text
            self.events.put(("text", line + "\n"))

        def set_backlog(sec: float) -> None:
            self.backlog = sec

        def work() -> None:
            try:
                self.transcriber.load(model)
                session = LiveSession(
                    self.recorder.read_new,
                    lambda: self.recorder.recording,
                    self.transcriber,
                    language,
                    emit,
                    set_backlog,
                )
                count = session.run(self.stop_flag.is_set)
                self.events.put(("done", "完了しました。" if count else "音声を聞き取れませんでした。"))
            except Exception:  # noqa: BLE001
                if self.recorder.recording:
                    self.recorder.stop()
                self.events.put(("rec_reset", None))
                self.events.put(("error", traceback.format_exc(limit=3)))

        threading.Thread(target=work, daemon=True).start()

    def open_file(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(title="音声ファイルを開く", filetypes=AUDIO_TYPES)
        if path:
            self.start_transcription(path, Path(path).name)

    def start_transcription(self, audio, label: str) -> None:
        if self.busy:
            return
        self.stop_flag.clear()
        self.set_busy(True)
        model = self.model_var.get()
        language = LANGUAGES[self.lang_var.get()]
        with_ts = self.ts_var.get()
        if self.text.get("1.0", "end-1c").strip():
            self.text.insert("end", "\n")
        self.text.insert("end", f"―― {label} ――\n")

        def work() -> None:
            try:
                self.events.put(("status", "モデルを準備中…"))
                self.transcriber.load(model)
                self.events.put(("status", "文字起こし中…"))
                count = 0
                for seg in self.transcriber.transcribe(
                    audio,
                    language=language,
                    progress=lambda p: self.events.put(("progress", p)),
                    should_stop=self.stop_flag.is_set,
                ):
                    if not seg.text:
                        continue
                    count += 1
                    line = f"[{format_time(seg.start)}] {seg.text}" if with_ts else seg.text
                    self.events.put(("text", line + "\n"))
                if self.stop_flag.is_set():
                    self.events.put(("done", "中止しました。"))
                elif count == 0:
                    self.events.put(("done", "音声を聞き取れませんでした。"))
                else:
                    self.events.put(("done", "完了しました。"))
            except Exception:  # noqa: BLE001
                self.events.put(("error", traceback.format_exc(limit=3)))

        threading.Thread(target=work, daemon=True).start()

    # ---------- 保存 ----------
    def copy_all(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.status_var.set("クリップボードにコピーしました。")

    def save_text(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            title="テキストを保存", defaultextension=".txt", filetypes=[("テキスト", "*.txt")]
        )
        if path:
            Path(path).write_text(self.text.get("1.0", "end-1c"), encoding="utf-8-sig")
            self.status_var.set(f"保存しました: {path}")

    def save_recording(self) -> None:
        from tkinter import filedialog

        if self.last_recording is None:
            return
        path = filedialog.asksaveasfilename(
            title="録音を保存", defaultextension=".wav", filetypes=[("WAV 音声", "*.wav")]
        )
        if path:
            save_wav(path, self.last_recording)
            self.status_var.set(f"保存しました: {path}")

    def on_close(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()
        self.stop_flag.set()
        self.root.destroy()


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")


def selftest() -> int:
    """配布物が正しく組み立てられているかを確認する（CI 用）。結果は selftest.log に書く。"""
    log = app_dir() / "selftest.log"
    lines: list[str] = []
    code = 0
    try:
        import tkinter  # noqa: F401

        import sounddevice  # noqa: F401  PortAudio の DLL が読めるか

        models = list_models()
        lines.append(f"whisper models: {models}")
        if not models:
            raise RuntimeError("no whisper models bundled")
        t = Transcriber()
        t.load(models[0])
        sr = 16000
        tt = np.arange(sr * 2) / sr
        tone = (0.1 * np.sin(2 * np.pi * 440 * tt)).astype(np.float32)
        segs = list(t.transcribe(tone, language="ja", vad=False))
        lines.append(f"transcribe ok: {len(segs)} segments")
        segs = list(t.transcribe(tone, language="ja", vad=True))
        lines.append(f"transcribe (vad) ok: {len(segs)} segments")

        # 録音中の逐次文字起こし（マイクの代わりに 0.2 秒ずつ音を渡す）
        audio = np.concatenate([tone, np.zeros(sr, np.float32), tone, np.zeros(sr // 5, np.float32)])
        pos = [0]

        def feed() -> np.ndarray:
            a = audio[pos[0] : pos[0] + 3200]
            pos[0] += 3200
            return a

        n = LiveSession(feed, lambda: pos[0] < audio.size, t, "ja", lambda s: None).run()
        lines.append(f"live ok: {n} segments")
        lines.append("SELFTEST OK")
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
