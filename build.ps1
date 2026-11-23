# Build the Windows distribution folder: dist\VoiceInput
# Usage:  .\build.ps1                                (whisper "small" + LLM "qwen3-4b")
#         .\build.ps1 -Model medium -Llm qwen3-8b
param(
    [string]$Model = "small",
    [string]$Llm = "qwen3-4b"
)
$ErrorActionPreference = "Stop"

python -m pip install --prefer-binary `
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu `
    -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

pyinstaller run.py --name VoiceInput --windowed --noconfirm --clean `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all onnxruntime `
    --collect-all av `
    --collect-all _sounddevice_data `
    --collect-all llama_cpp `
    --collect-data docx `
    --collect-data openpyxl
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

python scripts\download_model.py $Model dist\VoiceInput\models
if ($LASTEXITCODE -ne 0) { throw "whisper model download failed" }

python scripts\download_llm.py $Llm dist\VoiceInput\models
if ($LASTEXITCODE -ne 0) { throw "llm download failed" }

Write-Host "Done: dist\VoiceInput\VoiceInput.exe"
