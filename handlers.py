python
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
from image_prompt_generator import image_prompt_generator
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
        [InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")]
    ])

def get_recipe_keyboard(recipe_id: int = None, has_image: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура под рецептом - ОБНОВЛЕННЫЙ ПОРЯДОК"""
    buttons = []
    
    # Кнопка "В избранное" - ПЕРВАЯ
    if recipe_id:
        buttons.append([InlineKeyboardButton(
            text="❤️ В избранное",
            callback_data=f"fav_add_{recipe_id}"
        )])
    
    # Кнопка "Другой вариант" - ВТОРАЯ
    buttons.append([InlineKeyboardButton(
        text="🔄 Другой вариант", 
        callback_data="repeat_recipe"
    )])
    
    # Кнопка генерации промпта - ТРЕТЬЯ
    buttons.append([InlineKeyboardButton(
        text="🎨 Промпт для Midjourney/DALL-E",
        callback_data="gen_prompt"
    )])
    
    # Кнопка создания карточки (ЗАКОММЕНТИРОВАНА)
    # buttons.append([InlineKeyboardButton(
    #     text="📤 Поделиться рецептом",
    #     callback_data="create_card"
    # )])
    
    # Кнопка "Вернуться к категориям" - ЧЕТВЕРТАЯ
    buttons.append([InlineKeyboardButton(
        text="⬅️ Вернуться к категориям", 
        callback_data="back_to_categories"
    )])
    
    # Кнопка "Новый набор продуктов" - ПЯТАЯ
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
    
    # Промпт для генерации
    buttons.append([InlineKeyboardButton(
        text="🎨 Промпт для Midjourney/DALL-E",
        callback_data="gen_prompt"
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
    except:
        await message.answer("👋 Привет!")

async def cmd_author(message: Message):
    await message.answer("👨‍💻 Автор бота: @inikonoff")

async def cmd_stats(message: Message):
    try:
        user_id = message.from_user.id
        # Получаем последние рецепты пользователя для истории
        user_recipes = await database.get_user_recipes(user_id, limit=5)
        
        can_generate, remaining, limit = await database.check_image_limit(user_id)
        limit_text = f"{remaining}/{limit}" if limit != -1 else "∞"
        
        text = f"📊 <b>Статистика:</b>\n\n📝 Рецептов: <b>{len(user_recipes)}</b>\n"
        
        # Показываем историю последних рецептов
        if user_recipes:
            text += f"\n<b>Последние рецепты:</b>\n"
            for i, recipe in enumerate(user_recipes[:5], 1):
                text += f"{i}. {recipe['dish_name'][:30]}\n"
        
        await message.answer(
            text, 
            reply_markup=get_stats_keyboard(user_id, user_recipes), 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in stats: {e}", exc_info=True)
        await message.answer("❌ Ошибка получения статистики")

async def cmd_favorites(message: Message):
    try:
        favs = await database.get_user_favorites(message.from_user.id)
        if not favs:
            await message.answer("❤️ Пусто в избранном")
            return
        await message.answer(f"❤️ <b>Избранное ({len(favs)}):</b>", reply_markup=get_favorites_keyboard(favs), parse_mode="HTML")
    except: 
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
    
    # Очищаем "дай рецепт" и пробелы, сохраняем кавычки пользователя
    dish_name = text
    
    # Удаляем команды и фразы, но сохраняем кавычки
    for phrase in ["дай рецепт", "рецепт", "дай", "покажи рецепт", "напиши рецепт"]:
        dish_name = dish_name.replace(phrase, "")
    
    dish_name = dish_name.strip()
    
    if len(dish_name) < 2:
        await message.answer("Напишите название блюда, например: <i>Дай рецепт борща</i>", parse_mode="HTML")
        return
    
    # Сохраняем оригинальный текст для отображения в поиске
    original_search_text = dish_name
    
    # Преобразуем название в именительный падеж (для отображения в рецепте)
    # Это упрощенная логика - в реальности нужна полноценная библиотека для склонений
    dish_name_display = dish_name.strip('"\'')
    
    # Простая нормализация: первая буква заглавная, остальные строчные
    # Но сохраняем название в том виде, в каком оно обычно используется
    if dish_name_display and dish_name_display[0].islower():
        dish_name_display = dish_name_display[0].upper() + dish_name_display[1:]
    
    # Убираем лишние знаки препинания в конце
    dish_name_display = dish_name_display.rstrip('.!?,;')
    
    wait = await message.answer(f"Ищу рецепт {original_search_text}", parse_mode="HTML")
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
        
        if "дай рецепт" in text.lower() or "рецепт" in text.lower():
            await handle_direct_recipe(message, text)
        else:
            await process_products_input(message, user_id, text)
    except Exception as e:
        await processing_msg.delete()
        logger.error(f"Voice recognition error: {e}", exc_info=True)
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
    except Exception as e:
        await wait.edit_text("❌ Ошибка анализа")
        logger.error(f"Category analysis error: {e}", exc_info=True)

async def handle_category_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    category = callback.data.replace("cat_", "")
    products = await state_manager.get_products(user_id)
    
    wait = await callback.message.edit_text(f"🔍 Ищу рецепты ({category})...")
    
    try:
        dishes = await groq_service.generate_dishes_list(products, category)
        
        if not dishes:
            await wait.edit_text("❌ Не удалось найти рецепты для этой категории")
            return
        
        await state_manager.set_dishes_list(user_id, dishes)
        
        if category == "mix":
            # Для комплексного обеда показываем описание и одну кнопку
            description = "🍱 <b>Комплексный обед</b>\n\n"
            for i, dish in enumerate(dishes[:4], 1):
                description += f"<b>{i}. {dish['name']}</b>\n{dish['desc']}\n\n"
            
            await wait.edit_text(
                description,
                reply_markup=get_complex_lunch_keyboard(),
                parse_mode="HTML"
            )
        else:
            # Для обычных категорий показываем список блюд с описаниями
            description = f"🍽️ <b>Выберите блюдо:</b>\n\n"
            for i, dish in enumerate(dishes, 1):
                description += f"<b>{i}. {dish['name']}</b>\n{dish['desc']}\n\n"
            
            await wait.edit_text(
                description,
                reply_markup=get_dishes_keyboard(dishes, category),
                parse_mode="HTML"
            )
            
    except Exception as e:
        await wait.edit_text("❌ Ошибка при поиске рецептов")
        logger.error(f"Dish generation error: {e}", exc_info=True)

async def handle_dish_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # Проверяем, это комплексный обед или отдельное блюдо
    if callback.data == "dish_complex":
        # Для комплексного обеда получаем все блюда
        dishes = await state_manager.get_dishes_list(user_id)
        products = await state_manager.get_products(user_id)
        
        if not dishes or len(dishes) < 4:
            await callback.answer("❌ Нет данных для комплексного обеда", show_alert=True)
            return
        
        wait = await callback.message.edit_text("⚡️ Пишу рецепт комплексного обеда...")
        
        try:
            # Создаем описание для комплексного обеда
            dish_name = "Комплексный обед"
            dish_names = [dish['name'] for dish in dishes[:4]]
            dish_name += f" ({', '.join(dish_names)})"
            
            # Генерируем рецепт комплексного обеда
            recipe = await groq_service.generate_recipe(dish_name, products)
            await wait.delete()
            
            await state_manager.set_current_dish(user_id, dish_name)
            recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
            
            await callback.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
        except Exception as e:
            await wait.delete()
            logger.error(f"Complex lunch error: {e}", exc_info=True)
            await callback.answer("❌ Ошибка генерации рецепта", show_alert=True)
        
        return
    
    # Обычное блюдо
    idx = int(callback.data.replace("dish_", ""))
    dishes = await state_manager.get_dishes_list(user_id)
    
    if idx < 0 or idx >= len(dishes):
        await callback.answer("❌ Блюдо не найдено", show_alert=True)
        return
    
    selected = dishes[idx]
    products = await state_manager.get_products(user_id)
    
    wait = await callback.message.edit_text(f"⚡️ Пишу рецепт: <b>{selected['name']}</b>...", parse_mode="HTML")
    
    try:
        recipe = await groq_service.generate_recipe(selected['name'], products)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, selected['name'])
        recipe_id = await state_manager.save_recipe_to_history(user_id, selected['name'], recipe)
        
        await callback.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
    except Exception as e:
        await wait.delete()
        logger.error(f"Recipe generation error: {e}", exc_info=True)
        await callback.answer("❌ Ошибка генерации рецепта", show_alert=True)

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
    # Кнопка закомментирована, но обработчик оставляем для обратной совместимости
    await callback.answer("Функция временно недоступна", show_alert=True)

async def handle_fav_add(callback: CallbackQuery):
    user_id = callback.from_user.id
    rid = int(callback.data.replace("fav_add_", ""))
    success = await database.add_to_favorites(user_id, rid)
    msg = "✅ Добавлено в избранное!" if success else "⚠️ Уже в избранном"
    await callback.answer(msg, show_alert=False)

async def handle_fav_view(callback: CallbackQuery):
    """Просмотр избранного рецепта"""
    try:
        # Извлекаем recipe_id, игнорируя префикс fav_delete_
        callback_data = callback.data
        if callback_data.startswith("fav_delete_"):
            return  # Этот случай обрабатывается в handle_fav_delete
        
        recipe_id = int(callback_data.replace("fav_", ""))
        
        recipe = await database.get_favorite_recipe(recipe_id)
        
        if not recipe:
            await callback.answer("❌ Рецепт не найден", show_alert=True)
            return
        
        # Сохраняем информацию о текущем блюде для генерации промпта
        await state_manager.set_current_dish(callback.from_user.id, recipe['dish_name'])
        
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
        
        # Удаляем из избранного (меняем флаг is_favorite на FALSE)
        success = await database.remove_from_favorites(recipe_id)
        
        if success:
            await callback.message.edit_text(
                "✅ Рецепт удалён из избранного",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
                ])
            )
            await callback.answer("✅ Удалено!")
        else:
            await callback.answer("❌ Не удалось удалить", show_alert=True)
        
    except Exception as e:
        logger.error(f"Ошибка удаления из избранного: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)

async def handle_history_view(callback: CallbackQuery):
    """Просмотр рецепта из истории"""
    try:
        recipe_id = int(callback.data.replace("history_", ""))
        user_id = callback.from_user.id
        
        recipe = await database.get_favorite_recipe(recipe_id)
        
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
    await state_manager.clear_session(callback.from_user.id)
    await callback.message.edit_text("✅ Сброшено")
    await callback.answer()

async def handle_delete_msg(c: CallbackQuery): 
    try: 
        await c.message.delete()
    except: 
        pass

async def handle_action_add_more(c: CallbackQuery): 
    await c.message.edit_text("✏️ Пишите еще продукты:")

async def handle_back_to_categories(c: CallbackQuery): 
    await handle_action_cook(c)

async def handle_repeat_recipe(c: CallbackQuery):
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
        await wait.delete()
        
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        await c.message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
        await c.answer("✅ Новый вариант готов!")
    except Exception as e:
        await wait.delete()
        logger.error(f"Repeat recipe error: {e}", exc_info=True)
        await c.answer("❌ Ошибка генерации", show_alert=True)

async def handle_clear_my_history(c: CallbackQuery):
    await database.clear_user_history(c.from_user.id)
    await c.answer("✅ История очищена", show_alert=False)

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
    dp.callback_query.register(handle_generate_prompt, F.data == "gen_prompt")
    dp.callback_query.register(handle_create_card, F.data == "create_card")
    dp.callback_query.register(handle_fav_add, F.data.startswith("fav_add_"))
    dp.callback_query.register(handle_fav_delete, F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_fav_view, F.data.startswith("fav_") & ~F.data.startswith("fav_add_") & ~F.data.startswith("fav_delete_"))
    dp.callback_query.register(handle_history_view, F.data.startswith("history_"))
    dp.callback_query.register(handle_restart, F.data == "restart")
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_action_add_more, F.data == "action_add_more")
    dp.callback_query.register(handle_back_to_categories, F.data == "back_to_categories")
    dp.callback_query.register(handle_repeat_recipe, F.data == "repeat_recipe")
    dp.callback_query.register(handle_clear_my_history, F.data == "clear_my_history")
    
    # Админка
    dp.callback_query.register(handle_admin_stats, F.data == "admin_stats")
    dp.callback_query.register(handle_admin_top_cooks, F.data == "admin_top_cooks")
    dp.callback_query.register(handle_admin_top_ingredients, F.data == "admin_top_ingredients")
    dp.callback_query.register(handle_admin_top_dishes, F.data == "admin_top_dishes")
    dp.callback_query.register(handle_admin_random_fact, F.data == "admin_random_fact")
