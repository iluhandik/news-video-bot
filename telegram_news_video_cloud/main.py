import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

from config import Config
from telegram_listener import TelegramListener
from script_generator import ScriptGenerator
from tts_engine import TTSEngine
from video_engine import VideoEngine
from social_publisher import SocialPublisher

def process_single_news(raw_text: str, post_id: str = None) -> Path:
    print("=" * 60)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Обробка новини: {raw_text[:80]}...")

    script_data = ScriptGenerator.generate(raw_text)
    print(f" -> Заголовок: {script_data['headline']}")
    print(f" -> Хук: {script_data['hook']}")

    temp_audio = Config.TEMP_DIR / f"voice_{int(time.time())}.mp3"
    audio_path, duration = TTSEngine.generate_voiceover(script_data["full_voiceover"], temp_audio)

    subtitle_events = TTSEngine.generate_subtitle_chunks(script_data["full_voiceover"], duration)

    video_engine = VideoEngine()
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_video_path = Config.OUTPUT_DIR / f"news_bait_{timestamp_str}.mp4"

    video_engine.render_video(
        script_data=script_data,
        audio_path=audio_path,
        subtitle_events=subtitle_events,
        output_file=output_video_path
    )

    SocialPublisher.dispatch_all(output_video_path, script_data)

    if temp_audio.exists():
        try:
            temp_audio.unlink()
        except Exception:
            pass

    print("Готово! Відео успішно змонтовано.")
    return output_video_path

def run_once():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Одноразова перевірка каналу {Config.TELEGRAM_CHANNEL_ID}...")
    listener = TelegramListener()
    new_posts = listener.fetch_new_posts()
    if new_posts:
        print(f"Знайдено нових публікацій: {len(new_posts)}")
        for post in new_posts:
            process_single_news(post["text"], post["id"])
            listener.mark_as_processed(post["id"])
            time.sleep(3)
    else:
        print("Нових повідомлень у каналі не знайдено.")

def run_daemon(poll_interval: int = 60):
    print(f"Запуск автономного моніторингу каналу {Config.TELEGRAM_CHANNEL_ID}...")
    listener = TelegramListener()
    while True:
        try:
            new_posts = listener.fetch_new_posts()
            if new_posts:
                for post in new_posts:
                    process_single_news(post["text"], post["id"])
                    listener.mark_as_processed(post["id"])
                    time.sleep(3)
        except Exception as e:
            print(f"Помилка: {e}")
        time.sleep(poll_interval)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Згенерувати тестовий ролик")
    parser.add_argument("--once", action="store_true", help="Обробити нові пости один раз і вийти (для GitHub Actions)")
    parser.add_argument("--listen", action="store_true", help="Постійний моніторинг")
    parser.add_argument("--post", type=str, help="Згенерувати відео з тексту")
    args = parser.parse_args()

    if args.test:
        sample = "УВАГА: Верховна Рада щойно ухвалила скандальне рішення. Зміни торкнуться кожного вже з наступного місяця!"
        process_single_news(sample, "demo_test")
    elif args.once:
        run_once()
    elif args.post:
        process_single_news(args.post)
    elif args.listen:
        run_daemon()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
