"""分析項目テンプレートの保存・読み込み。

保存先: %APPDATA%\\VoiceInput\\templates.json（Windows 以外は ~/.voice_input/）
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Item:
    name: str
    description: str = ""


@dataclass
class Template:
    name: str
    items: list[Item] = field(default_factory=list)


DEFAULT_TEMPLATES = [
    Template(
        "営業ヒアリング",
        [
            Item("課題・困りごと", "相手が抱えている問題や不満"),
            Item("現状の運用", "今どのようなやり方・ツールで対応しているか"),
            Item("要望・期待", "解決策や提案に求めていること"),
            Item("予算感", "費用や予算に関する発言"),
            Item("決裁者・関係者", "意思決定に関わる人や部署"),
            Item("導入時期", "いつまでに・いつ頃といった時期の話"),
            Item("比較検討・競合", "検討している他社・他の方法"),
            Item("懸念点", "不安・リスク・反対意見"),
            Item("次のアクション", "次回までにやること、約束したこと"),
        ],
    ),
    Template(
        "業務改善ヒアリング",
        [
            Item("担当業務", "対象者が担当している業務の内容"),
            Item("業務の流れ", "作業の手順や関係する部署・システム"),
            Item("課題・ムダ", "時間がかかる、ミスが起きやすいなどの問題点"),
            Item("改善のアイデア", "本人が考えている改善案や要望"),
            Item("優先度・影響", "どれくらい困っているか、影響の大きさ"),
            Item("制約・前提条件", "変えられないルールや前提"),
        ],
    ),
]


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "VoiceInput" if base else Path.home() / ".voice_input"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path() -> Path:
    return config_dir() / "templates.json"


def load_templates() -> list[Template]:
    p = _path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = [
                Template(t["name"], [Item(i["name"], i.get("description", "")) for i in t.get("items", [])])
                for t in data
            ]
            if ts:
                return ts
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return [Template(t.name, [Item(i.name, i.description) for i in t.items]) for t in DEFAULT_TEMPLATES]


def save_templates(templates: list[Template]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(t) for t in templates], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
