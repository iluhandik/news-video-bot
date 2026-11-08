import os
import math
import random
import re
import time
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip, AudioFileClip

class Config:
    TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@glavni_novyny")
    CHANNEL_DISPLAY_NAME = os.getenv("CHANNEL_DISPLAY_NAME", "ГОЛОВНІ НОВИНИ UA")
    CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@glavni_novyny")
    VOICE_NAME = os.getenv("VOICE_NAME", "uk-UA-OstapNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+10%")
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 30
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

class ScriptGenerator:
    HOOKS = [
        "УВАГА: Ця новина прямо зараз змінює все!",
        "ТЕРМІНОВО: Те, про що щойно повідомили, шокувало всю країну!",
        "ШОК: Цю інформацію намагалися приховати до останнього!",
        "ВИ НЕ ПОВІРИТЕ: Тільки що з'явилися перші офіційні подробиці!",
    ]
    CLIFFHANGERS = [
        "Але найскандальніший документ і повне відео без цензури ми вже виклали в нашому Telegram-каналі! Посилання закріплено в шапці профілю!",
        "Хто насправді за цим стоїть і ексклюзивні кадри з місця подій дивіться в Telegram за посиланням у шапці та першому коментарі!",
        "Повний список та секретні деталі, які видаляють звідусіль, вже опубліковані в нашому каналі! Тисніть на посилання в шапці!",
    ]

    @classmethod
    def generate(cls, raw_text: str) -> Dict[str, str]:
        text = re.sub(r"https?://\S+", "", raw_text)
        text = re.sub(r"t\.me/\S+", "", text)
        words = text.split()
        headline = " ".join(words[:6]).upper() if len(words) >= 6 else "ТЕРМІНОВЕ ПОВІДОМЛЕННЯ"
        if not headline.endswith(("!", "?", ".")):
            headline += "!"

        hook = random.choice(cls.HOOKS)
        cliffhanger = random.choice(cls.CLIFFHANGERS)
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 10]
        body = sentences[0] if sentences else "З'явилися екстрені деталі щодо останніх резонансних подій."
        if len(body) > 160:
            body = body[:157] + "..."

        full_voiceover = f"{hook} {body}. {cliffhanger}"
        return {"headline": headline, "hook": hook, "body": body, "cliffhanger": cliffhanger, "full_voiceover": full_voiceover}

