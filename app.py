import os
import re
import time
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import numpy as np
from PIL import Image, ImageDraw, ImageFont

class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_USERNAME = "@news_ukraine365"
    VOICE_NAME = "uk-UA-OstapNeural"
    VOICE_RATE = "+8%"
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"t\.me/\S+", " ", text)
    text = re.sub(r"@[a-zA-Z0-9_]+", " ", text)

    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub(" ", text)

    text = text.replace("!?", " ").replace("?!", " ").replace("!", " ").replace("?", " ")
    text = re.sub(r"[⚡🔥👉👇⚠️🚨✔✓➔➡•—–«»#*_=~`\"'()\[\]{}:;+/\\]", " ", text)
    text = re.sub(r"(\d+)-([а-яА-ЯіїєґІЇЄҐ]+)", r"\1 \2", text)
    text = text.replace("-", " ")
    text = re.sub(r"\.{2,}", ".", text)
    return re.sub(r"\s+", " ", text).strip()

def has_word(text: str, words: List[str]) -> bool:
    for w in words:
        if re.search(r"\b" + re.escape(w), text):
            return True
    return False

def generate_seo(headline: str, body: str) -> str:
    combined = (headline + " " + body).lower()
    if has_word(combined, ["чорноморськ", "одес", "удар", "ринок", "загибл", "постражд"]):
        tags = ["#чорноморськ", "#одеса", "#обстріл", "#новиниукраїни", "#війна"]
        q = "Співчуття постраждалим та рідним загиблих. Бережіть себе! 👇"
    elif has_word(combined, ["світл", "електр", "блекаут", "дтек", "графік"]):
        tags = ["#відключеннясвітла", "#світло", "#блекаут", "#дтек", "#графіки"]
        q = "Як у вас зараз ситуація зі світлом? Чи дотримуються графіків у вашому місті? 👇"
    elif has_word(combined, ["патрон", "пес", "собак", "цуцен"]):
        tags = ["#песпатрон", "#патрон", "#собака", "#україна", "#тварини"]
        q = "Як вам така чудова новина? Діліться реакціями в коментарях 👇"
    else:
        tags = ["#терміново", "#важливо", "#новиниукраїни", "#резонанс"]
        q = "Яка ваша думка щодо цієї ситуації? Обговорюємо в коментарях 👇"

    rec_tags = ["#новини", "#україна", "#рек", "#рекомендації", "#хочуврек", "#тренди"]
    unique_tags = list(dict.fromkeys(tags + rec_tags))
    return f"{headline}!\n\n{q}\n\nПовні подробиці дивіться за посиланням у шапці профілю!\n\n{' '.join(unique_tags)}"

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
    clean = sanitize_text(raw_post)
    lines = [sanitize_text(l) for l in raw_post.split("\n") if len(sanitize_text(l)) > 3]

    if len(lines) > 1:
        headline = lines[0]
        other_lines = [l for l in lines[1:] if l.lower() != headline.lower()]
        body = ". ".join(other_lines) if other_lines else ""
    else:
        headline = clean
        body = ""

    cta = "Більше деталей дивіться в нашому Телеграм каналі за посиланням у шапці профілю."
    if body and body.lower() != headline.lower():
        voice = f"{headline}. {body}. {cta}"
    else:
        voice = f"{headline}. {cta}"

    return {
        "headline": sanitize_text(headline).upper(),
        "body": sanitize_text(body)[:220],
        "voiceover": sanitize_text(voice),
        "seo_desc": generate_seo(headline, body if body else headline)
    }

class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_p: Path, voice_name: str = "uk-UA-OstapNeural"):
        safe = sanitize_text(text)
        try:
            cmd = ["edge-tts", "--voice", voice_name, "--rate", "+6%", "--text", safe, "--write-media", str(out_p)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        except Exception:
            pass

        if not out_p.exists() or out_p.stat().st_size < 100:
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:beep_factor=4:duration=10", "-filter:a", "volume=0.2", str(out_p)]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return out_p, cls._dur(out_p)

    @classmethod
    def _dur(cls, p: Path) -> float:
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)]
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(r.stdout.strip())
        except Exception:
            return 12.0

