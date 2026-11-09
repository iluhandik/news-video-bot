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
    VOICE_RATE = "+14%"
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
    text = re.sub(r"[⚡🔥👉👇⚠️🚨✔✓➔➡•—–«»#*_=~`\"']", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def generate_seo_metadata(headline: str, body: str) -> Dict[str, str]:
    """Генерує вірусний опис та хештеги індивідуально під зміст новини для залітання в рекомендації"""
    full_text_lower = (headline + " " + body).lower()
    
    # Визначення тематики та цільових тегів
    topic_tags = []
    if any(k in full_text_lower for k in ["дорог", "авто", "тариф", "проїзд", "водій", "штраф"]):
        topic_tags = ["#платнідороги", "#водіїукраїни", "#автоукраїна", "#дорогиукраїни", "#тарифи"]
        question = "Що думаєте про такі тарифи? Пишіть у коментарях 👇"
    elif any(k in full_text_lower for k in ["трамп", "сша", "байден", "переговори", "вибори"]):
        topic_tags = ["#трамп", "#сша", "#новинисвіту", "#геополітика", "#політика"]
        question = "Як ви ставитеся до такої заяви? Діліться думками 👇"
    elif any(k in full_text_lower for k in ["пенсі", "виплат", "зарплат", "грош", "банк", "курс"]):
        topic_tags = ["#виплати", "#пенсії", "#грошіукраїна", "#фінанси", "#соціалка"]
        question = "Чи вистачає цих коштів зараз? Ваша думка в коментарях 👇"
    elif any(k in full_text_lower for k in ["рада", "закон", "депутат", "уряд", "зеленськ"]):
        topic_tags = ["#верховнарада", "#закониукраїни", "#політикаукраїни", "#слуганароду"]
        question = "Підтримуєте таке рішення депутатів? 👇"
    else:
        topic_tags = ["#резонанс", "#терміново", "#важливознати"]
        question = "Що ви думаєте з цього приводу? Обговорюємо в коментарях 👇"

    base_tags = ["#новиниукраїни", "#новини", "#українасьогодні", "#рек", "#рекомендації", "#тренди"]
    all_hashtags = " ".join(topic_tags + base_tags)

    description = f"{headline}! {question}\n\nПовні подробиці та першоджерело дивіться за посиланням у шапці профілю!\n\n{all_hashtags}"
    
    return {
        "description": description,
        "hashtags": all_hashtags
    }

def parse_post(raw_post: str) -> Dict[str, str]:
    lines = [l.strip() for l in raw_post.split("\n") if len(l.strip()) > 3]
    if lines:
        headline = clean_text_for_tts(lines[0])[:50].upper()
        body = clean_text_for_tts(" ".join(lines[1:])) if len(lines) > 1 else clean_text_for_tts(lines[0])
    else:
        headline = "ТЕРМІНОВА НОВИНА"
        body = clean_text_for_tts(raw_post)

    cta = "Повні деталі дивіться в нашому Телеграм каналі. Посилання в шапці профілю!"
    voice = f"{headline}. {body}. {cta}"

    seo = generate_seo_metadata(headline, body)

    return {
        "headline": headline,
        "body": body[:200],
        "voiceover": clean_text_for_tts(voice),
        "seo_description": seo["description"],
        "seo_hashtags": seo["hashtags"]
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
        self.font_head = ImageFont.truetype(self.font_path, 40)
        self.font_sub = ImageFont.truetype(self.font_path, 24)
        self.font_cta = ImageFont.truetype(self.font_path, 30)

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1000, 200
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(self.font_path, 68)
        up = text.upper()
        tw = draw.textlength(up, font=font)
        tx = max(10, (w - tw) // 2)
        ty = (h - 68) // 2

        # Чорний контур
        for dx in range(-6, 7):
            for dy in range(-6, 7):
                if dx*dx + dy*dy <= 36:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), up, font=font, fill=(255, 220, 10, 255))
        return img

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, user_img_path: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # 1. Розмитий фон Canvas Blur 9:16
        if user_img_path and user_img_path.exists():
            orig_img = Image.open(user_img_path).convert("RGB")
            bg_blurred = orig_img.resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT)).filter(ImageFilter.GaussianBlur(35))
            dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (0, 0, 0, 140))
            bg_blurred.paste(dim, (0, 0), dim)

            ow, oh = orig_img.size
            nw = 1000
            nh = int(oh * (nw / ow))
            sharp_img = orig_img.resize((nw, nh))

            sharp_y = (Config.VIDEO_HEIGHT - nh) // 2 - 80
            bg_blurred.paste(sharp_img, ((Config.VIDEO_WIDTH - nw) // 2, sharp_y))
            final_bg = bg_blurred
        else:
            final_bg = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (15, 20, 30))

        # 2. Верхній заголовок
        top_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 350), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(top_bar)
        t_draw.rounded_rectangle([40, 110, 340, 175], radius=12, fill=(225, 25, 35, 255))
        t_draw.text((60, 122), "ТЕРМІНОВО", font=self.font_sub, fill=(255, 255, 255, 255))
        t_draw.text((40, 205), parsed["headline"], font=self.font_head, fill=(255, 255, 255, 255))
        t_draw.line([(40, 290), (Config.VIDEO_WIDTH - 40, 290)], fill=(255, 215, 0, 200), width=3)

        # 3. Нижня плашка CTA
        cta_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 160), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_bar)
        c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 140], radius=20, fill=(18, 25, 38, 240), outline=(42, 171, 238, 255), width=2)
        cta_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
        tw = c_draw.textlength(cta_txt, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - tw)//2, 42), cta_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        sub_c = Config.CHANNEL_DISPLAY_NAME
        c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(sub_c, font=self.font_sub))//2, 88), sub_c, font=self.font_sub, fill=(42, 171, 238, 255))

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            zoom = 1.0 + 0.02 * (t / max(1.0, duration))
            zw, zh = int(Config.VIDEO_WIDTH * zoom), int(Config.VIDEO_HEIGHT * zoom)
            z_img = final_bg.resize((zw, zh))
            frame = z_img.crop(((zw - Config.VIDEO_WIDTH)//2, (zh - Config.VIDEO_HEIGHT)//2, (zw + Config.VIDEO_WIDTH)//2, (zh + Config.VIDEO_HEIGHT)//2)).convert("RGBA")

            frame.alpha_composite(top_bar, (0, 0))

            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 1150))
                    break

            frame.alpha_composite(cta_bar, (0, 1420))
            return np.array(frame.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        clip.close()
        return out_file

app = FastAPI(title="Viral News Studio Pro")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Viral News Studio</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #070A11; --card: #131A26; --accent: #2AABEE; --gold: #FFD233; --green: #2ED573; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 850px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; background: linear-gradient(135deg, #fff, #2AABEE); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .box { background: var(--card); border: 1px solid #232E42; border-radius: 20px; padding: 24px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        textarea { width: 100%; height: 140px; background: #0A0E17; border: 1px solid #232E42; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .drop { border: 2px dashed #2AABEE; border-radius: 12px; padding: 16px; text-align: center; cursor: pointer; color: #fff; font-size: 14px; margin-bottom: 14px; background: rgba(42, 171, 238, 0.05); }
        .btn-go { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; transition: 0.2s; }
        .btn-go:hover { transform: translateY(-2px); }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 14px; font-weight: 700; }
        .res { margin-top: 25px; display: none; }
        video { width: 100%; max-height: 500px; border-radius: 14px; background: #000; border: 1px solid #232E42; }
        .seo-box { background: #0A0E17; border: 1px solid #232E42; border-radius: 14px; padding: 16px; margin-top: 15px; }
        .seo-title { font-size: 14px; font-weight: 800; color: var(--gold); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
        .copy-btn { background: rgba(255,255,255,0.08); border: 1px solid #232E42; color: #fff; padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; }
        .copy-btn:hover { background: rgba(255,255,255,0.2); }
        .seo-text { font-size: 13px; color: #C5D1E0; white-space: pre-wrap; line-height: 1.5; }
        .social-title { font-size: 14px; font-weight: 800; color: #fff; margin: 20px 0 10px; }
        .social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
        .soc-link { padding: 14px; border-radius: 12px; text-align: center; text-decoration: none; font-weight: 800; font-size: 14px; display: flex; align-items: center; justify-content: center; gap: 6px; transition: 0.2s; }
        .soc-link:hover { transform: translateY(-2px); filter: brightness(1.1); }
        .btn-dl { background: var(--green); color: #000; }
        .btn-tt { background: #000; color: #fff; border: 1px solid #333; }
        .btn-yt { background: #FF0000; color: #fff; }
        .btn-ig { background: linear-gradient(45deg, #F58529, #DD2A7B, #8134AF); color: #fff; }
        .btn-fb { background: #1877F2; color: #fff; }
        .btn-th { background: #101010; color: #fff; border: 1px solid #333; }
    </style>
</head>
<body>
    <div class="wrap">
        <header>
            <h1>⚡ Студія вірусних новин TikTok / Shorts</h1>
            <p style="color:#8E9BAE; font-size:14px; margin-top:4px;">Монтаж у форматі рекомендацій + розумні хештеги та пряме вивантаження</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини з вашого Telegram-каналу..."></textarea>
            
            <div class="drop" onclick="document.getElementById('mFile').click()">
                📷 Додати фото або відео новини (зробить розмитий фон 9:16)
                <input type="file" id="mFile" accept="image/*" style="display:none;" onchange="showF(this)">
                <div id="mTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="gen()">🚀 Змонтувати вірусне відео</button>
            <div id="st">⏳ Створення кінематографічного розмиття фону, озвучка та прорахунок хештегів...</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>

                <!-- Блок індивідуального SEO під рекомендації -->
                <div class="seo-box">
                    <div class="seo-title">
                        <span>🔥 Опис та прораховані хештеги під рекомендації:</span>
                        <button class="copy-btn" onclick="copySeo()">📋 Скопіювати все</button>
                    </div>
                    <div class="seo-text" id="seoContent"></div>
                </div>

                <!-- Кнопки швидкого вивантаження -->
                <div class="social-title">🚀 Завантажити та відвантажити в соцмережі:</div>
                <div class="social-grid">
                    <a id="dlBtn" class="soc-link btn-dl" download>⬇ Скачати MP4</a>
                    <a href="https://www.tiktok.com/upload" target="_blank" class="soc-link btn-tt">🎵 TikTok</a>
                    <a href="https://studio.youtube.com/channel/UC/videos/shortsvanity" target="_blank" class="soc-link btn-yt">▶ Shorts</a>
                    <a href="https://www.instagram.com/" target="_blank" class="soc-link btn-ig">📸 Reels</a>
                    <a href="https://www.facebook.com/reels/create" target="_blank" class="soc-link btn-fb">📘 Facebook</a>
                    <a href="https://www.threads.net/" target="_blank" class="soc-link btn-th">🧵 Threads</a>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentSeoText = '';
        function showF(i) {
            if(i.files && i.files[0]) document.getElementById('mTxt').innerText = '✓ Обрано: ' + i.files[0].name;
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
                    currentSeoText = d.seo_description;
                    document.getElementById('seoContent').innerText = d.seo_description;
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
        function copySeo() {
            navigator.clipboard.writeText(currentSeoText);
            alert("✓ Опис і хештеги скопійовано! Тепер переходьте у соцмережу та вставляйте.");
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_generate(text: Optional[str] = Form(None), media: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "УВАГА: В Україні готують закон про платні дороги. Ставки затвердять до кінця 2027 року."

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

    return {
        "video_url": f"/videos/{out_file.name}",
        "seo_description": parsed["seo_description"]
    }

@app.get("/videos/{filename}")
async def get_vid(filename: str):
    p = Config.OUTPUT_DIR / filename
    if p.exists():
        return FileResponse(p, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/status")
async def status():
    return {"status": "ok"}
