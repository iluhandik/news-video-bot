import os
import math
import random
from pathlib import Path
from typing import Dict, List
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip, AudioFileClip, VideoFileClip
from config import Config

class VideoEngine:
    """
    Генерує вертикальне відео 1080x1920 (9:16) для TikTok, Reels та YouTube Shorts:
    - Стильний динамічний темний фон із рухомим світлом та сіткою
    - Реалістична плашка посту Telegram із логотипом та верифікацією
    - Динамічні великі субтитри (жовто-білі з чорним контуром)
    - Мега-байт CTA-банер для підписки на канал
    - Накладання аудіодоріжки
    """

    def __init__(self):
        self.width = Config.VIDEO_WIDTH
        self.height = Config.VIDEO_HEIGHT
        self.fps = Config.VIDEO_FPS

        # Завантаження шрифтів
        font_path = Config.FONTS_DIR / "font_bold.ttf"
        if not font_path.exists():
            font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

        self.font_path = str(font_path)
        self.font_title = ImageFont.truetype(self.font_path, 38)
        self.font_header = ImageFont.truetype(self.font_path, 32)
        self.font_sub = ImageFont.truetype(self.font_path, 22)
        self.font_body = ImageFont.truetype(self.font_path, 28)
        self.font_cta = ImageFont.truetype(self.font_path, 28)
        self.font_cta_small = ImageFont.truetype(self.font_path, 22)

    def _draw_rounded_rectangle(self, draw: ImageDraw.ImageDraw, xy, radius=24, fill=None, outline=None, width=1):
        x1, y1, x2, y2 = xy
        draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline, width=width)

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 3) -> List[str]:
        words = text.split()
        lines = []
        cur_line = []
        dummy_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy_img)

        for w in words:
            test_line = " ".join(cur_line + [w])
            if draw.textlength(test_line, font=font) <= max_width:
                cur_line.append(w)
            else:
                if cur_line:
                    lines.append(" ".join(cur_line))
                cur_line = [w]
            if len(lines) >= max_lines:
                break
        if cur_line and len(lines) < max_lines:
            lines.append(" ".join(cur_line))
        return lines

    def create_telegram_card(self, headline: str, body: str) -> Image.Image:
        """
        Створює піксель-перфектний макет темного повідомлення Telegram
        """
        card_w, card_h = 960, 500
        img = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Фонова плашка у стилі Telegram Dark Theme
        self._draw_rounded_rectangle(
            draw, (0, 0, card_w, card_h),
            radius=26,
            fill=(23, 33, 43, 245),
            outline=(45, 65, 90, 255),
            width=2
        )

        # 1. Аватарка каналу (синій градієнт із літачком)
        avatar_r = 38
        ax, ay = 36, 32
        draw.ellipse([ax, ay, ax + avatar_r*2, ay + avatar_r*2], fill=(42, 171, 238, 255))
        # Силует паперового літачка
        pts = [(ax + 22, ay + 40), (ax + 58, ay + 22), (ax + 40, ay + 58), (ax + 34, ay + 44)]
        draw.polygon(pts, fill=(255, 255, 255, 255))

        # 2. Назва каналу + синій бейдж верифікації
        draw.text((ax + avatar_r*2 + 18, ay + 6), Config.CHANNEL_DISPLAY_NAME, font=self.font_title, fill=(255, 255, 255, 255))
        
        name_len = int(draw.textlength(Config.CHANNEL_DISPLAY_NAME, font=self.font_title))
        badge_x = ax + avatar_r*2 + 18 + name_len + 10
        badge_y = ay + 12
        draw.ellipse([badge_x, badge_y, badge_x + 24, badge_y + 24], fill=(42, 171, 238, 255))
        draw.text((badge_x + 5, badge_y + 2), "✓", font=self.font_sub, fill=(255, 255, 255, 255))

        # Юзернейм та позначка часу
        draw.text((ax + avatar_r*2 + 18, ay + 48), f"{Config.CHANNEL_USERNAME} • щойно", font=self.font_sub, fill=(120, 140, 160, 255))

        # Розділювальна тонка лінія
        draw.line([(36, 125), (card_w - 36, 125)], fill=(40, 55, 75, 220), width=1)

        # 3. Заголовок новини (жовтий акцент, із переносом слів)
        head_lines = self._wrap_text(headline, self.font_header, max_width=card_w - 72, max_lines=2)
        cur_y = 145
        for hl in head_lines:
            draw.text((36, cur_y), hl, font=self.font_header, fill=(255, 220, 40, 255))
            cur_y += 38

        # 4. Тіло новини
        cur_y += 8
        body_lines = self._wrap_text(body, self.font_body, max_width=card_w - 72, max_lines=3)
        for bl in body_lines:
            draw.text((36, cur_y), bl, font=self.font_body, fill=(230, 235, 245, 255))
            cur_y += 36

        # 5. Нижній бар переглядів
        foot_y = card_h - 44
        draw.ellipse([36, foot_y + 4, 52, foot_y + 16], outline=(120, 140, 165, 255), width=2)
        draw.ellipse([41, foot_y + 7, 47, foot_y + 13], fill=(120, 140, 165, 255))
        draw.text((60, foot_y), "148.5K", font=self.font_sub, fill=(120, 140, 165, 255))

        draw.text((card_w - 160, foot_y), "➔ 24.3K", font=self.font_sub, fill=(120, 140, 165, 255))

        return img

    def create_cta_banner(self) -> Image.Image:
        """
        Створює контрастний банер заклику до підписки внизу екрана
        """
        w, h = 960, 150
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Червоно-бордова плашка уваги з золотою рамкою
        self._draw_rounded_rectangle(
            draw, (0, 0, w, h),
            radius=24,
            fill=(210, 25, 35, 250),
            outline=(255, 215, 60, 255),
            width=3
        )

        cta_title = "УВАГА: ПОВНЕ ВІДЕО ТА ДЕТАЛІ В ШАПЦІ ПРОФІЛЮ"
        cta_sub = ">>> Посилання на канал закріплено в описі та коментарях <<<"

        tw = draw.textlength(cta_title, font=self.font_cta)
        draw.text(((w - tw) / 2, 32), cta_title, font=self.font_cta, fill=(255, 255, 255, 255))

        sw = draw.textlength(cta_sub, font=self.font_cta_small)
        draw.text(((w - sw) / 2, 88), cta_sub, font=self.font_cta_small, fill=(255, 245, 180, 255))

        return img

    def render_subtitle_image(self, text: str) -> Image.Image:
        """
        Рендерить динамічні субтитри з адаптивним розміром шрифту
        """
        w, h = 1000, 220
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        up_text = text.upper()
        # Адаптивний розмір шрифту
        font_size = 54
        font = ImageFont.truetype(self.font_path, font_size)
        while draw.textlength(up_text, font=font) > (w - 60) and font_size > 32:
            font_size -= 4
            font = ImageFont.truetype(self.font_path, font_size)

        tw = draw.textlength(up_text, font=font)
        tx = max(20, (w - tw) / 2)
        ty = (h - font_size) // 2

        # Чорний контур 4px навколо букв для контрасту
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                if dx*dx + dy*dy <= 16:
                    draw.text((tx + dx, ty + dy), up_text, font=font, fill=(0, 0, 0, 255))

        # Яскраво-жовтий колір
        draw.text((tx, ty), up_text, font=font, fill=(255, 235, 20, 255))
        return img

    def render_video(self, script_data: Dict[str, str], audio_path: Path, subtitle_events: List[Dict], output_file: Path) -> Path:
        """
        Основний конвеєр збірки відео
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration

        tg_card = self.create_telegram_card(script_data["headline"], script_data["body"])
        cta_card = self.create_cta_banner()

        card_x = (self.width - tg_card.width) // 2
        card_y = 220

        cta_x = (self.width - cta_card.width) // 2
        cta_y = self.height - cta_card.height - 180

        sub_y = 1120

        # Кеш субтитрів
        sub_cache = {}
        for ev in subtitle_events:
            txt = ev["text"]
            if txt not in sub_cache:
                sub_cache[txt] = self.render_subtitle_image(txt)

        def make_frame(t):
            # Фон: глибокий темно-синій градієнт із сіткою та м'яким рухом
            frame = Image.new("RGBA", (self.width, self.height), (8, 12, 18, 255))
            draw = ImageDraw.Draw(frame)

            # Сітка
            for y_line in range(0, self.height, 90):
                draw.line([(0, y_line), (self.width, y_line)], fill=(15, 22, 34, 255), width=1)
            for x_line in range(0, self.width, 90):
                draw.line([(x_line, 0), (x_line, self.height)], fill=(15, 22, 34, 255), width=1)

            # М'яка розсіяна світлова пляма
            light_y = int(950 + 100 * math.sin(t * 1.5))
            draw.ellipse([self.width//2 - 400, light_y - 300, self.width//2 + 400, light_y + 300], fill=(18, 35, 65, 80))

            # Картка Telegram
            frame.alpha_composite(tg_card, (card_x, card_y))

            # Субтитри
            active_sub = None
            for ev in subtitle_events:
                if ev["start"] <= t <= ev["end"]:
                    active_sub = sub_cache.get(ev["text"])
                    break

            if active_sub:
                sub_x = (self.width - active_sub.width) // 2
                frame.alpha_composite(active_sub, (sub_x, sub_y))

            # Пульсуючий CTA банер
            pulse = int(3 * math.sin(t * 5.0))
            frame.alpha_composite(cta_card, (cta_x, cta_y + pulse))

            return np.array(frame.convert("RGB"))

        print(f"[VideoEngine] Рендеринг ролика тривалістю {duration:.1f} сек на {self.fps} FPS...")
        video_clip = VideoClip(make_frame, duration=duration)
        video_clip = video_clip.with_audio(audio_clip)

        video_clip.write_videofile(
            str(output_file),
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=4,
            logger=None
        )

        audio_clip.close()
        video_clip.close()

        print(f"[VideoEngine] Відео успішно згенеровано: {output_file}")
        return output_file
