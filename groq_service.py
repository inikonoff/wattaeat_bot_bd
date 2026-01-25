import json
import re
import logging
import asyncio
from typing import Dict, List, Optional
from openai import AsyncOpenAI

from config import GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger(__name__)

class GroqService:
    # Ваши правила
    FLAVOR_RULES = """❗️ ПРАВИЛА СОЧЕТАЕМОСТИ:
🎭 КОНТРАСТЫ: Жирное + Кислое, Сладкое + Солёное, Мягкое + Хрустящее.
✨ УСИЛЕНИЕ: Помидор + Базилик, Рыба + Укроп + Лимон, Тыква + Корица, Картофель + Лук + Укроп
👑 ОДИН ГЛАВНЫЙ ИНГРЕДИЕНТ: В каждом блюде один "король".
❌ ТАБУ: Рыба + Молочные продукты (в горячем), два сильных мяса в одной композиции."""

    def __init__(self):
        self.clients = []
        self.current_client_index = 0
        self._init_clients()
    
    def _init_clients(self):
        if not GROQ_API_KEYS:
            logger.warning("GROQ_API_KEYS не настроены!")
            return
        
        for key in GROQ_API_KEYS:
            try:
                client = AsyncOpenAI(
                    api_key=key,
                    base_url="https://api.groq.com/openai/v1",
                    timeout=30.0,
                )
                self.clients.append(client)
            except Exception as e:
                logger.error(f"Error client: {e}")
    
    def _get_client(self):
        if not self.clients: return None
        client = self.clients[self.current_client_index]
        self.current_client_index = (self.current_client_index + 1) % len(self.clients)
        return client
    
    async def _make_groq_request(self, func, *args, **kwargs):
        if not self.clients: raise Exception("No Groq clients")
        errors = []
        for _ in range(len(self.clients) * 2):
            client = self._get_client()
            try:
                return await func(client, *args, **kwargs)
            except Exception as e:
                errors.append(str(e))
                await asyncio.sleep(0.5)
        raise Exception(f"All clients failed: {errors}")

    async def _send_groq_request(self, system, user, task_type="generation", temperature=0.5):
        async def req(client):
            resp = await client.chat.completions.create(
                model=GROQ_MODEL, messages=[{"role":"system","content":system},{"role":"user","content":user}],
                temperature=temperature
            )
            return resp.choices[0].message.content
        return await self._make_groq_request(req)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.replace("```json", "").replace("```", "")
        start = text.find('[') if text.find('[') != -1 else text.find('{')
        end = text.rfind(']') if text.rfind(']') != -1 else text.rfind('}')
        if start != -1 and end != -1: return text[start:end+1]
        return text

    @staticmethod
    def _sanitize_input(text: str, max_length: int = 500) -> str:
        if not text: return ""
        sanitized = text.strip().replace('"', "'").replace('`', "'")
        sanitized = re.sub(r'[\r\n\t]', ' ', sanitized)
        sanitized = re.sub(r'\s+', ' ', sanitized)
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."
        return sanitized

    @staticmethod
    def _clean_html_for_telegram(text: str) -> str:
        """Очищает текст от неподдерживаемых Telegram тегов"""
        # Заменяем списки
        text = text.replace("<ul>", "").replace("</ul>", "")
        text = text.replace("<ol>", "").replace("</ol>", "")
        text = text.replace("<li>", "• ").replace("</li>", "\n")
        
        # Заменяем заголовки на жирный
        text = re.sub(r'<h1>(.*?)</h1>', r'<b>\1</b>', text)
        text = re.sub(r'<h2>(.*?)</h2>', r'<b>\1</b>', text)
        text = re.sub(r'<h3>(.*?)</h3>', r'<b>\1</b>', text)
        
        # Убираем Markdown жирный/курсив, если он смешался с HTML
        text = text.replace("**", "")
        text = text.replace("##", "")
        
        return text

    async def analyze_categories(self, products: str) -> List[str]:
        """Определяет категории блюд"""
        safe_products = self._sanitize_input(products, max_length=300)
        items_count = len(safe_products.split(',')) if ',' in safe_products else len(safe_products.split())
        mix_available = items_count >= 8

        prompt = f"""Analyze products: {products}.
        Return a JSON ARRAY of strings: ["breakfast", "soup", "main", "salad", "dessert", "drink", "snack"].
        Example: ["main", "salad"]."""
        
        res = await self._send_groq_request(prompt, "Categorize", task_type="categorization")
        
        try:
            data = json.loads(self._extract_json(res))
            clean_categories = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str): clean_categories.append(item.lower())
                    elif isinstance(item, dict):
                        vals = list(item.values())
                        if vals and isinstance(vals[0], str): clean_categories.append(vals[0].lower())
            
            if mix_available and "mix" not in clean_categories: clean_categories.insert(0, "mix")
            if not mix_available and "mix" in clean_categories: clean_categories.remove("mix")
            
            return clean_categories if clean_categories else ["main", "soup"]
        except: return ["main", "soup"]

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        safe_products = self._sanitize_input(products)
        prompt = f"""Suggest 5 dishes for category '{category}' using: {safe_products}.
        Return JSON ARRAY: [{{ "name": "Название", "desc": "Описание" }}]"""
        
        res = await self._send_groq_request(prompt, "Menu", task_type="generation")
        try:
            data = json.loads(self._extract_json(res))
            if isinstance(data, list): return data
            if isinstance(data, dict):
                for k in data: 
                    if isinstance(data[k], list): return data[k]
            return []
        except: return []

    async def generate_recipe(self, dish_name: str, products: str) -> str:
        safe_dish = self._sanitize_input(dish_name)
        safe_prods = self._sanitize_input(products)
        is_mix = "полный обед" in safe_dish.lower() or "+" in safe_dish
        instruction = "🍱 ПОЛНЫЙ ОБЕД ИЗ 4 БЛЮД." if is_mix else "Напиши рецепт одного блюда."
        
        prompt = f"""Ты профессиональный шеф. Напиши рецепт: "{safe_dish}".
🛒 ПРОДУКТЫ: {safe_prods}
📦 БАЗА: соль, сахар, вода, масло, специи.

{self.FLAVOR_RULES}
{instruction}

🎯 ТРЕБОВАНИЯ К ФОРМАТУ (Telegram HTML):
- Используй ТОЛЬКО теги <b>, <i>, <code>.
- ЗАПРЕЩЕНО использовать <ul>, <ol>, <li>.
- Для списков используй тире "-" или эмодзи "🔸".

📋 СТРОГИЙ ФОРМАТ:
<b>{safe_dish}</b>

📦 <b>Ингредиенты:</b>
🔸 [Название] — [количество]

📊 <b>Пищевая ценность на 1 порцию:</b>
🥚 Белки: X г
🥑 Жиры: X г
🌾 Углеводы: X г
⚡ Энерг. ценность: X ккал

⏱ <b>Время:</b> X мин
🪦 <b>Сложность:</b> [ур]
👥 <b>Порции:</b> X

👨‍🍳 <b>Приготовление:</b>
1. [шаг]

💡 <b>СОВЕТ ШЕФ-ПОВАРА:</b>
Проанализируй блюдо через триаду: ВКУС, АРОМАТ, ТЕКСТУРА.
"""
        raw_html = await self._send_groq_request(prompt, "Recipe", task_type="recipe")
        # Чистим HTML перед возвратом
        return self._clean_html_for_telegram(raw_html)

    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        safe_dish = self._sanitize_input(dish_name)
        
        prompt = f"""Ты креативный шеф-повар. Рецепт: "{safe_dish}"
{self.FLAVOR_RULES}

🎯 ТРЕБОВАНИЯ К ФОРМАТУ (Telegram HTML):
- Используй ТОЛЬКО теги <b>, <i>.
- ЗАПРЕЩЕНО использовать <ul>, <ol>, <li>.
- Для списков используй тире "-".

📋 СТРОГИЙ ФОРМАТ:
<b>{safe_dish}</b>

📦 <b>Ингредиенты:</b>
🔸 ...

📊 <b>Пищевая ценность:</b> ...
⏱ <b>Время:</b> X мин
🪦 <b>Сложность:</b> ...
👥 <b>Порции:</b> ...

👨‍🍳 <b>Приготовление:</b>
1. ...

💡 <b>СОВЕТ ШЕФ-ПОВАРА:</b>
Проанализируй блюдо через триаду: ВКУС, АРОМАТ, ТЕКСТУРА.
"""
        raw_html = await self._send_groq_request(prompt, "Recipe", task_type="freestyle")
        return self._clean_html_for_telegram(raw_html)

    async def transcribe_voice(self, audio_bytes: bytes) -> str:
        async def transcribe(client):
            response = await client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=("audio.ogg", audio_bytes, "audio/ogg"),
                language="ru",
                response_format="text",
            )
            return response
        try:
            return await self._make_groq_request(transcribe)
        except Exception as e:
            return f"❌ Ошибка: {str(e)[:100]}"

    async def translate_to_english(self, text: str) -> str:
        prompt = f"""You are a food photographer assistant. 
        Describe the dish '{text}' in English for an image generation prompt. 
        Focus on visual appearance (colors, plating, steam). 
        Max 40 words. Output ONLY the description."""
        return await self._send_groq_request("Translator", prompt, temperature=0.3)

    async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
        """Парсит рецепт в JSON для карточки"""
        prompt = """Parse this recipe to JSON: title, ingredients(list), time, portions, difficulty, chef_tip.
        Return ONLY valid JSON object. No markdown formatting."""
        
        res = await self._send_groq_request(prompt, recipe_text, task_type="validation")
        
        try:
            data = json.loads(self._extract_json(res))
            
            # --- ЗАЩИТА ОТ ОШИБОК ---
            # 1. Если вернулся список - берем первый элемент
            if isinstance(data, list):
                if len(data) > 0: data = data[0]
                else: return {}
            
            # 2. Если вернулась строка (бывает двойная упаковка json) - пробуем распарсить еще раз
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except:
                    pass

            # 3. Если все равно не словарь - возвращаем пусто
            if not isinstance(data, dict):
                logger.error(f"Card parse error: Expected dict, got {type(data)}")
                return {}
                
            return data
        except Exception as e:
            logger.error(f"Card parse fatal error: {e}")
            return {}

groq_service = GroqService()