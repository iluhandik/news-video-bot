import os
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
from moviepy import VideoClip, AudioFileClip, VideoFileClip

class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_USERNAME = "@news_ukraine365"
    VOICE_NAME = "uk-UA-OstapNeural"
    VOICE_RATE = "+14%"
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
    text = re.sub(r"[⚡🔥👉👇⚠️🚨✔✓➔➡•—–«»#*_=~`\"']", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def parse_post(raw_post: str) -> Dict[str, str]:
    lines = [l.strip() for l in raw_post.split("\n") if len(l.strip()) > 3]
    if lines:
        headline = clean_for_tts(lines[0])[:60]
        body_lines = lines[1:] if len(lines) > 1 else lines
        body = clean_for_tts(" ".join(body_lines))
    else:
        headline = "ТЕРМІНОВА НОВИНА"
        body = clean_for_tts(raw_post)

    cta = "Більше деталей дивіться в нашому Телеграм каналі. Посилання в шапці профілю!"
    voice = f"{headline}. {body}. {cta}"

    return {
        "headline": headline,
        "body": body[:220],
        "voiceover": clean_for_tts(voice)
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
            dur = max(8.0, min(25.0, len(text) / 14.0))
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
            return 15.0

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
        self.font_ch_name = ImageFont.truetype(self.font_path, 32)
        self.font_head = ImageFont.truetype(self.font_path, 32)
        self.font_body = ImageFont.truetype(self.font_path, 28)
        self.font_sub = ImageFont.truetype(self.font_path, 22)
        self.font_cta = ImageFont.truetype(self.font_path, 28)

    def _render_telegram_card(self, headline: str, body: str) -> Image.Image:
        w, h = 980, 540
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Біла картка Telegram
        draw.rounded_rectangle([0, 0, w, h], radius=24, fill=(255, 255, 255, 255), outline=(225, 230, 240, 255), width=2)

        # Фіолетова назва каналу як у пості: NEWS УКРАЇНА 365
        draw.text((36, 28), Config.CHANNEL_DISPLAY_NAME, font=self.font_ch_name, fill=(120, 50, 210, 255))
        draw.line([(36, 75), (w - 36, 75)], fill=(240, 242, 248, 255), width=2)

        # Заголовок новини з помаранчевим акцентом
        head_txt = headline[:48] + ("..." if len(headline) > 48 else "")
        draw.text((36, 95), "⚡ " + head_txt, font=self.font_head, fill=(210, 30, 40, 255))

        # Повний текст новини
        words = body.split()
        cur_y = 155
        for i in range(0, min(len(words), 42), 7):
            line = " ".join(words[i:i+7])
            draw.text((36, cur_y), line, font=self.font_body, fill=(35, 45, 60, 255))
            cur_y += 42

        # Нижня плашка Telegram
        draw.text((36, h - 48), f"👉 {Config.CHANNEL_DISPLAY_NAME} | Підписатися", font=self.font_sub, fill=(42, 140, 220, 255))
        draw.text((w - 180, h - 48), "👁 148K переглядів", font=self.font_sub, fill=(140, 150, 165, 255))
        return img

    def _render_karaoke_sub(self, text: str) -> Image.Image:
        w, h = 1000, 220
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(self.font_path, 66)
        up = text.upper()
        tw = draw.textlength(up, font=font)
        tx = max(15, (w - tw) // 2)
        ty = (h - 66) // 2

        # Товстий чорний контур для читабельності
        for dx in range(-6, 7):
            for dy in range(-6, 7):
                if dx*dx + dy*dy <= 36:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        # Яскравий неоновий жовтий
        draw.text((tx, ty), up, font=font, fill=(255, 235, 10, 255))
        return img

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, media_file: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # Підготовка медіа (відео або фото з посту) для верхньої половини екрана (980x750)
        media_img_base = None
        media_clip = None

        if media_file and media_file.exists():
            ext = media_file.suffix.lower()
            if ext in [".mp4", ".mov", ".avi", ".webm"]:
                try:
                    media_clip = VideoFileClip(str(media_file)).resized(width=980)
                except Exception:
                    media_clip = None
            else:
                try:
                    m = Image.open(media_file).convert("RGB")
                    mw, mh = m.size
                    tr = 980 / 720
                    if mw / mh > tr:
                        nw = int(mh * tr)
                        m_crop = m.crop(((mw - nw)//2, 0, (mw + nw)//2, mh))
                    else:
                        nh = int(mw / tr)
                        m_crop = m.crop((0, (mh - nh)//2, mw, (mh + nh)//2))
                    media_img_base = m_crop.resize((980, 720))
                except Exception:
                    media_img_base = None

        # Якщо медіа не завантажено — створюємо якісну стильну підкладку
        if not media_img_base and not media_clip:
            media_img_base = Image.new("RGB", (980, 720), (25, 35, 50))
            d = ImageDraw.Draw(media_img_base)
            d.text((360, 340), "▶ ВІДЕО НОВИНИ", font=self.font_head, fill=(255, 255, 255, 180))

        # Нижня Telegram-картка з повним текстом
        card = self._render_telegram_card(parsed["headline"], parsed["body"])
        sub_cache = {e["text"]: self._render_karaoke_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            # Темний фон 9:16
            frame = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (12, 16, 24, 255))
            draw = ImageDraw.Draw(frame)

            # 1. Верхнє живе відео або фото з посту (Y = 120..840)
            if media_clip:
                sub_t = t % media_clip.duration
                f_np = media_clip.get_frame(sub_t)
                f_img = Image.fromarray(f_np).resize((980, 720))
                frame.paste(f_img, ((Config.VIDEO_WIDTH - 980)//2, 120))
            elif media_img_base:
                # Плавний легкий рух фото
                zoom = 1.0 + 0.02 * (t / max(1.0, duration))
                zw, zh = int(980 * zoom), int(720 * zoom)
                z_im = media_img_base.resize((zw, zh))
                crop_im = z_im.crop(((zw - 980)//2, (zh - 720)//2, (zw + 980)//2, (zh + 720)//2))
                frame.paste(crop_im, ((Config.VIDEO_WIDTH - 980)//2, 120))

            # 2. Нижня картка Telegram із текстом (Y = 880)
            frame.alpha_composite(card, ((Config.VIDEO_WIDTH - card.width)//2, 880))

            # 3. Великі динамічні субтитри поверх медіа
            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 740))
                    break

            return np.array(frame.convert("RGB"))

        out_clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        out_clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        out_clip.close()
        if media_clip:
            media_clip.close()
        return out_file

app = FastAPI(title="News Video Studio")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NEWS 365 Video Maker</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0A0E17; --card: #151C28; --accent: #2AABEE; --gold: #FFD233; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 30px 15px; }
        .wrap { max-width: 800px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 25px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid #28344A; border-radius: 20px; padding: 25px; }
        textarea { width: 100%; height: 160px; background: #0E131E; border: 1px solid #28344A; border-radius: 12px; padding: 14px; color: #fff; font-size: 14px; outline: none; margin-bottom: 14px; resize: vertical; }
        .drop { border: 2px dashed #2AABEE; border-radius: 12px; padding: 18px; text-align: center; cursor: pointer; color: #fff; font-size: 14px; margin-bottom: 15px; background: rgba(42, 171, 238, 0.05); }
        .btn-go { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; }
        .btn-go:disabled { opacity: 0.5; }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 15px; font-weight: 700; font-size: 14px; }
        .res { margin-top: 25px; display: none; }
        video { width: 100%; max-height: 540px; border-radius: 14px; background: #000; }
        .dl { display: block; text-align: center; background: #2ED573; color: #000; text-decoration: none; padding: 15px; border-radius: 12px; font-weight: 800; margin-top: 12px; }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>🎬 Студія TikTok ролика під ваш Telegram-канал</h1>
            <p style="color:#8E9BAE; font-size:14px; margin-top:5px;">Верхня частина — відео/фото з посту, нижня — повний текст посту з озвучкою</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини (заголовок і весь опис)..."></textarea>
            
            <div class="drop" onclick="document.getElementById('mFile').click()">
                📹 <b>Обов'язково додайте відео або фото з посту</b> (наприклад, фрагмент з Трампом)
                <input type="file" id="mFile" accept="video/*,image/*" style="display:none;" onchange="showName(this)">
                <div id="mTxt" style="color:var(--gold); font-weight:800; margin-top:6px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="gen()">🚀 Змонтувати вірусний ролик</button>
            <div id="st">⏳ Збірка відео: склеювання кадру, накладання тексту посту та повна озвучка...</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>
                <a id="dlBtn" class="dl" download>⬇ Завантажити готовий MP4 для TikTok</a>
            </div>
        </div>
    </div>

    <script>
        function showName(i) {
            if(i.files && i.files[0]) document.getElementById('mTxt').innerText = '✓ Обрано файл: ' + i.files[0].name;
        }
        async function gen() {
            const btn = document.getElementById('btn');
            const st = document.getElementById('st');
            const box = document.getElementById('resBox');
            const vid = document.getElementById('vPlay');
            const txt = document.getElementById('pTxt').value;
            const f = document.getElementById('mFile').files[0];

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
        text = "Трамп: «Не хочу потрапити до пекла». У інтерв'ю програмі 60 Minutes Дональд Трамп поділився своїми думками про потойбічне життя."

    parsed = parse_post(text)

    media_p = None
    if media and media.filename:
        media_p = Config.TEMP_DIR / f"media_{int(time.time())}_{media.filename}"
        with open(media_p, "wb") as f:
            f.write(await media.read())

    temp_audio = Config.TEMP_DIR / f"voice_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio)
    sub_events = TTSEngine.chunks(parsed["voiceover"], duration)

    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_365_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
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
