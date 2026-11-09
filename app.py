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
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoClip, AudioFileClip

class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_USERNAME = "@news_ukraine365"
    VOICE_NAME = "uk-UA-OstapNeural"
    VOICE_RATE = "+10%"
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 25
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
    text = re.sub(r"(\d+)-([а-яА-ЯіїєґІЇЄҐ]+)", r"\1 \2", text)
    text = re.sub(r"\.{2,}", ".", text)
    return re.sub(r"\s+", " ", text).strip()

def wrap_text_lines(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> List[str]:
    words = text.split()
    lines = []
    cur = []
    dummy = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(dummy)
    for w in words:
        test = " ".join(cur + [w])
        if d.textlength(test, font=font) <= max_w:
            cur.append(w)
        else:
            if cur: lines.append(" ".join(cur))
            cur = [w]
    if cur: lines.append(" ".join(cur))
    return lines

def parse_post(raw_post: str) -> Dict[str, str]:
    clean = clean_for_tts(raw_post)
    lines = [l.strip() for l in raw_post.split("\n") if len(l.strip()) > 3]
    
    if lines:
        headline = clean_for_tts(lines[0])
        body_text = clean_for_tts(" ".join(lines[1:])) if len(lines) > 1 else clean_for_tts(lines[0])
    else:
        headline = "ТЕРМІНОВА НОВИНА"
        body_text = clean

    cta = "Повні деталі дивіться в нашому Телеграм каналі за посиланням у шапці профілю."
    voice = f"{headline}. {body_text}. {cta}"

    return {
        "headline": headline.upper(),
        "body": body_text,
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
        self.font_badge = ImageFont.truetype(self.font_path, 26)
        self.font_head = ImageFont.truetype(self.font_path, 36)
        self.font_cta = ImageFont.truetype(self.font_path, 30)
        self.font_cta_sub = ImageFont.truetype(self.font_path, 22)
        self.font_watermark = ImageFont.truetype(self.font_path, 24)

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1020, 220
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        up = text.upper()

        # Автоматичний підбір розміру шрифту, щоб слово не обрізалося
        font_size = 64
        font = ImageFont.truetype(self.font_path, font_size)
        while draw.textlength(up, font=font) > (w - 60) and font_size > 36:
            font_size -= 4
            font = ImageFont.truetype(self.font_path, font_size)

        tw = draw.textlength(up, font=font)
        tx = max(20, (w - tw) // 2)
        ty = (h - font_size) // 2

        # Чорний контур
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx*dx + dy*dy <= 25:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), up, font=font, fill=(255, 220, 10, 255))
        return img

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, user_img_path: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # 1. Формування фону та центрального фото
        if user_img_path and user_img_path.exists():
            try:
                orig = Image.open(user_img_path).convert("RGB")
                small = orig.resize((270, 480))
                bg_blur = small.resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), Image.BILINEAR).filter(ImageFilter.BoxBlur(8))
                dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (0, 0, 0, 160))
                bg_blur.paste(dim, (0, 0), dim)

                ow, oh = orig.size
                nw = 1000
                nh = int(oh * (nw / ow))
                sharp_img = orig.resize((nw, nh))
                sharp_y = (Config.VIDEO_HEIGHT - nh) // 2 - 40
            except Exception:
                bg_blur = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (15, 22, 35))
                sharp_img = None
                sharp_y = 600
        else:
            bg_blur = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (15, 22, 35))
            sharp_img = None
            sharp_y = 600

        # 2. Верхній заголовок (з авто-переносом рядків)
        top_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 420), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(top_bar)
        t_draw.rounded_rectangle([40, 95, 300, 155], radius=12, fill=(225, 25, 35, 255))
        t_draw.text((55, 108), "ТЕРМІНОВО", font=self.font_badge, fill=(255, 255, 255, 255))

        # Фірмова вотермарка в правому кутку
        wm_text = Config.CHANNEL_DISPLAY_NAME
        wm_w = int(t_draw.textlength(wm_text, font=self.font_watermark))
        t_draw.rounded_rectangle([Config.VIDEO_WIDTH - wm_w - 70, 95, Config.VIDEO_WIDTH - 40, 155], radius=12, fill=(20, 30, 45, 200), outline=(50, 70, 100, 255), width=1)
        t_draw.text((Config.VIDEO_WIDTH - wm_w - 55, 110), wm_text, font=self.font_watermark, fill=(255, 255, 255, 220))

        head_lines = wrap_text_lines(parsed["headline"], self.font_head, Config.VIDEO_WIDTH - 80)
        cur_hy = 175
        for hl in head_lines[:2]:
            t_draw.text((40, cur_hy), hl, font=self.font_head, fill=(255, 255, 255, 255))
            cur_hy += 46
        t_draw.line([(40, cur_hy + 8), (Config.VIDEO_WIDTH - 40, cur_hy + 8)], fill=(255, 215, 0, 220), width=3)

        # 3. Нижня плашка CTA
        cta_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 160), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_bar)
        c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 140], radius=20, fill=(18, 24, 36, 245), outline=(42, 171, 238, 255), width=2)
        c_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
        cw = c_draw.textlength(c_txt, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - cw)//2, 42), c_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        c_sub = Config.CHANNEL_DISPLAY_NAME
        c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(c_sub, font=self.font_cta_sub))//2, 88), c_sub, font=self.font_cta_sub, fill=(42, 171, 238, 255))

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            frame = bg_blur.copy().convert("RGBA")

            if sharp_img:
                frame.paste(sharp_img, ((Config.VIDEO_WIDTH - 1000)//2, sharp_y))

            frame.alpha_composite(top_bar, (0, 0))

            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        # Субтитри розташовані на комфортній висоті
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 1180))
                    break

            frame.alpha_composite(cta_bar, (0, 1420))
            return np.array(frame.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        clip.close()
        return out_file

app = FastAPI(title="Viral News Studio")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Studio Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #070A11; --card: #131A26; --accent: #2AABEE; --gold: #FFD233; --green: #2ED573; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 850px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid #232E42; border-radius: 20px; padding: 24px; }
        textarea { width: 100%; height: 140px; background: #0A0E17; border: 1px solid #232E42; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .drop { border: 2px dashed #2AABEE; border-radius: 12px; padding: 16px; text-align: center; cursor: pointer; color: #fff; font-size: 14px; margin-bottom: 14px; background: rgba(42, 171, 238, 0.05); }
        .btn-go { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 14px; font-weight: 700; }
        .res { margin-top: 25px; display: none; }
        video { width: 100%; max-height: 500px; border-radius: 14px; background: #000; border: 1px solid #232E42; }
        .social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin-top: 15px; }
        .soc-link { padding: 14px; border-radius: 12px; text-align: center; text-decoration: none; font-weight: 800; font-size: 14px; display: flex; align-items: center; justify-content: center; }
        .btn-dl { background: var(--green); color: #000; }
        .btn-tt { background: #000; color: #fff; border: 1px solid #333; }
        .btn-yt { background: #FF0000; color: #fff; }
        .btn-ig { background: linear-gradient(45deg, #F58529, #DD2A7B, #8134AF); color: #fff; }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>🎬 Студія новин NEWS УКРАЇНА 365</h1>
            <p style="color:#8E9BAE; font-size:14px;">З вотермаркою каналу, повними субтитрами та швидким рендерингом</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини..."></textarea>
            
            <div class="drop" onclick="document.getElementById('mFile').click()">
                📷 Додати фото з посту (натисніть, щоб обрати)
                <input type="file" id="mFile" accept="image/*" style="display:none;" onchange="showF(this)">
                <div id="mTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="gen()">🚀 Змонтувати відео</button>
            <div id="st">⏳ Монтаж відео та накладання вотермарки... (20-30 сек)</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>
                <div class="social-grid">
                    <a id="dlBtn" class="soc-link btn-dl" download>⬇ Скачати MP4</a>
                    <a href="https://www.tiktok.com/upload" target="_blank" class="soc-link btn-tt">🎵 TikTok</a>
                    <a href="https://studio.youtube.com/channel/UC/videos/shortsvanity" target="_blank" class="soc-link btn-yt">▶ Shorts</a>
                    <a href="https://www.instagram.com/" target="_blank" class="soc-link btn-ig">📸 Reels</a>
                </div>
            </div>
        </div>
    </div>

    <script>
        let selectedFile = null;
        function showF(i) {
            if(i.files && i.files[0]) {
                selectedFile = i.files[0];
                document.getElementById('mTxt').innerText = '✓ Обрано фото: ' + selectedFile.name;
            }
        }
        async function gen() {
            const btn = document.getElementById('btn');
            const st = document.getElementById('st');
            const box = document.getElementById('resBox');
            const vid = document.getElementById('vPlay');
            const txt = document.getElementById('pTxt').value;

            btn.disabled = true;
            st.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', txt);
                if(selectedFile) {
                    fd.append('media', selectedFile);
                }
                const res = await fetch('/api/generate', { method: 'POST', body: fd });
                if (!res.ok) {
                    throw new Error("Сервер повернув помилку (код " + res.status + ")");
                }
                const d = await res.json();
                if(d.video_url) {
                    vid.src = d.video_url;
                    document.getElementById('dlBtn').href = d.video_url;
                    box.style.display = 'block';
                    vid.play();
                }
            } catch(e) {
                alert('Помилка: ' + e.message);
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
        text = "У ЛЬВОВІ ТРЕТЬОКЛАСНИКА ОШТРАФОВАНО ЗА ПОГРОЗИ ОДНОКЛАСНИКАМ. 9 річний учень погрожував ножем."

    parsed = parse_post(text)

    media_p = None
    if media and media.filename:
        media_p = Config.TEMP_DIR / f"img_{int(time.time())}_{media.filename}"
        with open(media_p, "wb") as f:
            f.write(await media.read())

    temp_audio = Config.TEMP_DIR / f"v_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio)
    sub_events = TTSEngine.chunks(parsed["voiceover"], duration)

    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
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
