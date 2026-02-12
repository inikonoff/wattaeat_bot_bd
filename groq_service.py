import os
import logging
import json
import asyncio
import re
import random
from typing import List, Dict, Optional, Tuple
from groq import AsyncGroq
from config import GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger(__name__)

class GroqService:
    """
    Ultimate Groq Service:
    - Ротация ключей
    - Whisper V3 Turbo
    - Продвинутый Prompt Engineering (Роли, Правила, Вкусы)
    - Умное форматирование (Markdown -> Telegram HTML)
    - Валидация ингредиентов (Self-Correction)
    """

    # --- КОНСТАНТЫ И ПРАВИЛА (МОЗГИ) ---
    
    FLAVOR_RULES = """❗️ ПРАВИЛА ВКУСА:
🎭 КОНТРАСТЫ: Жирное + Кислое, Сладкое + Солёное, Мягкое + Хрустящее.
✨ УСИЛЕНИЕ: Помидор + Базилик, Рыба + Лимон, Тыква + Корица.
👑 ГЛАВНЫЙ ГЕРОЙ: В блюде должен быть один основной вкус."""

    LANGUAGE_KEYWORDS = {
        'german': ['kartoffel', 'wurst', 'kraut', 'bier', 'schnitzel'],
        'italian': ['pasta', 'pomodoro', 'formaggio', 'pizza', 'risotto'],
        'french': ['fromage', 'vin', 'baguette', 'creme'],
        'spanish': ['paella', 'chorizo', 'tortilla'],
        'asian': ['soy', 'rice', 'noodle', 'ginger', 'wasabi']
    }

    RECIPE_VALIDATION_RULES = """
🚫 КРИТИЧЕСКИЕ ЗАПРЕТЫ:
1. НЕ используй ингредиенты, которых нет в списке (кроме соли, воды, масла, перца).
2. Если нет муки/теста — ЗАПРЕЩЕНА выпечка. Предлагай салаты, супы или жарку.
3. Если нет духовки — предлагай готовку на плите.
"""

    def __init__(self):
        if not GROQ_API_KEYS:
            logger.error("❌ GROQ_API_KEYS пуст!")
            raise ValueError("GROQ_API_KEYS не найдены")
        
        self.api_keys = GROQ_API_KEYS
        logger.info(f"✅ GroqService инициализирован. Ключей: {len(self.api_keys)}")
        
        # Модели
        self.model_text = GROQ_MODEL  # Используем основную модель из config
        self.model_audio = "whisper-large-v3-turbo"  # Whisper для аудио
        
        self.max_tokens_map = {
            "analyze_categories": 500,
            "generate_dishes": 1000,
            "generate_recipe": 2800,  # Увеличено для детальных рецептов
            "freestyle_recipe": 2800,
            "comparison": 1500,
            "cooking_advice": 1500,
            "nutrition": 1500,
            "general_cooking": 1500,
            "transcribe": 1000,
            "validate_recipe": 1000,
            "regenerate_recipe": 2800,
            "classify": 100
        }

    def _get_client(self):
        """Ротация ключей"""
        key = random.choice(self.api_keys)
        return AsyncGroq(api_key=key)

    def _sanitize_input(self, text: str, max_length: int = 500) -> str:
        if not text: return ""
        text = text[:max_length]
        text = text.replace('"""', "'").replace("'''", "'").replace('`', "'")
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _clean_html_for_telegram(self, text: str) -> str:
        """Умная очистка и конвертация Markdown -> HTML"""
        if not text: return ""
            
        # Markdown заголовки -> Bold
        text = re.sub(r'#{1,6}\s+(.*?)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        # Markdown bold -> HTML bold
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.*?)__', r'<u>\1</u>', text)
        # Markdown списки -> Эмодзи
        text = re.sub(r'^\s*[\-\*]\s+(.*?)$', r'🔸 \1', text, flags=re.MULTILINE)
        
        # Очистка тегов
        replacements = [
            (r'<br/?>', r'\n'), (r'<p>', r''), (r'</p>', r'\n\n'),
            (r'<ul>', r''), (r'</ul>', r''), (r'<ol>', r''), (r'</ol>', r''),
            (r'<li>', r'🔸 '), (r'</li>', r'\n'),
            (r'<h1>(.*?)</h1>', r'<b>\1</b>\n'),
            (r'<h2>(.*?)</h2>', r'<b>\1</b>\n'),
            (r'<h3>(.*?)</h3>', r'<b>\1</b>\n'),
        ]
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    async def _send_groq_request(self, system_prompt: str, user_text: str, 
                                task_type: str = "general", temperature: float = 0.7, 
                                max_tokens: int = None) -> str:
        try:
            client = self._get_client()
            if max_tokens is None:
                max_tokens = self.max_tokens_map.get(task_type, 1000)
            
            response = await client.chat.completions.create(
                model=self.model_text,  # Используем self.model_text
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

    # --- ЯЗЫКОВЫЕ ФУНКЦИИ ---
    def detect_language_context(self, products: str) -> str:
        """Определяет кухню по продуктам"""
        products_lower = products.lower()
        for lang, keywords in self.LANGUAGE_KEYWORDS.items():
            if any(k in products_lower for k in keywords):
                return f"🌍 КОНТЕКСТ: Обнаружены продукты {lang.upper()} кухни. Предложи традиционное блюдо этого региона."
        return ""

    # --- WHISPER ---
    async def transcribe_voice(self, audio_data: bytes) -> Optional[str]:
        try:
            client = self._get_client()
            transcription = await client.audio.transcriptions.create(
                file=("voice_message.ogg", audio_data),
                model=self.model_audio,  # Используем self.model_audio
                response_format="text",
                language="ru"
            )
            return transcription
        except Exception as e:
            logger.error(f"Ошибка транскрипции: {e}")
            return None

    # --- CLASSIFY ---
    async def classify_intent(self, text: str) -> str:
        safe_text = self._sanitize_input(text, 200)
        system_prompt = "Ты классификатор. Определи интент: ingredients, recipe, comparison, advice, nutrition, general. Верни 1 слово."
        try:
            response = await self._send_groq_request(system_prompt, f"Запрос: {safe_text}", "classify", 0.1, 10)
            intent = re.sub(r'[^a-z]', '', response.strip().lower())
            if intent in ["ingredients", "recipe", "comparison", "advice", "nutrition", "general"]: return intent
            return "general"
        except: return "general"

    # --- FALLBACKS ---
    def _fallback_categories(self, products: str) -> List[str]:
        return ["main", "snack"]

    def _fallback_dishes(self, category: str, products: str) -> List[Dict[str, str]]:
        return [{"name": "Блюдо из продуктов", "description": "Вкусный вариант"}]

    def _fallback_recipe(self, dish_name: str, products: str) -> str:
        return f"<b>🍽️ {dish_name}</b>\n\nНе удалось сгенерировать рецепт. Попробуйте позже."

    # --- GENERATION ---
    async def analyze_categories(self, products: str) -> List[str]:
        safe_products = self._sanitize_input(products, 300)
        system_prompt = 'Ты шеф-повар. Проанализируй список продуктов и верни ТОЛЬКО JSON массив категорий из следующих: ["breakfast", "soup", "main", "salad", "snack", "dessert", "drink", "mix", "sauce"]. Никакого текста кроме JSON массива!'
        
        user_prompt = f"Продукты: {safe_products}\n\nВерни JSON массив категорий блюд, которые можно приготовить из этих продуктов."
        
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "analyze_categories", 0.3, 500)
            logger.info(f"Raw categories response: {response}")
            
            # Ищем JSON массив в ответе
            json_match = re.search(r'\[.*?\]', response, re.DOTALL)
            if json_match:
                categories = json.loads(json_match.group())
                logger.info(f"Parsed categories: {categories}")
                return categories[:4]
            
            logger.warning(f"No JSON found in response, using fallback")
            return self._fallback_categories(safe_products)
        except Exception as e:
            logger.error(f"Error in analyze_categories: {e}", exc_info=True)
            return self._fallback_categories(safe_products)

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        safe_products = self._sanitize_input(products, 300)
        system_prompt = f"Ты шеф. Предложи 3-5 блюд категории '{category}'. Верни JSON массив объектов с полями 'name' и 'description'."
        try:
            response = await self._send_groq_request(system_prompt, f"Продукты: {safe_products}", "generate_dishes", 0.7)
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match: return json.loads(json_match.group())[:5]
            return self._fallback_dishes(category, safe_products)
        except: return self._fallback_dishes(category, safe_products)

    async def generate_recipe(self, dish_name: str, products: str) -> str:
        safe_dish = self._sanitize_input(dish_name, 100)
        safe_products = self._sanitize_input(products, 300)
        
        # Умный контекст
        lang_context = self.detect_language_context(safe_products)
        
        # МОЩНЫЙ ПРОМПТ: КРАСОТА + МОЗГИ
        system_prompt = f"""Ты Бренд-шеф и Нутрициолог. Напиши идеальный рецепт.

{self.RECIPE_VALIDATION_RULES}
{self.FLAVOR_RULES}
{lang_context}

ФОРМАТ ВЫВОДА (Telegram HTML):
1. <b>Название блюда</b> (без лишних слов)
2. 📦 <b>Ингредиенты:</b>
   🔸 Ингредиент 1
   🔸 Ингредиент 2
3. 📊 <b>Пищевая ценность на 1 порцию:</b>
   🥚 Белки: ... г
   🥑 Жиры: ... г
   🌾 Углеводы: ... г
   ⚡ Энерг. ценность: ... ккал
4. ⏱ <b>Время:</b> ... мин
5. 🪦 <b>Сложность:</b> ...
6. 👥 <b>Порции:</b> ...
7. 👨‍🍳 <b>Приготовление:</b>
   1. Шаг 1 (выделяй <b>жирным</b> действия)
   2. Шаг 2
8. 💡 <b>Секрет шефа:</b> (совет по улучшению вкуса)

Используй только HTML теги <b>, <i>, <u>. Не используй Markdown."""

        user_prompt = f"Блюдо: {safe_dish}. Продукты: {safe_products}"
        
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "generate_recipe", 0.5, 2800)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.strip().startswith('<'): cleaned = f'<b>🍽️ {safe_dish}</b>\n\n{cleaned}'
            
            # ВАЛИДАЦИЯ (САМОПРОВЕРКА)
            is_valid, issues = await self.validate_recipe_consistency(safe_products, cleaned)
            if not is_valid:
                logger.warning(f"Validation failed: {issues}. Regenerating...")
                return await self.regenerate_recipe_without_missing(safe_dish, safe_products, cleaned, issues)
                
            return cleaned
        except Exception as e:
            logger.error(f"Error: {e}")
            return self._fallback_recipe(safe_dish, safe_products)

    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        safe_dish = self._sanitize_input(dish_name, 100)
        
        system_prompt = f"""Ты Бренд-шеф. Напиши рецепт.

{self.FLAVOR_RULES}

ФОРМАТ ВЫВОДА (Telegram HTML):
1. <b>Название блюда</b>
2. 📦 <b>Ингредиенты:</b>
   🔸 Ингредиент 1
3. 📊 <b>Пищевая ценность на 1 порцию:</b>
   🥚 Белки: ... г
   🥑 Жиры: ... г
   🌾 Углеводы: ... г
   ⚡ Энерг. ценность: ... ккал
4. ⏱ <b>Время:</b> ... мин
5. 🪦 <b>Сложность:</b> ...
6. 👥 <b>Порции:</b> ...
7. 👨‍🍳 <b>Приготовление:</b>
   1. Шаг 1 (выделяй <b>жирным</b> действия)
8. 💡 <b>Секрет шефа:</b> (лайфхак)

Используй только HTML."""

        user_prompt = f"Рецепт: {safe_dish}"
        try:
            response = await self._send_groq_request(system_prompt, user_prompt, "freestyle_recipe", 0.7, 2800)
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.strip().startswith('<'): cleaned = f'<b>👨‍🍳 {safe_dish}</b>\n\n{cleaned}'
            return cleaned
        except Exception as e:
            logger.error(f"Error: {e}")
            return self._fallback_recipe(safe_dish, "Классические")

    async def generate_comparison(self, query: str) -> str:
        try:
            system_prompt = "Сравни продукты. Структура: <b>Вкус</b>, <b>Польза</b>, <b>Вывод</b>. HTML."
            response = await self._send_groq_request(system_prompt, query, "comparison", 0.5, 1500)
            return self._clean_html_for_telegram(response)
        except: return "Ошибка сравнения"

    async def generate_cooking_advice(self, query: str) -> str:
        try:
            system_prompt = "Дай кулинарный совет. Используй <b>жирный</b>. HTML."
            response = await self._send_groq_request(system_prompt, query, "cooking_advice", 0.6, 1500)
            return self._clean_html_for_telegram(response)
        except: return "Ошибка совета"

    async def generate_nutrition_info(self, query: str) -> str:
        try:
            system_prompt = "Дай КБЖУ и пользу. Используй эмодзи. HTML."
            response = await self._send_groq_request(system_prompt, query, "nutrition", 0.4, 1500)
            return self._clean_html_for_telegram(response)
        except: return "Ошибка нутрициологии"

    # --- ВАЛИДАЦИЯ И ПЕРЕГЕНЕРАЦИЯ (ВОЗВРАЩЕНО!) ---
    
    async def validate_recipe_consistency(self, products: str, recipe: str) -> Tuple[bool, List[str]]:
        """Проверяет, не придумал ли бот лишнего"""
        issues = []
        recipe_lower = recipe.lower()
        
        # Критические проверки
        checks = [
            {'key': 'тесто', 'req': ['мука', 'тесто', 'лаваш'], 'msg': 'Требуется тесто, но нет муки'},
            {'key': 'мука', 'req': ['мука'], 'msg': 'Требуется мука, но ее нет'},
            {'key': 'яйц', 'req': ['яйц', 'яйко'], 'msg': 'Требуются яйца, но их нет'}
        ]
        
        # Если это фристайл (продуктов нет или мало), пропускаем жесткую проверку
        if len(products) < 5: 
            return True, []

        prod_lower = products.lower()
        for check in checks:
            if check['key'] in recipe_lower and not any(r in prod_lower for r in check['req']):
                issues.append(check['msg'])
        
        return len(issues) == 0, issues

    async def regenerate_recipe_without_missing(self, dish_name: str, products: str, original: str, issues: List[str]) -> str:
        """Переписывает рецепт, если валидация не прошла"""
        safe_dish = self._sanitize_input(dish_name, 100)
        safe_prods = self._sanitize_input(products, 300)
        
        prompt = f"""ИСПРАВЬ РЕЦЕПТ: {safe_dish}
        
ОШИБКИ: {', '.join(issues)}

ЗАДАЧА:
1. Убери ингредиенты, которых нет в списке: {safe_prods}
2. Если нельзя приготовить без них - предложи ДРУГОЕ блюдо из этих продуктов.
3. Сохрани красивое форматирование (HTML, эмодзи, КБЖУ).

ФОРМАТ: (тот же, что и раньше)"""
        
        try:
            response = await self._send_groq_request(prompt, "Fix recipe", "regenerate_recipe", 0.4, 2800)
            return self._clean_html_for_telegram(response)
        except:
            return original + "\n\n⚠️ <i>Внимание: возможно, потребуются дополнительные ингредиенты.</i>"

groq_service = GroqService()
