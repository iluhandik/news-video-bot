import re
import os
import random
from typing import Dict
from config import Config

class ScriptGenerator:
    """
    Генерує вірусний "мега-байт" сценарій (15-20 секунд) на основі новинного посту Telegram.
    Структура:
    1. Hook (0-3s): шокуючий заголовок / питання, що зупиняє скрол.
    2. Body (3-14s): динамічна кульмінація та наростання напруги без фінального розв'язання.
    3. Cliffhanger + CTA (14-20s): різкий обрив і заклик перейти в Telegram за розв'язкою/відео.
    """

    HOOK_TEMPLATES = [
        "УВАГА: Ця новина прямо зараз змінює все!",
        "ТЕРМІНОВО: Те, про що щойно повідомили, шокувало всю країну!",
        "ШОК: Цю інформацію намагалися приховати до останнього!",
        "ВИ НЕ ПОВІРИТЕ: Тільки що з'явилися перші офіційні подробиці!",
        "УСІМ УВАГА: Рішення вже підписано, і це торкнеться кожного!",
        "ПЕРЕСТАНЬТЕ ГОРТАТИ СТРІЧКУ: Сталося те, чого боялися всі!",
    ]

    CLIFFHANGER_TEMPLATES = [
        "Але найскандальніший документ і повне відео без цензури ми вже виклали в нашому Telegram-каналі! Посилання закріплено в шапці профілю!",
        "Хто насправді за цим стоїть і ексклюзивні кадри з місця подій дивіться в Telegram за посиланням у шапці та першому коментарі!",
        "Повний список та секретні деталі, які видаляють звідусіль, вже опубліковані в нашому каналі! Тисніть на посилання в шапці!",
        "Кадри без монтажу та всі прізвища виклали в наш Telegram. Переходьте за посиланням у закріпленому повідомленні прямо зараз!",
    ]

    @classmethod
    def clean_raw_text(cls, text: str) -> str:
        # Видалення посилань, реклами та тегів
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"t\.me/\S+", "", text)
        text = re.sub(r"@[a-zA-Z0-9_]+", "", text)
        text = re.sub(r"#\w+", "", text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        # Фільтрація рядків підписок
        cleaned_lines = []
        for line in lines:
            if any(w in line.lower() for w in ["підпишись", "підписатися", "підписуйтесь", "джерело", "реклама"]):
                continue
            cleaned_lines.append(line)
        return " ".join(cleaned_lines)

    @classmethod
    def generate(cls, raw_post: str) -> Dict[str, str]:
        cleaned = cls.clean_raw_text(raw_post)

        # Спроба генерації через OpenAI, якщо налаштовано ключ
        if Config.OPENAI_API_KEY:
            try:
                return cls._generate_with_llm(cleaned)
            except Exception as e:
                print(f"[ScriptGenerator] Помилка OpenAI API: {e}. Перехід на алгоритмічний генератор.")

        return cls._generate_algorithmic(cleaned)

    @classmethod
    def _generate_algorithmic(cls, text: str) -> Dict[str, str]:
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 10]
        
        hook = random.choice(cls.HOOK_TEMPLATES)
        cliffhanger = random.choice(cls.CLIFFHANGER_TEMPLATES)
        
        if sentences:
            lead = sentences[0]
            secondary = sentences[1] if len(sentences) > 1 else ""
            body_text = f"{lead}. {secondary}".strip()
            # Обмежуємо довжину основного тексту для 15-20 секунд ролика
            if len(body_text) > 180:
                body_text = body_text[:177] + "..."
        else:
            body_text = "З'явилися екстрені деталі щодо останніх резонансних подій, які сколихнули мережу."

        # Формування заголовка для макету Telegram-картки
        words = text.split()
        headline = " ".join(words[:6]) if len(words) >= 6 else "ТЕРМІНОВЕ ПОВІДОМЛЕННЯ"
        if not headline.endswith((".", "!", "?")):
            headline += "!"

        full_voiceover = f"{hook} {body_text} {cliffhanger}"

        return {
            "hook": hook,
            "headline": headline.upper(),
            "body": body_text,
            "cliffhanger": cliffhanger,
            "full_voiceover": full_voiceover,
            "hashtags": "#новини #україна #терміново #шок #рек #новиниукраїни"
        }

    @classmethod
    def _generate_with_llm(cls, text: str) -> Dict[str, str]:
        import openai
        client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        
        prompt = f"""Перетвори новину з Telegram у вірусний сценарій 15-секундного мега-байт відео для TikTok/Reels:
Текст новини: {text}

Вимоги:
1. Заголовок (HEADLINE): 4-6 слів капсом для плашки.
2. Хук (HOOK): 1 вибухове речення (перші 3 сек), що зупиняє скрол.
3. Тіло (BODY): 1-2 напружених речення про суть події без розв'язки.
4. Кліфхенгер та заклик (CTA): заклик перейти в закріплене посилання в шапці профілю в наш Telegram за повним відео/документом.

Поверни відповідь у форматі JSON із ключами:
headline, hook, body, cliffhanger, full_voiceover, hashtags"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.8
        )
        import json
        return json.loads(response.choices[0].message.content)
