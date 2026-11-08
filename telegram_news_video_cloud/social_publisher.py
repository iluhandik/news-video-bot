import os
import time
from pathlib import Path
from typing import Dict
import requests
from config import Config

class SocialPublisher:
    """
    Модуль автопублікації та надсилання готових відео у соцмережі:
    1. Telegram адмін-чат (швидке прев'ю з кнопками або сповіщення).
    2. YouTube Shorts (через YouTube Data API v3).
    3. Instagram Reels (через Meta Graph API).
    4. TikTok (через Content Posting API).
    """

    @classmethod
    def send_to_admin(cls, video_path: Path, caption: str) -> bool:
        """
        Надсилає згенероване відео в особисті повідомлення власнику каналу
        для контролю якості перед виходом у соцмережі.
        """
        if not Config.TELEGRAM_BOT_TOKEN or not Config.ADMIN_CHAT_ID:
            print("[SocialPublisher] Telegram Bot Token або Admin Chat ID не налаштовані, пропускаємо відправку адміну.")
            return False

        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendVideo"
        try:
            with open(video_path, "rb") as vf:
                data = {
                    "chat_id": Config.ADMIN_CHAT_ID,
                    "caption": f"🚀 <b>Згенеровано нове мега-байт відео!</b>\n\n{caption}\n\n<i>#автопостинг #відео</i>",
                    "parse_mode": "HTML"
                }
                files = {"video": vf}
                r = requests.post(url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    print("[SocialPublisher] Відео успішно надіслано в Telegram адміну!")
                    return True
                else:
                    print(f"[SocialPublisher] Помилка відправки адміну: {r.text}")
        except Exception as e:
            print(f"[SocialPublisher] Виняток при відправці адміну: {e}")
        return False

    @classmethod
    def upload_to_youtube_shorts(cls, video_path: Path, title: str, description: str, tags: list) -> bool:
        """
        Публікує вертикальне відео у YouTube Shorts через YouTube Data API v3.
        """
        if not Config.ENABLE_AUTO_POST_YOUTUBE:
            return False

        secrets_file = Config.BASE_DIR / Config.YOUTUBE_CLIENT_SECRETS_FILE
        if not secrets_file.exists():
            print(f"[SocialPublisher] Файл {secrets_file} не знайдено для YouTube API.")
            return False

        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google_auth_oauthlib.flow import InstalledAppFlow

            SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), SCOPES)
            credentials = flow.run_local_server(port=0)
            youtube = build("youtube", "v3", credentials=credentials)

            full_title = f"{title[:80]} #Shorts"
            body = {
                "snippet": {
                    "title": full_title,
                    "description": f"{description}\n\nПідписуйтесь на Telegram: {Config.CHANNEL_USERNAME}\n#Shorts #новини",
                    "tags": tags + ["Shorts", "news"],
                    "categoryId": "25"  # News & Politics
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False
                }
            }

            media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()
            print(f"[SocialPublisher] YouTube Shorts опубліковано! ID: {response.get('id')}")
            return True
        except Exception as e:
            print(f"[SocialPublisher] Помилка завантаження на YouTube: {e}")
            return False

    @classmethod
    def upload_to_instagram_reels(cls, video_url: str, caption: str) -> bool:
        """
        Публікує ролик в Instagram Reels через Meta Graph API.
        """
        if not Config.ENABLE_AUTO_POST_INSTAGRAM:
            return False

        if not Config.INSTAGRAM_ACCESS_TOKEN or not Config.INSTAGRAM_ACCOUNT_ID:
            print("[SocialPublisher] Дані Instagram API не заповнені.")
            return False

        base_url = f"https://graph.facebook.com/v19.0/{Config.INSTAGRAM_ACCOUNT_ID}"
        try:
            init_url = f"{base_url}/media"
            payload = {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": f"{caption}\n\nПосилання в шапці профілю: {Config.CHANNEL_USERNAME}",
                "access_token": Config.INSTAGRAM_ACCESS_TOKEN
            }
            r = requests.post(init_url, data=payload, timeout=30)
            creation_id = r.json().get("id")
            if not creation_id:
                print(f"[SocialPublisher] Помилка ініціалізації Instagram Reels: {r.text}")
                return False

            time.sleep(15)

            publish_url = f"{base_url}/media_publish"
            pub_res = requests.post(publish_url, data={
                "creation_id": creation_id,
                "access_token": Config.INSTAGRAM_ACCESS_TOKEN
            }, timeout=30)
            
            if pub_res.status_code == 200:
                print(f"[SocialPublisher] Instagram Reels опубліковано! ID: {pub_res.json().get('id')}")
                return True
            else:
                print(f"[SocialPublisher] Помилка публікації Reels: {pub_res.text}")
        except Exception as e:
            print(f"[SocialPublisher] Виняток Instagram Reels: {e}")
        return False

    @classmethod
    def dispatch_all(cls, video_path: Path, script_data: Dict[str, str]):
        """
        Головний диспетчер: відправка власнику та публікація у підключені канали
        """
        caption = f"{script_data['headline']}\n\n{script_data['hook']}\n{script_data['hashtags']}"
        
        # 1. Відправка в Telegram власнику
        cls.send_to_admin(video_path, caption)

        # 2. Публікація в YouTube Shorts
        if Config.ENABLE_AUTO_POST_YOUTUBE:
            tags = [t.replace("#", "") for t in script_data["hashtags"].split()]
            cls.upload_to_youtube_shorts(video_path, script_data["headline"], caption, tags)
