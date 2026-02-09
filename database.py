import asyncpg
from typing import List, Dict, Any, Optional, Tuple
import json
import logging
import re
from datetime import datetime, timedelta
from config import DATABASE_URL, ADMIN_IDS

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

    async def get_or_create_user(self, telegram_id: int, username: str = None, first_name: str = None, last_name: str = None, language: str = 'ru') -> Dict:
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", telegram_id)
            if not user:
                user = await conn.fetchrow(
                    "INSERT INTO users (id, username, first_name, last_name, language, is_banned) VALUES ($1, $2, $3, $4, $5, FALSE) RETURNING *",
                    telegram_id, username, first_name, last_name, language
                )
            return dict(user)

    # --- Session Methods ---
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
    async def save_recipe(self, telegram_id: int, dish_name: str, recipe_text: str, products_used: str = None, image_url: str = None) -> Dict:
        """Сохраняет рецепт и возвращает его полные данные"""
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow(
                "INSERT INTO recipes (user_id, dish_name, recipe_text, products_used, image_url) VALUES ($1, $2, $3, $4, $5) RETURNING *",
                telegram_id, dish_name, recipe_text, products_used, image_url
            )
            return dict(r)
            
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
        """Получает рецепт по ID (без проверки пользователя - для внутреннего использования)"""
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM recipes WHERE id = $1", recipe_id)
            return dict(r) if r else None

    async def get_recipe_by_id(self, user_id: int, recipe_id: int) -> Optional[Dict]:
        """Получает рецепт пользователя по ID (с проверкой принадлежности)"""
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM recipes WHERE id = $1 AND user_id = $2", recipe_id, user_id)
            return dict(r) if r else None

    async def is_recipe_favorite(self, user_id: int, recipe_id: int) -> bool:
        """Проверяет, находится ли рецепт в избранном у пользователя"""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM recipes WHERE id = $1 AND user_id = $2 AND is_favorite = TRUE",
                recipe_id, user_id
            )
            return count > 0

    async def add_to_favorites(self, user_id: int, recipe_id: int) -> bool:
        """Добавляет рецепт в избранное (только если рецепт принадлежит пользователю)"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE recipes SET is_favorite = TRUE WHERE id = $1 AND user_id = $2",
                recipe_id, user_id
            )
            logger.info(f"User {user_id} added recipe {recipe_id} to favorites. Result: {result}")
            return result == "UPDATE 1"

    async def remove_from_favorites(self, user_id: int, recipe_id: int) -> bool:
        """Удаляет рецепт из избранного (только если рецепт принадлежит пользователю)"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE recipes SET is_favorite = FALSE WHERE id = $1 AND user_id = $2",
                recipe_id, user_id
            )
            logger.info(f"User {user_id} removed recipe {recipe_id} from favorites. Result: {result}")
            return result == "UPDATE 1"

    async def clear_user_history(self, user_id: int):
        """Очищает историю рецептов пользователя (только не избранные)"""
        async with self.pool.acquire() as conn:
            deleted_count = await conn.execute("DELETE FROM recipes WHERE user_id = $1 AND is_favorite = FALSE", user_id)
            logger.info(f"User {user_id} cleared history. Deleted {deleted_count} recipes")
            return deleted_count

    # --- НОВЫЕ МЕТОДЫ ДЛЯ АДМИНКИ ---
    
    async def get_all_users(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Получает список всех пользователей с их статистикой"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    u.id,
                    u.username,
                    u.first_name,
                    u.last_name,
                    u.created_at,
                    u.is_banned,
                    COUNT(r.id) as recipe_count,
                    COUNT(CASE WHEN r.is_favorite = TRUE THEN 1 END) as favorites_count
                FROM users u
                LEFT JOIN recipes r ON u.id = r.user_id
                GROUP BY u.id, u.username, u.first_name, u.last_name, u.created_at, u.is_banned
                ORDER BY u.created_at DESC
                LIMIT $1 OFFSET $2
            """, limit, offset)
            return [dict(r) for r in rows]
    
    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Получает информацию о конкретном пользователе"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    u.*,
                    COUNT(r.id) as recipe_count,
                    COUNT(CASE WHEN r.is_favorite = TRUE THEN 1 END) as favorites_count,
                    MAX(r.created_at) as last_recipe_date
                FROM users u
                LEFT JOIN recipes r ON u.id = r.user_id
                WHERE u.id = $1
                GROUP BY u.id
            """, user_id)
            return dict(row) if row else None
    
    async def ban_user(self, user_id: int) -> bool:
        """Блокирует пользователя"""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    "UPDATE users SET is_banned = TRUE WHERE id = $1",
                    user_id
                )
                return result == "UPDATE 1"
            except asyncpg.exceptions.UndefinedColumnError:
                # Если колонки нет, сначала создаем её
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE")
                # Затем устанавливаем значение
                result = await conn.execute(
                    "UPDATE users SET is_banned = TRUE WHERE id = $1",
                    user_id
                )
                return result == "UPDATE 1"
    
    async def unban_user(self, user_id: int) -> bool:
        """Разблокирует пользователя"""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.execute(
                    "UPDATE users SET is_banned = FALSE WHERE id = $1",
                    user_id
                )
                return result == "UPDATE 1"
            except asyncpg.exceptions.UndefinedColumnError:
                # Если колонки нет, сначала создаем её
                await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE")
                return False
    
    async def is_user_banned(self, user_id: int) -> bool:
        """Проверяет, заблокирован ли пользователь"""
        async with self.pool.acquire() as conn:
            try:
                is_banned = await conn.fetchval(
                    "SELECT is_banned FROM users WHERE id = $1",
                    user_id
                )
                return bool(is_banned)
            except asyncpg.exceptions.UndefinedColumnError:
                # Если колонки нет, пользователь точно не заблокирован
                return False
    
    async def get_all_user_ids(self) -> List[int]:
        """Получает список всех ID пользователей (для рассылки)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users WHERE is_banned = FALSE OR is_banned IS NULL")
            return [row['id'] for row in rows]
    
    async def get_user_count_by_status(self) -> Dict:
        """Статистика пользователей по статусам"""
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM users")
            
            # Проверяем наличие колонки is_banned
            try:
                active = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = FALSE OR is_banned IS NULL")
                banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE")
            except asyncpg.exceptions.UndefinedColumnError:
                # Если колонки нет, все пользователи активны
                active = total
                banned = 0
            
            return {
                'total': total,
                'active': active,
                'banned': banned
            }
    
    # --- СТАТИСТИКА ДЛЯ ПОЛЬЗОВАТЕЛЯ ---
    
    async def get_user_stats(self, user_id: int) -> Dict:
        """Статистика конкретного пользователя"""
        async with self.pool.acquire() as conn:
            total_recipes = await conn.fetchval(
                "SELECT COUNT(*) FROM recipes WHERE user_id = $1", 
                user_id
            )
            favorites = await conn.fetchval(
                "SELECT COUNT(*) FROM recipes WHERE user_id = $1 AND is_favorite = TRUE", 
                user_id
            )
            
            return {
                'total_recipes': total_recipes,
                'favorites': favorites
            }
    
    # --- СТАТИСТИКА ДЛЯ АДМИНКИ ---
    
    async def get_stats(self) -> Dict:
        """Общая статистика бота"""
        async with self.pool.acquire() as conn:
            users = await conn.fetchval("SELECT COUNT(*) FROM users")
            week_ago = datetime.now() - timedelta(days=7)
            active_week = await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM recipes WHERE created_at >= $1", 
                week_ago
            )
            active_sessions = await conn.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE updated_at >= $1", 
                week_ago
            )
            recipes = await conn.fetchval("SELECT COUNT(*) FROM recipes")
            favorites = await conn.fetchval("SELECT COUNT(*) FROM recipes WHERE is_favorite = TRUE")
            
            return {
                'users': users,
                'active_this_week': active_week,
                'active_sessions': active_sessions,
                'saved_recipes': recipes,
                'favorites': favorites
            }
    
    async def get_retention_stats(self) -> Dict:
        """Статистика удержания пользователей"""
        async with self.pool.acquire() as conn:
            # Пользователи, создавшие рецепты
            users_with_recipes = await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM recipes"
            )
            
            # Новые пользователи за последние 30 дней
            month_ago = datetime.now() - timedelta(days=30)
            new_users_month = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE created_at >= $1",
                month_ago
            )
            
            # Активные пользователи из новых (создали хотя бы 1 рецепт)
            active_new_users = await conn.fetchval("""
                SELECT COUNT(DISTINCT u.id)
                FROM users u
                JOIN recipes r ON u.id = r.user_id
                WHERE u.created_at >= $1
            """, month_ago)
            
            # Удержание
            retention_rate = (active_new_users / new_users_month * 100) if new_users_month > 0 else 0
            
            # Среднее количество рецептов на пользователя
            avg_recipes_per_user = await conn.fetchval("""
                SELECT AVG(recipe_count) FROM (
                    SELECT user_id, COUNT(*) as recipe_count
                    FROM recipes
                    GROUP BY user_id
                ) sub
            """) or 0
            
            # Активность по дням
            daily_activity = await conn.fetch("""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(DISTINCT user_id) as active_users,
                    COUNT(*) as recipes_created
                FROM recipes
                WHERE created_at >= NOW() - INTERVAL '14 days'
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                LIMIT 14
            """)
            
            return {
                'users_with_recipes': users_with_recipes,
                'new_users_month': new_users_month,
                'active_new_users': active_new_users,
                'retention_rate': round(retention_rate, 1),
                'avg_recipes_per_user': round(float(avg_recipes_per_user), 1),
                'daily_activity': [dict(row) for row in daily_activity]
            }
    
    async def get_activity_by_weekday(self) -> List[Dict]:
        """Активность по дням недели"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    TO_CHAR(created_at, 'Day') as day,
                    COUNT(*) as count
                FROM recipes
                WHERE created_at >= NOW() - INTERVAL '30 days'
                GROUP BY TO_CHAR(created_at, 'Day'), EXTRACT(DOW FROM created_at)
                ORDER BY EXTRACT(DOW FROM created_at)
            """)
            return [{'day': r['day'].strip(), 'count': r['count']} for r in rows]
    
    async def get_daily_growth(self, days: int = 7) -> List[Dict]:
        """Рост пользователей по дням"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as count
                FROM users
                WHERE created_at >= NOW() - INTERVAL '1 day' * $1
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at) DESC
            """, days)
            return [{'date': r['date'].strftime('%d.%m'), 'count': r['count']} for r in rows]
    
    async def get_category_stats(self) -> List[Dict]:
        """Статистика по категориям блюд"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    CASE 
                        WHEN LOWER(dish_name) LIKE '%суп%' OR LOWER(dish_name) LIKE '%борщ%' THEN 'soup'
                        WHEN LOWER(dish_name) LIKE '%салат%' THEN 'salad'
                        WHEN LOWER(dish_name) LIKE '%десерт%' OR LOWER(dish_name) LIKE '%торт%' OR LOWER(dish_name) LIKE '%пирог%' THEN 'dessert'
                        WHEN LOWER(dish_name) LIKE '%завтрак%' OR LOWER(dish_name) LIKE '%омлет%' OR LOWER(dish_name) LIKE '%каша%' THEN 'breakfast'
                        WHEN LOWER(dish_name) LIKE '%напиток%' OR LOWER(dish_name) LIKE '%сок%' OR LOWER(dish_name) LIKE '%смузи%' THEN 'drink'
                        WHEN LOWER(dish_name) LIKE '%закуск%' OR LOWER(dish_name) LIKE '%бутерброд%' THEN 'snack'
                        ELSE 'main'
                    END as category,
                    COUNT(*) as count
                FROM recipes
                GROUP BY category
                ORDER BY count DESC
            """)
            return [{'category': r['category'], 'count': r['count']} for r in rows]
    
    async def get_top_users(self, limit: int = 3) -> List[Dict]:
        """Топ пользователей по количеству рецептов"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    u.id, u.username, u.first_name, u.last_name,
                    COUNT(r.id) as recipe_count
                FROM users u
                LEFT JOIN recipes r ON u.id = r.user_id
                GROUP BY u.id, u.username, u.first_name, u.last_name
                HAVING COUNT(r.id) > 0
                ORDER BY recipe_count DESC
                LIMIT $1
            """, limit)
            return [dict(r) for r in rows]
    
    async def get_top_ingredients(self, period: str = 'month', limit: int = 10) -> List[Dict]:
        """Топ продуктов - ИСПРАВЛЕННАЯ ВЕРСИЯ (без SQL-инъекции)"""
        async with self.pool.acquire() as conn:
            # Безопасное определение интервала
            intervals = {
                'week': 7,
                'month': 30,
                'year': 365
            }
            days = intervals.get(period, 30)
            
            rows = await conn.fetch("""
                SELECT 
                    LOWER(TRIM(ingredient)) as name,
                    COUNT(*) as count
                FROM (
                    SELECT UNNEST(REGEXP_SPLIT_TO_ARRAY(products_used, ',\\s*')) as ingredient
                    FROM recipes
                    WHERE created_at >= NOW() - INTERVAL '1 day' * $1
                    AND products_used IS NOT NULL
                    AND TRIM(products_used) != ''
                ) sub
                WHERE ingredient IS NOT NULL 
                AND TRIM(ingredient) != ''
                AND LENGTH(TRIM(ingredient)) > 1
                GROUP BY LOWER(TRIM(ingredient))
                HAVING COUNT(*) >= 1
                ORDER BY count DESC
                LIMIT $2
            """, days, limit)
            return [{'name': r['name'], 'count': r['count']} for r in rows]
    
    async def get_top_dishes(self, limit: int = 5) -> List[Dict]:
        """Топ блюд"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    dish_name,
                    COUNT(*) as request_count
                FROM recipes
                GROUP BY dish_name
                ORDER BY request_count DESC
                LIMIT $1
            """, limit)
            return [{'dish_name': r['dish_name'], 'request_count': r['request_count']} for r in rows]
    
    async def get_random_fact(self) -> str:
        """Случайный факт"""
        async with self.pool.acquire() as conn:
            total_recipes = await conn.fetchval("SELECT COUNT(*) FROM recipes")
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            avg = total_recipes // max(total_users, 1)
            
            import random
            facts = [
                f"🎯 За все время создано {total_recipes} рецептов!",
                f"👥 Нас уже {total_users} пользователей!",
                f"🔥 Средний пользователь создает {avg} рецептов",
            ]
            return random.choice(facts)


db = Database()