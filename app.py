import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from config import Config
from main import process_single_news

app = FastAPI(title="Telegram News Video Studio")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram News Video Studio</title>
    <style>
        body { background: #0A0E17; color: #fff; font-family: sans-serif; text-align: center; padding: 40px 20px; }
        .card { max-width: 600px; margin: 0 auto; background: #161C2A; padding: 30px; border-radius: 20px; border: 1px solid #384B6E; }
        textarea { width: 100%; height: 120px; background: #0C1018; border: 1px solid #384B6E; border-radius: 10px; color: #fff; padding: 10px; margin-bottom: 15px; }
        button { background: #2AABEE; color: #fff; border: none; padding: 14px 28px; border-radius: 10px; font-weight: bold; cursor: pointer; font-size: 16px; width: 100%; }
        video { width: 100%; max-height: 450px; border-radius: 12px; margin-top: 20px; display: none; }
    </style>
</head>
<body>
    <div class="card">
        <h2>🎬 Telegram News Video Studio</h2>
        <p style="color:#8E9BAE; margin-bottom:20px;">Автономна хмарна генерація відео для TikTok / Reels</p>
        <textarea id="text" placeholder="Вставте текст новини сюди..."></textarea>
        <button id="btn" onclick="gen()">🚀 Змонтувати відео</button>
        <p id="status" style="margin-top:15px; display:none; color:#FFD233;">Триває монтаж, зачекайте 20 секунд...</p>
        <video id="player" controls></video>
    </div>
    <script>
        async function gen() {
            const text = document.getElementById('text').value;
            document.getElementById('status').style.display = 'block';
            document.getElementById('btn').disabled = true;
            const fd = new FormData();
            fd.append('text', text);
            const res = await fetch('/api/generate', { method: 'POST', body: fd });
            const data = await res.json();
            document.getElementById('status').style.display = 'none';
            document.getElementById('btn').disabled = false;
            if(data.video_url) {
                const p = document.getElementById('player');
                p.src = data.video_url;
                p.style.display = 'block';
                p.play();
            }
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_generate(text: Optional[str] = Form(None)):
    if not text or not text.strip():
        text = "УВАГА: Верховна Рада щойно ухвалила скандальний законопроєкт у першому читанні!"
    out = process_single_news(text, f"web_{int(datetime.now().timestamp())}")
    return {"video_url": f"/videos/{out.name}"}

@app.get("/videos/{filename}")
async def serve_video(filename: str):
    file_p = Config.OUTPUT_DIR / filename
    if file_p.exists():
        return FileResponse(file_p, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/status")
async def status():
    return {"status": "ok"}
