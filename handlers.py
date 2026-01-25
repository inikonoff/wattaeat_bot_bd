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
    CallbackQuery, BufferedInputFile, FSInputFile
)

from groq_service import groq_service
from state_manager import state_manager
from database import db as database
from admin_service import admin_service
from storage_service import storage_service
from image_service import image_service  # <-- Используем новый сервис Hugging Face
from card_generator import recipe_card_generator
from config import ADMIN_IDS

# Инициализация
logger = logging.getLogger(__name__)

# --- СЛОВАРЬ КАТЕГОРИЙ ---
CATEGORY_MAP = {
    "breakfast": "🍳 Завтраки",
    "soup": "🍲 Супы",
    "main": "🍝 Вторые блюда",
    "salad": "🥗 Салаты",
    "snack": "🥪 Закуски",
    "dessert": "🍰 Десерты",
    "drink": "🥤 Напитки",
    "sauce": "🍾 Соусы",
    "mix": "🍱 Комплексный обед",
}

# --- КЛАВИАТУРЫ ---

def get_confirmation_keyboard():
    """Кнопки после ввода продуктов"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить продукты", callback_data="action_add_more")],
        [InlineKeyboardButton(text="👨‍🍳 Готовить (Категории)", callback_data="action_cook")]
    ])

def get_categories_keyboard(categories: list):
    builder = []
    row = []
    for cat_key in categories:
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
    """Клавиатура под рецептом"""
    buttons = []
    
    # Кнопка генерации изображения
    if remaining_images > 0 or remaining_images == -1:
        limit_text = "∞" if remaining_images == -1 else remaining_images
        buttons.append([InlineKeyboardButton(
            text=f"🎨 Сгенерировать фото ({limit_text})",
            callback_data="gen_image"
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text="🎨 Лимит исчерпан (завтра)",
            callback_data="limit_exceeded"
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
    """Админская клавиатура"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🏆 Топ поваров", callback_data="admin_top_cooks")],
        [InlineKeyboardButton(text="🥕 Топ продуктов", callback_data="admin_top_ingredients")],
        [InlineKeyboardButton(text="🍽️ Топ блюд", callback_data="admin_top_dishes")],
        [InlineKeyboardButton(text="🎲 Факт", callback_data="admin_random_fact")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])

