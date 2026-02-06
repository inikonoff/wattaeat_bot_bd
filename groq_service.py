import json
import re
import logging
import asyncio
from typing import Dict, List, Optional
from openai import AsyncOpenAI

from config import GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger(__name__)

class GroqService:
    """Сервис для работы с Groq API (LLM + Whisper 3 Turbo)"""
    
    # Правила сочетаемости
    FLAVOR_RULES = """❗️ ПРАВИЛА СОЧЕТАЕМОСТИ:
🎭 КОНТРАСТЫ: Жирное + Кислое, Сладкое + Солёное, Мягкое + Хрустящее.
✨ УСИЛЕНИЕ: Помидор + Базилик, Рыба + Укроп + Лимон, Тыква + Корица, Картофель + Лук + Укроп
👑 ОДИН ГЛАВНЫЙ ИНГРЕДИЕНТ: В каждом блюде один "король".
❌ ТАБУ: Рыба + Молочные продукты (в горячем), два сильных мяса в одной композиции."""

    # Словарь для определения языка
    LANGUAGE_KEYWORDS = {
        'german': ['kartoffel', 'zwiebel', 'karotte', 'tomate', 'gurke', 'käse', 'fleisch', 'wurst', 'brötchen'],
        'english': ['potato', 'onion', 'carrot', 'tomato', 'cucumber', 'cheese', 'meat', 'bread', 'butter'],
        'french': ['pomme de terre', 'oignon', 'carotte', 'tomate', 'concombre', 'fromage', 'viande', 'pain'],
        'spanish': ['patata', 'cebolla', 'zanahoria', 'tomate', 'pepino', 'queso', 'carne', 'pan'],
        'italian': ['patata', 'cipolla', 'carota', 'pomodoro', 'cetriolo', 'formaggio', 'carne', 'pane']
    }
    
    # Карта национальных кухонь
    NATIONAL_CUISINES = {
        'german': 'Немецкая кухня (bratwurst, sauerkraut, schnitzel, kartoffelsalat)',
        'english': 'Английская кухня (roast beef, fish and chips, shepherd\'s pie)',
        'french': 'Французская кухня (ratatouille, coq au vin, quiche lorraine)',
        'spanish': 'Испанская кухня (paella, gazpacho, tortilla española)',
        'italian': 'Итальянская кухня (pasta, pizza, risotto, tiramisu)'
    }

    def __init__(self):
        self.clients = []
        self.current_client_index = 0
        self._init_clients()
    
    def _init_clients(self):
        """Инициализация клиентов Groq"""
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
                logger.info(f"✅ Groq client: {key[:8]}...")
            except Exception as e:
                logger.error(f"❌ Error client {key[:8]}: {e}")
        
        logger.info(f"✅ Total Groq clients: {len(self.clients)}")
    
    def _get_client(self):
        """Получаем следующего клиента по кругу"""
        if not self.clients:
            return None
        client = self.clients[self.current_client_index]
        self.current_client_index = (self.current_client_index + 1) % len(self.clients)
        return client
    
    async def _make_groq_request(self, func, *args, **kwargs):
        """Делаем запрос с перебором ключей при ошибках"""
        if not self.clients:
            raise Exception("No Groq clients available")
        
        errors = []
        for _ in range(len(self.clients) * 2):
            client = self._get_client()
            if not client:
                break
            try:
                return await func(client, *args, **kwargs)
            except Exception as e:
                errors.append(str(e))
                logger.warning(f"Request error: {e}")
                await asyncio.sleep(0.5)
        
        raise Exception(f"All clients failed: {'; '.join(errors[:3])}")
    
    async def _send_groq_request(
        self, 
        system_prompt: str, 
        user_text: str, 
        task_type: str = "generation", 
        temperature: float = 0.5,
        max_tokens: int = 2000
    ):
        """Отправка запроса к LLM"""
        async def req(client):
            resp = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return resp.choices[0].message.content.strip()
        
        return await self._make_groq_request(req)
    
    @staticmethod
    def _extract_json(text: str) -> str:
        """Извлекает JSON из текста"""
        text = text.replace("```json", "").replace("```", "")
        start_brace = text.find('{')
        start_bracket = text.find('[')
        
        if start_brace == -1:
            start = start_bracket
        elif start_bracket == -1:
            start = start_brace
        else:
            start = min(start_brace, start_bracket)
        
        end_brace = text.rfind('}')
        end_bracket = text.rfind(']')
        end = max(end_brace, end_bracket)
        
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        return text.strip()
    
    @staticmethod
    def _sanitize_input(text: str, max_length: int = 500) -> str:
        """Очищает и обрезает входной текст"""
        if not text:
            return ""
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
        
        # Убираем Markdown жирный/курсив
        text = text.replace("**", "")
        text = text.replace("##", "")
        
        return text
    
    # ==================== WHISPER 3 TURBO ====================
    
    async def transcribe_voice(self, audio_bytes: bytes) -> str:
        """Транскрибация голоса через Whisper v3 Turbo"""
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
            logger.error(f"Transcription error: {e}")
            return f"❌ Ошибка распознавания: {str(e)[:100]}"
    
    # ==================== ЯЗЫКОВЫЕ ФУНКЦИИ ====================
    
    def detect_language_from_products(self, products: str) -> tuple[str, list]:
        """Определяет язык продуктов и возвращает иностранные слова"""
        products_lower = products.lower()
        detected_languages = []
        foreign_words = []
        
        for lang, keywords in self.LANGUAGE_KEYWORDS.items():
            lang_words = []
            for keyword in keywords:
                # Ищем целые слова, чтобы избежать частичных совпадений
                pattern = r'\b' + re.escape(keyword) + r'\b'
                if re.search(pattern, products_lower):
                    lang_words.append(keyword)
            
            if lang_words:
                detected_languages.append(lang)
                foreign_words.extend(lang_words)
        
        # Возвращаем основной язык (первый обнаруженный) и список иностранных слов
        main_language = detected_languages[0] if detected_languages else 'russian'
        return main_language, foreign_words
    
    def create_language_context(self, language: str, foreign_words: list) -> str:
        """Создает контекст для иностранных продуктов"""
        if language == 'russian' or not foreign_words:
            return ""
        
        # Создаем перевод иностранных слов
        translations = ", ".join([f"{word} (ингредиент)" for word in foreign_words])
        cuisine = self.NATIONAL_CUISINES.get(language, "международная кухня")
        
        return f"""
🌍 ИНОСТРАННЫЕ ПРОДУКТЫ:
Обнаружены продукты на {language} языке: {translations}
Рекомендую использовать {cuisine}.
В рецепте указывай иностранные названия с переводом в скобках, например: "Kartoffeln (картофель)".
"""
    
    # ==================== АНАЛИЗ И КАТЕГОРИИ ====================
    
    async def analyze_categories(self, products: str) -> List[str]:
        """Определяет категории блюд на основе продуктов"""
        safe_products = self._sanitize_input(products, max_length=300)
        
        # Определяем язык продуктов
        language, foreign_words = self.detect_language_from_products(safe_products)
        language_context = self.create_language_context(language, foreign_words)
        
        items = re.split(r'[,;\n]', safe_products)
        items_count = len([i for i in items if len(i.strip()) > 1])
        mix_available = items_count >= 8
        
        prompt = f"""Analyze these products: {safe_products}
{language_context}
Return a JSON ARRAY of category strings from: ["breakfast", "soup", "main", "salad", "dessert", "drink", "snack", "mix"]

Example response: ["main", "soup", "salad"]

Return ONLY the JSON array, no other text."""
        
        res = await self._send_groq_request(prompt, "Categorize", task_type="categorization", temperature=0.2)
        
        try:
            data = json.loads(self._extract_json(res))
            clean_categories = []
            
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        clean_categories.append(item.lower())
                    elif isinstance(item, dict):
                        vals = list(item.values())
                        if vals and isinstance(vals[0], str):
                            clean_categories.append(vals[0].lower())
            
            # Добавляем/убираем mix в зависимости от количества продуктов
            if mix_available and "mix" not in clean_categories:
                clean_categories.insert(0, "mix")
            if not mix_available and "mix" in clean_categories:
                clean_categories.remove("mix")
            
            return clean_categories[:4] if clean_categories else ["main", "soup"]
        except:
            return ["main", "soup"]
    
    # ==================== ГЕНЕРАЦИЯ БЛЮД ====================
    
    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        """Генерирует список блюд для категории"""
        safe_products = self._sanitize_input(products, max_length=400)
        
        # Определяем язык продуктов
        language, foreign_words = self.detect_language_from_products(safe_products)
        language_context = self.create_language_context(language, foreign_words)
        
        if category == "mix":
            prompt = f"""Create ONE full meal with 4 dishes using: {safe_products}
{language_context}

Return JSON ARRAY with exactly 4 objects:
[
  {{"name": "Суп", "desc": "Description"}},
  {{"name": "Второе блюдо", "desc": "Description"}},
  {{"name": "Салат", "desc": "Description"}},
  {{"name": "Напиток", "desc": "Description"}}
]

Return ONLY the JSON array."""
        else:
            prompt = f"""Suggest 5-6 dishes for category '{category}' using: {safe_products}
{language_context}

Return JSON ARRAY:
[{{"name": "Dish name", "desc": "Short appetizing description"}}]

Return ONLY the JSON array."""
        
        res = await self._send_groq_request(prompt, "Generate menu", task_type="generation", temperature=0.5)
        
        try:
            data = json.loads(self._extract_json(res))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for k in data:
                    if isinstance(data[k], list):
                        return data[k]
            return []
        except:
            return []
    
    # ==================== ГЕНЕРАЦИЯ РЕЦЕПТОВ ====================
    
    async def generate_recipe(self, dish_name: str, products: str) -> str:
        """Генерация полного рецепта"""
        safe_dish = self._sanitize_input(dish_name, max_length=150)
        safe_prods = self._sanitize_input(products, max_length=600)
        
        # Определяем язык продуктов
        language, foreign_words = self.detect_language_from_products(safe_prods)
        language_context = self.create_language_context(language, foreign_words)
        
        is_mix = "полный обед" in safe_dish.lower() or "комплекс" in safe_dish.lower()
        instruction = "🍱 ПОЛНЫЙ ОБЕД ИЗ 4 БЛЮД." if is_mix else "Напиши рецепт одного блюда."
        
        prompt = f"""Ты профессиональный шеф. Напиши рецепт: "{safe_dish}"
🛒 ПРОДУКТЫ: {safe_prods}
{language_context}
📦 БАЗА (всегда доступно): соль, сахар, вода, масло, специи.

{self.FLAVOR_RULES}
{instruction}

🎯 ТРЕБОВАНИЯ К ФОРМАТУ (Telegram HTML):
- Используй ТОЛЬКО теги <b>, <i>, <code>.
- ЗАПРЕЩЕНО использовать <ul>, <ol>, <li>, <h1>, <h2>.
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
🪦 <b>Сложность:</b> [уровень]
👥 <b>Порции:</b> X

👨‍🍳 <b>Приготовление:</b>
1. [шаг]
2. [шаг]

💡 <b>СОВЕТ ШЕФ-ПОВАРА:</b>
[Один конкретный совет для улучшения вкуса. 1-2 предложения.]
"""
        
        raw_html = await self._send_groq_request(prompt, "Write recipe", task_type="recipe", temperature=0.4, max_tokens=3000)
        return self._clean_html_for_telegram(raw_html) + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
    
    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        """Генерация рецепта без продуктов (креативный режим)"""
        safe_dish = self._sanitize_input(dish_name, max_length=100)
        
        # Нормализуем название блюда (именительный падеж)
        # В реальном приложении здесь нужна полноценная библиотека для морфологии
        normalized_dish = self._normalize_dish_name(safe_dish)
        
        prompt = f"""Ты креативный шеф-повар. Создай рецепт: "{normalized_dish}"

{self.FLAVOR_RULES}

🎯 ТРЕБОВАНИЯ К ФОРМАТУ (Telegram HTML):
- Используй ТОЛЬКО теги <b>, <i>, <code>.
- ЗАПРЕЩЕНО использовать <ul>, <ol>, <li>, <h1>, <h2>.
- Для списков используй тире "-" или эмодзи "🔸".

📋 СТРОГИЙ ФОРМАТ:
<b>{normalized_dish}</b>

📦 <b>Ингредиенты:</b>
🔸 [Название] — [количество]

📊 <b>Пищевая ценность на 1 порцию:</b>
🥚 Белки: X г
🥑 Жиры: X г
🌾 Углеводы: X г
⚡ Энерг. ценность: X ккал

⏱ <b>Время:</b> X мин
🪦 <b>Сложность:</b> [уровень]
👥 <b>Порции:</b> X

👨‍🍳 <b>Приготовление:</b>
1. [шаг]
2. [шаг]

💡 <b>СОВЕТ ШЕФ-ПОВАРА:</b>
[Лайфхак по приготовлению или подаче. 1-2 предложения.]
"""
        
        raw_html = await self._send_groq_request(prompt, "Create recipe", task_type="freestyle", temperature=0.6, max_tokens=2000)
        return self._clean_html_for_telegram(raw_html) + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
    
    def _normalize_dish_name(self, dish_name: str) -> str:
        """Нормализует название блюда (упрощенная версия)"""
        # Удаляем кавычки, если они только в начале и конце
        dish_name = dish_name.strip().strip('"\'')
        
        # Простая нормализация: первая буква заглавная
        if dish_name and dish_name[0].islower():
            dish_name = dish_name[0].upper() + dish_name[1:]
        
        # Убираем лишние знаки препинания в конце
        dish_name = dish_name.rstrip('.!?,;')
        
        return dish_name
    
    # ==================== ПАРСИНГ РЕЦЕПТА ДЛЯ КАРТОЧКИ ====================
    
    async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
        """Парсит рецепт в JSON для генерации карточки"""
        prompt = """Parse this recipe to JSON with these EXACT fields:
{
  "title": "Dish name",
  "ingredients": ["ingredient 1", "ingredient 2", "ingredient 3"],
  "time": "30",
  "portions": "2",
  "difficulty": "Easy",
  "chef_tip": "One sentence tip"
}

CRITICAL RULES:
- Return ONLY valid JSON object (not array, not string)
- NO markdown formatting (no ```json```)
- "ingredients" must be an array of strings (3-8 items)
- "time" must be a NUMBER as string (e.g. "30" not "30 min")
- "portions" must be a NUMBER as string (e.g. "2")
- All values must be strings
- Remove all HTML tags from values

Recipe to parse:"""
        
        try:
            res = await self._send_groq_request(
                prompt, 
                recipe_text[:1000],  # Ограничиваем длину
                task_type="validation", 
                temperature=0.1,
                max_tokens=500
            )
            
            # Очищаем от markdown
            clean_json = self._extract_json(res)
            
            # Пробуем распарсить
            data = json.loads(clean_json)
            
            # КРИТИЧЕСКАЯ ПРОВЕРКА: если вернулась строка - пробуем еще раз
            if isinstance(data, str):
                logger.warning("Got string instead of dict, trying to parse again")
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
                logger.error(f"Expected dict, got {type(data)}")
                return self._get_fallback_card_data(recipe_text)
            
            # Валидация и очистка полей
            cleaned_data = self._validate_and_clean_card_data(data)
            return cleaned_data
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return self._get_fallback_card_data(recipe_text)
        except Exception as e:
            logger.error(f"Card parse error: {e}")
            return self._get_fallback_card_data(recipe_text)
    
    def _validate_and_clean_card_data(self, data: Dict) -> Dict:
        """Валидирует и очищает данные карточки"""
        # Обязательные поля
        required_fields = ['title', 'ingredients', 'time', 'portions', 'difficulty', 'chef_tip']
        
        for field in required_fields:
            if field not in data:
                data[field] = self._get_default_value(field)
        
        # Очищаем title от HTML
        data['title'] = self._clean_html_tags(str(data['title']))
        
        # Проверяем ingredients - должен быть список
        if not isinstance(data['ingredients'], list):
            data['ingredients'] = [str(data['ingredients'])]
        
        # Очищаем ингредиенты от HTML и эмодзи
        clean_ingredients = []
        for ing in data['ingredients'][:8]:
            clean_ing = self._clean_html_tags(str(ing))
            clean_ing = clean_ing.replace("🔸", "").replace("•", "").strip()
            if clean_ing:
                clean_ingredients.append(clean_ing)
        
        data['ingredients'] = clean_ingredients if clean_ingredients else ["Не указано"]
        
        # Очищаем время от слов, оставляем только число
        time_str = str(data['time'])
        numbers = re.findall(r'\d+', time_str)
        data['time'] = numbers[0] if numbers else "30"
        
        # Очищаем порции от слов
        portions_str = str(data['portions'])
        numbers = re.findall(r'\d+', portions_str)
        data['portions'] = numbers[0] if numbers else "2"
        
        # Очищаем остальные поля от HTML
        data['difficulty'] = self._clean_html_tags(str(data['difficulty']))
        data['chef_tip'] = self._clean_html_tags(str(data['chef_tip']))
        
        return data
    
    @staticmethod
    def _clean_html_tags(text: str) -> str:
        """Убирает все HTML теги из текста"""
        return re.sub(r'<[^>]+>', '', text).strip()
    
    def _get_fallback_card_data(self, recipe_text: str) -> Dict:
        """Возвращает fallback данные если парсинг не удался"""
        # Пробуем извлечь название из первой строки
        lines = recipe_text.split('\n')
        title = "Вкусное блюдо"
        
        for line in lines[:5]:
            clean_line = self._clean_html_tags(line).strip()
            if len(clean_line) > 3 and not clean_line.startswith(('📦', '📊', '⏱', '🪦', '👥', '👨‍🍳', '💡')):
                title = clean_line
                break
        
        return {
            "title": title,
            "ingredients": ["Смотрите полный рецепт выше"],
            "time": "30",
            "portions": "2",
            "difficulty": "Средняя",
            "chef_tip": "Готовьте с любовью и наслаждайтесь процессом!"
        }
    
    @staticmethod
    def _get_default_value(field: str) -> any:
        """Возвращает дефолтное значение для поля"""
        defaults = {
            'title': 'Рецепт',
            'ingredients': ['Не указано'],
            'time': '30',
            'portions': '2',
            'difficulty': 'Средняя',
            'chef_tip': 'Приятного аппетита!'
        }
        return defaults.get(field, 'Не указано')
    
    # ==================== ПЕРЕВОД ДЛЯ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЙ ====================
    
    async def translate_to_english(self, text: str) -> str:
        """Переводит название блюда на английский для генерации изображений"""
        prompt = """You are a food photographer assistant. 
Describe this dish in English for an image generation prompt. 
Focus on visual appearance (colors, plating, steam, garnish). 
Maximum 40 words. 
Output ONLY the description, no quotes."""
        
        return await self._send_groq_request(
            prompt, 
            text, 
            task_type="validation",
            temperature=0.3,
            max_tokens=100
        )

# Глобальный экземпляр
groq_service = GroqService()
