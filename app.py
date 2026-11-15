import os
import re
import gc
import time
import uuid
import random
import shutil
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# =============================================================
# КОНФІГ
# =============================================================
class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_BAIT_WATERMARK = "NEWS УКРАЇНА 365 | ЕКСКЛЮЗИВ"
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 25
    MAX_UPLOAD_MB = 250
    JOB_TTL_SECONDS = 3600
    VIDEO_TTL_SECONDS = 86400
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"
    WATERMARK_PATH = BASE_DIR / "logo.png"  # Фотермарка

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

JOBS: Dict[str, Dict] = {}
JOBS_LOCK = threading.Lock()

# Перевірка залежностей
HAS_FFMPEG = shutil.which("ffmpeg") is not None
HAS_FFPROBE = shutil.which("ffprobe") is not None
HAS_EDGE_TTS = shutil.which("edge-tts") is not None

# =============================================================
# ШРИФТИ
# =============================================================
_FONT_CACHE: Dict[int, ImageFont.FreeTypeFont] = {}

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\segoeuib.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                f = ImageFont.truetype(path, size)
                _FONT_CACHE[size] = f
                return f
            except Exception:
                continue
    try:
        f = ImageFont.load_default(size=size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f

# =============================================================
# УТИЛІТИ ТЕКСТУ
# =============================================================
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
    "]+", flags=re.UNICODE
)

