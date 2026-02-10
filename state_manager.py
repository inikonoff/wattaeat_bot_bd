--- START OF FILE state_manager.py ---

import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import redis.asyncio as redis
from database import db
from config import REDIS_URL, MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)

class StateManagerRedis:
    def __init__(self):
        self.redis = None
        self.ttl = 86400  # 24 часа жизни кеша

    async def initialize(self):
        try:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
            await self.redis.ping()
            logger.info("✅ Redis подключен успешно")
            
            # Подключаем БД для персистентности
            await db.connect()
        except Exception as e:
            logger.error(f"❌ Ошибка подключения Redis/DB: {e}")
            raise e

    async def shutdown(self):
        if self.redis:
            await self.redis.close()
        await db.close()

    def _key(self, user_id: int, key_type: str) -> str:
        return f"user:{user_id}:{key_type}"

    # --- БАЗОВЫЕ МЕТОДЫ ---

    async def _get_json(self, user_id: int, key_type: str, default=None):
        """Получает JSON из Redis, если нет - пробует из БД и кеширует"""
        try:
            # 1. Пробуем Redis
            data = await self.redis.get(self._key(user_id, key_type))
            if data:
                return json.loads(data)
            
            # 2. Если нет в Redis, грузим из БД (восстановление сессии)
            session = await db.get_session(user_id)
            if session:
                # Маппинг ключей БД на ключи Redis
                db_map = {
                    'products': 'products',
                    'state': 'state',
                    'categories': 'categories',
                    'generated_dishes': 'dishes',
                    'current_dish': 'current_dish',
                    'history': 'history'
                }
                # Ищем нужный ключ в сессии БД
                for db_key, redis_key in db_map.items():
                    if redis_key == key_type and session.get(db_key):
                        val = session[db_key]
                        # Кешируем в Redis
                        await self._set_json(user_id, key_type, val, save_to_db=False)
                        return val
            
            return default
        except Exception as e:
            logger.error(f"Redis get error ({key_type}): {e}")
            return default

    async def _set_json(self, user_id: int, key_type: str, value: Any, save_to_db: bool = True):
        """Пишет в Redis и (опционально) в БД"""
        try:
            # 1. Пишем в Redis
            json_val = json.dumps(value)
            await self.redis.set(self._key(user_id, key_type), json_val, ex=self.ttl)
            
            # 2. Пишем в БД (Write-through cache)
            if save_to_db:
                db_field_map = {
                    'products': 'products',
                    'state': 'state',
                    'categories': 'categories',
                    'dishes': 'generated_dishes',
                    'current_dish': 'current_dish',
                    'history': 'history'
                }
                if key_type in db_field_map:
                    kwargs = {db_field_map[key_type]: value}
                    await db.create_or_update_session(user_id, **kwargs)
                    
        except Exception as e:
            logger.error(f"Redis set error ({key_type}): {e}")

    # --- PUBLIC API ---

    async def get_products(self, user_id: int) -> Optional[str]:
        return await self._get_json(user_id, 'products', default="")

    async def set_products(self, user_id: int, products: str):
        await self._set_json(user_id, 'products', products)

    async def add_products(self, user_id: int, new_products: str):
        current = await self.get_products(user_id)
        if current:
            updated = f"{current}, {new_products}"
        else:
            updated = new_products
        await self.set_products(user_id, updated)

    async def get_state(self, user_id: int) -> Optional[str]:
        return await self._get_json(user_id, 'state', default="")

    async def set_state(self, user_id: int, state: str):
        await self._set_json(user_id, 'state', state)

    async def get_categories(self, user_id: int) -> List[Dict]:
        return await self._get_json(user_id, 'categories', default=[])

    async def set_categories(self, user_id: int, categories: List[Dict]):
        await self._set_json(user_id, 'categories', categories)
        
    async def set_category(self, user_id: int, category: str):
        await self._set_json(user_id, 'current_category', category, save_to_db=False) # Не храним в БД

    async def get_dishes(self, user_id: int) -> List[Dict]:
        return await self._get_json(user_id, 'dishes', default=[])

    async def set_dishes(self, user_id: int, dishes: List[Dict]):
        await self._set_json(user_id, 'dishes', dishes)

    async def get_current_dish(self, user_id: int) -> Optional[str]:
        return await self._get_json(user_id, 'current_dish', default="")

    async def set_current_dish(self, user_id: int, dish_name: str):
        await self._set_json(user_id, 'current_dish', dish_name)

    # --- РАССЫЛКА (Временные данные, только Redis) ---
    
    async def set_broadcast_text(self, user_id: int, text: str):
        await self._set_json(user_id, 'broadcast_text', text, save_to_db=False)

    async def get_broadcast_text(self, user_id: int) -> Optional[str]:
        return await self._get_json(user_id, 'broadcast_text', default=None)

    # --- ИСТОРИЯ И РЕЦЕПТЫ ---

    async def save_recipe_to_history(self, user_id: int, dish_name: str, recipe_text: str, image_url: Optional[str] = None) -> Optional[int]:
        try:
            # 1. Сохраняем в БД (первичный источник правды для рецептов)
            products = await self.get_products(user_id)
            recipe_data = await db.save_recipe(user_id, dish_name, recipe_text, products, image_url)
            
            if not recipe_data: return None
            
            recipe_id = recipe_data['id']
            
            # 2. Обновляем историю в Redis
            history = await self._get_json(user_id, 'history', default=[])
            history.append({
                "role": "bot",
                "text": recipe_text,
                "timestamp": datetime.now().isoformat(),
                "dish_name": dish_name,
                "recipe_id": recipe_id
            })
            # Ограничиваем историю
            if len(history) > MAX_HISTORY_MESSAGES:
                history = history[-MAX_HISTORY_MESSAGES:]
                
            await self._set_json(user_id, 'history', history)
            await self._set_json(user_id, 'last_recipe_id', recipe_id, save_to_db=False)
            
            return recipe_id
        except Exception as e:
            logger.error(f"Error saving recipe: {e}")
            return None

    async def clear_session(self, user_id: int):
        """Очистка всех ключей пользователя"""
        try:
            keys = [
                self._key(user_id, k) for k in 
                ['products', 'state', 'categories', 'dishes', 'current_dish', 'history', 'broadcast_text']
            ]
            if keys:
                await self.redis.delete(*keys)
            await db.clear_session(user_id)
        except Exception as e:
            logger.error(f"Error clearing session: {e}")

    # Метод periodic_cleanup больше не нужен, так как Redis сам удаляет ключи по TTL (ex=86400)

state_manager = StateManagerRedis()
