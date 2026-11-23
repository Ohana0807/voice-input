"""画面なしで動かすためのコマンドライン版（Docker 用）。

音声・動画ファイルを文字起こしし、続けてテンプレートの項目ごとに分析して
テキスト / Excel / Word に書き出す。.txt を渡した場合は分析だけを行う。

使い方の例:
  python -m voice_input.cli /data/meeting.m4a
  python -m voice_input.cli /data/meeting.m4a --no-analyze
  python -m voice_input.cli /data/transcript.txt --template 業務改善ヒアリング
  python -m voice_input.cli --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import Analyzer, list_llm_models, llm_dir
from .templates import load_templates
from .transcriber import Transcriber, format_time, list_models, models_dir

LANGUAGES = {"ja": "ja", "en": "en", "auto": None}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"文字コードを判別できませんでした: {path}")


def _progress_bar(p: float) -> None:
    print(f"\r  文字起こし中… {int(p * 100):3d}%", end="", file=sys.stderr, flush=True)


def transcribe(path: Path, model: str, language: str | None, vad: bool, timestamps: bool) -> str:
    t = Transcriber()
    print(f"Whisper モデル「{model}」を読み込み中…", file=sys.stderr)
    t.load(model)
    lines = []
    for seg in t.transcribe(str(path), language=language, vad=vad, progress=_progress_bar):
        if not seg.text:
            continue
        line = f"[{format_time(seg.start)} → {format_time(seg.end)}] {seg.text}" if timestamps else seg.text
        lines.append(line)
    print(file=sys.stderr)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="voice-input", description="Voice Input のコマンドライン版")
    ap.add_argument("input", nargs="?", help="音声・動画ファイル、または文字起こし済みの .txt")
    ap.add_argument("-o", "--out", help="出力先フォルダ（既定: 入力ファイルと同じ場所）")
    ap.add_argument("--model", help="Whisper モデル名（既定: models 内の最初のもの）")
    ap.add_argument("--llm", help="分析用モデルのファイル名（.gguf。既定: models/llm 内の最初のもの）")
    ap.add_argument("--template", help="分析テンプレート名（既定: 最初のテンプレート）")
    ap.add_argument("--lang", choices=LANGUAGES, default="ja", help="言語（既定: ja）")
    ap.add_argument("--no-vad", action="store_true", help="無音部分をスキップしない")
    ap.add_argument("--no-timestamps", action="store_true", help="時刻を付けない")
    ap.add_argument("--no-analyze", action="store_true", help="文字起こしだけ行う")
    ap.add_argument("--list", action="store_true", help="使えるモデルとテンプレートを表示して終了")
    args = ap.parse_args(argv)

    templates = load_templates()
    if args.list or not args.input:
        print(f"models フォルダ: {models_dir()}")
        print("Whisper モデル :", ", ".join(list_models()) or "（なし）")
        print("分析用モデル   :", ", ".join(list_llm_models()) or "（なし）")
        print("テンプレート   :", ", ".join(t.name for t in templates))
        if not args.input and not args.list:
            ap.print_usage()
        return 0

    src = Path(args.input)
    if not src.is_file():
        raise SystemExit(f"ファイルが見つかりません: {src}")
    out_dir = Path(args.out) if args.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    # ---- 文字起こし ----
    if src.suffix.lower() == ".txt":
        text = _read_text(src)
    else:
        models = list_models()
        model = args.model or (models[0] if models else None)
        if not model:
            raise SystemExit(f"Whisper モデルがありません。{models_dir()} にダウンロードしてください。")
        text = transcribe(src, model, LANGUAGES[args.lang], not args.no_vad, not args.no_timestamps)
        if not text.strip():
            raise SystemExit("音声を聞き取れませんでした。")
        txt_path = out_dir / f"{stem}.txt"
        txt_path.write_text(text + "\n", encoding="utf-8")
        print(f"文字起こし: {txt_path}", file=sys.stderr)

    if args.no_analyze:
        return 0

    # ---- 分析 ----
    llms = list_llm_models()
    llm = args.llm or (llms[0] if llms else None)
    if not llm:
        raise SystemExit(f"分析用モデルがありません。{llm_dir()} にダウンロードしてください。")
    if args.template:
        tpl = next((t for t in templates if t.name == args.template), None)
        if tpl is None:
            raise SystemExit(f"テンプレート「{args.template}」がありません: " + ", ".join(t.name for t in templates))
    else:
        tpl = templates[0]

    an = Analyzer()
    print(f"分析用モデル「{llm}」を読み込み中…", file=sys.stderr)
    an.load(llm)
    result = an.analyze(
        tpl,
        text,
        source_label=src.name,
        progress=lambda done, total, msg: print(f"  [{done}/{total}] {msg}", file=sys.stderr, flush=True),
    )
    if result is None:
        return 1

    from .export import export_excel, export_word

    xlsx = out_dir / f"{stem}_分析.xlsx"
    docx = out_dir / f"{stem}_分析.docx"
    export_excel(result, xlsx)
    export_word(result, docx)

    print(f"\n== {tpl.name} ==")
    for item in result.items:
        print(f"■ {item.name}\n  {item.summary}")
    print(f"\nExcel: {xlsx}\nWord : {docx}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