def sanitize_text(text: str) -> str:
    if not text: return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"t\.me/\S+", " ", text)
    text = re.sub(r"@[a-zA-Z0-9_]+", " ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = re.sub(r"[⚡🔥👉👇⚠️🚨✔✓➔➡•—–«»#*_=~`]", " ", text)
    text = re.sub(r"(\d+)-([а-яА-ЯіїєґІЇЄҐ]+)", r"\1 \2", text)
    text = text.replace("-", " ")
    text = re.sub(r"\.{2,}", ".", text)
    return re.sub(r"\s+", " ", text).strip()

def has_word(text: str, words: List[str]) -> bool:
    t = text.lower()
    return any(re.search(r"\b" + re.escape(w), t) for w in words)

# =============================================================
# CTA ТА SEO
# =============================================================
def get_adaptive_cta(combined: str, mode: str) -> Dict[str, str]:
    t = combined.lower()
    bait = (mode == "bait")
    rules = [
        (["тцк", "мобілізац", "повістк"],
         ("Але що сталося далі, повне відео конфлікту та офіційну реакцію ми вже виклали в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!",
          "Усі подробиці інциденту, відео з місця та реакцію дивіться в нашому Телеграм каналі Ньюз Україна 365 за посиланням у шапці профілю!"),
         ("🚨 Повне відео інциденту без цензури та офіційна реакція вже в Telegram 👉 NEWS УКРАЇНА 365 (посилання в шапці)",
          "👇 Усі деталі події та коментарі очевидців вже в нашому Telegram: NEWS УКРАЇНА 365 (в шапці)")),
        (["відключен", "блекаут", "дтек", "графік"],
         ("Але точний графік відключень для вашої області та коли повернуть світло, дивіться у нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!",
          "Оперативні графіки та новини енергетики дивіться в нашому Телеграм каналі Ньюз Україна 365 за посиланням у шапці профілю!"),
         ("⚡ Повний графік відключень по кожній області вже опублікували в нашому Telegram 👉 NEWS УКРАЇНА 365",
          "💡 Слідкувати за оновленнями графіків по вашому місту можна в нашому Telegram: NEWS УКРАЇНА 365")),
        (["обстріл", "удар", "ракета", "шахед", "вибух"],
         ("Але кадри моменту влучання та перші деталі з місця події, які блокує Тік Ток, вже в нашому Телеграм каналі Ньюз Україна 365 в шапці профілю!",
          "Оперативну ситуацію та кадри з місця подій дивіться в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"),
         ("🚨 Кадри без цензури та оперативні деталі з місця подій вже в Telegram 👉 NEWS УКРАЇНА 365",
          "⚠️ Усі оперативні новини та відео без блюру в нашому Telegram: NEWS УКРАЇНА 365")),
    ]
    for triggers, voice_pair, comment_pair in rules:
        if has_word(t, triggers):
            return {"voice_cta": voice_pair[0] if bait else voice_pair[1],
                    "comment": comment_pair[0] if bait else comment_pair[1]}
    return {
        "voice_cta": ("Але повне відео та всі деталі, які видаляє Тік Ток, ми вже виклали в нашому Телеграм каналі Ньюз Україна 365 у шапці профілю!"
                      if bait else "Більше ексклюзивних новин дивіться в нашому Телеграм каналі Ньюз Україна 365 за посиланням у шапці профілю!"),
        "comment": ("🔥 Повне відео без цензури та всі деталі вже виклали в Telegram 👉 NEWS УКРАЇНА 365"
                    if bait else "👉 Повні новини та відео без затримок у нашому Telegram: NEWS УКРАЇНА 365")
    }

def generate_seo(headline: str, body: str, mode: str) -> str:
    combined = (headline + " " + body).lower()
    bait = (mode == "bait")
    tags = ["#новини", "#україна", "#рек", "#рекомендації", "#тренди"]
    q = ("Повні кадри та деталі вже у нашому ТГ в шапці профілю 👇"
         if bait else "Яка ваша думка щодо цієї новини? Обговорюємо в коментарях 👇")
    if has_word(combined, ["тцк", "мобілізац"]):
        tags = ["#тцк", "#мобілізація", "#скандал", "#новиниукраїни"] + tags
    elif has_word(combined, ["обстріл", "удар", "вибух"]):
        tags = ["#обстріл", "#новиниукраїни", "#війна", "#рятувальники"] + tags
    if bait: tags.append("#ексклюзив")
    return f"{headline}\n\n{q}\n\n🔎 Більше новин: t.me/kropivnit\n\n{' '.join(list(dict.fromkeys(tags)))}"

# =============================================================
# ПАРСЕР ПОСТА
# =============================================================
_dummy_img = Image.new("RGBA", (1, 1))
_dummy_draw = ImageDraw.Draw(_dummy_img)

def wrap_text_lines(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> List[str]:
    if not text or not text.strip(): return [""]
    words, lines, cur = text.split(), [], []
    for w in words:
        test = " ".join(cur + [w])
        if _dummy_draw.textlength(test, font=font) <= max_w:
            cur.append(w)
        else:
            if cur: lines.append(" ".join(cur))
            cur = [w]
    if cur: lines.append(" ".join(cur))
    return lines

def parse_post(raw_post: str, mode: str = "full") -> Dict[str, str]:
    lines = [sanitize_text(l) for l in raw_post.split("\n") if sanitize_text(l)]
    if len(lines) > 1:
        headline = lines[0]
        others = [l for l in lines[1:] if l.lower() != headline.lower()]
        full_body = ". ".join(others)
    else:
        headline = lines[0] if lines else "ТЕРМІНОВА НОВИНА"
        others, full_body = [], ""

    adaptive = get_adaptive_cta(f"{headline} {full_body}", mode)
    cta = adaptive["voice_cta"]
    if mode == "bait":
        teaser = others[0] if others else ""
        voice = (f"{headline}. {teaser}. {cta}" if teaser else f"{headline}. {cta}")
        display_body = teaser
    else:
        voice = (f"{headline}. {full_body}. {cta}" if full_body else f"{headline}. {cta}")
        display_body = full_body

    return {
        "headline": sanitize_text(headline).upper(),
        "body": sanitize_text(display_body)[:220],
        "voiceover": sanitize_text(voice)[:2500],
        "seo_desc": generate_seo(headline, display_body or headline, mode),
        "ready_comment": adaptive["comment"],
        "mode": mode,
    }

# =============================================================
# ОЗВУЧКА (EDGE-TTS)
# =============================================================
class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_audio: Path, voice: str, out_vtt: Optional[Path] = None) -> Tuple[Path, float, Optional[Path]]:
        if not HAS_EDGE_TTS: raise RuntimeError("edge-tts не встановлено")
        safe = sanitize_text(text)[:3000]
        if not safe.strip(): raise RuntimeError("Порожній текст")
        
        cmd = ["edge-tts", "--voice", voice, "--rate", "+6%", "--text", safe, "--write-media", str(out_audio)]
        if out_vtt: cmd += ["--write-subtitles", str(out_vtt)]
        
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0: raise RuntimeError(f"TTS помилка: {r.stderr[:200]}")
        
        duration = cls._duration(out_audio)
        return out_audio, duration, (out_vtt if out_vtt and out_vtt.exists() else None)

    @classmethod
    def _duration(cls, p: Path) -> float:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)], capture_output=True, text=True, timeout=10)
            return float(r.stdout.strip())
        except Exception: return 10.0

    @classmethod
    def parse_vtt(cls, vtt_path: Path) -> List[Dict]:
        events = []
        try: content = vtt_path.read_text(encoding="utf-8")
        except Exception: return events
        for block in content.split("\n\n"):
            lines = [l.strip() for l in block.strip().split("\n") if l.strip() and not l.startswith("WEBVTT")]
            if not lines: continue
            for i, line in enumerate(lines):
                m = re.match(r"(\d+):(\d+):(\d+)\.(\d+)\s*-->\s*(\d+):(\d+):(\d+)\.(\d+)", line)
                if m:
                    start = int(m[1])*3600 + int(m[2])*60 + int(m[3]) + int(m[4])/1000
                    end = int(m[5])*3600 + int(m[6])*60 + int(m[7]) + int(m[8])/1000
                    txt = " ".join(lines[i+1:])
                    if txt.strip(): events.append({"start": start, "end": end, "text": txt})
                    break
        return events

