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
        (["відключен", "блекаут", "дтек", "графік", "обленерго", "електроенерг", "без світла", "без електрики", "електрик"],
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
    base_tags = ["#новини", "#новиниукраїни", "#україна", "#рек", "#рекомендації", "#тренди"]
    topic_tags: List[str] = []

    if has_word(combined, ["тцк", "мобілізац", "повістк", "військком"]):
        topic_tags = ["#тцк", "#мобілізація", "#скандал", "#резонанс"]
        q = ("Повне відео конфлікту та чим усе закінчилося — вже в нашому ТГ в шапці профілю 👇"
             if bait else "Що думаєте про цю ситуацію? Пишіть у коментарях 👇")
    elif has_word(combined, ["відключен", "блекаут", "дтек", "графік", "обленерго", "електроенерг", "без світла", "без електрики", "електрик"]):
        topic_tags = ["#відключеннясвітла", "#блекаут", "#світло", "#енергетика"]
        q = ("Точні графіки та коли повернуть світло — вже в нашому ТГ в шапці профілю 👇"
             if bait else "А як у вас зараз зі світлом? Пишіть ваше місто в коментарях 👇")
    elif has_word(combined, ["обстріл", "удар", "ракета", "шахед", "вибух", "евакуац", "атакув"]):
        topic_tags = ["#обстріл", "#війна", "#тривога", "#терміново"]
        q = ("Кадри без блюру та деталі з місця подій — вже в нашому ТГ в шапці профілю 👇"
             if bait else "Тримаємось і бережемо себе. Що відомо у вашому місті? 👇")
    elif has_word(combined, ["путін", "переговор", "трамп", "зеленськ"]):
        topic_tags = ["#політика", "#переговори", "#новинисвіту", "#війна"]
        q = ("Повна заява та реакція без вирізок — вже в нашому ТГ в шапці профілю 👇"
             if bait else "Як оцінюєте такі заяви? Обговорюємо в коментарях 👇")
    else:
        topic_tags = ["#терміново", "#важливо", "#актуально"]
        q = ("Повні кадри та деталі, які видаляє ТікТок — вже в нашому ТГ в шапці профілю 👇"
             if bait else "Яка ваша думка щодо цієї новини? Обговорюємо в коментарях 👇")

    city_map = {
        "бердянськ": "#бердянськ", "київ": "#київ", "харків": "#харків", "одес": "#одеса",
        "дніпр": "#дніпро", "запоріж": "#запоріжжя", "львів": "#львів", "кропивниц": "#кропивницький",
        "чорноморськ": "#чорноморськ", "волин": "#волинь", "крим": "#крим", "херсон": "#херсон",
        "суми": "#суми", "полтав": "#полтава", "миколаїв": "#миколаїв"
    }
    for kw, ctag in city_map.items():
        if kw in combined:
            topic_tags.append(ctag)

    if bait:
        topic_tags.append("#ексклюзив")

    all_tags = list(dict.fromkeys(topic_tags + base_tags))

    clean_head = headline.strip()
    clean_body = body.strip()
    if bait:
        main_text = f"🚨 {clean_head}"
        if clean_body and clean_body.lower() != clean_head.lower():
            main_text += f"\n{clean_body[:180].rstrip()}..."
    else:
        main_text = f"⚡ {clean_head}"
        if clean_body and clean_body.lower() != clean_head.lower():
            main_text += f"\n\n{clean_body[:550]}"

    return f"{main_text}\n\n{q}\n\n🔎 Telegram: NEWS УКРАЇНА 365 (t.me/kropivnit)\n\n{chr(32).join(all_tags)}"

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
        "seo_desc": generate_seo(headline, display_body or "", mode),
        "ready_comment": adaptive["comment"],
        "mode": mode,
    }

