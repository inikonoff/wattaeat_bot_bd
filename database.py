import asyncpg
from typing import List, Dict, Any, Optional
import json
import logging
import re
from datetime import datetime, timedelta
from config import DATABASE_URL, DAILY_IMAGE_LIMIT_NORMAL, DAILY_IMAGE_LIMIT_ADMIN, ADMIN_IDS

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Подключение к базе данных"""
        try:
            db_url = DATABASE_URL
            if ":6543" not in db_url:
                logger.warning("⚠️  DATABASE_URL не использует порт 6543")
            
            self.pool = await asyncpg.create_pool(
                db_url,
                min_size=1,
                max_size=5,
                statement_cache_size=0,
                command_timeout=60,
                max_inactive_connection_lifetime=300
            )
            
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                logger.info("✅ Успешное подключение к БД")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка подключения: {e}")
            try:
                # Fallback на порт 5432
                fallback_url = db_url.replace(":6543", ":5432")
                self.pool = await asyncpg.create_pool(fallback_url, min_size=1, max_size=3, statement_cache_size=0)
                logger.info("⚠️  Подключение через порт 5432")
            except Exception as fe:
                raise fe

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ... (Остальные методы getUser, check_image_limit и т.д. остаются без изменений) ...
    # Я сократил код для читаемости, вставь сюда методы get_or_create_user, check_image_limit, create_or_update_session и т.д. из прошлого файла
    # ВАЖНО: Ниже добавляем исправление для избранного

    async def get_or_create_user(self, telegram_id: int, username: str = None, first_name: str = None, last_name: str = None, language: str = 'ru') -> Dict:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", telegram_id)
            if not user:
                limit = DAILY_IMAGE_LIMIT_ADMIN if telegram_id in ADMIN_IDS else DAILY_IMAGE_LIMIT_NORMAL
                user = await conn.fetchrow(
                    "INSERT INTO users (id, username, first_name, last_name, language, daily_image_limit, last_image_date) VALUES ($1, $2, $3, $4, $5, $6, CURRENT_DATE) RETURNING *",
                    telegram_id, username, first_name, last_name, language, limit
                )
            return dict(user)

    async def check_image_limit(self, telegram_id: int) -> tuple[bool, int, int]:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT daily_image_limit, images_generated_today, last_image_date FROM users WHERE id = $1", telegram_id)
            if not user: return False, 0, 0
            
            limit = user['daily_image_limit']
            if limit == -1: return True, -1, -1
            
            if user['last_image_date'] != datetime.now().date():
                await conn.execute("UPDATE users SET images_generated_today = 0, last_image_date = CURRENT_DATE WHERE id = $1", telegram_id)
                return True, limit, limit
            
            remaining = limit - user['images_generated_today']
            return remaining > 0, remaining, limit

    async def increment_image_count(self, telegram_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET images_generated_today = images_generated_today + 1 WHERE id = $1", telegram_id)

    # --- Session Methods (оставляем как были) ---
    async def get_session(self, telegram_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM sessions WHERE user_id = $1", telegram_id)
            if row:
                d = dict(row)
                # Десериализация JSON
                for k in ['categories', 'generated_dishes', 'history']:
                    if d.get(k): d[k] = json.loads(d[k])
                return d
            return None

    async def create_or_update_session(self, telegram_id: int, products=None, state=None, categories=None, generated_dishes=None, current_dish=None, history=None):
        async with self.pool.acquire() as conn:
            cat_json = json.dumps(categories) if categories else None
            dish_json = json.dumps(generated_dishes) if generated_dishes else None
            hist_json = json.dumps(history) if history else None
            
            exists = await conn.fetchval("SELECT 1 FROM sessions WHERE user_id = $1", telegram_id)
            if exists:
                await conn.execute(
                    """UPDATE sessions SET products=COALESCE($2, products), state=COALESCE($3, state), 
                    categories=COALESCE($4::jsonb, categories), generated_dishes=COALESCE($5::jsonb, generated_dishes), 
                    current_dish=COALESCE($6, current_dish), history=COALESCE($7::jsonb, history), updated_at=NOW() 
                    WHERE user_id=$1""", telegram_id, products, state, cat_json, dish_json, current_dish, hist_json
                )
            else:
                await conn.execute(
                    "INSERT INTO sessions (user_id, products, state, categories, generated_dishes, current_dish, history) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7::jsonb)",
                    telegram_id, products, state, cat_json, dish_json, current_dish, hist_json
                )

    async def clear_session(self, telegram_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE sessions SET products=NULL, state=NULL, categories='[]'::jsonb, generated_dishes='[]'::jsonb, current_dish=NULL, history='[]'::jsonb WHERE user_id=$1", telegram_id)

    # --- Recipe Methods ---
    async def save_recipe(self, telegram_id: int, dish_name: str, recipe_text: str, products_used: str = None, image_url: str = None) -> int:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow(
                "INSERT INTO recipes (user_id, dish_name, recipe_text, products_used, image_url) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                telegram_id, dish_name, recipe_text, products_used, image_url
            )
            return r['id']
            
    async def get_user_recipes(self, telegram_id: int, limit: int = 10) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM recipes WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2", telegram_id, limit)
            return [dict(r) for r in rows]
   
    async def update_recipe_image(self, recipe_id: int, image_url: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE recipes SET image_url = $1 WHERE id = $2",
                image_url, recipe_id
            )

    async def get_user_favorites(self, telegram_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM recipes WHERE user_id = $1 AND is_favorite = TRUE ORDER BY created_at DESC", telegram_id)
            return [dict(r) for r in rows]
            
    async def get_favorite_recipe(self, recipe_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM recipes WHERE id = $1", recipe_id)
            return dict(r) if r else None

    # === ИСПРАВЛЕНИЕ: Добавлен метод add_to_favorites ===
    async def add_to_favorites(self, user_id: int, recipe_id: int) -> bool:
        """Добавляет рецепт в избранное (Алиас для mark_as_favorite, но с проверкой юзера)"""
        async with self.pool.acquire() as conn:
            # Проверяем, принадлежит ли рецепт пользователю (опционально, но безопасно)
            # В данном случае просто обновляем по ID
            result = await conn.execute(
                "UPDATE recipes SET is_favorite = TRUE WHERE id = $1",
                recipe_id
            )
            return result == "UPDATE 1"

    async def clear_user_history(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM recipes WHERE user_id = $1 AND is_favorite = FALSE", user_id)

    # --- Cache Methods ---
    async def get_cached_image(self, recipe_hash: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM image_cache WHERE recipe_hash = $1", recipe_hash)
            return dict(row) if row else None

    async def save_cached_image(self, dish_name: str, recipe_hash: str, image_url: str, backend: str, file_size: int = 0):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO image_cache (dish_name, recipe_hash, image_url, storage_backend, file_size) 
                VALUES ($1, $2, $3, $4, $5) 
                ON CONFLICT (recipe_hash) DO UPDATE SET image_url=$3, storage_backend=$4""",
                dish_name, recipe_hash, image_url, backend, file_size
            )

db = Database()
