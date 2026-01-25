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
[Здесь напиши ОДНО конкретное предложение. Какой ОДИН секретный ингредиент (специю, траву, соус, овощ, фрукт, алкогольный напиток) нужно добавить, чтобы вкус стал идеальным? Не пиши слова "триада" или "анализ". Просто дай совет.]
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
[Напиши краткий лайфхак по приготовлению этого блюда или совет по подаче. Максимум 2 предложения.]
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

    
# Замените метод parse_recipe_for_card в groq_service.py:

async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
    """Парсит рецепт в JSON для карточки"""
    prompt = """Parse this recipe to JSON with these EXACT fields:
{
  "title": "Dish name",
  "ingredients": ["ingredient 1", "ingredient 2", ...],
  "time": "30 min",
  "portions": "2",
  "difficulty": "Easy",
  "chef_tip": "One sentence tip"
}

IMPORTANT: 
- Return ONLY valid JSON object (not array, not string)
- No markdown formatting (no ```json```)
- ingredients must be an array of strings
- All values must be strings

Recipe to parse:"""
    
    res = await self._send_groq_request(prompt, recipe_text, task_type="validation", temperature=0.2)
    
    try:
        # Очищаем от markdown
        clean_json = self._extract_json(res)
        
        # Пробуем распарсить
        data = json.loads(clean_json)
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: если вернулась строка - пробуем еще раз
        if isinstance(data, str):
            logger.warning(f"Got string instead of dict, trying to parse again: {data[:100]}")
            try:
                data = json.loads(data)
            except:
                logger.error("Double JSON parse failed, returning fallback")
                return self._get_fallback_card_data(recipe_text)
        
        # Если вернулся список - берем первый элемент
        if isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict):
                data = data[0]
            else:
                logger.error("Got list but no valid dict inside")
                return self._get_fallback_card_data(recipe_text)
        
        # Финальная проверка: это точно словарь?
        if not isinstance(data, dict):
            logger.error(f"Final check failed: Expected dict, got {type(data)}")
            return self._get_fallback_card_data(recipe_text)
        
        # Валидация обязательных полей
        required_fields = ['title', 'ingredients', 'time', 'portions']
        for field in required_fields:
            if field not in data:
                logger.warning(f"Missing field: {field}, adding default")
                data[field] = GroqService._get_default_value(field)
        
        # Проверяем, что ingredients - это список
        if not isinstance(data.get('ingredients'), list):
            logger.warning("Ingredients is not a list, converting")
            data['ingredients'] = [str(data.get('ingredients', 'Не указано'))]
        
        return data
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}, raw response: {res[:200]}")
        return GroqService._get_fallback_card_data(recipe_text)
    except Exception as e:
        logger.error(f"Card parse fatal error: {e}")
        return GroqService._get_fallback_card_data(recipe_text)

def _get_fallback_card_data(self, recipe_text: str) -> Dict:
    """Возвращает fallback данные если парсинг не удался"""
    # Пробуем хотя бы извлечь название из первой строки
    lines = recipe_text.split('\n')
    title = "Рецепт"
    for line in lines:
        clean_line = line.replace('<b>', '').replace('</b>', '').strip()
        if len(clean_line) > 3 and not clean_line.startswith('📦'):
            title = clean_line
            break
    
    return {
        "title": title,
        "ingredients": ["Смотрите полный рецепт выше"],
        "time": "30 мин",
        "portions": "2",
        "difficulty": "Средняя",
        "chef_tip": "Готовьте с любовью!"
    }

@staticmethod
def _get_fallback_card_data(recipe_text: str) -> Dict:
    """Возвращает fallback данные если парсинг не удался"""
    # Пробуем хотя бы извлечь название из первой строки
    lines = recipe_text.split('\n')
    title = "Рецепт"
    for line in lines:
        clean_line = line.replace('<b>', '').replace('</b>', '').strip()
        if len(clean_line) > 3 and not clean_line.startswith('📦'):
            title = clean_line
            break
    
    return {
        "title": title,
        "ingredients": ["Смотрите полный рецепт выше"],
        "time": "30 мин",
        "portions": "2",
        "difficulty": "Средняя",
        "chef_tip": "Готовьте с любовью!"
    }

@staticmethod
def _get_default_value(field: str) -> any:
    """Возвращает дефолтное значение для поля"""
    defaults = {
        'title': 'Рецепт',
        'ingredients': ['Не указано'],
        'time': '30 мин',
        'portions': '2',
        'difficulty': 'Средняя',
        'chef_tip': 'Приятного аппетита!'
    }
    return defaults.get(field, 'Не указано')
groq_service = GroqService()
