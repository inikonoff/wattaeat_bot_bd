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
from image_prompt_generator import image_prompt_generator  # Добавлено
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

def get_recipe_keyboard(recipe_id: int = None, has_image: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура под рецептом"""
    buttons = []
    
    # НОВАЯ КНОПКА: Генерация промпта вместо изображения
    buttons.append([InlineKeyboardButton(
        text="🎨 Промпт для Midjourney/DALL-E",
        callback_data="gen_prompt"
    )])
    
    # Кнопка создания карточки
    buttons.append([InlineKeyboardButton(
        text="📤 Поделиться рецептом",
        callback_data="create_card"
    )])
    
    # Кнопка "В избранное"
    if recipe_id:
        buttons.append([InlineKeyboardButton(
            text="❤️ В избранное",
            callback_data=f"fav_add_{recipe_id}"
        )])
    
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
    dish_name = text.lower()
    for phrase in ["дай рецепт", "рецепт", "дай", "покажи рецепт", "напиши рецепт"]:
        dish_name = dish_name.replace(phrase, "")
    dish_name = dish_name.strip()
    
    if len(dish_name) < 2:
        await message.answer("Напишите название блюда, например: <i>Дай рецепт борща</i>", parse_mode="HTML")
        return

    # Приводим к нормальному виду (первая буква заглавная)
    dish_name_display = dish_name[0].upper() + dish_name[1:].lower()

    wait = await message.answer(f"⚡️ Ищу рецепт: <b>{dish_name_display}</b>...", parse_mode="HTML")
    try:
        # Генерируем рецепт с нормализованным названием
        recipe = await groq_service.generate_freestyle_recipe(dish_name_display)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_name_display)
        await state_manager.set_state(user_id, "recipe_sent")
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name_display, recipe)
        
        await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
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
    
    await callback.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")

async def handle_generate_prompt(callback: CallbackQuery):
    """Генерирует промпт для создания изображения"""
    user_id = callback.from_user.id
    dish_name = await state_manager.get_current_dish(user_id)
    
    if not dish_name:
        await callback.answer("❌ Блюдо не найдено. Сначала выберите рецепт.", show_alert=True)
        return
    
    try:
        # Генерируем 3 варианта промптов
        prompts = image_prompt_generator.generate_multiple_variants(dish_name, count=3)
        
        # Формируем сообщение
        message = f"🎨 <b>Промпты для генерации изображения:</b>\n\n"
        message += f"📝 <b>Блюдо:</b> {dish_name}\n\n"
        
        for i, prompt in enumerate(prompts, 1):
            message += f"<b>Вариант {i}:</b>\n"
            message += f"<code>{prompt}</code>\n\n"
        
        message += "💡 <i>Скопируйте любой вариант и используйте в Midjourney, DALL-E, Stable Diffusion или любом другом генераторе изображений!</i>"
        
        await callback.message.answer(
            message,
            parse_mode="HTML",
            reply_markup=get_hide_keyboard()
        )
        
        await callback.answer("✅ Промпты сгенерированы!")
        
    except Exception as e:
        logger.error(f"Ошибка генерации промпта: {e}", exc_info=True)
        await callback.answer("❌ Ошибка генерации промпта", show_alert=True)

async def handle_create_card(callback: CallbackQuery):
    user_id = callback.from_user.id
    dish_name = await state_manager.get_current_dish(user_id)
    recipe = await state_manager.get_last_bot_message(user_id)
    
    if not recipe:
        await callback.answer("❌ Рецепт не найден. Создайте новый рецепт.", show_alert=True)
        return
    
    wait = await callback.message.answer("📸 Создаю карточку...")
    
    try:
        # 1. Парсим рецепт в структурированные данные
        parsed = await groq_service.parse_recipe_for_card(recipe)
        
        # 2. Проверяем, что получили валидные данные
        if not parsed or not isinstance(parsed, dict):
            logger.error(f"Invalid parsed data: {type(parsed)}")
            await wait.edit_text("❌ Не удалось распарсить рецепт. Попробуйте создать новый рецепт.")
            return
        
        # 3. Получаем изображение блюда (если есть)
        recipe_id = await state_manager.get_last_saved_recipe_id(user_id)
        dish_image_data = None
        
        if recipe_id:
            recipe_record = await database.get_favorite_recipe(recipe_id)
            if recipe_record and recipe_record.get('image_url'):
                try:
                    # Скачиваем картинку
                    async with aiohttp.ClientSession() as session:
                        async with session.get(recipe_record['image_url'], timeout=10) as resp:
                            if resp.status == 200:
                                dish_image_data = await resp.read()
                except Exception as e:
                    logger.warning(f"Failed to fetch image: {e}")
        
        # 4. Генерируем карточку
        logger.info(f"Generating card with data: title={parsed.get('title')}, ingredients_count={len(parsed.get('ingredients', []))}")
        
        card_bytes = recipe_card_generator.generate_card(
            title=parsed.get("title", dish_name or "Рецепт"),
            ingredients=parsed.get("ingredients", ["Не указано"]),
            time=parsed.get("time", "30 мин"),
            portions=parsed.get("portions", "2"),
            difficulty=parsed.get("difficulty", "Средняя"),
            chef_tip=parsed.get("chef_tip", "Приятного аппетита!"),
            dish_image_data=dish_image_data
        )
        
        # 5. Проверяем, что карточка создалась
        if not card_bytes or len(card_bytes) < 1000:
            logger.error("Generated card is too small or empty")
            await wait.edit_text("❌ Ошибка генерации карточки. Попробуйте позже.")
            return
        
        # 6. Отправляем
        await wait.delete()
        await callback.message.answer_document(
            BufferedInputFile(card_bytes, f"recipe_{dish_name[:30]}.png"),
            caption=f"📋 <b>{parsed.get('title', dish_name)}</b>\n\n✨ Поделитесь рецептом с друзьями!",
            parse_mode="HTML"
        )
        await callback.answer("✅ Карточка готова!")
        
    except Exception as e:
        logger.error(f"Card generation error: {e}", exc_info=True)
        await wait.delete()
        
        # Более подробное сообщение об ошибке
        error_msg = "❌ Не удалось создать карточку.\n\n"
        
        if "cannot open resource" in str(e):
            error_msg += "Причина: Отсутствуют шрифты.\n"
            error_msg += "Решение: Администратор должен запустить скачивание шрифтов."
        elif "JSON" in str(e):
            error_msg += "Причина: Ошибка обработки рецепта.\n"
            error_msg += "Решение: Попробуйте создать рецепт заново."
        else:
            error_msg += f"Причина: {str(e)[:100]}"
        
        await callback.message.answer(error_msg)

async def handle_fav_add(callback: CallbackQuery):
    user_id = callback.from_user.id
    rid = int(callback.data.replace("fav_add_", ""))
    success = await database.add_to_favorites(user_id, rid)
    msg = "✅ Добавлено в избранное!" if success else "⚠️ Уже в избранном"
    await callback.answer(msg, show_alert=False)

async def handle_restart(callback: CallbackQuery):
    await state_manager.clear_session(callback.from_user.id)
    await callback.message.edit_text("✅ Сброшено")
    await callback.answer()

async def handle_delete_msg(c: CallbackQuery): 
    try: await c.message.delete()
    except: pass

async def handle_action_add_more(c: CallbackQuery): 
    await c.message.edit_text("✏️ Пишите еще продукты:")

async def handle_back_to_categories(c: CallbackQuery): 
    await handle_action_cook(c)

async def handle_repeat_recipe(c: CallbackQuery):
    # Логика повтора...
    await c.answer("Генерирую новый вариант...", show_alert=False)

async def handle_fav_view(c: CallbackQuery):
    rid = int(c.data.replace("fav_", ""))
    r = await database.get_favorite_recipe(rid)
    if r: 
        await c.message.edit_text(r['recipe_text'], parse_mode="HTML")

async def handle_clear_my_history(c: CallbackQuery):
    await database.clear_user_history(c.from_user.id)
    await c.answer("✅ Очищено", show_alert=False)

# --- АДМИН ОБРАБОТЧИКИ ---
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
    dp.callback_query.register(handle_generate_prompt, F.data == "gen_prompt")  # Изменено с handle_generate_image
    dp.callback_query.register(handle_create_card, F.data == "create_card")
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
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
