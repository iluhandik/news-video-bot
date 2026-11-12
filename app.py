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
from moviepy import VideoClip, AudioFileClip, VideoFileClip

class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_USERNAME = "@kropivnit"
    VOICE_NAME = "uk-UA-PolinaNeural"
    VOICE_RATE = "+8%"
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 25
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

def get_adaptive_cta(combined_text: str, mode: str) -> Dict[str, str]:
    """Підбирає логічний заклик та готовий коментар під КОНКРЕТНУ тему новини"""
    t = combined_text.lower()

    if has_word(t, ["світл", "електр", "блекаут", "дтек", "графік"]):
        if mode == "bait":
            voice_cta = "Але точний графік відключень для вашої області та коли повернуть світло, дивіться у нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"
            comment = "⚡ Повний графік відключень по кожній області вже опублікували в нашому Telegram 👉 NEWS УКРАЇНА 365 (посилання в шапці профілю)"
        else:
            voice_cta = "Оперативні графіки та новини енергетики дивіться в нашому Телеграм каналі Ньюз Україна 365 за посиланням у шапці профілю!"
            comment = "💡 Слідкувати за оновленнями графіків по вашому місту можна в нашому Telegram: NEWS УКРАЇНА 365 (в шапці профілю)"

    elif has_word(t, ["путін", "анекдот", "переговор", "трамп", "зеленськ", "янукович"]):
        if mode == "bait":
            voice_cta = "А що саме сталося далі та повне відео без цензури і вирізок ми вже виклали в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"
            comment = "🔥 Повне відео без вирізок та реакцію вже закинули в Telegram 👉 NEWS УКРАЇНА 365 (посилання закріплено в шапці)"
        else:
            voice_cta = "Повне відео виступу та головні заяви дивіться в нашому Телеграм каналі Ньюз Україна 365 в шапці профілю!"
            comment = "👇 Усі подробиці та повний розбір заяви вже в нашому Telegram: NEWS УКРАЇНА 365 (посилання в шапці)"

    elif has_word(t, ["обстріл", "удар", "ракета", "шахед", "приліт", "ринок", "вибух"]):
        if mode == "bait":
            voice_cta = "Але кадри моменту влучання та перші деталі з місця події, які блокує Тік Ток, вже в нашому Телеграм каналі Ньюз Україна 365 в шапці профілю!"
            comment = "🚨 Кадри без цензури та оперативні деталі з місця подій вже в Telegram 👉 NEWS УКРАЇНА 365 (шукайте в шапці профілю)"
        else:
            voice_cta = "Оперативну ситуацію та кадри з місця подій дивіться в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"
            comment = "⚠️ Усі оперативні новини та відео без блюру в нашому Telegram: NEWS УКРАЇНА 365 (в шапці профілю)"

    elif has_word(t, ["закон", "штраф", "подат", "пенсі", "виплат", "тариф", "дорог"]):
        if mode == "bait":
            voice_cta = "Але точний розрахунок сум та кого саме торкнуться зміни, ми вже виклали в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"
            comment = "📌 Повний перелік змін, сум та кого це торкнеться вже в Telegram 👉 NEWS УКРАЇНА 365 (посилання в шапці)"
        else:
            voice_cta = "Усі подробиці нового рішення дивіться в нашому Телеграм каналі Ньюз Україна 365 за посиланням у шапці профілю!"
            comment = "👇 Повний текст рішення та роз'яснення вже в нашому Telegram: NEWS УКРАЇНА 365 (в шапці профілю)"

    else:
        if mode == "bait":
            voice_cta = "Але повне відео та всі деталі, які видаляє Тік Ток, ми вже виклали в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"
            comment = "🔥 Повне відео без цензури та всі деталі вже виклали в Telegram 👉 NEWS УКРАЇНА 365 (посилання в шапці профілю)"
        else:
            voice_cta = "Більше ексклюзивних новин дивіться в нашому Телеграм каналі Ньюз Україна 365 за посиланням у шапці профілю!"
            comment = "👉 Повні новини та відео без затримок у нашому Telegram: NEWS УКРАЇНА 365 (посилання в шапці)"

    return {"voice_cta": voice_cta, "comment": comment}

