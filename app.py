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

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# =============================================================
# КОНФІГ
# =============================================================
class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_USERNAME = "@kropivnit"
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 25
    JOB_TTL_SECONDS = 3600
    VIDEO_TTL_SECONDS = 86400
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"
    WATERMARK_PATH = BASE_DIR / "logo.png"

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

JOBS: Dict[str, Dict] = {}
JOBS_LOCK = threading.Lock()

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
    if not text:
        return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"t\.me/\S+", " ", text)
    text = re.sub(r"@[a-zA-Z0-9_]+", " ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = text.replace("!?", " ").replace("?!", " ").replace("!", " ").replace("?", " ")
    text = re.sub(r"[⚡🔥👉👇⚠️🚨✔✓➔➡•—–«»#*_=~`\"'()\[\]{}:;+/\\]", " ", text)
    text = re.sub(r"(\d+)-([а-яА-ЯіїєґІЇЄҐ]+)", r"\1 \2", text)
    text = text.replace("-", " ")
    text = re.sub(r"\.{2,}", ".", text)
    return re.sub(r"\s+", " ", text).strip()

def has_word(text: str, words: List[str]) -> bool:
    t = text.lower()
    return any(re.search(r"\b" + re.escape(w), t) for w in words)

# =============================================================
# CTA ТА SEO (ЗАКЛИК ПИСАТИ "+" У КОМЕНТАРЯХ)
# =============================================================
def get_adaptive_cta(combined: str) -> Dict[str, str]:
    t = combined.lower()

    if has_word(t, ["тцк", "мобілізац", "повістк", "військком"]):
        voice_cta = "Повне відео конфлікту та офіційну реакцію вже виклали в нашому Телеграм каналі Ньюз Україна 365. Хто хоче посилання, пишіть плюс у коментарях!"
        comment = "👇 Хто хоче глянути повне відео та деталі — пишіть «+» у коментарях, скину наш Telegram (NEWS УКРАЇНА 365)!"
        reply_plus = "Ось наш Telegram 👉 шукай в пошуку: NEWS УКРАЇНА 365 (@kropivnit) або тисни посилання в шапці профілю!"

    elif has_word(t, ["відключен", "блекаут", "дтек", "графік", "обленерго", "електроенерг", "без світла", "без електрики", "електрик"]):
        voice_cta = "Точні графіки відключень для вашого міста вже опубліковані в нашому Телеграм каналі Ньюз Україна 365. Хто хоче в канал, ставте плюс у коментарях!"
        comment = "⚡ Кому потрібні точні графіки світла по областях — пишіть «+» у коментарях, одразу скину наш Telegram!"
        reply_plus = "Графіки тут 👉 шукай в Telegram: NEWS УКРАЇНА 365 (@kropivnit) або за посиланням у шапці профілю!"

    elif has_word(t, ["обстріл", "удар", "ракета", "шахед", "вибух", "евакуац", "атакув", "загибл"]):
        voice_cta = "Оперативні кадри з місця подій та детальну інформацію дивіться в нашому Телеграм каналі Ньюз Україна 365. Пишіть плюс у коментарях, і я скину посилання!"
        comment = "🚨 Усі оперативні новини, фото та відео без затримок у нашому Telegram. Хто хоче в канал — ставте «+» у коментарях!"
        reply_plus = "Ось канал 👉 шукай в Telegram: NEWS УКРАЇНА 365 (@kropivnit) або переходь за посиланням у шапці профілю!"

    elif has_word(t, ["путін", "переговор", "трамп", "зеленськ", "янукович"]):
        voice_cta = "Повне відео виступу та головні заяви без вирізок вже в нашому Телеграм каналі Ньюз Україна 365. Хто хоче посилання, пишіть плюс у коментарях!"
        comment = "🔥 Повний розбір та відео без вирізок уже в нашому Telegram. Пишіть «+» у коментарях, хто хоче посилання!"
        reply_plus = "Тримай 👉 шукай в Telegram: NEWS УКРАЇНА 365 (@kropivnit) або тисни посилання в шапці профілю!"

    else:
        voice_cta = "Більше ексклюзивних новин та відео без цензури дивіться в нашому Телеграм каналі Ньюз Україна 365. Хто хоче в канал, пишіть плюс у коментарях!"
        comment = "👉 Хто хоче в наш Telegram-канал новин — ставте «+» у коментарях, одразу скину посилання!"
        reply_plus = "Ось наш Telegram 👉 шукай в пошуку: NEWS УКРАЇНА 365 (@kropivnit) або переходь у шапку профілю!"

    return {
        "voice_cta": voice_cta,
        "comment": comment,
        "reply_plus": reply_plus
    }

def generate_seo(headline: str, body: str) -> str:
    combined = (headline + " " + body).lower()
    base_tags = ["#новини", "#новиниукраїни", "#україна", "#рек", "#рекомендації", "#тренди"]
    topic_tags: List[str] = []

    if has_word(combined, ["тцк", "мобілізац", "повістк", "військком"]):
        topic_tags = ["#тцк", "#мобілізація", "#скандал", "#резонанс"]
        q = "Що думаєте про цю ситуацію? Пишіть «+» у коментарях, хто хоче в наш ТГ 👇"
    elif has_word(combined, ["відключен", "блекаут", "дтек", "графік", "обленерго", "електроенерг", "без світла", "без електрики", "електрик"]):
        topic_tags = ["#відключеннясвітла", "#блекаут", "#світло", "#енергетика"]
        q = "Як у вас зі світлом? Пишіть «+» у коментарях — скину ТГ із точними графіками 👇"
    elif has_word(combined, ["обстріл", "удар", "ракета", "шахед", "вибух", "евакуац", "атакув", "загибл"]):
        topic_tags = ["#обстріл", "#війна", "#тривога", "#терміново"]
        q = "Тримаємось і бережемо себе. Пишіть «+» у коментарях, хто хоче посилання на наш ТГ 👇"
    elif has_word(combined, ["путін", "переговор", "трамп", "зеленськ"]):
        topic_tags = ["#політика", "#переговори", "#новинисвіту", "#війна"]
        q = "Як оцінюєте такі заяви? Ставте «+» у коментарях — скину посилання на наш ТГ 👇"
    else:
        topic_tags = ["#терміново", "#важливо", "#актуально"]
        q = "Яка ваша думка? Хто хоче в наш Telegram-канал — пишіть «+» у коментарях 👇"

    city_map = {
        "бердянськ": "#бердянськ", "київ": "#київ", "харків": "#харків", "одес": "#одеса",
        "дніпр": "#дніпро", "запоріж": "#запоріжжя", "львів": "#львів", "кропивниц": "#кропивницький",
        "чорноморськ": "#чорноморськ", "волин": "#волинь", "крим": "#крим", "херсон": "#херсон",
        "суми": "#суми", "полтав": "#полтава", "миколаїв": "#миколаїв", "вінниц": "#вінниця",
        "житомир": "#житомир", "рівн": "#рівне", "черкас": "#черкаси", "тернопіл": "#тернопіль",
        "черніг": "#чернігів", "луцьк": "#луцьк", "хмельниц": "#хмельницький", "ужгород": "#ужгород"
    }
    for kw, ctag in city_map.items():
        if kw in combined:
            topic_tags.append(ctag)

    all_tags = list(dict.fromkeys(topic_tags + base_tags))

    clean_head = headline.strip()
    clean_body = body.strip()
    main_text = f"⚡ {clean_head}"
    if clean_body and clean_body.lower() != clean_head.lower():
        main_text += f"\n\n{clean_body[:550]}"

    return f"{main_text}\n\n{q}\n\n🔎 Telegram: NEWS УКРАЇНА 365 (t.me/kropivnit)\n\n{' '.join(all_tags)}"

# =============================================================
# ПАРСЕР ПОСТА
# =============================================================
_dummy_img = Image.new("RGBA", (1, 1))
_dummy_draw = ImageDraw.Draw(_dummy_img)

def wrap_text_lines(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> List[str]:
    if not text or not text.strip():
        return [""]
    words, lines, cur = text.split(), [], []
    for w in words:
        test = " ".join(cur + [w])
        if _dummy_draw.textlength(test, font=font) <= max_w:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines

def parse_post(raw_post: str) -> Dict[str, str]:
    lines = [sanitize_text(l) for l in raw_post.split("\n") if sanitize_text(l)]
    if len(lines) > 1:
        headline = lines[0]
        others = [l for l in lines[1:] if l.lower() != headline.lower()]
        full_body = ". ".join(others)
    else:
        headline = lines[0] if lines else "ТЕРМІНОВА НОВИНА"
        others, full_body = [], ""

    adaptive = get_adaptive_cta(f"{headline} {full_body}")
    cta = adaptive["voice_cta"]
    voice = f"{headline}. {full_body}. {cta}" if full_body else f"{headline}. {cta}"

    return {
        "headline": sanitize_text(headline).upper(),
        "body": sanitize_text(full_body)[:220],
        "voiceover": sanitize_text(voice)[:2500],
        "seo_desc": generate_seo(headline, full_body or ""),
        "ready_comment": adaptive["comment"],
        "reply_plus": adaptive["reply_plus"],
    }

# =============================================================
# ОЗВУЧКА ТА СУБТИТРИ (EDGE-TTS)
# =============================================================
class TTSEngine:
    @classmethod
    def generate(cls, text: str, out_audio: Path, voice: str, out_vtt: Optional[Path] = None) -> Tuple[Path, float, Optional[Path]]:
        if not HAS_EDGE_TTS:
            raise RuntimeError("edge-tts не встановлено")
        safe = sanitize_text(text)[:3000]
        if not safe.strip():
            raise RuntimeError("Порожній текст")

        cmd = ["edge-tts", "--voice", voice, "--rate", "+6%", "--text", safe, "--write-media", str(out_audio)]
        if out_vtt:
            cmd += ["--write-subtitles", str(out_vtt)]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"TTS помилка: {r.stderr[:200]}")

        duration = cls._duration(out_audio)
        return out_audio, duration, (out_vtt if out_vtt and out_vtt.exists() else None)

    @classmethod
    def _duration(cls, p: Path) -> float:
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                capture_output=True, text=True, timeout=10
            )
            return float(r.stdout.strip())
        except Exception:
            return 10.0

    @classmethod
    def parse_vtt(cls, vtt_path: Path) -> List[Dict]:
        events = []
        try:
            content = vtt_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except Exception:
            return events

        pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
        for block in content.split("\n\n"):
            lines = [l.strip() for l in block.strip().split("\n") if l.strip() and not l.startswith("WEBVTT")]
            if not lines:
                continue

            time_match = None
            text_lines = []
            for line in lines:
                m = pattern.search(line)
                if m:
                    time_match = m
                elif time_match:
                    text_lines.append(line)

            if time_match:
                start = int(time_match[1])*3600 + int(time_match[2])*60 + int(time_match[3]) + int(time_match[4])/1000
                end = int(time_match[5])*3600 + int(time_match[6])*60 + int(time_match[7]) + int(time_match[8])/1000
                txt = " ".join(text_lines).strip()
                if txt:
                    events.append({"start": start, "end": end, "text": txt})
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
            if current_start is None:
                current_start = e["start"]
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
# ВІДЕО-ДВИЖОК (ОДНЕ ВІДЕО БЕЗ НАКЛАДАННЯ ВОТЕРМАРКИ НА ТЕКСТ)
# =============================================================
class VideoEngine:
    def __init__(self):
        self.font_badge = _load_font(26)
        self.font_head = _load_font(38)
        self.font_cta = _load_font(28)
        self.font_watermark = _load_font(26)

    def _build_overlay(self, parsed: Dict, out_png: Path):
        W = Config.VIDEO_WIDTH
        overlay = Image.new("RGBA", (W, Config.VIDEO_HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)

        # Підготовка заголовка (до 2 рядків, щоб точно знати висоту шапки)
        headline_clean = sanitize_text(parsed["headline"]) or "ТЕРМІНОВА НОВИНА"
        h_lines = wrap_text_lines(headline_clean, self.font_head, W - 80)[:2]
        header_bottom = 345 + len(h_lines) * 48 + 30

        # Темна плашка шапки в безпечній зоні TikTok (Y=220..header_bottom)
        d.rectangle([0, 220, W, header_bottom], fill=(5, 8, 14, 195))

        # Бейдж "ТЕРМІНОВО" зліва на Y=256..316 (ширина строго під текст)
        badge_txt = "ТЕРМІНОВО"
        bw = int(d.textlength(badge_txt, font=self.font_badge)) + 40
        d.rounded_rectangle([40, 256, 40 + bw, 316], radius=12, fill=(225, 25, 35, 255))
        d.text((60, 270), badge_txt, font=self.font_badge, fill=(255, 255, 255, 255))

        # Вотермарка справа строго в рядку Y=256..316 (макс висота 60px, тому НЕ налазить на заголовок!)
        wm_placed = False
        if Config.WATERMARK_PATH.exists():
            try:
                with Image.open(Config.WATERMARK_PATH) as wm_img:
                    wm_img = wm_img.convert("RGBA")
                    max_h = 60
                    max_w = 260
                    scale = min(max_h / wm_img.height, max_w / wm_img.width)
                    new_w = max(1, int(wm_img.width * scale))
                    new_h = max(1, int(wm_img.height * scale))
                    wm_img = wm_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    wy = 256 + (60 - new_h) // 2
                    overlay.paste(wm_img, (W - new_w - 40, wy), wm_img)
                    wm_placed = True
            except Exception:
                wm_placed = False

        if not wm_placed:
            wm = Config.CHANNEL_DISPLAY_NAME
            wm_w = int(d.textlength(wm, font=self.font_watermark))
            d.rounded_rectangle([W - wm_w - 70, 256, W - 40, 316], radius=12, fill=(120, 50, 210, 240), outline=(255, 255, 255, 200), width=2)
            d.text((W - wm_w - 55, 270), wm, font=self.font_watermark, fill=(255, 255, 255, 255))

        # Заголовок на Y=345 (нижче бейджа й вотермарки)
        cur_hy = 345
        for hl in h_lines:
            d.text((40, cur_hy), hl, font=self.font_head, fill=(255, 255, 255, 255))
            cur_hy += 48
        d.line([(40, cur_hy + 8), (W - 40, cur_hy + 8)], fill=(255, 215, 0, 240), width=3)

        # Нижній CTA-банер на Y=1360..1480 (над інтерфейсом TikTok)
        y_off = 1360
        d.rounded_rectangle([40, y_off + 20, W - 40, y_off + 140], radius=20, fill=(18, 25, 38, 245), outline=(42, 171, 238, 255), width=2)
        c_txt = "ПИШИ «+» В КОМЕНТАРЯХ — ДАМ ТГ ➔"
        cw = d.textlength(c_txt, font=self.font_cta)
        d.text(((W - cw) // 2, y_off + 42), c_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        sub_t = f"Telegram: {Config.CHANNEL_DISPLAY_NAME} ({Config.CHANNEL_USERNAME})"
        d.text(((W - d.textlength(sub_t, font=self.font_badge)) // 2, y_off + 88), sub_t, font=self.font_badge, fill=(42, 171, 238, 255))

        overlay.save(out_png, "PNG")

    def _build_ass(self, sub_events: List[Dict], out_ass: Path):
        primary = "&H000ADCFF"  # Фірмові жовті субтитри з чорною обводкою
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
        if not HAS_FFMPEG:
            raise RuntimeError("ffmpeg не встановлено")

        uid = uuid.uuid4().hex[:8]
        overlay_png = Config.TEMP_DIR / f"ov_{uid}.png"
        ass_file = Config.TEMP_DIR / f"sub_{uid}.ass"
        bg_img_file = Config.TEMP_DIR / f"bg_{uid}.jpg"

        self._build_overlay(parsed, overlay_png)
        self._build_ass(sub_events, ass_file)

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
                            nw = int(oh * tr)
                            c_box = ((ow - nw) // 2, 0, (ow + nw) // 2, oh)
                        else:
                            nh = int(ow / tr)
                            c_box = (0, (oh - nh) // 2, ow, (oh + nh) // 2)
                        im_crop = im.crop(c_box).resize((Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT))
                        dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, 115))
                        im_crop.paste(dim, (0, 0), dim)
                        im_crop.save(bg_img_file, "JPEG", quality=92)
                except Exception:
                    bg_img_file = None

        if not is_video_media and (not bg_img_file or not bg_img_file.exists()):
            bg_img_file = Config.TEMP_DIR / f"bg_{uid}.jpg"
            self._create_branded_bg(bg_img_file)

        try:
            if is_video_media:
                fc = (
                    f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=4:1,scale={Config.VIDEO_WIDTH}:{Config.VIDEO_HEIGHT},setsar=1,drawbox=x=0:y=0:w={Config.VIDEO_WIDTH}:h={Config.VIDEO_HEIGHT}:color=black@0.48:t=fill[bg];"
                    f"[0:v]scale=1000:1880:force_original_aspect_ratio=decrease,setsar=1[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2-20[comp];[comp][2:v]overlay=0:0,ass={ass_file.name}[outv]"
                )
                cmd = [
                    "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(media_path.resolve()),
                    "-i", str(audio_path.resolve()), "-i", str(overlay_png.resolve()),
                    "-filter_complex", fc, "-map", "[outv]", "-map", "1:a",
                    "-t", f"{duration:.2f}", "-r", str(Config.VIDEO_FPS),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-threads", "2", "-movflags", "+faststart", str(out_file.resolve())
                ]
            else:
                fc = f"[0:v][2:v]overlay=0:0,ass={ass_file.name}[outv]"
                cmd = [
                    "ffmpeg", "-y", "-loop", "1", "-framerate", str(Config.VIDEO_FPS),
                    "-i", str(bg_img_file.resolve()), "-i", str(audio_path.resolve()), "-i", str(overlay_png.resolve()),
                    "-filter_complex", fc, "-map", "[outv]", "-map", "1:a",
                    "-t", f"{duration:.2f}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-tune", "stillimage", "-crf", "26", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-threads", "2", "-movflags", "+faststart",
                    str(out_file.resolve())
                ]

            proc = subprocess.run(cmd, cwd=str(Config.TEMP_DIR), capture_output=True, text=True, timeout=240)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg: {proc.stderr[-400:]}")
        finally:
            for tmp in [overlay_png, ass_file, bg_img_file]:
                if tmp and tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass

    def _create_branded_bg(self, out_path: Path):
        w, h = Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT
        top, bot = (10, 20, 50), (2, 5, 15)

        base = Image.new("RGB", (w, h))
        px = base.load()
        for y in range(h):
            t = y / h
            px_row = (int(top[0]*(1-t) + bot[0]*t), int(top[1]*(1-t) + bot[1]*t), int(top[2]*(1-t) + bot[2]*t))
            for x in range(w):
                px[x, y] = px_row

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        colors = [(40, 150, 255), (100, 80, 255)]

        for i in range(4):
            cx, cy = w // 2, h // 2
            r = 300 + i * 150
            od.arc([cx-r, cy-r, cx+r, cy+r], start=random.randint(0, 180), end=random.randint(180, 360), fill=random.choice(colors) + (random.randint(40, 80),), width=random.randint(15, 40))

        for _ in range(6):
            cx, cy = random.randint(-200, w+200), random.randint(-300, h+300)
            r = random.randint(200, 500)
            c = random.choice(colors)
            od.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*c, random.randint(20, 60)))

        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=80))
        base = Image.alpha_composite(base.convert("RGBA"), overlay)

        grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
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
def _worker_single(job_id: str, text: str, voice: str, saved_media: Optional[Path]):
    def _set(**kw):
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(kw)

    try:
        _set(step="⏳ Озвучую новину та формую субтитри...", progress=25)
        parsed = parse_post(text)
        uid = uuid.uuid4().hex[:8]
        temp_audio, temp_vtt = Config.TEMP_DIR / f"a_{uid}.mp3", Config.TEMP_DIR / f"a_{uid}.vtt"

        audio_path, duration, vtt_path = TTSEngine.generate(parsed["voiceover"], temp_audio, voice, temp_vtt)
        sub_events = TTSEngine.get_grouped_subtitles(vtt_path, parsed["voiceover"], duration)

        _set(step="🎬 Монтую відео у форматі Full HD 9:16...", progress=65)
        out_file = Config.OUTPUT_DIR / f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uid}.mp4"
        VideoEngine().render(parsed, audio_path, sub_events, out_file, duration, saved_media)

        for tmp in [temp_audio, temp_vtt]:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass

        _set(
            step="✅ Відео готове!",
            progress=100,
            done=True,
            finished_at=time.time(),
            result={
                "video_url": f"/videos/{out_file.name}",
                "seo_desc": parsed["seo_desc"],
                "ready_comment": parsed["ready_comment"],
                "reply_plus": parsed["reply_plus"],
            }
        )
    except Exception as e:
        _set(error=str(e), done=True, step=f"❌ {e}")
    finally:
        if saved_media and saved_media.exists():
            try:
                saved_media.unlink()
            except Exception:
                pass
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
                if (now - f.stat().st_mtime) > Config.VIDEO_TTL_SECONDS:
                    f.unlink()
        except Exception:
            pass
        time.sleep(1800)

