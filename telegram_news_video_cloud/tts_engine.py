import os
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple
from config import Config

class TTSEngine:
    """
    Генерує реалістичну озвучку українською мовою та розраховує таймінги субтитрів.
    Підтримує Edge-TTS (безкоштовно та високоякісно) з голосами:
    - uk-UA-OstapNeural (енергійний чоловічий диктор новин)
    - uk-UA-PolinaNeural (чіткий жіночий голос)
    """

    @classmethod
    def generate_voiceover(cls, text: str, output_path: Path) -> Tuple[Path, float]:
        """
        Генерує MP3/WAV файл озвучки та повертає (шлях, тривалість у секундах).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Спроба генерації через edge-tts (якщо бібліотека доступна і є з\'єднання)
        success = False
        try:
            cmd = [
                "edge-tts",
                "--voice", Config.VOICE_NAME,
                "--rate", Config.VOICE_RATE,
                "--text", text,
                "--write-media", str(output_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 100:
                success = True
        except Exception:
            success = False

        # Резервна генерація через FFmpeg синтезатор звуку (якщо немає інтернету/edge-tts)
        if not success:
            cls._generate_fallback_audio(text, output_path)

        duration = cls._get_audio_duration(output_path)
        return output_path, duration

    @classmethod
    def _generate_fallback_audio(cls, text: str, output_path: Path):
        """
        Генерує резервну аудіодоріжку (пульсуючий новинний тон) для автономної роботи без мережі.
        """
        # Середня швидкість мовлення диктора ~ 14 символів на секунду
        duration = max(8.0, min(25.0, len(text) / 14.0))
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=440:beep_factor=4:duration={duration}",
            "-filter:a", "volume=0.3",
            str(output_path)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def _get_audio_duration(cls, file_path: Path) -> float:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(res.stdout.strip())
        except Exception:
            return 15.0

    @classmethod
    def generate_subtitle_chunks(cls, text: str, total_duration: float) -> List[Dict]:
        """
        Розбиває текст на динамічні фрази по 2-4 слова (стиль Shorts/Reels)
        і розподіляє таймінги на загальну тривалість відео.
        """
        words = text.split()
        if not words:
            return []

        # Групуємо по 3 слова
        chunk_size = 3
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunk_words = words[i:i + chunk_size]
            chunks.append(" ".join(chunk_words))

        time_per_chunk = total_duration / len(chunks)
        subtitle_events = []
        
        current_time = 0.0
        for chunk in chunks:
            start_t = current_time
            end_t = min(total_duration, current_time + time_per_chunk)
            subtitle_events.append({
                "text": chunk,
                "start": start_t,
                "end": end_t
            })
            current_time = end_t

        return subtitle_events