# =============================================================
# ОЗВУЧКА ТА СУБТИТРИ (EDGE-TTS)
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
        try: content = vtt_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except Exception: return events
        
        pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
        for block in content.split("\n\n"):
            lines = [l.strip() for l in block.strip().split("\n") if l.strip() and not l.startswith("WEBVTT")]
            if not lines: continue
            
            time_match = None
            text_lines = []
            for line in lines:
                m = pattern.search(line)
                if m: time_match = m
                elif time_match: text_lines.append(line)
                    
            if time_match:
                start = int(time_match[1])*3600 + int(time_match[2])*60 + int(time_match[3]) + int(time_match[4])/1000
                end = int(time_match[5])*3600 + int(time_match[6])*60 + int(time_match[7]) + int(time_match[8])/1000
                txt = " ".join(text_lines).strip()
                if txt: events.append({"start": start, "end": end, "text": txt})
        return events

    @classmethod
    def get_grouped_subtitles(cls, vtt_path: Optional[Path], fallback_text: str, duration: float) -> List[Dict]:
        events = cls.parse_vtt(vtt_path) if vtt_path else []
        if not events:
            words = ["NEWS" if w.lower() == "ньюз" else w for w in sanitize_text(fallback_text).split()]
            chunks = [" ".join(words[i:i+2]) for i in range(0, len(words), 2)]
            t_chunk = duration / max(1, len(chunks))
            return [{"text": c, "start": i*t_chunk, "end": (i+1)*t_chunk} for i, c in enumerate(chunks)]
            
        grouped = []
        current_words, current_start = [], None
        for e in events:
            if current_start is None: current_start = e["start"]
            w_clean = "NEWS" if e["text"].strip().lower() == "ньюз" else e["text"].strip()
            current_words.append(w_clean)
            if len(current_words) >= 2:
                grouped.append({"start": current_start, "end": e["end"], "text": " ".join(current_words)})
                current_words, current_start = [], None
                
        if current_words and events:
            grouped.append({"start": current_start, "end": events[-1]["end"], "text": " ".join(current_words)})
        return grouped

def _fmt_ass_time(sec: float) -> str:
    return f"{int(sec // 3600)}:{int((sec % 3600) // 60):02d}:{int(sec % 60):02d}.{int((sec - int(sec)) * 100):02d}"

