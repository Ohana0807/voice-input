"""faster-whisper を使ったオフライン文字起こし。

モデルは exe（または開発時はリポジトリ直下）の隣にある models フォルダから読み込む。
インターネットには一切接続しない。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

# 念のため Hugging Face へのアクセスを完全に止める
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def app_dir() -> Path:
    """exe のあるフォルダ（開発時はリポジトリ直下）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    return app_dir() / "models"


def list_models() -> list[str]:
    """models フォルダ内の利用可能なモデル名（model.bin を含むフォルダ）。"""
    d = models_dir()
    if not d.is_dir():
        return []
    names = [p.name for p in d.iterdir() if (p / "model.bin").is_file()]
    order = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
    return sorted(names, key=lambda n: (order.index(n) if n in order else 99, n))


@dataclass
class Segment:
    start: float
    end: float
    text: str


class Transcriber:
    def __init__(self) -> None:
        self._model = None
        self._model_name: str | None = None

    def load(self, name: str) -> None:
        if self._model is not None and self._model_name == name:
            return
        from faster_whisper import WhisperModel  # 起動を速くするため遅延 import

        path = models_dir() / name
        if not (path / "model.bin").is_file():
            raise FileNotFoundError(f"モデルが見つかりません: {path}")
        threads = max(1, (os.cpu_count() or 4) - 1)
        self._model = WhisperModel(
            str(path), device="cpu", compute_type="int8", cpu_threads=threads
        )
        self._model_name = name

    def transcribe(
        self,
        audio: str | np.ndarray,
        language: str | None = "ja",
        vad: bool = True,
        progress: Callable[[float], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> Iterator[Segment]:
        """音声ファイルのパス、または 16kHz モノラル float32 配列を文字起こしする。"""
        if self._model is None:
            raise RuntimeError("モデルが読み込まれていません")
        segments, info = self._model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=vad,
            condition_on_previous_text=False,
        )
        duration = info.duration or 0.0
        for s in segments:
            if should_stop and should_stop():
                break
            if progress and duration > 0:
                progress(min(1.0, s.end / duration))
            yield Segment(s.start, s.end, s.text.strip())
        if progress:
            progress(1.0)


def format_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
