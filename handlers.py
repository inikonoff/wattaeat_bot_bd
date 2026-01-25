import os
import io
import logging
import hashlib
import time
import asyncio
import aiohttp
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
from storage_service import storage_service
from image_service import image_service
from card_generator import recipe_card_generator
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

def get_dishes_keyboard(dishes_list: list):
    builder = []
    for i, dish in enumerate(dishes_list):
        btn_text = f"{dish['name'][:40]}"
        builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"dish_{i}")])
    builder.append([InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=builder)

def get_recipe_keyboard(recipe_id: int = None, has_image: bool = False, remaining_images: int = 0):
    buttons = []
    if remaining_images > 0 or remaining_images == -1:
        limit_text = "∞" if remaining_images == -1 else remaining_images
        buttons.append([InlineKeyboardButton(text=f"🎨 Сгенерировать фото ({limit_text})", callback_data="gen_image")])
    else:
        buttons.append([InlineKeyboardButton(text="🎨 Лимит исчерпан", callback_data="limit_exceeded")])
    
    buttons.append([InlineKeyboardButton(text="📤 Поделиться рецептом", callback_data="create_card")])
    if recipe_id:
        buttons.append([InlineKeyboardButton(text="❤️ В избранное", callback_data=f"fav_add_{recipe_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔄 Другой вариант", callback_data="repeat_recipe")])
    buttons.append([InlineKeyboardButton(text="⬅️ Вернуться к категориям", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить мою историю", callback_data="clear_my_history")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
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

# --- COMMANDS ---

async def cmd_start(message: Message):
    user_id = message.from_user.id
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
            "Напишите список продуктов или отправьте голосовое сообщение.\n"
            "Также можно спросить конкретный рецепт, например: <i>'Дай рецепт пиццы'</i>"
        )
        await message.answer(text, parse_mode="HTML")
    except:
        await message.answer("👋 Привет!")

async def cmd_author(message: Message):
    await message.answer("👨‍💻 Автор бота: @inikonoff")

async def cmd_stats(message: Message):
    try:
        user_id = message.from_user.id
        user_recipes = await database.get_user_recipes(user_id, limit=5)
        recipes_text = "\n".join([f"• {r['dish_name']}" for r in user_recipes]) if user_recipes else "Нет рецептов"
        can_generate, remaining, limit = await database.check_image_limit(user_id)
        limit_text = f"{remaining}/{limit}" if limit != -1 else "∞"
        text = f"📊 <b>Статистика:</b>\n\n📝 Рецептов: <b>{len(user_recipes)}</b>\n🎨 Лимит фото: <b>{limit_text}</b>\n\n<b>История:</b>\n{recipes_text}"
        await message.answer(text, reply_markup=get_stats_keyboard(), parse_mode="HTML")
    except: await message.answer("❌ Ошибка")

async def cmd_favorites(message: Message):
    try:
        favs = await database.get_user_favorites(message.from_user.id)
        if not favs:
            await message.answer("❤️ Пусто в избранном")
            return
        await message.answer(f"❤️ <b>Избранное ({len(favs)}):</b>", reply_markup=get_favorites_keyboard(favs), parse_mode="HTML")
    except: await message.answer("❌ Ошибка")

async def cmd_admin(message: Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("📊 Админка", reply_markup=get_admin_keyboard())

# --- TEXT & VOICE HANDLERS ---

async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if text.lower().startswith("дай рецепт") or text.lower().startswith("рецепт"):
        await handle_direct_recipe(message, text)
    else:
        await process_products_input(message, user_id, text)

async def handle_direct_recipe(message: Message, text: str):
    """Прямой поиск рецепта по названию"""
    user_id = message.from_user.id
    # Очищаем "дай рецепт" и пробелы
    dish_name = text.lower().replace("дай рецепт", "").replace("рецепт", "").strip()
    
    if len(dish_name) < 2:
        await message.answer("Напишите название блюда, например: <i>Дай рецепт борща</i>", parse_mode="HTML")
        return

    wait = await message.answer(f"⚡️ Ищу рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
    try:
        recipe = await groq_service.generate_freestyle_recipe(dish_name)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_name)
        await state_manager.set_state(user_id, "recipe_sent")
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        can_generate, remaining, limit = await database.check_image_limit(user_id)
        
        await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id, False, remaining), parse_mode="HTML")
    except Exception as e:
        await wait.delete()
        logger.error(f"Recipe error: {e}")
        await message.answer("❌ Не удалось придумать рецепт.")

async def process_products_input(message: Message, user_id: int, products_text: str):
    try:
        await state_manager.add_products(user_id, products_text)
        current = await state_manager.get_products(user_id)
        await message.answer(f"✅ Продукты: <b>{current}</b>\n\nЧто делаем?", reply_markup=get_confirmation_keyboard(), parse_mode="HTML")
    except: await message.answer("❌ Ошибка")

async def handle_voice(message: Message):
    user_id = message.from_user.id
    processing_msg = await message.answer("🎧 Распознаю...")
    try:
        file = await message.bot.get_file(message.voice.file_id if message.voice else message.audio.file_id)
        buffer = io.BytesIO()
        await message.bot.download_file(file.file_path, buffer)
        
        text = await groq_service.transcribe_voice(buffer.getvalue())
        await processing_msg.delete()
        
        if "дай рецепт" in text.lower() or "рецепт" in text.lower():
            await handle_direct_recipe(message, text)
        else:
            await process_products_input(message, user_id, text)
    except:
        await processing_msg.delete()
        await message.answer("❌ Не удалось распознать")

# --- CALLBACK HANDLERS ---

async def handle_action_cook(callback: CallbackQuery):
    user_id = callback.from_user.id
    products = await state_manager.get_products(user_id)
    if not products:
        await callback.answer("❌ Нет продуктов", show_alert=False)
        return
    wait = await callback.message.edit_text("🔍 Анализирую продукты...")
    try:
        categories = await groq_service.analyze_categories(products)
        await wait.edit_text(f"✅ Продукты: <b>{products}</b>\n\n🍽️ <b>Категория:</b>", reply_markup=get_categories_keyboard(categories), parse_mode="HTML")
    except: await wait.edit_text("❌ Ошибка анализа")

async def handle_category_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    category = callback.data.replace("cat_", "")
    products = await state_manager.get_products(user_id)
    wait = await callback.message.edit_text(f"🔍 Ищу рецепты ({category})...")
    dishes = await groq_service.generate_dishes_list(products, category)
    await state_manager.set_dishes_list(user_id, dishes)
    await wait.edit_text("🍽️ Выберите блюдо:", reply_markup=get_dishes_keyboard(dishes))

async def handle_dish_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    idx = int(callback.data.replace("dish_", ""))
    dishes = await state_manager.get_dishes_list(user_id)
    selected = dishes[idx]
    products = await state_manager.get_products(user_id)
    
    wait = await callback.message.edit_text(f"⚡️ Пишу рецепт: <b>{selected['name']}</b>...", parse_mode="HTML")
    recipe = await groq_service.generate_recipe(selected['name'], products)
    await wait.delete()
    
    await state_manager.set_current_dish(user_id, selected['name'])
    recipe_id = await state_manager.save_recipe_to_history(user_id, selected['name'], recipe)
    can_gen, rem, lim = await database.check_image_limit(user_id)
    
    await callback.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id, False, rem), parse_mode="HTML")

