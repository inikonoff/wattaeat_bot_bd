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
    except Exception as e:
        logger.error(f"Start error: {e}", exc_info=True)

async def cmd_author(message: Message):
    text = (
        "👨‍💻 <b>Разработчик бота:</b>\n\n"
        "Иван Никифоров\n"
        "Telegram: @ivi4an\n\n"
        "Спасибо что пользуетесь!"
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
    
    # Убираем только "дай " в начале (без изменения регистра)
    dish_request = text.strip()
    
    if dish_request.lower().startswith("дай "):
        dish_request = dish_request[4:].strip()  # Удаляем "дай "
    
    # Проверяем минимальную длину
    if len(dish_request) < 2:
        await message.answer("Напишите название блюда, например: <i>Дай рецепт борща</i>", parse_mode="HTML")
        return
    
    # Для сообщения "Ищу..." используем текст как есть
    search_message = f"Ищу {dish_request}"
    
    # Для заголовка рецепта делаем первую букву заглавной
    dish_title = dish_request
    if dish_title and dish_title[0].islower():
        dish_title = dish_title[0].upper() + dish_title[1:]
    
    wait = await message.answer(search_message)
    
    try:
        # Генерируем рецепт с заголовком (первая буква заглавная)
        recipe = await groq_service.generate_freestyle_recipe(dish_title)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_title)
        await state_manager.set_state(user_id, "recipe_sent")
        
        # Сохраняем рецепт и получаем его ID
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_title, recipe)
        
        if recipe_id:
            await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
        else:
            await message.answer(recipe, parse_mode="HTML")
    except Exception as e:
        await wait.delete()
        logger.error(f"Recipe error: {e}", exc_info=True)
        await message.answer("❌ Не удалось придумать рецепт.")

async def process_products_input(message: Message, user_id: int, products_text: str):
    try:
        await state_manager.add_products(user_id, products_text)
        current = await state_manager.get_products(user_id)
        await message.answer(f"✅ Продукты: <b>{current}</b>\n\nЧто делаем?", reply_markup=get_confirmation_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error processing products: {e}", exc_info=True)
        await message.answer("❌ Ошибка обработки продуктов")

async def handle_voice(message: Message):
    user_id = message.from_user.id
    processing_msg = await message.answer("🎧 Распознаю...")
    try:
        file = await message.bot.get_file(message.voice.file_id if message.voice else message.audio.file_id)
        buffer = io.BytesIO()
        await message.bot.download_file(file.file_path, buffer)
        
        text = await groq_service.transcribe_voice(buffer.getvalue())
        await processing_msg.delete()
        
        if "дай рецепт" in text.lower() or text.lower().startswith("рецепт"):
            await handle_direct_recipe(message, text)
        else:
            await process_products_input(message, user_id, text)
    except Exception as e:
        await processing_msg.delete()
        logger.error(f"Voice error: {e}", exc_info=True)
        await message.answer("❌ Ошибка распознавания")

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
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_fav_delete, F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_fav_view, F.data.startswith("fav_") & ~F.data.startswith("fav_add_") & ~F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_history_view, F.data.startswith("history_"))
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
    dp.callback_query.register(handle_back_to_categories, F.data == "back_to_categories")
    dp.callback_query.register(handle_clear_my_history, F.data == "clear_my_history")
    
    # Админка
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_top_cooks, F.data == "admin_top_cooks")
    dp.callback_query.register(handle_admin_top_ingredients, F.data == "admin_top_ingredients")
    dp.callback_query.register(handle_admin_top_dishes, F.data == "admin_top_dishes")
    dp.callback_query.register(handle_admin_random_fact, F.data == "admin_random_fact")
