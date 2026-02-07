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
    
    # ==================== КУЛИНАРНАЯ ТРИАДА И ПРАВИЛА СОЧЕТАЕМОСТИ ====================
    
    # Триада анализа блюда
    CULINARY_TRIAD = """🎯 КУЛИНАРНАЯ ТРИАДА (обязательный анализ в "СОВЕТЕ ШЕФА"):
1. ВКУС: баланс солёного, сладкого, кислого, острого, жирного.
2. АРОМАТ: гармония запахов, соответствие ингредиентов.
3. ТЕКСТУРА: контраст мягкого/хрустящего, сочного/сухого."""
    
    # Правила сочетаемости
    FLAVOR_RULES = """❗️ ПРАВИЛА СОЧЕТАЕМОСТИ:
🎭 КОНТРАСТЫ: Жирное + Кислое, Сладкое + Солёное, Мягкое + Хрустящее.
✨ УСИЛЕНИЕ: Помидор + Базилик, Рыба + Укроп + Лимон, Тыква + Корица, Картофель + Лук + Укроп
👑 ОДИН ГЛАВНЫЙ ИНГРЕДИЕНТ: В каждом блюде один "король" (основной продукт).
❌ ТАБУ:
- Рыба + Молочные продукты (в горячем виде)
- Два сильных мяса в одной композиции
- Рыба + Мясо или Сало
- Молочное + солёные/маринованные продукты (огурцы, селёдка, цитрусы)
- Сладкие фрукты + чеснок/лук/острое"""
    
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
    
    # Критические правила валидации рецептов
    RECIPE_VALIDATION_RULES = """
🚫 КРИТИЧЕСКИЕ ПРАВИЛА ГЕНЕРАЦИИ РЕЦЕПТОВ:

1. ИНГРЕДИЕНТЫ:
   - Используй ТОЛЬКО ингредиенты из списка продуктов пользователя
   - НЕ добавляй муку, тесто, яйца, молоко, сливки, кефир — если их нет в списке
   - Можно использовать БАЗУ: соль, сахар, вода, растительное масло, специи (перец, паприка)

2. ТЕХНОЛОГИИ:
   - Если нет муки/теста → НЕ предлагай выпечку
   - Если нет духовки → предлагай варку, жарку на сковороде, холодные блюда
   - Используй простые инструменты: нож, ложка, вилка, сковорода, кастрюля

3. АЛЬТЕРНАТИВЫ:
   - Нет теста? → Сделай салат, холодную закуску, десерт без выпечки
   - Нет духовки? → Жарь на сковороде, вари, туши
   - Нет специальных ингредиентов? → Используй аналоги из списка

4. ЧЕСТНОСТЬ:
   - Если блюдо невозможно приготовить с данными продуктами → скажи об этом честно
   - Предложи альтернативное блюдо с теми же продуктами
   - Не выдумывай недостающие ингредиенты

5. ЛАКОНИЧНОСТЬ И ЧИСТОТА СОСТАВА:
   - Используй только те ингредиенты из списка, которые действительно подходят блюду
   - Не пытайся использовать все продукты сразу, если это портит вкус
   - Не упоминай оставшиеся неиспользованные продукты в рецепте
"""
    
    # СТРОГИЕ ЯЗЫКОВЫЕ ПРАВИЛА
    LANGUAGE_RULES = """
📋 СТРОГИЕ ЯЗЫКОВЫЕ ПРАВИЛА:

1. Если пользователь ввёл продукты на иностранном языке:
   - В рецепте указывай иностранные названия с переводом в скобках
   - Пример: "Kartoffeln (картофель)", "Pollo (курица)"

2. Для списка блюд:
   - `name`: название на языке оригинала ингредиентов
   - `desc`: описание строго на русском языке

3. Для рецепта:
   - Название блюда: всегда оригинальное имя (например "Pasta Carbonara")
   - Шаги приготовления и совет шефа: строго на русском языке
   - Ингредиенты: на языке оригинала, перевод в скобках при необходимости
"""
    
    # ПРАВИЛА ЕДИНИЦ ИЗМЕРЕНИЯ
    MEASUREMENT_RULES = """
📏 ПРАВИЛА ЕДИНИЦ ИЗМЕРЕНИЯ:
- Большинство ингредиентов: в граммах (г)
- Масла/жидкости: столовые (ст. л.) или чайные (ч. л.) ложки
- Чеснок: зубчики (зубчика)
- Овощи (морковь, свекла, лук и т.д.): штуки (шт.)
- Формат строки: "- [ингредиент] — [количество]"
"""
    
    # ФИНАЛЬНЫЙ СИСТЕМНЫЙ ПРОМПТ
    SYSTEM_PROMPT = f"""Ты — профессиональный шеф-повар с экспертизой в кулинарной триаде (вкус, аромат, текстура), сочетаемости продуктов и международных кухнях.

ТВОИ ОСНОВНЫЕ ПРИНЦИПЫ:
1. БЕЗОПАСНОСТЬ: готовить только съедобные блюда, отсеивать опасные/неуместные запросы
2. РЕАЛИЗМ: использовать только доступные ингредиенты и инструменты
3. ВКУС: приоритет вкусовой гармонии над использованием всех продуктов
4. ЧЕСТНОСТЬ: если блюдо невозможно — сказать прямо и предложить альтернативу
5. ЛОКАЛИЗАЦИЯ: уважать язык оригинала, но адаптировать для пользователя

ТЫ СТРОГО СОБЛЮДАЕШЬ ВСЕ КУЛИНАРНЫЕ ПРАВИЛА ВО ВСЕХ ОТВЕТАХ.

{FLAMOR_RULES}
{CULINARY_TRIAD}
{LANGUAGE_RULES}
{RECIPE_VALIDATION_RULES}
"""

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
    
    # ==================== ВАЛИДАЦИЯ РЕЦЕПТОВ ====================
    
    async def validate_recipe_consistency(self, ingredients_text: str, recipe_text: str) -> tuple[bool, list]:
        """
        Проверяет консистентность рецепта
        Returns: (is_valid, list_of_issues)
        """
        issues = []
        
        try:
            # Извлекаем список ингредиентов из текста рецепта
            recipe_lower = recipe_text.lower()
            
            # Критические проверки
            critical_checks = [
                {
                    'keyword': 'тесто',
                    'required': ['мука', 'тесто', 'лаваш', 'блин', 'корж', 'тортилья'],
                    'message': 'Рецепт требует теста, но в ингредиентах нет муки или готового теста'
                },
                {
                    'keyword': 'мука',
                    'required': ['мука'],
                    'message': 'Рецепт требует муки, но её нет в ингредиентах'
                },
                {
                    'keyword': 'запекать',
                    'required': ['духовк', 'печь', 'запекать'],
                    'message': 'Рецепт требует запекания, но это нормально (духовка есть на кухне)'
                },
                {
                    'keyword': 'яйц',
                    'required': ['яйц', 'яйко'],
                    'message': 'Рецепт требует яиц, но их нет в ингредиентах'
                },
                {
                    'keyword': 'молок',
                    'required': ['молок', 'сливк', 'кефир'],
                    'message': 'Рецепт требует молока/сливок, но их нет в ингредиентах'
                }
            ]
            
            ingredients_lower = ingredients_text.lower()
            
            for check in critical_checks:
                if check['keyword'] in recipe_lower:
                    # Проверяем, есть ли хоть один из требуемых ингредиентов
                    has_required = any(req in ingredients_lower for req in check['required'])
                    
                    # Для теста/муки это критическая ошибка
                    if check['keyword'] in ['тесто', 'мука'] and not has_required:
                        issues.append(f"❌ {check['message']}")
                    # Для остальных - предупреждение
                    elif not has_required:
                        issues.append(f"⚠️ {check['message']}")
            
            # Проверяем странные комбинации
            if 'суп' in recipe_lower and 'духовк' in recipe_lower:
                issues.append("⚠️ Суп обычно не запекают в духовке")
            
            if 'салат' in recipe_lower and 'запекать' in recipe_lower:
                issues.append("⚠️ Салаты обычно не запекают")
            
            return len([i for i in issues if i.startswith('❌')]) == 0, issues
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return True, []  # В случае ошибки пропускаем валидацию
    
    async def regenerate_recipe_without_missing(self, dish_name: str, products: str, original_recipe: str, issues: list) -> str:
        """Перегенерирует рецепт без недостающих ингредиентов"""
        safe_dish = self._sanitize_input(dish_name, max_length=150)
        safe_prods = self._sanitize_input(products, max_length=600)
        
        # Определяем язык продуктов
        language, foreign_words = self.detect_language_from_products(safe_prods)
        language_context = self.create_language_context(language, foreign_words)
        
        # Формируем инструкции на основе найденных проблем
        constraints = ""
        if any('тесто' in issue.lower() or 'мука' in issue.lower() for issue in issues):
            constraints = "НЕ используй тесто, муку, выпечку. Сделай холодное блюдо, салат или закуску без теста."
        
        prompt = f"""ПЕРЕГЕНЕРАЦИЯ РЕЦЕПТА: {safe_dish}

🚫 ПРОБЛЕМЫ В ПРЕДЫДУЩЕМ РЕЦЕПТЕ:
{chr(10).join(issues)}

🎯 НОВЫЕ ТРЕБОВАНИЯ:
1. Используй ТОЛЬКО эти ингредиенты: {safe_prods}
2. {constraints}
3. Можно использовать БАЗУ: соль, сахар, вода, растительное масло, специи
4. НЕ добавляй ингредиенты, которых нет в списке
5. Сделай рецепт реалистичным и выполнимым

🛒 ИСХОДНЫЕ ПРОДУКТЫ: {safe_prods}
{language_context}

📋 ФОРМАТ РЕЦЕПТА (Telegram HTML):
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

👨‍🍳 <b>Приятного аппетита!</b>
"""
        
        try:
            raw_html = await self._send_groq_request(prompt, "Regenerate recipe without missing ingredients", 
                                                   task_type="regeneration", temperature=0.4, max_tokens=2500)
            
            # Проверяем новый рецепт
            new_recipe = self._clean_html_for_telegram(raw_html) + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
            is_valid, new_issues = await self.validate_recipe_consistency(safe_prods, new_recipe)
            
            if not is_valid:
                logger.warning(f"Regenerated recipe still has issues: {new_issues}")
                # Если проблемы остались, добавляем примечание
                new_recipe += f"\n\n⚠️ <i>Примечание: {new_issues[0] if new_issues else 'Рецепт может требовать дополнительных ингредиентов'}</i>"
            
            return new_recipe
            
        except Exception as e:
            logger.error(f"Regeneration error: {e}")
            # Возвращаем оригинальный рецепт с пометкой
            return original_recipe + "\n\n⚠️ <i>Примечание: рецепт требует теста/муки, которых нет в ваших продуктах. Рассмотрите вариант холодного десерта.</i>"
    
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
{self.RECIPE_VALIDATION_RULES}

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
        """Генерация полного рецепта с валидацией"""
        safe_dish = self._sanitize_input(dish_name, max_length=150)
        safe_prods = self._sanitize_input(products, max_length=600)
        
        # Определяем язык продуктов
        language, foreign_words = self.detect_language_from_products(safe_prods)
        language_context = self.create_language_context(language, foreign_words)
        
        is_mix = "полный обед" in safe_dish.lower() or "комплекс" in safe_dish.lower()
        instruction = "🍱 ПОЛНЫЙ ОБЕД ИЗ 4 БЛЮД." if is_mix else "Напиши рецепт одного блюда."
        
        # Обновленный промпт с интегрированными правилами
        prompt = f"""{self.SYSTEM_PROMPT}

{language_context}

📋 ЗАДАНИЕ: Напиши рецепт: "{safe_dish}"

🛒 ПРОДУКТЫ (используй ТОЛЬКО эти): {safe_prods}
📦 БАЗА (можно использовать БЕЗ ограничений): соль, сахар, вода, растительное масло, специи (перец, паприка)

{instruction}

{self.MEASUREMENT_RULES}

🎯 КРИТИЧЕСКИЕ ТРЕБОВАНИЯ:
1. НЕ добавляй муку, тесто, яйца, молоко - если их нет в продуктах
2. Если в продуктах нет муки - делай ХОЛОДНОЕ блюдо без выпечки
3. Используй ТОЛЬКО простые кухонные инструменты (нож, ложка, сковорода, кастрюля)
4. Будь честен - если блюдо невозможно, предложи альтернативу

📋 СТРОГИЙ ФОРМАТ (Telegram HTML):
<b>{safe_dish}</b>

📦 <b>Ингредиенты:</b>
🔸 [Название] — [количество] (ТОЛЬКО из списка продуктов)

📊 <b>Пищевая ценность на 1 порцию:</b>
🥚 Белки: X г
🥑 Жиры: X г
🌾 Углеводы: X г
⚡ Энерг. ценность: X ккал

⏱ <b>Время:</b> X мин
🪦 <b>Сложность:</b> [низкая/средняя/высокая]
👥 <b>Порции:</b> X

👨‍🍳 <b>Приготовление:</b>
1. [шаг]
2. [шаг]

💡 <b>СОВЕТ ШЕФ-ПОВАРА:</b>
Проанализируй полученное блюдо на баланс вкусов (Жирное, Кислое, Соленое, Сладкое, Острое) и текстур (Мягкое/Хрустящее). Напиши короткий совет: чего не хватает для идеала в контексте кулинарной триады? Порекомендуй ТОЛЬКО ОДИН ингредиент!

Пример: "Блюдо вышло жирным и мягким. Добавьте для баланса маринованный лук (кислота/хруст) или подайте с долькой лимона."
"""
        
        raw_html = await self._send_groq_request(prompt, "Write recipe", task_type="recipe", temperature=0.4, max_tokens=3000)
        recipe = self._clean_html_for_telegram(raw_html) + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
        
        # ВАЛИДАЦИЯ РЕЦЕПТА
        is_valid, issues = await self.validate_recipe_consistency(safe_prods, recipe)
        
        if not is_valid:
            logger.warning(f"Recipe validation failed: {issues}")
            # Пытаемся перегенерировать рецепт
            recipe = await self.regenerate_recipe_without_missing(safe_dish, safe_prods, recipe, issues)
        
        return recipe
    
    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        """Генерация рецепта без продуктов (креативный режим)"""
        safe_dish = self._sanitize_input(dish_name, max_length=100)
        
        # Нормализуем название блюда (именительный падеж)
        normalized_dish = self._normalize_dish_name(safe_dish)
        
        prompt = f"""{self.SYSTEM_PROMPT}

📋 ЗАДАНИЕ: Ты креативный шеф-повар. Создай рецепт: "{normalized_dish}"

{self.MEASUREMENT_RULES}

🎯 ТРЕБОВАНИЯ:
- Будь реалистичен в выборе ингредиентов
- Не предлагай редкие или дорогие компоненты
- Используй стандартные кухонные инструменты

📋 ФОРМАТ РЕЦЕПТА (Telegram HTML):
{normalized_dish}

📦 <b>Ингредиенты:</b>
🔸 [Название] — [количество]

📊 <b>Пищевая ценность на 1 порцию:</b>
🥚 Белки: X г
🥑 Жиры: X г
🌾 Углеводы: X г
⚡ Энерг. ценность: X ккал

⏱ <b>Время:</b> X мин
🪦 <b>Сложность:</b> [низкая/средняя/высокая]
👥 <b>Порции:</b> X

👨‍🍳 <b>Приготовление:</b>
1. [шаг]
2. [шаг]

💡 <b>СОВЕТ ШЕФ-ПОВАРА:</b>
Проанализируй полученное блюдо на баланс вкусов (Жирное, Кислое, Соленое, Сладкое, Острое) и текстур (Мягкое/Хрустящее). Напиши короткий совет: чего не хватает для идеала в контексте кулинарной триады? Порекомендуй ТОЛЬКО ОДИН ингредиент!

Пример: "Блюдо вышло жирным и мягким. Добавьте для баланса маринованный лук (кислота/хруст) или подайте с долькой лимона."
"""
        
        raw_html = await self._send_groq_request(prompt, "Create recipe", task_type="freestyle", temperature=0.6, max_tokens=2000)
        recipe = self._clean_html_for_telegram(raw_html) + "\n\n👨‍🍳 <b>Приятного аппетита!</b>"
        
        # Для фристайла тоже делаем базовую валидацию
        is_valid, issues = await self.validate_recipe_consistency("", recipe)
        
        if not is_valid and any('тесто' in issue.lower() or 'мука' in issue.lower() for issue in issues):
            # Добавляем примечание о недостающих ингредиентах
            recipe += "\n\n⚠️ <i>Для этого рецепта могут потребоваться дополнительные ингредиенты (мука, тесто и т.д.)</i>"
        
        return recipe
    
    def _normalize_dish_name(self, dish_name: str) -> str:
        """Нормализует название блюда (упрощенная версия)"""
        # Удаляем кавычки, если они только в начале и конце
        dish_name = dish_name.strip().strip('"\'')
        
        # Простая нормализация: первая буква заглавная
        if dish_name and dish_name[0].islower():
            dish_name = dish_name
