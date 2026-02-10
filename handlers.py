--- START OF FILE handlers.py ---

import os
import io
import logging
import asyncio
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

CATEGORY_MAP = {
    "breakfast": "🍳 Завтраки", "soup": "🍲 Супы", "main": "🍝 Вторые блюда",
    "salad": "🥗 Салаты", "snack": "🥪 Закуски", "dessert": "🍰 Десерты",
    "drink": "🥤 Напитки", "mix": "🍱 Комплексный обед", "sauce": "🍾 Соусы"
}

def normalize_ingredients(text: str) -> str:
    text = text.strip()
    if ',' not in text and ' ' in text:
        words = text.split()
        if len(words) > 1: return ", ".join(words)
    return text

def extract_dish_name(text: str) -> str:
    text = text.lower()
    remove = ['рецепт', 'приготовь', 'как сделать', 'хочу', 'дай', 'мне', 'пожалуйста']
    for word in remove:
        text = text.replace(word, '')
    return text.strip().capitalize()

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
        buttons.append([InlineKeyboardButton(text=f"📝 {recipe['dish_name'][:30]}", callback_data=f"history_{recipe['id']}")])
    buttons.append([InlineKeyboardButton(text="🗑 Очистить историю", callback_data="clear_my_history")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить (Фон)", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")]
    ])

