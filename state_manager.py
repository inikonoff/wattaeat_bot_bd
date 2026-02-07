import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from database import db
from config import MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)

class StateManagerDB:
    def __init__(self):
        self._cache = {
            'products': {},
            'states': {},
            'categories': {},
            'dishes': {},
            'current_dish': {},
            'history': {},
            'last_recipe_id': {},
            'last_access': {}  # NEW: для очистки старых сессий
        }
        self.db_connected = False
        self.MAX_CACHE_AGE = 3600  # 1 час

    async def initialize(self):
        try:
            await db.connect()
            self.db_connected = True
            logger.info("✅ StateManagerDB инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")

    # --- LAZY LOADING HELPER ---
    async def _ensure_cache(self, user_id: int):
        """Если кеш пуст, пытаемся загрузить из БД"""
        # Обновляем время доступа
        self._cache['last_access'][user_id] = datetime.now()
        
        # Если в кеше уже что-то есть (даже пустая строка), считаем что загружено
        if user_id in self._cache['products']:
            return

        if not self.db_connected:
            logger.warning(f"БД не подключена для пользователя {user_id}")
            # Инициализируем пустыми значениями
            self._initialize_empty_cache(user_id)
            return

        logger.debug(f"🔄 Восстановление сессии из БД для {user_id}")
        try:
            session = await db.get_session(user_id)
            if session:
                self._cache['products'][user_id] = session.get('products') or ''
                self._cache['states'][user_id] = session.get('state') or ''
                self._cache['categories'][user_id] = session.get('categories') or []
                self._cache['dishes'][user_id] = session.get('generated_dishes') or []
                self._cache['current_dish'][user_id] = session.get('current_dish') or ''
                self._cache['history'][user_id] = session.get('history') or []
            else:
                self._initialize_empty_cache(user_id)
        except Exception as e:
            logger.error(f"Ошибка загрузки сессии для {user_id}: {e}")
            self._initialize_empty_cache(user_id)

    def _initialize_empty_cache(self, user_id: int):
        """Инициализирует пустые значения в кэше"""
        self._cache['products'][user_id] = ''
        self._cache['states'][user_id] = ''
        self._cache['categories'][user_id] = []
        self._cache['dishes'][user_id] = []
        self._cache['current_dish'][user_id] = ''
        self._cache['history'][user_id] = []

    async def _clean_old_cache(self):
        """Очищает старые записи из кэша"""
        now = datetime.now()
        for key in ['products', 'states', 'categories', 'dishes', 'current_dish', 'history', 'last_recipe_id']:
            for user_id in list(self._cache[key].keys()):
                last_access = self._cache['last_access'].get(user_id)
                if last_access and (now - last_access).seconds > self.MAX_CACHE_AGE:
                    del self._cache[key][user_id]
                    if user_id in self._cache['last_access']:
                        del self._cache['last_access'][user_id]

    async def save_session_to_db(self, user_id: int):
        if not self.db_connected: 
            logger.warning(f"БД не подключена, пропускаем сохранение для {user_id}")
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
        except Exception as e:
            logger.error(f"DB Save error for user {user_id}: {e}")

    # ==================== PUBLIC METHODS ====================

    async def get_products(self, user_id: int) -> Optional[str]:
        try:
            await self._ensure_cache(user_id)
            return self._cache['products'].get(user_id)
        except Exception as e:
            logger.error(f"Error getting products for {user_id}: {e}")
            return None

    async def set_products(self, user_id: int, products: str):
        try:
            await self._ensure_cache(user_id)
            self._cache['products'][user_id] = products
            await self.save_session_to_db(user_id)
        except Exception as e:
            logger.error(f"Error setting products for {user_id}: {e}")

    async def add_products(self, user_id: int, new_products: str):
        try:
            await self._ensure_cache(user_id)
            current = self._cache['products'].get(user_id)
            if current:
                self._cache['products'][user_id] = f"{current}, {new_products}"
            else:
                self._cache['products'][user_id] = new_products
            await self.save_session_to_db(user_id)
        except Exception as e:
            logger.error(f"Error adding products for {user_id}: {e}")

    async def get_state(self, user_id: int) -> Optional[str]:
        try:
            await self._ensure_cache(user_id)
            return self._cache['states'].get(user_id)
        except Exception as e:
            logger.error(f"Error getting state for {user_id}: {e}")
            return None

    async def set_state(self, user_id: int, state: str):
        try:
            await self._ensure_cache(user_id)
            self._cache['states'][user_id] = state
            await self.save_session_to_db(user_id)
        except Exception as e:
            logger.error(f"Error setting state for {user_id}: {e}")

    async def get_categories(self, user_id: int) -> List[Dict]:
        try:
            await self._ensure_cache(user_id)
            return self._cache['categories'].get(user_id, [])
        except Exception as e:
            logger.error(f"Error getting categories for {user_id}: {e}")
            return []

    async def set_categories(self, user_id: int, categories: List[Dict]):
        try:
            await self._ensure_cache(user_id)
            self._cache['categories'][user_id] = categories
            await self.save_session_to_db(user_id)
        except Exception as e:
            logger.error(f"Error setting categories for {user_id}: {e}")

    async def get_category(self, user_id: int) -> Optional[str]:
        """Получает текущую выбранную категорию"""
        try:
            await self._ensure_cache(user_id)
            # Можно хранить отдельно или извлекать из какого-то контекста
            # В текущей реализации нет отдельного поля для категории
            return None
        except Exception as e:
            logger.error(f"Error getting category for {user_id}: {e}")
            return None

    async def set_category(self, user_id: int, category: str):
        """Устанавливает текущую категорию"""
        try:
            await self._ensure_cache(user_id)
            # В текущей реализации нет отдельного поля для категории
            # Можно добавить self._cache['current_category'][user_id] = category
            pass
        except Exception as e:
            logger.error(f"Error setting category for {user_id}: {e}")

    async def get_dishes(self, user_id: int) -> List[Dict]:
        try:
            await self._ensure_cache(user_id)
            return self._cache['dishes'].get(user_id, [])
        except Exception as e:
            logger.error(f"Error getting dishes for {user_id}: {e}")
            return []

    async def set_dishes(self, user_id: int, dishes: List[Dict]):
        try:
            await self._ensure_cache(user_id)
            self._cache['dishes'][user_id] = dishes
            await self.save_session_to_db(user_id)
        except Exception as e:
            logger.error(f"Error setting dishes for {user_id}: {e}")

    async def get_current_dish(self, user_id: int) -> Optional[str]:
        try:
            await self._ensure_cache(user_id)
            return self._cache['current_dish'].get(user_id)
        except Exception as e:
            logger.error(f"Error getting current dish for {user_id}: {e}")
            return None

    async def set_current_dish(self, user_id: int, dish_name: str):
        try:
            await self._ensure_cache(user_id)
            self._cache['current_dish'][user_id] = dish_name
            await self.save_session_to_db(user_id)
        except Exception as e:
            logger.error(f"Error setting current dish for {user_id}: {e}")

    async def get_last_bot_message(self, user_id: int) -> Optional[str]:
        try:
            await self._ensure_cache(user_id)
            hist = self._cache['history'].get(user_id, [])
            for msg in reversed(hist):
                if msg.get("role") == "bot":
                    return msg.get("text")
            return None
        except Exception as e:
            logger.error(f"Error getting last bot message for {user_id}: {e}")
            return None

    async def save_recipe_to_history(self, user_id: int, dish_name: str, recipe_text: str, image_url: Optional[str] = None) -> Optional[int]:
        """Сохраняет рецепт в историю и возвращает ID рецепта"""
        if not self.db_connected: 
            logger.warning(f"БД не подключена, пропускаем сохранение рецепта для {user_id}")
            return None
        
        try:
            # Добавляем в историю сообщений
            await self._ensure_cache(user_id)
            if user_id not in self._cache['history']: 
                self._cache['history'][user_id] = []
            
            self._cache['history'][user_id].append({
                "role": "bot", 
                "text": recipe_text, 
                "timestamp": datetime.now().isoformat(),
                "dish_name": dish_name
            })
            
            # Сохраняем в БД
            products = await self.get_products(user_id)
            recipe_data = await db.save_recipe(user_id, dish_name, recipe_text, products, image_url)
            
            if recipe_data and 'id' in recipe_data:
                recipe_id = recipe_data['id']
                self._cache['last_recipe_id'][user_id] = recipe_id
                await self.save_session_to_db(user_id)
                logger.info(f"Рецепт {recipe_id} сохранен для пользователя {user_id}")
                return recipe_id
            
            logger.error(f"Не удалось получить ID рецепта после сохранения для {user_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error saving recipe to history for {user_id}: {e}", exc_info=True)
            return None

    async def get_last_saved_recipe_id(self, user_id: int) -> Optional[int]:
        """Получает ID последнего сохраненного рецепта"""
        try:
            # Сначала проверяем кэш
            cached_id = self._cache['last_recipe_id'].get(user_id)
            if cached_id:
                return cached_id
            
            # Если нет в кэше, пробуем получить из БД
            if self.db_connected:
                recipes = await db.get_user_recipes(user_id, limit=1)
                if recipes:
                    recipe_id = recipes[0]['id']
                    self._cache['last_recipe_id'][user_id] = recipe_id
                    return recipe_id
            
            return None
        except Exception as e:
            logger.error(f"Error getting last recipe ID for {user_id}: {e}")
            return None

    async def clear_session(self, user_id: int):
        """Полная очистка сессии"""
        try:
            for k in self._cache:
                if user_id in self._cache[k]: 
                    del self._cache[k][user_id]
                    
            if self.db_connected:
                await db.clear_session(user_id)
                
            logger.info(f"Сессия пользователя {user_id} очищена")
        except Exception as e:
            logger.error(f"Error clearing session for {user_id}: {e}")

    async def periodic_cleanup(self):
        """Периодическая очистка старых сессий из кэша"""
        try:
            await self._clean_old_cache()
            logger.debug("Периодическая очистка кэша выполнена")
        except Exception as e:
            logger.error(f"Error during periodic cleanup: {e}")

    async def shutdown(self):
        """Завершение работы"""
        try:
            if self.db_connected:
                await db.close()
                self.db_connected = False
            logger.info("StateManagerDB завершил работу")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

state_manager = StateManagerDB()
