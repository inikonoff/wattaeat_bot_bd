import asyncpg
from typing import List, Dict, Any, Optional
import json
import logging
import re
from datetime import datetime, timedelta
from config import DATABASE_URL

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Подключение к базе данных Supabase"""
        try:
            self.pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                statement_cache_size=0,
                command_timeout=60,
                max_inactive_connection_lifetime=300
            )
            await self._check_tables()
            logger.info("✅ Успешное подключение к Supabase PostgreSQL")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД: {e}")
            raise

    async def close(self):
        """Graceful shutdown пула соединений"""
        if self.pool:
            await self.pool.close()
            logger.info("💤 Соединение с БД закрыто")

    async def _check_tables(self):
        """Проверяем существование таблиц"""
        async with self.pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename IN ('users', 'sessions', 'recipes', 'image_cache')
            """)
            found_tables = [t['tablename'] for t in tables]
            
            if len(tables) < 3:
                logger.warning("⚠️  Некоторые таблицы отсутствуют!")
                logger.warning(f"Найдены таблицы: {found_tables}")
            
            if 'image_cache' not in found_tables:
                logger.info("ℹ️  Таблица image_cache отсутствует (это нормально для первого запуска)")

    # ==================== ПОЛЬЗОВАТЕЛИ ====================

    async def get_or_create_user(
        self, 
        telegram_id: int, 
        username: str = None, 
        first_name: str = None, 
        last_name: str = None,
        language: str = 'ru'
    ) -> Dict:
        """Создаём или получаем пользователя"""
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                telegram_id
            )
            
            if not user:
                user = await conn.fetchrow(
                    """
                    INSERT INTO users (id, username, first_name, last_name, language)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                    """,
                    telegram_id, username, first_name, last_name, language
                )
                logger.info(f"👤 Создан новый пользователь: {telegram_id}")
            else:
                await conn.execute(
                    """
                    UPDATE users 
                    SET last_active = NOW(), 
                        username = COALESCE($2, username)
                    WHERE id = $1
                    """,
                    telegram_id, username
                )
                user = await conn.fetchrow(
                    "SELECT * FROM users WHERE id = $1",
                    telegram_id
                )
            
            return dict(user)

    async def update_user_language(self, telegram_id: int, language: str):
        """Обновляем язык пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET language = $1 WHERE id = $2",
                language, telegram_id
            )

    async def get_all_user_ids(self) -> List[int]:
        """Получить все ID пользователей для broadcast"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users ORDER BY id")
            return [row['id'] for row in rows]

    # ==================== СЕССИИ ====================

    async def create_or_update_session(
        self,
        telegram_id: int,
        products: Optional[str] = None,
        state: Optional[str] = None,
        categories: Optional[List[str]] = None,
        generated_dishes: Optional[List[Dict]] = None,
        current_dish: Optional[str] = None,
        history: Optional[List[Dict]] = None
    ) -> Dict:
        """Создаёт или обновляет сессию пользователя"""
        async with self.pool.acquire() as conn:
            categories_json = json.dumps(categories) if categories else None
            dishes_json = json.dumps(generated_dishes) if generated_dishes else None
            history_json = json.dumps(history) if history else None

            existing = await conn.fetchrow(
                "SELECT id FROM sessions WHERE user_id = $1",
                telegram_id
            )

            if existing:
                session = await conn.fetchrow(
                    """
                    UPDATE sessions 
                    SET 
                        products = COALESCE($2, products),
                        state = COALESCE($3, state),
                        categories = COALESCE($4::jsonb, categories),
                        generated_dishes = COALESCE($5::jsonb, generated_dishes),
                        current_dish = COALESCE($6, current_dish),
                        history = COALESCE($7::jsonb, history),
                        updated_at = NOW()
                    WHERE user_id = $1
                    RETURNING *
                    """,
                    telegram_id, products, state, categories_json, 
                    dishes_json, current_dish, history_json
                )
            else:
                session = await conn.fetchrow(
                    """
                    INSERT INTO sessions 
                    (user_id, products, state, categories, generated_dishes, current_dish, history)
                    VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7::jsonb)
                    RETURNING *
                    """,
                    telegram_id, products, state, categories_json, 
                    dishes_json, current_dish, history_json
                )
            
            return dict(session) if session else None

    async def get_session(self, telegram_id: int) -> Optional[Dict]:
        """Получаем текущую сессию пользователя"""
        async with self.pool.acquire() as conn:
            session = await conn.fetchrow(
                """
                SELECT * FROM sessions 
                WHERE user_id = $1
                ORDER BY updated_at DESC 
                LIMIT 1
                """,
                telegram_id
            )
            
            if session:
                session_dict = dict(session)
                
                if session_dict.get('categories'):
                    try:
                        session_dict['categories'] = json.loads(session_dict['categories'])
                    except:
                        session_dict['categories'] = []
                
                if session_dict.get('generated_dishes'):
                    try:
                        session_dict['generated_dishes'] = json.loads(session_dict['generated_dishes'])
                    except:
                        session_dict['generated_dishes'] = []
                
                if session_dict.get('history'):
                    try:
                        session_dict['history'] = json.loads(session_dict['history'])
                    except:
                        session_dict['history'] = []
                
                return session_dict
            return None

    async def update_session_state(self, telegram_id: int, state: str):
        """Обновляем только состояние сессии"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET state = $1, updated_at = NOW() WHERE user_id = $2",
                state, telegram_id
            )

    async def update_session_products(self, telegram_id: int, products: str):
        """Обновляем только продукты в сессии"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET products = $1, updated_at = NOW() WHERE user_id = $2",
                products, telegram_id
            )

    async def clear_session(self, telegram_id: int):
        """Очищаем сессию пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE sessions 
                SET 
                    products = NULL,
                    state = NULL,
                    categories = '[]'::jsonb,
                    generated_dishes = '[]'::jsonb,
                    current_dish = NULL,
                    history = '[]'::jsonb,
                    updated_at = NOW()
                WHERE user_id = $1
                """,
                telegram_id
            )
            logger.info(f"🧹 Сессия очищена для пользователя {telegram_id}")

    async def delete_session(self, telegram_id: int):
        """Полное удаление сессии"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE user_id = $1",
                telegram_id
            )

    # ==================== РЕЦЕПТЫ ====================

    async def save_recipe(
        self,
        telegram_id: int,
        dish_name: str,
        recipe_text: str,
        products_used: Optional[str] = None,
        image_url: Optional[str] = None
    ) -> int:
        """Сохраняем рецепт в историю"""
        async with self.pool.acquire() as conn:
            recipe = await conn.fetchrow(
                """
                INSERT INTO recipes (user_id, dish_name, recipe_text, products_used, image_url)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                telegram_id, dish_name, recipe_text, products_used, image_url
            )
            logger.info(f"📝 Рецепт сохранён: {dish_name} для пользователя {telegram_id}")
            return recipe['id']

    async def get_user_recipes(self, telegram_id: int, limit: int = 10) -> List[Dict]:
        """Получаем историю рецептов пользователя"""
        async with self.pool.acquire() as conn:
            recipes = await conn.fetch(
                """
                SELECT * FROM recipes 
                WHERE user_id = $1 
                ORDER BY created_at DESC 
                LIMIT $2
                """,
                telegram_id, limit
            )
            return [dict(r) for r in recipes]

    async def mark_as_favorite(self, recipe_id: int) -> bool:
        """Пометить рецепт как избранное"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE recipes SET is_favorite = TRUE WHERE id = $1",
                recipe_id
            )
            return result == "UPDATE 1"

    async def unmark_favorite(self, recipe_id: int):
        """Убрать из избранного"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE recipes SET is_favorite = FALSE WHERE id = $1",
                recipe_id
            )

    async def get_user_favorites(self, telegram_id: int, limit: int = 50) -> List[Dict]:
        """Получаем избранные рецепты пользователя"""
        async with self.pool.acquire() as conn:
            recipes = await conn.fetch(
                """
                SELECT * FROM recipes 
                WHERE user_id = $1 AND is_favorite = TRUE
                ORDER BY created_at DESC 
                LIMIT $2
                """,
                telegram_id, limit
            )
            return [dict(r) for r in recipes]

    async def get_recipe_by_id(self, recipe_id: int) -> Optional[Dict]:
        """Получить рецепт по ID"""
        async with self.pool.acquire() as conn:
            recipe = await conn.fetchrow(
                "SELECT * FROM recipes WHERE id = $1",
                recipe_id
            )
            return dict(recipe) if recipe else None

    async def update_recipe_image(self, recipe_id: int, image_url: str):
        """Обновить URL изображения рецепта"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE recipes SET image_url = $1 WHERE id = $2",
                image_url, recipe_id
            )

    # ==================== КЕШ ИЗОБРАЖЕНИЙ ====================

    async def get_cached_image(self, recipe_hash: str) -> Optional[Dict]:
        """Получить закешированное изображение"""
        async with self.pool.acquire() as conn:
            cached = await conn.fetchrow(
                "SELECT * FROM image_cache WHERE recipe_hash = $1",
                recipe_hash
            )
            return dict(cached) if cached else None

    async def save_cached_image(
        self, 
        dish_name: str, 
        recipe_hash: str, 
        image_url: str, 
        backend: str,
        file_size: int = 0
    ):
        """Сохранить изображение в кеш"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO image_cache (dish_name, recipe_hash, image_url, storage_backend, file_size)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (recipe_hash) DO UPDATE 
                SET image_url = $3, storage_backend = $4, file_size = $5
                """,
                dish_name, recipe_hash, image_url, backend, file_size
            )

    # ==================== АДМИНКА - СТАТИСТИКА ====================

    async def get_stats(self) -> Dict:
        """Общая статистика базы данных"""
        async with self.pool.acquire() as conn:
            users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            sessions_count = await conn.fetchval("SELECT COUNT(*) FROM sessions WHERE state IS NOT NULL")
            recipes_count = await conn.fetchval("SELECT COUNT(*) FROM recipes")
            favorites_count = await conn.fetchval("SELECT COUNT(*) FROM recipes WHERE is_favorite = TRUE")
            
            # Активные за неделю
            week_ago = datetime.now() - timedelta(days=7)
            active_week = await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM recipes WHERE created_at > $1",
                week_ago
            )
            
            return {
                "users": users_count,
                "active_sessions": sessions_count,
                "saved_recipes": recipes_count,
                "favorites": favorites_count,
                "active_this_week": active_week
            }

    async def get_top_users(self, limit: int = 3) -> List[Dict]:
        """Топ-3 поваров по количеству рецептов"""
        async with self.pool.acquire() as conn:
            top_users = await conn.fetch(
                """
                SELECT 
                    u.id,
                    u.username,
                    u.first_name,
                    u.last_name,
                    COUNT(r.id) as recipe_count
                FROM users u
                JOIN recipes r ON u.id = r.user_id
                GROUP BY u.id, u.username, u.first_name, u.last_name
                ORDER BY recipe_count DESC
                LIMIT $1
                """,
                limit
            )
            return [dict(user) for user in top_users]

    async def get_top_ingredients(self, period: str = 'month', limit: int = 10) -> List[Dict]:
        """Топ-10 продуктов за период"""
        async with self.pool.acquire() as conn:
            # Определяем период
            if period == 'week':
                time_filter = datetime.now() - timedelta(days=7)
            elif period == 'month':
                time_filter = datetime.now() - timedelta(days=30)
            else:
                time_filter = datetime.now() - timedelta(days=365)
            
            # Получаем все продукты за период
            recipes = await conn.fetch(
                "SELECT products_used FROM recipes WHERE created_at > $1 AND products_used IS NOT NULL",
                time_filter
            )
            
            # Парсим продукты
            ingredient_counts = {}
            
            for recipe in recipes:
                products_text = recipe['products_used']
                if not products_text:
                    continue
                
                # Разбиваем по запятым, точкам с запятой, переносам
                ingredients = re.split(r'[,;\n]', products_text.lower())
                
                for ingredient in ingredients:
                    ingredient = ingredient.strip()
                    # Убираем числа и единицы измерения
                    ingredient = re.sub(r'\d+', '', ingredient)
                    ingredient = re.sub(r'\b(г|кг|мл|л|шт|штук|штука)\b', '', ingredient)
                    ingredient = ingredient.strip()
                    
                    # Пропускаем короткие и служебные слова
                    if len(ingredient) < 3:
                        continue
                    if ingredient in ['и', 'или', 'для', 'по', 'на', 'в', 'из']:
                        continue
                    
                    ingredient_counts[ingredient] = ingredient_counts.get(ingredient, 0) + 1
            
            # Сортируем и возвращаем топ
            sorted_ingredients = sorted(
                ingredient_counts.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:limit]
            
            return [
                {"name": name, "count": count} 
                for name, count in sorted_ingredients
            ]

    async def get_top_dishes(self, limit: int = 5) -> List[Dict]:
        """Топ-5 блюд по запросам"""
        async with self.pool.acquire() as conn:
            top_dishes = await conn.fetch(
                """
                SELECT 
                    dish_name,
                    COUNT(*) as request_count
                FROM recipes
                GROUP BY dish_name
                ORDER BY request_count DESC
                LIMIT $1
                """,
                limit
            )
            return [dict(dish) for dish in top_dishes]

    async def get_random_fact(self) -> str:
    """Генерирует случайный факт из статистики"""
    async with self.pool.acquire() as conn:
        # Разные виды фактов
        facts_queries = [
            # Самое популярное блюдо
            """
            SELECT dish_name, COUNT(*) as cnt
            FROM recipes
            GROUP BY dish_name
            ORDER BY cnt DESC
            LIMIT 1
            """,
            # Самый активный день недели
            """
            SELECT 
                TO_CHAR(created_at, 'Day') as day_name,
                COUNT(*) as cnt
            FROM recipes
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY TO_CHAR(created_at, 'Day')
            ORDER BY cnt DESC
            LIMIT 1
            """,
            # Общее количество рецептов за неделю
            """
            SELECT COUNT(*) as cnt
            FROM recipes
            WHERE created_at > NOW() - INTERVAL '7 days'
            """,
        ]
            
            import random
            query = random.choice(facts_queries)
            result = await conn.fetchrow(query)
            
            if not result:
                return "🎲 Пока недостаточно данных для генерации фактов"
            
            # Формируем текст факта
            if 'dish_name' in result.keys():
                return f"🍽️ Самое популярное блюдо за всё время: <b>{result['dish_name']}</b> ({result['cnt']} запросов)"
            elif 'day_name' in result.keys():
                day_name = result['day_name'].strip()
                day_map = {
                    'Monday': 'Понедельник',
                    'Tuesday': 'Вторник',
                    'Wednesday': 'Среда',
                    'Thursday': 'Четверг',
                    'Friday': 'Пятница',
                    'Saturday': 'Суббота',
                    'Sunday': 'Воскресенье'
                }
                ru_day = day_map.get(day_name, day_name)
                return f"📅 Самый активный день недели в этом месяце: <b>{ru_day}</b> ({result['cnt']} рецептов)"
            else:
                return f"📈 За последнюю неделю создано <b>{result['cnt']}</b> рецептов"

    # ==================== АДМИНИСТРАТИВНЫЕ ====================

    async def cleanup_old_sessions(self, days_old: int = 7):
        """Удаляем старые сессии"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM sessions 
                WHERE updated_at < NOW() - INTERVAL '1 day' * $1
                """,
                days_old
            )
            logger.info(f"🧹 Удалены старые сессии: {result}")

    async def cleanup_old_image_cache(self, days_old: int = 30):
        """Очистка старого кеша изображений"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM image_cache
                WHERE created_at < NOW() - INTERVAL '1 day' * $1
                """,
                days_old
            )
            logger.info(f"🧹 Очищен кеш изображений: {result}")

# Глобальный экземпляр
db = Database()