threading.Thread(target=_cleanup_worker, daemon=True).start()

# =============================================================
# FASTAPI ROUTES
# =============================================================
app = FastAPI(title="News Studio 365")

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
.wrap { max-width: 820px; margin: 0 auto; padding: 30px 20px 60px; }
header { text-align: center; margin-bottom: 30px; }
h1 { font-size: clamp(26px, 4vw, 38px); font-weight: 900; background: linear-gradient(120deg, #fff, #8CC7FF, #FFBEE9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
.subtitle { color: var(--txt-dim); font-size: 15px; font-weight: 500; }
.box { background: var(--card); border: 1px solid var(--border); border-radius: 24px; padding: 26px; backdrop-filter: blur(24px); box-shadow: 0 20px 80px rgba(0,0,0,0.4); }
textarea { width: 100%; height: 165px; background: rgba(0,0,0,0.35); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; color: var(--txt); font-size: 15px; resize: vertical; outline: none; transition: .2s; font-family: inherit; }
textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(42, 171, 238, 0.15); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; background: rgba(0,0,0,0.25); padding: 14px 20px; border-radius: 14px; border: 1px solid var(--border); margin: 16px 0; }
label.opt { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; font-weight: 600; padding: 8px 16px; border-radius: 10px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); transition: .2s; }
label.opt:has(input:checked) { background: rgba(42,171,238,0.2); border-color: var(--blue); color: #fff; }
label.opt input { display: none; }
.drop { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; border: 2px dashed rgba(42, 171, 238, 0.5); border-radius: 16px; padding: 22px; cursor: pointer; text-align: center; background: rgba(42,171,238,0.05); margin: 16px 0; transition: .2s; }
.drop.dragover { border-color: var(--blue); background: rgba(42,171,238,0.15); transform: scale(1.01); }
.drop-icon { font-size: 26px; } .drop-text { font-size: 14px; font-weight: 600; } .drop-hint { font-size: 12px; color: var(--txt-dim); }
#mTxt { color: var(--blue); font-weight: 700; margin-top: 4px; font-size: 13px; }
.btn-go { width: 100%; padding: 18px; font-size: 16px; font-weight: 800; border: none; border-radius: 14px; cursor: pointer; color: #fff; background: linear-gradient(135deg, var(--blue), #7B3DD1); box-shadow: 0 12px 40px rgba(42, 171, 238, 0.35); transition: .3s; margin-top: 8px; }
.btn-go:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.1); }
.btn-go:disabled { opacity: 0.6; cursor: not-allowed; }
.progress-wrap { display: none; margin-top: 20px; background: rgba(0,0,0,0.4); border-radius: 10px; padding: 16px; }
#st { display: flex; justify-content: space-between; font-size: 14px; font-weight: 700; color: var(--gold); margin-bottom: 10px; }
.bar-bg { width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }
#bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--blue), var(--gold)); transition: width 0.4s ease; border-radius: 4px; }
.card { background: rgba(12, 17, 26, 0.85); border: 1px solid rgba(42, 171, 238, 0.35); border-radius: 20px; padding: 22px; margin-top: 28px; display: none; animation: slideUp .4s ease-out; }
.card.show { display: block; }
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 10px; font-size: 13px; font-weight: 800; margin-bottom: 14px; background: rgba(42, 171, 238, 0.15); color: var(--blue); border: 1px solid rgba(42, 171, 238, 0.3); }
video { width: 100%; max-height: 520px; border-radius: 14px; background: #000; border: 1px solid var(--border); display: block; }
.seo { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-top: 14px; }
.seo-head { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 800; color: var(--gold); margin-bottom: 10px; }
.copy-btn { background: rgba(255,255,255,0.06); border: 1px solid var(--border); color: var(--txt); padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; transition: .2s; }
.copy-btn:hover { background: rgba(255,255,255,0.15); }
.copy-btn.copied { background: var(--green); color: #000; }
.seo-text { font-size: 13px; color: #C8D2E2; white-space: pre-wrap; line-height: 1.6; }
.btn-dl { display: flex; align-items: center; justify-content: center; text-decoration: none; background: linear-gradient(135deg, var(--green), #1FB863); color: #051A0C; padding: 14px; border-radius: 12px; font-weight: 800; font-size: 14px; margin-top: 14px; box-shadow: 0 8px 24px rgba(46, 224, 122, 0.25); transition: .2s; }
.btn-dl:hover { transform: translateY(-1px); filter: brightness(1.1); }
.social-wrap { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border); display: none; }
.social-wrap.show { display: block; }
.social-title { font-size: 14px; font-weight: 800; margin-bottom: 12px; color: var(--txt); }
.social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.soc { padding: 13px; border-radius: 12px; text-align: center; text-decoration: none; font-weight: 800; font-size: 13px; transition: all .2s; display: flex; align-items: center; justify-content: center; gap: 6px; }
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
    <p class="subtitle">Повна новина з автосубтитрами та збором «+» у коментарях для переливу в Telegram.</p>
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

    <button class="btn-go" id="btn" onclick="genVideo()">🚀 Змонтувати відео</button>

    <div class="progress-wrap" id="progWrap">
      <div id="st">Ініціалізація... <span id="progTxt">0%</span></div>
      <div class="bar-bg"><div id="bar-fill"></div></div>
    </div>

    <div class="card" id="cardRes">
      <span class="badge">📰 Готове відео · NEWS УКРАЇНА 365</span>
      <video id="vidRes" controls playsinline></video>
      <a id="dlRes" class="btn-dl" download>⬇ Скачати MP4</a>

      <div class="seo">
        <div class="seo-head"><span>🔥 SEO-опис</span><button class="copy-btn" onclick="copyText('seoRes', this)">📋 Копіювати</button></div>
        <div class="seo-text" id="seoRes"></div>
      </div>

      <div class="seo" style="border-color: rgba(42, 171, 238, 0.35);">
        <div class="seo-head" style="color:var(--blue);"><span>📌 Закріплений коментар (збір «+»)</span><button class="copy-btn" onclick="copyText('comRes', this)">📋 Копіювати</button></div>
        <div class="seo-text" id="comRes"></div>
      </div>

      <div class="seo" style="border-color: rgba(46, 224, 122, 0.35);">
        <div class="seo-head" style="color:var(--green);"><span>💬 Відповідь людям на «+» у коментарях</span><button class="copy-btn" onclick="copyText('repRes', this)">📋 Копіювати</button></div>
        <div class="seo-text" id="repRes"></div>
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

async function genVideo() {
  const btn = document.getElementById('btn'), pWrap = document.getElementById('progWrap');
  const txt = document.getElementById('pTxt').value.trim();
  const voice = document.querySelector('input[name="voice"]:checked').value;
  if (!txt) { toast('Введіть текст!', 'err'); return; }

  btn.disabled = true;
  document.getElementById('cardRes').classList.remove('show');
  document.getElementById('socPanel').classList.remove('show');
  pWrap.style.display = 'block';
  document.getElementById('bar-fill').style.width = '5%';
  document.getElementById('st').innerHTML = '⏳ Підготовка... <span id="progTxt">5%</span>';

  try {
    const fd = new FormData();
    fd.append('text', txt);
    fd.append('voice', voice);
    if (selectedFile) fd.append('media_file', selectedFile);

    const startRes = await fetch('/api/start', { method: 'POST', body: fd });
    if (!startRes.ok) throw new Error('Помилка старту');
    const { job_id } = await startRes.json();

    while (true) {
      await new Promise(r => setTimeout(r, 1500));
      const pollRes = await fetch('/api/job/' + job_id);
      const job = await pollRes.json();

      if (job.progress !== undefined) document.getElementById('bar-fill').style.width = job.progress + '%';
      document.getElementById('st').innerHTML = (job.step || 'Монтую...') + ` <span id="progTxt">${job.progress || 0}%</span>`;

      if (job.error) throw new Error(job.error);
      if (job.done && job.result) {
        document.getElementById('vidRes').src = job.result.video_url;
        document.getElementById('dlRes').href = job.result.video_url;
        document.getElementById('seoRes').textContent = job.result.seo_desc;
        document.getElementById('comRes').textContent = job.result.ready_comment;
        document.getElementById('repRes').textContent = job.result.reply_plus;
        document.getElementById('cardRes').classList.add('show');
        document.getElementById('socPanel').classList.add('show');
        toast('✅ Відео готове!', 'ok');
        pWrap.style.display = 'none';
        break;
      }
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err');
    pWrap.style.display = 'none';
  } finally {
    btn.disabled = false;
  }
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

@app.post("/api/start")
async def api_start(text: Optional[str] = Form(None), voice: Optional[str] = Form("uk-UA-PolinaNeural"), media_file: Optional[UploadFile] = File(None)):
    if not text or not text.strip():
        text = "У Чорноморську троє загиблих через удар по ринку. Повідомили в ОВА."
    saved_media = None
    if media_file and media_file.filename:
        ext = Path(media_file.filename).suffix.lower() or ".mp4"
        saved_media = Config.TEMP_DIR / f"upload_{uuid.uuid4().hex[:8]}{ext}"
        with open(saved_media, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)

    job_id = uuid.uuid4().hex[:10]
    with JOBS_LOCK:
        JOBS[job_id] = {"step": "Ініціалізація...", "progress": 5, "result": None, "done": False, "error": None, "created": time.time()}
    threading.Thread(target=_worker_single, args=(job_id, text, voice or "uk-UA-PolinaNeural", saved_media), daemon=True).start()
    return {"job_id": job_id}

@app.get("/api/job/{job_id}")
async def api_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return job

@app.get("/videos/{filename}")
async def get_vid(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        return JSONResponse(status_code=400, content={"error": "Bad filename"})
    p = Config.OUTPUT_DIR / filename
    return FileResponse(p, media_type="video/mp4") if p.exists() else JSONResponse(status_code=404, content={"error": "Not found"})
