import os
import re
import gc
import time
import uuid
import shutil
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from PIL import Image, ImageDraw, ImageFont

class Config:
    CHANNEL_DISPLAY_NAME = "NEWS УКРАЇНА 365"
    CHANNEL_BAIT_WATERMARK = "NEWS УКРАЇНА 365 | ЕКСКЛЮЗИВ"
    CHANNEL_USERNAME = "@kropivnit"
    VOICE_NAME = "uk-UA-PolinaNeural"
    VIDEO_WIDTH = 1080
    VIDEO_HEIGHT = 1920
    VIDEO_FPS = 25
    BASE_DIR = Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"

Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

JOBS: Dict[str, Dict] = {}

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

    elif has_word(t, ["обстріл", "удар", "ракета", "шахед", "приліт", "ринок", "вибух", "евакуац", "атакув"]):
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
    elif has_word(combined, ["чорноморськ", "одес", "удар", "ринок", "загибл", "евакуац", "рятув"]):
        tags = ["#обстріл", "#новиниукраїни", "#війна", "#герої", "#рятувальники"]
        q = "Повне відео без блюру та деталі вже в нашому ТГ (посилання в шапці) 👇" if mode == "bait" else "Сили та здоров'я постраждалим! Бережіть себе 👇"
    elif has_word(combined, ["світл", "електр", "блекаут", "дтек", "графік"]):
        tags = ["#відключеннясвітла", "#світло", "#блекаут", "#дтек", "#графіки"]
        q = "Повний графік по кожному району вже в нашому ТГ в шапці профілю! 👇" if mode == "bait" else "Як у вас зараз зі світлом? Пишіть у коментарях 👇"
    else:
        tags = ["#терміново", "#важливо", "#новиниукраїни", "#резонанс"]
        q = "Повні кадри та деталі, які видаляє ТікТок, вже у нашому ТГ в шапці профілю 👇" if mode == "bait" else "Яка ваша думка щодо цієї новини? Обговорюємо в коментарях 👇"

    rec_tags = ["#новини", "#україна", "#рек", "#рекомендації", "#хочуврек", "#тренди"]
    if mode == "bait":
        rec_tags.append("#ексклюзив")
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
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
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
        other_lines = []
        full_body = ""

    combined_for_cta = f"{headline} {full_body}"
    adaptive = get_adaptive_cta(combined_for_cta, mode)
    cta = adaptive["voice_cta"]

    if mode == "bait":
        teaser = other_lines[0] if other_lines else ""
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
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
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
        clean_words = sanitize_text(text).split()
        display_words = ["NEWS" if w.lower() == "ньюз" else w for w in clean_words]

        chunks = [" ".join(display_words[i:i+2]) for i in range(0, len(display_words), 2)]
        t_chunk = dur / max(1, len(chunks))
        return [{"text": c, "start": i*t_chunk, "end": (i+1)*t_chunk} for i, c in enumerate(chunks)]

def _fmt_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec - int(sec)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

