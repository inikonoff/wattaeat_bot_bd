import logging
from typing import Dict, List, Optional
from datetime import datetime
from database import db
from config import MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)

class StateManagerDB:
    def __init__(self):
        # Кеш в памяти для быстрого доступа
        self._cache = {
            'history': {},
            'products': {},
            'states': {},
            'categories': {},
            'dishes': {},
            'current_dish': {},
            'last_recipe_id': {},
            'broadcast_text': {}  # Для хранения текста broadcast
        }
        
        self.db_connected = False

    async def initialize(self):
        """Инициализация подключения к БД"""
        try:
            await db.connect()
            self.db_connected = True
            logger.info("✅ StateManagerDB инициализирован с БД")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            self.db_connected = False

    # ==================== ОСНОВНЫЕ МЕТОДЫ ====================

    async def load_user_session(self, user_id: int) -> bool:
        """Загружаем сессию пользователя из БД в кеш"""
        if not self.db_connected:
            return False
            
        try:
            session = await db.get_session(user_id)
            if session:
                self._cache['products'][user_id] = session.get('products', '')
                self._cache['states'][user_id] = session.get('state', '')
                self._cache['categories'][user_id] = session.get('categories', [])
                self._cache['dishes'][user_id] = session.get('generated_dishes', [])
                self._cache['current_dish'][user_id] = session.get('current_dish', '')
                self._cache['history'][user_id] = session.get('history', [])
                
                logger.debug(f"📥 Сессия загружена из БД для user_id={user_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка загрузки сессии из БД: {e}")
        
        return False

    async def save_session_to_db(self, user_id: int):
        """Сохраняем сессию пользователя в БД"""
        if not self.db_connected:
            return
            
        try:
            await db.create_or_update_session(
                telegram_id=user_id,
                products=self._cache['products'].get(user_id),
                state=self._cache['states'].get(user_id),
                categories=self._cache['categories'].get(user_id),
                generated_dishes=self._cache['dishes'].get(user_id),
                current_dish=self._cache['current_dish'].get(user_id),
                history=self._cache['history'].get(user_id, [])[-MAX_HISTORY_MESSAGES:]
            )
            logger.debug(f"💾 Сессия сохранена в БД для user_id={user_id}")
        except Exception as e:
            logger.error(f"Ошибка сохранения сессии в БД: {e}")

    # ==================== ИСТОРИЯ ====================

    def get_history(self, user_id: int) -> List[Dict]:
        """Получает историю сообщений пользователя"""
        return self._cache['history'].get(user_id, [])

    async def add_message(self, user_id: int, role: str, text: str):
        """Добавляет сообщение в историю"""
        if user_id not in self._cache['history']:
            self._cache['history'][user_id] = []
        
        self._cache['history'][user_id].append({
            "role": role, 
            "text": text,
            "timestamp": datetime.now().isoformat()
        })
        
        if len(self._cache['history'][user_id]) > MAX_HISTORY_MESSAGES:
            self._cache['history'][user_id] = self._cache['history'][user_id][-MAX_HISTORY_MESSAGES:]
        
        await self.save_session_to_db(user_id)

    def get_last_bot_message(self, user_id: int) -> Optional[str]:
        """Получает последнее сообщение бота из истории"""
        hist = self.get_history(user_id)
        
        # Защита от None и пустого списка
        if not hist:
            return None
        
        for msg in reversed(hist):
            if msg.get("role") == "bot":
                return msg.get("text")
        
        return None

    # ==================== ПРОДУКТЫ ====================

    def get_products(self, user_id: int) -> Optional[str]:
        """Получает продукты пользователя"""
        return self._cache['products'].get(user_id)

    async def set_products(self, user_id: int, products: str):
        """Устанавливает продукты пользователя"""
        self._cache['products'][user_id] = products
        await self.save_session_to_db(user_id)

    async def add_products(self, user_id: int, new_products: str):
        """Добавляет новые продукты к существующим"""
        current = self._cache['products'].get(user_id)
        if current:
            self._cache['products'][user_id] = f"{current}, {new_products}"
        else:
            self._cache['products'][user_id] = new_products
        
        await self.save_session_to_db(user_id)

    # ==================== СТАТУСЫ ====================

    def get_state(self, user_id: int) -> Optional[str]:
        """Получает состояние пользователя"""
        return self._cache['states'].get(user_id)

    async def set_state(self, user_id: int, state: str):
        """Устанавливает состояние пользователя"""
        self._cache['states'][user_id] = state
        await self.save_session_to_db(user_id)

    async def clear_state(self, user_id: int):
        """Очищает состояние пользователя"""
        if user_id in self._cache['states']:
            del self._cache['states'][user_id]
        await self.save_session_to_db(user_id)

    # ==================== КАТЕГОРИИ И БЛЮДА ====================

    async def set_categories(self, user_id: int, categories: List[str]):
        """Устанавливает категории для пользователя"""
        self._cache['categories'][user_id] = categories
        await self.save_session_to_db(user_id)

    def get_categories(self, user_id: int) -> List[str]:
        """Получает категории пользователя"""
        return self._cache['categories'].get(user_id, [])

    async def set_generated_dishes(self, user_id: int, dishes: List[Dict]):
        """Устанавливает сгенерированные блюда"""
        self._cache['dishes'][user_id] = dishes
        await self.save_session_to_db(user_id)

    def get_generated_dishes(self, user_id: int) -> List[Dict]:
        """Получает сгенерированные блюда"""
        return self._cache['dishes'].get(user_id, [])

    def set_dishes_list(self, user_id: int, dishes: List[Dict]):
        """Устанавливает список блюд (используется в handlers.py)"""
        self._cache['dishes'][user_id] = dishes

    def get_dishes_list(self, user_id: int) -> List[Dict]:
        """Получает список блюд (используется в handlers.py)"""
        return self._cache['dishes'].get(user_id, [])

    def get_generated_dish(self, user_id: int, index: int) -> Optional[str]:
        """Получает блюдо по индексу"""
        dishes = self.get_generated_dishes(user_id)
        if 0 <= index < len(dishes):
            return dishes[index]['name']
        return None

    async def set_current_dish(self, user_id: int, dish_name: str):
        """Устанавливает текущее блюдо"""
        self._cache['current_dish'][user_id] = dish_name
        await self.save_session_to_db(user_id)

    def get_current_dish(self, user_id: int) -> Optional[str]:
        """Получает текущее блюдо"""
        return self._cache['current_dish'].get(user_id)

    # ==================== РЕЦЕПТЫ ====================

    async def save_recipe_to_history(
        self, 
        user_id: int, 
        dish_name: str, 
        recipe_text: str,
        image_url: Optional[str] = None
    ) -> Optional[int]:
        """Сохраняем рецепт в историю БД и возвращаем ID"""
        if not self.db_connected:
            return None
            
        try:
            products = self.get_products(user_id)
            recipe_id = await db.save_recipe(
                telegram_id=user_id,
                dish_name=dish_name,
                recipe_text=recipe_text,
                products_used=products,
                image_url=image_url
            )
            
            # Сохраняем ID последнего рецепта
            self._cache['last_recipe_id'][user_id] = recipe_id
            
            # Также добавляем в историю сообщений
            await self.add_message(user_id, "bot", recipe_text)
            
            logger.info(f"📝 Рецепт сохранён в историю: {dish_name} (ID: {recipe_id})")
            return recipe_id
        except Exception as e:
            logger.error(f"Ошибка сохранения рецепта: {e}")
            return None

    def get_last_saved_recipe_id(self, user_id: int) -> Optional[int]:
        """Получить ID последнего сохранённого рецепта"""
        return self._cache['last_recipe_id'].get(user_id)

    # ==================== BROADCAST ====================

    async def set_broadcast_text(self, user_id: int, text: str):
        """Сохраняет текст для broadcast"""
        self._cache['broadcast_text'][user_id] = text

    def get_broadcast_text(self, user_id: int) -> Optional[str]:
        """Получает сохранённый текст broadcast"""
        return self._cache['broadcast_text'].get(user_id)

    async def clear_broadcast_text(self, user_id: int):
        """Очищает текст broadcast"""
        if user_id in self._cache['broadcast_text']:
            del self._cache['broadcast_text'][user_id]

    # ==================== ОЧИСТКА ====================

    async def clear_session(self, user_id: int):
        """Полная очистка сессии (кеш + БД)"""
        for cache_key in self._cache:
            if user_id in self._cache[cache_key]:
                del self._cache[cache_key][user_id]
        
        if self.db_connected:
            try:
                await db.clear_session(user_id)
                logger.info(f"🧹 Сессия очищена для user_id={user_id}")
            except Exception as e:
                logger.error(f"Ошибка очистки сессии в БД: {e}")

    async def shutdown(self):
        """Graceful shutdown - закрываем соединение с БД"""
        if self.db_connected:
            await db.close()
            self.db_connected = False
            logger.info("💤 StateManagerDB завершил работу")

# Глобальный экземпляр
state_manager = StateManagerDB()