def _fmt_ass_time(sec: float) -> str:
    return f"{int(sec // 3600)}:{int((sec % 3600) // 60):02d}:{int(sec % 60):02d}.{int((sec - int(sec)) * 100):02d}"

# =============================================================
# ВІДЕО-ДВИЖОК
# =============================================================
class VideoEngine:
    def __init__(self):
        self.font_badge = _load_font(28)
        self.font_head = _load_font(44)
        self.font_cta = _load_font(32)
        self.font_small = _load_font(24)

    def _build_overlay(self, parsed: Dict, out_png: Path, is_bait: bool):
        W, H = Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        accent = (255, 60, 80) if is_bait else (42, 171, 238)
        accent_soft = (255, 165, 0) if is_bait else (100, 200, 255)

        # Верхня акцентна лінія
        d.rectangle([0, 0, W, 10], fill=accent)

        # Бейдж зліва
        badge_text = "ЕКСКЛЮЗИВ" if is_bait else "ТЕРМІНОВО"
        badge_fill = (255, 165, 0) if is_bait else (225, 25, 35)
        badge_fg = (0, 0, 0) if is_bait else (255, 255, 255)
        bw = int(d.textlength(badge_text, font=self.font_badge)) + 50
        d.rounded_rectangle([40, 100, 40+bw, 160], radius=30, fill=badge_fill, outline=(255,255,255,50), width=1)
        d.text((65, 116), badge_text, font=self.font_badge, fill=badge_fg)

        # Водяний знак (Фотермарка)
        if Config.WATERMARK_PATH.exists():
            try:
                with Image.open(Config.WATERMARK_PATH) as wm:
                    wm = wm.convert("RGBA")
                    ratio = 320 / wm.width
                    wm = wm.resize((320, int(wm.height * ratio)), Image.Resampling.LANCZOS)
                    
                    shadow = Image.new("RGBA", wm.size, (0,0,0,0))
                    shadow_d = ImageDraw.Draw(shadow)
                    shadow_d.rectangle([0,0,wm.width,wm.height], fill=(0,0,0,100))
                    
                    wm_x = W - wm.width - 40
                    wm_y = 80
                    overlay.paste(shadow, (wm_x+4, wm_y+4), shadow)
                    overlay.paste(wm, (wm_x, wm_y), wm)
            except Exception as e:
                print(f"Watermark error: {e}")
        else:
            wm = Config.CHANNEL_BAIT_WATERMARK if is_bait else Config.CHANNEL_DISPLAY_NAME
            wm_w = int(d.textlength(wm, font=self.font_small))
            d.rounded_rectangle([W - wm_w - 90, 100, W - 40, 160], radius=14, fill=(15, 22, 35, 230), outline=accent_soft, width=2)
            d.text((W - wm_w - 65, 118), wm, font=self.font_small, fill=(255, 255, 255))

        # Панель із заголовком
        panel_y = 260
        d.rectangle([0, panel_y, W, panel_y + 380], fill=(5, 8, 14, 210))

        headline_clean = sanitize_text(parsed["headline"]) or ("ЕКСКЛЮЗИВ" if is_bait else "ТЕРМІНОВА НОВИНА")
        h_lines = wrap_text_lines(headline_clean, self.font_head, W - 80)
        hy = panel_y + 45
        for hl in h_lines[:3]:
            d.text((44, hy+4), hl, font=self.font_head, fill=(0, 0, 0, 180))
            d.text((40, hy), hl, font=self.font_head, fill=(255, 255, 255))
            hy += 62

        d.rectangle([40, hy + 15, 40 + 180, hy + 22], fill=accent)

        # CTA-кнопка
        cta_y = 1480
        if is_bait:
            d.rounded_rectangle([40, cta_y, W-40, cta_y+200], radius=28, fill=(180, 20, 30, 250), outline=(255, 215, 0), width=6)
            cta_l1, cta_l2, cta_col = "ПОВНЕ ВІДЕО БЕЗ ЦЕНЗУРИ", "В ШАПЦІ ПРОФІЛЮ  ➔", (255, 235, 100)
        else:
            d.rounded_rectangle([40, cta_y, W-40, cta_y+200], radius=28, fill=(12, 20, 34, 250), outline=accent, width=4)
            cta_l1, cta_l2, cta_col = "ПОВНІ ДЕТАЛІ В ТЕЛЕГРАМ", "t.me/kropivnit  ➔", accent

        cw = d.textlength(cta_l1, font=self.font_cta)
        d.text(((W - cw) // 2, cta_y + 40), cta_l1, font=self.font_cta, fill=(255, 255, 255))
        sw = d.textlength(cta_l2, font=self.font_badge)
        d.text(((W - sw) // 2, cta_y + 120), cta_l2, font=self.font_badge, fill=cta_col)

        # Брендинг знизу
        d.rectangle([0, H - 40, W, H - 36], fill=accent)
        d.text((40, H - 34), f"© {Config.CHANNEL_DISPLAY_NAME}", font=self.font_small, fill=(160, 170, 190))

        overlay.save(out_png, "PNG")

    def _build_ass(self, sub_events: List[Dict], out_ass: Path, is_bait: bool):
        primary = "&H00FFFFFF" if is_bait else "&H00FFDC2A"
        header = (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {Config.VIDEO_WIDTH}\nPlayResY: {Config.VIDEO_HEIGHT}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,DejaVu Sans,72,{primary},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,40,40,560,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        body = [header]
        for e in sub_events:
            txt = sanitize_text(e["text"]).upper()
            if txt:
                body.append(f"Dialogue: 0,{_fmt_ass_time(e['start'])},{_fmt_ass_time(e['end'])},Default,,0,0,0,,{txt}\n")
        out_ass.write_text("".join(body), encoding="utf-8")

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, duration: float, media_path: Optional[Path] = None):
        if not HAS_FFMPEG: raise RuntimeError("ffmpeg не встановлено")
        
        is_bait = (parsed["mode"] == "bait")
        uid = uuid.uuid4().hex[:8]
        overlay_png, ass_file, bg_img_file = Config.TEMP_DIR / f"ov_{uid}.png", Config.TEMP_DIR / f"sub_{uid}.ass", Config.TEMP_DIR / f"bg_{uid}.jpg"

        self._build_overlay(parsed, overlay_png, is_bait)
        self._build_ass(sub_events, ass_file, is_bait)

        is_video_media = False
        if media_path and media_path.exists():
            if media_path.suffix.lower() in [".mp4", ".mov", ".webm", ".avi", ".mkv"]:
                is_video_media = True
            else:
                try:
                    with Image.open(media_path) as im:
                        im = im.convert("RGB")
                        ow, oh = im.size
                        tr = Config.VIDEO_WIDTH / Config.VIDEO_HEIGHT
                        if ow / oh > tr:
                            nw = int(oh * tr); c_box = ((ow - nw) // 2, 0, (ow + nw) // 2, oh)
                        else:
                            nh = int(ow / tr); c_box = (0, (oh - nh) // 2, ow, (oh + nh) // 2)
                        im_crop = im.crop(c_box).resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))
                        dim_alpha = 140 if is_bait else 115
                        dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, dim_alpha))
                        im_crop.paste(dim, (0, 0), dim)
                        im_crop.save(bg_img_file, "JPEG", quality=92)
                except Exception as e:
                    bg_img_file = None

        if not is_video_media and (not bg_img_file or not bg_img_file.exists()):
            self._create_branded_bg(is_bait, bg_img_file)

        try:
            if is_video_media:
                target_w = 1020 if is_bait else 1000
                dim_val = "0.58" if is_bait else "0.48"
                fc = (
                    f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=4:1,scale={Config.VIDEO_WIDTH}:{Config.VIDEO_HEIGHT},setsar=1,drawbox=x=0:y=0:w={Config.VIDEO_WIDTH}:h={Config.VIDEO_HEIGHT}:color=black@{dim_val}:t=fill[bg];"
                    f"[0:v]scale={target_w}:1880:force_original_aspect_ratio=decrease,setsar=1[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2-20[comp];[comp][2:v]overlay=0:0,ass={ass_file.name}[outv]"
                )
                cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(media_path.resolve()), "-i", str(audio_path.resolve()), "-i", str(overlay_png.resolve()), "-filter_complex", fc, "-map", "[outv]", "-map", "1:a", "-t", f"{duration:.2f}", "-r", str(Config.VIDEO_FPS), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-threads", "2", "-movflags", "+faststart", str(out_file.resolve())]
            else:
                fc = f"[0:v][2:v]overlay=0:0,ass={ass_file.name}[outv]"
                cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(Config.VIDEO_FPS), "-i", str(bg_img_file.resolve()), "-i", str(audio_path.resolve()), "-i", str(overlay_png.resolve()), "-filter_complex", fc, "-map", "[outv]", "-map", "1:a", "-t", f"{duration:.2f}", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-threads", "2", "-movflags", "+faststart", str(out_file.resolve())]

            proc = subprocess.run(cmd, cwd=str(Config.TEMP_DIR), capture_output=True, text=True, timeout=240)
            if proc.returncode != 0: raise RuntimeError(f"ffmpeg: {proc.stderr[-400:]}")
        finally:
            for tmp in [overlay_png, ass_file, bg_img_file]:
                if tmp and tmp.exists():
                    try: tmp.unlink()
                    except: pass

    def _create_branded_bg(self, is_bait: bool, out_path: Path):
        w, h = Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT
        top, bot = ((48, 10, 20), (4, 2, 8)) if is_bait else ((10, 18, 42), (2, 4, 10))
        
        base = Image.new("RGB", (w, h))
        px = base.load()
        for y in range(h):
            t = y / h
            px_row = (int(top[0]*(1-t) + bot[0]*t), int(top[1]*(1-t) + bot[1]*t), int(top[2]*(1-t) + bot[2]*t))
            for x in range(w): px[x, y] = px_row

        orbs = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(orbs)
        colors = [(220, 40, 60), (140, 20, 40), (255, 90, 60)] if is_bait else [(40, 100, 220), (70, 60, 200), (30, 160, 220)]
        for _ in range(6):
            cx, cy, rr = random.randint(-200, w+200), random.randint(-300, h+300), random.randint(300, 700)
            c = random.choice(colors)
            od.ellipse([cx-rr, cy-rr, cx+rr, cy+rr], fill=(*c, random.randint(25, 60)))
        
        orbs = orbs.filter(ImageFilter.GaussianBlur(radius=100))
        combined = Image.alpha_composite(base.convert("RGBA"), orbs)
        
        noise = Image.effect_noise((w, h), 15).convert("L")
        combined = Image.alpha_composite(combined, Image.merge("RGBA", (noise, noise, noise, Image.new("L", (w, h), 15))))
        combined.convert("RGB").save(out_path, "JPEG", quality=90)

# =============================================================
# ГЕНЕРАЦІЯ ТА ЧЕРГА
# =============================================================
def _generate_single(text: str, voice: str, mode: str, media_path: Optional[Path]) -> Dict:
    parsed = parse_post(text, mode)
    uid = uuid.uuid4().hex[:8]
    temp_audio, temp_vtt = Config.TEMP_DIR / f"a_{uid}.mp3", Config.TEMP_DIR / f"a_{uid}.vtt"

    audio_path, duration, vtt_path = TTSEngine.generate(parsed["voiceover"], temp_audio, voice, temp_vtt)
    sub_events = TTSEngine.parse_vtt(vtt_path) if vtt_path else []
    if not sub_events:
        sub_events = [{"text": w, "start": i*1.5, "end": (i+1)*1.5} for i, w in enumerate(parsed["voiceover"].split())]

    out_file = Config.OUTPUT_DIR / f"news_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uid}.mp4"
    VideoEngine().render(parsed, audio_path, sub_events, out_file, duration, media_path)

    for tmp in [temp_audio, temp_vtt]:
        if tmp.exists():
            try: tmp.unlink()
            except: pass
    gc.collect()
    return {"video_url": f"/videos/{out_file.name}", "seo_desc": parsed["seo_desc"], "ready_comment": parsed["ready_comment"]}

def _worker_both(job_id: str, text: str, voice: str, saved_media: Optional[Path]):
    def _set(**kw):
        with JOBS_LOCK:
            if job_id in JOBS: JOBS[job_id].update(kw)
    try:
        _set(step="⏳ [1/2] Монтую відео для Акаунту 1...", progress=20)
        _set(full=_generate_single(text, voice, "full", saved_media))
        _set(step="⏳ [2/2] Монтую відео для Акаунту 2...", progress=60)
        _set(bait=_generate_single(text, voice, "bait", saved_media))
        _set(step="✅ Обидва відео готові!", done=True, progress=100, finished_at=time.time())
    except Exception as e:
        _set(error=str(e), done=True, step=f"❌ {e}")
    finally:
        if saved_media and saved_media.exists():
            try: saved_media.unlink()
            except: pass
        gc.collect()

def _cleanup_worker():
    while True:
        try:
            now = time.time()
            with JOBS_LOCK:
                for jid in list(JOBS.keys()):
                    if JOBS[jid].get("done") and (now - JOBS[jid].get("finished_at", 0)) > Config.JOB_TTL_SECONDS:
                        del JOBS[jid]
            for f in Config.OUTPUT_DIR.glob("*.mp4"):
                if (now - f.stat().st_mtime) > Config.VIDEO_TTL_SECONDS: f.unlink()
        except Exception: pass
        time.sleep(1800)

threading.Thread(target=_cleanup_worker, daemon=True).start()

# =============================================================
# FASTAPI ROUTES
# =============================================================
app = FastAPI()

_HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>News Studio · 365</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800;900&display=swap" rel="stylesheet">
<style>
:root { --bg: #06070D; --card: rgba(20, 26, 38, 0.7); --border: rgba(255,255,255,0.08); --txt: #EAF0FF; --txt-dim: #8A97AC; --blue: #2AABEE; --red: #FF3B4E; --gold: #FFC847; --green: #2EE07A; }
* { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
body { background: var(--bg); color: var(--txt); min-height: 100vh; overflow-x: hidden; }
body::before { content: ''; position: fixed; inset: -20%; background: radial-gradient(900px 700px at 15% 15%, rgba(42, 171, 238, 0.18), transparent 60%), radial-gradient(800px 600px at 85% 20%, rgba(180, 40, 200, 0.13), transparent 60%), var(--bg); z-index: -1; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 30px 20px 60px; }
header { text-align: center; margin-bottom: 36px; }
h1 { font-size: clamp(26px, 4vw, 40px); font-weight: 900; background: linear-gradient(120deg, #fff, #8CC7FF, #FFBEE9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
.subtitle { color: var(--txt-dim); font-size: 15px; font-weight: 500; line-height: 1.5; }
.box { background: var(--card); border: 1px solid var(--border); border-radius: 24px; padding: 28px; backdrop-filter: blur(24px); box-shadow: 0 20px 80px rgba(0,0,0,0.4); }
textarea { width: 100%; height: 170px; background: rgba(0,0,0,0.35); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; color: var(--txt); font-size: 15px; resize: vertical; outline: none; transition: .2s; font-family: inherit; }
textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(42, 171, 238, 0.15); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; background: rgba(0,0,0,0.25); padding: 14px 20px; border-radius: 14px; border: 1px solid var(--border); margin: 16px 0; }
label.opt { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; font-weight: 600; padding: 8px 16px; border-radius: 10px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); transition: .2s; }
label.opt:has(input:checked) { background: rgba(42,171,238,0.2); border-color: var(--blue); color: #fff; }
label.opt input { display: none; }
.drop { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; border: 2px dashed rgba(42, 171, 238, 0.5); border-radius: 16px; padding: 24px; cursor: pointer; text-align: center; background: rgba(42,171,238,0.05); margin: 16px 0; transition: .2s; }
.drop.dragover { border-color: var(--blue); background: rgba(42,171,238,0.15); transform: scale(1.02); }
.drop-icon { font-size: 28px; } .drop-text { font-size: 14px; font-weight: 600; } .drop-hint { font-size: 12px; color: var(--txt-dim); }
#mTxt { color: var(--blue); font-weight: 700; margin-top: 6px; font-size: 13px; }
.btn-go { width: 100%; padding: 18px; font-size: 16px; font-weight: 800; border: none; border-radius: 14px; cursor: pointer; color: #fff; background: linear-gradient(135deg, var(--blue), #7B3DD1); box-shadow: 0 12px 40px rgba(42, 171, 238, 0.35); transition: .3s; margin-top: 8px; }
.btn-go:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.1); }
.btn-go:disabled { opacity: 0.6; cursor: not-allowed; }
.progress-wrap { display: none; margin-top: 20px; background: rgba(0,0,0,0.4); border-radius: 10px; padding: 16px; }
#st { display: flex; justify-content: space-between; font-size: 14px; font-weight: 700; color: var(--gold); margin-bottom: 10px; }
.bar-bg { width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }
#bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--blue), var(--gold)); transition: width 0.4s ease; border-radius: 4px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 32px; }
@media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
.card { background: rgba(12, 17, 26, 0.85); border: 1px solid var(--border); border-radius: 20px; padding: 20px; display: none; animation: slideUp .4s ease-out; }
.card.show { display: block; }
.card.full { border-color: rgba(42, 171, 238, 0.35); }
.card.bait { border-color: rgba(255, 59, 78, 0.35); }
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 10px; font-size: 13px; font-weight: 800; margin-bottom: 14px; }
.badge.full { background: rgba(42, 171, 238, 0.15); color: var(--blue); border: 1px solid rgba(42, 171, 238, 0.3); }
.badge.bait { background: rgba(255, 59, 78, 0.15); color: #FF6B7E; border: 1px solid rgba(255, 59, 78, 0.3); }
video { width: 100%; max-height: 500px; border-radius: 14px; background: #000; border: 1px solid var(--border); display: block; }
.seo { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-top: 14px; }
.seo-head { display: flex; justify-content: space-between; font-size: 12px; font-weight: 800; color: var(--gold); margin-bottom: 10px; }
.copy-btn { background: rgba(255,255,255,0.06); border: 1px solid var(--border); color: var(--txt); padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; transition: .2s; }
.copy-btn:hover { background: rgba(255,255,255,0.15); }
.copy-btn.copied { background: var(--green); color: #000; }
.seo-text { font-size: 13px; color: #C8D2E2; white-space: pre-wrap; line-height: 1.6; }
.btn-dl { display: flex; align-items: center; justify-content: center; text-decoration: none; background: linear-gradient(135deg, var(--green), #1FB863); color: #051A0C; padding: 14px; border-radius: 12px; font-weight: 800; font-size: 14px; margin-top: 14px; box-shadow: 0 8px 24px rgba(46, 224, 122, 0.25); transition: .2s; }
.btn-dl:hover { transform: translateY(-1px); filter: brightness(1.1); }
#toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(100px); padding: 14px 24px; border-radius: 12px; font-weight: 800; font-size: 14px; opacity: 0; transition: .3s; z-index: 9999; pointer-events: none; }
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
#toast.err { background: var(--red); color: #fff; } #toast.ok { background: var(--green); color: #000; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🎬 News Studio · 365</h1>
    <p class="subtitle">Створення унікальних відео для двох акаунтів за один клік.</p>
  </header>
  <div class="box">
    <textarea id="pTxt" placeholder="Вставте сюди текст новини..." autofocus></textarea>
    <div class="row">
      <span style="font-size:13px; font-weight:700; color:var(--txt-dim);">ГОЛОС:</span>
      <label class="opt"><input type="radio" name="voice" value="uk-UA-PolinaNeural" checked> 👩 Поліна</label>
      <label class="opt"><input type="radio" name="voice" value="uk-UA-OstapNeural"> 👨 Остап</label>
    </div>
    
    <div class="drop" id="dropZone" onclick="document.getElementById('mFile').click()">
      <div class="drop-icon">📹</div>
      <div class="drop-text"><b>Перетягніть відео або фото</b></div>
      <div class="drop-hint">Не обов'язково. Якщо пусто — буде брендовий фон.</div>
      <input type="file" id="mFile" accept="video/*,image/*" style="display:none;" onchange="showF(this)">
      <div id="mTxt"></div>
    </div>

    <button class="btn-go" id="btn" onclick="genBoth()">🚀 Змонтувати 2 відео</button>
    
    <div class="progress-wrap" id="progWrap">
      <div id="st">Ініціалізація... <span id="progTxt">0%</span></div>
      <div class="bar-bg"><div id="bar-fill"></div></div>
    </div>

    <div class="grid">
      <div class="card full" id="cardFull">
        <span class="badge full">📰 Акаунт 1 · Повна новина</span>
        <video id="vidFull" controls playsinline></video>
        <a id="dlFull" class="btn-dl" download>⬇ Скачати MP4</a>
        <div class="seo"><div class="seo-head"><span>🔥 SEO-опис</span><button class="copy-btn" onclick="copyText('seoFull', this)">📋 Копіювати</button></div><div class="seo-text" id="seoFull"></div></div>
        <div class="seo"><div class="seo-head" style="color:var(--blue);"><span>💬 Коментар</span><button class="copy-btn" onclick="copyText('comFull', this)">📋 Копіювати</button></div><div class="seo-text" id="comFull"></div></div>
      </div>
      <div class="card bait" id="cardBait">
        <span class="badge bait">🔥 Акаунт 2 · Перелив у ТГ</span>
        <video id="vidBait" controls playsinline></video>
        <a id="dlBait" class="btn-dl" download>⬇ Скачати MP4</a>
        <div class="seo"><div class="seo-head"><span>🔥 SEO-опис</span><button class="copy-btn" onclick="copyText('seoBait', this)">📋 Копіювати</button></div><div class="seo-text" id="seoBait"></div></div>
        <div class="seo"><div class="seo-head" style="color:#FF8A99;"><span>💬 Коментар</span><button class="copy-btn" onclick="copyText('comBait', this)">📋 Копіювати</button></div><div class="seo-text" id="comBait"></div></div>
      </div>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
let selectedFile = null;
const dz = document.getElementById('dropZone');

['dragenter', 'dragover'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.add('dragover'); }));
['dragleave', 'drop'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.remove('dragover'); }));
dz.addEventListener('drop', ev => {
  const files = ev.dataTransfer.files;
  if(files.length > 0) {
    document.getElementById('mFile').files = files;
    showF(document.getElementById('mFile'));
  }
});

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'show ' + type;
  clearTimeout(t._timer); t._timer = setTimeout(() => t.className = '', 3500);
}

function showF(i) {
  if (i.files && i.files[0]) {
    selectedFile = i.files[0];
    document.getElementById('mTxt').innerText = '✓ ' + selectedFile.name;
  }
}

async function genBoth() {
  const btn = document.getElementById('btn'), pWrap = document.getElementById('progWrap');
  const txt = document.getElementById('pTxt').value.trim(), voice = document.querySelector('input[name="voice"]:checked').value;
  if (!txt) { toast('Введіть текст!', 'err'); return; }

  btn.disabled = true;
  document.getElementById('cardFull').classList.remove('show'); document.getElementById('cardBait').classList.remove('show');
  pWrap.style.display = 'block';
  document.getElementById('bar-fill').style.width = '5%';
  document.getElementById('st').innerHTML = '⏳ Підготовка... <span id="progTxt">5%</span>';

  try {
    const fd = new FormData(); fd.append('text', txt); fd.append('voice', voice);
    if (selectedFile) fd.append('media_file', selectedFile);

    const startRes = await fetch('/api/start_both', { method: 'POST', body: fd });
    if (!startRes.ok) throw new Error('Помилка старту');
    const { job_id } = await startRes.json();

    let shownFull = false, shownBait = false;

    while (true) {
      await new Promise(r => setTimeout(r, 1500));
      const pollRes = await fetch('/api/job/' + job_id);
      const job = await pollRes.json();

      if (job.progress !== undefined) document.getElementById('bar-fill').style.width = job.progress + '%';
      document.getElementById('st').innerHTML = (job.step || 'Монтую...') + ` <span id="progTxt">${job.progress || 0}%</span>`;

      if (job.full && !shownFull) {
        shownFull = true;
        document.getElementById('vidFull').src = job.full.video_url;
        document.getElementById('dlFull').href = job.full.video_url;
        document.getElementById('seoFull').textContent = job.full.seo_desc;
        document.getElementById('comFull').textContent = job.full.ready_comment;
        document.getElementById('cardFull').classList.add('show');
      }
      if (job.bait && !shownBait) {
        shownBait = true;
        document.getElementById('vidBait').src = job.bait.video_url;
        document.getElementById('dlBait').href = job.bait.video_url;
        document.getElementById('seoBait').textContent = job.bait.seo_desc;
        document.getElementById('comBait').textContent = job.bait.ready_comment;
        document.getElementById('cardBait').classList.add('show');
      }
      if (job.error) throw new Error(job.error);
      if (job.done) { toast('✅ Готово!', 'ok'); pWrap.style.display = 'none'; break; }
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err'); pWrap.style.display = 'none';
  } finally { btn.disabled = false; }
}

function copyText(id, btn) {
  navigator.clipboard.writeText(document.getElementById(id).textContent).then(() => {
    const orig = btn.textContent; btn.textContent = '✓ Готово'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = orig; btn.classList.remove('copied'); }, 1500);
  });
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return _HTML

@app.post("/api/start_both")
async def api_start_both(text: Optional[str] = Form(None), voice: Optional[str] = Form("uk-UA-PolinaNeural"), media_file: Optional[UploadFile] = File(None)):
    if not text or not text.strip(): text = "У Чорноморську троє загиблих через удар по ринку. Повідомили в ОВА."
    saved_media = None
    if media_file and media_file.filename:
        contents = await media_file.read()
        if len(contents) > Config.MAX_UPLOAD_MB * 1024 * 1024: raise HTTPException(413, "Файл завеликий")
        saved_media = Config.TEMP_DIR / f"upload_{uuid.uuid4().hex[:8]}{Path(media_file.filename).suffix.lower()}"
        saved_media.write_bytes(contents)
    
    job_id = uuid.uuid4().hex[:10]
    with JOBS_LOCK:
        JOBS[job_id] = {"step": "Ініціалізація...", "progress": 5, "full": None, "bait": None, "done": False, "error": None, "created": time.time()}
    threading.Thread(target=_worker_both, args=(job_id, text, voice, saved_media), daemon=True).start()
    return {"job_id": job_id}

@app.get("/api/job/{job_id}")
async def api_job(job_id: str):
    with JOBS_LOCK: job = JOBS.get(job_id)
    if not job: return JSONResponse(status_code=404, content={"error": "Not found"})
    return job

@app.get("/videos/{filename}")
async def get_vid(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename: return JSONResponse(status_code=400, content={"error": "Bad filename"})
    p = Config.OUTPUT_DIR / filename
    return FileResponse(p, media_type="video/mp4") if p.exists() else JSONResponse(status_code=404, content={"error": "Not found"})
