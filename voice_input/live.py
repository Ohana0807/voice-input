"""録音中の逐次文字起こし。

録音を少しずつ受け取り、話の切れ目（短い無音）で区切って、区切った分から順に文字起こしする。
同じ音声を二度認識しないので、文字が重複したり書き換わったりしない。
"""

from __future__ import annotations

import time
from typing import Callable

import numpy as np

from .transcriber import Segment, Transcriber

SR = 16000
FRAME = 480  # 30ms
MIN_CHUNK = 1.5  # これより短い区切りは作らない（秒）
MAX_CHUNK = 12.0  # 無音が来なくてもこの長さで区切る（秒）
SILENCE = 0.5  # この長さの無音で区切る（秒）
MIN_LEVEL = 0.004  # これ未満の音量は常に無音とみなす


def frame_rms(audio: np.ndarray) -> np.ndarray:
    n = audio.size // FRAME
    if n == 0:
        return np.zeros(0, np.float32)
    f = audio[: n * FRAME].reshape(n, FRAME).astype(np.float64)
    return np.sqrt((f * f).mean(axis=1))


def _threshold(rms: np.ndarray) -> float:
    return max(MIN_LEVEL, float(np.percentile(rms, 10)) * 2.5)


def has_speech(audio: np.ndarray) -> bool:
    rms = frame_rms(audio)
    if rms.size == 0:
        return False
    loud = rms >= max(_threshold(rms), MIN_LEVEL * 2.5)
    return int(loud.sum()) >= 5  # 150ms 以上の音


def find_cut(buf: np.ndarray) -> int | None:
    """buf のどこで区切るか（サンプル位置）。まだ区切らないなら None。"""
    if buf.size < MIN_CHUNK * SR:
        return None
    rms = frame_rms(buf)
    quiet = rms < _threshold(rms)
    need = int(SILENCE * SR / FRAME)
    if quiet[-need:].all():
        return rms.size * FRAME
    if buf.size >= MAX_CHUNK * SR:
        # 後半のいちばん静かなところで区切る
        half = rms.size // 2
        smooth = np.convolve(rms[half:], np.ones(5) / 5, mode="same")
        return (half + int(np.argmin(smooth)) + 1) * FRAME
    return None


class LiveSession:
    """録音中に呼び続け、区切れた分から文字起こしして on_segment に渡す。"""

    def __init__(
        self,
        read_new: Callable[[], np.ndarray],
        is_recording: Callable[[], bool],
        transcriber: Transcriber,
        language: str | None,
        on_segment: Callable[[Segment], None],
        on_backlog: Callable[[float], None] | None = None,
    ) -> None:
        self.read_new = read_new
        self.is_recording = is_recording
        self.transcriber = transcriber
        self.language = language
        self.on_segment = on_segment
        self.on_backlog = on_backlog

    def _transcribe(self, chunk: np.ndarray, offset: float) -> int:
        n = 0
        for seg in self.transcriber.transcribe(chunk, language=self.language, vad=True):
            if seg.text:
                self.on_segment(Segment(seg.start + offset, seg.end + offset, seg.text))
                n += 1
        return n

    def run(self, should_stop: Callable[[], bool] = lambda: False) -> int:
        """録音が止まり、残りを文字起こしし終えたら戻る。戻り値は出力した行数。"""
        buf = np.zeros(0, np.float32)
        offset = 0.0
        count = 0
        while not should_stop():
            recording = self.is_recording()  # 先に見る：False なら以後のチャンクは揃っている
            new = self.read_new()
            if new.size:
                buf = np.concatenate([buf, new])
            if not recording and new.size == 0:
                if buf.size >= 0.3 * SR and has_speech(buf):
                    count += self._transcribe(buf, offset)
                break
            cut = find_cut(buf)
            if cut is None:
                if self.on_backlog:
                    self.on_backlog(buf.size / SR)
                time.sleep(0.15)
                continue
            chunk, buf = buf[:cut], buf[cut:]
            if has_speech(chunk):
                count += self._transcribe(chunk, offset)
            offset += cut / SR
        return count
