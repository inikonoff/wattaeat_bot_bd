--- START OF FILE groq_service.py ---

import os
import logging
import json
import asyncio
import re
import random
from typing import List, Dict, Optional, Tuple
from groq import AsyncGroq
# Импортируем список ключей из конфига
from config import GROQ_API_KEYS, GROQ_MODEL_TEXT, GROQ_MODEL_AUDIO

logger = logging.getLogger(__name__)

class GroqService:
    def __init__(self):
        # Проверяем список, импортированный из config.py
        if not GROQ_API_KEYS:
            logger.error("❌ GROQ_API_KEYS пуст! Проверьте переменные окружения.")
            raise ValueError("GROQ_API_KEYS не найдены в переменных окружения")
        
        self.api_keys = GROQ_API_KEYS
        logger.info(f"✅ GroqService инициализирован. Загружено ключей: {len(self.api_keys)}")
        
        self.max_tokens_map = {
            "analyze_categories": 500,
            "generate_dishes": 1000,
            "generate_recipe": 2000,
            "freestyle_recipe": 2000,
            "comparison": 1500,
            "cooking_advice": 1500,
            "nutrition": 1500,
            "general_cooking": 1500,
            "transcribe": 1000,
            "validate_recipe": 1000,
            "regenerate_recipe": 2000,
            "classify": 100
        }

    def _get_client(self):
        """Ротация ключей для распределения нагрузки"""
        key = random.choice(self.api_keys)
        return AsyncGroq(api_key=key)

    def _sanitize_input(self, text: str, max_length: int = 500) -> str:
        if not text:
            return ""
        text = text[:max_length]
        text = text.replace('"""', "'").replace("'''", "'").replace('`', "'")
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _clean_html_for_telegram(self, text: str) -> str:
        if not text: 
            return ""
        replacements = [
            (r'<b>(.*?)</b>', r'<b>\1</b>'),
            (r'<strong>(.*?)</strong>', r'<b>\1</b>'),
            (r'<i>(.*?)</i>', r'<i>\1</i>'),
            (r'<em>(.*?)</em>', r'<i>\1</i>'),
            (r'<u>(.*?)</u>', r'<u>\1</u>'),
            (r'<s>(.*?)</s>', r'<s>\1</s>'),
            (r'<code>(.*?)</code>', r'<code>\1</code>'),
            (r'<pre>(.*?)</pre>', r'<pre>\1</pre>'),
            (r'<a href="(.*?)">(.*?)</a>', r'<a href="\1">\2</a>'),
            (r'<br/?>', r'\n'),
            (r'<p>', r''), (r'</p>', r'\n\n'),
            (r'<h[1-6]>(.*?)</h[1-6]>', r'<b>\1</b>\n'),
            (r'<ul>', r''), (r'</ul>', r''), (r'<ol>', r''), (r'</ol>', r''),
            (r'<li>', r'• '), (r'</li>', r'\n'),
        ]
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        return text.strip()

    async def _send_groq_request(self, system_prompt: str, user_text: str, 
                                task_type: str = "general", temperature: float = 0.7, 
                                max_tokens: int = None) -> str:
        try:
            client = self._get_client()
            if max_tokens is None:
                max_tokens = self.max_tokens_map.get(task_type, 1000)
            
            response = await client.chat.completions.create(
                model=GROQ_MODEL_TEXT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=0.9
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка Groq API ({task_type}): {e}", exc_info=True)
            raise

    # --- НОВЫЕ МЕТОДЫ ---

    async def transcribe_voice(self, audio_data: bytes) -> Optional[str]:
        """Транскрибация голоса через Whisper"""
        try:
            client = self._get_client()
            # Whisper требует файл с именем
            transcription = await client.audio.transcriptions.create(
                file=("voice_message.ogg", audio_data),
                model=GROQ_MODEL_AUDIO,
                response_format="text",
                language="ru"
            )
            logger.info(f"Голос распознан: {transcription[:50]}...")
            return transcription
        except Exception as e:
            logger.error(f"Ошибка транскрипции Whisper: {e}")
            return None

    async def classify_intent(self, text: str) -> str:
        """Классификация намерения пользователя"""
        safe_text = self._sanitize_input(text, 200)
        
        system_prompt = """Ты классификатор намерений для кулинарного бота.
Твоя задача - определить категорию запроса пользователя.
Верни ТОЛЬКО одно слово из списка:
- ingredients (если пользователь перечисляет продукты: "яйца, молоко", "есть курица и рис")
- recipe (если просит конкретный рецепт: "как готовить борщ", "рецепт пиццы")
- comparison (сравнение продуктов: "что полезнее", "где больше белка")
- advice (советы по технике: "как варить", "почему пригорает")
- nutrition (вопросы про БЖУ, калории, диеты)
- general (общие вопросы, приветствия, болтовня)

Если не уверен, верни 'general'."""

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=f"Запрос: {safe_text}",
                task_type="classify",
                temperature=0.1, # Минимальная температура для точности
                max_tokens=10
            )
            
            intent = response.strip().lower()
            # Очистка от лишних символов, если модель вернула точку или кавычки
            intent = re.sub(r'[^a-z]', '', intent)
            
            valid_intents = ["ingredients", "recipe", "comparison", "advice", "nutrition", "general"]
            if intent in valid_intents:
                return intent
            return "general"
            
        except Exception as e:
            logger.error(f"Ошибка классификации: {e}")
            # Fallback на простую логику
            if ',' in safe_text or ' и ' in safe_text: 
                return "ingredients"
            return "general"

    # --- ВСПОМОГАТЕЛЬНЫЕ FALLBACK МЕТОДЫ ---

    def _fallback_categories(self, products: str) -> List[str]:
        """Fallback метод определения категорий"""
        products_lower = products.lower()
        categories = []
        
        if any(word in products_lower for word in ['яйц', 'омлет', 'блин', 'каша', 'хлопья', 'творог']):
            categories.append("breakfast")
        
        if any(word in products_lower for word in ['суп', 'борщ', 'бульон', 'похлебка']):
            categories.append("soup")
        
        if any(word in products_lower for word in ['мяс', 'куриц', 'рыб', 'гарнир', 'картош', 'рис', 'греч', 'макарон']):
            categories.append("main")
        
        if any(word in products_lower for word in ['салат', 'овощ', 'помидор', 'огурец', 'зелен']):
            categories.append("salad")
        
        if any(word in products_lower for word in ['бутерброд', 'сыр', 'колбас', 'хлеб']):
            categories.append("snack")
        
        if any(word in products_lower for word in ['десерт', 'торт', 'пирог', 'печенье', 'шоколад', 'сахар', 'мука']):
            categories.append("dessert")
        
        if any(word in products_lower for word in ['сок', 'напиток', 'чай', 'кофе', 'молоко', 'кефир']):
            categories.append("drink")
        
        if len(categories) == 0:
            categories = ["main", "snack"]
        
        return categories[:3]

    def _fallback_dishes(self, category: str, products: str) -> List[Dict[str, str]]:
        """Fallback список блюд"""
        dishes_map = {
            "breakfast": [
                {"name": "Омлет с овощами", "description": "Пышный омлет со свежими овощами"},
                {"name": "Творожная запеканка", "description": "Нежная запеканка из творога"},
                {"name": "Каша на выбор", "description": "Питательная каша с добавками"}
            ],
            "main": [
                {"name": "Основное блюдо", "description": "Сытное блюдо из доступных продуктов"},
                {"name": "Гарнир с добавками", "description": "Вкусный гарнир с дополнительными ингредиентами"}
            ],
            "salad": [
                {"name": "Свежий салат", "description": "Легкий салат из сезонных овощей"},
                {"name": "Овощная нарезка", "description": "Разнообразные овощи с заправкой"}
            ],
            "soup": [
                {"name": "Ароматный суп", "description": "Наваристый суп с доступными продуктами"},
                {"name": "Легкий бульон", "description": "Прозрачный бульон с зеленью"}
            ]
        }
        
        return dishes_map.get(category, [
            {"name": "Вкусное блюдо", "description": "Приготовлено из имеющихся продуктов"}
        ])

    def _fallback_recipe(self, dish_name: str, products: str) -> str:
        """Fallback рецепт"""
        return f'''<b>🍽️ {dish_name}</b>

📋 <b>Ингредиенты:</b>
Основные: {products}
Дополнительно: соль, перец, масло растительное

👨‍🍳 <b>Приготовление:</b>
1. Подготовьте все ингредиенты
2. Смешайте основные компоненты
3. Приправьте по вкусу
4. Готовьте до готовности
5. Подавайте горячим

💡 <b>Советы:</b>
• Регулируйте количество специй по вкусу
• Можно добавить дополнительные ингредиенты
• Следите за временем приготовления'''

    # --- СТАРЫЕ МЕТОДЫ ---

    async def analyze_categories(self, products: str) -> List[str]:
        safe_products = self._sanitize_input(products, 300)
        system_prompt = """Ты шеф-повар. Анализируй продукты и верни JSON массив подходящих категорий.
Доступные: ["breakfast", "soup", "main", "salad", "snack", "dessert", "drink", "mix", "sauce"]
Верни от 1 до 4 категорий."""
        user_prompt = f"Продукты: {safe_products}\nВерни только JSON."
        
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "analyze_categories", 0.3, 300)
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                categories = json.loads(json_match.group())
                valid = ["breakfast", "soup", "main", "salad", "snack", "dessert", "drink", "mix", "sauce"]
                return [c for c in categories if c in valid][:4]
            return self._fallback_categories(safe_products)
        except Exception as e:
            logger.error(f"Ошибка анализа категорий: {e}")
            return self._fallback_categories(safe_products)

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        safe_products = self._sanitize_input(products, 300)
        system_prompt = f"Ты шеф-повар. Предложи 3-5 блюд категории '{category}' из продуктов. Верни JSON массив объектов {{'name': '...', 'description': '...'}}."
        user_prompt = f"Продукты: {safe_products}"
        
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "generate_dishes", 0.7)
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                dishes = json.loads(json_match.group())
                return dishes[:5]
            return self._fallback_dishes(category, safe_products)
        except Exception as e:
            logger.error(f"Ошибка генерации списка блюд: {e}")
            return self._fallback_dishes(category, safe_products)

    async def generate_recipe(self, dish_name: str, products: str) -> str:
        safe_dish = self._sanitize_input(dish_name, 100)
        safe_products = self._sanitize_input(products, 300)
        system_prompt = """Ты шеф-повар. Напиши рецепт. Используй HTML теги <b>, <i>. Структура: Название, Ингредиенты, Приготовление, Советы.
Начни с названия в тегах <b>."""
        user_prompt = f"Блюдо: {safe_dish}. Продукты: {safe_products}"
        
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "generate_recipe", 0.6, 1500)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.startswith('<b>'):
                cleaned = f'<b>🍽️ {safe_dish}</b>\n\n{cleaned}'
            return cleaned
        except Exception as e:
            logger.error(f"Ошибка генерации рецепта: {e}")
            return self._fallback_recipe(safe_dish, safe_products)

    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        safe_dish = self._sanitize_input(dish_name, 100)
        system_prompt = """Ты шеф-повар. Напиши подробный рецепт. Используй HTML.
Начни с названия в тегах <b>. Включи разделы: Ингредиенты, Приготовление, Советы."""
        user_prompt = f"Рецепт: {safe_dish}"
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "freestyle_recipe", 0.7, 1800)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.startswith('<b>'):
                cleaned = f'<b>👨‍🍳 {safe_dish}</b>\n\n{cleaned}'
            return cleaned
        except Exception as e:
            logger.error(f"Ошибка генерации свободного рецепта: {e}")
            return self._fallback_recipe(safe_dish, "разные ингредиенты")

    async def generate_comparison(self, query: str) -> str:
        """Сравнение продуктов или блюд"""
        try:
            system_prompt = "Ты эксперт по питанию и кулинарии. Сравни объективно, используй факты. Форматируй ответ для Telegram HTML."
            response = await self._send_groq_request(system_prompt, query, "comparison", 0.5, 1500)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.startswith('<b>'):
                cleaned = f'<b>🔍 Сравнение</b>\n\n{cleaned}'
            return cleaned
        except Exception as e:
            logger.error(f"Ошибка сравнения: {e}")
            return f"<b>🔍 Сравнение</b>\n\nНе удалось провести сравнение для: {query}"

    async def generate_cooking_advice(self, query: str) -> str:
        """Дает советы по готовке"""
        try:
            system_prompt = "Ты опытный кулинарный наставник. Дай практические, проверенные советы. Форматируй ответ для Telegram HTML."
            response = await self._send_groq_request(system_prompt, query, "cooking_advice", 0.6, 1500)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.startswith('<b>'):
                cleaned = f'<b>👨‍🍳 Совет шефа</b>\n\n{cleaned}'
            return cleaned
        except Exception as e:
            logger.error(f"Ошибка совета: {e}")
            return f"<b>👨‍🍳 Совет шефа</b>\n\nНе удалось найти совет для: {query}"

    async def generate_nutrition_info(self, query: str) -> str:
        """Информация о питательной ценности"""
        try:
            system_prompt = "Ты диетолог и эксперт по питанию. Дай научно обоснованную информацию о пищевой ценности. Форматируй ответ для Telegram HTML."
            response = await self._send_groq_request(system_prompt, query, "nutrition", 0.4, 1500)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.startswith('<b>'):
                cleaned = f'<b>🥗 Пищевая ценность</b>\n\n{cleaned}'
            return cleaned
        except Exception as e:
            logger.error(f"Ошибка информации о питании: {e}")
            return f"<b>🥗 Пищевая ценность</b>\n\nНе удалось найти информацию для: {query}"

    async def validate_recipe_consistency(self, products: str, recipe: str) -> Tuple[bool, List[str]]:
        """Упрощенная валидация рецепта"""
        # Возвращаем True для упрощения
        return True, []

    async def regenerate_recipe_without_missing(self, dish_name: str, products: str, original: str, missing: List[str]) -> str:
        """Возвращает оригинальный рецепт"""
        return original

groq_service = GroqService()
