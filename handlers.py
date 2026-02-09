import os
import io
import logging
import hashlib
import time
import asyncio
import aiohttp
import re
from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, BufferedInputFile
)

from groq_service import groq_service
from state_manager import state_manager
from database import db as database
from admin_service import admin_service
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

CATEGORY_MAP = {
    "breakfast": "🍳 Завтраки",
    "soup": "🍲 Супы",
    "main": "🍝 Вторые блюда",
    "salad": "🥗 Салаты",
    "snack": "🥪 Закуски",
    "dessert": "🍰 Десерты",
    "drink": "🥤 Напитки",
    "mix": "🍱 Комплексный обед",
    "sauce": "🍾 Соусы"
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_hide_keyboard():
    """Клавиатура для скрытия сообщения"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скрыть", callback_data="delete_msg")]
    ])

def extract_dish_name(text: str) -> str:
    """Извлекает название блюда из разных форматов запросов"""
    text_lower = text.lower()
    
    # Паттерны для удаления
    patterns_to_remove = [
        # Рецепты
        'рецепт', 'рецепта', 'рецепту', 'рецептом', 'рецепты',
        # Приготовление
        'приготовить', 'приготовления', 'приготовлению', 'приготовь', 'приготовьте',
        'сделать', 'сделай', 'сделайте', 'сделаю', 'сделаем',
        # Запросы
        'дай', 'дайте', 'хочу', 'хотел', 'хотела', 'хотело', 'хотели',
        'можно', 'мне', 'надо', 'нужно', 'надо бы',
        # Вопросительные
        'как', 'какой', 'какая', 'какое', 'какие',
        'что', 'чего', 'чему', 'чем',
        'где', 'куда', 'когда', 'почему', 'зачем',
        # Вежливость
        'пожалуйста', 'пожалуй', 'будь', 'будьте', 'добрый',
        'умоляю', 'прошу', 'очень',
        # Действия
        'научи', 'научите', 'объясни', 'объясните',
        'расскажи', 'расскажите', 'покажи', 'покажите',
        'посоветуй', 'посоветуйте', 'подскажи', 'подскажите',
        # Общие слова
        'вкусн', 'быстр', 'простой', 'простого', 'просто',
        'лёгкий', 'легкий', 'лёгкого', 'легкого',
        'классический', 'классического',
        'для', 'от', 'из', 'с', 'по', 'на', 'в'
    ]
    
    # Удаляем паттерны
    dish_name = text_lower
    for pattern in patterns_to_remove:
        # Удаляем слово полностью
        dish_name = re.sub(r'\b' + re.escape(pattern) + r'\b', ' ', dish_name)
    
    # Удаляем знаки препинания в начале/конце
    dish_name = dish_name.strip(' ,.!?;:-—–')
    
    # Удаляем лишние пробелы
    dish_name = ' '.join(dish_name.split())
    
    # Если ничего не осталось, возвращаем оригинал без первых слов
    if not dish_name or len(dish_name) < 2:
        # Более агрессивное извлечение: берем последние слова
        words = text_lower.split()
        if len(words) > 1:
            # Пробуем взять последние 2-4 слова
            dish_name = ' '.join(words[-min(4, len(words)):])
            # Удаляем вопросительные знаки
            dish_name = dish_name.strip('?')
    
    # Первая буква заглавная
    if dish_name and dish_name[0].islower():
        dish_name = dish_name[0].upper() + dish_name[1:]
    
    return dish_name

async def determine_query_type(text: str) -> str:
    """Определяет тип запроса пользователя"""
    text_lower = text.lower()
    
    # 1. Проверяем на список продуктов (самый приоритетный)
    # Эвристика: наличие запятых, союзов "и", "с"
    if ',' in text_lower or ' и ' in text_lower or ' с ' in text_lower:
        # Проверяем, что это не вопрос
        if not any(q in text_lower for q in ['?', 'как', 'что', 'где', 'почему', 'зачем']):
            # Проверяем на ключевые слова рецептов, которые могут быть в списке
            recipe_keywords_in_query = any(word in text_lower for word in 
                                        ['рецепт', 'приготовить', 'сделать', 'как приготовить'])
            
            if not recipe_keywords_in_query:
                # Проверяем длину слов
                words = [w.strip() for w in text_lower.replace(',', ' ').replace(' и ', ' ').replace(' с ', ' ').split()]
                # Слова длиной более 2 символов (исключаем предлоги)
                meaningful_words = [w for w in words if len(w) > 2 and w not in ['для', 'от', 'из', 'по', 'на', 'в']]
                
                if len(meaningful_words) >= 2:
                    return "ingredients"
    
    # 2. Рецепт (второй по приоритету)
    recipe_patterns = [
        'рецепт', 'приготовь', 'приготовьте', 'сделай', 'сделайте',
        'как приготовить', 'как сделать', 'как готовить',
        'хочу приготовить', 'хочу сделать', 'хочу готовить',
        'дай рецепт', 'дайте рецепт', 'рецептик', 'рецептики',
        'пошаговый рецепт', 'приготовление', 'готовка',
        'как готовится', 'как приготовляется', 'как делается',
        'мне нужен рецепт', 'ищу рецепт', 'найди рецепт',
        'рецепт для', 'рецепт от', 'рецепт из'
    ]
    
    for pattern in recipe_patterns:
        if pattern in text_lower:
            return "recipe"
    
    # 3. Сравнение
    comparison_patterns = [
        'или', 'больше', 'меньше', 'чем', 'сравни', 'сравните',
        'что лучше', 'что полезнее', 'что вкуснее',
        'где больше', 'где меньше', 'какая разница',
        'отличие', 'отличия', 'разница между', 'различия',
        'что выбрать', 'что предпочесть', 'что купить',
        'против', 'в сравнении с', 'по сравнению с'
    ]
    
    if any(pattern in text_lower for pattern in comparison_patterns):
        # Проверяем контекст - должно быть сравнение продуктов/блюд
        food_context = any(word in text_lower for word in 
                          ['белк', 'белок', 'жир', 'углевод', 'калори', 'витамин',
                           'минерал', 'полезн', 'вредн', 'питательн', 'диет',
                           'курин', 'говядин', 'свинин', 'рыб', 'овощ', 'фрукт',
                           'молок', 'сыр', 'творог', 'йогурт', 'крупа', 'каша',
                           'масл', 'сахар', 'соль', 'специ', 'приправ'])
        
        if food_context:
            return "comparison"
    
    # 4. Советы по готовке
    advice_patterns = [
        'как правильно', 'правильно ли', 'как лучше',
        'совет', 'советы', 'рекомендация', 'рекомендации',
        'лайфхак', 'лайфхаки', 'секрет', 'секреты',
        'правило', 'правила', 'технология', 'технологии',
        'способ', 'способы', 'метод', 'методы',
        'чтобы было', 'чтобы получилось', 'как добиться',
        'как избежать', 'как не', 'как сделать чтобы',
        'почему не', 'почему не получается'
    ]
    
    for pattern in advice_patterns:
        if pattern in text_lower:
            # Проверяем кулинарный контекст
            cooking_context = any(word in text_lower for word in
                                ['готов', 'приготов', 'вари', 'жари', 'печи',
                                 'выпека', 'туши', 'пари', 'копти', 'маринуй',
                                 'реза', 'чист', 'мыт', 'меша', 'взбива',
                                 'замес', 'раскат', 'форм', 'подава',
                                 'сковород', 'кастрюл', 'духовк', 'плит',
                                 'нож', 'вилк', 'ложк', 'миск', 'тарел'])
            
            if cooking_context:
                return "cooking_advice"
    
    # 5. Питание и диетология
    nutrition_patterns = [
        'белок', 'белки', 'протеин', 'протеины',
        'жир', 'жиры', 'липид', 'липиды',
        'углевод', 'углеводы', 'карбо', 'карбогидрат',
        'калори', 'калорийность', 'энергетическая ценность',
        'витамин', 'витамины', 'минерал', 'минералы',
        'полезно', 'вредно', 'польза', 'вред',
        'диета', 'диеты', 'диетический', 'диетическая',
        'питание', 'питательный', 'питательная',
        'здоров', 'здоровое', 'здоровая', 'здоровый',
        'пп', 'правильное питание',
        'бжу', 'белки жиры углеводы',
        'для похудения', 'для набора массы', 'для набора веса',
        'для похудеть', 'чтобы похудеть', 'чтобы набрать',
        'спортпит', 'спортивное питание', 'спорт питание',
        'низкокалорийный', 'высокобелковый', 'низкоуглеводный',
        'кето', 'кето', 'палео', 'веган', 'вегетариан',
        'глютен', 'лактоз', 'сахар', 'соль', 'холестерин'
    ]
    
    for pattern in nutrition_patterns:
        if pattern in text_lower:
            return "nutrition"
    
    # 6. Общие кулинарные вопросы
    general_cooking_patterns = [
        'сколько варить', 'сколько жарить', 'сколько печь',
        'сколько времени', 'как долго', 'при какой температуре',
        'сколько градусов', 'какая температура',
        'сколько нужно', 'сколько надо', 'в каких пропорциях',
        'соотношение', 'пропорция', 'сколько на сколько',
        'можно ли', 'можно ли есть', 'можно ли готовить',
        'что делать если', 'что делать когда', 'как быть если',
        'почему горчит', 'почему кислит', 'почему сладкий',
        'как узнать', 'как определить', 'как проверить',
        'какой должен быть', 'какой должна быть'
    ]
    
    for pattern in general_cooking_patterns:
        if pattern in text_lower:
            return "general_cooking"
    
    # 7. Если ничего не подошло - unknown
    return "unknown"

# --- KEYBOARDS ---
def get_confirmation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить продукты", callback_data="action_add_more")],
        [InlineKeyboardButton(text="👨‍🍳 Готовить (Категории)", callback_data="action_cook")]
    ])

def get_categories_keyboard(categories: list):
    builder = []
    row = []
    for cat_key in categories:
        if not isinstance(cat_key, str): continue
        text = CATEGORY_MAP.get(cat_key, cat_key.capitalize())
        row.append(InlineKeyboardButton(text=text, callback_data=f"cat_{cat_key}"))
        if len(row) == 2:
            builder.append(row)
            row = []
    if row: builder.append(row)
    builder.append([InlineKeyboardButton(text="🗑 Сброс", callback_data="restart")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_dishes_keyboard(dishes_list: list, category: str):
    """Клавиатура с названиями блюд (каждое блюдо теперь отдельная кнопка)"""
    builder = []
    for i, dish in enumerate(dishes_list):
        btn_text = f"{i+1}. {dish['name'][:30]}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"dish_{i}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_complex_lunch_keyboard():
    """Клавиатура для комплексного обеда (только одна кнопка 'Рецепт')"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Рецепт комплексного обеда", callback_data="dish_complex")],
        [InlineKeyboardButton(text="⬅️ Назад к категории", callback_data="back_to_categories")]
    ])

