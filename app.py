import os
import math
import random
import re
import time
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoClip, AudioFileClip

class Config:
    TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@glavni_novyny")
    CHANNEL_DISPLAY_NAME = os.getenv("CHANNEL_DISPLAY_NAME", "ГОЛОВНІ НОВИНИ UA")
    CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@glavni_novyny")
    VOICE_NAME = os.getenv("VOICE_NAME", "uk-UA-OstapNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+14%")
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 30
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

def clean_text_for_tts(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"t\.me/\S+", "", text)
    text = re.sub(r"@[a-zA-Z0-9_]+", "", text)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub(" ", text)
    text = re.sub(r"[⚡🔥👉👇⚠️🚨✔✓➔➡•—–«»#*_=~`]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_news_content(raw_post: str) -> Dict[str, str]:
    clean = clean_text_for_tts(raw_post)
    lines = [l.strip() for l in clean.split("\n") if len(l.strip()) > 5]
    
    # Виділяємо головний заголовок
    if lines:
        headline = lines[0][:45].upper()
        content_body = " ".join(lines[1:]) if len(lines) > 1 else lines[0]
    else:
        headline = "ТЕРМІНОВА НОВИНА"
        content_body = clean

    # Якщо текст задовгий — беремо суть перших 2-3 речень
    sentences = [s.strip() for s in re.split(r"[.!?]+", content_body) if len(s.strip()) > 8]
    core_news = ". ".join(sentences[:3]) if sentences else content_body[:180]

    # Швидкий короткий заклик наприкінці
    cta_voice = "Повний список та всі подробиці вже в нашому Телеграм каналі. Посилання в шапці профілю!"
    full_voice = f"{headline}. {core_news}. {cta_voice}"

    return {
        "headline": headline,
        "body": core_news,
        "voiceover": clean_text_for_tts(full_voice)
    }

class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_p: Path):
        try:
            cmd = ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, "--text", text, "--write-media", str(out_p)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        except Exception:
            pass

        if not out_p.exists() or out_p.stat().st_size < 100:
            duration = max(8.0, min(24.0, len(text) / 14.0))
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:beep_factor=4:duration={duration}", "-filter:a", "volume=0.2", str(out_p)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        duration = cls._dur(out_p)
        return out_p, duration

    @classmethod
    def _dur(cls, p: Path) -> float:
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)]
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(r.stdout.strip())
        except Exception:
            return 16.0

    @classmethod
    def chunks(cls, text: str, dur: float):
        words = text.split()
        # По 2 слова для динамічного темпу
        chunks = [" ".join(words[i:i+2]) for i in range(0, len(words), 2)]
        t_chunk = dur / max(1, len(chunks))
        return [{"text": c, "start": i*t_chunk, "end": (i+1)*t_chunk} for i, c in enumerate(chunks)]

