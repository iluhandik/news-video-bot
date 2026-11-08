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
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip, AudioFileClip

class Config:
    TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@glavni_novyny")
    CHANNEL_DISPLAY_NAME = os.getenv("CHANNEL_DISPLAY_NAME", "ГОЛОВНІ НОВИНИ UA")
    CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@glavni_novyny")
    VOICE_NAME = os.getenv("VOICE_NAME", "uk-UA-OstapNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+12%")
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 30
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

def clean_for_tts(text: str) -> str:
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

class ScriptGenerator:
    HOOKS = [
        "Увага: це рішення вже змінює ситуацію прямо зараз!",
        "Терміново: те, про що повідомили, шокувало всю країну!",
        "Шок: цю інформацію намагалися приховати до останнього!",
        "Ви не повірите: з'явилися перші офіційні подробиці!",
    ]
    CLIFFHANGERS = [
        "Але найскандальніший документ і деталі без цензури ми вже виклали в нашому Телеграм каналі. Посилання закріплено в шапці профілю!",
        "Хто насправді за цим стоїть та ексклюзивні кадри дивіться в нашому Телеграм каналі за посиланням у шапці!",
        "Повний список та секретні подробиці вже опубліковані в нашому каналі. Тисніть на посилання в шапці прямо зараз!",
    ]

    @classmethod
    def generate(cls, raw_post: str) -> Dict[str, str]:
        cleaned = clean_for_tts(raw_post)
        words = cleaned.split()
        headline = " ".join(words[:6]).upper() if len(words) >= 6 else "ТЕРМІНОВЕ ПОВІДОМЛЕННЯ"
        if not headline.endswith(("!", "?", ".")):
            headline += "!"

        hook = random.choice(cls.HOOKS)
        cliffhanger = random.choice(cls.CLIFFHANGERS)
        sentences = [s.strip() for s in re.split(r"[.!?]+", cleaned) if len(s.strip()) > 10]
        body = sentences[0] if sentences else "З'явилися екстрені деталі щодо останніх резонансних подій."
        if len(body) > 160:
            body = body[:157] + "..."

        full_voiceover = f"{hook} {body}. {cliffhanger}"
        return {
            "headline": headline,
            "hook": hook,
            "body": body,
            "cliffhanger": cliffhanger,
            "full_voiceover": clean_for_tts(full_voiceover)
        }