def get_recipe_keyboard(recipe_id: int = None) -> InlineKeyboardMarkup:
    """Клавиатура под рецептом - ОБНОВЛЕННЫЙ ПОРЯДОК"""
    buttons = []
    
    # Кнопка "В избранное" - ПЕРВАЯ
    if recipe_id:
        buttons.append([InlineKeyboardButton(
            text="❤️ В избранное",
            callback_data=f"fav_add_{recipe_id}"
        )])
    
    # Кнопка "Вернуться к категориям"
    buttons.append([InlineKeyboardButton(
        text="⬅️ Вернуться к категориям", 
        callback_data="back_to_categories"
    )])
    
    # Кнопка "Новый набор продуктов"
    buttons.append([InlineKeyboardButton(
        text="🆕 Новый набор продуктов",
        callback_data="restart"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_recipe_keyboard_favorite(recipe_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для избранного рецепта"""
    buttons = []
    
    # НОВАЯ КНОПКА: Удалить из избранного
    buttons.append([InlineKeyboardButton(
        text="🗑️ Удалить из избранного",
        callback_data=f"fav_delete_{recipe_id}"
    )])
    
    buttons.append([InlineKeyboardButton(
        text="❌ Закрыть",
        callback_data="delete_msg"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_stats_keyboard(user_id: int, history_recipes: list):
    """Клавиатура для статистики с историей"""
    buttons = []
    
    # Кнопки истории последних рецептов
    for recipe in history_recipes[:5]:  # Последние 5 рецептов
        buttons.append([InlineKeyboardButton(
            text=f"📝 {recipe['dish_name'][:30]}",
            callback_data=f"history_{recipe['id']}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🗑 Очистить мою историю", callback_data="clear_my_history")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📈 Retention", callback_data="admin_retention")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="👤 Поиск пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="🚫 Блокировки", callback_data="admin_ban_stats")],
        [InlineKeyboardButton(text="📋 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🏆 Топ поваров", callback_data="admin_top_cooks")],
        [InlineKeyboardButton(text="🥕 Топ продуктов", callback_data="admin_top_ingredients")],
        [InlineKeyboardButton(text="🍽️ Топ блюд", callback_data="admin_top_dishes")],
        [InlineKeyboardButton(text="🎲 Факт", callback_data="admin_random_fact")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])

def get_favorites_keyboard(favorites: list):
    buttons = []
    for recipe in favorites:
        buttons.append([InlineKeyboardButton(text=recipe['dish_name'][:40], callback_data=f"fav_{recipe['id']}")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_broadcast_confirmation_keyboard():
    """Клавиатура подтверждения рассылки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")]
    ])

# --- COMMANDS ---

async def cmd_start(message: Message):
    user_id = message.from_user.id
    
    # Проверка на блокировку
    is_banned = await database.is_user_banned(user_id)
    if is_banned:
        await message.answer("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
        return
    
    try:
        await database.get_or_create_user(
            telegram_id=user_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name
        )
        await state_manager.clear_session(user_id)
        
        text = (
            "👋 <b>Добро пожаловать в ЧёПоесть!</b>\n\n"
            "Я ваш кулинарный помощник! Со мной можно:\n\n"
            "🍽️ <b>Попросить рецепт</b> (любыми словами):\n"
            "<i>• рецепт борща</i>\n"
            "<i>• как приготовить пиццу</i>\n"
            "<i>• хочу сделать омлет</i>\n\n"
            "🥗 <b>Узнать о питании</b>:\n"
            "<i>• где больше белка в курице или говядине?</i>\n"
            "<i>• овсянка для набора мышц</i>\n\n"
            "👨‍🍳 <b>Получить совет</b>:\n"
            "<i>• как правильно варить яйца?</i>\n"
            "<i>• совет по приготовлению стейка</i>\n\n"
            "🥕 <b>Или просто перечислите продукты</b> для подбора рецептов!"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Start error: {e}", exc_info=True)

async def cmd_author(message: Message):
    """ИСПРАВЛЕНО: Изменено на 'Связь с автором бота' и контакт @inikonoff"""
    text = (
        "👨‍💻 <b>Связь с автором бота:</b>\n\n"
        "@inikonoff"
    )
    await message.answer(text, parse_mode="HTML")

async def cmd_stats(message: Message):
    user_id = message.from_user.id
    try:
        stats = await database.get_user_stats(user_id)
        history = await database.get_user_recipes(user_id)
        
        text = (
            f"📊 <b>Ваша статистика:</b>\n\n"
            f"🧾 Всего рецептов: {stats['total_recipes']}\n"
            f"❤️ В избранном: {stats['favorites']}\n\n"
            f"🏆 <b>Ваши достижения:</b>\n"
            f"{'🥇 Кулинарный мастер (50+ рецептов)' if stats['total_recipes'] >= 50 else ''}\n"
            f"{'🔥 Активный кулинар (20+ рецептов)' if stats['total_recipes'] >= 20 else ''}\n"
            f"{'👨‍🍳 Начинающий повар (5+ рецептов)' if stats['total_recipes'] >= 5 else ''}"
        )
        
        await message.answer(text, reply_markup=get_stats_keyboard(user_id, history), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Stats error: {e}", exc_info=True)
        await message.answer("❌ Ошибка загрузки статистики")

async def cmd_favorites(message: Message):
    user_id = message.from_user.id
    try:
        favs = await database.get_user_favorites(user_id)
        if not favs:
            await message.answer("❤️ Пусто в избранном")
            return
        await message.answer(f"❤️ <b>Избранное ({len(favs)}):</b>", reply_markup=get_favorites_keyboard(favs), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Favorites error: {e}", exc_info=True)
        await message.answer("❌ Ошибка")

async def cmd_admin(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("📊 Админ-панель", reply_markup=get_admin_keyboard())
    else:
        await message.answer("❌ Доступ запрещен")

# --- НОВЫЕ АДМИН КОМАНДЫ ---

async def cmd_retention(message: Message):
    """Команда для получения статистики удержания"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    try:
        text = await admin_service.get_retention_message()
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Retention command error: {e}")
        await message.answer("❌ Ошибка получения статистики удержания")

async def cmd_user(message: Message):
    """Команда для получения информации о пользователе по ID"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /user [ID_пользователя]\nПример: /user 123456789")
        return
    
    try:
        user_id = int(args[1])
        text = await admin_service.get_user_info_message(user_id)
        await message.answer(text, parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")
    except Exception as e:
        logger.error(f"User command error: {e}")
        await message.answer(f"❌ Ошибка получения информации о пользователе: {str(e)[:100]}")

async def cmd_ban(message: Message):
    """Команда для блокировки пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /ban [ID_пользователя] [причина (опционально)]\nПример: /ban 123456789 спам")
        return
    
    try:
        user_id = int(args[1])
        reason = " ".join(args[2:]) if len(args) > 2 else "Причина не указана"
        
        # Проверяем, существует ли пользователь
        user_info = await database.get_user_by_id(user_id)
        if not user_info:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        # Проверяем, не заблокирован ли уже
        if user_info.get('is_banned'):
            await message.answer(f"⚠️ Пользователь {user_id} уже заблокирован")
            return
        
        # Блокируем
        success = await database.ban_user(user_id)
        if success:
            logger.info(f"Админ {message.from_user.id} заблокировал пользователя {user_id}. Причина: {reason}")
            await message.answer(f"✅ Пользователь {user_id} успешно заблокирован\n📝 Причина: {reason}")
        else:
            await message.answer(f"❌ Не удалось заблокировать пользователя {user_id}")
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")
    except Exception as e:
        logger.error(f"Ban command error: {e}")
        await message.answer(f"❌ Ошибка блокировки пользователя: {str(e)[:100]}")

async def cmd_unban(message: Message):
    """Команда для разблокировки пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unban [ID_пользователя]\nПример: /unban 123456789")
        return
    
    try:
        user_id = int(args[1])
        
        # Проверяем, существует ли пользователь
        user_info = await database.get_user_by_id(user_id)
        if not user_info:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден")
            return
        
        # Проверяем, не разблокирован ли уже
        if not user_info.get('is_banned'):
            await message.answer(f"⚠️ Пользователь {user_id} не заблокирован")
            return
        
        # Разблокируем
        success = await database.unban_user(user_id)
        if success:
            logger.info(f"Админ {message.from_user.id} разблокировал пользователя {user_id}")
            await message.answer(f"✅ Пользователь {user_id} успешно разблокирован")
        else:
            await message.answer(f"❌ Не удалось разблокировать пользователя {user_id}")
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")
    except Exception as e:
        logger.error(f"Unban command error: {e}")
        await message.answer(f"❌ Ошибка разблокировки пользователя: {str(e)[:100]}")

async def cmd_logs(message: Message):
    """Команда для просмотра логов"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    args = message.text.split()
    lines = 20  # По умолчанию
    
    if len(args) > 1:
        try:
            lines = int(args[1])
            lines = min(lines, 100)  # Максимум 100 строк
            lines = max(lines, 5)    # Минимум 5 строк
        except ValueError:
            await message.answer("❌ Неверный формат количества строк. Используйте число.")
            return
    
    try:
        text = await admin_service.get_logs_message(lines)
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Logs command error: {e}")
        await message.answer(f"❌ Ошибка чтения логов: {str(e)[:100]}")

async def cmd_broadcast(message: Message):
    """Начало процесса рассылки"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    # Сохраняем сообщение для рассылки в состояние
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "📢 <b>Рассылка сообщений</b>\n\n"
            "Использование: /broadcast [сообщение]\n\n"
            "Пример: /broadcast Привет всем! У нас обновление бота!",
            parse_mode="HTML"
        )
        return
    
    broadcast_text = args[1]
    
    # Получаем количество пользователей
    user_ids = await database.get_all_user_ids()
    user_count = len(user_ids)
    
    await message.answer(
        f"📢 <b>Подтверждение рассылки</b>\n\n"
        f"📝 <b>Сообщение:</b>\n{broadcast_text}\n\n"
        f"👥 <b>Получатели:</b> {user_count} пользователей\n\n"
        f"<i>Отправить это сообщение всем пользователям?</i>",
        reply_markup=get_broadcast_confirmation_keyboard(),
        parse_mode="HTML"
    )
    
    # Сохраняем текст для рассылки во временное хранилище
    await state_manager.set_broadcast_text(message.from_user.id, broadcast_text)

# --- ТИПЫ ЗАПРОСОВ И ОБРАБОТЧИКИ ---

async def handle_text(message: Message):
    user_id = message.from_user.id
    
    # Проверка на блокировку
    is_banned = await database.is_user_banned(user_id)
    if is_banned:
        await message.answer("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
        return
    
    text = message.text.strip()
    
    # Определяем тип запроса
    query_type = await determine_query_type(text)
    
    logger.info(f"Запрос от {user_id}: '{text}' -> тип: {query_type}")
    
    if query_type == "recipe":
        await handle_recipe_request(message, text)
    elif query_type == "comparison":
        await handle_comparison_request(message, text)
    elif query_type == "cooking_advice":
        await handle_cooking_advice(message, text)
    elif query_type == "nutrition":
        await handle_nutrition_request(message, text)
    elif query_type == "general_cooking":
        await handle_general_cooking_request(message, text)
    elif query_type == "ingredients":
        await process_products_input(message, user_id, text)
    else:
        # Если непонятно, что хочет пользователь
        await message.answer(
            "🤔 <b>Понял вас не до конца!</b>\n\n"
            "Я ваш кулинарный помощник! Со мной можно:\n\n"
            "🍽️ <b>Попросить рецепт</b> (любыми словами):\n"
            "<i>• рецепт борща</i>\n"
            "<i>• как приготовить пиццу</i>\n"
            "<i>• хочу сделать омлет</i>\n\n"
            "🥗 <b>Узнать о питании</b>:\n"
            "<i>• где больше белка в курице или говядине?</i>\n"
            "<i>• овсянка для набора мышц</i>\n\n"
            "👨‍🍳 <b>Получить совет</b>:\n"
            "<i>• как правильно варить яйца?</i>\n"
            "<i>• совет по приготовлению стейка</i>\n\n"
            "🥕 <b>Или просто перечислите продукты</b> для подбора рецептов!\n\n"
            "<i>Попробуйте сформулировать иначе...</i>",
            parse_mode="HTML"
        )

async def handle_recipe_request(message: Message, text: str):
    """Обработка запросов на рецепты (разные форматы)"""
    user_id = message.from_user.id
    
    # Извлекаем название блюда из разных форматов
    dish_name = extract_dish_name(text)
    
    if not dish_name or len(dish_name) < 2:
        await message.answer(
            "🍽️ <b>Уточните, пожалуйста</b>\n\n"
            "Напишите, рецепт какого блюда вас интересует?\n"
            "Например: <i>рецепт борща</i>, <i>как приготовить пиццу</i>, <i>хочу сделать омлет</i>",
            parse_mode="HTML"
        )
        return
    
    wait = await message.answer(f"👨‍🍳 Ищу рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
    
    try:
        # Генерируем рецепт с заголовком
        recipe = await groq_service.generate_freestyle_recipe(dish_name)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_name)
        await state_manager.set_state(user_id, "recipe_sent")
        
        # Сохраняем рецепт и получаем его ID
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        if recipe_id:
            await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
        else:
            await message.answer(recipe, parse_mode="HTML")
    except Exception as e:
        await wait.delete()
        logger.error(f"Recipe error: {e}", exc_info=True)
        await message.answer(
            "❌ Не удалось найти рецепт.\n\n"
            "Попробуйте:\n"
            "• Уточнить название блюда\n"
            "• Проверить написание\n"
            "• Спросить иначе\n\n"
            "<i>Например: 'рецепт классического борща'</i>",
            parse_mode="HTML"
        )

async def handle_comparison_request(message: Message, text: str):
    """Обработка запросов на сравнение продуктов/блюд"""
    wait = await message.answer("🔍 Анализирую и сравниваю...", parse_mode="HTML")
    
    try:
        response = await groq_service.generate_comparison(text)
        await wait.delete()
        
        await message.answer(f"🔍 <b>Сравнительный анализ:</b>\n\n{response}", parse_mode="HTML")
        
    except Exception as e:
        await wait.delete()
        logger.error(f"Comparison error: {e}", exc_info=True)
        await message.answer(
            "❌ Не удалось провести сравнение.\n\n"
            "Попробуйте сформулировать иначе:\n"
            "• 'Что лучше: курица или рыба?'\n"
            "• 'Сравни овсянку и гречку'\n"
            "• 'Где больше белка в яйцах или твороге?'",
            parse_mode="HTML"
        )

async def handle_cooking_advice(message: Message, text: str):
    """Обработка запросов на советы по готовке"""
    wait = await message.answer("👨‍🍳 Ищу лучшие советы...", parse_mode="HTML")
    
    try:
        response = await groq_service.generate_cooking_advice(text)
        await wait.delete()
        
        await message.answer(f"👨‍🍳 <b>Совет шефа:</b>\n\n{response}", parse_mode="HTML")
        
    except Exception as e:
        await wait.delete()
        logger.error(f"Cooking advice error: {e}", exc_info=True)
        await message.answer(
            "❌ Не удалось найти информацию.\n\n"
            "Попробуйте уточнить вопрос:\n"
            "• 'Как правильно варить яйца всмятку?'\n"
            "• 'Совет по приготовлению сочного стейка'\n"
            "• 'Как сделать тесто для пиццы воздушным?'",
            parse_mode="HTML"
        )

async def handle_nutrition_request(message: Message, text: str):
    """Обработка запросов о питании"""
    wait = await message.answer("🥗 Анализирую питательную ценность...", parse_mode="HTML")
    
    try:
        response = await groq_service.generate_nutrition_info(text)
        await wait.delete()
        
        await message.answer(f"🥗 <b>Информация о питании:</b>\n\n{response}", parse_mode="HTML")
        
    except Exception as e:
        await wait.delete()
        logger.error(f"Nutrition error: {e}", exc_info=True)
        await message.answer(
            "❌ Не удалось найти информацию о питании.\n\n"
            "Попробуйте сформулировать иначе:\n"
            "• 'Сколько белка в куриной грудке?'\n"
            "• 'Полезные свойства овсянки'\n"
            "• 'Диетические рецепты для похудения'",
            parse_mode="HTML"
        )

async def handle_general_cooking_request(message: Message, text: str):
    """Обработка общих кулинарных вопросов"""
    wait = await message.answer("🍳 Ищу ответ на ваш вопрос...", parse_mode="HTML")
    
    try:
        # Используем общий промпт для кулинарных вопросов
        safe_question = groq_service._sanitize_input(text, max_length=300)
        
        prompt = f"""Ты эксперт по кулинарии. Ответь на вопрос: "{safe_question}"

Требования:
1. Будь точным и практичным
2. Дай конкретные цифры если нужно (время, температура, пропорции)
3. Объясни просто и понятно
4. Добавь полезные советы
5. Используй эмодзи для наглядности

Формат для Telegram HTML."""

        response = await groq_service._send_groq_request(
            system_prompt="Ты опытный повар и кулинарный эксперт, помогающий людям готовить лучше.",
            user_text=prompt,
            task_type="general_cooking",
            temperature=0.4,
            max_tokens=1000
        )
        
        formatted_response = groq_service._clean_html_for_telegram(response)
        await wait.delete()
        
        await message.answer(f"🍳 <b>Ответ на ваш вопрос:</b>\n\n{formatted_response}", parse_mode="HTML")
        
    except Exception as e:
        await wait.delete()
        logger.error(f"General cooking error: {e}", exc_info=True)
        await message.answer(
            "❌ Не удалось найти ответ.\n\n"
            "Попробуйте задать вопрос иначе или уточнить детали.",
            parse_mode="HTML"
        )

async def process_products_input(message: Message, user_id: int, products_text: str):
    """Обработка списка продуктов"""
    try:
        await state_manager.add_products(user_id, products_text)
        current = await state_manager.get_products(user_id)
        await message.answer(
            f"✅ <b>Продукты сохранены:</b> {current}\n\n"
            f"Что делаем дальше?",
            reply_markup=get_confirmation_keyboard(), 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error processing products: {e}", exc_info=True)
        await message.answer("❌ Ошибка обработки продуктов")

# --- ГОЛОСОВЫЕ СООБЩЕНИЯ ---

async def handle_voice(message: Message):
    user_id = message.from_user.id
    
    # Проверка на блокировку
    is_banned = await database.is_user_banned(user_id)
    if is_banned:
        await message.answer("🚫 Ваш аккаунт заблокирован. Обратитесь к администратору.")
        return
    
    processing_msg = await message.answer("🎧 Распознаю голос...")
    try:
        file = await message.bot.get_file(message.voice.file_id if message.voice else message.audio.file_id)
        buffer = io.BytesIO()
        await message.bot.download_file(file.file_path, buffer)
        
        text = await groq_service.transcribe_voice(buffer.getvalue())
        await processing_msg.delete()
        
        if text:
            # Обрабатываем распознанный текст как обычный текст
            await handle_text(Message(
                message_id=message.message_id,
                date=message.date,
                chat=message.chat,
                text=text,
                from_user=message.from_user
            ))
        else:
            await message.answer("❌ Не удалось распознать голос. Попробуйте написать текстом.")
    except Exception as e:
        await processing_msg.delete()
        logger.error(f"Voice error: {e}", exc_info=True)
        await message.answer("❌ Ошибка распознавания голоса. Попробуйте написать текстом.")

# --- CALLBACK HANDLERS ---

async def handle_action_cook(c: CallbackQuery):
    user_id = c.from_user.id
    products = await state_manager.get_products(user_id)
    if not products:
        await c.answer("❌ Сначала укажите продукты", show_alert=True)
        return
    
    wait = await c.message.edit_text("📊 Анализирую продукты...")
    
    try:
        categories = await groq_service.analyze_categories(products)
        available_categories = categories
        
        await state_manager.set_categories(user_id, categories)
        
        text = f"👨‍🍳 Выберите категорию блюда:\n\n📦 Ваши продукты: <b>{products}</b>"
        await wait.edit_text(text, reply_markup=get_categories_keyboard(available_categories), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Cook error: {e}", exc_info=True)
        await wait.edit_text("❌ Ошибка анализа продуктов")

async def handle_category_selection(c: CallbackQuery):
    user_id = c.from_user.id
    category = c.data.replace("cat_", "")
    
    if category == "mix":
        # Для комплексного обеда показываем только кнопку "Рецепт"
        await state_manager.set_category(user_id, category)
        products = await state_manager.get_products(user_id)
        category_name = CATEGORY_MAP.get(category, category.capitalize())
        text = f"🍱 Категория: <b>{category_name}</b>\n\n📦 Продукты: {products}"
        await c.message.edit_text(text, reply_markup=get_complex_lunch_keyboard(), parse_mode="HTML")
        return
    
    wait = await c.message.edit_text(f"🍽️ Подбираю блюда категории <b>{CATEGORY_MAP.get(category, category)}</b>...", parse_mode="HTML")
    
    try:
        await state_manager.set_category(user_id, category)
        
        products = await state_manager.get_products(user_id)
        dishes = await groq_service.generate_dishes_list(products, category)
        
        await state_manager.set_dishes(user_id, dishes)
        
        category_name = CATEGORY_MAP.get(category, category.capitalize())
        text = f"🍽️ Категория: <b>{category_name}</b>\n\n📦 Продукты: {products}"
        await wait.edit_text(text, reply_markup=get_dishes_keyboard(dishes, category), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Category selection error: {e}", exc_info=True)
        await wait.edit_text("❌ Ошибка")

async def handle_dish_selection(c: CallbackQuery):
    user_id = c.from_user.id
    
    # Проверяем специальный случай комплексного обеда
    if c.data == "dish_complex":
        products = await state_manager.get_products(user_id)
        wait = await c.message.edit_text("👨‍🍳 Создаю комплексный обед...", parse_mode="HTML")
        
        try:
            recipe = await groq_service.generate_recipe("Комплексный обед", products)
            await wait.delete()
            
            await state_manager.set_current_dish(user_id, "Комплексный обед")
            await state_manager.set_state(user_id, "recipe_sent")
            recipe_id = await state_manager.save_recipe_to_history(user_id, "Комплексный обед", recipe)
            
            if recipe_id:
                await c.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
            else:
                await c.message.answer(recipe, parse_mode="HTML")
            await c.answer()
        except Exception as e:
            await wait.delete()
            logger.error(f"Complex lunch error: {e}", exc_info=True)
            await c.answer("❌ Ошибка генерации", show_alert=True)
        return
    
    # Обычный выбор блюда
    dish_idx = int(c.data.replace("dish_", ""))
    products = await state_manager.get_products(user_id)
    dishes = await state_manager.get_dishes(user_id)
    
    if dish_idx >= len(dishes):
        await c.answer("❌ Блюдо не найдено", show_alert=True)
        return
    
    dish = dishes[dish_idx]
    dish_name = dish.get("name", "Неизвестное блюдо")
    
    wait = await c.message.edit_text(f"👨‍🍳 Готовлю рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
    
    try:
        recipe = await groq_service.generate_recipe(dish_name, products)
        
        # ВАЛИДАЦИЯ РЕЦЕПТА
        is_valid, issues = await groq_service.validate_recipe_consistency(products, recipe)
        
        if not is_valid:
            logger.warning(f"Recipe validation failed: {issues}")
            # Пробуем перегенерировать без недостающих ингредиентов
            recipe = await groq_service.regenerate_recipe_without_missing(dish_name, products, recipe, issues)
        
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_name)
        await state_manager.set_state(user_id, "recipe_sent")
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        if recipe_id:
            await c.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
        else:
            await c.message.answer(recipe, parse_mode="HTML")
        await c.answer()
        
    except Exception as e:
        await wait.delete()
        logger.error(f"Recipe error: {e}", exc_info=True)
        await c.answer("❌ Ошибка генерации", show_alert=True)

async def handle_fav_add(callback: CallbackQuery):
    """Добавление рецепта в избранное"""
    try:
        recipe_id = int(callback.data.replace("fav_add_", ""))
        user_id = callback.from_user.id
        
        # Проверяем, не в избранном ли уже у этого пользователя
        already_favorite = await database.is_recipe_favorite(user_id, recipe_id)
        
        if already_favorite:
            await callback.answer("❤️ Уже в избранном!", show_alert=False)
            return
        
        # Проверяем, существует ли рецепт у пользователя
        recipe = await database.get_recipe_by_id(user_id, recipe_id)
        if not recipe:
            await callback.answer("❌ Рецепт не найден", show_alert=True)
            return
        
        # Добавляем в избранное
        success = await database.add_to_favorites(user_id, recipe_id)
        
        if success:
            await callback.answer("✅ Добавлено в избранное!", show_alert=False)
        else:
            await callback.answer("❌ Не удалось добавить", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка добавления в избранное: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_fav_view(callback: CallbackQuery):
    """Просмотр избранного рецепта"""
    try:
        recipe_id = int(callback.data.replace("fav_", ""))
        user_id = callback.from_user.id
        
        recipe = await database.get_recipe_by_id(user_id, recipe_id)
        
        if not recipe:
            await callback.answer("❌ Рецепт не найден", show_alert=True)
            return
        
        # Проверяем, что рецепт действительно в избранном
        if not recipe.get('is_favorite'):
            await callback.answer("❌ Рецепт не в избранном", show_alert=True)
            return
        
        # Сохраняем информацию о текущем блюде
        await state_manager.set_current_dish(user_id, recipe['dish_name'])
        
        await callback.message.edit_text(
            recipe['recipe_text'],
            reply_markup=get_recipe_keyboard_favorite(recipe_id),
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка получения избранного: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_fav_delete(callback: CallbackQuery):
    """Удаление рецепта из избранного"""
    try:
        recipe_id = int(callback.data.replace("fav_delete_", ""))
        user_id = callback.from_user.id
        
        # Удаляем из избранного
        success = await database.remove_from_favorites(user_id, recipe_id)
        
        if success:
            await callback.message.edit_text(
                "✅ Рецепт удалён из избранного",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
                ])
            )
            await callback.answer("✅ Удалено!")
        else:
            await callback.answer("❌ Не удалось удалить или рецепт не найден", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка удаления из избранного: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_history_view(callback: CallbackQuery):
    """Просмотр рецепта из истории"""
    try:
        recipe_id = int(callback.data.replace("history_", ""))
        user_id = callback.from_user.id
        
        recipe = await database.get_recipe_by_id(user_id, recipe_id)
        
        if not recipe:
            await callback.answer("❌ Рецепт не найден", show_alert=True)
            return
        
        # Сохраняем информацию о текущем блюде
        await state_manager.set_current_dish(user_id, recipe['dish_name'])
        
        await callback.message.edit_text(
            recipe['recipe_text'],
            reply_markup=get_recipe_keyboard(recipe_id),
            parse_mode="HTML"
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка просмотра истории: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_restart(callback: CallbackQuery):
    """Сброс сессии"""
    user_id = callback.from_user.id
    try:
        await state_manager.clear_session(user_id)
        await callback.message.edit_text("✅ Сброшено")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка сброса сессии: {e}", exc_info=True)
        await callback.answer("❌ Ошибка сброса", show_alert=True)

async def handle_delete_msg(c: CallbackQuery): 
    """Удаление сообщения"""
    try: 
        await c.message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

async def handle_action_add_more(c: CallbackQuery): 
    """Добавление продуктов"""
    await c.message.edit_text("✏️ Пишите еще продукты:")

async def handle_back_to_categories(c: CallbackQuery): 
    """Возврат к категориям"""
    await handle_action_cook(c)

async def handle_repeat_recipe(c: CallbackQuery):
    """Генерация нового варианта рецепта"""
    user_id = c.from_user.id
    dish_name = await state_manager.get_current_dish(user_id)
    products = await state_manager.get_products(user_id)
    
    if not dish_name:
        await c.answer("❌ Блюдо не найдено", show_alert=True)
        return
    
    wait = await c.message.edit_text(f"🔄 Генерирую новый вариант: <b>{dish_name}</b>...", parse_mode="HTML")
    
    try:
        # Генерируем новый вариант рецепта
        recipe = await groq_service.generate_recipe(dish_name, products)
        
        # ВАЛИДАЦИЯ РЕЦЕПТА (дополнительная проверка)
        is_valid, issues = await groq_service.validate_recipe_consistency(products, recipe)
        
        if not is_valid:
            logger.warning(f"Recipe validation failed on repeat: {issues}")
            # Пробуем перегенерировать
            recipe = await groq_service.regenerate_recipe_without_missing(dish_name, products, recipe, issues)
        
        await wait.delete()
        
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        if recipe_id:
            await c.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
        else:
            await c.message.answer(recipe, parse_mode="HTML")
        await c.answer("✅ Новый вариант готов!")
    except Exception as e:
        await wait.delete()
        logger.error(f"Repeat recipe error: {e}", exc_info=True)
        await c.answer("❌ Ошибка генерации", show_alert=True)

async def handle_clear_my_history(callback: CallbackQuery):
    """Очистка истории пользователя"""
    try:
        user_id = callback.from_user.id
        deleted_count = await database.clear_user_history(user_id)
        
        if deleted_count:
            await callback.answer(f"✅ История очищена ({deleted_count} рецептов удалено)", show_alert=False)
        else:
            await callback.answer("✅ История и так пуста", show_alert=False)
    except Exception as e:
        logger.error(f"Ошибка очистки истории: {e}", exc_info=True)
        await callback.answer("❌ Ошибка очистки истории", show_alert=True)

# --- НОВЫЕ АДМИН ОБРАБОТЧИКИ ---

async def handle_admin_retention(callback: CallbackQuery):
    """Показывает статистику удержания"""
    try:
        text = await admin_service.get_retention_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin retention error: {e}")
        await callback.answer("❌ Ошибка загрузки статистики удержания", show_alert=True)

async def handle_admin_ban_stats(callback: CallbackQuery):
    """Показывает статистику блокировок"""
    try:
        text = await admin_service.get_user_status_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin ban stats error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_admin_logs(callback: CallbackQuery):
    """Показывает логи"""
    try:
        text = await admin_service.get_logs_message(20)
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin logs error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_admin_find_user(callback: CallbackQuery):
    """Начинает процесс поиска пользователя"""
    await callback.message.edit_text(
        "👤 <b>Поиск пользователя</b>\n\n"
        "Введите ID пользователя для получения информации.\n"
        "Пример: <code>123456789</code>\n\n"
        "Или нажмите /user [ID] в чате.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

async def handle_admin_back(callback: CallbackQuery):
    """Возврат в главное меню админки"""
    await callback.message.edit_text("📊 Админ-панель", reply_markup=get_admin_keyboard())
    await callback.answer()

async def handle_admin_broadcast(callback: CallbackQuery):
    """Начинает процесс рассылки"""
    await callback.message.edit_text(
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Введите сообщение для рассылки всем пользователям.\n"
        "Пример: /broadcast Привет всем! У нас обновление бота!\n\n"
        "Или нажмите /broadcast [сообщение] в чате.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

async def handle_broadcast_confirm(callback: CallbackQuery):
    """Подтверждение и отправка рассылки"""
    user_id = callback.from_user.id
    
    # Получаем текст рассылки из временного хранилища
    broadcast_text = await state_manager.get_broadcast_text(user_id)
    
    if not broadcast_text:
        await callback.answer("❌ Текст рассылки не найден", show_alert=True)
        return
    
    # Получаем список пользователей
    user_ids = await database.get_all_user_ids()
    total_users = len(user_ids)
    
    # Отправляем начальное сообщение
    progress_msg = await callback.message.edit_text(
        f"📢 <b>Начало рассылки...</b>\n\n"
        f"👥 Получателей: {total_users}\n"
        f"📝 Отправка... 0/{total_users}",
        parse_mode="HTML"
    )
    
    success_count = 0
    failed_count = 0
    
    # Отправляем сообщения
    for i, target_user_id in enumerate(user_ids, 1):
        try:
            await callback.bot.send_message(
                chat_id=target_user_id,
                text=broadcast_text,
                parse_mode="HTML"
            )
            success_count += 1
            
            # Обновляем прогресс каждые 10 сообщений
            if i % 10 == 0 or i == total_users:
                await progress_msg.edit_text(
                    f"📢 <b>Рассылка в процессе...</b>\n\n"
                    f"👥 Получателей: {total_users}\n"
                    f"✅ Успешно: {success_count}\n"
                    f"❌ Ошибок: {failed_count}\n"
                    f"📝 Отправлено: {i}/{total_users}",
                    parse_mode="HTML"
                )
            
            # Небольшая задержка для антифлуда
            await asyncio.sleep(0.1)
            
        except Exception as e:
            failed_count += 1
            logger.error(f"Ошибка отправки рассылки пользователю {target_user_id}: {e}")
    
    # Итоговое сообщение
    await progress_msg.edit_text(
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"👥 Всего получателей: {total_users}\n"
        f"✅ Успешно отправлено: {success_count}\n"
        f"❌ Ошибок отправки: {failed_count}\n"
        f"📝 Текст рассылки: {broadcast_text[:100]}...",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    
    logger.info(f"Админ {user_id} выполнил рассылку. Успешно: {success_count}, Ошибок: {failed_count}")
    await callback.answer()

async def handle_broadcast_cancel(callback: CallbackQuery):
    """Отмена рассылки"""
    await callback.message.edit_text(
        "❌ Рассылка отменена",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

# --- СУЩЕСТВУЮЩИЕ АДМИН ОБРАБОТЧИКИ ---

async def handle_admin_stats(callback: CallbackQuery):
    """Показывает статистику с графиками"""
    try:
        text = await admin_service.get_stats_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        await callback.answer("❌ Ошибка загрузки статистики", show_alert=True)

async def handle_admin_top_cooks(callback: CallbackQuery):
    """Показывает топ поваров"""
    try:
        text = await admin_service.get_top_cooks_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin top cooks error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_admin_top_ingredients(callback: CallbackQuery):
    """Показывает топ продуктов"""
    try:
        text = await admin_service.get_top_ingredients_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin top ingredients error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_admin_top_dishes(callback: CallbackQuery):
    """Показывает топ блюд"""
    try:
        text = await admin_service.get_top_dishes_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin top dishes error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_admin_random_fact(callback: CallbackQuery):
    """Показывает случайный факт"""
    try:
        text = await admin_service.get_random_fact_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin random fact error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_admin_users(callback: CallbackQuery):
    """Показывает список пользователей"""
    try:
        text = await admin_service.get_users_list_message(page=1, page_size=20)
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin users list error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# --- REGISTER ---
def register_handlers(dp: Dispatcher):
    # Основные команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_author, Command("author"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_favorites, Command("favorites"))
    dp.message.register(cmd_admin, Command("admin"))
    
    # Новые админ команды
    dp.message.register(cmd_retention, Command("retention"))
    dp.message.register(cmd_user, Command("user"))
    dp.message.register(cmd_ban, Command("ban"))
    dp.message.register(cmd_unban, Command("unban"))
    dp.message.register(cmd_logs, Command("logs"))
    dp.message.register(cmd_broadcast, Command("broadcast"))
    
    # Обработчики сообщений
    dp.message.register(handle_voice, F.voice | F.audio)
    dp.message.register(handle_text, F.text)
    
    # Основные callback обработчики
    dp.callback_query.register(handle_action_cook, F.data == "action_cook")
    dp.callback_query.register(handle_category_selection, F.data.startswith("cat_"))
    dp.callback_query.register(handle_dish_selection, F.data.startswith("dish_"))
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_fav_delete, F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_fav_view, F.data.startswith("fav_") & ~F.data.startswith("fav_add_") & ~F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_history_view, F.data.startswith("history_"))
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
    dp.callback_query.register(handle_back_to_categories, F.data == "back_to_categories")
    dp.callback_query.register(handle_clear_my_history, F.data == "clear_my_history")
    
    # Новые админ callback обработчики
    dp.callback_query.register(handle_admin_retention, F.data == "admin_retention")
    dp.callback_query.register(handle_admin_ban_stats, F.data == "admin_ban_stats")
    dp.callback_query.register(handle_admin_logs, F.data == "admin_logs")
    dp.callback_query.register(handle_admin_find_user, F.data == "admin_find_user")
    dp.callback_query.register(handle_admin_back, F.data == "admin_back")
    dp.callback_query.register(handle_admin_broadcast, F.data == "admin_broadcast")
    dp.callback_query.register(handle_broadcast_confirm, F.data == "broadcast_confirm")
    dp.callback_query.register(handle_broadcast_cancel, F.data == "broadcast_cancel")
    
    # Существующие админ callback обработчики
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_users, F.data == "admin_users")
    dp.callback_query.register(handle_admin_top_cooks, F.data == "admin_top_cooks")
    dp.callback_query.register(handle_admin_top_ingredients, F.data == "admin_top_ingredients")
    dp.callback_query.register(handle_admin_top_dishes, F.data == "admin_top_dishes")
    dp.callback_query.register(handle_admin_random_fact, F.data == "admin_random_fact")
