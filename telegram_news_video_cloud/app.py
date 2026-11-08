import os
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from config import Config
from main import process_single_news
from telegram_listener import TelegramListener

app = FastAPI(title="Telegram News Video Studio")

# Фоновий моніторинг каналу в пам'яті
IS_MONITORING = True
LAST_CHECK = "Ще не перевірялося"

async def background_channel_poller():
    global LAST_CHECK
    while True:
        if IS_MONITORING and Config.TELEGRAM_CHANNEL_ID and Config.TELEGRAM_CHANNEL_ID != "@your_news_channel":
            try:
                LAST_CHECK = datetime.now().strftime("%H:%M:%S")
                listener = TelegramListener()
                new_posts = listener.fetch_new_posts()
                if new_posts:
                    for post in new_posts:
                        process_single_news(post["text"], post["id"])
                        listener.mark_as_processed(post["id"])
            except Exception as e:
                print(f"[Poller Error] {e}")
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_channel_poller())

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_content = f'''<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram News Video Studio</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0A0E17;
            --card-bg: rgba(22, 28, 42, 0.75);
            --border: rgba(56, 75, 110, 0.4);
            --accent: #2AABEE;
            --accent-glow: rgba(42, 171, 238, 0.25);
            --gold: #FFD233;
            --red: #FF3B30;
            --text-main: #FFFFFF;
            --text-muted: #8E9BAE;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }}
        body {{
            background: radial-gradient(circle at top right, #131E33 0%, #0A0E17 100%);
            color: var(--text-main);
            min-height: 100vh;
            padding: 30px 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            flex-wrap: wrap;
            gap: 15px;
        }}
        .logo {{ display: flex; align-items: center; gap: 12px; }}
        .logo-icon {{
            width: 44px; height: 44px;
            background: linear-gradient(135deg, #2AABEE, #0088CC);
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 24px;
            box-shadow: 0 0 20px var(--accent-glow);
        }}
        .logo-text h1 {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
        .logo-text p {{ font-size: 13px; color: var(--text-muted); }}
        .status-badge {{
            display: flex; align-items: center; gap: 8px;
            background: rgba(46, 213, 115, 0.1);
            color: #2ed573;
            padding: 8px 16px;
            border-radius: 30px;
            font-size: 13px;
            font-weight: 600;
            border: 1px solid rgba(46, 213, 115, 0.3);
        }}
        .status-dot {{ width: 8px; height: 8px; background: #2ed573; border-radius: 50%; box-shadow: 0 0 10px #2ed573; }}
        
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
        @media (max-width: 850px) {{ .grid {{ grid-template-columns: 1fr; }} }}

        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 24px;
            backdrop-filter: blur(16px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        .card-title {{
            font-size: 18px; font-weight: 700; margin-bottom: 16px;
            display: flex; align-items: center; justify-content: space-between;
        }}
        textarea {{
            width: 100%; height: 130px;
            background: rgba(12, 16, 24, 0.8);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px;
            color: #fff;
            font-size: 14px;
            resize: vertical;
            outline: none;
            transition: 0.2s;
        }}
        textarea:focus {{ border-color: var(--accent); box-shadow: 0 0 15px var(--accent-glow); }}
        .btn {{
            background: linear-gradient(135deg, #2AABEE, #0077B5);
            color: #fff;
            border: none;
            padding: 14px 24px;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            width: 100%;
            margin-top: 14px;
            transition: 0.2s;
            display: flex; align-items: center; justify-content: center; gap: 8px;
        }}
        .btn:hover {{ transform: translateY(-2px); box-shadow: 0 8px 25px var(--accent-glow); }}
        .btn-secondary {{
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
            margin-top: 8px;
        }}
        .btn-secondary:hover {{ background: rgba(255, 255, 255, 0.15); box-shadow: none; }}
        
        .video-box {{
            width: 100%;
            border-radius: 16px;
            overflow: hidden;
            background: #000;
            aspect-ratio: 9/16;
            max-height: 480px;
            display: flex; align-items: center; justify-content: center;
            border: 1px solid var(--border);
        }}
        video {{ width: 100%; height: 100%; object-fit: contain; }}
        
        .stat-row {{
            display: flex; justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            font-size: 14px;
        }}
        .stat-label {{ color: var(--text-muted); }}
        .stat-value {{ font-weight: 600; color: var(--gold); }}

        .video-list {{ margin-top: 15px; display: flex; flex-direction: column; gap: 10px; max-height: 250px; overflow-y: auto; }}
        .video-item {{
            display: flex; justify-content: space-between; align-items: center;
            background: rgba(255,255,255,0.04);
            padding: 10px 14px;
            border-radius: 10px;
            font-size: 13px;
        }}
        .video-item a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
        .video-item a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <div class="logo-icon">🎬</div>
                <div class="logo-text">
                    <h1>Telegram News Video Studio</h1>
                    <p>Автономний хмарний генератор вірусних відео для TikTok, Reels та Shorts</p>
                </div>
            </div>
            <div class="status-badge">
                <div class="status-dot"></div>
                Автономна робота 24/7 (Хмара)
            </div>
        </header>

        <div class="grid">
            <!-- Ліва колонка: Генератор та Стан -->
            <div style="display: flex; flex-direction: column; gap: 24px;">
                <div class="card">
                    <div class="card-title">
                        <span>⚡ Швидкий монтаж відео</span>
                    </div>
                    <form id="genForm">
                        <textarea id="newsText" placeholder="Вставте текст новини сюди (або залиште порожнім, щоб змонтувати демонстраційний ролик)..."></textarea>
                        <button type="submit" class="btn" id="genBtn">🚀 Змонтувати відео зараз</button>
                    </form>
                    <div id="loader" style="display:none; text-align:center; margin-top:15px; color:var(--gold); font-size:14px;">
                        ⏳ Триває генерація сценарію, озвучка та монтаж... (15-25 сек)
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        <span>📊 Стан каналу та робота бота</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Цільовий Telegram-канал:</span>
                        <span class="stat-value">{Config.TELEGRAM_CHANNEL_ID}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Назва на плашці:</span>
                        <span class="stat-value">{Config.CHANNEL_DISPLAY_NAME}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Голос диктора:</span>
                        <span class="stat-value">{Config.VOICE_NAME}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Фоновий моніторинг:</span>
                        <span class="stat-value" style="color:#2ed573;">Активний (перевірка щохвилини)</span>
                    </div>
                </div>
            </div>

            <!-- Права колонка: Відео плеєр та останні ролики -->
            <div style="display: flex; flex-direction: column; gap: 24px;">
                <div class="card">
                    <div class="card-title">
                        <span>📱 Попередній перегляд (9:16)</span>
                    </div>
                    <div class="video-box" id="playerContainer">
                        <p style="color:var(--text-muted); font-size:14px;" id="noVideoMsg">Змонтуйте перше відео, щоб побачити результат</p>
                        <video id="videoPlayer" controls style="display:none;"></video>
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">
                        <span>📁 Галерея готових відео (.mp4)</span>
                    </div>
                    <div class="video-list" id="videoList">
                        <!-- Динамічно завантажується -->
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const genForm = document.getElementById('genForm');
        const genBtn = document.getElementById('genBtn');
        const loader = document.getElementById('loader');
        const videoPlayer = document.getElementById('videoPlayer');
        const noVideoMsg = document.getElementById('noVideoMsg');
        const videoList = document.getElementById('videoList');

        async function loadVideos() {{
            try {{
                const res = await fetch('/api/videos');
                const files = await res.json();
                if (files.length > 0) {{
                    videoList.innerHTML = files.map(f => `
                        <div class="video-item">
                            <span>📹 ${{f}}</span>
                            <div>
                                <a href="/videos/${{f}}" target="_blank" style="margin-right:10px;">▶ Дивитися</a>
                                <a href="/videos/${{f}}" download>⬇ Завантажити</a>
                            </div>
                        </div>
                    `).join('');

                    // Показуємо найсвіжіше відео
                    if (videoPlayer.style.display === 'none') {{
                        videoPlayer.src = '/videos/' + files[0];
                        videoPlayer.style.display = 'block';
                        noVideoMsg.style.display = 'none';
                    }}
                }} else {{
                    videoList.innerHTML = '<p style="color:var(--text-muted); font-size:13px;">Відео ще не створено.</p>';
                }}
            }} catch(e) {{
                console.error(e);
            }}
        }}

        genForm.addEventListener('submit', async (e) => {{
            e.preventDefault();
            const text = document.getElementById('newsText').value;
            genBtn.disabled = true;
            loader.style.display = 'block';

            try {{
                const formData = new FormData();
                formData.append('text', text);
                const res = await fetch('/api/generate', {{ method: 'POST', body: formData }});
                const data = await res.json();
                if (data.video_url) {{
                    videoPlayer.src = data.video_url;
                    videoPlayer.style.display = 'block';
                    noVideoMsg.style.display = 'none';
                    videoPlayer.play();
                    loadVideos();
                }}
            }} catch (err) {{
                alert('Помилка генерації: ' + err);
            }} finally {{
                genBtn.disabled = false;
                loader.style.display = 'none';
            }}
        }});

        loadVideos();
    </script>
</body>
</html>'''
    return html_content

@app.post("/api/generate")
async def api_generate(text: Optional[str] = Form(None)):
    if not text or not text.strip():
        text = "УВАГА: Верховна Рада щойно ухвалила скандальний законопроєкт! Зміни торкнуться кожного громадянина вже з 1 числа."

    output_path = process_single_news(text, f"web_{int(datetime.now().timestamp())}")
    return {"status": "ok", "video_url": f"/videos/{output_path.name}"}

@app.get("/api/videos")
async def api_get_videos():
    if not Config.OUTPUT_DIR.exists():
        return []
    videos = [f.name for f in sorted(Config.OUTPUT_DIR.glob("*.mp4"), key=os.path.getmtime, reverse=True)]
    return videos

@app.get("/videos/{filename}")
async def serve_video(filename: str):
    file_p = Config.OUTPUT_DIR / filename
    if file_p.exists():
        return FileResponse(file_p, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/status")
async def api_status():
    return {
        "status": "healthy",
        "channel": Config.TELEGRAM_CHANNEL_ID,
        "last_check": LAST_CHECK,
        "monitoring": IS_MONITORING
    }
