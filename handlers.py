import os
import io
import logging
import asyncio
import re
from aiogram import Dispatcher, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery
)

from groq_service import groq_service
from state_manager import state_manager
from database import db as database
from admin_service import admin_service
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

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

def normalize_ingredients(text: str) -> str:
    """Нормализует список продуктов"""
    text = text.strip()
    if ',' not in text and ' ' in text:
        words = text.split()
        if len(words) > 1:
            return ", ".join(words)
    return text

def extract_dish_name(text: str) -> str:
    """Извлекает название блюда из запроса"""
    text = text.lower()
    
    # Удаляем служебные слова
    patterns_to_remove = [
        'рецепт', 'рецепта', 'рецепту', 'рецептом', 'рецепты',
        'приготовить', 'приготовления', 'приготовлению', 'приготовь', 'приготовьте',
        'сделать', 'сделай', 'сделайте', 'сделаю', 'сделаем',
        'дай', 'дайте', 'хочу', 'хотел', 'хотела', 'хотело', 'хотели',
        'можно', 'мне', 'надо', 'нужно', 'надо бы',
        'как', 'какой', 'какая', 'какое', 'какие',
        'что', 'чего', 'чему', 'чем',
        'пожалуйста', 'пожалуй', 'будь', 'будьте'
    ]
    
    dish_name = text
    for pattern in patterns_to_remove:
        dish_name = re.sub(r'\b' + re.escape(pattern) + r'\b', ' ', dish_name)
    
    dish_name = dish_name.strip(' ,.!?;:-—–')
    dish_name = ' '.join(dish_name.split())
    
    # Если ничего не осталось, берем последние слова
    if not dish_name or len(dish_name) < 2:
        words = text.split()
        if len(words) > 1:
            dish_name = ' '.join(words[-min(3, len(words)):])
    
    if dish_name and dish_name[0].islower():
        dish_name = dish_name[0].upper() + dish_name[1:]
    
    return dish_name

async def classify_intent_groq(text: str) -> str:
    """Классифицирует интент через Groq"""
    try:
        safe_text = text[:200]  # Ограничиваем длину
        
        system_prompt = """Ты классифицируешь кулинарные запросы. Определи тип запроса и верни ТОЛЬКО одно слово из списка:
        
        Типы запросов:
        1. "ingredients" - пользователь перечисляет продукты (например: "яйца, молоко, сыр", "у меня есть картошка и мясо")
        2. "recipe" - просит конкретный рецепт (например: "рецепт борща", "как приготовить пиццу", "хочу сделать омлет")
        3. "comparison" - сравнивает продукты или блюда (например: "что лучше курица или рыба", "сравни гречку и овсянку")
        4. "advice" - просит совет по готовке (например: "как правильно варить яйца", "совет по приготовлению стейка")
        5. "nutrition" - вопросы о питании (например: "польза гречки", "сколько белка в курице", "диетические рецепты")
        6. "unknown" - не понятно или не относится к кулинарии
        
        ВЕРНИ ТОЛЬКО ОДНО СЛОВО БЕЗ КАВЫЧЕК И ДОПОЛНИТЕЛЬНОГО ТЕКСТА."""
        
        user_prompt = f"Запрос пользователя: {safe_text}\n\nТип запроса:"
        
        response = await groq_service._send_groq_request(
            system_prompt=system_prompt,
            user_text=user_prompt,
            task_type="general_cooking",  # Используем существующий тип
            temperature=0.3,
            max_tokens=50
        )
        
        # Очищаем ответ
        intent = response.strip().lower()
        valid_intents = ["ingredients", "recipe", "comparison", "advice", "nutrition", "unknown"]
        
        # Проверяем, что ответ соответствует одному из валидных интентов
        for valid in valid_intents:
            if valid in intent:
                return valid
        
        # Fallback: эвристическая классификация
        text_lower = text.lower()
        
        # 1. Список продуктов (приоритет)
        if ',' in text_lower or ' и ' in text_lower or ' с ' in text_lower:
            if not any(q in text_lower for q in ['?', 'как', 'что', 'почему']):
                return "ingredients"
        
        # 2. Рецепт
        recipe_words = ['рецепт', 'приготовь', 'сделай', 'как приготовить', 'хочу приготовить']
        if any(word in text_lower for word in recipe_words):
            return "recipe"
        
        # 3. Сравнение
        comparison_words = ['или', 'больше', 'меньше', 'сравни', 'что лучше', 'что полезнее']
        if any(word in text_lower for word in comparison_words):
            return "comparison"
        
        # 4. Совет
        advice_words = ['как правильно', 'совет', 'лайфхак', 'секрет', 'правильно ли']
        if any(word in text_lower for word in advice_words):
            return "advice"
        
        # 5. Питание
        nutrition_words = ['белок', 'жир', 'углевод', 'калори', 'витамин', 'польза', 'диет']
        if any(word in text_lower for word in nutrition_words):
            return "nutrition"
        
        return "unknown"
        
    except Exception as e:
        logger.error(f"Ошибка классификации интента: {e}")
        return "unknown"

