import os
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

class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_USERNAME = "@news_ukraine365"
    VOICE_NAME = "uk-UA-OstapNeural"
    VOICE_RATE = "+8%"
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

def generate_pro_flux_image(news_text: str, out_p: Path) -> bool:
    try:
        t_low = news_text.lower()
        if any(w in t_low for w in ["школ", "учен", "клас", "діт", "вчител"]):
            scene = "hallway of modern school building, police officer talking with teachers, documentary press photography, natural light, 35mm"
        elif any(w in t_low for w in ["суд", "штраф", "закон", "рада", "депутат"]):
            scene = "courtroom interior, wooden judge bench, law gavel, official press photography, dramatic lighting"
        elif any(w in t_low for w in ["дорог", "авто", "тариф", "траса", "водій"]):
            scene = "modern highway toll gate station with cars, evening dusk, realistic editorial photography"
        elif any(w in t_low for w in ["трамп", "сша", "байден", "президент"]):
            scene = "press conference with microphones, american flags in background, documentary photojournalism"
        elif any(w in t_low for w in ["поліц", "стрілян", "напад", "збро"]):
            scene = "police cars with flashing emergency lights at dusk on city street, yellow caution tape, photojournalism"
        else:
            scene = "breaking news scene, camera crew with microphones, police cordon in European city, documentary press photo"

        prompt = f"authentic candid photojournalism, {scene}, shot on 35mm lens, hyperrealistic, detailed, 8k, award winning AP news photo"
        enc = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{enc}?model=flux&width=1080&height=1920&nologo=true&seed={int(time.time())}"
        
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) > 15000:
            with open(out_p, "wb") as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"[FLUX Error] {e}")
    return False

def generate_seo(headline: str, body: str) -> Dict[str, str]:
    combined = (headline + " " + body).lower()
    if any(k in combined for k in ["школ", "учен", "ніж", "штраф", "поліц"]):
        tags = ["#надзвичайніновини", "#школа", "#батьки", "#львів", "#поліція", "#резонанс"]
        q = "Як вважаєте, 1700 грн штрафу для батьків — це достатнє покарання? Пишіть у коментарях 👇"
    elif any(k in combined for k in ["дорог", "авто", "тариф", "проїзд", "водій"]):
        tags = ["#платнідороги", "#водіїукраїни", "#автоновини", "#дороги", "#тарифи"]
        q = "Чи готові ви платити такі гроші за проїзд новими трасами? 👇"
    elif any(k in combined for k in ["трамп", "сша", "байден", "політик"]):
        tags = ["#трамп", "#сша", "#новинисвіту", "#геополітика", "#політика"]
        q = "Що думаєте про такі заяви? Діліться думками в коментарях 👇"
    elif any(k in combined for k in ["рада", "закон", "депутат", "уряд"]):
        tags = ["#верховнарада", "#закониукраїни", "#депутати", "#політика"]
        q = "Підтримуєте ухвалення такого закону? Обговорюємо нижче 👇"
    else:
        tags = ["#терміново", "#важливо", "#новиниукраїни", "#резонанс"]
        q = "Яка ваша думка щодо цієї ситуації? Пишіть у коментарях 👇"

    rec_tags = ["#новини", "#україна", "#новинисьогодні", "#рек", "#рекомендації", "#хочуврек", "#тренди"]
    all_tags = " ".join(tags + rec_tags)
    desc = f"{headline}!\n\n{q}\n\nПовні подробиці дивіться за посиланням у шапці профілю!\n\n{all_tags}"
    return {"desc": desc, "tags": all_tags}

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
    seo_data = generate_seo(headline, body_text)

    return {
        "headline": headline.upper(),
        "body": body_text,
        "voiceover": clean_for_tts(voice),
        "seo_desc": seo_data["desc"]
    }

