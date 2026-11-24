# Build the Windows distribution folder: dist\VoiceInput
# Usage:  .\build.ps1               (Whisper "small")
#         .\build.ps1 -Model base   (より軽く速い)
param(
    [string]$Model = "small"
)
$ErrorActionPreference = "Stop"

python -m pip install --prefer-binary -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

pyinstaller run.py --name VoiceInput --windowed --noconfirm --clean `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all onnxruntime `
    --collect-all av `
    --collect-all _sounddevice_data
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

python scripts\download_model.py $Model dist\VoiceInput\models
if ($LASTEXITCODE -ne 0) { throw "whisper model download failed" }

Write-Host "Done: dist\VoiceInput\VoiceInput.exe"
