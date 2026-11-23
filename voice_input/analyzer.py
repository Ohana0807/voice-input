"""ローカル言語モデル（llama.cpp）によるヒアリング内容の項目別分析。

長い文字起こしは数千文字ずつに分け、
  1. 各区間から項目ごとに該当する発言（要点＋時刻）を抜き出す
  2. 項目ごとに抜き出した内容をまとめる
の 2 段階で処理する。インターネットには接続しない。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .templates import Template
from .transcriber import models_dir

CHUNK_CHARS = 2500
MAX_FINDINGS_PER_CHUNK = 4

SYSTEM_PROMPT = (
    "あなたはヒアリング記録を分析する有能なアシスタントです。"
    "与えられた文字起こしだけを根拠に、指定された項目ごとに情報を整理します。"
    "文字起こしに書かれていないことは推測で補いません。出力は必ず日本語で書きます。"
)


def llm_dir() -> Path:
    return models_dir() / "llm"


def list_llm_models() -> list[str]:
    d = llm_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("*.gguf"))


@dataclass
class Evidence:
    time: str
    point: str


@dataclass
class ItemResult:
    name: str
    description: str
    summary: str = ""
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class AnalysisResult:
    template_name: str
    source_label: str
    model_name: str
    created: datetime
    items: list[ItemResult]
    transcript: str


def split_chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > limit:  # 改行のない長文への対策
            if buf:
                chunks.append("\n".join(buf))
                buf, size = [], 0
            chunks.append(line[:limit])
            line = line[limit:]
        if size + len(line) > limit and buf:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def _items_block(template: Template) -> str:
    lines = []
    for i, it in enumerate(template.items, 1):
        desc = f"：{it.description}" if it.description else ""
        lines.append(f"i{i}. {it.name}{desc}")
    return "\n".join(lines)


class Analyzer:
    def __init__(self) -> None:
        self._llm = None
        self._name: str | None = None

    def load(self, name: str) -> None:
        if self._llm is not None and self._name == name:
            return
        from llama_cpp import Llama  # 遅延 import

        path = llm_dir() / name
        if not path.is_file():
            raise FileNotFoundError(f"分析用モデルが見つかりません: {path}")
        self._llm = Llama(
            model_path=str(path),
            n_ctx=8192,
            n_batch=512,
            n_threads=max(1, (os.cpu_count() or 4) - 1),
            chat_format="chatml",
            verbose=False,
        )
        self._name = name

    def _ask(self, user: str, schema: dict, max_tokens: int) -> dict:
        res = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object", "schema": schema},
            temperature=0.2,
            max_tokens=max_tokens,
        )
        content = res["choices"][0]["message"]["content"] or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 出力が途中で切れた場合など。取れた分だけ使う
            return {}

    # ---- 1. 抽出 ----
    def _extract(self, template: Template, chunk: str) -> dict[str, list[Evidence]]:
        keys = [f"i{i}" for i in range(1, len(template.items) + 1)]
        finding = {
            "type": "object",
            "properties": {"time": {"type": "string"}, "point": {"type": "string"}},
            "required": ["time", "point"],
        }
        schema = {
            "type": "object",
            "properties": {k: {"type": "array", "items": finding, "maxItems": MAX_FINDINGS_PER_CHUNK} for k in keys},
            "required": keys,
        }
        user = (
            "次の文字起こしから、各分析項目に当てはまる内容を抜き出してください。\n"
            "- point：その内容の要点（1文、60文字以内）\n"
            "- time：その発言の行頭にある [開始時刻 → 終了時刻] の開始時刻（例 03:15）。時刻が無ければ空文字\n"
            f"- 1つの項目につき最大{MAX_FINDINGS_PER_CHUNK}件。当てはまる内容が無い項目は空の配列 []\n\n"
            f"## 分析項目\n{_items_block(template)}\n\n## 文字起こし\n{chunk}"
        )
        data = self._ask(user, schema, max_tokens=1500)
        out: dict[str, list[Evidence]] = {}
        for k in keys:
            vals = data.get(k) or []
            out[k] = [
                Evidence(str(v.get("time", "")).strip(), str(v.get("point", "")).strip())
                for v in vals
                if isinstance(v, dict) and str(v.get("point", "")).strip()
            ]
        return out

    # ---- 2. まとめ ----
    def _summarize(self, template: Template, found: dict[str, list[Evidence]]) -> dict[str, str]:
        keys = [k for k, v in found.items() if v]
        if not keys:
            return {}
        schema = {
            "type": "object",
            "properties": {k: {"type": "string"} for k in keys},
            "required": keys,
        }
        blocks = []
        for k in keys:
            idx = int(k[1:]) - 1
            it = template.items[idx]
            pts = "\n".join(f"  - {e.point}" for e in found[k])
            desc = f"（{it.description}）" if it.description else ""
            blocks.append(f"{k}. {it.name}{desc}\n{pts}")
        user = (
            "以下は、ヒアリングから項目ごとに抜き出した要点です。"
            "項目ごとに、要点を重複なく統合して 1〜3 文のまとめを書いてください。"
            "要点に無いことは書かないでください。\n\n" + "\n\n".join(blocks)
        )
        data = self._ask(user, schema, max_tokens=300 * len(keys) + 200)
        return {k: str(data.get(k, "")).strip() for k in keys}

    def analyze(
        self,
        template: Template,
        transcript: str,
        source_label: str = "",
        progress: Callable[[int, int, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> AnalysisResult | None:
        if self._llm is None:
            raise RuntimeError("分析用モデルが読み込まれていません")
        if not template.items:
            raise ValueError("テンプレートに分析項目がありません")
        chunks = split_chunks(transcript)
        if not chunks:
            raise ValueError("分析するテキストがありません")
        total = len(chunks) + 1
        found: dict[str, list[Evidence]] = {f"i{i}": [] for i in range(1, len(template.items) + 1)}

        for n, chunk in enumerate(chunks, 1):
            if should_stop and should_stop():
                return None
            if progress:
                progress(n - 1, total, f"内容を読み取り中（{n}/{len(chunks)}）…")
            for k, evs in self._extract(template, chunk).items():
                seen = {e.point for e in found[k]}
                found[k].extend(e for e in evs if e.point not in seen)

        if should_stop and should_stop():
            return None
        if progress:
            progress(len(chunks), total, "項目ごとにまとめ中…")
        summaries = self._summarize(template, found)
        if progress:
            progress(total, total, "完了")

        items = []
        for i, it in enumerate(template.items, 1):
            k = f"i{i}"
            summary = summaries.get(k) or ("（言及なし）" if not found[k] else "；".join(e.point for e in found[k]))
            items.append(ItemResult(it.name, it.description, summary, found[k]))
        return AnalysisResult(
            template_name=template.name,
            source_label=source_label,
            model_name=self._name or "",
            created=datetime.now(),
            items=items,
            transcript=transcript,
        )