def get_favorites_keyboard(favorites: list):
    """Клавиатура для избранного"""
    buttons = []
    for recipe in favorites:
        buttons.append([InlineKeyboardButton(
            text=recipe['dish_name'][:40],
            callback_data=f"fav_{recipe['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОСНОВНЫЕ ХЭНДЛЕРЫ ---

async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    try:
        await database.get_or_create_user(
            telegram_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name
        )
        
        # ВАЖНО: Теперь используем await, так как state_manager лезет в БД
        current_products = await state_manager.get_products(user_id)
        
        if current_products:
            text = (
                "🔄 <b>Продолжаем предыдущую сессию</b>\n\n"
                f"🛒 Ваши продукты: <b>{current_products}</b>\n\n"
                "✏️ Добавьте продукты или выберите:"
            )
            await message.answer(text, reply_markup=get_confirmation_keyboard(), parse_mode="HTML")
        else:
            await state_manager.clear_session(user_id)
            text = (
                "👋 Здравствуйте!\n"
                "🎤 Отправьте голосовое или текстовое сообщение с перечнем продуктов,\n"
                "и я подскажу, что из них можно приготовить.\n\n"
                "📝 Или напишите 'Дай рецепт [блюдо]'."
            )
            await message.answer(text, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при старте: {e}")
        await message.answer("👋 Привет! Напиши, какие есть продукты.")

async def cmd_author(message: Message):
    await message.answer("👨‍💻 Автор бота: @inikonoff")

async def cmd_stats(message: Message):
    """Показать статистику бота"""
    try:
        user_id = message.from_user.id
        
        user_recipes = await database.get_user_recipes(user_id, limit=5)
        recipes_text = "\n".join([f"• {r['dish_name']} ({r['created_at'].strftime('%d.%m')})" 
                                  for r in user_recipes]) if user_recipes else "Пока нет сохраненных рецептов"
        
        can_generate, remaining, limit = await database.check_image_limit(user_id)
        limit_text = f"Осталось: {remaining}/{limit}" if limit != -1 else "Безлимит"
        
        text = (
            "📊 <b>Ваша статистика:</b>\n\n"
            f"📝 Ваших рецептов: <b>{len(user_recipes)}</b>\n"
            f"🎨 Лимит изображений: <b>{limit_text}</b>\n\n"
            f"<b>Последние рецепты:</b>\n{recipes_text}\n\n"
            "❤️ Избранное: /favorites"
        )
        await message.answer(text, reply_markup=get_stats_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

async def cmd_favorites(message: Message):
    """Команда /favorites - показать избранное"""
    user_id = message.from_user.id
    try:
        favorites = await database.get_user_favorites(user_id)
        if not favorites:
            await message.answer("❤️ У вас пока нет избранных рецептов")
            return
        
        text = f"❤️ <b>Ваши избранные рецепты ({len(favorites)}):</b>\n\nВыберите рецепт:"
        kb = get_favorites_keyboard(favorites)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка получения избранного: {e}")
        await message.answer("❌ Ошибка")

async def cmd_admin(message: Message):
    """Команда /admin"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("🚫 У вас нет доступа к админке")
        return
    await message.answer("📊 <b>Админская панель</b>", reply_markup=get_admin_keyboard(), parse_mode="HTML")

# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ---

async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if text.lower().startswith("дай рецепт") or text.lower().startswith("рецепт"):
        await handle_direct_recipe(message, text)
    else:
        await process_products_input(message, user_id, text)

async def handle_direct_recipe(message: Message, text: str):
    user_id = message.from_user.id
    dish_name = text.lower().replace("дай рецепт", "").replace("рецепт", "").strip()
    dish_name = dish_name.strip(":,-. ")
    
    if len(dish_name) < 3:
        await message.answer("Название блюда слишком короткое.")
        return

    wait = await message.answer(f"⚡️ Ищу: <b>{dish_name}</b>...", parse_mode="HTML")
    try:
        recipe = await groq_service.generate_freestyle_recipe(dish_name)
        await wait.delete()
        
        # AWAIT HERE: все вызовы state_manager
        await state_manager.set_current_dish(user_id, dish_name)
        await state_manager.set_state(user_id, "recipe_sent")
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        can_generate, remaining, limit = await database.check_image_limit(user_id)
        
        await message.answer(
            recipe, 
            reply_markup=get_recipe_keyboard(recipe_id, False, remaining),
            parse_mode="HTML"
        )
    except Exception as e:
        await wait.delete()
        logger.error(f"Ошибка генерации: {e}")
        await message.answer("❌ Ошибка генерации рецепта.")

async def process_products_input(message: Message, user_id: int, products_text: str):
    try:
        # AWAIT HERE
        await state_manager.add_products(user_id, products_text)
        current_products = await state_manager.get_products(user_id)
        
        text = (
            f"✅ Продукты сохранены!\n\n"
            f"🛒 <b>Текущий набор:</b> {current_products}\n\n"
            f"Выберите действие:"
        )
        await message.answer(text, reply_markup=get_confirmation_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка продуктов: {e}")
        await message.answer("❌ Ошибка обработки продуктов")

# --- ОБРАБОТКА ГОЛОСОВЫХ ---

async def handle_voice(message: Message):
    user_id = message.from_user.id
    processing_msg = await message.answer("🎧 Распознаю...")
    
    try:
        if message.voice:
            file_info = await message.bot.get_file(message.voice.file_id)
        else:
            file_info = await message.bot.get_file(message.audio.file_id)
        
        voice_buffer = io.BytesIO()
        await message.bot.download_file(file_info.file_path, voice_buffer)
        
        recognized_text = await groq_service.transcribe_voice(voice_buffer.getvalue())
        await processing_msg.delete()
        
        if recognized_text.startswith("❌"):
            await message.answer(recognized_text)
            return
        
        if recognized_text.lower().startswith("дай рецепт") or recognized_text.lower().startswith("рецепт"):
            await handle_direct_recipe(message, recognized_text)
        else:
            await process_products_input(message, user_id, recognized_text)
            
    except Exception as e:
        await processing_msg.delete()
        logger.error(f"Ошибка голосового: {e}")
        await message.answer("❌ Ошибка обработки голосового")

# --- CALLBACK ХЭНДЛЕРЫ ---

async def handle_delete_msg(callback: CallbackQuery):
    try: await callback.message.delete()
    except: pass

async def handle_limit_exceeded(callback: CallbackQuery):
    await callback.answer("❌ Лимит исчерпан! Попробуйте завтра", show_alert=True)

async def handle_action_add_more(callback: CallbackQuery):
    await callback.message.edit_text("✏️ Напишите дополнительные продукты:")
    await callback.answer()

async def handle_action_cook(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        # AWAIT HERE
        products = await state_manager.get_products(user_id)
        
        if not products:
            await callback.answer("❌ Сначала добавьте продукты", show_alert=True)
            return
        
        wait = await callback.message.edit_text("🔍 Анализирую продукты и подбираю категории...")
        
        try:
            categories = await groq_service.analyze_categories(products)
            if not categories:
                await wait.edit_text("❌ Не удалось определить категории. Уточните список продуктов.")
                return
            
            await wait.edit_text(
                f"✅ Продукты: <b>{products}</b>\n\n🍽️ <b>Выберите категорию:</b>",
                reply_markup=get_categories_keyboard(categories),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка категорий: {e}")
            await wait.edit_text("❌ Ошибка определения категорий")
    except Exception as e:
        logger.error(f"Ошибка cook: {e}")

async def handle_category_selection(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        category = callback.data.replace("cat_", "")
        # AWAIT HERE
        products = await state_manager.get_products(user_id)
        
        wait = await callback.message.edit_text(
            f"🔍 Ищу блюда в категории: <b>{CATEGORY_MAP.get(category, category)}</b>...",
            parse_mode="HTML"
        )
        
        dishes = await groq_service.generate_dishes_list(products, category)
        if not dishes:
            await wait.edit_text("❌ Не нашлось блюд. Попробуйте другую категорию.")
            return
        
        # AWAIT HERE
        await state_manager.set_dishes_list(user_id, dishes)
        
        dishes_text = "\n".join([f"{i+1}. {dish['name']}" for i, dish in enumerate(dishes)])
        await wait.edit_text(
            f"🍽️ <b>Доступные блюда:</b>\n\n{dishes_text}\n\nВыберите для рецепта:",
            reply_markup=get_dishes_keyboard(dishes),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка выбора категории: {e}")

async def handle_dish_selection(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        dish_index = int(callback.data.replace("dish_", ""))
        
        # AWAIT HERE
        dishes = await state_manager.get_dishes_list(user_id)
        if not dishes or dish_index >= len(dishes):
            await callback.answer("❌ Блюдо не найдено", show_alert=True)
            return
        
        selected_dish = dishes[dish_index]
        products = await state_manager.get_products(user_id)
        
        wait = await callback.message.edit_text(f"⚡️ Пишу рецепт: <b>{selected_dish['name']}</b>...", parse_mode="HTML")
        
        try:
            recipe = await groq_service.generate_recipe(selected_dish['name'], products)
            await wait.delete()
            
            # AWAIT HERE
            await state_manager.set_current_dish(user_id, selected_dish['name'])
            await state_manager.set_state(user_id, "recipe_sent")
            recipe_id = await state_manager.save_recipe_to_history(user_id, selected_dish['name'], recipe)
            
            can_generate, remaining, limit = await database.check_image_limit(user_id)
            
            await callback.message.answer(
                recipe, 
                reply_markup=get_recipe_keyboard(recipe_id, False, remaining),
                parse_mode="HTML"
            )
        except Exception as e:
            await wait.delete()
            logger.error(f"Ошибка рецепта: {e}")
            await callback.message.answer("❌ Ошибка генерации рецепта")
    except Exception as e:
        logger.error(f"Ошибка выбора блюда: {e}")

async def handle_repeat_recipe(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        # AWAIT HERE
        dish_name = await state_manager.get_current_dish(user_id)
        products = await state_manager.get_products(user_id)
        
        if not dish_name:
            await callback.answer("❌ Сначала выберите блюдо", show_alert=True)
            return
        
        wait = await callback.message.edit_text(f"⚡️ Готовлю другой вариант: <b>{dish_name}</b>", parse_mode="HTML")
        recipe = await groq_service.generate_recipe(dish_name, products)
        await wait.delete()
        
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        can_generate, remaining, limit = await database.check_image_limit(user_id)
        
        await callback.message.answer(
            recipe, 
            reply_markup=get_recipe_keyboard(recipe_id, False, remaining),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка повтора: {e}")

async def handle_back_to_categories(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        # AWAIT HERE
        products = await state_manager.get_products(user_id)
        
        if not products:
            await callback.answer("❌ Нет продуктов", show_alert=True)
            return
        
        wait = await callback.message.edit_text("🔍 Возвращаюсь к категориям...")
        categories = await groq_service.analyze_categories(products)
        
        await wait.edit_text(
            f"✅ Продукты: <b>{products}</b>\n\n🍽️ <b>Выберите категорию:</b>",
            reply_markup=get_categories_keyboard(categories),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка назад: {e}")

async def handle_restart(callback: CallbackQuery):
    user_id = callback.from_user.id
    # AWAIT HERE
    await state_manager.clear_session(user_id)
    await callback.message.edit_text("✅ Сессия сброшена!\n✏️ Отправьте новые продукты.")
    await callback.answer()

async def handle_fav_add(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        recipe_id = int(callback.data.replace("fav_add_", ""))
        success = await database.add_to_favorites(user_id, recipe_id)
        if success:
            await callback.answer("✅ Добавлено в избранное!", show_alert=True)
        else:
            await callback.answer("⚠️ Уже в избранном", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка избранного: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_fav_view(callback: CallbackQuery):
    try:
        recipe_id = int(callback.data.replace("fav_", ""))
        recipe = await database.get_favorite_recipe(recipe_id)
        if not recipe:
            await callback.answer("❌ Рецепт не найден", show_alert=True)
            return
        
        can_generate, remaining, limit = await database.check_image_limit(callback.from_user.id)
        await callback.message.edit_text(
            recipe['recipe_text'],
            reply_markup=get_recipe_keyboard(recipe_id, recipe.get('image_url') is not None, remaining),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка просмотра избранного: {e}")

async def handle_clear_my_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    await database.clear_user_history(user_id)
    await callback.answer("✅ История очищена!", show_alert=True)

# --- ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ (HUGGING FACE) ---

# ... (начало файла без изменений) ...

async def handle_generate_image(callback: CallbackQuery):
    """Кнопка '🎨 Сгенерировать фото'"""
    user_id = callback.from_user.id
    dish_name = await state_manager.get_current_dish(user_id)
    recipe = await state_manager.get_last_bot_message(user_id)
    
    if not dish_name or not recipe:
        await callback.answer("❌ Рецепт не найден")
        return
    
    can_generate, remaining, limit = await database.check_image_limit(user_id)
    if limit != -1 and remaining <= 0:
        await callback.answer(f"❌ Лимит исчерпан!", show_alert=True)
        return
    
    recipe_hash = hashlib.md5(recipe.encode()).hexdigest()
    try:
        cached = await database.get_cached_image(recipe_hash)
        if cached:
            await callback.message.answer_photo(cached['image_url'], caption=f"🎨 {dish_name}")
            await callback.answer("✅ Из кеша")
            return
    except Exception as e:
        logger.warning(f"Ошибка кеша: {e}")
    
    wait = await callback.message.answer("🎨 Рисую (Hugging Face)... Это займет 10-20 сек.")
    await callback.answer()
    
    try:
        # 1. ПЕРЕВОД НА АНГЛИЙСКИЙ ДЛЯ HF
        logger.info(f"Перевожу '{dish_name}' для HF...")
        translated_prompt = await groq_service.translate_to_english(dish_name)
        
        # 2. ГЕНЕРАЦИЯ ПО АНГЛИЙСКОМУ ПРОМПТУ
        image_data = await image_service.generate_image(translated_prompt)
        
        if not image_data:
            await wait.edit_text("❌ Сервер перегружен. Попробуйте позже.")
            return
        
        # Загрузка и сохранение
        filename = f"{user_id}_{int(time.time())}.jpg"
        image_url, backend = await storage_service.upload_image(image_data, filename)
        
        if image_url:
            await database.save_cached_image(dish_name, recipe_hash, image_url, backend, len(image_data))
            await database.increment_image_count(user_id)
            
            await wait.delete()
            photo = BufferedInputFile(image_data, filename="image.jpg")
            await callback.message.answer_photo(
                photo,
                caption=f"🎨 <b>{dish_name}</b>",
                parse_mode="HTML"
            )
        else:
            await wait.edit_text("❌ Ошибка сохранения изображения.")
            
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}", exc_info=True)
        await wait.edit_text("❌ Произошла ошибка.")

async def handle_create_card(callback: CallbackQuery):
    """Кнопка '📤 Поделиться рецептом'"""
    user_id = callback.from_user.id
    # AWAIT HERE
    dish_name = await state_manager.get_current_dish(user_id)
    recipe = await state_manager.get_last_bot_message(user_id)
    
    if not dish_name or not recipe:
        await callback.answer("❌ Рецепт не найден")
        return
    
    wait = await callback.message.answer("📸 Создаю красивую карточку...")
    await callback.answer()
    
    try:
        # Парсим рецепт
        parsed = await groq_service.parse_recipe_for_card(recipe)
        
        # Пытаемся получить картинку блюда для фона
        dish_image_data = None
        recipe_hash = hashlib.md5(recipe.encode()).hexdigest()
        cached = await database.get_cached_image(recipe_hash)
        
        if cached and cached.get('image_url'):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(cached['image_url']) as resp:
                        if resp.status == 200:
                            dish_image_data = await resp.read()
            except: pass
        
        # Генерируем карточку
        card_data = recipe_card_generator.generate_card(
            title=parsed.get("title", dish_name),
            ingredients=parsed.get("ingredients", []),
            time=parsed.get("time", "30"),
            portions=parsed.get("portions", "2"),
            difficulty=parsed.get("difficulty", "Easy"),
            chef_tip=parsed.get("chef_tip", "Приятного аппетита!"),
            dish_image_data=dish_image_data
        )
        
        await wait.delete()
        
        card_file = BufferedInputFile(card_data, filename=f"Recipe_{dish_name}.png")
        await callback.message.answer_document(
            card_file,
            caption=f"📤 <b>Карточка рецепта: {dish_name}</b>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        await wait.edit_text("❌ Не удалось создать карточку.")
        logger.error(f"Ошибка карточки: {e}", exc_info=True)

# --- АДМИНСКИЕ ХЭНДЛЕРЫ ---

async def handle_admin_stats(callback: CallbackQuery):
    try:
        text = await admin_service.get_stats_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка")

async def handle_admin_top_cooks(callback: CallbackQuery):
    try:
        text = await admin_service.get_top_cooks_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка")

async def handle_admin_top_ingredients(callback: CallbackQuery):
    try:
        text = await admin_service.get_top_ingredients_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка")

async def handle_admin_top_dishes(callback: CallbackQuery):
    try:
        text = await admin_service.get_top_dishes_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка")

async def handle_admin_random_fact(callback: CallbackQuery):
    try:
        text = await admin_service.get_random_fact_message()
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        await callback.answer("❌ Ошибка")

# --- РЕГИСТРАЦИЯ ХЭНДЛЕРОВ ---

def register_handlers(dp: Dispatcher):
    # Команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_author, Command("author"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_favorites, Command("favorites"))
    dp.message.register(cmd_admin, Command("admin"))
    
    # Медиа
    dp.message.register(handle_voice, F.voice | F.audio)
    dp.message.register(handle_text, F.text)
    
    # Callback
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_limit_exceeded, F.data == "limit_exceeded")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
    dp.callback_query.register(handle_action_cook, F.data == "action_cook")
    dp.callback_query.register(handle_category_selection, F.data.startswith("cat_"))
    dp.callback_query.register(handle_dish_selection, F.data.startswith("dish_"))
    dp.callback_query.register(handle_repeat_recipe, F.data == "repeat_recipe")
    dp.callback_query.register(handle_back_to_categories, F.data == "back_to_categories")
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_fav_view, F.data.startswith("fav_"))
    dp.callback_query.register(handle_clear_my_history, F.data == "clear_my_history")
    
    # Генерация
    dp.callback_query.register(handle_generate_image, F.data == "gen_image")
    dp.callback_query.register(handle_create_card, F.data == "create_card")
    
    # Админка
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_top_cooks, F.data == "admin_top_cooks")
    dp.callback_query.register(handle_admin_top_ingredients, F.data == "admin_top_ingredients")
    dp.callback_query.register(handle_admin_top_dishes, F.data == "admin_top_dishes")
    dp.callback_query.register(handle_admin_random_fact, F.data == "admin_random_fact")
