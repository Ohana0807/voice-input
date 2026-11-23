"""分析用の言語モデル（GGUF）を models/llm に保存する（ビルド時に一度だけネット接続が必要）。

使い方: python scripts/download_llm.py qwen3-4b [保存先の models フォルダ]
"""

import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

# 名前 → (リポジトリ, ファイル名) の候補。上から順に試す
CANDIDATES = {
    "qwen3-1.7b": [
        ("Qwen/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q8_0.gguf"),
        ("unsloth/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q4_K_M.gguf"),
    ],
    "qwen3-4b": [
        ("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"),
        ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf"),
        ("unsloth/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf"),
    ],
    "qwen3-8b": [
        ("Qwen/Qwen3-8B-GGUF", "Qwen3-8B-Q4_K_M.gguf"),
        ("unsloth/Qwen3-8B-GGUF", "Qwen3-8B-Q4_K_M.gguf"),
    ],
}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "qwen3-4b"
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "models"
    dest = root / "llm"
    dest.mkdir(parents=True, exist_ok=True)
    errors = []
    for repo, fname in CANDIDATES[name]:
        try:
            print(f"downloading {repo}/{fname} -> {dest}")
            hf_hub_download(repo_id=repo, filename=fname, local_dir=str(dest))
            cache = dest / ".cache"
            if cache.exists():
                import shutil

                shutil.rmtree(cache, ignore_errors=True)
            print("done")
            return
        except Exception as e:  # noqa: BLE001
            print(f"  failed: {e}")
            errors.append(f"{repo}/{fname}: {e}")
    raise SystemExit("all candidates failed:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