class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_p: Path):
        try:
            cmd = [
                "edge-tts",
                "--voice", Config.VOICE_NAME,
                "--rate", Config.VOICE_RATE,
                "--text", text,
                "--write-media", str(out_p)
            ]
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
        self.font_badge = ImageFont.truetype(self.font_path, 26)
        self.font_head = ImageFont.truetype(self.font_path, 38)
        self.font_cta = ImageFont.truetype(self.font_path, 28)
        self.font_watermark = ImageFont.truetype(self.font_path, 30)

    def _render_sub(self, text: str) -> Image.Image:
        w, h = 1020, 220
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        up = text.upper()

        font_size = 64
        font = ImageFont.truetype(self.font_path, font_size)
        while draw.textlength(up, font=font) > (w - 60) and font_size > 34:
            font_size -= 4
            font = ImageFont.truetype(self.font_path, font_size)

        tw = draw.textlength(up, font=font)
        tx = max(20, (w - tw) // 2)
        ty = (h - font_size) // 2

        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx*dx + dy*dy <= 25:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), up, font=font, fill=(255, 220, 10, 255))
        return img

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, user_img_path: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        # Підготовка зображення 9:16
        if user_img_path and user_img_path.exists():
            orig = Image.open(user_img_path).convert("RGB")
            # Обрізаємо нижні 50px картинки, щоб гарантовано видалити сторонній логотип
            ow, oh = orig.size
            if oh > 100:
                orig = orig.crop((0, 0, ow, oh - 60))
        else:
            orig = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (18, 25, 40))

        ow, oh = orig.size
        tr = Config.VIDEO_WIDTH / Config.VIDEO_HEIGHT
        if ow / oh > tr:
            nw = int(oh * tr)
            crop_box = ((ow - nw) // 2, 0, (ow + nw) // 2, oh)
        else:
            nh = int(ow / tr)
            crop_box = (0, (oh - nh) // 2, ow, (oh + nh) // 2)
        bg_base = orig.crop(crop_box).resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))
        
        # Легке затемнення
        dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, 120))
        bg_base.paste(dim, (0, 0), dim)

        # 1. Верхній блок новини (ОПУЩЕНИЙ НА РІВЕНЬ Y = 260px - БЕЗПЕЧНА ЗОНА ТІКТОКУ)
        top_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 520), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(top_bar)
        
        # Червоний бейдж «ТЕРМІНОВО»
        t_draw.rounded_rectangle([40, 260, 280, 320], radius=12, fill=(225, 25, 35, 255))
        t_draw.text((55, 272), "ТЕРМІНОВО", font=self.font_badge, fill=(255, 255, 255, 255))

        # Велика яскрава вотермарка каналу праворуч
        wm = Config.CHANNEL_DISPLAY_NAME
        wm_w = int(t_draw.textlength(wm, font=self.font_watermark))
        t_draw.rounded_rectangle([Config.VIDEO_WIDTH - wm_w - 70, 260, Config.VIDEO_WIDTH - 40, 320], radius=12, fill=(120, 50, 210, 240), outline=(255, 255, 255, 200), width=2)
        t_draw.text((Config.VIDEO_WIDTH - wm_w - 55, 272), wm, font=self.font_watermark, fill=(255, 255, 255, 255))

        # Заголовок новини
        h_lines = wrap_text_lines(parsed["headline"], self.font_head, Config.VIDEO_WIDTH - 80)
        cur_hy = 345
        for hl in h_lines[:2]:
            t_draw.text((40, cur_hy), hl, font=self.font_head, fill=(255, 255, 255, 255))
            cur_hy += 48
        t_draw.line([(40, cur_hy + 8), (Config.VIDEO_WIDTH - 40, cur_hy + 8)], fill=(255, 215, 0, 240), width=3)

        # 2. Нижня плашка CTA (піднята до Y = 1380, щоб не накладатися на опис TikTok)
        cta_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 160), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_bar)
        c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 140], radius=20, fill=(18, 25, 38, 245), outline=(42, 171, 238, 255), width=2)
        c_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
        cw = c_draw.textlength(c_txt, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - cw)//2, 42), c_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(Config.CHANNEL_DISPLAY_NAME, font=self.font_badge))//2, 88), Config.CHANNEL_DISPLAY_NAME, font=self.font_badge, fill=(42, 171, 238, 255))

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            zoom = 1.0 + 0.04 * (t / max(1.0, duration))
            zw, zh = int(Config.VIDEO_WIDTH * zoom), int(Config.VIDEO_HEIGHT * zoom)
            z_img = bg_base.resize((zw, zh))
            frame = z_img.crop(((zw - Config.VIDEO_WIDTH)//2, (zh - Config.VIDEO_HEIGHT)//2, (zw + Config.VIDEO_WIDTH)//2, (zh + Config.VIDEO_HEIGHT)//2)).convert("RGBA")

            frame.alpha_composite(top_bar, (0, 0))

            # Субтитри по центру
            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 1080))
                    break

            # Нижня плашка
            frame.alpha_composite(cta_bar, (0, 1360))
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
    <title>News Studio FLUX Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #070A11; --card: #131A26; --accent: #2AABEE; --gold: #FFD233; --green: #2ED573; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 850px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid #232E42; border-radius: 20px; padding: 24px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        textarea { width: 100%; height: 140px; background: #0A0E17; border: 1px solid #232E42; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .drop { border: 2px dashed #2AABEE; border-radius: 12px; padding: 16px; text-align: center; cursor: pointer; color: #fff; font-size: 14px; margin-bottom: 14px; background: rgba(42, 171, 238, 0.05); }
        .btn-go { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 14px; font-weight: 700; }
        .res { margin-top: 25px; display: none; }
        video { width: 100%; max-height: 500px; border-radius: 14px; background: #000; border: 1px solid #232E42; }
        .seo-box { background: #0A0E17; border: 1px solid #232E42; border-radius: 14px; padding: 16px; margin-top: 15px; }
        .seo-title { font-size: 14px; font-weight: 800; color: var(--gold); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
        .copy-btn { background: rgba(255,255,255,0.08); border: 1px solid #232E42; color: #fff; padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; }
        .seo-text { font-size: 13px; color: #C5D1E0; white-space: pre-wrap; line-height: 1.5; }
        .social-title { font-size: 14px; font-weight: 800; color: #fff; margin: 20px 0 10px; }
        .social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
        .soc-link { padding: 14px; border-radius: 12px; text-align: center; text-decoration: none; font-weight: 800; font-size: 14px; display: flex; align-items: center; justify-content: center; }
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
            <h1>🎬 Студія новин NEWS УКРАЇНА 365</h1>
            <p style="color:#8E9BAE; font-size:14px;">100% сумісність із безпечними зонами TikTok та помітна вотермарка</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини..."></textarea>
            
            <div class="drop" onclick="document.getElementById('mFile').click()">
                📷 Додати своє фото з новини (якщо немає — нейромережа підбере автоматично)
                <input type="file" id="mFile" accept="image/*" style="display:none;" onchange="showF(this)">
                <div id="mTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="gen()">🚀 Змонтувати вірусне відео</button>
            <div id="st">⏳ Монтаж у безпечних зонах TikTok та накладання вотермарки... (30-40 сек)</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>

                <div class="seo-box">
                    <div class="seo-title">
                        <span>🔥 Опис та прораховані хештеги під рекомендації:</span>
                        <button class="copy-btn" onclick="copySeo()">📋 Скопіювати все</button>
                    </div>
                    <div class="seo-text" id="seoContent"></div>
                </div>

                <div class="social-title">🚀 Завантажити та відвантажити в соцмережі:</div>
                <div class="social-grid">
                    <a id="dlBtn" class="soc-link btn-dl" download>⬇ Скачати MP4</a>
                    <a href="https://www.tiktok.com/upload" target="_blank" class="soc-link btn-tt">🎵 TikTok</a>
                   <a href="https://www.youtube.com/upload" target="_blank" class="soc-link btn-yt">▶ Shorts</a>
                    <a href="https://www.instagram.com/" target="_blank" class="soc-link btn-ig">📸 Reels</a>
                    <a href="https://www.facebook.com/reels/create" target="_blank" class="soc-link btn-fb">📘 Facebook</a>
                    <a href="https://www.threads.net/" target="_blank" class="soc-link btn-th">🧵 Threads</a>
                </div>
            </div>
        </div>
    </div>

    <script>
        let selectedFile = null;
        let currentSeoText = '';

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
                    throw new Error("Помилка сервера (код " + res.status + ")");
                }
                const d = await res.json();
                if(d.video_url) {
                    vid.src = d.video_url;
                    document.getElementById('dlBtn').href = d.video_url;
                    currentSeoText = d.seo_desc;
                    document.getElementById('seoContent').innerText = d.seo_desc;
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
        function copySeo() {
            navigator.clipboard.writeText(currentSeoText);
            alert("✓ Опис і хештеги скопійовано! Вставляйте у підпис до відео.");
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_generate(text: Optional[str] = Form(None), media: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "У ЛЬВОВІ ТРЕТЬОКЛАСНИКА ОШТРАФОВАНО ЗА ПОГРОЗИ ОДНОКЛАСНИКАМ. 9-річний учень погрожував ножем."

    parsed = parse_post(text)

    media_p = None
    if media and media.filename:
        media_p = Config.TEMP_DIR / f"img_{int(time.time())}_{media.filename}"
        with open(media_p, "wb") as f:
            f.write(await media.read())
    else:
        flux_img = Config.TEMP_DIR / f"flux_{int(time.time())}.jpg"
        if generate_pro_flux_image(parsed["headline"] + " " + parsed["body"], flux_img):
            media_p = flux_img

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
        "seo_desc": parsed["seo_desc"]
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
