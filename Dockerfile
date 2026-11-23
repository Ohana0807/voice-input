# Voice Input のコマンドライン版（画面・マイクなし）を動かすためのイメージ。
# モデルはイメージに含めず、./models をマウントして使う。
FROM python:3.11-slim

# llama-cpp-python のビルド済みパッケージが無い場合に備えてコンパイラを入れる
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
        -r requirements.txt

COPY voice_input ./voice_input
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

ENTRYPOINT ["python", "-m", "voice_input.cli"]
