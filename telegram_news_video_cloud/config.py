import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def load_env(env_path: Path):
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k not in os.environ:
                os.environ[k] = v

load_env(BASE_DIR / ".env")

class Config:
    # Telegram
    TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@your_news_channel")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
    CHANNEL_DISPLAY_NAME = os.getenv("CHANNEL_DISPLAY_NAME", "ГОЛОВНІ НОВИНИ UA")
    CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@glavni_novyny")

    # AI Script
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    # TTS
    VOICE_NAME = os.getenv("VOICE_NAME", "uk-UA-OstapNeural")
    VOICE_RATE = os.getenv("VOICE_RATE", "+10%")
    VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz")

    # Video specs
    VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1080"))
    VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "1920"))
    VIDEO_FPS = int(os.getenv("VIDEO_FPS", "30"))

    # Paths
    ASSETS_DIR = BASE_DIR / "assets"
    FONTS_DIR = ASSETS_DIR / "fonts"
    BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
    AUDIO_DIR = ASSETS_DIR / "audio"
    OUTPUT_DIR = BASE_DIR / "output_videos"
    TEMP_DIR = BASE_DIR / "temp"

    # Social auto-posting
    ENABLE_AUTO_POST_YOUTUBE = os.getenv("ENABLE_AUTO_POST_YOUTUBE", "False").lower() in ("true", "1")
    ENABLE_AUTO_POST_TIKTOK = os.getenv("ENABLE_AUTO_POST_TIKTOK", "False").lower() in ("true", "1")
    ENABLE_AUTO_POST_INSTAGRAM = os.getenv("ENABLE_AUTO_POST_INSTAGRAM", "False").lower() in ("true", "1")

    YOUTUBE_CLIENT_SECRETS_FILE = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secrets.json")
    INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
    TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")
