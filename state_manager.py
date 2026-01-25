import logging
from typing import Dict, List, Optional
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
            'last_recipe_id': {}
        }
        self.db_connected = False

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
        # Если в кеше уже что-то есть (даже пустая строка), считаем что загружено
        if user_id in self._cache['products']:
            return

        if not self.db_connected:
            return

        logger.info(f"🔄 Восстановление сессии из БД для {user_id}")
        session = await db.get_session(user_id)
        if session:
            self._cache['products'][user_id] = session.get('products') or ''
            self._cache['states'][user_id] = session.get('state') or ''
            self._cache['categories'][user_id] = session.get('categories') or []
            self._cache['dishes'][user_id] = session.get('generated_dishes') or []
            self._cache['current_dish'][user_id] = session.get('current_dish') or ''
            self._cache['history'][user_id] = session.get('history') or []
        else:
            # Если сессии нет в БД, инициализируем пустыми значениями
            self._cache['products'][user_id] = ''
            self._cache['states'][user_id] = ''

    async def save_session_to_db(self, user_id: int):
        if not self.db_connected: return
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
            logger.error(f"DB Save error: {e}")

    # ==================== PUBLIC METHODS (ASYNC NOW) ====================

    async def get_products(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        return self._cache['products'].get(user_id)

    async def set_products(self, user_id: int, products: str):
        self._cache['products'][user_id] = products
        await self.save_session_to_db(user_id)

    async def add_products(self, user_id: int, new_products: str):
        await self._ensure_cache(user_id)
        current = self._cache['products'].get(user_id)
        if current:
            self._cache['products'][user_id] = f"{current}, {new_products}"
        else:
            self._cache['products'][user_id] = new_products
        await self.save_session_to_db(user_id)

    async def get_state(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        return self._cache['states'].get(user_id)

    async def set_state(self, user_id: int, state: str):
        self._cache['states'][user_id] = state
        await self.save_session_to_db(user_id)

    async def get_dishes_list(self, user_id: int) -> List[Dict]:
        await self._ensure_cache(user_id)
        return self._cache['dishes'].get(user_id, [])

    async def set_dishes_list(self, user_id: int, dishes: List[Dict]):
        self._cache['dishes'][user_id] = dishes
        await self.save_session_to_db(user_id)

    async def get_current_dish(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        return self._cache['current_dish'].get(user_id)

    async def set_current_dish(self, user_id: int, dish_name: str):
        self._cache['current_dish'][user_id] = dish_name
        await self.save_session_to_db(user_id)

    async def get_last_bot_message(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        hist = self._cache['history'].get(user_id, [])
        for msg in reversed(hist):
            if msg.get("role") == "bot":
                return msg.get("text")
        return None

    async def save_recipe_to_history(self, user_id: int, dish_name: str, recipe_text: str, image_url: Optional[str] = None):
        if not self.db_connected: return None
        
        # Добавляем в историю сообщений
        await self._ensure_cache(user_id)
        if user_id not in self._cache['history']: self._cache['history'][user_id] = []
        self._cache['history'][user_id].append({
            "role": "bot", "text": recipe_text, "timestamp": datetime.now().isoformat()
        })
        
        products = await self.get_products(user_id)
        recipe_id = await db.save_recipe(user_id, dish_name, recipe_text, products, image_url)
        self._cache['last_recipe_id'][user_id] = recipe_id
        await self.save_session_to_db(user_id)
        return recipe_id

    async def get_last_saved_recipe_id(self, user_id: int) -> Optional[int]:
        # Этот метод берет только из RAM, так как ID нужен сразу после генерации
        return self._cache['last_recipe_id'].get(user_id)

    async def clear_session(self, user_id: int):
        """Полная очистка"""
        for k in self._cache:
            if user_id in self._cache[k]: del self._cache[k][user_id]
        if self.db_connected:
            await db.clear_session(user_id)

    async def shutdown(self):
        if self.db_connected:
            await db.close()

state_manager = StateManagerDB()