# --- КЛАВИАТУРЫ ---

def get_confirmation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить продукты", callback_data="action_add_more")],
        [InlineKeyboardButton(text="👨‍🍳 Готовить (Категории)", callback_data="action_cook")]
    ])

def get_categories_keyboard(categories: list):
    builder = []
    row = []
    for cat_key in categories:
        if not isinstance(cat_key, str): 
            continue
        text = CATEGORY_MAP.get(cat_key, cat_key.capitalize())
        row.append(InlineKeyboardButton(text=text, callback_data=f"cat_{cat_key}"))
        if len(row) == 2:
            builder.append(row)
            row = []
    if row: 
        builder.append(row)
    builder.append([InlineKeyboardButton(text="🗑 Сброс", callback_data="restart")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_dishes_keyboard(dishes_list: list, category: str):
    builder = []
    for i, dish in enumerate(dishes_list):
        btn_text = f"{i+1}. {dish['name'][:30]}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"dish_{i}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_recipe_keyboard(recipe_id: int = None):
    buttons = []
    if recipe_id:
        buttons.append([InlineKeyboardButton(text="❤️ В избранное", callback_data=f"fav_add_{recipe_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Вернуться к категориям", callback_data="back_to_categories")])
    buttons.append([InlineKeyboardButton(text="🆕 Новый набор продуктов", callback_data="restart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_recipe_keyboard_favorite(recipe_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ Удалить из избранного", callback_data=f"fav_delete_{recipe_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])

def get_stats_keyboard(user_id: int, history_recipes: list):
    buttons = []
    for recipe in history_recipes[:5]:
        buttons.append([InlineKeyboardButton(
            text=f"📝 {recipe['dish_name'][:30]}", 
            callback_data=f"history_{recipe['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="🗑 Очистить историю", callback_data="clear_my_history")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])

def get_favorites_keyboard(favorites: list):
    buttons = []
    for recipe in favorites:
        buttons.append([InlineKeyboardButton(
            text=recipe['dish_name'][:40], 
            callback_data=f"fav_{recipe['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_broadcast_confirmation_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить (Фон)", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")]
    ])

# --- КОМАНДЫ ---

async def cmd_start(message: Message):
    user_id = message.from_user.id
    await database.get_or_create_user(
        user_id, 
        message.from_user.username, 
        message.from_user.first_name, 
        message.from_user.last_name
    )
    await state_manager.clear_session(user_id)
    await message.answer(
        "👋 <b>Привет! Я ЧёПоесть Бот!</b>\n\n"
        "🎤 <b>Можешь отправить голосовое сообщение!</b>\n"
        "🥕 Просто перечисли продукты: <i>яйца, молоко, сыр</i>\n"
        "🍲 Или попроси рецепт: <i>как сварить борщ</i>\n"
        "🥗 Спроси про питание: <i>польза гречки</i>",
        parse_mode="HTML"
    )

async def cmd_admin(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("📊 Админ-панель", reply_markup=get_admin_keyboard())

async def cmd_stats(message: Message):
    user_id = message.from_user.id
    stats = await database.get_user_stats(user_id)
    history = await database.get_user_recipes(user_id)
    await message.answer(
        f"📊 Рецептов: {stats['total_recipes']}\n❤️ Избранное: {stats['favorites']}", 
        reply_markup=get_stats_keyboard(user_id, history)
    )

async def cmd_favorites(message: Message):
    favs = await database.get_user_favorites(message.from_user.id)
    if not favs:
        await message.answer("❤️ Пусто")
        return
    await message.answer("❤️ Избранное:", reply_markup=get_favorites_keyboard(favs))

async def cmd_broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS: 
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /broadcast [текст]")
        return
    
    await state_manager.set_broadcast_text(message.from_user.id, args[1])
    await message.answer(
        f"Отправить всем?\n\n{args[1]}", 
        reply_markup=get_broadcast_confirmation_keyboard()
    )

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Классификация интента
    intent = await classify_intent_groq(text)
    logger.info(f"User {user_id}: '{text}' -> Intent: {intent}")
    
    if intent == "ingredients":
        await process_products_input(message, user_id, text)
    elif intent == "recipe":
        await handle_recipe_request(message, text)
    elif intent == "comparison":
        await handle_comparison_request(message, text)
    elif intent == "advice":
        await handle_cooking_advice(message, text)
    elif intent == "nutrition":
        await handle_nutrition_request(message, text)
    else:
        # General chat или fallback
        await message.answer(
            "🤔 Не совсем понял. Перечислите продукты или задайте вопрос о еде.\n\n"
            "Примеры:\n"
            "• <i>яйца, молоко, хлеб</i>\n"
            "• <i>рецепт борща</i>\n"
            "• <i>что полезнее: курица или рыба?</i>\n"
            "• <i>как правильно варить яйца?</i>\n"
            "• <i>польза гречки для здоровья</i>",
            parse_mode="HTML"
        )

async def handle_voice(message: Message):
    """Обработка голосовых сообщений через Whisper"""
    user_id = message.from_user.id
    processing_msg = await message.answer("🎧 Слушаю...")
    
    try:
        # Скачиваем файл
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file = await message.bot.get_file(file_id)
        file_bytes = io.BytesIO()
        await message.bot.download_file(file.file_path, file_bytes)
        
        # Транскрибация
        text = await groq_service.transcribe_voice(file_bytes.getvalue())
        await processing_msg.delete()
        
        if text:
            await message.answer(f"🗣 <b>Вы сказали:</b>\n<i>{text}</i>", parse_mode="HTML")
            # Передаем распознанный текст в текстовый обработчик
            msg_copy = message.model_copy(update={"text": text})
            await handle_text(msg_copy)
        else:
            await message.answer("❌ Не удалось разобрать слова.")
            
    except Exception as e:
        await processing_msg.delete()
        logger.error(f"Voice error: {e}")
        await message.answer("❌ Ошибка обработки голоса.")

async def process_products_input(message: Message, user_id: int, text: str):
    """Обработка списка продуктов"""
    normalized = normalize_ingredients(text)
    await state_manager.add_products(user_id, normalized)
    current = await state_manager.get_products(user_id)
    await message.answer(
        f"✅ Продукты: <b>{current}</b>\nЧто дальше?", 
        reply_markup=get_confirmation_keyboard(), 
        parse_mode="HTML"
    )

async def handle_recipe_request(message: Message, text: str):
    """Обработка запроса рецепта"""
    dish_name = extract_dish_name(text)
    if not dish_name or len(dish_name) < 2:
        await message.answer("🍽️ <b>Уточните, пожалуйста</b>\n\nНапишите, рецепт какого блюда вас интересует?\nПример: <i>рецепт борща</i>, <i>как приготовить пиццу</i>, <i>хочу сделать омлет</i>", parse_mode="HTML")
        return
    
    wait = await message.answer(f"👨‍🍳 Придумываю рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
    recipe = await groq_service.generate_freestyle_recipe(dish_name)
    await wait.delete()
    recipe_id = await state_manager.save_recipe_to_history(message.from_user.id, dish_name, recipe)
    await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")

async def handle_comparison_request(message: Message, text: str):
    """Обработка запроса сравнения"""
    wait = await message.answer("🔍 Сравниваю...")
    resp = await groq_service.generate_comparison(text)
    await wait.delete()
    await message.answer(resp, parse_mode="HTML")

async def handle_cooking_advice(message: Message, text: str):
    """Обработка запроса совета"""
    wait = await message.answer("👨‍🍳 Ищу совет...")
    resp = await groq_service.generate_cooking_advice(text)
    await wait.delete()
    await message.answer(resp, parse_mode="HTML")

async def handle_nutrition_request(message: Message, text: str):
    """Обработка запроса о питании"""
    wait = await message.answer("🥗 Считаю калории...")
    resp = await groq_service.generate_nutrition_info(text)
    await wait.delete()
    await message.answer(resp, parse_mode="HTML")

# --- CALLBACK ОБРАБОТЧИКИ ---

async def handle_action_cook(c: CallbackQuery):
    """Обработка кнопки 'Готовить'"""
    user_id = c.from_user.id
    products = await state_manager.get_products(user_id)
    if not products:
        await c.answer("Сначала добавьте продукты", show_alert=True)
        return
    
    wait = await c.message.edit_text("📊 Анализирую продукты...")
    cats = await groq_service.analyze_categories(products)
    await state_manager.set_categories(user_id, cats)
    await wait.edit_text(
        f"📦 Продукты: {products}\n\nВыберите категорию:", 
        reply_markup=get_categories_keyboard(cats)
    )

async def handle_category_selection(c: CallbackQuery):
    """Обработка выбора категории"""
    user_id = c.from_user.id
    cat = c.data.replace("cat_", "")
    
    await state_manager.set_category(user_id, cat)
    products = await state_manager.get_products(user_id)
    
    wait = await c.message.edit_text(f"🍽️ Ищу блюда ({CATEGORY_MAP.get(cat, cat)})...")
    dishes = await groq_service.generate_dishes_list(products, cat)
    await state_manager.set_dishes(user_id, dishes)
    
    await wait.edit_text("Выберите блюдо:", reply_markup=get_dishes_keyboard(dishes, cat))

async def handle_dish_selection(c: CallbackQuery):
    """Обработка выбора блюда"""
    user_id = c.from_user.id
    idx = int(c.data.replace("dish_", ""))
    
    dishes = await state_manager.get_dishes(user_id)
    if idx >= len(dishes):
        await c.answer("Блюдо не найдено", show_alert=True)
        return
    
    dish = dishes[idx]
    products = await state_manager.get_products(user_id)
    
    wait = await c.message.edit_text(f"👨‍🍳 Готовлю рецепт: <b>{dish['name']}</b>...", parse_mode="HTML")
    recipe = await groq_service.generate_recipe(dish['name'], products)
    await wait.delete()
    
    recipe_id = await state_manager.save_recipe_to_history(user_id, dish['name'], recipe)
    await c.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
    await c.answer()

# --- АСИНХРОННАЯ РАССЫЛКА ---

async def broadcast_worker(bot: Bot, user_ids: list, text: str, admin_id: int):
    """Фоновая задача рассылки"""
    success = 0
    failed = 0
    total = len(user_ids)
    
    # Отчет о начале
    try:
        status_msg = await bot.send_message(admin_id, f"🚀 Рассылка началась: 0/{total}")
    except:
        status_msg = None
    
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)  # Лимит ~20 сообщений в секунду
        except Exception as e:
            failed += 1
            logger.debug(f"Ошибка отправки пользователю {uid}: {e}")
        
        # Обновляем статус каждые 50 сообщений
        if i % 50 == 0 and status_msg:
            try:
                await status_msg.edit_text(f"🚀 Рассылка: {i}/{total}\n✅ {success} ❌ {failed}")
            except:
                pass
    
    # Финальный отчет
    try:
        await bot.send_message(
            admin_id, 
            f"🏁 <b>Рассылка завершена!</b>\n\n"
            f"📊 Всего пользователей: {total}\n"
            f"✅ Успешно: {success}\n"
            f"❌ Ошибок: {failed}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки финального отчета: {e}")

async def handle_broadcast_confirm(c: CallbackQuery):
    """Подтверждение рассылки"""
    user_id = c.from_user.id
    text = await state_manager.get_broadcast_text(user_id)
    
    if not text:
        await c.answer("Ошибка: текст рассылки не найден", show_alert=True)
        return
    
    user_ids = await database.get_all_user_ids()
    await c.message.edit_text(f"🚀 Рассылка запущена на {len(user_ids)} пользователей.")
    
    # Запуск в фоне (Non-blocking)
    asyncio.create_task(broadcast_worker(c.bot, user_ids, text, user_id))
    await c.answer()

async def handle_broadcast_cancel(c: CallbackQuery):
    """Отмена рассылки"""
    await c.message.edit_text("❌ Рассылка отменена")

# --- ПРОСТЫЕ ОБРАБОТЧИКИ ---

async def handle_restart(c: CallbackQuery):
    """Сброс сессии"""
    await state_manager.clear_session(c.from_user.id)
    await c.message.edit_text("🔄 Сброшено")
    await c.answer()

async def handle_delete_msg(c: CallbackQuery):
    """Удаление сообщения"""
    try:
        await c.message.delete()
    except:
        pass

async def handle_action_add_more(c: CallbackQuery):
    """Добавление продуктов"""
    await c.message.edit_text("✏️ Пишите еще продукты:")

async def handle_back_to_categories(c: CallbackQuery):
    """Возврат к категориям"""
    await handle_action_cook(c)

async def handle_fav_add(c: CallbackQuery):
    """Добавление в избранное"""
    rid = int(c.data.replace("fav_add_", ""))
    user_id = c.from_user.id
    
    # Проверяем, не добавлено ли уже
    already_fav = await database.is_recipe_favorite(user_id, rid)
    if already_fav:
        await c.answer("❤️ Уже в избранном!", show_alert=False)
        return
    
    if await database.add_to_favorites(user_id, rid):
        await c.answer("❤️ Добавлено в избранное!", show_alert=False)
    else:
        await c.answer("❌ Не удалось добавить", show_alert=True)

async def handle_fav_view(c: CallbackQuery):
    """Просмотр избранного"""
    rid = int(c.data.replace("fav_", ""))
    user_id = c.from_user.id
    
    recipe = await database.get_recipe_by_id(user_id, rid)
    if recipe:
        await c.message.edit_text(
            recipe['recipe_text'], 
            reply_markup=get_recipe_keyboard_favorite(rid), 
            parse_mode="HTML"
        )
        await c.answer()
    else:
        await c.answer("❌ Рецепт не найден", show_alert=True)

async def handle_fav_delete(c: CallbackQuery):
    """Удаление из избранного"""
    rid = int(c.data.replace("fav_delete_", ""))
    user_id = c.from_user.id
    
    await database.remove_from_favorites(user_id, rid)
    await c.message.edit_text(
        "🗑 Удалено из избранного",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Закрыть", callback_data="delete_msg")]
        ])
    )
    await c.answer("✅ Удалено!")

async def handle_history_view(c: CallbackQuery):
    """Просмотр истории"""
    rid = int(c.data.replace("history_", ""))
    user_id = c.from_user.id
    
    recipe = await database.get_recipe_by_id(user_id, rid)
    if recipe:
        await c.message.edit_text(
            recipe['recipe_text'], 
            reply_markup=get_recipe_keyboard(rid), 
            parse_mode="HTML"
        )
        await c.answer()
    else:
        await c.answer("❌ Рецепт не найден", show_alert=True)

async def handle_clear_my_history(c: CallbackQuery):
    """Очистка истории"""
    deleted = await database.clear_user_history(c.from_user.id)
    if deleted:
        await c.answer(f"✅ История очищена ({deleted} рецептов удалено)", show_alert=False)
    else:
        await c.answer("✅ История и так пуста", show_alert=False)

# --- АДМИН ОБРАБОТЧИКИ ---

async def handle_admin_stats(callback: CallbackQuery):
    """Показывает статистику"""
    try:
        text = await admin_service.get_stats_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        await callback.answer("❌ Ошибка загрузки статистики", show_alert=True)

async def handle_admin_users(callback: CallbackQuery):
    """Показывает список пользователей"""
    try:
        text = await admin_service.get_users_list_message(page=1, page_size=20)
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Admin users error: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# --- РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ---

def register_handlers(dp: Dispatcher):
    # Основные команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_admin, Command("admin"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_favorites, Command("favorites"))
    dp.message.register(cmd_broadcast, Command("broadcast"))
    
    # Обработчики сообщений
    dp.message.register(handle_voice, F.voice | F.audio)
    dp.message.register(handle_text, F.text)
    
    # Основные callback обработчики
    dp.callback_query.register(handle_action_cook, F.data == "action_cook")
    dp.callback_query.register(handle_category_selection, F.data.startswith("cat_"))
    dp.callback_query.register(handle_dish_selection, F.data.startswith("dish_"))
    dp.callback_query.register(handle_broadcast_confirm, F.data == "broadcast_confirm")
    dp.callback_query.register(handle_broadcast_cancel, F.data == "broadcast_cancel")
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
    dp.callback_query.register(handle_back_to_categories, F.data == "back_to_categories")
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_fav_view, F.data.startswith("fav_"))
    dp.callback_query.register(handle_fav_delete, F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_history_view, F.data.startswith("history_"))
    dp.callback_query.register(handle_clear_my_history, F.data == "clear_my_history")
    
    # Админские обработчики
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_users, F.data == "admin_users")
