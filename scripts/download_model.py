"""Whisper モデルを models フォルダに保存する（ビルド時に一度だけネット接続が必要）。

使い方: python scripts/download_model.py small [保存先の models フォルダ]
"""

import sys
from pathlib import Path

from faster_whisper.utils import download_model


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "small"
    dest_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "models"
    dest = dest_root / name
    dest.mkdir(parents=True, exist_ok=True)
    print(f"downloading '{name}' -> {dest}")
    download_model(name, output_dir=str(dest))
    for junk in dest.glob(".*"):
        if junk.is_file():
            junk.unlink()
    print("done")


if __name__ == "__main__":
    main()
