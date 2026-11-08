import os
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Optional
import requests
from config import Config

class TelegramListener:
    """
    Моніторить Telegram-канал та витягує нові текстові повідомлення.
    Підтримує 2 режими роботи:
    1. Через офіційний Bot API (якщо бот доданий як адмін у канал).
    2. Через публічну веб-стрічку каналу (t.me/s/channel), що працює навіть БЕЗ бота й API-ключів!
    """

    def __init__(self):
        self.processed_file = Config.BASE_DIR / "processed_posts.json"
        self.processed_ids = self._load_processed_ids()

    def _load_processed_ids(self) -> set:
        if self.processed_file.exists():
            try:
                data = json.loads(self.processed_file.read_text(encoding="utf-8"))
                return set(data)
            except Exception:
                return set()
        return set()

    def _save_processed_id(self, post_id: str):
        self.processed_ids.add(str(post_id))
        try:
            self.processed_file.write_text(json.dumps(list(self.processed_ids)), encoding="utf-8")
        except Exception as e:
            print(f"[TelegramListener] Помилка збереження processed_ids: {e}")

    def fetch_new_posts(self) -> List[Dict]:
        """
        Отримує нові публікації з каналу, яких ще не було в обробці.
        """
        posts = []
        if Config.TELEGRAM_BOT_TOKEN and not Config.TELEGRAM_CHANNEL_ID.startswith("http"):
            # Спроба отримати через Bot API
            posts = self._fetch_via_bot_api()

        if not posts:
            # Резервний / базовий метод через відкриту веб-стрічку t.me/s/
            posts = self._fetch_via_web_preview()

        new_posts = [p for p in posts if str(p["id"]) not in self.processed_ids]
        return new_posts

    def _fetch_via_bot_api(self) -> List[Dict]:
        """
        Опитування оновлень через getUpdates
        """
        url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/getUpdates"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                results = []
                for item in data.get("result", []):
                    channel_post = item.get("channel_post")
                    if channel_post and channel_post.get("text"):
                        text = channel_post["text"]
                        if len(text.strip()) > 50:
                            results.append({
                                "id": str(channel_post["message_id"]),
                                "text": text,
                                "date": channel_post.get("date", int(time.time()))
                            })
                return results
        except Exception as e:
            print(f"[TelegramListener] Bot API запит не вдався: {e}")
        return []

    def _fetch_via_web_preview(self) -> List[Dict]:
        """
        Парсинг публічної сторінки t.me/s/{channel_username}
        """
        username = Config.TELEGRAM_CHANNEL_ID.replace("@", "").strip()
        if not username or username == "your_news_channel":
            return []

        url = f"https://t.me/s/{username}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                return []

            html = r.text
            # Знаходження блоків повідомлень tgme_widget_message_text
            pattern = re.compile(
                r'data-post="([^"]+)".*?<div class="tgme_widget_message_text[^"]*">(.*?)</div>',
                re.DOTALL
            )
            matches = pattern.findall(html)
            results = []
            for post_id, raw_html_text in matches:
                # Очищення HTML тегів (<br/>, <b>, <a> тощо)
                clean_text = re.sub(r'<br\s*/?>', '\n', raw_html_text)
                clean_text = re.sub(r'<[^>]+>', '', clean_text).strip()
                if len(clean_text) > 40:
                    results.append({
                        "id": post_id,
                        "text": clean_text,
                        "date": int(time.time())
                    })
            return results
        except Exception as e:
            print(f"[TelegramListener] Помилка web preview: {e}")
            return []

    def mark_as_processed(self, post_id: str):
        self._save_processed_id(post_id)
