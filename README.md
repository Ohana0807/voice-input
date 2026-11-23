# Voice Input

Whisper（faster-whisper）で音声を文字にする、**完全オフライン**の Windows デスクトップアプリです。
音声もテキストも外部に送られません。

## できること

- マイクで録音 → 停止すると自動で文字起こし
- 音声・動画ファイル（wav / mp3 / m4a / mp4 など）を開いて文字起こし
- 言語の選択（日本語 / 英語 / 自動判定）、時刻付き表示、無音部分のスキップ
- 結果の編集、コピー、テキスト保存（.txt）、録音の WAV 保存

## ダウンロードと起動

1. GitHub の **Actions** タブ →「Build Windows app」→ 最新の成功した実行を開く
2. 下の **Artifacts** から `VoiceInput-windows-small` をダウンロードして展開
3. フォルダ内の `VoiceInput.exe` をダブルクリック

初回起動時に Windows SmartScreen が出たら「詳細情報」→「実行」を選んでください（署名していないため表示されます）。
フォルダごと好きな場所に置いて使えます。`models` フォルダは exe と同じ場所に置いたままにしてください。

## モデルの選び方

| モデル | 大きさ | 速さ | 精度 |
|---|---|---|---|
| base | 約 150MB | とても速い | 低め |
| small（既定） | 約 500MB | 速い | 実用的 |
| medium | 約 1.5GB | 遅め | 高い |
| large-v3-turbo | 約 1.6GB | 遅め | とても高い |

別のモデルが欲しいときは Actions →「Build Windows app」→「Run workflow」でモデルを選んでビルドします。
複数のモデルを使いたい場合は、それぞれの `models` 内のフォルダを 1 つの `models` フォルダにまとめると、アプリ上で切り替えられます。

## 開発者向け

```powershell
pip install -r requirements.txt
python scripts\download_model.py small   # models\small に保存
python run.py                            # 起動
.\build.ps1                              # exe 作成（dist\VoiceInput）
```

`v1.0.0` のようなタグを push すると、zip を添付した Release が自動で作られます。