class VideoEngine:
    def __init__(self):
        font_p = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        self.font_path = str(font_p)
        self.font_badge = ImageFont.truetype(self.font_path, 26)
        self.font_head = ImageFont.truetype(self.font_path, 38)
        self.font_cta = ImageFont.truetype(self.font_path, 28)
        self.font_watermark = ImageFont.truetype(self.font_path, 26)

    def _build_overlay(self, parsed: Dict, out_png: Path, is_bait: bool):
        overlay = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(overlay)
        t_draw.rectangle([0, 220, Config.VIDEO_WIDTH, 520], fill=(5, 8, 14, 195))

        if is_bait:
            t_draw.rounded_rectangle([40, 260, 300, 320], radius=12, fill=(255, 165, 0, 255))
            t_draw.text((55, 272), "ЕКСКЛЮЗИВ", font=self.font_badge, fill=(0, 0, 0, 255))
            wm = Config.CHANNEL_BAIT_WATERMARK
            wm_fill = (200, 30, 45, 240)
        else:
            t_draw.rounded_rectangle([40, 260, 280, 320], radius=12, fill=(225, 25, 35, 255))
            t_draw.text((55, 272), "ТЕРМІНОВО", font=self.font_badge, fill=(255, 255, 255, 255))
            wm = Config.CHANNEL_DISPLAY_NAME
            wm_fill = (120, 50, 210, 240)

        wm_w = int(t_draw.textlength(wm, font=self.font_watermark))
        t_draw.rounded_rectangle([Config.VIDEO_WIDTH - wm_w - 70, 260, Config.VIDEO_WIDTH - 40, 320], radius=12, fill=wm_fill, outline=(255, 255, 255, 200), width=2)
        t_draw.text((Config.VIDEO_WIDTH - wm_w - 55, 274), wm, font=self.font_watermark, fill=(255, 255, 255, 255))

        clean_headline = sanitize_text(parsed["headline"])
        h_lines = wrap_text_lines(clean_headline, self.font_head, Config.VIDEO_WIDTH - 80)
        cur_hy = 345
        for hl in h_lines[:2]:
            t_draw.text((40, cur_hy), hl, font=self.font_head, fill=(255, 255, 255, 255))
            cur_hy += 48
        line_col = (255, 80, 80, 240) if is_bait else (255, 215, 0, 240)
        t_draw.line([(40, cur_hy + 8), (Config.VIDEO_WIDTH - 40, cur_hy + 8)], fill=line_col, width=3)

        y_off = 1360
        if is_bait:
            t_draw.rounded_rectangle([40, y_off + 20, Config.VIDEO_WIDTH - 40, y_off + 140], radius=20, fill=(200, 25, 35, 245), outline=(255, 215, 0, 255), width=3)
            c_txt = "ПОВНЕ ВІДЕО БЕЗ ЦЕНЗУРИ В ШАПЦІ ПРОФІЛЮ ➔"
            sub_col = (255, 245, 180, 255)
        else:
            t_draw.rounded_rectangle([40, y_off + 20, Config.VIDEO_WIDTH - 40, y_off + 140], radius=20, fill=(18, 25, 38, 245), outline=(42, 171, 238, 255), width=2)
            c_txt = "ПОВНІ ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ ➔"
            sub_col = (42, 171, 238, 255)

        cw = t_draw.textlength(c_txt, font=self.font_cta)
        t_draw.text(((Config.VIDEO_WIDTH - cw) // 2, y_off + 42), c_txt, font=self.font_cta, fill=(255, 255, 255, 255))
        sub_t = f"Telegram: {Config.CHANNEL_DISPLAY_NAME}"
        t_draw.text(((Config.VIDEO_WIDTH - t_draw.textlength(sub_t, font=self.font_badge)) // 2, y_off + 88), sub_t, font=self.font_badge, fill=sub_col)

        overlay.save(out_png, "PNG")

    def _build_ass(self, sub_events: List[Dict], out_ass: Path, is_bait: bool):
        primary_col = "&H00FFFFFF" if is_bait else "&H000ADCFF"
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {Config.VIDEO_WIDTH}\n"
            f"PlayResY: {Config.VIDEO_HEIGHT}\n"
            "WrapStyle: 0\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,DejaVu Sans,68,{primary_col},&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,40,40,700,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
        lines = [header]
        for e in sub_events:
            txt = sanitize_text(e["text"]).upper().replace("\n", " ")
            if not txt:
                continue
            lines.append(f"Dialogue: 0,{_fmt_ass_time(e['start'])},{_fmt_ass_time(e['end'])},Default,,0,0,0,,{txt}\n")
        out_ass.write_text("".join(lines), encoding="utf-8")

    def render(self, parsed: Dict, audio_path: Path, sub_events: List[Dict], out_file: Path, duration: float, media_path: Optional[Path] = None):
        is_bait = (parsed["mode"] == "bait")
        uid = uuid.uuid4().hex[:8]
        overlay_png = Config.TEMP_DIR / f"ov_{uid}.png"
        ass_file = Config.TEMP_DIR / f"sub_{uid}.ass"
        bg_img_file = Config.TEMP_DIR / f"bg_{uid}.jpg"

        self._build_overlay(parsed, overlay_png, is_bait)
        self._build_ass(sub_events, ass_file, is_bait)

        is_video = False
        if media_path and media_path.exists():
            ext = media_path.suffix.lower()
            if ext in [".mp4", ".mov", ".webm", ".avi", ".mkv"]:
                is_video = True
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
                    dim_alpha = 135 if is_bait else 110
                    dim = Image.new("RGBA", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), (6, 10, 18, dim_alpha))
                    im_crop.paste(dim, (0, 0), dim)
                    im_crop.save(bg_img_file, "JPEG", quality=92)
                except Exception:
                    bg_img_file = None

        if not is_video and (not bg_img_file or not bg_img_file.exists()):
            bg_img_file = Config.TEMP_DIR / f"bg_{uid}.jpg"
            bg_color = (22, 14, 24) if is_bait else (16, 22, 34)
            Image.new("RGB", (Config.VIDEO_WIDTH, Config.VIDEO_HEIGHT), bg_color).save(bg_img_file, "JPEG", quality=90)

        try:
            if is_video:
                target_w = 1020 if is_bait else 1000
                dim_val = "0.56" if is_bait else "0.46"
                fc = (
                    f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                    f"boxblur=4:1,scale={Config.VIDEO_WIDTH}:{Config.VIDEO_HEIGHT},setsar=1,"
                    f"drawbox=x=0:y=0:w={Config.VIDEO_WIDTH}:h={Config.VIDEO_HEIGHT}:color=black@{dim_val}:t=fill[bg];"
                    f"[0:v]scale={target_w}:1880:force_original_aspect_ratio=decrease,setsar=1[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2-20[comp];"
                    f"[comp][2:v]overlay=0:0,ass={ass_file.name}[outv]"
                )
                cmd = [
                    "ffmpeg", "-y",
                    "-stream_loop", "-1", "-i", str(media_path.resolve()),
                    "-i", str(audio_path.resolve()),
                    "-i", str(overlay_png.resolve()),
                    "-filter_complex", fc,
                    "-map", "[outv]", "-map", "1:a",
                    "-t", f"{duration:.2f}",
                    "-r", str(Config.VIDEO_FPS),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-threads", "2", "-movflags", "+faststart",
                    str(out_file.resolve())
                ]
            else:
                fc = f"[0:v][2:v]overlay=0:0,ass={ass_file.name}[outv]"
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(Config.VIDEO_FPS), "-i", str(bg_img_file.resolve()),
                    "-i", str(audio_path.resolve()),
                    "-i", str(overlay_png.resolve()),
                    "-filter_complex", fc,
                    "-map", "[outv]", "-map", "1:a",
                    "-t", f"{duration:.2f}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", "26",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-threads", "2", "-movflags", "+faststart",
                    str(out_file.resolve())
                ]

            proc = subprocess.run(cmd, cwd=str(Config.TEMP_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr[-500:] if proc.stderr else "ffmpeg error")
        finally:
            for tmp in [overlay_png, ass_file, bg_img_file]:
                if tmp and tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass

        return out_file

def _generate_single(text: str, voice: str, mode: str, media_path: Optional[Path]) -> Dict:
    parsed = parse_post(text, mode)
    temp_audio = Config.TEMP_DIR / f"v_{mode}_{uuid.uuid4().hex[:8]}.mp3"
    audio_path, duration = TTSEngine.generate(parsed["voiceover"], temp_audio, voice)
    sub_events = TTSEngine.chunks(parsed["voiceover"], duration)

    engine = VideoEngine()
    out_file = Config.OUTPUT_DIR / f"news_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.mp4"
    engine.render(parsed, audio_path, sub_events, out_file, duration, media_path)

    if temp_audio.exists():
        try:
            temp_audio.unlink()
        except Exception:
            pass
    gc.collect()

    return {
        "video_url": f"/videos/{out_file.name}",
        "seo_desc": parsed["seo_desc"],
        "ready_comment": parsed["ready_comment"]
    }

def _worker_both(job_id: str, text: str, voice: str, saved_media: Optional[Path]):
    try:
        JOBS[job_id]["step"] = "⏳ [1/2] Монтую відео для Акаунту 1 (Повна новина)..."
        res_full = _generate_single(text, voice, "full", saved_media)
        JOBS[job_id]["full"] = res_full

        JOBS[job_id]["step"] = "⏳ [2/2] Монтую відео для Акаунту 2 (100% Перелив у ТГ)..."
        res_bait = _generate_single(text, voice, "bait", saved_media)
        JOBS[job_id]["bait"] = res_bait

        JOBS[job_id]["step"] = "✅ Обидва відео готові!"
        JOBS[job_id]["done"] = True
    except Exception as e:
        JOBS[job_id]["error"] = str(e)
        JOBS[job_id]["done"] = True
    finally:
        if saved_media and saved_media.exists():
            try:
                saved_media.unlink()
            except Exception:
                pass
        gc.collect()

app = FastAPI(title="News Studio Dual-Account Pro")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>News Studio Dual Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #070A11; --card: #131A26; --accent: #2AABEE; --gold: #FFD233; --green: #2ED573; --red: #FF3B30; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: #fff; min-height: 100vh; padding: 25px 15px; }
        .wrap { max-width: 1100px; margin: 0 auto; }
        header { text-align: center; margin-bottom: 20px; }
        h1 { font-size: 26px; font-weight: 800; }
        .box { background: var(--card); border: 1px solid #232E42; border-radius: 20px; padding: 24px; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }
        textarea { width: 100%; height: 140px; background: #0A0E17; border: 1px solid #232E42; border-radius: 12px; padding: 14px; color: #fff; font-size: 15px; outline: none; margin-bottom: 12px; resize: vertical; }
        .select-row { display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 14px; background: #0A0E17; padding: 12px 16px; border-radius: 12px; border: 1px solid #232E42; align-items: center; }
        .select-label { font-size: 14px; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; }
        .drop { border: 2px dashed #2AABEE; border-radius: 12px; padding: 16px; text-align: center; cursor: pointer; color: #fff; font-size: 14px; margin-bottom: 14px; background: rgba(42, 171, 238, 0.05); }
        .btn-go { background: linear-gradient(135deg, #2AABEE, #0077B5); color: #fff; border: none; padding: 16px; border-radius: 12px; font-size: 16px; font-weight: 800; cursor: pointer; width: 100%; transition: 0.2s; }
        .btn-go:hover { filter: brightness(1.1); }
        .btn-go:disabled { opacity: 0.5; cursor: not-allowed; }
        #st { display: none; text-align: center; color: var(--gold); margin-top: 14px; font-weight: 700; font-size: 15px; }

        .dual-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 25px; }
        @media (max-width: 800px) { .dual-grid { grid-template-columns: 1fr; } }

        .res-card { background: #0D121D; border: 1px solid #232E42; border-radius: 18px; padding: 18px; display: none; }
        .res-card.bait { border-color: rgba(255, 59, 48, 0.5); }
        .res-badge { display: inline-block; padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 800; margin-bottom: 12px; }
        .badge-full { background: rgba(42, 171, 238, 0.2); color: #2AABEE; }
        .badge-bait { background: rgba(255, 59, 48, 0.2); color: #FF6B6B; }

        video { width: 100%; max-height: 460px; border-radius: 12px; background: #000; border: 1px solid #232E42; }
        
        .seo-box { background: #070A11; border: 1px solid #232E42; border-radius: 12px; padding: 14px; margin-top: 12px; }
        .seo-title { font-size: 13px; font-weight: 800; color: var(--gold); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
        .copy-btn { background: rgba(255,255,255,0.08); border: 1px solid #232E42; color: #fff; padding: 5px 10px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; }
        .copy-btn:hover { background: rgba(255,255,255,0.18); }
        .seo-text { font-size: 12px; color: #C5D1E0; white-space: pre-wrap; line-height: 1.45; }

        .btn-dl { display: block; text-align: center; background: var(--green); color: #000; text-decoration: none; padding: 12px; border-radius: 10px; font-weight: 800; font-size: 14px; margin-top: 12px; }
        .social-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin-top: 16px; }
        .soc-link { padding: 11px; border-radius: 10px; text-align: center; text-decoration: none; font-weight: 800; font-size: 13px; }
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
            <h1>🎬 Студія новин NEWS УКРАЇНА 365 (2 Акаунти)</h1>
            <p style="color:#8E9BAE; font-size:14px;">Один клік — 2 унікальних відео: повна новина (Акаунт 1) + перелив у ТГ (Акаунт 2)</p>
        </header>

        <div class="box">
            <textarea id="pTxt" placeholder="Вставте сюди пост новини..."></textarea>
            
            <div class="select-row">
                <span style="color:#8E9BAE; font-size:14px;">Голос диктора:</span>
                <label class="select-label"><input type="radio" name="voice" value="uk-UA-PolinaNeural" checked> Жіночий (Поліна)</label>
                <label class="select-label"><input type="radio" name="voice" value="uk-UA-OstapNeural"> Чоловічий (Остап)</label>
            </div>

            <div class="drop" onclick="document.getElementById('mFile').click()">
                📹 <b>Додайте ВІДЕО або фото з новини</b> (піде на обидва ролики)
                <input type="file" id="mFile" accept="video/*,image/*" style="display:none;" onchange="showF(this)">
                <div id="mTxt" style="color:var(--accent); font-weight:bold; margin-top:5px;"></div>
            </div>

            <button class="btn-go" id="btn" onclick="genBoth()">🚀 Змонтувати ОДРАЗУ 2 ВІДЕО</button>
            <div id="st"></div>

            <div class="dual-grid">
                <div class="res-card" id="cardFull">
                    <span class="res-badge badge-full">📰 Акаунт 1: Повна новина</span>
                    <video id="vidFull" controls></video>
                    <a id="dlFull" class="btn-dl" download>⬇ Скачати MP4 (Акаунт 1)</a>

                    <div class="seo-box">
                        <div class="seo-title">
                            <span>🔥 Опис та хештеги:</span>
                            <button class="copy-btn" onclick="copyText('seoFull')">📋 Копіювати</button>
                        </div>
                        <div class="seo-text" id="seoFull"></div>
                    </div>

                    <div class="seo-box" style="border-color: rgba(42, 171, 238, 0.4);">
                        <div class="seo-title" style="color:#2AABEE;">
                            <span>💬 Коментар під відео:</span>
                            <button class="copy-btn" onclick="copyText('comFull')">📋 Копіювати</button>
                        </div>
                        <div class="seo-text" id="comFull" style="color:#fff;"></div>
                    </div>
                </div>

                <div class="res-card bait" id="cardBait">
                    <span class="res-badge badge-bait">🔥 Акаунт 2: Перелив у ТГ</span>
                    <video id="vidBait" controls></video>
                    <a id="dlBait" class="btn-dl" download>⬇ Скачати MP4 (Акаунт 2)</a>

                    <div class="seo-box">
                        <div class="seo-title">
                            <span>🔥 Опис та хештеги:</span>
                            <button class="copy-btn" onclick="copyText('seoBait')">📋 Копіювати</button>
                        </div>
                        <div class="seo-text" id="seoBait"></div>
                    </div>

                    <div class="seo-box" style="border-color: rgba(255, 59, 48, 0.4);">
                        <div class="seo-title" style="color:#FF6B6B;">
                            <span>💬 Коментар під відео:</span>
                            <button class="copy-btn" onclick="copyText('comBait')">📋 Копіювати</button>
                        </div>
                        <div class="seo-text" id="comBait" style="color:#fff;"></div>
                    </div>
                </div>
            </div>

            <div id="socPanel" style="display:none; margin-top:20px; border-top:1px solid #232E42; padding-top:15px;">
                <div style="font-size:14px; font-weight:800; margin-bottom:10px;">🚀 Швидке вивантаження в соцмережі:</div>
                <div class="social-grid">
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

        async function genBoth() {
            const btn = document.getElementById('btn');
            const st = document.getElementById('st');
            const txt = document.getElementById('pTxt').value;
            const voice = document.querySelector('input[name="voice"]:checked').value;

            btn.disabled = true;
            document.getElementById('cardFull').style.display = 'none';
            document.getElementById('cardBait').style.display = 'none';
            document.getElementById('socPanel').style.display = 'none';
            st.style.display = 'block';
            st.innerText = '⏳ Завантажую файл і запускаю монтаж...';

            try {
                const fd = new FormData();
                fd.append('text', txt);
                fd.append('voice', voice);
                if(selectedFile) {
                    fd.append('media_file', selectedFile);
                }

                const startRes = await fetch('/api/start_both', { method: 'POST', body: fd });
                if (!startRes.ok) {
                    throw new Error("Помилка запуску (код " + startRes.status + ")");
                }
                const { job_id } = await startRes.json();

                let shownFull = false;
                let shownBait = false;

                while (true) {
                    await new Promise(r => setTimeout(r, 2000));
                    const pollRes = await fetch('/api/job/' + job_id);
                    if (!pollRes.ok) {
                        throw new Error("Помилка перевірки статусу (" + pollRes.status + ")");
                    }
                    const job = await pollRes.json();
                    st.innerText = job.step || '⏳ Монтую...';

                    if (job.full && !shownFull) {
                        shownFull = true;
                        document.getElementById('vidFull').src = job.full.video_url;
                        document.getElementById('dlFull').href = job.full.video_url;
                        document.getElementById('seoFull').innerText = job.full.seo_desc;
                        document.getElementById('comFull').innerText = job.full.ready_comment;
                        document.getElementById('cardFull').style.display = 'block';
                    }

                    if (job.bait && !shownBait) {
                        shownBait = true;
                        document.getElementById('vidBait').src = job.bait.video_url;
                        document.getElementById('dlBait').href = job.bait.video_url;
                        document.getElementById('seoBait').innerText = job.bait.seo_desc;
                        document.getElementById('comBait').innerText = job.bait.ready_comment;
                        document.getElementById('cardBait').style.display = 'block';
                    }

                    if (job.error) {
                        throw new Error(job.error);
                    }
                    if (job.done) {
                        document.getElementById('socPanel').style.display = 'block';
                        break;
                    }
                }
            } catch(e) {
                alert('Помилка: ' + e.message);
                st.style.display = 'none';
            } finally {
                btn.disabled = false;
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

@app.post("/api/start_both")
async def api_start_both(
    text: Optional[str] = Form(None),
    voice: Optional[str] = Form("uk-UA-PolinaNeural"),
    media_file: Optional[UploadFile] = File(None)
):
    if not text or not text.strip():
        text = "У Чорноморську троє загиблих через удар по ринку. Повідомили в ОВА."

    saved_media = None
    if media_file and media_file.filename:
        ext = Path(media_file.filename).suffix.lower() or ".mp4"
        saved_media = Config.TEMP_DIR / f"upload_{uuid.uuid4().hex[:8]}{ext}"
        with open(saved_media, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)

    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {
        "step": "⏳ [1/2] Готую озвучку та монтаж для Акаунту 1...",
        "full": None,
        "bait": None,
        "done": False,
        "error": None
    }

    t = threading.Thread(target=_worker_both, args=(job_id, text, voice or "uk-UA-PolinaNeural", saved_media), daemon=True)
    t.start()

    return {"job_id": job_id}

@app.get("/api/job/{job_id}")
async def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return job

@app.post("/api/generate")
async def api_generate(
    text: Optional[str] = Form(None),
    voice: Optional[str] = Form("uk-UA-PolinaNeural"),
    mode: Optional[str] = Form("full"),
    media_file: Optional[UploadFile] = File(None)
):
    if not text or not text.strip():
        text = "У Чорноморську троє загиблих через удар по ринку. Повідомили в ОВА."

    saved_media = None
    if media_file and media_file.filename:
        ext = Path(media_file.filename).suffix.lower() or ".mp4"
        saved_media = Config.TEMP_DIR / f"upload_{mode}_{uuid.uuid4().hex[:8]}{ext}"
        with open(saved_media, "wb") as buffer:
            shutil.copyfileobj(media_file.file, buffer)

    try:
        return _generate_single(text, voice or "uk-UA-PolinaNeural", mode or "full", saved_media)
    finally:
        if saved_media and saved_media.exists():
            try:
                saved_media.unlink()
            except Exception:
                pass

@app.get("/videos/{filename}")
async def get_vid(filename: str):
    p = Config.OUTPUT_DIR / filename
    if p.exists():
        return FileResponse(p, media_type="video/mp4")
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.get("/api/status")
async def status():
    return {"status": "ok"}