# ... (импорты и начало файла без изменений) ...

async def handle_generate_image(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. Получаем ID рецепта (ВАЖНО ДЛЯ СОХРАНЕНИЯ В БД)
    # Метод get_last_saved_recipe_id берет ID из памяти state_manager
    recipe_id = await state_manager.get_last_saved_recipe_id(user_id)
    
    dish_name = await state_manager.get_current_dish(user_id)
    
    can_gen, rem, lim = await database.check_image_limit(user_id)
    if lim != -1 and rem <= 0:
        await callback.answer("❌ Лимит исчерпан", show_alert=False)
        return

    wait = await callback.message.answer("🎨 Рисую (Hugging Face)...")
    
    try:
        translated = await groq_service.translate_to_english(dish_name)
        img_data = await image_service.generate_image(translated)
        
        if img_data:
            # 1. Загружаем в облако
            filename = f"{user_id}_{int(time.time())}.jpg"
            image_url, backend = await storage_service.upload_image(img_data, filename)
            
            # 2. Сохраняем в кэш
            recipe_hash = hashlib.md5(dish_name.encode()).hexdigest() # Тут лучше бы хеш рецепта, но пока так
            await database.save_cached_image(dish_name, recipe_hash, image_url, backend, len(img_data))
            
            # 3. ОБНОВЛЯЕМ ЗАПИСЬ В ТАБЛИЦЕ РЕЦЕПТОВ (ЧТОБЫ БЫЛО В ИЗБРАННОМ)
            if recipe_id and image_url:
                await database.update_recipe_image(recipe_id, image_url)
            
            # 4. Увеличиваем счетчик
            await database.increment_image_count(user_id)
            
            await wait.delete()
            await callback.message.answer_photo(BufferedInputFile(img_data, "img.jpg"), caption=f"🎨 {dish_name}")
        else:
            await wait.edit_text("❌ Ошибка генерации")
    except Exception as e:
        logger.error(f"Image Error: {e}")
        await wait.edit_text("❌ Ошибка")

# ... (Остальные методы без изменений) ...

async def handle_create_card(callback: CallbackQuery):
    user_id = callback.from_user.id
    dish_name = await state_manager.get_current_dish(user_id)
    recipe = await state_manager.get_last_bot_message(user_id)
    
    wait = await callback.message.answer("📸 Создаю карточку...")
    
    try:
        parsed = await groq_service.parse_recipe_for_card(recipe)
        # Генерация...
        card_bytes = recipe_card_generator.generate_card(
            parsed.get("title", dish_name),
            parsed.get("ingredients", []),
            parsed.get("time", "30"),
            parsed.get("portions", "2"),
            parsed.get("difficulty", "Easy"),
            parsed.get("chef_tip", ""),
            None # Здесь можно передать картинку если есть
        )
        await wait.delete()
        await callback.message.answer_document(BufferedInputFile(card_bytes, "card.png"), caption="✅")
    except Exception as e:
        logger.error(f"Card error: {e}")
        await wait.delete()
        # Специальное сообщение об ошибке
        await callback.message.answer("⚠️ Данный функционал находится в процессе тестирования. Попробуйте позже.")

async def handle_fav_add(callback: CallbackQuery):
    user_id = callback.from_user.id
    rid = int(callback.data.replace("fav_add_", ""))
    success = await database.add_to_favorites(user_id, rid)
    # show_alert=False для тихого уведомления
    msg = "✅ Добавлено в избранное!" if success else "⚠️ Уже в избранном"
    await callback.answer(msg, show_alert=False)

async def handle_restart(callback: CallbackQuery):
    await state_manager.clear_session(callback.from_user.id)
    await callback.message.edit_text("✅ Сброшено")
    await callback.answer()

async def handle_limit_exceeded(callback: CallbackQuery):
    await callback.answer("❌ Лимит исчерпан", show_alert=False)

async def handle_delete_msg(c): 
    try: await c.message.delete()
    except: pass

async def handle_action_add_more(c): 
    await c.message.edit_text("✏️ Пишите еще продукты:")

async def handle_back_to_categories(c): await handle_action_cook(c)

async def handle_repeat_recipe(c):
    # Логика повтора...
    await c.answer("Генерирую новый вариант...", show_alert=False)

async def handle_fav_view(c):
    rid = int(c.data.replace("fav_", ""))
    r = await database.get_favorite_recipe(rid)
    if r: await c.message.edit_text(r['recipe_text'], parse_mode="HTML")

async def handle_clear_my_history(c):
    await database.clear_user_history(c.from_user.id)
    await c.answer("✅ Очищено", show_alert=False)

# Админка заглушки
async def handle_admin_stats(c): await c.answer("Stats")
async def handle_admin_top_cooks(c): await c.answer("Top Cooks")
async def handle_admin_top_ingredients(c): await c.answer("Top Ing")
async def handle_admin_top_dishes(c): await c.answer("Top Dishes")
async def handle_admin_random_fact(c): await c.answer("Fact")

# --- REGISTER ---
def register_handlers(dp: Dispatcher):
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_author, Command("author"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_favorites, Command("favorites"))
    dp.message.register(cmd_admin, Command("admin"))
    dp.message.register(handle_voice, F.voice | F.audio)
    dp.message.register(handle_text, F.text)
    
    dp.callback_query.register(handle_action_cook, F.data == "action_cook")
    dp.callback_query.register(handle_category_selection, F.data.startswith("cat_"))
    dp.callback_query.register(handle_dish_selection, F.data.startswith("dish_"))
    dp.callback_query.register(handle_generate_image, F.data == "gen_image")
    dp.callback_query.register(handle_create_card, F.data == "create_card")
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
    dp.callback_query.register(handle_limit_exceeded, F.data == "limit_exceeded")
    dp.callback_query.register(handle_back_to_categories, F.data == "back_to_categories")
    dp.callback_query.register(handle_repeat_recipe, F.data == "repeat_recipe")
    dp.callback_query.register(handle_fav_view, F.data.startswith("fav_"))
    dp.callback_query.register(handle_clear_my_history, F.data == "clear_my_history")
    
    # Админка
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_top_cooks, F.data == "admin_top_cooks")
    dp.callback_query.register(handle_admin_top_ingredients, F.data == "admin_top_ingredients")
    dp.callback_query.register(handle_admin_top_dishes, F.data == "admin_top_dishes")
    dp.callback_query.register(handle_admin_random_fact, F.data == "admin_random_fact")
