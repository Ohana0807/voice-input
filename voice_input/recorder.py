"""マイク録音。デバイス既定のサンプルレートで録って 16kHz モノラルに変換する。"""

from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np

TARGET_SR = 16000


def resample(audio: np.ndarray, src_sr: int, dst_sr: int = TARGET_SR) -> np.ndarray:
    """線形補間による簡易リサンプリング（音声認識用途には十分）。"""
    if src_sr == dst_sr or audio.size == 0:
        return audio.astype(np.float32)
    n_out = int(round(audio.size * dst_sr / src_sr))
    x_old = np.arange(audio.size, dtype=np.float64) / src_sr
    x_new = np.arange(n_out, dtype=np.float64) / dst_sr
    return np.interp(x_new, x_old, audio).astype(np.float32)


def save_wav(path: str | Path, audio: np.ndarray, sr: int = TARGET_SR) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


class Recorder:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._sr = TARGET_SR
        self._lock = threading.Lock()
        self._read_pos = 0  # read_new で渡し済みのチャンク数
        self.level = 0.0  # 直近の音量（0〜1）

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd

        info = sd.query_devices(kind="input")
        self._sr = int(info["default_samplerate"]) or 44100
        self._chunks = []
        self._read_pos = 0

        def callback(indata, frames, time, status):  # noqa: ARG001
            mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
            with self._lock:
                self._chunks.append(mono)
            self.level = float(min(1.0, np.abs(mono).max() * 1.5)) if mono.size else 0.0

        self._stream = sd.InputStream(
            samplerate=self._sr, channels=1, dtype="float32", callback=callback
        )
        self._stream.start()

    def elapsed(self) -> float:
        with self._lock:
            return sum(c.size for c in self._chunks) / self._sr

    def read_new(self) -> np.ndarray:
        """前回の呼び出し以降に録れた分を 16kHz モノラル float32 で返す（録音中の逐次文字起こし用）。"""
        with self._lock:
            new = self._chunks[self._read_pos :]
            self._read_pos = len(self._chunks)
        if not new:
            return np.zeros(0, np.float32)
        return resample(np.concatenate(new), self._sr)

    def stop(self) -> np.ndarray:
        """録音を止め、録音全体を 16kHz モノラル float32 の配列で返す。

        read_new でまだ読んでいない分は、停止後も read_new で受け取れる。
        """
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.level = 0.0
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        return resample(audio, self._sr)