# --- COMMANDS ---
async def cmd_start(message: Message):
    user_id = message.from_user.id
    await database.get_or_create_user(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
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
    await message.answer(f"📊 Рецептов: {stats['total_recipes']}\n❤️ Избранное: {stats['favorites']}", reply_markup=get_stats_keyboard(user_id, history))

async def cmd_favorites(message: Message):
    favs = await database.get_user_favorites(message.from_user.id)
    if not favs:
        await message.answer("❤️ Пусто")
        return
    await message.answer("❤️ Избранное:", reply_markup=get_favorites_keyboard(favs))

async def cmd_broadcast(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("/broadcast [текст]")
        return
    await state_manager.set_broadcast_text(message.from_user.id, args[1])
    await message.answer(f"Отправить всем?\n\n{args[1]}", reply_markup=get_broadcast_confirmation_keyboard())

# --- HANDLERS ---

async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # 1. Классификация интента через Groq
    intent = await groq_service.classify_intent(text)
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
        # General chat or fallback
        await message.answer("🤔 Не совсем понял. Перечислите продукты или задайте вопрос о еде.")

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
    normalized = normalize_ingredients(text)
    await state_manager.add_products(user_id, normalized)
    current = await state_manager.get_products(user_id)
    await message.answer(f"✅ Продукты: <b>{current}</b>\nЧто дальше?", reply_markup=get_confirmation_keyboard(), parse_mode="HTML")

async def handle_recipe_request(message: Message, text: str):
    dish_name = extract_dish_name(text)
    wait = await message.answer(f"👨‍🍳 Придумываю рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
    recipe = await groq_service.generate_freestyle_recipe(dish_name)
    await wait.delete()
    recipe_id = await state_manager.save_recipe_to_history(message.from_user.id, dish_name, recipe)
    await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")

async def handle_comparison_request(message: Message, text: str):
    wait = await message.answer("🔍 Сравниваю...")
    resp = await groq_service.generate_comparison(text)
    await wait.delete()
    await message.answer(resp, parse_mode="HTML")

async def handle_cooking_advice(message: Message, text: str):
    wait = await message.answer("👨‍🍳 Ищу совет...")
    resp = await groq_service.generate_cooking_advice(text)
    await wait.delete()
    await message.answer(resp, parse_mode="HTML")

async def handle_nutrition_request(message: Message, text: str):
    wait = await message.answer("🥗 Считаю калории...")
    resp = await groq_service.generate_nutrition_info(text)
    await wait.delete()
    await message.answer(resp, parse_mode="HTML")

# --- CALLBACKS ---

async def handle_action_cook(c: CallbackQuery):
    products = await state_manager.get_products(c.from_user.id)
    if not products:
        await c.answer("Сначала добавьте продукты")
        return
    wait = await c.message.edit_text("📊 Анализирую...")
    cats = await groq_service.analyze_categories(products)
    await state_manager.set_categories(c.from_user.id, cats)
    await wait.edit_text(f"📦 Продукты: {products}\nВыберите категорию:", reply_markup=get_categories_keyboard(cats))

async def handle_category_selection(c: CallbackQuery):
    cat = c.data.replace("cat_", "")
    await state_manager.set_category(c.from_user.id, cat)
    products = await state_manager.get_products(c.from_user.id)
    wait = await c.message.edit_text(f"🍽️ Ищу блюда ({CATEGORY_MAP.get(cat)})...")
    dishes = await groq_service.generate_dishes_list(products, cat)
    await state_manager.set_dishes(c.from_user.id, dishes)
    await wait.edit_text("Выберите блюдо:", reply_markup=get_dishes_keyboard(dishes, cat))

async def handle_dish_selection(c: CallbackQuery):
    idx = int(c.data.replace("dish_", ""))
    dishes = await state_manager.get_dishes(c.from_user.id)
    dish = dishes[idx]
    products = await state_manager.get_products(c.from_user.id)
    wait = await c.message.edit_text(f"👨‍🍳 Готовлю рецепт: <b>{dish['name']}</b>...", parse_mode="HTML")
    recipe = await groq_service.generate_recipe(dish['name'], products)
    await wait.delete()
    recipe_id = await state_manager.save_recipe_to_history(c.from_user.id, dish['name'], recipe)
    await c.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")

# --- АСИНХРОННАЯ РАССЫЛКА ---

async def broadcast_worker(bot: Bot, user_ids: list, text: str, admin_id: int):
    """Фоновая задача рассылки"""
    success = 0
    failed = 0
    total = len(user_ids)
    
    # Отчет о начале
    status_msg = await bot.send_message(admin_id, f"🚀 Рассылка началась: 0/{total}")
    
    for i, uid in enumerate(user_ids):
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05) # Лимит 20-30 msg/sec
        except Exception:
            failed += 1
        
        # Обновляем статус каждые 50 сообщений
        if i % 50 == 0:
            try:
                await status_msg.edit_text(f"🚀 Рассылка: {i}/{total}\n✅ {success} ❌ {failed}")
            except: pass

    await bot.send_message(admin_id, f"🏁 <b>Рассылка завершена!</b>\n\n✅ Успешно: {success}\n❌ Ошибок: {failed}", parse_mode="HTML")

async def handle_broadcast_confirm(c: CallbackQuery):
    text = await state_manager.get_broadcast_text(c.from_user.id)
    if not text:
        await c.answer("Ошибка текста")
        return
    
    user_ids = await database.get_all_user_ids()
    await c.message.edit_text(f"🚀 Рассылка запущена на {len(user_ids)} пользователей.")
    
    # ЗАПУСК В ФОНЕ (Non-blocking)
    asyncio.create_task(broadcast_worker(c.bot, user_ids, text, c.from_user.id))
    await c.answer()

async def handle_broadcast_cancel(c: CallbackQuery):
    await c.message.edit_text("❌ Отменено")

# --- Остальные обработчики (fav, history, restart) ---
async def handle_restart(c: CallbackQuery):
    await state_manager.clear_session(c.from_user.id)
    await c.message.edit_text("🔄 Сброшено")

async def handle_delete_msg(c: CallbackQuery):
    await c.message.delete()

async def handle_action_add_more(c: CallbackQuery):
    await c.message.edit_text("✏️ Пишите еще продукты:")

async def handle_back_to_categories(c: CallbackQuery):
    await handle_action_cook(c)

async def handle_fav_add(c: CallbackQuery):
    rid = int(c.data.replace("fav_add_", ""))
    if await database.add_to_favorites(c.from_user.id, rid):
        await c.answer("❤️ Добавлено!")
    else:
        await c.answer("Уже есть или ошибка")

async def handle_fav_view(c: CallbackQuery):
    rid = int(c.data.replace("fav_", ""))
    r = await database.get_recipe_by_id(c.from_user.id, rid)
    if r: await c.message.edit_text(r['recipe_text'], reply_markup=get_recipe_keyboard_favorite(rid), parse_mode="HTML")

async def handle_fav_delete(c: CallbackQuery):
    rid = int(c.data.replace("fav_delete_", ""))
    await database.remove_from_favorites(c.from_user.id, rid)
    await c.message.edit_text("🗑 Удалено", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Закрыть", callback_data="delete_msg")]]))

async def handle_history_view(c: CallbackQuery):
    rid = int(c.data.replace("history_", ""))
    r = await database.get_recipe_by_id(c.from_user.id, rid)
    if r: await c.message.edit_text(r['recipe_text'], reply_markup=get_recipe_keyboard(rid), parse_mode="HTML")

async def handle_clear_my_history(c: CallbackQuery):
    await database.clear_user_history(c.from_user.id)
    await c.answer("История очищена")

# --- ADMIN HANDLERS (Реализация) ---

async def handle_admin_stats(c: CallbackQuery):
    text = await admin_service.get_stats_message()
    await c.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

async def handle_admin_users(c: CallbackQuery):
    text = await admin_service.get_users_list_message()
    await c.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

async def handle_admin_top_cooks(c: CallbackQuery):
    text = await admin_service.get_top_cooks_message()
    await c.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

async def handle_admin_top_ingredients(c: CallbackQuery):
    text = await admin_service.get_top_ingredients_message()
    await c.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

async def handle_admin_top_dishes(c: CallbackQuery):
    text = await admin_service.get_top_dishes_message()
    await c.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

async def handle_admin_random_fact(c: CallbackQuery):
    text = await admin_service.get_random_fact_message()
    await c.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

# --- REGISTER ---

def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_admin, Command("admin"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_favorites, Command("favorites"))
    dp.message.register(cmd_broadcast, Command("broadcast"))
    
    dp.message.register(handle_voice, F.voice | F.audio)
    dp.message.register(handle_text, F.text)
    
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
    
    # Админские
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_users, F.data == "admin_users")
    dp.callback_query.register(handle_admin_top_cooks, F.data == "admin_top_cooks")
    dp.callback_query.register(handle_admin_top_ingredients, F.data == "admin_top_ingredients")
    dp.callback_query.register(handle_admin_top_dishes, F.data == "admin_top_dishes")
    dp.callback_query.register(handle_admin_random_fact, F.data == "admin_random_fact")
