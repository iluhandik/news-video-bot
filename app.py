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
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
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
    return re.sub(r"\s+", " ", text).strip()

def parse_post(raw_post: str) -> Dict[str, str]:
    cleaned = clean_text_for_tts(raw_post)
    lines = [l.strip() for l in raw_post.split("\n") if len(l.strip()) > 3]
    
    # Визначаємо головний заголовок новини
    if lines:
        first_line = clean_text_for_tts(lines[0])
        headline = first_line[:40].upper()
    else:
        headline = "ВАЖЛИВА НОВИНА"

    # Тіло новини
    sentences = [s.strip() for s in re.split(r"[.!?]+", cleaned) if len(s.strip()) > 8]
    core_text = ". ".join(sentences[:3]) if sentences else cleaned[:160]

    # Природний заклик наприкінці
    cta = "Повні деталі та першоджерело дивіться в нашому Телеграм каналі за посиланням у шапці профілю."
    voice = f"{headline}. {core_text}. {cta}"

    return {
        "headline": headline,
        "full_text": raw_post,
        "voiceover": clean_text_for_tts(voice)
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
            dur = max(8.0, min(24.0, len(text) / 14.0))
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:beep_factor=4:duration={dur}", "-filter:a", "volume=0.2", str(out_p)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return out_p, cls._dur(out_p)

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
        chunks = [" ".join(words[i:i+2]) for i in range(0, len(words), 2)]
        t_chunk = dur / max(1, len(chunks))
        return [{"text": c, "start": i*t_chunk, "end": (i+1)*t_chunk} for i, c in enumerate(chunks)]

class VideoEngine:
    def __init__(self):
        font_p = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.font_path = str(font_p)
        self.font_hook = ImageFont.truetype(self.font_path, 46)
        self.font_card_head = ImageFont.truetype(self.font_path, 30)
        self.font_card_body = ImageFont.truetype(self.font_path, 26)
        self.font_card_sub = ImageFont.truetype(self.font_path, 22)
        self.font_cta = ImageFont.truetype(self.font_path, 26)

    def _render_telegram_post_card(self, raw_post: str) -> Image.Image:
        """Створює білий/світлий фірмовий скриншот посту в стилі новинних каналів TikTok"""
        w, h = 980, 520
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Біла підкладка як у Telegram
        draw.rounded_rectangle([0, 0, w, h], radius=24, fill=(255, 255, 255, 245), outline=(220, 225, 235, 255), width=2)

        # Синій аватар каналу
        draw.ellipse([36, 32, 106, 102], fill=(42, 171, 238, 255))
        draw.polygon([(56, 70), (90, 52), (72, 86), (66, 74)], fill=(255, 255, 255, 255))

        # Назва каналу + галочка
        draw.text((120, 36), Config.CHANNEL_DISPLAY_NAME, font=self.font_card_head, fill=(20, 30, 45, 255))
        n_len = int(draw.textlength(Config.CHANNEL_DISPLAY_NAME, font=self.font_card_head))
        draw.ellipse([120 + n_len + 8, 44, 120 + n_len + 30, 66], fill=(42, 171, 238, 255))
        draw.text((120 + n_len + 12, 44), "✓", font=self.font_card_sub, fill=(255, 255, 255, 255))
        draw.text((120, 74), f"{Config.CHANNEL_USERNAME} • новини", font=self.font_card_sub, fill=(120, 135, 150, 255))

        draw.line([(36, 118), (w - 36, 118)], fill=(230, 235, 245, 255), width=2)

        # Текст новини (4 рядки)
        words = clean_text_for_tts(raw_post).split()
        cur_y = 135
        for i in range(0, min(len(words), 36), 9):
            line_txt = " ".join(words[i:i+9])
            draw.text((36, cur_y), line_txt, font=self.font_card_body, fill=(30, 40, 55, 255))
            cur_y += 38

        # Перегляди Telegram
        draw.text((36, h - 42), "148K переглядів", font=self.font_card_sub, fill=(130, 145, 160, 255))
        draw.text((w - 180, h - 42), "Поділитися ➔", font=self.font_card_sub, fill=(42, 171, 238, 255))
        return img

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1000, 220
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(self.font_path, 64)
        up = text.upper()
        tw = draw.textlength(up, font=font)
        tx = max(15, (w - tw) // 2)
        ty = (h - 64) // 2

        # Чорний контур
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx*dx + dy*dy <= 25:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        # Жовтий акцент на буквах
        draw.text((tx, ty), up, font=font, fill=(255, 225, 20, 255))
        return img

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, bg_video_or_img: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # Фонове зображення (темний фон новинного каналу)
        if bg_video_or_img and bg_video_or_img.exists():
            bg_base = Image.open(bg_video_or_img).convert("RGB")
        else:
            bg_base = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (16, 22, 34))

        bw, bh = bg_base.size
        tr = Config.VIDEO_WIDTH / Config.VIDEO_HEIGHT
        if bw / bh > tr:
            nw = int(bh * tr)
            bg_base = bg_base.crop(((bw - nw) // 2, 0, (bw + nw) // 2, bh))
        else:
            nh = int(bw / tr)
            bg_base = bg_base.crop((0, (bh - nh) // 2, bw, (bh + nh) // 2))
        bg_base = bg_base.resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))

        # Легке затемнення фону
        dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (0, 0, 0, 150))
        bg_base.paste(dim, (0, 0), dim)

        # 1. Верхній яскравий блок «ТЕРМІНОВО» (Hook Header у стилі BBC/Труха)
        header_img = Image.new("RGBA", (Config.VIDEO_WIDTH, 360), (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(header_img)
        # Червона плашка
        h_draw.rounded_rectangle([40, 120, 320, 180], radius=10, fill=(235, 30, 45, 255))
        h_draw.text((60, 130), "ТЕРМІНОВО", font=self.font_card_head, fill=(255, 255, 255, 255))
        # Великий заголовок
        h_draw.text((40, 210), parsed["headline"], font=self.font_hook, fill=(255, 255, 255, 255))

        # 2. Картка посту Telegram (центр)
        card_img = self._render_telegram_post_card(parsed["full_text"])

        # 3. Нижня плашка заклику (у безпечній зоні Y=1450)
        cta_img = Image.new("RGBA", (Config.VIDEO_WIDTH, 140), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_img)
        c_draw.rounded_rectangle([50, 10, Config.VIDEO_WIDTH - 50, 110], radius=20, fill=(20, 26, 40, 240), outline=(255, 215, 0, 255), width=2)
        c_text = "ПОВНЕ ВІДЕО ТА ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
        tw = c_draw.textlength(c_text, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - tw) // 2, 42), c_text, font=self.font_cta, fill=(255, 220, 40, 255))

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            zoom = 1.0 + 0.03 * (t / max(1.0, duration))
            zw, zh = int(Config.VIDEO_WIDTH * zoom), int(Config.VIDEO_HEIGHT * zoom)
            z_img = bg_base.resize((zw, zh))
            frame = z_img.crop(((zw - Config.VIDEO_WIDTH)//2, (zh - Config.VIDEO_HEIGHT)//2, (zw + Config.VIDEO_WIDTH)//2, (zh + Config.VIDEO_HEIGHT)//2)).convert("RGBA")

            # Верхній заголовок
            frame.alpha_composite(header_img, (0, 0))

            # Скриншот Telegram посту
            frame.alpha_composite(card_img, ((Config.VIDEO_WIDTH - card_img.width)//2, 480))

            # Динамічні субтитри під скриншотом
            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 1080))
                    break

            # Заклик до дії в безпечній зоні
            frame.alpha_composite(cta_img, (0, 1420))
            return np.array(frame.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        clip.close()
        return out_file

app = FastAPI(title="Telegram News Reel Studio")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram News Studio</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0A0E17; --card: #141A26; --accent: #2AABEE; --gold: #FFD233; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 800px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid #232D42; border-radius: 18px; padding: 22px; }
        textarea { width: 100%; height: 140px; background: #0B0E14; border: 1px solid #232D42; border-radius: 12px; padding: 14px; color: #fff; font-size: 14px; outline: none; margin-bottom: 12px; resize: vertical; }
        .drop { border: 2px dashed #232D42; border-radius: 12px; padding: 14px; text-align: center; cursor: pointer; color: #8E9BAE; font-size: 13px; margin-bottom: 14px; }
        .btn-make { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; }
        .btn-make:disabled { opacity: 0.5; }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 14px; font-weight: 700; font-size: 14px; }
        .res { margin-top: 20px; display: none; }
        video { width: 100%; max-height: 520px; border-radius: 14px; background: #000; }
        .dl { display: block; text-align: center; background: #2ED573; color: #000; text-decoration: none; padding: 14px; border-radius: 10px; font-weight: 800; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>🎬 Новинна студія TikTok / Reels</h1>
            <p style="color:#8E9BAE; font-size:13px; margin-top:4px;">Формат «Скриншот посту Telegram + живий відеоряд» як у топових каналах</p>
        </header>

        <div class="box">
            <textarea id="inpTxt" placeholder="Вставте сюди пост новини з вашого Telegram-каналу..."></textarea>
            
            <div class="drop" onclick="document.getElementById('bgFile').click()">
                📷 Додати реальне тематичне фото/відео (дорога, Рада, машини тощо)
                <input type="file" id="bgFile" accept="image/*,video/*" style="display:none;" onchange="showName(this)">
                <div id="fTxt" style="color:var(--accent); font-weight:bold; margin-top:4px;"></div>
            </div>

            <button class="btn-make" id="btn" onclick="gen()">🚀 Змонтувати ролик</button>
            <div id="st">⏳ Створення плашки Telegram, генерація озвучки та збірка відео...</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>
                <a id="dlBtn" class="dl" download>⬇ Завантажити готовий MP4</a>
            </div>
        </div>
    </div>

    <script>
        function showName(i) {
            if(i.files && i.files[0]) document.getElementById('fTxt').innerText = '✓ Обрано: ' + i.files[0].name;
        }
        async function gen() {
            const btn = document.getElementById('btn');
            const st = document.getElementById('st');
            const box = document.getElementById('resBox');
            const vid = document.getElementById('vPlay');
            const txt = document.getElementById('inpTxt').value;
            const f = document.getElementById('bgFile').files[0];

            btn.disabled = true;
            st.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', txt);
                if(f) fd.append('media', f);
                const res = await fetch('/api/generate', { method: 'POST', body: fd });
                const d = await res.json();
                if(d.video_url) {
                    vid.src = d.video_url;
                    document.getElementById('dlBtn').href = d.video_url;
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
async def api_generate(text: Optional[str] = Form(None), media: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "УВАГА: В Україні готують закон про платні дороги. Ставки затвердять до кінця 2027 року: від 2,30 євро за 100 км."

    parsed = parse_post(text)

    media_p = None
    if media and media.filename:
        media_p = Config.TEMP_DIR / f"m_{int(time.time())}_{media.filename}"
        with open(media_p, "wb") as f:
            f.write(await media.read())

    temp_audio = Config.TEMP_DIR / f"v_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio)
    sub_events = TTSEngine.chunks(parsed["voiceover"], duration)

    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"tiktok_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    engine.render(parsed, audio_path, sub_events, out_file, media_p)

    for p in [temp_audio, media_p]:
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