class VideoEngine:
    def __init__(self):
        font_p = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.font_path = str(font_p)
        self.font_tag = ImageFont.truetype(self.font_path, 26)
        self.font_head = ImageFont.truetype(self.font_path, 40)
        self.font_body = ImageFont.truetype(self.font_path, 32)
        self.font_cta = ImageFont.truetype(self.font_path, 28)

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1000, 220
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(self.font_path, 66)
        up = text.upper()
        tw = draw.textlength(up, font=font)
        tx = max(15, (w - tw) // 2)
        ty = (h - 66) // 2

        # Контрастний обвід 6px
        for dx in range(-6, 7):
            for dy in range(-6, 7):
                if dx*dx + dy*dy <= 36:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        # Яскравий зелений / жовтий колір
        draw.text((tx, ty), up, font=font, fill=(46, 213, 115, 255))
        return img

    def render(self, data: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, user_img_path: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # Підготовка фону
        if user_img_path and user_img_path.exists():
            bg_raw = Image.open(user_img_path).convert("RGB")
        else:
            # Преміальний темний фон без дефектів
            bg_raw = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (12, 16, 26))

        # Масштабуємо фон
        bw, bh = bg_raw.size
        tr = Config.VIDEO_WIDTH / Config.VIDEO_HEIGHT
        if bw / bh > tr:
            nw = int(bh * tr)
            bg_base = bg_raw.crop(((bw - nw) // 2, 0, (bw + nw) // 2, bh))
        else:
            nh = int(bw / tr)
            bg_base = bg_raw.crop((0, (bh - nh) // 2, bw, (bh + nh) // 2))
        bg_base = bg_base.resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))

        # Напівпрозоре затемнення, щоб текст читався на будь-якому фото
        dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, 175))
        bg_base.paste(dim, (0, 0), dim)

        # 1. Верхня плашка (зона безпечна від інтерфейсу TikTok)
        header_overlay = Image.new("RGBA", (Config.VIDEO_WIDTH, 480), (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(header_overlay)
        # Червоний бейдж
        h_draw.rounded_rectangle([40, 140, 280, 195], radius=10, fill=(235, 45, 55, 255))
        h_draw.text((60, 150), "НОВИНИ UA", font=self.font_tag, fill=(255, 255, 255, 255))
        # Заголовок
        h_draw.text((40, 220), data["headline"], font=self.font_head, fill=(255, 225, 30, 255))
        h_draw.line([(40, 310), (Config.VIDEO_WIDTH - 40, 310)], fill=(255, 255, 255, 120), width=2)

        # 2. Плашка каналу над безпечною зоною (Y=1450, не перекривається описом)
        cta_overlay = Image.new("RGBA", (Config.VIDEO_WIDTH, 140), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_overlay)
        c_draw.rounded_rectangle([50, 10, Config.VIDEO_WIDTH - 50, 110], radius=20, fill=(22, 30, 46, 240), outline=(42, 171, 238, 255), width=2)
        cta_t = "ПОВНА НОВИНА В ЗАКРІПЛЕНОМУ ПОСИЛАННІ"
        tw = c_draw.textlength(cta_t, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - tw)//2, 28), cta_t, font=self.font_cta, fill=(255, 255, 255, 255))
        sub_c = "Канал: " + Config.CHANNEL_USERNAME
        c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(sub_c, font=self.font_tag))//2, 68), sub_c, font=self.font_tag, fill=(42, 171, 238, 255))

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            # Плавний повільний рух
            zoom = 1.0 + 0.03 * (t / max(1.0, duration))
            zw, zh = int(Config.VIDEO_WIDTH * zoom), int(Config.VIDEO_HEIGHT * zoom)
            z_img = bg_base.resize((zw, zh))
            frame = z_img.crop(((zw - Config.VIDEO_WIDTH)//2, (zh - Config.VIDEO_HEIGHT)//2, (zw + Config.VIDEO_WIDTH)//2, (zh + Config.VIDEO_HEIGHT)//2)).convert("RGBA")

            # Накладаємо шари
            frame.alpha_composite(header_overlay, (0, 0))

            # Субтитри по центру екрана (Y = 880-920)
            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 900))
                    break

            # CTA у безпечній зоні
            frame.alpha_composite(cta_overlay, (0, 1380))
            return np.array(frame.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        clip.close()
        return out_file

app = FastAPI(title="Viral News Video Studio")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Reel Studio</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #07090E; --card: rgba(18, 24, 38, 0.95); --accent: #2ED573; --border: #243044; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 800px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid var(--border); border-radius: 18px; padding: 22px; }
        textarea { width: 100%; height: 140px; background: #0D121C; border: 1px solid var(--border); border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .img-drop { border: 2px dashed var(--border); border-radius: 12px; padding: 15px; text-align: center; cursor: pointer; color: #8E9BAE; font-size: 14px; margin-bottom: 14px; }
        .btn-go { background: linear-gradient(135deg, #2ED573, #1B9E51); color: #000; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; }
        .btn-go:disabled { opacity: 0.5; }
        #status { display: none; text-align: center; color: #FFD233; margin-top: 14px; font-weight: 700; font-size: 14px; }
        .res-box { margin-top: 20px; display: none; }
        video { width: 100%; max-height: 520px; border-radius: 14px; background: #000; }
        .btn-dl { display: block; text-align: center; background: #2AABEE; color: #fff; text-decoration: none; padding: 14px; border-radius: 10px; font-weight: 700; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>🎬 Генератор промо-відео TikTok / Reels</h1>
            <p style="color:#8E9BAE; font-size:13px; margin-top:4px;">Без дурних ШІ-картинок, з чітким текстом новини та врахуванням зон TikTok</p>
        </header>

        <div class="box">
            <textarea id="postTxt" placeholder="Вставте сюди текст новини з вашого Telegram-каналу..."></textarea>
            
            <div class="img-drop" onclick="document.getElementById('imgInp').click()">
                📷 Додати реальне фото/картинку з новини (за бажанням)
                <input type="file" id="imgInp" accept="image/*" style="display:none;" onchange="showF(this)">
                <div id="fName" style="color:var(--accent); font-weight:bold; margin-top:4px;"></div>
            </div>

            <button class="btn-go" id="goBtn" onclick="generate()">🚀 Змонтувати ролик</button>
            <div id="status">⏳ Очищення тексту від смайликів, дикторська озвучка та рендеринг...</div>

            <div class="res-box" id="resBox">
                <video id="vPlay" controls></video>
                <a id="dlLink" class="btn-dl" download>⬇ Завантажити готовий MP4 для публікації</a>
            </div>
        </div>
    </div>

    <script>
        function showF(i) {
            if(i.files && i.files[0]) document.getElementById('fName').innerText = '✓ Обрано: ' + i.files[0].name;
        }
        async function generate() {
            const btn = document.getElementById('goBtn');
            const st = document.getElementById('status');
            const box = document.getElementById('resBox');
            const vid = document.getElementById('vPlay');
            const txt = document.getElementById('postTxt').value;
            const file = document.getElementById('imgInp').files[0];

            btn.disabled = true;
            st.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', txt);
                if(file) fd.append('image', file);
                const res = await fetch('/api/generate', { method: 'POST', body: fd });
                const d = await res.json();
                if(d.video_url) {
                    vid.src = d.video_url;
                    document.getElementById('dlLink').href = d.video_url;
                    box.style.display = 'block';
                    vid.play();
                }
            } catch(e) {
                alert('Помилка: ' + e);
            } finally {
                btn.disabled = false;
                st.style.display = 'none';
            }
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_generate(text: Optional[str] = Form(None), image: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "УВАГА: Верховна Рада готує закон про платні дороги. Ставки затвердять до кінця 2027 року: від 2,30 євро за 100 км."

    parsed = parse_news_content(text)

    user_img = None
    if image and image.filename:
        user_img = Config.TEMP_DIR / f"u_{int(time.time())}_{image.filename}"
        with open(user_img, "wb") as f:
            f.write(await image.read())

    temp_audio = Config.TEMP_DIR / f"v_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio)
    sub_events = TTSEngine.chunks(parsed["voiceover"], duration)

    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"reel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    engine.render(parsed, audio_path, sub_events, out_file, user_img)

    for p in [temp_audio, user_img]:
        if p and p.exists():
            try: p.unlink()
            except Exception: pass

    return {"video_url": f"/videos/{out_file.name}"}

@app.get("/videos/{filename}")
async def get_vid(filename: str):
    p = Config.OUTPUT_DIR / filename
    if p.exists():
        return FileResponse(p, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/status")
async def status():
    return {"status": "ok"}