def create_overlays(parsed: Dict, temp_dir: Path):
    font_p = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    font_badge = ImageFont.truetype(str(font_p), 26)
    font_head = ImageFont.truetype(str(font_p), 38)
    font_cta = ImageFont.truetype(str(font_p), 28)
    font_wm = ImageFont.truetype(str(font_p), 30)

    # 1. Верхня плашка новини в безпечній зоні Y=260
    top_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 520), (0, 0, 0, 0))
    t_draw = ImageDraw.Draw(top_bar)
    t_draw.rounded_rectangle([40, 260, 280, 320], radius=12, fill=(225, 25, 35, 255))
    t_draw.text((55, 272), "ТЕРМІНОВО", font=font_badge, fill=(255, 255, 255, 255))

    wm = Config.CHANNEL_DISPLAY_NAME
    wm_w = int(t_draw.textlength(wm, font=font_wm))
    t_draw.rounded_rectangle([Config.VIDEO_WIDTH - wm_w - 70, 260, Config.VIDEO_WIDTH - 40, 320], radius=12, fill=(120, 50, 210, 240), outline=(255, 255, 255, 200), width=2)
    t_draw.text((Config.VIDEO_WIDTH - wm_w - 55, 272), wm, font=font_wm, fill=(255, 255, 255, 255))

    h_lines = wrap_text_lines(parsed["headline"], font_head, Config.VIDEO_WIDTH - 80)
    cur_hy = 345
    for hl in h_lines[:2]:
        t_draw.text((40, cur_hy), hl, font=font_head, fill=(255, 255, 255, 255))
        cur_hy += 48
    t_draw.line([(40, cur_hy + 8), (Config.VIDEO_WIDTH - 40, cur_hy + 8)], fill=(255, 215, 0, 240), width=3)
    top_p = temp_dir / f"top_{int(time.time())}.png"
    top_bar.save(top_p)

    # 2. Нижня плашка CTA
    cta_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 160), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(cta_bar)
    c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 140], radius=20, fill=(18, 25, 38, 245), outline=(42, 171, 238, 255), width=2)
    c_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
    cw = c_draw.textlength(c_txt, font=font_cta)
    c_draw.text(((Config.VIDEO_WIDTH - cw)//2, 42), c_txt, font=font_cta, fill=(255, 255, 255, 255))
    c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(Config.CHANNEL_DISPLAY_NAME, font=font_badge))//2, 88), Config.CHANNEL_DISPLAY_NAME, font=font_badge, fill=(42, 171, 238, 255))
    cta_p = temp_dir / f"cta_{int(time.time())}.png"
    cta_bar.save(cta_p)

    return top_p, cta_p

def build_video_ffmpeg(audio_p: Path, media_p: Optional[Path], top_p: Path, cta_p: Path, duration: float, out_p: Path):
    is_video = False
    if media_p and media_p.exists():
        ext = media_p.suffix.lower()
        if ext in [".mp4", ".mov", ".avi", ".webm", ".mkv"]:
            is_video = True

    if is_video:
        # Живе відео: масштаб на 9:16 + швидкий розмитий фон
        filter_complex = (
            f"[1:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,scale=1080:1920,boxblur=15:3[bg];"
            f"[1:v]scale=1000:-1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2-20[v1];"
            f"[v1][2:v]overlay=0:0[v2];"
            f"[v2][3:v]overlay=0:1360[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_p),
            "-stream_loop", "-1", "-i", str(media_p),
            "-i", str(top_p),
            "-i", str(cta_p),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-threads", "2",
            "-c:a", "aac",
            str(out_p)
        ]
    elif media_p and media_p.exists():
        # Фото
        filter_complex = (
            f"[1:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,scale=1080:1920,boxblur=15:3[bg];"
            f"[1:v]scale=1000:-1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2-20[v1];"
            f"[v1][2:v]overlay=0:0[v2];"
            f"[v2][3:v]overlay=0:1360[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_p),
            "-loop", "1", "-i", str(media_p),
            "-i", str(top_p),
            "-i", str(cta_p),
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-threads", "2",
            "-c:a", "aac",
            str(out_p)
        ]
    else:
        # Фон за замовчуванням
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_p),
            "-f", "lavfi", "-i", f"color=c=0x0E1420:s=1080x1920:d={duration}",
            "-i", str(top_p),
            "-i", str(cta_p),
            "-filter_complex", "[1:v][2:v]overlay=0:0[v1];[v1][3:v]overlay=0:1360[vout]",
            "-map", "[vout]",
            "-map", "0:a",
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-threads", "2",
            "-c:a", "aac",
            str(out_p)
        ]

    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

