FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi>=0.100.0 \
    "uvicorn[standard]>=0.23.0" \
    python-multipart>=0.0.6 \
    moviepy>=2.0.0 \
    Pillow>=9.5.0 \
    numpy>=1.24.0 \
    requests>=2.31.0 \
    edge-tts>=6.1.9 \
    aiohttp>=3.9.0

COPY . .

ENV PORT=8000
EXPOSE 8000

CMD uvicorn app:app --host 0.0.0.0 --port $PORT
