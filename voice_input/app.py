"""Voice Input — オフライン文字起こし＆ヒアリング分析アプリ（Windows 向け GUI）。"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path

import numpy as np

from .analyzer import AnalysisResult, Analyzer, list_llm_models, llm_dir
from .recorder import Recorder, save_wav
from .templates import Item, Template, load_templates, save_templates
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

        self.tk = tk
        self.root = root
        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.analyzer = Analyzer()
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.stop_flag = threading.Event()
        self.last_recording: np.ndarray | None = None
        self.last_label = ""
        self.templates = load_templates()
        self.result: AnalysisResult | None = None

        root.title(APP_NAME)
        root.geometry("980x680")
        root.minsize(720, 480)
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        root.option_add("*Font", ("Yu Gothic UI", 10))

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_tr = ttk.Frame(self.nb)
        self.tab_an = ttk.Frame(self.nb)
        self.nb.add(self.tab_tr, text="  文字起こし  ")
        self.nb.add(self.tab_an, text="  ヒアリング分析  ")
        self._build_transcribe_tab(self.tab_tr)
        self._build_analyze_tab(self.tab_an)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        if initial_file and list_models():
            root.after(300, lambda: self.start_transcription(initial_file, Path(initial_file).name))

    # ================= 文字起こしタブ =================
    def _build_transcribe_tab(self, parent) -> None:
        tk = self.tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        bar = ttk.Frame(parent, padding=(8, 10, 8, 4))
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

        status = ttk.Frame(parent, padding=(8, 2, 8, 6))
        status.pack(fill="x")
        self.status_var = tk.StringVar()
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.cancel_btn = ttk.Button(status, text="中止", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right")
        self.progress = ttk.Progressbar(status, length=220, maximum=1.0)
        self.progress.pack(side="right", padx=8)

        self.text = ScrolledText(parent, wrap="word", font=("Meiryo", 11), undo=True, padx=8, pady=6)
        self.text.pack(fill="both", expand=True, padx=8)

        bottom = ttk.Frame(parent, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="すべてコピー", command=self.copy_all).pack(side="left")
        ttk.Button(bottom, text="テキストを保存…", command=self.save_text).pack(side="left", padx=6)
        self.save_wav_btn = ttk.Button(bottom, text="録音を保存…", command=self.save_recording, state="disabled")
        self.save_wav_btn.pack(side="left")
        ttk.Button(bottom, text="この内容を分析 ▶", command=self.analyze_from_transcript).pack(side="right")
        ttk.Button(bottom, text="クリア", command=lambda: self.text.delete("1.0", "end")).pack(side="right", padx=6)

        if not models:
            self.set_status(f"モデルがありません。{models_dir()} にモデルを置いてください。")
            self.rec_btn.state(["disabled"])
            self.open_btn.state(["disabled"])
        else:
            self.set_status("準備完了。録音するか、音声ファイルを開いてください。")

    # ================= 分析タブ =================
    def _build_analyze_tab(self, parent) -> None:
        tk = self.tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        bar = ttk.Frame(parent, padding=(8, 10, 8, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="分析項目").pack(side="left")
        self.tpl_var = tk.StringVar()
        self.tpl_box = ttk.Combobox(bar, textvariable=self.tpl_var, width=22, state="readonly")
        self.tpl_box.pack(side="left", padx=(4, 4))
        self.tpl_box.bind("<<ComboboxSelected>>", lambda e: self.show_template_preview())
        ttk.Button(bar, text="項目を編集…", command=self.edit_templates).pack(side="left", padx=(0, 16))

        ttk.Label(bar, text="分析モデル").pack(side="left")
        llms = list_llm_models()
        self.llm_var = tk.StringVar(value=llms[0] if llms else "")
        self.llm_box = ttk.Combobox(bar, textvariable=self.llm_var, values=llms, width=30, state="readonly")
        self.llm_box.pack(side="left", padx=4)

        bar2 = ttk.Frame(parent, padding=(8, 2, 8, 4))
        bar2.pack(fill="x")
        self.an_btn = ttk.Button(bar2, text="文字起こしタブの内容を分析", command=self.analyze_from_transcript)
        self.an_btn.pack(side="left")
        self.an_file_btn = ttk.Button(bar2, text="テキストファイルを分析…", command=self.analyze_from_file)
        self.an_file_btn.pack(side="left", padx=6)
        self.an_cancel_btn = ttk.Button(bar2, text="中止", command=self.cancel, state="disabled")
        self.an_cancel_btn.pack(side="right")
        self.an_progress = ttk.Progressbar(bar2, length=220, maximum=1.0)
        self.an_progress.pack(side="right", padx=8)
        self.an_status_var = tk.StringVar()
        ttk.Label(bar2, textvariable=self.an_status_var).pack(side="right", padx=8)

        self.an_text = ScrolledText(parent, wrap="word", font=("Meiryo", 11), padx=10, pady=8)
        self.an_text.pack(fill="both", expand=True, padx=8)
        self.an_text.tag_configure("h", font=("Meiryo", 12, "bold"), foreground="#1F3864", spacing1=10)
        self.an_text.tag_configure("desc", foreground="#7F7F7F", font=("Meiryo", 9))
        self.an_text.tag_configure("ev", foreground="#404040", lmargin1=18, lmargin2=18, font=("Meiryo", 10))
        self.an_text.tag_configure("meta", foreground="#7F7F7F", font=("Meiryo", 9))

        bottom = ttk.Frame(parent, padding=8)
        bottom.pack(fill="x")
        self.xlsx_btn = ttk.Button(bottom, text="Excel に書き出し…", command=self.export_excel, state="disabled")
        self.xlsx_btn.pack(side="left")
        self.docx_btn = ttk.Button(bottom, text="Word に書き出し…", command=self.export_word, state="disabled")
        self.docx_btn.pack(side="left", padx=6)
        self.an_copy_btn = ttk.Button(bottom, text="結果をコピー", command=self.copy_result, state="disabled")
        self.an_copy_btn.pack(side="left")

        self.refresh_templates()
        if not llms:
            self.an_status_var.set(f"分析用モデルがありません（{llm_dir()}）")
            self.an_btn.state(["disabled"])
            self.an_file_btn.state(["disabled"])

    def refresh_templates(self, select: str | None = None) -> None:
        names = [t.name for t in self.templates]
        self.tpl_box["values"] = names
        cur = select or self.tpl_var.get()
        self.tpl_var.set(cur if cur in names else (names[0] if names else ""))
        if self.result is None:
            self.show_template_preview()

    def current_template(self) -> Template | None:
        return next((t for t in self.templates if t.name == self.tpl_var.get()), None)

    def show_template_preview(self) -> None:
        if self.result is not None or self.busy:
            return
        t = self.current_template()
        w = self.an_text
        w.config(state="normal")
        w.delete("1.0", "end")
        if t:
            w.insert("end", f"「{t.name}」の分析項目\n", "h")
            for i, it in enumerate(t.items, 1):
                w.insert("end", f"{i}. {it.name}\n")
                if it.description:
                    w.insert("end", f"    {it.description}\n", "desc")
            w.insert("end", "\n文字起こしが済んだら「文字起こしタブの内容を分析」を押してください。\n", "meta")
        w.config(state="disabled")

    def show_result(self, r: AnalysisResult) -> None:
        w = self.an_text
        w.config(state="normal")
        w.delete("1.0", "end")
        w.insert(
            "end",
            f"{r.source_label}　｜　{r.template_name}　｜　{r.created.strftime('%Y-%m-%d %H:%M')}\n",
            "meta",
        )
        for it in r.items:
            w.insert("end", f"■ {it.name}\n", "h")
            w.insert("end", it.summary + "\n")
            for e in it.evidence:
                w.insert("end", (f"[{e.time}] " if e.time else "・") + e.point + "\n", "ev")
        w.config(state="disabled")

    # ---------- テンプレート編集 ----------
    def edit_templates(self) -> None:
        if self.busy:
            return
        dlg = TemplateEditor(self.root, self.templates, self.tpl_var.get())
        self.root.wait_window(dlg.win)
        if dlg.saved:
            self.templates = dlg.templates
            save_templates(self.templates)
            self.result = None
            self._set_result_buttons(False)
            self.refresh_templates(dlg.selected)

    # ================= 共通 =================
    def set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _set_result_buttons(self, enabled: bool) -> None:
        st = ["!disabled"] if enabled else ["disabled"]
        for b in (self.xlsx_btn, self.docx_btn, self.an_copy_btn):
            b.state(st)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        st = ["disabled"] if busy else ["!disabled"]
        has_whisper = bool(list_models())
        has_llm = bool(list_llm_models())
        self.open_btn.state(st if has_whisper else ["disabled"])
        if not self.recorder.recording:
            self.rec_btn.state(st if has_whisper else ["disabled"])
        self.model_box.state(["disabled"] if busy else ["!disabled", "readonly"])
        self.tpl_box.state(["disabled"] if busy else ["!disabled", "readonly"])
        self.llm_box.state(["disabled"] if busy else ["!disabled", "readonly"])
        self.an_btn.state(st if has_llm else ["disabled"])
        self.an_file_btn.state(st if has_llm else ["disabled"])
        for b in (self.cancel_btn, self.an_cancel_btn):
            b.state(["!disabled"] if busy else ["disabled"])
        if not busy:
            self.progress["value"] = 0

    def poll(self) -> None:
        from tkinter import messagebox

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
                elif kind == "a_status":
                    self.an_status_var.set(payload)
                elif kind == "a_progress":
                    self.an_progress["value"] = payload
                elif kind == "a_done":
                    self.set_busy(False)
                    self.an_progress["value"] = 0
                    if payload is None:
                        self.an_status_var.set("中止しました。")
                        self.show_template_preview()
                    else:
                        self.result = payload
                        self.show_result(payload)
                        self._set_result_buttons(True)
                        self.an_status_var.set("分析が完了しました。")
                elif kind == "error":
                    self.set_busy(False)
                    self.an_progress["value"] = 0
                    self.set_status("エラーが発生しました")
                    self.an_status_var.set("エラーが発生しました")
                    messagebox.showerror(APP_NAME, payload)
        except queue.Empty:
            pass
        if self.recorder.recording:
            bars = "▮" * int(self.recorder.level * 10)
            self.set_status(f"録音中… {format_time(self.recorder.elapsed())}  {bars}")
        self.root.after(100, self.poll)

    def cancel(self) -> None:
        self.stop_flag.set()
        self.set_status("中止しています…")
        self.an_status_var.set("中止しています…（今の処理が終わり次第止まります）")

    # ================= 録音・文字起こし =================
    def toggle_record(self) -> None:
        from tkinter import messagebox

        if self.recorder.recording:
            audio = self.recorder.stop()
            self.rec_btn.config(text="● 録音開始")
            if audio.size < 16000 * 0.5:
                self.set_status("録音が短すぎます。")
                self.set_busy(False)
                return
            self.last_recording = audio
            self.save_wav_btn.state(["!disabled"])
            self.start_transcription(audio, "録音 " + _now())
        else:
            try:
                self.recorder.start()
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"マイクを開けませんでした。\n\n{e}")
                return
            self.rec_btn.config(text="■ 録音停止")
            self.open_btn.state(["disabled"])
            self.model_box.state(["disabled"])

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
        self.last_label = label
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
                    self.events.put(("done", f"完了しました（{count} 行）。「この内容を分析」で項目別に分析できます。"))
            except Exception:  # noqa: BLE001
                self.events.put(("error", traceback.format_exc(limit=3)))

        threading.Thread(target=work, daemon=True).start()

    # ================= 分析 =================
    def analyze_from_transcript(self) -> None:
        self.nb.select(self.tab_an)
        text = self.text.get("1.0", "end-1c").strip()
        if not text:
            from tkinter import messagebox

            messagebox.showinfo(APP_NAME, "文字起こしタブにテキストがありません。")
            return
        self.start_analysis(text, self.last_label or "文字起こし")

    def analyze_from_file(self) -> None:
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            title="文字起こしテキストを開く", filetypes=[("テキスト", "*.txt"), ("すべてのファイル", "*.*")]
        )
        if not path:
            return
        raw = Path(path).read_bytes()
        for enc in ("utf-8-sig", "cp932", "utf-16"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            messagebox.showerror(APP_NAME, "文字コードを判別できませんでした。")
            return
        self.start_analysis(text, Path(path).name)

    def start_analysis(self, text: str, label: str) -> None:
        from tkinter import messagebox

        if self.busy:
            return
        tpl = self.current_template()
        if tpl is None or not tpl.items:
            messagebox.showinfo(APP_NAME, "分析項目がありません。「項目を編集…」から追加してください。")
            return
        if not self.llm_var.get():
            messagebox.showinfo(APP_NAME, "分析用モデルがありません。")
            return
        tpl = Template(tpl.name, [Item(i.name, i.description) for i in tpl.items])  # 実行中の編集に備えて複製
        llm = self.llm_var.get()
        self.stop_flag.clear()
        self.result = None
        self._set_result_buttons(False)
        self.set_busy(True)
        self.an_text.config(state="normal")
        self.an_text.delete("1.0", "end")
        self.an_text.insert("end", f"「{label}」を「{tpl.name}」の項目で分析しています…\n", "meta")
        self.an_text.insert(
            "end", "パソコンの性能によっては数分〜十数分かかります。そのままお待ちください。\n", "meta"
        )
        self.an_text.config(state="disabled")

        def work() -> None:
            try:
                self.events.put(("a_status", "分析モデルを読み込み中…"))
                self.events.put(("a_progress", 0.02))
                self.analyzer.load(llm)

                def prog(done: int, total: int, msg: str) -> None:
                    self.events.put(("a_status", msg))
                    self.events.put(("a_progress", max(0.02, done / total)))

                res = self.analyzer.analyze(
                    tpl, text, source_label=label, progress=prog, should_stop=self.stop_flag.is_set
                )
                self.events.put(("a_done", res))
            except Exception:  # noqa: BLE001
                self.events.put(("error", traceback.format_exc(limit=3)))

        threading.Thread(target=work, daemon=True).start()

    # ================= 保存・書き出し =================
    def copy_all(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.set_status("クリップボードにコピーしました。")

    def copy_result(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.an_text.get("1.0", "end-1c"))
        self.an_status_var.set("クリップボードにコピーしました。")

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

    def _export(self, kind: str) -> None:
        from tkinter import filedialog, messagebox

        from .export import export_excel, export_word

        if self.result is None:
            return
        ext, label, fn = (".xlsx", "Excel ブック", export_excel) if kind == "xlsx" else (".docx", "Word 文書", export_word)
        stem = f"ヒアリング分析_{self.result.created.strftime('%Y%m%d_%H%M')}"
        path = filedialog.asksaveasfilename(
            title=f"{label}に書き出し", defaultextension=ext, initialfile=stem + ext, filetypes=[(label, "*" + ext)]
        )
        if not path:
            return
        try:
            fn(self.result, path)
        except PermissionError:
            messagebox.showerror(APP_NAME, "保存できませんでした。同じ名前のファイルを開いていたら閉じてください。")
            return
        self.an_status_var.set(f"保存しました: {path}")

    def export_excel(self) -> None:
        self._export("xlsx")

    def export_word(self) -> None:
        self._export("docx")

    def on_close(self) -> None:
        if self.recorder.recording:
            self.recorder.stop()
        self.stop_flag.set()
        self.root.destroy()


class TemplateEditor:
    """分析項目テンプレートの編集ダイアログ。"""

    def __init__(self, parent, templates: list[Template], selected: str) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.templates = [Template(t.name, [Item(i.name, i.description) for i in t.items]) for t in templates]
        self.saved = False
        self.selected = selected
        self.win = win = tk.Toplevel(parent)
        win.title("分析項目の編集")
        win.geometry("820x520")
        win.transient(parent)
        win.grab_set()

        left = ttk.Frame(win, padding=10)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="テンプレート").pack(anchor="w")
        self.tpl_list = tk.Listbox(left, width=24, exportselection=False, font=("Yu Gothic UI", 10))
        self.tpl_list.pack(fill="y", expand=True, pady=4)
        self.tpl_list.bind("<<ListboxSelect>>", lambda e: self.load_items())
        for txt, cmd in (("新規", self.new_tpl), ("複製", self.dup_tpl), ("名前を変更", self.rename_tpl), ("削除", self.del_tpl)):
            ttk.Button(left, text=txt, command=cmd).pack(fill="x", pady=1)

        right = ttk.Frame(win, padding=(0, 10, 10, 10))
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="分析項目（上から順に分析・出力されます）").pack(anchor="w")
        self.tree = ttk.Treeview(right, columns=("name", "desc"), show="headings", height=12, selectmode="browse")
        self.tree.heading("name", text="項目名")
        self.tree.heading("desc", text="何を拾うか（AIへの説明）")
        self.tree.column("name", width=160)
        self.tree.column("desc", width=380)
        self.tree.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.fill_fields())

        form = ttk.Frame(right)
        form.pack(fill="x", pady=4)
        ttk.Label(form, text="項目名").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(form, text="説明").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.desc_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.desc_var).grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=4)
        for txt, cmd in (("追加", self.add_item), ("選択中を更新", self.update_item), ("削除", self.del_item), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1))):
            ttk.Button(btns, text=txt, command=cmd, width=12 if len(txt) > 1 else 3).pack(side="left", padx=(0, 4))

        foot = ttk.Frame(right)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Button(foot, text="キャンセル", command=win.destroy).pack(side="right")
        ttk.Button(foot, text="保存して閉じる", command=self.save).pack(side="right", padx=6)

        self.refresh_list(selected)

    # --- テンプレート ---
    def cur(self) -> Template | None:
        sel = self.tpl_list.curselection()
        return self.templates[sel[0]] if sel else None

    def refresh_list(self, select: str | None = None) -> None:
        self.tpl_list.delete(0, "end")
        for t in self.templates:
            self.tpl_list.insert("end", t.name)
        names = [t.name for t in self.templates]
        idx = names.index(select) if select in names else 0
        if names:
            self.tpl_list.selection_set(idx)
            self.tpl_list.see(idx)
        self.load_items()

    def _ask_name(self, title: str, initial: str = "") -> str | None:
        from tkinter import messagebox, simpledialog

        name = simpledialog.askstring(title, "テンプレート名", initialvalue=initial, parent=self.win)
        if name is None:
            return None
        name = name.strip()
        if not name:
            return None
        if any(t.name == name for t in self.templates) and name != initial:
            messagebox.showwarning(title, "同じ名前のテンプレートがあります。", parent=self.win)
            return None
        return name

    def new_tpl(self) -> None:
        name = self._ask_name("新しいテンプレート")
        if name:
            self.templates.append(Template(name, []))
            self.refresh_list(name)

    def dup_tpl(self) -> None:
        t = self.cur()
        if not t:
            return
        name = self._ask_name("テンプレートを複製", t.name + "（コピー）")
        if name:
            self.templates.append(Template(name, [Item(i.name, i.description) for i in t.items]))
            self.refresh_list(name)

    def rename_tpl(self) -> None:
        t = self.cur()
        if not t:
            return
        name = self._ask_name("名前を変更", t.name)
        if name:
            t.name = name
            self.refresh_list(name)

    def del_tpl(self) -> None:
        from tkinter import messagebox

        t = self.cur()
        if not t:
            return
        if len(self.templates) == 1:
            messagebox.showinfo("削除", "最後のテンプレートは削除できません。", parent=self.win)
            return
        if messagebox.askyesno("削除", f"「{t.name}」を削除しますか？", parent=self.win):
            self.templates.remove(t)
            self.refresh_list()

    # --- 項目 ---
    def load_items(self, select: int | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        t = self.cur()
        if not t:
            return
        for i, it in enumerate(t.items):
            self.tree.insert("", "end", iid=str(i), values=(it.name, it.description))
        if select is not None and 0 <= select < len(t.items):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def sel_index(self) -> int | None:
        s = self.tree.selection()
        return int(s[0]) if s else None

    def fill_fields(self) -> None:
        t, i = self.cur(), self.sel_index()
        if t and i is not None:
            self.name_var.set(t.items[i].name)
            self.desc_var.set(t.items[i].description)

    def add_item(self) -> None:
        t = self.cur()
        name = self.name_var.get().strip()
        if not t or not name:
            return
        t.items.append(Item(name, self.desc_var.get().strip()))
        self.name_var.set("")
        self.desc_var.set("")
        self.load_items(len(t.items) - 1)

    def update_item(self) -> None:
        t, i = self.cur(), self.sel_index()
        name = self.name_var.get().strip()
        if t and i is not None and name:
            t.items[i] = Item(name, self.desc_var.get().strip())
            self.load_items(i)

    def del_item(self) -> None:
        t, i = self.cur(), self.sel_index()
        if t and i is not None:
            del t.items[i]
            self.load_items(min(i, len(t.items) - 1))

    def move(self, d: int) -> None:
        t, i = self.cur(), self.sel_index()
        if t and i is not None and 0 <= i + d < len(t.items):
            t.items[i], t.items[i + d] = t.items[i + d], t.items[i]
            self.load_items(i + d)

    def save(self) -> None:
        t = self.cur()
        self.selected = t.name if t else ""
        self.saved = True
        self.win.destroy()


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")


SELFTEST_TRANSCRIPT = """\
[00:00 → 00:08] 本日はお時間いただきありがとうございます。早速ですが、今の困りごとを教えてください。
[00:08 → 00:25] はい、今は請求書の作成を全部エクセルで手作業でやっていて、毎月末に三日くらいかかってしまうんです。
[00:25 → 00:40] 入力ミスも多くて、取引先から指摘されることもあります。
[00:40 → 00:55] 予算としては、年間で百万円くらいまでなら検討できると思います。
[00:55 → 01:10] 導入は来年の四月、新年度に合わせたいですね。最終的な判断は経理部長がします。
"""


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

        llms = list_llm_models()
        lines.append(f"llm models: {llms}")
        if not llms:
            raise RuntimeError("no llm bundled")
        a = Analyzer()
        a.load(llms[0])
        tpl = Template(
            "test",
            [Item("課題・困りごと", "相手が抱えている問題"), Item("予算感", "費用や予算"), Item("導入時期", "時期"), Item("競合", "他社")],
        )
        res = a.analyze(tpl, SELFTEST_TRANSCRIPT, "selftest")
        for it in res.items:
            lines.append(f"[{it.name}] {it.summary}")
            for e in it.evidence:
                lines.append(f"    ({e.time}) {e.point}")
        if not res.items[0].evidence or not res.items[1].evidence:
            raise RuntimeError("analysis returned no findings for obvious items")

        from tempfile import TemporaryDirectory

        from .export import export_excel, export_word

        with TemporaryDirectory() as d:
            export_excel(res, Path(d) / "t.xlsx")
            export_word(res, Path(d) / "t.docx")
            lines.append(f"export ok: {sorted(p.name for p in Path(d).iterdir())}")
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
