# Voice Input

Whisper（faster-whisper）で音声を文字にし、ヒアリング内容を指定した項目ごとに分析する、**完全オフライン**の Windows デスクトップアプリです。
音声もテキストも分析結果も、外部には一切送られません。

## できること

### 文字起こしタブ
- マイクで録音 → 停止すると自動で文字起こし
- 音声・動画ファイル（wav / mp3 / m4a / mp4 など）を開いて文字起こし
- 言語の選択（日本語 / 英語 / 自動判定）、時刻付き表示、無音部分のスキップ
- 結果の編集、コピー、テキスト保存（.txt）、録音の WAV 保存

### ヒアリング分析タブ
- 文字起こしの内容（または .txt ファイル）を、テンプレートの項目ごとに AI が整理
- 項目ごとに「まとめ」と「根拠（発言の時刻と要点）」を表示
- 分析項目は「項目を編集…」から自由に追加・変更・並べ替え。テンプレートを複数持てます
  （最初から「営業ヒアリング」「業務改善ヒアリング」を用意しています）
- **Excel**（項目／まとめ／根拠の表＋文字起こしシート）と **Word**（概要表＋項目ごとの詳細＋文字起こし）に書き出し

分析はパソコンの CPU で動くため、1 時間程度のヒアリングで数分〜十数分かかります。

## ダウンロードと起動

1. GitHub の **Actions** タブ →「Build Windows app」→ 最新の成功した実行を開く
2. 下の **Artifacts** から `VoiceInput-windows-small-qwen3-4b` をダウンロードして展開（約 3GB）
3. フォルダ内の `VoiceInput.exe` をダブルクリック

初回起動時に Windows SmartScreen が出たら「詳細情報」→「実行」を選んでください（署名していないため表示されます）。
フォルダごと好きな場所に置いて使えます。`models` フォルダは exe と同じ場所に置いたままにしてください。
メモリは 8GB 以上を推奨します。

テンプレートは `%APPDATA%\VoiceInput\templates.json` に保存されます。アプリを入れ替えても消えません。

## モデルの選び方

Actions →「Build Windows app」→「Run workflow」で、同梱するモデルを選んでビルドできます。

**文字起こし（Whisper）**

| モデル | 大きさ | 速さ | 精度 |
|---|---|---|---|
| base | 約 150MB | とても速い | 低め |
| small（既定） | 約 500MB | 速い | 実用的 |
| medium | 約 1.5GB | 遅め | 高い |
| large-v3-turbo | 約 1.6GB | 遅め | とても高い |

**分析（言語モデル Qwen3）**

| モデル | 大きさ | 速さ | 分析の質 |
|---|---|---|---|
| qwen3-1.7b | 約 2GB | 速い | 簡易 |
| qwen3-4b（既定） | 約 2.5GB | 普通 | 実用的 |
| qwen3-8b | 約 5GB | 遅い | 高い（メモリ 16GB 推奨） |

## Docker で試す（画面なし）

Docker では画面とマイク録音は使えません。音声ファイル（または文字起こし済みの .txt）を渡すと、
文字起こし → 項目別分析 → テキスト / Excel / Word への書き出しまでをコマンドで行います。
以下は Docker Desktop を入れた Windows の PowerShell で、リポジトリのフォルダから実行します。

```powershell
# 1. イメージを作る（初回のみ。数分かかります）
docker compose build

# 2. モデルを ./models にダウンロードする（初回のみ）
docker compose run --rm --entrypoint python voice-input scripts/download_model.py small
docker compose run --rm --entrypoint python voice-input scripts/download_llm.py qwen3-4b

# 3. 試したい音声を ./data に置いて実行する
docker compose run --rm voice-input /data/sample.m4a
```

結果は `./data` に `sample.txt`（文字起こし）、`sample_分析.xlsx`、`sample_分析.docx` として保存されます。

よく使うオプション:

| オプション | 内容 |
|---|---|
| `--list` | 使えるモデルとテンプレートを表示 |
| `--no-analyze` | 文字起こしだけ行う |
| `--template 業務改善ヒアリング` | 分析テンプレートを選ぶ |
| `--lang en` / `--lang auto` | 言語（既定は日本語） |
| `--model medium` | Whisper モデルを選ぶ |

Docker Desktop のメモリ割り当ては 8GB 以上にしてください（設定 → Resources）。

## 開発者向け

```powershell
pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu -r requirements.txt
python scripts\download_model.py small     # models\small に保存
python scripts\download_llm.py qwen3-4b    # models\llm に保存
python run.py                              # 起動
.\build.ps1                                # exe 作成（dist\VoiceInput）
```
