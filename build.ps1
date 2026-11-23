# Build the Windows distribution folder: dist\VoiceInput
# Usage:  .\build.ps1                 (bundles the "small" model)
#         .\build.ps1 -Model medium
param([string]$Model = "small")
$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt pyinstaller

pyinstaller run.py --name VoiceInput --windowed --noconfirm --clean `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all onnxruntime `
    --collect-all av `
    --collect-all _sounddevice_data
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

python scripts\download_model.py $Model dist\VoiceInput\models
if ($LASTEXITCODE -ne 0) { throw "model download failed" }

Write-Host "Done: dist\VoiceInput\VoiceInput.exe"
