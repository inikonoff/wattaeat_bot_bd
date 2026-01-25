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
                
                # Находим максимальное значение для масштабирования
                max_activity = max(item['count'] for item in activity_data) if activity_data else 1
                
                # Дни недели на русском
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
            
            # Эмодзи для продуктов
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
    # ИСПРАВЛЕНИЕ 2: Замените метод get_random_fact_message в admin_service.py

@staticmethod
async def get_random_fact_message() -> str:
    """Случайный факт с обработкой ошибок"""
    try:
        fact = await db.get_random_fact()
        
        # Проверяем, что факт не пустой
        if not fact or len(fact) < 5:
            return "🎲 <b>Случайный факт</b>\n\nПока недостаточно данных для генерации фактов"
        
        return f"🎲 <b>Случайный факт</b>\n\n{fact}"
        
    except Exception as e:
        logger.error(f"Ошибка получения факта: {e}", exc_info=True)
        return "❌ Ошибка получения данных. Попробуйте позже."

# Глобальный экземпляр
admin_service = AdminService()