# =============================================================
# ВІДЕО-ДВИЖОК
# =============================================================
class VideoEngine:
    def __init__(self):
        self.font_badge = _load_font(26)
        self.font_head = _load_font(38)
        self.font_cta = _load_font(28)
        self.font_watermark = _load_font(26)

    def _build_overlay(self, parsed: Dict, out_png: Path, is_bait: bool):
        W = Config.VIDEO_WIDTH
        overlay = Image.new("RGBA", (W, Config.VIDEO_HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        # Компактна темна плашка шапки в безпечній зоні TikTok (Y=220..520)
        d.rectangle([0, 220, W, 520], fill=(5, 8, 14, 195))

        # Бейдж зліва на Y=260
        if is_bait:
            d.rounded_rectangle([40, 260, 300, 320], radius=12, fill=(255, 165, 0, 255))
            d.text((55, 272), "ЕКСКЛЮЗИВ", font=self.font_badge, fill=(0, 0, 0, 255))
            wm = Config.CHANNEL_BAIT_WATERMARK
            wm_fill = (200, 30, 45, 240)
        else:
            d.rounded_rectangle([40, 260, 280, 320], radius=12, fill=(225, 25, 35, 255))
            d.text((55, 272), "ТЕРМІНОВО", font=self.font_badge, fill=(255, 255, 255, 255))
            wm = Config.CHANNEL_DISPLAY_NAME
            wm_fill = (120, 50, 210, 240)

        # Вотермарка справа на Y=260 (logo.png або фірмова кольорова плашка)
        if Config.WATERMARK_PATH.exists():
            try:
                with Image.open(Config.WATERMARK_PATH) as wm_img:
                    wm_img = wm_img.convert("RGBA")
                    ratio = 320 / wm_img.width
                    wm_img = wm_img.resize((320, int(wm_img.height * ratio)), Image.Resampling.LANCZOS)
                    overlay.paste(wm_img, (W - wm_img.width - 40, 250), wm_img)
            except Exception:
                wm_w = int(d.textlength(wm, font=self.font_watermark))
                d.rounded_rectangle([W - wm_w - 70, 260, W - 40, 320], radius=12, fill=wm_fill, outline=(255, 255, 255, 200), width=2)
                d.text((W - wm_w - 55, 274), wm, font=self.font_watermark, fill=(255, 255, 255, 255))
        else:
            wm_w = int(d.textlength(wm, font=self.font_watermark))
            d.rounded_rectangle([W - wm_w - 70, 260, W - 40, 320], radius=12, fill=wm_fill, outline=(255, 255, 255, 200), width=2)
            d.text((W - wm_w - 55, 274), wm, font=self.font_watermark, fill=(255, 255, 255, 255))

        # Заголовок (2 рядки) + золота/червона лінія
        headline_clean = sanitize_text(parsed["headline"]) or ("ЕКСКЛЮЗИВ" if is_bait else "ТЕРМІНОВА НОВИНА")
        h_lines = wrap_text_lines(headline_clean, self.font_head, W - 80)
        cur_hy = 345
        for hl in h_lines[:2]:
            d.text((40, cur_hy), hl, font=self.font_head, fill=(255, 255, 255, 255))
            cur_hy += 48
        line_col = (255, 80, 80, 240) if is_bait else (255, 215, 0, 240)
        d.line([(40, cur_hy + 8), (W - 40, cur_hy + 8)], fill=line_col, width=3)

        # Нижній CTA-банер на Y=1360..1480 (над описом TikTok)
        y_off = 1360
        if is_bait:
            d.rounded_rectangle([40, y_off + 20, W - 40, y_off + 140], radius=20, fill=(200, 25, 35, 245), outline=(255, 215, 0, 255), width=3)
            c_txt = "ПОВНЕ ВІДЕО БЕЗ ЦЕНЗУРИ В ШАПЦІ ПРОФІЛЮ ➔"
            sub_col = (255, 245, 180, 255)
        else:
            d.rounded_rectangle([40, y_off + 20, W - 40, y_off + 140], radius=20, fill=(18, 25, 38, 245), outline=(42, 171, 238, 255), width=2)
            c_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
            sub_col = (42, 171, 238, 255)

        cw = d.textlength(c_txt, font=self.font_cta)
        d.text(((W - cw) // 2, y_off + 42), c_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        sub_t = f"Telegram: {Config.CHANNEL_DISPLAY_NAME}"
        d.text(((W - d.textlength(sub_t, font=self.font_badge)) // 2, y_off + 88), sub_t, font=self.font_badge, fill=sub_col)

        overlay.save(out_png, "PNG")

    def _build_ass(self, sub_events: List[Dict], out_ass: Path, is_bait: bool):
        primary = "&H00FFFFFF" if is_bait else "&H000ADCFF"
        header = (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {Config.VIDEO_WIDTH}\nPlayResY: {Config.VIDEO_HEIGHT}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,DejaVu Sans,68,{primary},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,700,1\n\n"
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
                except Exception:
                    bg_img_file = None

        # Якщо медіа немає — генеруємо крутий фон
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
        top = (35, 10, 25) if is_bait else (10, 20, 50)
        bot = (5, 2, 8) if is_bait else (2, 5, 15)
        
        base = Image.new("RGB", (w, h))
        px = base.load()
        for y in range(h):
            t = y / h
            px_row = (int(top[0]*(1-t) + bot[0]*t), int(top[1]*(1-t) + bot[1]*t), int(top[2]*(1-t) + bot[2]*t))
            for x in range(w): px[x, y] = px_row

        overlay = Image.new("RGBA", (w, h), (0,0,0,0))
        od = ImageDraw.Draw(overlay)
        
        colors = [(255, 50, 80), (255, 100, 50)] if is_bait else [(40, 150, 255), (100, 80, 255)]
        # Неонові дуги
        for i in range(4):
            cx, cy = w // 2, h // 2
            r = 300 + i * 150
            od.arc([cx-r, cy-r, cx+r, cy+r], start=random.randint(0, 180), end=random.randint(180, 360), fill=random.choice(colors) + (random.randint(40, 80),), width=random.randint(15, 40))
            
        # Світлові кулі
        for _ in range(6):
            cx, cy = random.randint(-200, w+200), random.randint(-300, h+300)
            r = random.randint(200, 500)
            c = random.choice(colors)
            od.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*c, random.randint(20, 60)))
            
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=80))
        base = Image.alpha_composite(base.convert("RGBA"), overlay)
        
        # Технологічна сітка
        grid = Image.new("RGBA", (w, h), (0,0,0,0))
        gd = ImageDraw.Draw(grid)
        for x in range(0, w, 80):
            gd.line([(x, 0), (x, h)], fill=(255, 255, 255, 10), width=1)
        for y in range(0, h, 80):
            gd.line([(0, y), (w, y)], fill=(255, 255, 255, 10), width=1)
            
        base = Image.alpha_composite(base, grid)
        base.convert("RGB").save(out_path, "JPEG", quality=92)

# =============================================================
# ГЕНЕРАЦІЯ ТА ЧЕРГА
# =============================================================
def _generate_single(text: str, voice: str, mode: str, media_path: Optional[Path]) -> Dict:
    parsed = parse_post(text, mode)
    uid = uuid.uuid4().hex[:8]
    temp_audio, temp_vtt = Config.TEMP_DIR / f"a_{uid}.mp3", Config.TEMP_DIR / f"a_{uid}.vtt"

    audio_path, duration, vtt_path = TTSEngine.generate(parsed["voiceover"], temp_audio, voice, temp_vtt)
    sub_events = TTSEngine.get_grouped_subtitles(vtt_path, parsed["voiceover"], duration)

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
.social-wrap { margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--border); display: none; }
.social-wrap.show { display: block; }
.social-title { font-size: 14px; font-weight: 800; margin-bottom: 14px; color: var(--txt); }
.social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.soc { padding: 14px; border-radius: 12px; text-align: center; text-decoration: none; font-weight: 800; font-size: 13px; transition: all .2s; display: flex; align-items: center; justify-content: center; gap: 6px; }
.soc:hover { transform: translateY(-2px); filter: brightness(1.1); }
.soc-tt { background: #000; color: #fff; border: 1px solid #333; }
.soc-yt { background: #FF0033; color: #fff; }
.soc-ig { background: linear-gradient(45deg, #F58529, #DD2A7B, #8134AF); color: #fff; }
.soc-fb { background: #1877F2; color: #fff; }
.soc-th { background: #101010; color: #fff; border: 1px solid #333; }
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
      <div class="drop-hint">Не обов'язково. Якщо пусто — згенерується неоновий фон.</div>
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

    <div id="socPanel" class="social-wrap">
      <div class="social-title">🚀 Швидке вивантаження:</div>
      <div class="social-grid">
        <a href="https://www.tiktok.com/upload" target="_blank" class="soc soc-tt">🎵 TikTok</a>
        <a href="https://www.youtube.com/upload" target="_blank" class="soc soc-yt">▶ Shorts</a>
        <a href="https://www.instagram.com/" target="_blank" class="soc soc-ig">📸 Reels</a>
        <a href="https://www.facebook.com/reels/create" target="_blank" class="soc soc-fb">📘 Reels FB</a>
        <a href="https://www.threads.net/" target="_blank" class="soc soc-th">🧵 Threads</a>
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
  document.getElementById('socPanel').classList.remove('show');
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
      if (job.done) { 
        toast('✅ Готово!', 'ok'); 
        pWrap.style.display = 'none'; 
        document.getElementById('socPanel').classList.add('show');
        break; 
      }
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
        ext = Path(media_file.filename).suffix.lower() or ".mp4"
        saved_media = Config.TEMP_DIR / f"upload_{uuid.uuid4().hex[:8]}{ext}"
        with open(saved_media, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)
    
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