class TTSEngine:
    @classmethod
    def generate_voiceover(cls, text: str, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cmd = ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, "--text", text, "--write-media", str(output_path)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        except Exception:
            pass

        if not output_path.exists() or output_path.stat().st_size < 100:
            duration = max(8.0, min(25.0, len(text) / 14.0))
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:beep_factor=4:duration={duration}", "-filter:a", "volume=0.3", str(output_path)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        duration = cls._get_duration(output_path)
        return output_path, duration

    @classmethod
    def _get_duration(cls, path: Path) -> float:
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(res.stdout.strip())
        except Exception:
            return 15.0

    @classmethod
    def get_subtitle_chunks(cls, text: str, duration: float):
        words = text.split()
        if not words:
            return []
        chunks = [" ".join(words[i:i+3]) for i in range(0, len(words), 3)]
        time_per_chunk = duration / len(chunks)
        return [{"text": c, "start": i*time_per_chunk, "end": (i+1)*time_per_chunk} for i, c in enumerate(chunks)]

class VideoEngine:
    def __init__(self):
        font_p = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.font_title = ImageFont.truetype(str(font_p), 38)
        self.font_header = ImageFont.truetype(str(font_p), 32)
        self.font_sub = ImageFont.truetype(str(font_p), 22)
        self.font_body = ImageFont.truetype(str(font_p), 28)
        self.font_cta = ImageFont.truetype(str(font_p), 28)
        self.font_cta_small = ImageFont.truetype(str(font_p), 22)
        self.font_path = str(font_p)

    def _draw_card(self, headline: str, body: str) -> Image.Image:
        w, h = 960, 500
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w, h], radius=26, fill=(23, 33, 43, 245), outline=(45, 65, 90, 255), width=2)
        draw.ellipse([36, 32, 112, 108], fill=(42, 171, 238, 255))
        draw.polygon([(58, 72), (94, 54), (76, 90), (70, 76)], fill=(255, 255, 255, 255))
        draw.text((130, 38), Config.CHANNEL_DISPLAY_NAME, font=self.font_title, fill=(255, 255, 255, 255))
        n_len = int(draw.textlength(Config.CHANNEL_DISPLAY_NAME, font=self.font_title))
        draw.ellipse([130 + n_len + 10, 50, 130 + n_len + 34, 74], fill=(42, 171, 238, 255))
        draw.text((130 + n_len + 15, 52), "✓", font=self.font_sub, fill=(255, 255, 255, 255))
        draw.text((130, 80), f"{Config.CHANNEL_USERNAME} • щойно", font=self.font_sub, fill=(120, 140, 160, 255))
        draw.line([(36, 125), (w - 36, 125)], fill=(40, 55, 75, 220), width=1)
        draw.text((36, 145), headline[:44] + ("..." if len(headline) > 44 else ""), font=self.font_header, fill=(255, 220, 40, 255))
        words = body.split()
        draw.text((36, 210), " ".join(words[:8]), font=self.font_body, fill=(230, 235, 245, 255))
        draw.text((36, 255), " ".join(words[8:16]), font=self.font_body, fill=(230, 235, 245, 255))
        draw.text((36, h - 45), "👁 148.5K", font=self.font_sub, fill=(120, 140, 165, 255))
        draw.text((w - 160, h - 45), "➔ 24.3K", font=self.font_sub, fill=(120, 140, 165, 255))
        return img

    def _draw_cta(self) -> Image.Image:
        w, h = 960, 150
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w, h], radius=24, fill=(210, 25, 35, 250), outline=(255, 215, 60, 255), width=3)
        t1 = "УВАГА: ПОВНЕ ВІДЕО ТА ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ"
        t2 = ">>> Посилання на канал закріплено в описі та коментарях <<<"
        draw.text(((w - draw.textlength(t1, font=self.font_cta))/2, 32), t1, font=self.font_cta, fill=(255, 255, 255, 255))
        draw.text(((w - draw.textlength(t2, font=self.font_cta_small))/2, 88), t2, font=self.font_cta_small, fill=(255, 245, 180, 255))
        return img

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1000, 200
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font_size = 52
        font = ImageFont.truetype(self.font_path, font_size)
        up_text = text.upper()
        while draw.textlength(up_text, font=font) > (w - 60) and font_size > 30:
            font_size -= 4
            font = ImageFont.truetype(self.font_path, font_size)
        tw = draw.textlength(up_text, font=font)
        tx = max(20, (w - tw) // 2)
        ty = (h - font_size) // 2
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                if dx*dx + dy*dy <= 16:
                    draw.text((tx+dx, ty+dy), up_text, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), up_text, font=font, fill=(255, 235, 20, 255))
        return img

    def render(self, script_data: Dict, audio_path: Path, sub_events: List[Dict], output_file: Path):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration
        card = self._draw_card(script_data["headline"], script_data["body"])
        cta = self._draw_cta()
        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            frame = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (8, 12, 18, 255))
            draw = ImageDraw.Draw(frame)
            for y in range(0, Config.VIDEO_HEIGHT, 90):
                draw.line([(0, y), (Config.VIDEO_WIDTH, y)], fill=(15, 22, 34, 255))
            for x in range(0, Config.VIDEO_WIDTH, 90):
                draw.line([(x, 0), (x, Config.VIDEO_HEIGHT)], fill=(15, 22, 34, 255))
            ly = int(950 + 100 * math.sin(t * 1.5))
            draw.ellipse([Config.VIDEO_WIDTH//2 - 400, ly - 300, Config.VIDEO_WIDTH//2 + 400, ly + 300], fill=(18, 35, 65, 80))
            frame.alpha_composite(card, ((Config.VIDEO_WIDTH - card.width)//2, 220))
            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    simg = sub_cache.get(e["text"])
                    if simg:
                        frame.alpha_composite(simg, ((Config.VIDEO_WIDTH - simg.width)//2, 1120))
                    break
            pulse = int(3 * math.sin(t * 5.0))
            frame.alpha_composite(cta, ((Config.VIDEO_WIDTH - cta.width)//2, Config.VIDEO_HEIGHT - cta.height - 180 + pulse))
            return np.array(frame.convert("RGB"))

        video_clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        video_clip.write_videofile(str(output_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
        audio_clip.close()
        video_clip.close()
        return output_file

def generate_video_from_text(text: str) -> Path:
    script_data = ScriptGenerator.generate(text)
    temp_audio = Config.TEMP_DIR / f"voice_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate_voiceover(script_data["full_voiceover"], temp_audio)
    sub_events = TTSEngine.get_subtitle_chunks(script_data["full_voiceover"], duration)
    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_bait_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    engine.render(script_data, audio_path, sub_events, out_file)
    if temp_audio.exists():
        temp_audio.unlink()
    return out_file

app = FastAPI(title="Telegram News Video Studio")

@app.get("/", response_class=HTMLResponse)
async def home():
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram News Video Studio</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{ --bg: #0A0E17; --card-bg: rgba(22, 28, 42, 0.85); --border: rgba(56, 75, 110, 0.4); --accent: #2AABEE; --accent-glow: rgba(42, 171, 238, 0.3); --gold: #FFD233; }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }}
        body {{ background: radial-gradient(circle at top right, #131E33 0%, #0A0E17 100%); color: #fff; min-height: 100vh; padding: 40px 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        header {{ text-align: center; margin-bottom: 30px; }}
        header h1 {{ font-size: 26px; font-weight: 800; }}
        .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 20px; padding: 30px; backdrop-filter: blur(16px); box-shadow: 0 10px 40px rgba(0,0,0,0.5); }}
        textarea {{ width: 100%; height: 130px; background: rgba(10, 14, 23, 0.9); border: 1px solid var(--border); border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 15px; }}
        .btn {{ background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 700; cursor: pointer; width: 100%; }}
        .btn:disabled {{ opacity: 0.5; }}
        #loader {{ display: none; text-align: center; margin-top: 15px; color: var(--gold); }}
        .video-box {{ margin-top: 25px; border-radius: 16px; overflow: hidden; background: #000; display: none; border: 1px solid var(--border); }}
        video {{ width: 100%; max-height: 520px; object-fit: contain; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 Telegram News Video Studio</h1>
            <p style="color:#8E9BAE; font-size:14px; margin-top:5px;">Хмарний монтаж вірусних відео для TikTok / Reels</p>
        </header>
        <div class="card">
            <textarea id="newsText" placeholder="Вставте текст новини сюди..."></textarea>
            <button class="btn" id="genBtn" onclick="generateVideo()">🚀 Змонтувати відео зараз</button>
            <div id="loader">⏳ Триває озвучка та відеомонтаж... (15-20 сек)</div>
            <div class="video-box" id="vBox">
                <video id="vPlayer" controls></video>
            </div>
        </div>
    </div>
    <script>
        async function generateVideo() {{
            const btn = document.getElementById('genBtn');
            const loader = document.getElementById('loader');
            const vBox = document.getElementById('vBox');
            const vPlayer = document.getElementById('vPlayer');
            const text = document.getElementById('newsText').value;

            btn.disabled = true;
            loader.style.display = 'block';

            try {{
                const fd = new FormData();
                fd.append('text', text);
                const res = await fetch('/api/generate', {{ method: 'POST', body: fd }});
                const data = await res.json();
                if(data.video_url) {{
                    vPlayer.src = data.video_url;
                    vBox.style.display = 'block';
                    vPlayer.play();
                }}
            }} catch(e) {{
                alert('Помилка: ' + e);
            }} finally {{
                btn.disabled = false;
                loader.style.display = 'none';
            }}
        }}
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_gen(text: Optional[str] = Form(None)):
    if not text or not text.strip():
        text = "УВАГА: Верховна Рада щойно ухвалила скандальний законопроєкт у першому читанні!"
    out = generate_video_from_text(text)
    return {"video_url": f"/videos/{out.name}"}

@app.get("/videos/{filename}")
async def get_video(filename: str):
    p = Config.OUTPUT_DIR / filename
    if p.exists():
        return FileResponse(p, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/status")
async def status():
    return {"status": "ok"}
