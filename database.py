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
        """Подключение к базе данных через Transaction Pooler (порт 6543)"""
        try:
            # Проверяем, использует ли DATABASE_URL порт 6543
            db_url = DATABASE_URL
            if ":6543" not in db_url:
                logger.warning("⚠️  DATABASE_URL не использует порт 6543 (transaction pooler)")
                logger.warning("   Для Supabase используйте: postgresql://postgres:password@db.project_id.supabase.co:6543/postgres")
            
            self.pool = await asyncpg.create_pool(
                db_url,
                min_size=1,
                max_size=5,
                statement_cache_size=0,  # КРИТИЧЕСКИ ВАЖНО для transaction pooler
                command_timeout=60,
                max_inactive_connection_lifetime=300,
                server_settings={
                    'application_name': 'cooking_bot',
                    'search_path': 'public'
                }
            )
            
            # Проверяем подключение
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                if result == 1:
                    logger.info(f"✅ Успешное подключение к Supabase через Transaction Pooler")
                    logger.info("   Connection String: " + db_url.split('@')[1].split(':')[0])
                else:
                    raise Exception("Connection test failed")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к БД через Transaction Pooler: {e}")
            logger.error(f"   URL: {DATABASE_URL}")
            
            # Пробуем подключиться к стандартному порту 5432 как fallback
            logger.info("🔄 Пробую подключиться к порту 5432...")
            try:
                fallback_url = db_url.replace(":6543", ":5432")
                self.pool = await asyncpg.create_pool(
                    fallback_url,
                    min_size=1,
                    max_size=3,
                    statement_cache_size=0,
                    command_timeout=30
                )
                logger.info("⚠️  Подключение к порту 5432 (не рекомендуется для Supabase)")
            except Exception as fallback_error:
                logger.error(f"❌ Fallback также не удался: {fallback_error}")
                raise e

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
            
            if len(tables) < 4:
                logger.warning("⚠️  Некоторые таблицы отсутствуют!")
                logger.warning(f"Найдены таблицы: {found_tables}")
                return False
            return True

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
                # Определяем лимит: безлимит для админа, обычный для других
                daily_limit = DAILY_IMAGE_LIMIT_ADMIN if telegram_id in ADMIN_IDS else DAILY_IMAGE_LIMIT_NORMAL
                
                user = await conn.fetchrow(
                    """
                    INSERT INTO users (
                        id, username, first_name, last_name, language, 
                        daily_image_limit, last_image_date
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_DATE)
                    RETURNING *
                    """,
                    telegram_id, username, first_name, last_name, language, daily_limit
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

    # ==================== ЛИМИТЫ ИЗОБРАЖЕНИЙ (ЧЕРЕЗ SQL ФУНКЦИИ) ====================

    async def check_image_limit(self, telegram_id: int) -> tuple[bool, int, int]:
        """
        Проверяет лимит генерации изображений через SQL функцию
        
        Returns:
            tuple[can_generate, remaining, limit]
        """
        async with self.pool.acquire() as conn:
            try:
                # Используем созданную SQL функцию
                result = await conn.fetchrow(
                    "SELECT * FROM check_image_limit($1)",
                    telegram_id
                )
                
                if result:
                    return result['can_generate'], result['remaining'], result['user_limit']
                else:
                    # Fallback если функция не существует
                    return await self._check_image_limit_fallback(conn, telegram_id)
                    
            except Exception as e:
                logger.error(f"Ошибка вызова check_image_limit: {e}")
                return await self._check_image_limit_fallback(conn, telegram_id)

    async def _check_image_limit_fallback(self, conn, telegram_id: int) -> tuple[bool, int, int]:
        """Fallback метод если SQL функция не работает"""
        user = await conn.fetchrow(
            """
            SELECT 
                daily_image_limit,
                images_generated_today,
                last_image_date
            FROM users 
            WHERE id = $1
            """,
            telegram_id
        )
        
        if not user:
            return False, 0, 0
        
        limit = user['daily_image_limit']
        
        # Безлимит для админа
        if limit == -1:
            return True, -1, -1
        
        # Проверяем дату
        today = datetime.now().date()
        last_date = user['last_image_date']
        
        # Если дата не сегодня - сбрасываем счётчик
        if last_date != today:
            await conn.execute(
                """
                UPDATE users 
                SET images_generated_today = 0,
                    last_image_date = CURRENT_DATE
                WHERE id = $1
                """,
                telegram_id
            )
            remaining = limit
        else:
            remaining = limit - user['images_generated_today']
        
        can_generate = remaining > 0
        return can_generate, remaining, limit

    async def increment_image_count(self, telegram_id: int) -> bool:
        """Увеличивает счётчик сгенерированных изображений через SQL функцию"""
        async with self.pool.acquire() as conn:
            try:
                # Используем созданную SQL функцию
                result = await conn.fetchval(
                    "SELECT increment_image_count($1)",
                    telegram_id
                )
                return bool(result)
            except Exception as e:
                logger.error(f"Ошибка вызова increment_image_count: {e}")
                # Fallback
                return await self._increment_image_count_fallback(conn, telegram_id)

    async def _increment_image_count_fallback(self, conn, telegram_id: int) -> bool:
        """Fallback метод увеличения счётчика"""
        user = await conn.fetchrow(
            "SELECT last_image_date FROM users WHERE id = $1",
            telegram_id
        )
        
        if not user:
            return False
        
        today = datetime.now().date()
        last_date = user['last_image_date']
        
        if last_date != today:
            # Сбрасываем счётчик
            result = await conn.execute(
                """
                UPDATE users 
                SET images_generated_today = 1,
                    last_image_date = CURRENT_DATE
                WHERE id = $1
                """,
                telegram_id
            )
        else:
            # Увеличиваем счётчик
            result = await conn.execute(
                """
                UPDATE users 
                SET images_generated_today = images_generated_today + 1
                WHERE id = $1
                """,
                telegram_id
            )
        
        return result == "UPDATE 1"

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
        """Общая статистика базы данных через SQL функцию"""
        async with self.pool.acquire() as conn:
            try:
                result = await conn.fetchrow("SELECT * FROM get_bot_stats()")
                if result:
                    return {
                        "users": result['total_users'],
                        "active_sessions": result['active_sessions'],
                        "saved_recipes": result['total_recipes'],
                        "favorites": result['favorite_recipes'],
                        "active_this_week": result['active_week']
                    }
            except Exception as e:
                logger.warning(f"Функция get_bot_stats не найдена: {e}")
            
            # Fallback
            users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            sessions_count = await conn.fetchval("SELECT COUNT(*) FROM sessions WHERE state IS NOT NULL")
            recipes_count = await conn.fetchval("SELECT COUNT(*) FROM recipes")
            favorites_count = await conn.fetchval("SELECT COUNT(*) FROM recipes WHERE is_favorite = TRUE")
            
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

    async def get_activity_by_weekday(self) -> List[Dict]:
        """Статистика активности по дням недели"""
        async with self.pool.acquire() as conn:
            activity = await conn.fetch("""
                SELECT 
                    TO_CHAR(created_at, 'Day') as day_name,
                    COUNT(*) as count
                FROM recipes
                WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY TO_CHAR(created_at, 'Day')
                ORDER BY 
                    CASE TO_CHAR(created_at, 'Day')
                        WHEN 'Monday' THEN 1
                        WHEN 'Tuesday' THEN 2
                        WHEN 'Wednesday' THEN 3
                        WHEN 'Thursday' THEN 4
                        WHEN 'Friday' THEN 5
                        WHEN 'Saturday' THEN 6
                        WHEN 'Sunday' THEN 7
                    END
            """)
            
            result = []
            for row in activity:
                result.append({
                    "day": row['day_name'].strip(),
                    "count": row['count']
                })
            
            return result

    async def get_daily_growth(self, days: int = 7) -> List[Dict]:
        """Рост пользователей по дням"""
        async with self.pool.acquire() as conn:
            growth = await conn.fetch(f"""
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as new_users
                FROM users
                WHERE created_at > NOW() - INTERVAL '{days} days'
                GROUP BY DATE(created_at)
                ORDER BY date
            """)
            
            result = []
            for row in growth:
                result.append({
                    "date": row['date'].strftime("%d.%m"),
                    "count": row['new_users']
                })
            
            return result

    async def get_category_stats(self) -> List[Dict]:
        """Статистика по категориям блюд"""
        async with self.pool.acquire() as conn:
            recipes = await conn.fetch("""
                SELECT dish_name FROM recipes
                WHERE created_at > NOW() - INTERVAL '30 days'
            """)
            
            category_keywords = {
                "soup": ["суп", "борщ", "щи", "солянка", "харчо", "бульон"],
                "main": ["жарен", "тушен", "запечен", "гриль", "котлет", "стейк", "плов", "паста"],
                "salad": ["салат", "винегрет", "оливье"],
                "breakfast": ["омлет", "яичниц", "блин", "каша", "сырник"],
                "dessert": ["торт", "пирог", "десерт", "морожен", "печенье", "пирожное"],
                "drink": ["сок", "компот", "морс", "чай", "кофе", "коктейль"],
                "snack": ["бутерброд", "закуск", "канапе", "тапенад"]
            }
            
            category_counts = {cat: 0 for cat in category_keywords}
            
            for recipe in recipes:
                dish_name = recipe['dish_name'].lower()
                for category, keywords in category_keywords.items():
                    if any(keyword in dish_name for keyword in keywords):
                        category_counts[category] += 1
                        break
            
            result = []
            for category, count in category_counts.items():
                if count > 0:
                    result.append({"category": category, "count": count})
            
            result.sort(key=lambda x: x["count"], reverse=True)
            return result[:5]

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
            if period == 'week':
                time_filter = datetime.now() - timedelta(days=7)
            elif period == 'month':
                time_filter = datetime.now() - timedelta(days=30)
            else:
                time_filter = datetime.now() - timedelta(days=365)
            
            recipes = await conn.fetch(
                "SELECT products_used FROM recipes WHERE created_at > $1 AND products_used IS NOT NULL",
                time_filter
            )
            
            ingredient_counts = {}
            
            for recipe in recipes:
                products_text = recipe['products_used']
                if not products_text:
                    continue
                
                ingredients = re.split(r'[,;\n]', products_text.lower())
                
                for ingredient in ingredients:
                    ingredient = ingredient.strip()
                    ingredient = re.sub(r'\d+', '', ingredient)
                    ingredient = re.sub(r'\b(г|кг|мл|л|шт|штук|штука)\b', '', ingredient)
                    ingredient = ingredient.strip()
                    
                    if len(ingredient) < 3:
                        continue
                    if ingredient in ['и', 'или', 'для', 'по', 'на', 'в', 'из']:
                        continue
                    
                    ingredient_counts[ingredient] = ingredient_counts.get(ingredient, 0) + 1
            
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
            import random
            facts_queries = [
                """
                SELECT dish_name, COUNT(*) as cnt
                FROM recipes
                GROUP BY dish_name
                ORDER BY cnt DESC
                LIMIT 1
                """,
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
                """
                SELECT COUNT(*) as cnt
                FROM recipes
                WHERE created_at > NOW() - INTERVAL '7 days'
                """,
            ]
            
            query = random.choice(facts_queries)
            result = await conn.fetchrow(query)
            
            if not result:
                return "🎲 Пока недостаточно данных для генерации фактов"
            
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
        """Удаляем старые сессии через SQL функцию"""
        async with self.pool.acquire() as conn:
            try:
                deleted = await conn.fetchval(
                    "SELECT cleanup_old_sessions($1)",
                    days_old
                )
                logger.info(f"🧹 Удалены старые сессии: {deleted} записей")
            except Exception as e:
                logger.warning(f"Функция cleanup_old_sessions не найдена: {e}")
                # Fallback
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