def generate_seo(headline: str, body: str, mode: str) -> str:
    combined = (headline + " " + body).lower()
    if has_word(combined, ["путін", "анекдот", "переговор", "трамп", "зеленськ"]):
        tags = ["#переговори", "#політика", "#новинисвіту", "#путін", "#україна"]
        q = "Що думаєте про такі заяви? Пишіть у коментарях 👇"
    elif has_word(combined, ["чорноморськ", "одес", "удар", "ринок", "загибл"]):
        tags = ["#чорноморськ", "#одеса", "#обстріл", "#новиниукраїни", "#війна"]
        q = "Повне відео без блюру та деталі вже в нашому ТГ (посилання в шапці) 👇"
    elif has_word(combined, ["світл", "електр", "блекаут", "дтек", "графік"]):
        tags = ["#відключеннясвітла", "#світло", "#блекаут", "#дтек", "#графіки"]
        q = "Повний графік по кожному району вже в нашому ТГ в шапці профілю! 👇"
    else:
        tags = ["#терміново", "#важливо", "#новиниукраїни", "#резонанс"]
        q = "Повні кадри та деталі, які видаляє ТікТок, вже у нашому ТГ в шапці профілю 👇"

    rec_tags = ["#новини", "#україна", "#рек", "#рекомендації", "#хочуврек", "#тренди"]
    unique_tags = list(dict.fromkeys(tags + rec_tags))
    return f"{headline}!\n\n{q}\n\n🔎 Знайти в Telegram: NEWS УКРАЇНА 365\n\n{' '.join(unique_tags)}"

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

def parse_post(raw_post: str, mode: str = "full") -> Dict[str, str]:
    clean = sanitize_text(raw_post)
    lines = [sanitize_text(l) for l in raw_post.split("\n") if len(sanitize_text(l)) > 3]

    if len(lines) > 1:
        headline = lines[0]
        other_lines = [l for l in lines[1:] if l.lower() != headline.lower()]
        full_body = ". ".join(other_lines) if other_lines else ""
    else:
        headline = clean
        full_body = ""

    combined_for_cta = f"{headline} {full_body}"
    adaptive = get_adaptive_cta(combined_for_cta, mode)
    cta = adaptive["voice_cta"]

    if mode == "bait":
        teaser = other_lines[0] if (len(lines) > 1 and other_lines) else ""
        if teaser and teaser.lower() != headline.lower():
            voice = f"{headline}. {teaser}. {cta}"
        else:
            voice = f"{headline}. {cta}"
        display_body = teaser
    else:
        if full_body and full_body.lower() != headline.lower():
            voice = f"{headline}. {full_body}. {cta}"
        else:
            voice = f"{headline}. {cta}"
        display_body = full_body

    return {
        "headline": sanitize_text(headline).upper(),
        "body": sanitize_text(display_body)[:220],
        "voiceover": sanitize_text(voice),
        "seo_desc": generate_seo(headline, display_body if display_body else headline, mode),
        "ready_comment": adaptive["comment"],
        "mode": mode
    }