app = FastAPI(title="News Studio Pro")

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
        .box { background: var(--card); border: 1px solid #232E42; border-radius: 20px; padding: 24px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        textarea { width: 100%; height: 140px; background: #0A0E17; border: 1px solid #232E42; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .voice-select { display: flex; gap: 15px; margin-bottom: 15px; background: #0A0E17; padding: 12px; border-radius: 10px; border: 1px solid #232E42; }
        .voice-label { font-size: 14px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; }
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
            <p style="color:#8E9BAE; font-size:14px;">Стабільне завантаження важких відеофайлів без 502 помилки</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини..."></textarea>
            
            <div class="voice-select">
                <span style="color:#8E9BAE; font-size:14px; margin-right:10px;">Голос диктора:</span>
                <label class="voice-label"><input type="radio" name="voice" value="uk-UA-OstapNeural" checked> Чоловічий (Остап)</label>
                <label class="voice-label"><input type="radio" name="voice" value="uk-UA-PolinaNeural"> Жіночий (Поліна)</label>
            </div>

            <div class="drop" onclick="document.getElementById('mFile').click()">
                📹 <b>Додайте ВІДЕО або фото з новини</b> (надійна підтримка будь-яких назв файлів)
                <input type="file" id="mFile" accept="video/*,image/*" style="display:none;" onchange="showF(this)">
                <div id="mTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="gen()">🚀 Змонтувати чисте відео</button>
            <div id="st">⏳ Монтаж живого відео... (15-20 сек)</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>

                <div class="seo-box">
                    <div class="seo-title">
                        <span>🔥 Опис та прораховані хештеги під рекомендації:</span>
                        <button class="copy-btn" onclick="copySeo()">📋 Скопіювати все</button>
                    </div>
                    <div class="seo-text" id="seoContent"></div>
                </div>

                <div class="social-title">🚀 Завантажити та опублікувати:</div>
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
                document.getElementById('mTxt').innerText = '✓ Обрано файл: ' + selectedFile.name;
            }
        }
        async function gen() {
            const btn = document.getElementById('btn');
            const st = document.getElementById('st');
            const box = document.getElementById('resBox');
            const vid = document.getElementById('vPlay');
            const txt = document.getElementById('pTxt').value;
            const voice = document.querySelector('input[name="voice"]:checked').value;

            btn.disabled = true;
            st.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', txt);
                fd.append('voice', voice);
                if(selectedFile) {
                    fd.append('media_file', selectedFile);
                }
                const res = await fetch('/api/generate', { method: 'POST', body: fd });
                if (!res.ok) {
                    throw new Error("Сервер не зміг обробити файл (код " + res.status + ")");
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
async def api_generate(
    text: Optional[str] = Form(None),
    voice: Optional[str] = Form("uk-UA-OstapNeural"),
    media_file: Optional[UploadFile] = File(None)
):
    if not text or not text.strip():
        text = "У Чорноморську троє загиблих через удар по ринку. Повідомили в ОВА."

    parsed = parse_post(text)

    saved_media = None
    if media_file and media_file.filename:
        ext = Path(media_file.filename).suffix.lower()
        if not ext:
            ext = ".mp4"
        # Безпечне збереження файлу на диск частинами
        saved_media = Config.TEMP_DIR / f"upload_{int(time.time())}{ext}"
        with open(saved_media, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)

    temp_audio = Config.TEMP_DIR / f"v_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio, voice)

    top_p, cta_p = create_overlays(parsed, Config.TEMP_DIR)
    out_file = Config.OUTPUT_DIR / f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

    build_video_ffmpeg(audio_path, saved_media, top_p, cta_p, duration, out_file)

    for p in [temp_audio, saved_media, top_p, cta_p]:
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
