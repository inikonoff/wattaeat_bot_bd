import os
import logging
import json
import asyncio
import re
from typing import List, Dict, Optional, Tuple
from groq import AsyncGroq
from aiogram.types import Message  # <--- ОБЯЗАТЕЛЬНО ИМПОРТИРОВАТЬ

logger = logging.getLogger(__name__)

class GroqService:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY не найден в переменных окружения")
        
        self.client = AsyncGroq(api_key=api_key)
        logger.info("✅ GroqService инициализирован")
        
        # Максимальные токены для разных типов запросов
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
            "regenerate_recipe": 2000
        }

    def _sanitize_input(self, text: str, max_length: int = 500) -> str:
        """Очищает входной текст от потенциально опасных символов"""
        if not text:
            return ""
        
        # Обрезаем длину
        text = text[:max_length]
        
        # Удаляем опасные символы для промптов
        text = text.replace('"""', "'")
        text = text.replace("'''", "'")
        text = text.replace('`', "'")
        
        # Заменяем множественные переводы строк
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()

    def _clean_html_for_telegram(self, text: str) -> str:
        """Очищает HTML для Telegram"""
        if not text:
            return ""
        
        # Заменяем HTML теги на форматирование Telegram
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
            (r'<p>', r''),
            (r'</p>', r'\n\n'),
            (r'<h[1-6]>(.*?)</h[1-6]>', r'<b>\1</b>\n'),
            (r'<ul>', r''),
            (r'</ul>', r''),
            (r'<ol>', r''),
            (r'</ol>', r''),
            (r'<li>', r'• '),
            (r'</li>', r'\n'),
        ]
        
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        # Удаляем оставшиеся HTML теги
        text = re.sub(r'<[^>]+>', '', text)
        
        # Чистим лишние пробелы
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        text = text.strip()
        
        return text

    async def _send_groq_request(self, system_prompt: str, user_text: str, 
                                task_type: str = "general", temperature: float = 0.7, 
                                max_tokens: int = None) -> str:
        """Отправляет запрос к Groq API"""
        try:
            if max_tokens is None:
                max_tokens = self.max_tokens_map.get(task_type, 1000)
            
            logger.info(f"Отправка запроса к Groq ({task_type}), токены: {max_tokens}")
            
            response = await self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # или другой доступный модель
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=0.9
            )
            
            result = response.choices[0].message.content
            logger.info(f"Успешный ответ от Groq ({len(result)} символов)")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка Groq API ({task_type}): {e}", exc_info=True)
            raise

    # --- ОСНОВНЫЕ МЕТОДЫ ---

    async def analyze_categories(self, products: str) -> List[str]:
        """Анализирует продукты и возвращает подходящие категории блюд"""
        safe_products = self._sanitize_input(products, 300)
        
        system_prompt = """Ты опытный шеф-повар и кулинарный эксперт. Твоя задача - анализировать список продуктов и определять, какие категории блюд можно из них приготовить.

Верни ТОЛЬКО список категорий в формате JSON массив строк. Никаких пояснений, только JSON.

Доступные категории: ["breakfast", "soup", "main", "salad", "snack", "dessert", "drink", "mix", "sauce"]
Верни от 1 до 4 наиболее подходящих категорий."""

        user_prompt = f"""Продукты: {safe_products}

Верни JSON массив с подходящими категориями. Примеры:
- Для "яйца, молоко, хлеб" -> ["breakfast", "snack"]
- Для "картофель, морковь, лук, мясо" -> ["main", "soup"]
- Для "фрукты, йогурт, орехи" -> ["breakfast", "dessert", "snack"]
- Для "курица, рис, овощи" -> ["main", "mix"]"""

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="analyze_categories",
                temperature=0.3,
                max_tokens=300
            )
            
            # Извлекаем JSON из ответа
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                categories = json.loads(json_match.group())
                # Фильтруем только допустимые категории
                valid_categories = ["breakfast", "soup", "main", "salad", "snack", "dessert", "drink", "mix", "sauce"]
                return [cat for cat in categories if cat in valid_categories][:4]
            else:
                # Fallback: определяем по ключевым словам
                return self._fallback_categories(safe_products)
                
        except Exception as e:
            logger.error(f"Ошибка анализа категорий: {e}")
            return ["main", "snack"]  # Категории по умолчанию

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

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        """Генерирует список блюд для выбранной категории"""
        safe_products = self._sanitize_input(products, 300)
        
        category_names = {
            "breakfast": "завтраки",
            "soup": "супы",
            "main": "вторые блюда",
            "salad": "салаты",
            "snack": "закуски",
            "dessert": "десерты",
            "drink": "напитки",
            "mix": "комплексные обеды",
            "sauce": "соусы"
        }
        
        category_ru = category_names.get(category, category)
        
        system_prompt = f"""Ты опытный шеф-повар. Твоя задача - предложить конкретные блюда из категории "{category_ru}" на основе предоставленных продуктов.

Верни ТОЛЬКО JSON массив объектов, каждый объект имеет структуру: {{"name": "Название блюда", "description": "Краткое описание 10-15 слов"}}
Верни 3-5 вариантов блюд."""

        user_prompt = f"""Категория: {category_ru}
Продукты: {safe_products}

Придумай блюда, которые можно приготовить из этих продуктов. Названия должны быть конкретными и аппетитными.
Пример для категории "main" и продуктов "курица, рис, овощи":
[
  {{"name": "Курица с рисом по-восточному", "description": "Нежная курица с ароматным рисом, тушеная с овощами и специями"}},
  {{"name": "Овощное рагу с курицей", "description": "Сочная курица с сезонными овощами в томатном соусе"}},
  {{"name": "Жареный рис с курицей и овощами", "description": "Классический азиатский рецепт с соевой заправкой"}}
]"""

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="generate_dishes",
                temperature=0.7
            )
            
            # Извлекаем JSON
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                dishes = json.loads(json_match.group())
                # Ограничиваем 5 блюдами и проверяем структуру
                valid_dishes = []
                for dish in dishes[:5]:
                    if isinstance(dish, dict) and 'name' in dish:
                        if 'description' not in dish:
                            dish['description'] = "Вкусное блюдо из доступных ингредиентов"
                        valid_dishes.append(dish)
                return valid_dishes
            else:
                # Fallback
                return self._fallback_dishes(category, safe_products)
                
        except Exception as e:
            logger.error(f"Ошибка генерации списка блюд: {e}")
            return self._fallback_dishes(category, safe_products)

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

    async def generate_recipe(self, dish_name: str, products: str) -> str:
        """Генерирует рецепт блюда"""
        safe_dish = self._sanitize_input(dish_name, 100)
        safe_products = self._sanitize_input(products, 300)
        
        system_prompt = """Ты опытный шеф-повар с многолетним стажем. Твоя задача - создавать подробные, понятные и практичные рецепты.

Требования к рецепту:
1. НАЧНИ С КРАСИВОГО НАЗВАНИЯ БЛЮДА В ТЕГАХ <b>
2. Всегда включай разделы: 📋 Ингредиенты, 👨‍🍳 Приготовление, 💡 Советы
3. Используй доступные продукты, но можешь предложить дополнительные (помечай *)
4. Указывай точные количества и время приготовления
5. Будь дружелюбным и воодушевляющим
6. Используй эмодзи для наглядности
7. Форматируй для Telegram HTML (используй <b>, <i>, переносы строк)

Не упоминай, что ты ИИ. Пиши как настоящий шеф."""

        user_prompt = f"""Создай рецепт для блюда: "{safe_dish}"

Доступные продукты: {safe_products}

Создай подробный пошаговый рецепт. Если нужны дополнительные ингредиенты - помечай их *.
Сделай рецепт понятным даже для начинающих поваров."""

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="generate_recipe",
                temperature=0.6,
                max_tokens=1500
            )
            
            # Чистим HTML для Telegram
            cleaned_response = self._clean_html_for_telegram(response)
            
            # Добавляем заголовок если его нет
            if not cleaned_response.startswith('<b>'):
                cleaned_response = f'<b>🍽️ {safe_dish}</b>\n\n{cleaned_response}'
            
            return cleaned_response
            
        except Exception as e:
            logger.error(f"Ошибка генерации рецепта: {e}")
            return self._fallback_recipe(safe_dish, safe_products)

    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        """Генерирует рецепт без привязки к конкретным продуктам"""
        safe_dish = self._sanitize_input(dish_name, 100)
        
        system_prompt = """Ты знаменитый шеф-повар мирового уровня. Твоя задача - создавать классические и авторские рецепты блюд.

Требования:
1. НАЧНИ С КРАСИВОГО НАЗВАНИЯ В <b>ТЕГАХ</b>
2. Включи: 📋 Ингредиенты (с количествами), 👨‍🍳 Пошаговое приготовление, ⏰ Время готовки, 💡 Профессиональные советы
3. Будь точным в пропорциях и времени
4. Объясняй тонкости и секреты приготовления
5. Используй эмодзи и Telegram HTML форматирование
6. Пиши вдохновляюще и профессионально"""

        user_prompt = f"""Создай подробный рецепт для блюда: "{safe_dish}"

Сделай его:
- Классическим или с авторским twist
- С точными количествами ингредиентов
- С четкими шагами приготовления
- С полезными советами от шефа
- С указанием сложности и времени

Если это известное блюдо - объясни его особенности. Если менее известное - расскажи о нем."""

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="freestyle_recipe",
                temperature=0.7,
                max_tokens=1800
            )
            
            cleaned_response = self._clean_html_for_telegram(response)
            
            if not cleaned_response.startswith('<b>'):
                cleaned_response = f'<b>👨‍🍳 {safe_dish}</b>\n\n{cleaned_response}'
            
            return cleaned_response
            
        except Exception as e:
            logger.error(f"Ошибка генерации свободного рецепта: {e}")
            return f"<b>🍽️ {safe_dish}</b>\n\nНе удалось создать рецепт. Попробуйте другой запрос."

    # --- ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ---

    async def generate_comparison(self, query: str) -> str:
        """Сравнивает продукты или блюда"""
        safe_query = self._sanitize_input(query, 200)
        
        system_prompt = """Ты эксперт по питанию и кулинарии. Сравнивай продукты или блюда объективно и информативно.

Формат ответа:
1. <b>Сравнительный анализ</b>
2. 📊 По категориям (польза, вкус, сложность приготовления, стоимость)
3. 🏆 Выводы и рекомендации
4. 💡 Практические советы

Будь нейтральным, приводи факты, используй эмодзи."""

        user_prompt = f"Сравни: {safe_query}\n\nДай подробный анализ по разным параметрам."

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="comparison",
                temperature=0.5
            )
            return self._clean_html_for_telegram(response)
        except Exception as e:
            logger.error(f"Ошибка сравнения: {e}")
            return f"Не удалось провести сравнение для: {safe_query}"

    async def generate_cooking_advice(self, query: str) -> str:
        """Дает советы по готовке"""
        safe_query = self._sanitize_input(query, 200)
        
        system_prompt = """Ты опытный кулинарный наставник. Дай практические, проверенные советы.

Структура:
1. <b>Ответ на вопрос</b>
2. 📝 Основные принципы
3. 👨‍🍳 Пошаговые рекомендации
4. ⚠️ Частые ошибки и как их избежать
5. 💎 Лайфхаки и секреты

Будь конкретным, используй примеры, объясняй почему."""

        user_prompt = f"Кулинарный вопрос: {safe_query}\n\nДай развернутый совет с практическими рекомендациями."

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="cooking_advice",
                temperature=0.6
            )
            return self._clean_html_for_telegram(response)
        except Exception as e:
            logger.error(f"Ошибка совета: {e}")
            return f"Не удалось найти совет для: {safe_query}"

    async def generate_nutrition_info(self, query: str) -> str:
        """Информация о питательной ценности"""
        safe_query = self._sanitize_input(query, 200)
        
        system_prompt = """Ты диетолог и эксперт по питанию. Дай научно обоснованную информацию.

Структура:
1. <b>Пищевая ценность</b>
2. 🍎 Состав (БЖУ, витамины, минералы)
3. 👍 Польза для здоровья
4. ⚠️ Возможные ограничения
5. 🍽️ Как лучше употреблять
6. 🔄 Альтернативы и варианты

Используй точные цифры, ссылайся на принципы здорового питания."""

        user_prompt = f"Запрос о питании: {safe_query}\n\nДай подробную информацию о пищевой ценности и пользе."

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="nutrition",
                temperature=0.4
            )
            return self._clean_html_for_telegram(response)
        except Exception as e:
            logger.error(f"Ошибка информации о питании: {e}")
            return f"Не удалось найти информацию для: {safe_query}"

    async def transcribe_voice(self, audio_data: bytes) -> Optional[str]:
        """Транскрибирует голосовое сообщение"""
        try:
            # Временная заглушка - в реальности нужна интеграция с ASR API
            # Например, через OpenAI Whisper или аналоги
            logger.info("Транскрипция голоса (заглушка)")
            return None
            
        except Exception as e:
            logger.error(f"Ошибка транскрипции: {e}")
            return None

    async def validate_recipe_consistency(self, products: str, recipe: str) -> Tuple[bool, List[str]]:
        """Проверяет, соответствует ли рецепт доступным продуктам"""
        safe_products = self._sanitize_input(products, 200)
        
        system_prompt = """Ты проверяешь рецепты на соответствие списку продуктов. 
        Определи, каких ингредиентов не хватает в рецепте по сравнению со списком продуктов.
        Верни ТОЛЬКО JSON: {"missing": ["ингредиент1", "ингредиент2"], "is_valid": true/false}
        is_valid = true, если недостающие ингредиенты не критичны или их менее 3."""
        
        user_prompt = f"""Продукты: {safe_products}

Рецепт: {recipe[:500]}

Каких ингредиентов не хватает? Учти, что специи, соль, сахар, масло могут не указываться."""

        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="validate_recipe",
                temperature=0.3,
                max_tokens=500
            )
            
            # Извлекаем JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                missing = result.get("missing", [])
                is_valid = result.get("is_valid", len(missing) < 3)
                return is_valid, missing
            else:
                return True, []  # Если не смогли проверить, считаем валидным
                
        except Exception as e:
            logger.error(f"Ошибка валидации рецепта: {e}")
            return True, []  # При ошибке считаем валидным

    async def regenerate_recipe_without_missing(self, dish_name: str, products: str, 
                                               original_recipe: str, missing_ingredients: List[str]) -> str:
        """Перегенерирует рецепт без недостающих ингредиентов"""
        safe_dish = self._sanitize_input(dish_name, 100)
        safe_products = self._sanitize_input(products, 300)
        missing_str = ", ".join(missing_ingredients[:5])
        
        system_prompt = """Ты адаптируешь рецепт под доступные продукты. Убери недостающие ингредиенты или замени их доступными аналогами.
        
        Требования:
        1. Сохрани структуру и суть блюда
        2. Замени или убери недостающие ингредиенты
        3. Предложи варианты замены
        4. Сделай рецепт реалистичным с имеющимися продуктами"""
        
        user_prompt = f"""Блюдо: {safe_dish}
        Доступные продукты: {safe_products}
        Недостающие в оригинальном рецепте: {missing_str}
        
        Оригинальный рецепт: {original_recipe[:300]}...
        
        Создай адаптированный вариант рецепта без недостающих ингредиентов."""
        
        try:
            response = await self._send_groq_request(
                system_prompt=system_prompt,
                user_text=user_prompt,
                task_type="regenerate_recipe",
                temperature=0.5,
                max_tokens=1500
            )
            
            cleaned = self._clean_html_for_telegram(response)
            if not cleaned.startswith('<b>'):
                cleaned = f'<b>🍽️ {safe_dish} (адаптированный)</b>\n\n{cleaned}'
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Ошибка перегенерации рецепта: {e}")
            return original_recipe  # Возвращаем оригинал при ошибке

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

# Глобальный экземпляр
groq_service = GroqService()
