import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from database import db
from config import MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)

class StateManagerDB:
    def __init__(self):
        # Структура кэша в памяти
        self._cache = {
            'products': {},
            'states': {},
            'categories': {},
            'dishes': {},
            'current_dish': {},
            'history': {},
            'last_recipe_id': {},
            'broadcast_text': {},
            'last_access': {} # Для очистки старых данных
        }
        self.MAX_CACHE_AGE = 3600  # Хранить в памяти 1 час, потом выгружать

    async def initialize(self):
        try:
            await db.connect()
            logger.info("✅ StateManager (In-Memory + DB) инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            raise e

    async def shutdown(self):
        await db.close()

    # --- ВНУТРЕННИЕ МЕТОДЫ ---

    async def _ensure_cache(self, user_id: int):
        """Загружает данные из БД в память, если их нет"""
        # Обновляем время доступа
        self._cache['last_access'][user_id] = datetime.now()
        
        # Если данные уже есть в памяти — выходим
        if user_id in self._cache['products']:
            return

        try:
            # Грузим из БД
            session = await db.get_session(user_id)
            if session:
                self._cache['products'][user_id] = session.get('products') or ''
                self._cache['states'][user_id] = session.get('state') or ''
                self._cache['categories'][user_id] = session.get('categories') or []
                self._cache['dishes'][user_id] = session.get('generated_dishes') or []
                self._cache['current_dish'][user_id] = session.get('current_dish') or ''
                self._cache['history'][user_id] = session.get('history') or []
            else:
                self._init_empty_user(user_id)
        except Exception as e:
            logger.error(f"Ошибка загрузки сессии {user_id}: {e}")
            self._init_empty_user(user_id)

    def _init_empty_user(self, user_id: int):
        self._cache['products'][user_id] = ''
        self._cache['states'][user_id] = ''
        self._cache['categories'][user_id] = []
        self._cache['dishes'][user_id] = []
        self._cache['current_dish'][user_id] = ''
        self._cache['history'][user_id] = []

    async def _save_to_db(self, user_id: int):
        """Сохраняет текущее состояние кэша в БД"""
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
            logger.error(f"Ошибка сохранения в БД {user_id}: {e}")

    async def periodic_cleanup(self):
        """Очищает старые данные из памяти, чтобы не было утечек"""
        try:
            now = datetime.now()
            keys_to_remove = []
            
            for uid, last_time in self._cache['last_access'].items():
                if (now - last_time).total_seconds() > self.MAX_CACHE_AGE:
                    keys_to_remove.append(uid)
            
            for uid in keys_to_remove:
                for key in self._cache:
                    if uid in self._cache[key]:
                        del self._cache[key][uid]
            
            if keys_to_remove:
                logger.info(f"🧹 Очищено {len(keys_to_remove)} неактивных сессий из памяти")
                
        except Exception as e:
            logger.error(f"Ошибка очистки кэша: {e}")

    # --- PUBLIC API ---

    async def get_products(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        return self._cache['products'].get(user_id, "")

    async def set_products(self, user_id: int, products: str):
        await self._ensure_cache(user_id)
        self._cache['products'][user_id] = products
        await self._save_to_db(user_id)

    async def add_products(self, user_id: int, new_products: str):
        await self._ensure_cache(user_id)
        current = self._cache['products'].get(user_id, "")
        if current:
            self._cache['products'][user_id] = f"{current}, {new_products}"
        else:
            self._cache['products'][user_id] = new_products
        await self._save_to_db(user_id)

    async def get_state(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        return self._cache['states'].get(user_id, "")

    async def set_state(self, user_id: int, state: str):
        await self._ensure_cache(user_id)
        self._cache['states'][user_id] = state
        await self._save_to_db(user_id)

    async def get_categories(self, user_id: int) -> List[Dict]:
        await self._ensure_cache(user_id)
        return self._cache['categories'].get(user_id, [])

    async def set_categories(self, user_id: int, categories: List[Dict]):
        await self._ensure_cache(user_id)
        self._cache['categories'][user_id] = categories
        await self._save_to_db(user_id)

    async def set_category(self, user_id: int, category: str):
        # Категорию храним только в памяти, в БД она не нужна
        await self._ensure_cache(user_id)
        # Можно добавить логику, если нужно

    async def get_dishes(self, user_id: int) -> List[Dict]:
        await self._ensure_cache(user_id)
        return self._cache['dishes'].get(user_id, [])

    async def set_dishes(self, user_id: int, dishes: List[Dict]):
        await self._ensure_cache(user_id)
        self._cache['dishes'][user_id] = dishes
        await self._save_to_db(user_id)

    async def get_current_dish(self, user_id: int) -> Optional[str]:
        await self._ensure_cache(user_id)
        return self._cache['current_dish'].get(user_id, "")

    async def set_current_dish(self, user_id: int, dish_name: str):
        await self._ensure_cache(user_id)
        self._cache['current_dish'][user_id] = dish_name
        await self._save_to_db(user_id)

    # --- РАССЫЛКА (Только память) ---
    async def set_broadcast_text(self, user_id: int, text: str):
        self._cache['broadcast_text'][user_id] = text

    async def get_broadcast_text(self, user_id: int) -> Optional[str]:
        return self._cache['broadcast_text'].get(user_id)

    # --- ИСТОРИЯ И РЕЦЕПТЫ ---

    async def save_recipe_to_history(self, user_id: int, dish_name: str, recipe_text: str, image_url: Optional[str] = None) -> Optional[int]:
        try:
            await self._ensure_cache(user_id)
            
            # 1. Сохраняем в БД
            products = self._cache['products'].get(user_id)
            recipe_data = await db.save_recipe(user_id, dish_name, recipe_text, products, image_url)
            
            if not recipe_data: return None
            recipe_id = recipe_data['id']
            
            # 2. Обновляем память
            if user_id not in self._cache['history']:
                self._cache['history'][user_id] = []
                
            self._cache['history'][user_id].append({
                "role": "bot",
                "text": recipe_text,
                "timestamp": datetime.now().isoformat(),
                "dish_name": dish_name,
                "recipe_id": recipe_id
            })
            
            # Ограничиваем историю
            if len(self._cache['history'][user_id]) > MAX_HISTORY_MESSAGES:
                self._cache['history'][user_id] = self._cache['history'][user_id][-MAX_HISTORY_MESSAGES:]
                
            self._cache['last_recipe_id'][user_id] = recipe_id
            await self._save_to_db(user_id)
            
            return recipe_id
        except Exception as e:
            logger.error(f"Error saving recipe: {e}")
            return None

    async def clear_session(self, user_id: int):
        try:
            for key in self._cache:
                if user_id in self._cache[key]:
                    del self._cache[key][user_id]
            
            await db.clear_session(user_id)
        except Exception as e:
            logger.error(f"Error clearing session: {e}")

state_manager = StateManagerDB()