class TTSEngine:
    @classmethod
    def generate_voiceover(cls, text: str, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        safe_text = clean_for_tts(text)
        try:
            cmd = ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, "--text", safe_text, "--write-media", str(output_path)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        except Exception:
            pass

        if not output_path.exists() or output_path.stat().st_size < 100:
            duration = max(8.0, min(25.0, len(safe_text) / 14.0))
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
        self.font_path = str(font_p)
        self.font_title = ImageFont.truetype(self.font_path, 38)
        self.font_header = ImageFont.truetype(self.font_path, 32)
        self.font_sub = ImageFont.truetype(self.font_path, 22)
        self.font_body = ImageFont.truetype(self.font_path, 28)
        self.font_cta = ImageFont.truetype(self.font_path, 28)
        self.font_cta_small = ImageFont.truetype(self.font_path, 22)

    def _draw_telegram_card(self, headline: str, text_snippet: str) -> Image.Image:
        w, h = 980, 480
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w, h], radius=28, fill=(18, 25, 38, 240), outline=(55, 80, 115, 255), width=2)
        draw.ellipse([36, 32, 112, 108], fill=(42, 171, 238, 255))
        draw.polygon([(58, 72), (94, 54), (76, 90), (70, 76)], fill=(255, 255, 255, 255))
        draw.text((130, 38), Config.CHANNEL_DISPLAY_NAME, font=self.font_title, fill=(255, 255, 255, 255))
        n_len = int(draw.textlength(Config.CHANNEL_DISPLAY_NAME, font=self.font_title))
        draw.ellipse([130 + n_len + 10, 50, 130 + n_len + 34, 74], fill=(42, 171, 238, 255))
        draw.text((130 + n_len + 15, 52), "✓", font=self.font_sub, fill=(255, 255, 255, 255))
        draw.text((130, 80), f"{Config.CHANNEL_USERNAME} • щойно", font=self.font_sub, fill=(120, 140, 160, 255))
        draw.line([(36, 125), (w - 36, 125)], fill=(40, 55, 75, 220), width=1)
        clean_head = clean_for_tts(headline)
        draw.text((36, 145), clean_head[:44] + ("..." if len(clean_head) > 44 else ""), font=self.font_header, fill=(255, 220, 40, 255))
        words = clean_for_tts(text_snippet).split()
        draw.text((36, 210), " ".join(words[:8]), font=self.font_body, fill=(230, 235, 245, 255))
        draw.text((36, 255), " ".join(words[8:16]), font=self.font_body, fill=(230, 235, 245, 255))
        draw.text((36, h - 45), "148.5K переглядів", font=self.font_sub, fill=(120, 140, 165, 255))
        draw.text((w - 200, h - 45), "24.3K поширень", font=self.font_sub, fill=(120, 140, 165, 255))
        return img

    def _draw_cta(self) -> Image.Image:
        w, h = 980, 150
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w, h], radius=24, fill=(215, 25, 35, 250), outline=(255, 215, 60, 255), width=3)
        t1 = "ПОВНЕ ВІДЕО ТА ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ"
        t2 = "Посилання на канал закріплено в описі та коментарях"
        draw.text(((w - draw.textlength(t1, font=self.font_cta))/2, 34), t1, font=self.font_cta, fill=(255, 255, 255, 255))
        draw.text(((w - draw.textlength(t2, font=self.font_cta_small))/2, 88), t2, font=self.font_cta_small, fill=(255, 245, 180, 255))
        return img

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1000, 200
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font_size = 56
        font = ImageFont.truetype(self.font_path, font_size)
        up_text = clean_for_tts(text).upper()
        while draw.textlength(up_text, font=font) > (w - 60) and font_size > 30:
            font_size -= 4
            font = ImageFont.truetype(self.font_path, font_size)
        tw = draw.textlength(up_text, font=font)
        tx = max(20, (w - tw) // 2)
        ty = (h - font_size) // 2
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx*dx + dy*dy <= 25:
                    draw.text((tx+dx, ty+dy), up_text, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), up_text, font=font, fill=(255, 235, 20, 255))
        return img

    def render(self, script_data: Dict, audio_path: Path, sub_events: List[Dict], output_file: Path, user_image_path: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration
        card = self._draw_telegram_card(script_data["headline"], script_data["body"])
        cta = self._draw_cta()
        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        user_img = None
        if user_image_path and user_image_path.exists():
            try:
                raw_u = Image.open(user_image_path).convert("RGBA")
                user_img = raw_u.resize((Config.VIDEO_WIDTH, int(Config.VIDEO_WIDTH * raw_u.height / raw_u.width)))
            except Exception:
                user_img = None

        def make_frame(t):
            frame = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (10, 14, 22, 255))
            draw = ImageDraw.Draw(frame)

            if user_img:
                zoom = 1.0 + 0.04 * (t / max(1.0, duration))
                zw = int(Config.VIDEO_WIDTH * zoom)
                zh = int(user_img.height * zoom)
                resized_u = user_img.resize((zw, zh))
                ox = (zw - Config.VIDEO_WIDTH) // 2
                oy = max(0, (zh - 800) // 2)
                crop_u = resized_u.crop((ox, oy, ox + Config.VIDEO_WIDTH, oy + 800))
                frame.alpha_composite(crop_u, (0, 720))
                draw.rectangle([0, 720, Config.VIDEO_WIDTH, 1520], fill=(10, 14, 22, 120))
            else:
                for i in range(12):
                    px = int((i * 180 + t * 40) % Config.VIDEO_WIDTH)
                    py = int(750 + 200 * math.sin(t * 1.5 + i))
                    draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(42, 171, 238, 140))
                glow_y = int(980 + 120 * math.sin(t * 1.8))
                draw.ellipse([Config.VIDEO_WIDTH//2 - 420, glow_y - 250, Config.VIDEO_WIDTH//2 + 420, glow_y + 250], fill=(22, 45, 80, 100))

            frame.alpha_composite(card, ((Config.VIDEO_WIDTH - card.width)//2, 180))

            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    simg = sub_cache.get(e["text"])
                    if simg:
                        frame.alpha_composite(simg, ((Config.VIDEO_WIDTH - simg.width)//2, 1180))
                    break

            pulse = int(4 * math.sin(t * 5.0))
            frame.alpha_composite(cta, ((Config.VIDEO_WIDTH - cta.width)//2, Config.VIDEO_HEIGHT - cta.height - 150 + pulse))
            return np.array(frame.convert("RGB"))

        video_clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        video_clip.write_videofile(str(output_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
        audio_clip.close()
        video_clip.close()
        return output_file

def generate_video_from_post(text: str, image_path: Optional[Path] = None) -> Path:
    script_data = ScriptGenerator.generate(text)
    temp_audio = Config.TEMP_DIR / f"voice_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate_voiceover(script_data["full_voiceover"], temp_audio)
    sub_events = TTSEngine.get_subtitle_chunks(script_data["full_voiceover"], duration)
    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_bait_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    engine.render(script_data, audio_path, sub_events, out_file, image_path)
    if temp_audio.exists():
        temp_audio.unlink()
    return out_file

app = FastAPI(title="Telegram News Video Studio Pro")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram News Video Studio Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0A0E17; --card-bg: rgba(22, 28, 42, 0.9); --border: rgba(56, 75, 110, 0.4); --accent: #2AABEE; --gold: #FFD233; --green: #2ED573; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: radial-gradient(circle at top right, #131E33 0%, #0A0E17 100%); color: #fff; min-height: 100vh; padding: 30px 15px; }
        .container { max-width: 850px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 25px; }
        header h1 { font-size: 28px; font-weight: 800; }
        header p { color: #8E9BAE; font-size: 14px; margin-top: 6px; }
        .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 20px; padding: 25px; backdrop-filter: blur(16px); box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        textarea { width: 100%; height: 140px; background: rgba(10, 14, 23, 0.9); border: 1px solid var(--border); border-radius: 12px; padding: 14px; color: #fff; font-size: 14px; outline: none; margin-bottom: 15px; resize: vertical; }
        .file-upload { border: 2px dashed var(--border); border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 15px; cursor: pointer; color: #8E9BAE; font-size: 13px; }
        .file-upload:hover { border-color: var(--accent); color: #fff; }
        .btn { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 700; cursor: pointer; width: 100%; transition: 0.2s; }
        .btn:hover { transform: translateY(-2px); }
        .btn:disabled { opacity: 0.5; }
        #loader { display: none; text-align: center; margin-top: 15px; color: var(--gold); font-weight: 600; }
        .video-box { margin-top: 25px; border-radius: 16px; overflow: hidden; background: #000; display: none; border: 1px solid var(--border); }
        video { width: 100%; max-height: 500px; object-fit: contain; }
        .action-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 15px; }
        .btn-action { background: rgba(255,255,255,0.08); color: #fff; border: 1px solid var(--border); padding: 12px; border-radius: 10px; font-size: 14px; font-weight: 600; text-align: center; text-decoration: none; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .btn-action:hover { background: rgba(255,255,255,0.15); }
        .btn-green { background: rgba(46, 213, 115, 0.15); border-color: rgba(46, 213, 115, 0.4); color: #2ed573; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 Telegram News Video Studio Pro</h1>
            <p>Вставте пост новини — бот сам видалить смайлики, зробить озвучку та змонтує ролик</p>
        </header>
        <div class="card">
            <textarea id="newsText" placeholder="Просто скопіюйте і вставте сюди пост вашої новини з Telegram..."></textarea>
            
            <div class="file-upload" onclick="document.getElementById('imgFile').click()">
                📷 Додати фото з посту (необов'язково — якщо немає, бот створить кібер-фон сам)
                <input type="file" id="imgFile" accept="image/*" style="display:none;" onchange="updateFileName(this)">
                <div id="fileName" style="color:var(--accent); margin-top:5px; font-weight:600;"></div>
            </div>

            <button class="btn" id="genBtn" onclick="generateVideo()">🚀 Змонтувати відео зараз</button>
            <div id="loader">⏳ Триває монтаж та озвучка без смайликів... (зачекайте 30-60 сек)</div>

            <div class="video-box" id="vBox">
                <video id="vPlayer" controls></video>
                <div class="action-row">
                    <a id="downloadBtn" class="btn-action btn-green" download>⬇ Завантажити MP4 для TikTok</a>
                    <button class="btn-action" onclick="copyPostText()">📋 Скопіювати хештеги та текст</button>
                </div>
            </div>
        </div>
    </div>
    <script>
        let currentVideoUrl = '';
        function updateFileName(input) {
            if(input.files && input.files[0]) {
                document.getElementById('fileName').innerText = '✓ Обрано: ' + input.files[0].name;
            }
        }
        async function generateVideo() {
            const btn = document.getElementById('genBtn');
            const loader = document.getElementById('loader');
            const vBox = document.getElementById('vBox');
            const vPlayer = document.getElementById('vPlayer');
            const text = document.getElementById('newsText').value;
            const imgInput = document.getElementById('imgFile');

            btn.disabled = true;
            loader.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', text);
                if(imgInput.files[0]) {
                    fd.append('image', imgInput.files[0]);
                }
                const res = await fetch('/api/generate', { method: 'POST', body: fd });
                const data = await res.json();
                if(data.video_url) {
                    currentVideoUrl = data.video_url;
                    vPlayer.src = data.video_url;
                    document.getElementById('downloadBtn').href = data.video_url;
                    vBox.style.display = 'block';
                    vPlayer.play();
                }
            } catch(e) {
                alert('Помилка: ' + e);
            } finally {
                btn.disabled = false;
                loader.style.display = 'none';
            }
        }
        function copyPostText() {
            navigator.clipboard.writeText("🔥 Повне відео та деталі в шапці профілю! #новини #україна #терміново #рек");
            alert("Хештеги та заклик скопійовано! Вставляйте в опис TikTok/Reels.");
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_gen(text: Optional[str] = Form(None), image: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "УВАГА: Верховна Рада щойно ухвалила скандальний законопроєкт у першому читанні!"

    saved_img = None
    if image and image.filename:
        saved_img = Config.TEMP_DIR / f"img_{int(time.time())}_{image.filename}"
        with open(saved_img, "wb") as f:
            f.write(await image.read())

    out = generate_video_from_post(text, saved_img)

    if saved_img and saved_img.exists():
        try:
            saved_img.unlink()
        except Exception:
            pass

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
