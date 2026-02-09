import logging
from typing import List, Dict
from database import db

logger = logging.getLogger(__name__)

class AdminService:
    """Сервис для админских функций с графиками"""
    
    MEDALS = ["🥇", "🥈", "🥉"]
    
    @staticmethod
    def _create_bar_chart(value: int, max_value: int, bar_length: int = 10, filled_char: str = "🟦") -> str:
        """Создаёт эмодзи-бар для графика"""
        if max_value == 0:
            return "⬜" * bar_length
        
        filled_count = int((value / max_value) * bar_length)
        empty_count = bar_length - filled_count
        
        bar = filled_char * filled_count + "⬜" * empty_count
        return bar
    
    @staticmethod
    async def get_stats_message() -> str:
        """Формирует сообщение с общей статистикой и графиками"""
        try:
            stats = await db.get_stats()
            
            # Получаем данные для графиков
            activity_data = await db.get_activity_by_weekday()
            growth_data = await db.get_daily_growth(days=7)
            category_stats = await db.get_category_stats()
            
            text = "📊 <b>Статистика бота с графиками</b>\n\n"
            
            # Основная статистика
            text += f"👥 Всего пользователей: <b>{stats['users']}</b>\n"
            text += f"🔥 Активных за неделю: <b>{stats['active_this_week']}</b>\n"
            text += f"📱 Активных сессий: <b>{stats['active_sessions']}</b>\n"
            text += f"📝 Рецептов создано: <b>{stats['saved_recipes']}</b>\n"
            text += f"❤️ В избранном: <b>{stats['favorites']}</b>\n\n"
            
            # График активности по дням недели
            if activity_data:
                text += "📈 <b>Активность по дням недели:</b>\n"
                
                max_activity = max(item['count'] for item in activity_data) if activity_data else 1
                
                day_map = {
                    'Monday': 'Пн',
                    'Tuesday': 'Вт', 
                    'Wednesday': 'Ср',
                    'Thursday': 'Чт',
                    'Friday': 'Пт',
                    'Saturday': 'Сб',
                    'Sunday': 'Вс'
                }
                
                for item in activity_data:
                    ru_day = day_map.get(item['day'], item['day'][:2])
                    bar = AdminService._create_bar_chart(item['count'], max_activity, 10, "🟦")
                    text += f"{ru_day} {bar} {item['count']}\n"
                text += "\n"
            
            # График роста пользователей
            if growth_data:
                text += "📊 <b>Новые пользователи (7 дней):</b>\n"
                
                max_growth = max(item['count'] for item in growth_data) if growth_data else 1
                
                for item in growth_data:
                    bar = AdminService._create_bar_chart(item['count'], max_growth, 10, "🟩")
                    text += f"{item['date']} {bar} +{item['count']}\n"
                text += "\n"
            
            # Топ категорий
            if category_stats:
                text += "🏆 <b>Популярные категории:</b>\n"
                
                max_category = max(item['count'] for item in category_stats) if category_stats else 1
                category_names = {
                    "soup": "🍲 Супы",
                    "main": "🍝 Вторые", 
                    "salad": "🥗 Салаты",
                    "breakfast": "🍳 Завтраки",
                    "dessert": "🍰 Десерты",
                    "drink": "🥤 Напитки",
                    "snack": "🥪 Закуски"
                }
                
                for item in category_stats:
                    cat_name = category_names.get(item['category'], item['category'])
                    bar = AdminService._create_bar_chart(item['count'], max_category, 10, "🟩")
                    text += f"{cat_name:<10} {bar} {item['count']}\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}", exc_info=True)
            return "❌ Ошибка получения статистики"
    
    @staticmethod
    async def get_retention_message() -> str:
        """Статистика удержания пользователей"""
        try:
            retention_stats = await db.get_retention_stats()
            
            text = "📈 <b>Статистика удержания пользователей</b>\n\n"
            
            text += f"👥 Всего пользователей с рецептами: <b>{retention_stats['users_with_recipes']}</b>\n"
            text += f"🆕 Новых пользователей за 30 дней: <b>{retention_stats['new_users_month']}</b>\n"
            text += f"🔥 Активных из новых: <b>{retention_stats['active_new_users']}</b>\n"
            text += f"🎯 Удержание новых пользователей: <b>{retention_stats['retention_rate']}%</b>\n"
            text += f"📊 Среднее рецептов на пользователя: <b>{retention_stats['avg_recipes_per_user']}</b>\n\n"
            
            # График активности за 14 дней
            if retention_stats['daily_activity']:
                text += "📅 <b>Активность за 14 дней:</b>\n"
                
                max_active = max(item['active_users'] for item in retention_stats['daily_activity']) if retention_stats['daily_activity'] else 1
                
                for item in retention_stats['daily_activity']:
                    date_str = item['date'].strftime('%d.%m')
                    bar = AdminService._create_bar_chart(item['active_users'], max_active, 8, "🟢")
                    text += f"{date_str} {bar} {item['active_users']} 👤 ({item['recipes_created']} 📝)\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики удержания: {e}", exc_info=True)
            return "❌ Ошибка получения статистики удержания"
    
    @staticmethod
    async def get_user_info_message(user_id: int) -> str:
        """Информация о конкретном пользователе"""
        try:
            user_info = await db.get_user_by_id(user_id)
            
            if not user_info:
                return f"❌ Пользователь с ID {user_id} не найден"
            
            # Формируем имя
            name_parts = []
            if user_info.get('first_name'):
                name_parts.append(user_info['first_name'])
            if user_info.get('last_name'):
                name_parts.append(user_info['last_name'])
            
            display_name = " ".join(name_parts) if name_parts else "Аноним"
            
            # Статус блокировки
            status = "🚫 <b>Заблокирован</b>" if user_info.get('is_banned') else "✅ <b>Активен</b>"
            
            text = f"👤 <b>Информация о пользователе</b>\n\n"
            text += f"🆔 ID: <code>{user_info['id']}</code>\n"
            text += f"👤 Имя: <b>{display_name}</b>\n"
            
            if user_info.get('username'):
                text += f"📱 Username: @{user_info['username']}\n"
            
            text += f"📅 Регистрация: {user_info['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
            text += f"📊 Статус: {status}\n\n"
            
            # Статистика
            text += f"📝 Создано рецептов: <b>{user_info.get('recipe_count', 0)}</b>\n"
            text += f"❤️ В избранном: <b>{user_info.get('favorites_count', 0)}</b>\n"
            
            if user_info.get('last_recipe_date'):
                text += f"🕐 Последний рецепт: {user_info['last_recipe_date'].strftime('%d.%m.%Y')}\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {user_id}: {e}")
            return f"❌ Ошибка получения информации о пользователе {user_id}"
    
    @staticmethod
    async def get_user_status_message() -> str:
        """Статистика пользователей по статусам"""
        try:
            user_stats = await db.get_user_count_by_status()
            
            text = "👥 <b>Статистика пользователей по статусам</b>\n\n"
            
            text += f"👥 Всего пользователей: <b>{user_stats['total']}</b>\n"
            text += f"✅ Активных: <b>{user_stats['active']}</b>\n"
            text += f"🚫 Заблокированных: <b>{user_stats['banned']}</b>\n"
            
            # Процентное соотношение
            if user_stats['total'] > 0:
                active_percent = (user_stats['active'] / user_stats['total']) * 100
                banned_percent = (user_stats['banned'] / user_stats['total']) * 100
                
                text += f"\n📊 <b>Соотношение:</b>\n"
                text += f"✅ Активные: {active_percent:.1f}%\n"
                text += f"🚫 Заблокированные: {banned_percent:.1f}%\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики пользователей: {e}")
            return "❌ Ошибка получения статистики пользователей"
    
    @staticmethod
    async def get_logs_message(lines: int = 20) -> str:
        """Получает последние логи из файла"""
        try:
            import os
            
            log_file = "bot.log"
            if not os.path.exists(log_file):
                # Если файла нет, пробуем найти по стандартным путям
                possible_paths = [
                    "bot.log",
                    "logs/bot.log", 
                    "/var/log/bot.log",
                    "./logs/bot.log"
                ]
                
                for path in possible_paths:
                    if os.path.exists(path):
                        log_file = path
                        break
            
            if not os.path.exists(log_file):
                return "📋 <b>Логи бота</b>\n\nФайл логов не найден"
            
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            
            # Берем последние N строк
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            text = f"📋 <b>Логи бота (последние {len(recent_lines)} строк)</b>\n\n"
            text += "```\n"
            text += "".join(recent_lines)
            text += "```"
            
            # Обрезаем если слишком длинное (Telegram лимит 4096 символов)
            if len(text) > 4000:
                text = text[:3900] + "\n... (логи обрезаны)\n```"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка чтения логов: {e}")
            return f"❌ Ошибка чтения логов: {str(e)[:100]}"
    
    @staticmethod
    async def get_top_cooks_message() -> str:
        """Топ-3 поваров"""
        try:
            top_users = await db.get_top_users(limit=3)
            
            if not top_users:
                return "🏆 <b>Доска почёта</b>\n\nПока нет данных"
            
            text = "🏆 <b>Доска почёта - Топ-3 поваров</b>\n\n"
            
            for idx, user in enumerate(top_users):
                medal = AdminService.MEDALS[idx] if idx < len(AdminService.MEDALS) else "🔸"
                
                name_parts = []
                if user.get('first_name'):
                    name_parts.append(user['first_name'])
                if user.get('last_name'):
                    name_parts.append(user['last_name'])
                
                display_name = " ".join(name_parts) if name_parts else "Аноним"
                
                if user.get('username'):
                    display_name += f" (@{user['username']})"
                
                text += f"{medal} <b>{display_name}</b>\n"
                text += f"   📝 Рецептов: {user['recipe_count']}\n\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения топ поваров: {e}", exc_info=True)
            return "❌ Ошибка получения данных"
    
    @staticmethod
    async def get_top_ingredients_message(period: str = 'month') -> str:
        """Топ-10 продуктов"""
        try:
            top_ingredients = await db.get_top_ingredients(period=period, limit=10)
            
            if not top_ingredients:
                return "🥕 <b>Топ продуктов</b>\n\nПока нет данных"
            
            period_names = {
                'week': 'за неделю',
                'month': 'за месяц',
                'year': 'за год'
            }
            
            text = f"🥕 <b>Народные любимцы - Топ-10 продуктов {period_names.get(period, '')}</b>\n\n"
            
            emoji_map = {
                'картофель': '🥔', 'картошка': '🥔',
                'лук': '🧅',
                'морковь': '🥕',
                'помидор': '🍅', 'томат': '🍅',
                'огурец': '🥒',
                'яйц': '🥚', 'яйко': '🥚',
                'молоко': '🥛',
                'сыр': '🧀',
                'мяс': '🥩', 'говядин': '🥩', 'свинин': '🥩',
                'курица': '🍗', 'куриц': '🍗',
                'рыб': '🐟',
                'рис': '🍚',
                'паста': '🍝', 'макарон': '🍝',
                'хлеб': '🍞',
                'масло': '🧈',
                'чеснок': '🧄',
                'перец': '🌶️',
                'зелень': '🌿', 'петрушка': '🌿', 'укроп': '🌿',
                'капуста': '🥬',
            }
            
            for idx, ingredient in enumerate(top_ingredients, 1):
                name = ingredient['name']
                count = ingredient['count']
                
                emoji = '🔸'
                for key, em in emoji_map.items():
                    if key in name:
                        emoji = em
                        break
                
                text += f"{idx}. {emoji} <b>{name.capitalize()}</b> — {count} раз\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения топ продуктов: {e}", exc_info=True)
            return "❌ Ошибка получения данных"
    
    @staticmethod
    async def get_top_dishes_message() -> str:
        """Топ-5 блюд"""
        try:
            top_dishes = await db.get_top_dishes(limit=5)
            
            if not top_dishes:
                return "🍽️ <b>Популярные блюда</b>\n\nПока нет данных"
            
            text = "🍽️ <b>Что готовим чаще всего - Топ-5</b>\n\n"
            
            for idx, dish in enumerate(top_dishes, 1):
                medal = AdminService.MEDALS[idx - 1] if idx <= 3 else f"{idx}."
                text += f"{medal} <b>{dish['dish_name']}</b>\n"
                text += f"   📊 Запросов: {dish['request_count']}\n\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения топ блюд: {e}", exc_info=True)
            return "❌ Ошибка получения данных"
    
    @staticmethod
    async def get_random_fact_message() -> str:
        """Случайный факт с обработкой ошибок"""
        try:
            fact = await db.get_random_fact()
            
            if not fact or len(fact) < 5:
                return "🎲 <b>Случайный факт</b>\n\nПока недостаточно данных для генерации фактов"
            
            return f"🎲 <b>Случайный факт</b>\n\n{fact}"
            
        except Exception as e:
            logger.error(f"Ошибка получения факта: {e}", exc_info=True)
            return "❌ Ошибка получения данных. Попробуйте позже."
    
    @staticmethod
    async def get_users_list_message(page: int = 1, page_size: int = 20) -> str:
        """Список всех пользователей с пагинацией"""
        try:
            offset = (page - 1) * page_size
            users = await db.get_all_users(limit=page_size, offset=offset)
            
            if not users:
                return "👥 <b>Список пользователей</b>\n\nПользователей не найдено"
            
            text = f"👥 <b>Список пользователей (стр. {page})</b>\n\n"
            
            for idx, user in enumerate(users, start=offset + 1):
                # Формируем имя
                name_parts = []
                if user.get('first_name'):
                    name_parts.append(user['first_name'])
                if user.get('last_name'):
                    name_parts.append(user['last_name'])
                
                display_name = " ".join(name_parts) if name_parts else "Аноним"
                
                # Username
                username = f"@{user['username']}" if user.get('username') else "—"
                
                # ID
                user_id = user['id']
                
                # Статус блокировки
                status = "🚫" if user.get('is_banned') else "✅"
                
                # Статистика
                recipes = user.get('recipe_count', 0)
                favorites = user.get('favorites_count', 0)
                
                # Дата регистрации
                created_at = user['created_at'].strftime('%d.%m.%Y') if user.get('created_at') else "—"
                
                text += f"{idx}. {status} <b>{display_name}</b>\n"
                text += f"   🆔 ID: <code>{user_id}</code>\n"
                text += f"   👤 Username: {username}\n"
                text += f"   📝 Рецептов: {recipes} (❤️ {favorites})\n"
                text += f"   📅 Регистрация: {created_at}\n\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения списка пользователей: {e}", exc_info=True)
            return "❌ Ошибка получения данных"

# Глобальный экземпляр
admin_service = AdminService()