class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_p: Path, voice_name: str = "uk-UA-PolinaNeural"):
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

    @classmethod
    def chunks(cls, text: str, dur: float):
        # Автоматично замінюємо транскрипцію 'ньюз' назад на 'NEWS' у субтитрах!
        clean_words = sanitize_text(text).split()
        display_words = ["NEWS" if w.lower() == "ньюз" else w for w in clean_words]

        chunks = [" ".join(display_words[i:i+2]) for i in range(0, len(display_words), 2)]
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
        up = sanitize_text(text).upper()

        font_size = 64
        font = ImageFont.truetype(self.font_path, font_size)
        while draw.textlength(up, font=font) > (w - 60) and font_size > 34:
            font_size -= 4
            font = ImageFont.truetype(self.font_path, font_size)

        tw = draw.textlength(up, font=font)
        tx = max(20, (w - tw) // 2)
        ty = (h - font_size) // 2

        for dx in range(-6, 7):
            for dy in range(-6, 7):
                if dx*dx + dy*dy <= 36:
                    draw.text((tx+dx, ty+dy), up, font=font, fill=(0, 0, 0, 255))
        draw.text((tx, ty), up, font=font, fill=(255, 220, 10, 255))
        return img

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, media_path: Optional[Path] = None):
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        user_video_clip = None
        prepared_img = None

        if media_path and media_path.exists():
            ext = media_path.suffix.lower()
            if ext in [".mp4", ".mov", ".webm", ".avi", ".mkv"]:
                try:
                    user_video_clip = VideoFileClip(str(media_path))
                except Exception:
                    user_video_clip = None
            else:
                try:
                    im = Image.open(media_path).convert("RGB")
                    ow, oh = im.size
                    tr = Config.VIDEO_WIDTH / Config.VIDEO_HEIGHT
                    if ow / oh > tr:
                        nw = int(oh * tr)
                        c_box = ((ow - nw)//2, 0, (ow + nw)//2, oh)
                    else:
                        nh = int(ow / tr)
                        c_box = (0, (oh - nh)//2, ow, (oh + nh)//2)
                    im_crop = im.crop(c_box).resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))
                    dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, 110))
                    im_crop.paste(dim, (0, 0), dim)
                    prepared_img = im_crop
                except Exception:
                    prepared_img = None

        if not user_video_clip and not prepared_img:
            bg_default = Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (16, 22, 34))
            prepared_img = bg_default

        top_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 540), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(top_bar)
        t_draw.rectangle([0, 220, Config.VIDEO_WIDTH, 520], fill=(5, 8, 14, 180))

        t_draw.rounded_rectangle([40, 260, 280, 320], radius=12, fill=(225, 25, 35, 255))
        t_draw.text((55, 272), "ТЕРМІНОВО", font=self.font_badge, fill=(255, 255, 255, 255))

        wm = Config.CHANNEL_DISPLAY_NAME
        wm_w = int(t_draw.textlength(wm, font=self.font_watermark))
        t_draw.rounded_rectangle([Config.VIDEO_WIDTH - wm_w - 70, 260, Config.VIDEO_WIDTH - 40, 320], radius=12, fill=(120, 50, 210, 240), outline=(255, 255, 255, 200), width=2)
        t_draw.text((Config.VIDEO_WIDTH - wm_w - 55, 272), wm, font=self.font_watermark, fill=(255, 255, 255, 255))

        clean_headline = sanitize_text(parsed["headline"])
        h_lines = wrap_text_lines(clean_headline, self.font_head, Config.VIDEO_WIDTH - 80)
        cur_hy = 345
        for hl in h_lines[:2]:
            t_draw.text((40, cur_hy), hl, font=self.font_head, fill=(255, 255, 255, 255))
            cur_hy += 48
        t_draw.line([(40, cur_hy + 8), (Config.VIDEO_WIDTH - 40, cur_hy + 8)], fill=(255, 215, 0, 240), width=3)

        cta_bar = Image.new("RGBA", (Config.VIDEO_WIDTH, 160), (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cta_bar)

        if parsed["mode"] == "bait":
            c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 140], radius=20, fill=(200, 25, 35, 245), outline=(255, 215, 0, 255), width=3)
            c_txt = "ПОВНЕ ВІДЕО БЕЗ ЦЕНЗУРИ В ШАПЦІ ПРОФІЛЮ ➔"
            sub_col = (255, 245, 180, 255)
        else:
            c_draw.rounded_rectangle([40, 20, Config.VIDEO_WIDTH - 40, 140], radius=20, fill=(18, 25, 38, 245), outline=(42, 171, 238, 255), width=2)
            c_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
            sub_col = (42, 171, 238, 255)

        cw = c_draw.textlength(c_txt, font=self.font_cta)
        c_draw.text(((Config.VIDEO_WIDTH - cw)//2, 42), c_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        sub_t = f"Telegram: {Config.CHANNEL_DISPLAY_NAME}"
        c_draw.text(((Config.VIDEO_WIDTH - c_draw.textlength(sub_t, font=self.font_badge))//2, 88), sub_t, font=self.font_badge, fill=sub_col)

        sub_cache = {e["text"]: self._render_sub(e["text"]) for e in sub_events}

        def make_frame(t):
            if user_video_clip:
                loop_t = t % user_video_clip.duration
                raw_frame = user_video_clip.get_frame(loop_t)
                v_img = Image.fromarray(raw_frame)
                
                small = v_img.resize((270, 480))
                bg_v = small.resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), Image.BILINEAR)
                dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, 120))
                bg_v.paste(dim, (0, 0), dim)
                frame = bg_v.convert("RGBA")

                vw, vh = v_img.size
                target_w = 1000
                target_h = int(vh * (target_w / vw))
                sharp_v = v_img.resize((target_w, target_h))
                center_y = (Config.VIDEO_HEIGHT - target_h) // 2 - 20
                frame.paste(sharp_v, ((Config.VIDEO_WIDTH - target_w)//2, center_y))
            else:
                zoom = 1.0 + 0.03 * (t / max(1.0, duration))
                zw, zh = int(Config.VIDEO_WIDTH * zoom), int(Config.VIDEO_HEIGHT * zoom)
                z_img = prepared_img.resize((zw, zh))
                frame = z_img.crop(((zw - Config.VIDEO_WIDTH)//2, (zh - Config.VIDEO_HEIGHT)//2, (zw + Config.VIDEO_WIDTH)//2, (zh + Config.VIDEO_HEIGHT)//2)).convert("RGBA")

            frame.alpha_composite(top_bar, (0, 0))

            for e in sub_events:
                if e["start"] <= t <= e["end"]:
                    s = sub_cache.get(e["text"])
                    if s:
                        frame.alpha_composite(s, ((Config.VIDEO_WIDTH - s.width)//2, 1080))
                    break

            frame.alpha_composite(cta_bar, (0, 1360))
            return np.array(frame.convert("RGB"))

        clip = VideoClip(make_frame, duration=duration).with_audio(audio_clip)
        clip.write_videofile(str(out_file), fps=Config.VIDEO_FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)
        audio_clip.close()
        clip.close()
        if user_video_clip:
            user_video_clip.close()
        return out_file

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
        :root { --bg: #070A11; --card: #131A26; --accent: #2AABEE; --gold: #FFD233; --green: #2ED573; --red: #FF3B30; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 850px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid #232E42; border-radius: 20px; padding: 24px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        textarea { width: 100%; height: 140px; background: #0A0E17; border: 1px solid #232E42; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .select-row { display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 14px; background: #0A0E17; padding: 12px 16px; border-radius: 12px; border: 1px solid #232E42; align-items: center; }
        .select-label { font-size: 14px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; }
        .drop { border: 2px dashed #2AABEE; border-radius: 12px; padding: 16px; text-align: center; cursor: pointer; color: #fff; font-size: 14px; margin-bottom: 14px; background: rgba(42, 171, 238, 0.05); }
        .btn-go { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 14px; font-weight: 700; }
        .res { margin-top: 25px; display: none; }
        video { width: 100%; max-height: 500px; border-radius: 14px; background: #000; border: 1px solid #232E42; }
        
        .seo-box { background: #0A0E17; border: 1px solid #232E42; border-radius: 14px; padding: 16px; margin-top: 15px; }
        .seo-title { font-size: 14px; font-weight: 800; color: var(--gold); margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
        .copy-btn { background: rgba(255,255,255,0.08); border: 1px solid #232E42; color: #fff; padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; }
        .copy-btn:hover { background: rgba(255,255,255,0.18); }
        .seo-text { font-size: 13px; color: #C5D1E0; white-space: pre-wrap; line-height: 1.5; }

        .reply-item { display: flex; justify-content: space-between; align-items: center; gap: 10px; background: rgba(255,255,255,0.04); padding: 10px 12px; border-radius: 10px; margin-bottom: 8px; border: 1px solid rgba(255,255,255,0.06); }
        .reply-text { font-size: 13px; color: #D5E0F0; line-height: 1.4; }

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
            <p style="color:#8E9BAE; font-size:14px;">Адаптивний перелив, правильний титр NEWS та вікно коментаря</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини..."></textarea>
            
            <div class="select-row" style="border-color: rgba(255, 59, 48, 0.4);">
                <span style="color:#FFD233; font-size:14px;">Формат ролика:</span>
                <label class="select-label"><input type="radio" name="mode" value="full" checked> 📰 Повна новина</label>
                <label class="select-label" style="color:#FF6B6B;"><input type="radio" name="mode" value="bait"> 🔥 100% Перелив у ТГ</label>
            </div>

            <div class="select-row">
                <span style="color:#8E9BAE; font-size:14px;">Голос диктора:</span>
                <label class="select-label"><input type="radio" name="voice" value="uk-UA-PolinaNeural" checked> Жіночий (Поліна)</label>
                <label class="select-label"><input type="radio" name="voice" value="uk-UA-OstapNeural"> Чоловічий (Остап)</label>
            </div>

            <div class="drop" onclick="document.getElementById('mFile').click()">
                📹 <b>Додайте ВІДЕО або фото з новини</b> (живе відео програватиметься в динаміці)
                <input type="file" id="mFile" accept="video/*,image/*" style="display:none;" onchange="showF(this)">
                <div id="mTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="gen()">🚀 Змонтувати відео</button>
            <div id="st">⏳ Адаптація сценарію, монтаж відео та генерація коментаря... (20-30 сек)</div>

            <div class="res" id="resBox">
                <video id="vPlay" controls></video>

                <!-- Блок 1: Опис і хештеги -->
                <div class="seo-box">
                    <div class="seo-title">
                        <span>🔥 Опис та хештеги під рекомендації:</span>
                        <button class="copy-btn" onclick="copyText('seoContent')">📋 Копіювати</button>
                    </div>
                    <div class="seo-text" id="seoContent"></div>
                </div>

                <!-- Блок 2: Адаптивний коментар під це відео -->
                <div class="seo-box" style="border-color: rgba(42, 171, 238, 0.5);">
                    <div class="seo-title" style="color:#2AABEE;">
                        <span>💬 Готовий коментар під ЦЕ відео (закріпи під постом):</span>
                        <button class="copy-btn" onclick="copyText('readyComment')">📋 Копіювати коментар</button>
                    </div>
                    <div class="seo-text" id="readyComment" style="color:#fff; font-weight:bold;"></div>
                </div>

                <!-- Блок 3: Шаблон для ЛС -->
                <div class="seo-box">
                    <div class="seo-title">
                        <span>📩 Шаблон для автовідповіді в ЛС (TikTok Business):</span>
                        <button class="copy-btn" onclick="copyText('dmTemplate')">📋 Копіювати для ЛС</button>
                    </div>
                    <div class="seo-text" id="dmTemplate">Вітаємо! Дякуємо за підписку 🙏 Всі головні новини без цензури та оперативно публікуємо тут: https://t.me/kropivnit</div>
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
            const mode = document.querySelector('input[name="mode"]:checked').value;

            btn.disabled = true;
            st.style.display = 'block';

            try {
                const fd = new FormData();
                fd.append('text', txt);
                fd.append('voice', voice);
                fd.append('mode', mode);
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
                    document.getElementById('seoContent').innerText = d.seo_desc;
                    document.getElementById('readyComment').innerText = d.ready_comment;
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
        function copyText(elementId) {
            const txt = document.getElementById(elementId).innerText;
            navigator.clipboard.writeText(txt);
            alert("✓ Скопійовано в буфер обміну!");
        }
    </script>
</body>
</html>"""

@app.post("/api/generate")
async def api_generate(
    text: Optional[str] = Form(None),
    voice: Optional[str] = Form("uk-UA-PolinaNeural"),
    mode: Optional[str] = Form("full"),
    media_file: Optional[UploadFile] = File(None)
):
    if not text or not text.strip():
        text = "У Чорноморську троє загиблих через удар по ринку. Повідомили в ОВА."

    parsed = parse_post(text, mode)

    saved_media = None
    if media_file and media_file.filename:
        ext = Path(media_file.filename).suffix.lower()
        if not ext:
            ext = ".mp4"
        saved_media = Config.TEMP_DIR / f"upload_{int(time.time())}{ext}"
        with open(saved_media, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)

    temp_audio = Config.TEMP_DIR / f"v_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio, voice)
    sub_events = TTSEngine.chunks(parsed["voiceover"], duration)

    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    engine.render(parsed, audio_path, sub_events, out_file, saved_media)

    for p in [temp_audio, saved_media]:
        if p and p.exists():
            try: p.unlink()
            except Exception: pass

    return {
        "video_url": f"/videos/{out_file.name}",
        "seo_desc": parsed["seo_desc"],
        "ready_comment": parsed["ready_comment"]
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
