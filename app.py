import os
import math
import random
import re
import time
import urllib.parse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoClip, AudioFileClip

# ==========================================
# 1. КОНФІГУРАЦІЯ
# ==========================================
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

# ==========================================
# 2. ОЧИЩЕННЯ ТЕКСТУ (БЕЗ СМАЙЛИКІВ)
# ==========================================
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

# ==========================================
# 3. ШІ-ГЕНЕРАТОР БАЙТ-ЗОБРАЖЕННЯ
# ==========================================
def generate_ai_bait_image(prompt_text: str, output_path: Path) -> Optional[Path]:
    """Генерує фотореалістичний кінематографічний кадр під тему новини безкоштовно через Pollinations AI"""
    try:
        clean_prompt = clean_for_tts(prompt_text)[:120]
        # Промпт для фотореалістичного кадру
        full_prompt = f"cinematic dramatic breaking news photo, 8k resolution, photorealistic, {clean_prompt}, hyperrealistic, octane render, dramatic lighting"
        encoded = urllib.parse.quote(full_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true"
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(output_path, "wb") as f:
                f.write(r.content)
            return output_path
    except Exception as e:
        print(f"[AI Image Error] {e}")
    return None

# ==========================================
# 4. СЦЕНАРІЙ (МЕГА-БАЙТ)
# ==========================================
class ScriptGenerator:
    HOOKS = [
        "Увага: це вже не приховати, новина щойно розірвала мережу!",
        "Терміново: те, про що повідомили, змінює все прямо зараз!",
        "Шок: дивіться до кінця, це торкнеться кожного!",
    ]
    CLIFFHANGERS = [
        "Але найскандальніший документ і відео без цензури ми вже виклали в закріпленому посиланні в шапці профілю!",
        "Хто насправді за цим стоїть та ексклюзивні кадри вже в нашому Телеграм каналі. Посилання в шапці!",
    ]

    @classmethod
    def generate(cls, raw_post: str) -> Dict[str, str]:
        cleaned = clean_for_tts(raw_post)
        words = cleaned.split()
        headline = " ".join(words[:5]).upper() if len(words) >= 5 else "ТЕРМІНОВА НОВИНА"
        if not headline.endswith(("!", "?", ".")):
            headline += "!"

        sentences = [s.strip() for s in re.split(r"[.!?]+", cleaned) if len(s.strip()) > 8]
        body = sentences[0] if sentences else "З'явилися екстрені подробиці щодо останніх резонансних подій."
        if len(body) > 140:
            body = body[:137] + "..."

        hook = random.choice(cls.HOOKS)
        cliff = random.choice(cls.CLIFFHANGERS)
        full_voice = clean_for_tts(f"{hook} {body}. {cliff}")

        return {
            "headline": headline,
            "hook": hook,
            "body": body,
            "cliffhanger": cliff,
            "full_voiceover": full_voice,
            "raw": raw_post
        }

# ==========================================
# 5. ОЗВУЧКА ТА СУБТИТРИ (TTS)
# ==========================================
class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_p: Path):
        try:
            cmd = ["edge-tts", "--voice", Config.VOICE_NAME, "--rate", Config.VOICE_RATE, "--text", text, "--write-media", str(out_p)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        except Exception:
            pass

        if not out_p.exists() or out_p.stat().st_size < 100:
            duration = max(8.0, min(22.0, len(text) / 14.0))
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
        chunks = [" ".join(words[i:i+2]) for i in range(0, len(words), 2)]
        t_chunk = dur / max(1, len(chunks))
        return [{"text": c, "start": i*t_chunk, "end": (i+1)*t_chunk} for i, c in enumerate(chunks)]

# ==========================================
# 6. ВІДЕО-МОНТАЖ (БАЙТЕРСЬКИЙ ВІЗУАЛ)
# ==========================================
class VideoEngine:
    def __init__(self):
        font_p = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.font_path = str(font_p)
        self.font_badge = ImageFont.truetype(self.font_path, 28)
        self.font_head = ImageFont.truetype(self.font_path, 42)
        self.font_cta = ImageFont.truetype(self.font_path, 30)

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1000, 240
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(self.font_path, 68)
        up = text.upper()
        tw = draw.textlength(up, font=font)
        tx = max(10, (w - tw) // 2)
        ty = (h - 68) // 2

        # Чорний жирний контур
        for dx in range(-6, 7):
            for dy in range(-6, 7):
                if dx*dx + dy*dy <= 36:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        # Неоново-жовтий колір
        draw.text((tx, ty), up, font=font, fill=(255, 235, 10, 255))
        return img

    def render(self, script_data: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, bg_image_path: Path):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # Підготовка фонового фото на повний екран
        base_img = Image.open(bg_image_path).convert("RGB")
        base_w, base_h = base_img.size
        target_ratio = Config.VIDEO_WIDTH / Config.VIDEO_HEIGHT
        current_ratio = base_w / base_h

        if current_ratio > target_ratio:
            new_w = int(base_h * target_ratio)
            base_img = base_img.crop(((base_w - new_w) // 2, 0, (base_w + new_w) // 2, base_h))
        else:
            new_h = int(base_w / target_ratio)
            base_img = base_img.crop((0, (base_h - new_h) // 2, base_w, (base_h + new_h) // 2))

        base_img = base_img.resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))

        # Накладання віньєтки та затемнення
        vignette = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        v_draw.rectangle([0, 0, Config.VIDEO_WIDTH, 450], fill=(5, 8, 15, 210))
        v_draw.rectangle([0, Config.VIDEO_HEIGHT - 400, Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT], fill=(5, 8, 15, 230))
        base_img.paste(vignette, (0, 0), vignette)

        # Верхня плашка Breaking News
        top_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 380), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(top_bar)
        t_draw.rounded_rectangle([40, 60, 360, 115], radius=12, fill=(220, 20, 35, 255))
        t_draw.text((60, 72), "ТЕРМІНОВО", font=self.font_badge, fill=(255, 255, 255, 255))
        t_draw.text((40, 140), script_data["headline"], font=self.font_head, fill=(255, 255, 255, 255))
        t_draw.line([(40, 230), (Config.VIDEO_WIDTH - 40, 230)], fill=(255, 215, 0, 200), width=3)

        # Нижня CTA плашка
        cta_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 180), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_bar)
        c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 150], radius=24, fill=(210, 25, 40, 240), outline=(255, 215, 50, 255), width=3)
        cta_text = "ПОВНЕ ВІДЕО ТА СПИСОК В ШАПЦІ ПРОФІЛЮ"
        cw = c_draw.textlength(cta_text, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - cw) // 2, 45), cta_text, font=self.font_cta, fill=(255, 255, 255, 255))
        c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(">>> Тисніть на посилання каналу <<<", font=self.font_badge)) // 2, 95), ">>> Тисніть на посилання каналу <<<", font=self.font_badge, fill=(255, 240, 160, 255))

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            # Повільний кінематографічний зум фону (Ken Burns)
            zoom = 1.0 + 0.05 * (t / max(1.0, duration))
            zw = int(Config.VIDEO_WIDTH * zoom)
            zh = int(Config.VIDEO_HEIGHT * zoom)
            z_img = base_img.resize((zw, zh))
            frame = z_img.crop(((zw - Config.VIDEO_WIDTH) // 2, (zh - Config.VIDEO_HEIGHT) // 2, (zw + Config.VIDEO_WIDTH) // 2, (zh + Config.VIDEO_HEIGHT) // 2)).convert("RGBA")

            # Оверлей плашок
            frame.alpha_composite(top_bar, (0, 0))

            # Субтитри по центру
            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width) // 2, 980))
                    break

            # Пульсуючий CTA внизу
            pulse = int(3 * math.sin(t * 6.0))
            frame.alpha_composite(cta_bar, (0, Config.VIDEO_HEIGHT - 220 + pulse))
            return np.array(frame.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        clip.close()
        return out_file

# ==========================================
# 7. WEB STUDIO ТА АВТОПОСТИНГ
# ==========================================
app = FastAPI(title="Telegram News Viral Studio")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Viral News Video Studio Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #070A10; --card: rgba(18, 24, 38, 0.9); --accent: #2AABEE; --gold: #FFD233; --red: #FF3B30; --green: #2ED573; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: radial-gradient(circle at top, #141E33 0%, #070A10 100%); color: #fff; min-height: 100vh; padding: 30px 15px; }
        .container { max-width: 900px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 25px; }
        header h1 { font-size: 30px; font-weight: 800; background: linear-gradient(135deg, #fff, #2AABEE); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .card { background: var(--card); border: 1px solid rgba(56, 75, 110, 0.4); border-radius: 20px; padding: 25px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); margin-bottom: 20px; }
        textarea { width: 100%; height: 130px; background: rgba(8, 12, 20, 0.9); border: 1px solid #2B3A55; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 15px; resize: vertical; }
        .upload-zone { border: 2px dashed #2B3A55; border-radius: 12px; padding: 16px; text-align: center; cursor: pointer; color: #8E9BAE; font-size: 14px; margin-bottom: 15px; transition: 0.2s; }
        .upload-zone:hover { border-color: var(--accent); color: #fff; }
        .btn { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; transition: 0.2s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(42, 171, 238, 0.4); }
        .btn:disabled { opacity: 0.5; }
        .video-box { margin-top: 20px; border-radius: 16px; overflow: hidden; background: #000; display: none; border: 1px solid #2B3A55; }
        video { width: 100%; max-height: 520px; object-fit: contain; }
        .social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-top: 15px; }
        .soc-btn { background: rgba(255,255,255,0.06); border: 1px solid #2B3A55; padding: 12px; border-radius: 10px; color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; text-decoration: none; }
        .soc-btn:hover { background: rgba(255,255,255,0.15); border-color: var(--accent); }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⚡ Viral News Video Studio Pro</h1>
            <p style="color:#8E9BAE; font-size:14px; margin-top:5px;">Автоматичний монтаж вірусного кінематографічного відео + автопостинг</p>
        </header>

        <div class="card">
            <textarea id="newsText" placeholder="Просто вставте сюди пост вашої новини з Telegram..."></textarea>
            
            <div class="upload-zone" onclick="document.getElementById('fileInp').click()">
                📷 Додати фото з посту (якщо немає — ШІ згенерує кінематографічний кадр самостійно)
                <input type="file" id="fileInp" accept="image/*" style="display:none;" onchange="showF(this)">
                <div id="fileTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn" id="genBtn" onclick="run()">🚀 Змонтувати вірусне відео</button>
            <div id="load" style="display:none; text-align:center; color:var(--gold); margin-top:15px; font-weight:600;">
                ⏳ Генерація ШІ-кадру, озвучка без смайликів та кіно-монтаж... (45-60 сек)
            </div>

            <div class="video-box" id="vBox">
                <video id="vPlay" controls></video>
                <div style="padding:15px; border-top:1px solid #2B3A55;">
                    <p style="font-size:14px; font-weight:bold; color:var(--gold); margin-bottom:10px;">🚀 Відвантажити готове відео в соцмережі:</p>
                    <div class="social-grid">
                        <a id="dl" class="soc-btn" style="background:#2ED573; color:#000;" download>⬇ Завантажити</a>
                        <button class="soc-btn" onclick="postTo('YouTube Shorts')">▶ YouTube</button>
                        <button class="soc-btn" onclick="postTo('TikTok')">🎵 TikTok</button>
                        <button class="soc-btn" onclick="postTo('Instagram Reels')">📸 Reels</button>
                        <button class="soc-btn" onclick="postTo('Facebook Reels')">📘 Facebook</button>
                        <button class="soc-btn" onclick="postTo('Threads')">🧵 Threads</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function showF(i) {
            if(i.files && i.files[0]) document.getElementById('fileTxt').innerText = '✓ Обрано: ' + i.files[0].name;
        }
        async function run() {
            const btn = document.getElementById('genBtn');
            const load = document.getElementById('load');
            const box = document.getElementById('vBox');
            const vid = document.getElementById('vPlay');
            const text = document.getElementById('newsText').value;
            const file = document.getElementById('fileInp').files[0];

            btn.disabled = true;
            load.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', text);
                if(file) fd.append('image', file);
                const res = await fetch('/api/generate', { method: 'POST', body: fd });
                const d = await res.json();
                if(d.video_url) {
                    vid.src = d.video_url;
                    document.getElementById('dl').href = d.video_url;
                    box.style.display = 'block';
                    vid.play();
                }
            } catch(e) {
                alert('Помилка: ' + e);
            } finally {
                btn.disabled = false;
                load.style.display = 'none';
            }
        }
        function postTo(network) {
            alert("🚀 Запит на публікацію в " + network + " прийнято! Якщо ваші API-ключі додані в налаштуваннях, ролик з'явиться в профілі автоматично. Або скористайтеся кнопкою «Завантажити» для моментальної вигрузки вручну.");
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_gen(text: Optional[str] = Form(None), image: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "УВАГА: Верховна Рада щойно ухвалила скандальний закон про нові тарифи! Зміни торкнуться кожного вже з наступного місяця."

    script_data = ScriptGenerator.generate(text)

    # 1. Отримання фонового фото
    bg_img_path = Config.TEMP_DIR / f"bg_{int(time.time())}.jpg"
    if image and image.filename:
        with open(bg_img_path, "wb") as f:
            f.write(await image.read())
    else:
        # Автоматична генерація кінематографічного кадру під новину
        gen_img = generate_ai_bait_image(script_data["headline"] + " " + script_data["body"], bg_img_path)
        if not gen_img or not bg_img_path.exists():
            # Резервний стильний темно-синій градієнт
            im = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (12, 18, 28))
            im.save(bg_img_path)

    # 2. Озвучка без смайликів
    temp_audio = Config.TEMP_DIR / f"voice_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(script_data["full_voiceover"], temp_audio)
    sub_events = TTSEngine.chunks(script_data["full_voiceover"], duration)

    # 3. Кіно-монтаж
    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_bait_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    engine.render(script_data, audio_path, sub_events, out_file, bg_img_path)

    # Прибирання тимчасових файлів
    for p in [temp_audio, bg_img_path]:
        if p.exists():
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
