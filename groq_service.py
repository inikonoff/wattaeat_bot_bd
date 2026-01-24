import json
import re
import logging
import asyncio
import random
from typing import Dict, List, Optional
from openai import AsyncOpenAI

from config import GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger(__name__)

class GroqService:
    """Сервис для работы с Groq API (LLM + Whisper 3 Turbo)"""
    
    def __init__(self):
        self.clients = []
        self.current_client_index = 0
        self._init_clients()
        
        # Конфигурация моделей
        self.LLM_CONFIG = {
            "validation": {"temperature": 0.1, "max_tokens": 200},
            "categorization": {"temperature": 0.2, "max_tokens": 500},
            "generation": {"temperature": 0.5, "max_tokens": 1500},
            "recipe": {"temperature": 0.4, "max_tokens": 3000},
            "freestyle": {"temperature": 0.6, "max_tokens": 2000},
            "full_menu": {"temperature": 0.4, "max_tokens": 4000}
        }
        
        # Правила сочетаемости
        self.FLAVOR_RULES = """❗️ ПРАВИЛА СОЧЕТАЕМОСТИ:
🎭 КОНТРАСТЫ: Жирное + Кислое, Сладкое + Солёное, Мягкое + Хрустящее.
✨ УСИЛЕНИЕ: Помидор + Базилик, Рыба + Укроп + Лимон, Тыква + Корица, Картофель + Лук + Укроп
👑 ОДИН ГЛАВНЫЙ ИНГРЕДИЕНТ: В каждом блюде один "король".
❌ ТАБУ: Рыба + Молочные продукты (в горячем), два сильных мяса в одной композиции."""
    
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
        
        logger.info(f"✅ Total clients: {len(self.clients)}")
    
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
        
        for _ in range(len(self.clients) * 2):  # Пробуем каждый ключ 2 раза
            client = self._get_client()
            if not client:
                break
            
            try:
                return await func(client, *args, **kwargs)
            except Exception as e:
                errors.append(str(e))
                logger.warning(f"Request error: {e}")
                await asyncio.sleep(0.5 + random.random())
        
        raise Exception(f"All clients failed: {'; '.join(errors[:3])}")
    
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
    
    # ==================== ОБРАБОТКА ТЕКСТА ====================
    
    @staticmethod
    def _detect_input_language(text: str) -> str:
        """Определяет язык ввода: 'ru' или 'other'"""
        if not text:
            return "ru"
        if re.search(r'[а-яА-ЯёЁ]', text):
            return "ru"
        return "other"
    
    @staticmethod
    def _sanitize_input(text: str, max_length: int = 500) -> str:
        if not text:
            return ""
        sanitized = text.strip()
        sanitized = sanitized.replace('"', "'").replace('`', "'")
        sanitized = re.sub(r'[\r\n\t]', ' ', sanitized)
        sanitized = re.sub(r'\s+', ' ', sanitized)
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "..."
        return sanitized
    
    async def _send_groq_request(
        self, 
        system_prompt: str, 
        user_text: str, 
        task_type: str = "generation",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """Отправка запроса к LLM"""
        config = self.LLM_CONFIG.get(task_type, self.LLM_CONFIG["generation"])
        final_temperature = temperature if temperature is not None else config["temperature"]
        final_max_tokens = max_tokens if max_tokens is not None else config["max_tokens"]
        
        async def make_request(client):
            response = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                max_tokens=final_max_tokens,
                temperature=final_temperature
            )
            return response.choices[0].message.content.strip()
        
        return await self._make_groq_request(make_request)
    
    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.replace("```json", "").replace("```", "")
        start_brace = text.find('{')
        start_bracket = text.find('[')
        if start_brace == -1: start = start_bracket
        elif start_bracket == -1: start = start_brace
        else: start = min(start_brace, start_bracket)
        end_brace = text.rfind('}')
        end_bracket = text.rfind(']')
        end = max(end_brace, end_bracket)
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        return text.strip()
    
    # ==================== ВАЛИДАЦИЯ И КАТЕГОРИИ ====================
    
    async def validate_ingredients(self, text: str) -> bool:
        """Проверка текста на валидность продуктов"""
        prompt = """Ты эксперт по безопасности продуктов. Проверь текст на валидность.
📋 КРИТЕРИИ: ✅ ПРИНЯТЬ (еда, специи, опечатки), ❌ ОТКЛОНИТЬ (яд, мат, бред, приветствия, <3 симв).
🎯 СТРОГИЙ JSON: {"valid": true, "reason": "кратко"}"""
        safe_text = self._sanitize_input(text, max_length=200)
        res = await self._send_groq_request(prompt, f'Текст: "{safe_text}"', task_type="validation")
        try:
            data = json.loads(self._extract_json(res))
            return data.get("valid", False)
        except:
            return "true" in res.lower()
    
    async def analyze_categories(self, products: str) -> List[str]:
        """Анализ продуктов и определение категорий блюд"""
        safe_products = self._sanitize_input(products, max_length=300)

        if ',' not in safe_products and ';' not in safe_products and '\n' not in safe_products:
            items = [i.strip() for i in safe_products.split() if len(i.strip()) > 1]
        else:
            items = [i.strip() for i in re.split(r'[,;\n\.]', safe_products) if len(i.strip()) > 1]

        items_count = len(items)
        mix_available = items_count >= 8

        prompt = f"""Ты шеф-повар. Определи категории блюд.
🛒 ПРОДУКТЫ: {safe_products}
📦 БАЗА (ВСЕГДА В НАЛИЧИИ): соль, сахар, вода, подсолнечное масло, специи.
📊 Кол-во продуктов: {items_count}

📚 КАТЕГОРИИ:
- "mix" (ПОЛНЫЙ ОБЕД) — ОБЯЗАТЕЛЬНО ПЕРВЫМ, если продуктов >= 8.
- "soup", "main", "salad", "breakfast", "dessert", "drink", "snack".

🎯 ТРЕБОВАНИЯ:
1. Если продуктов >= 8, верни "mix" и еще 3 подходящие категории.
2. Если продуктов < 8, верни от 2 до 4 категорий.
🎯 JSON: ["mix", "cat2", "cat3", "cat4"]"""
        
        res = await self._send_groq_request(prompt, "Определи категории", task_type="categorization", temperature=0.1)
        try:
            data = json.loads(self._extract_json(res))
            if isinstance(data, list):
                if mix_available and "mix" not in data:
                    data.insert(0, "mix")
                elif not mix_available and "mix" in data:
                    data = [item for item in data if item != "mix"]
                return data[:4]
        except:
            pass
        return ["mix", "main", "soup", "salad"] if mix_available else ["main", "soup"]
    
    # ==================== ГЕНЕРАЦИЯ БЛЮД И РЕЦЕПТОВ ====================
    
    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        """Генерация списка блюд для категории"""
        safe_products = self._sanitize_input(products, max_length=400)
        input_language = self._detect_input_language(safe_products)
        base_instruction = "⚠️ ВАЖНО: соль, сахар, вода, масло и специи ДОСТУПНЫ ВСЕГДА."
        
        if category == "mix":
            prompt = f"""📝 ЗАДАНИЕ: Составь ОДИН комплексный обед из 4-х блюд.
🛒 ПРОДУКТЫ: {safe_products}
📦 БАЗА: соль, сахар, вода, масло, специи.
{base_instruction}

🎯 ПРАВИЛА ЯЗЫКА:
- Если продукты на русском: используй русские названия (Суп, Второе блюдо, Салат, Напиток)
- Если продукты на другом языке: используй названия на языке оригинала без перевода: "Soup (Суп)"

🎯 ТРЕБОВАНИЯ К МЕНЮ:
- СТРОГО 4 блюда: 1) Суп, 2) Второе блюдо, 3) Салат, 4) Напиток
- Распредели продукты логично.
- Описание (desc) ВСЕГДА на русском языке.

🎯 JSON:
[
  {{ "name": "{'Суп' if input_language == 'ru' else 'Soup (Суп)'}", "desc": "Аппетитное описание на русском" }},
  {{ "name": "{'Второе блюдо' if input_language == 'ru' else 'Main course (Второе блюдо)'}", "desc": "Аппетитное описание на русском" }},
  {{ "name": "{'Салат' if input_language == 'ru' else 'Salad (Салат)'}", "desc": "Аппетитное описание на русском" }},
  {{ "name": "{'Напиток' if input_language == 'ru' else 'Drink (Напиток)'}", "desc": "Аппетитное описание на русском" }}
]"""
        else:
            language_rule = ""
            if input_language == "ru":
                language_rule = """🎯 ПРАВИЛА ЯЗЫКА:
- Поле "name": Название блюда НА РУССКОМ ЯЗЫКЕ
- Поле "desc": Описание на русском языке"""
            else:
                language_rule = """🎯 ПРАВИЛА ЯЗЫКА:
- Поле "name": Название блюда НА ЯЗЫКЕ ВВОДА (оригинале) + перевод в скобках.
- Поле "desc": Описание на РУССКОМ ЯЗЫКЕ"""
            
            prompt = f"""📝 ЗАДАНИЕ: Составь меню "{category}".
🛒 ПРОДУКТЫ: {safe_products}
{base_instruction}
{language_rule}
🎯 ТРЕБОВАНИЯ:
- Предложи 5-6 разнообразных блюд
- Описания должны быть аппетитными и краткими
🎯 JSON: [{{ "name": "...", "desc": "..." }}]"""
        
        res = await self._send_groq_request(prompt, "Генерируй меню", task_type="generation")
        try:
            dishes = json.loads(self._extract_json(res))
            if category == "mix":
                if len(dishes) != 4:
                    expected_names = [
                        "Суп" if input_language == "ru" else "Soup (Суп)",
                        "Второе блюдо" if input_language == "ru" else "Main course (Второе блюдо)",
                        "Салат" if input_language == "ru" else "Salad (Салат)",
                        "Напиток" if input_language == "ru" else "Drink (Напиток)"
                    ]
                    if dishes and len(dishes) > 0:
                        new_dishes = []
                        for i in range(4):
                            if i < len(dishes):
                                dishes[i]["name"] = expected_names[i]
                                new_dishes.append(dishes[i])
                            else:
                                new_dishes.append({"name": expected_names[i], "desc": "Вкусное блюдо"})
                        dishes = new_dishes
            return dishes
        except Exception as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            return []
    
    async def generate_recipe(self, dish_name: str, products: str) -> str:
        """Генерация полного рецепта"""
        safe_dish_name = self._sanitize_input(dish_name, max_length=150)
        safe_products = self._sanitize_input(products, max_length=600)
        input_language = self._detect_input_language(safe_products)

        prompt = f"""Ты профессиональный шеф. Напиши рецепт: "{safe_dish_name}"
🛒 ПРОДУКТЫ: {safe_products}
📦 БАЗА: соль, сахар, вода, масло, специи.
{self.FLAVOR_RULES}

🚨 КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ЯЗЫКА:
{"1. Названия ингредиентов пиши на РУССКОМ языке без скобок." if input_language == "ru" else "1. Названия ингредиентов пиши на ОРИГИНАЛЬНОМ языке продуктов, а в скобках добавляй русский перевод. Например: 面粉 (мука), 鸡蛋 (яйца), Eggs (яйца)."}
2. ВСЕ ОСТАЛЬНОЕ (шаги приготовления, советы, пояснения) пиши ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.
3. ЗАПРЕЩЕНО использовать иностранные слова в разделе "Приготовление" и "Совет шеф-повара".

⚠️ ФОРМАТИРОВАНИЕ:
- Используй ТОЛЬКО HTML теги (<b>...</b>).
- НЕ ИСПОЛЬЗУЙ Markdown (**...**).

📋 <b>ОБЯЗАТЕЛЬНЫЙ ФОРМАТ:</b>

🍽️ <b>{safe_dish_name}</b>

📦 <b>Ингредиенты:</b>
🔸 [Название{' (Перевод)' if input_language != 'ru' else ''}] - [количество]
🔸 [Название{' (Перевод)' if input_language != 'ru' else ''}] - [количество]

📊 <b>Пищевая ценность на 1 порцию:</b>
🥚 Белки: [X] г
🥑 Жиры: [X] г
🌾 Углеводы: [X] г
⚡ Энерг. ценность: [X] ккал

⏱ <b>Время:</b> [X] минут
🪦 <b>Сложность:</b> [уровень]
👥 <b>Порции:</b> [X] человека

🔪 <b>Приготовление:</b>
[ВЕСЬ текст инструкций ТОЛЬКО на русском языке - никаких иностранных слов!]

💡 <b>Совет шеф-повара:</b>
[Полезный совет ТОЛЬКО на русском языке]"""
        
        res = await self._send_groq_request(prompt, "Напиши рецепт", task_type="recipe")
        if self._is_refusal(res):
            return res
        return res + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
    
    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        """Генерация рецепта без продуктов (креативный режим)"""
        safe_dish_name = self._sanitize_input(dish_name, max_length=100)
        input_language = self._detect_input_language(safe_dish_name)

        prompt = f"""Ты креативный шеф-повар. Рецепт: "{safe_dish_name}"
{self.FLAVOR_RULES}

🚨 КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ЯЗЫКА:
{"1. Названия ингредиентов и блюд пиши на РУССКОМ языке." if input_language == "ru" else "1. Название блюда и ингредиенты пиши на ОРИГИНАЛЬНОМ языке (как в запросе), а в скобках добавляй русский перевод. Например: Pancakes (Блинчики), Eggs (Яйца)."}
2. ВСЕ ОСТАЛЬНОЕ (шаги приготовления, советы, пояснения) пиши ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.
3. ЗАПРЕЩЕНО использовать иностранные слова в разделе "Приготовление" и "Совет шеф-повара".

⚠️ ФОРМАТИРОВАНИЕ:
- Используй ТОЛЬКО HTML теги (<b>...</b>).
- НЕ ИСПОЛЬЗУЙ Markdown (**...**).

📋 <b>ОБЯЗАТЕЛЬНЫЙ ФОРМАТ:</b>

🍽️ <b>{safe_dish_name}</b>

📦 <b>Ингредиенты:</b>
🔸 [Название{' (Перевод)' if input_language != 'ru' else ''}] - [количество]
🔸 [Название{' (Перевод)' if input_language != 'ru' else ''}] - [количество]

📊 <b>Пищевая ценность на 1 порцию:</b>
🥚 Белки: [X] г
🥑 Жиры: [X] г
🌾 Углеводы: [X] г
⚡ Энерг. ценность: [X] ккал

⏱ <b>Время:</b> [X] минут
🪦 <b>Сложность:</b> [уровень]
👥 <b>Порции:</b> [X] человека

🔪 <b>Приготовление:</b>
[ВЕСЬ текст инструкций ТОЛЬКО на русском языке - никаких иностранных слов!]

💡 <b>Совет шеф-повара:</b>
[Полезный совет ТОЛЬКО на русском языке]"""

        res = await self._send_groq_request(prompt, "Создай рецепт", task_type="freestyle")
        if self._is_refusal(res):
            return res
        return res + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
    
    async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
        """Парсит рецепт для генерации карточки"""
        prompt = """Парси следующий рецепт и верни JSON:
{
  "title": "Название блюда",
  "ingredients": ["ингредиент 1", "ингредиент 2", ...],
  "time": "время в минутах",
  "portions": "количество порций",
  "difficulty": "уровень сложности",
  "chef_tip": "совет шеф-повара"
}

Рецепт:"""
        
        try:
            res = await self._send_groq_request(
                prompt, 
                recipe_text, 
                task_type="validation",
                temperature=0.1,
                max_tokens=500
            )
            
            parsed = json.loads(self._extract_json(res))
            
            # Очистка и валидация
            if "ingredients" in parsed and isinstance(parsed["ingredients"], list):
                # Берем только первые 8 ингредиентов
                parsed["ingredients"] = [ing.strip() for ing in parsed["ingredients"][:8]]
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка парсинга рецепта: {e}")
            # Возвращаем дефолтные значения
            return {
                "title": "Вкусное блюдо",
                "ingredients": ["Ингредиенты не найдены"],
                "time": "30",
                "portions": "2",
                "difficulty": "средняя",
                "chef_tip": "Приятного аппетита!"
            }
    
    @staticmethod
    def _is_refusal(text: str) -> bool:
        """Проверяет, является ли ответ отказом"""
        refusals = ["cannot fulfill", "against my policy", "не могу выполнить", "⛔"]
        return any(ph in text.lower() for ph in refusals)

# Глобальный экземпляр
groq_service = GroqService()
