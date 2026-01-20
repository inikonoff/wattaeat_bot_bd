import logging
from typing import List, Dict
from database import db

logger = logging.getLogger(__name__)

class AdminService:
    """Сервис для админских функций"""
    
    MEDALS = ["🥇", "🥈", "🥉"]
    
    @staticmethod
    def _create_bar_chart(label: str, value: int, max_value: int, width: int = 10) -> str:
        """Создаёт ASCII бар"""
        filled = int((value / max_value) * width) if max_value > 0 else 0
        empty = width - filled
        bar = "█" * filled + "░" * empty
        return f"{label} {bar} {value}"
    
    @staticmethod
    async def get_stats_message() -> str:
        """Формирует сообщение с общей статистикой"""
        try:
            stats = await db.get_stats()
            
            text = "📊 <b>Статистика бота</b>\n\n"
            text += f"👥 Всего пользователей: <b>{stats['users']}</b>\n"
            text += f"🔥 Активных за неделю: <b>{stats['active_this_week']}</b>\n"
            text += f"📱 Активных сессий: <b>{stats['active_sessions']}</b>\n"
            text += f"📝 Рецептов создано: <b>{stats['saved_recipes']}</b>\n"
            text += f"❤️ В избранном: <b>{stats['favorites']}</b>\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return "❌ Ошибка получения статистики"
    
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
                
                # Формируем имя пользователя
                name_parts = []
                if user.get('first_name'):
                    name_parts.append(user['first_name'])
                if user.get('last_name'):
                    name_parts.append(user['last_name'])
                
                display_name = " ".join(name_parts) if name_parts else "Аноним"
                
                # Добавляем username если есть
                if user.get('username'):
                    display_name += f" (@{user['username']})"
                
                text += f"{medal} <b>{display_name}</b>\n"
                text += f"   📝 Рецептов: {user['recipe_count']}\n\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения топ поваров: {e}")
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
            
            # Эмодзи для продуктов (простая эвристика)
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
                
                # Подбираем эмодзи
                emoji = '🔸'
                for key, em in emoji_map.items():
                    if key in name:
                        emoji = em
                        break
                
                text += f"{idx}. {emoji} <b>{name.capitalize()}</b> — {count} раз\n"
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка получения топ продуктов: {e}")
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
            logger.error(f"Ошибка получения топ блюд: {e}")
            return "❌ Ошибка получения данных"
    
    @staticmethod
    async def get_random_fact_message() -> str:
        """Случайный факт"""
        try:
            fact = await db.get_random_fact()
            return f"🎲 <b>Случайный факт</b>\n\n{fact}"
            
        except Exception as e:
            logger.error(f"Ошибка получения факта: {e}")
            return "❌ Ошибка получения данных"

# Глобальный экземпляр
admin_service = AdminService()
