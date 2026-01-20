import os
import io
import logging
import hashlib
import time
import asyncio
from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile
from utils import VoiceProcessor
from groq_service import GroqService
from state_manager import state_manager
from database import db as database
from admin_service import admin_service
from storage_service import storage_service
from replicate_image import generate_with_fallback
from config import ADMIN_IDS

# Инициализация
voice_processor = VoiceProcessor()
groq_service = GroqService()
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
    """Кнопки после ввода продуктов: Добавить еще или Готовить"""
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

def get_recipe_keyboard(recipe_id: int = None, has_image: bool = False):
    """Клавиатура под рецептом"""
    buttons = []
    
    # Кнопка генерации изображения (если ещё нет)
    if not has_image:
        buttons.append([InlineKeyboardButton(text="🎨 Сгенерировать фото", callback_data="gen_image")])
    
    # Кнопка "В избранное" (если есть ID рецепта)
    if recipe_id:
        buttons.append([InlineKeyboardButton(text="❤️ В избранное", callback_data=f"fav_add_{recipe_id}")])
    
    # ИЗМЕНЕНО: Вместо "Другой вариант" теперь "Новый набор продуктов"
    buttons.append([InlineKeyboardButton(text="🛒 Новый набор продуктов", callback_data="new_products_set")])
    buttons.append([InlineKeyboardButton(text="⬅️ Вернуться к категориям", callback_data="back_to_categories")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_hide_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Скрыть", callback_data="delete_msg")]])

def get_stats_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить мою историю", callback_data="clear_my_history")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="delete_msg")]
    ])

def get_admin_keyboard():
    """Админская клавиатура"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Доска почёта (Топ-3)", callback_data="admin_top_cooks")],
        [InlineKeyboardButton(text="🥕 Топ-10 продуктов", callback_data="admin_top_ingredients")],
        [InlineKeyboardButton(text="🍽️ Топ-5 блюд", callback_data="admin_top_dishes")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎲 Случайный факт", callback_data="admin_random_fact")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
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

# --- ХЭНДЛЕРЫ КОМАНД ---

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
        
        # ИЗМЕНЕНО: Всегда очищаем сессию при /start
        await state_manager.clear_session(user_id)
        await state_manager.load_user_session(user_id)
        
        text = (
            "👋 Здравствуйте.\n"
            "🎤 Отправьте голосовое или текстовое сообщение с перечнем продуктов на русском или иностранном языке, и я подскажу, что из них можно приготовить.\n"
            "📝 Или напишите 'Дай рецепт [блюдо]'.\n"
        )
        await message.answer(text, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка при старте: {e}")
        await state_manager.clear_session(user_id)
        text = (
            "👋 Здравствуйте.\n"
            "🎤 Отправьте голосовое или текстовое сообщение с перечнем продуктов, и я подскажу, что из них можно приготовить.\n"
            "📝 Или напишите 'Дай рецепт [блюдо]'.\n"
        )
        await message.answer(text, parse_mode="HTML")

async def cmd_author(message: Message):
    """Показать информацию об авторе"""
    await message.answer("👨‍💻 Автор бота: @inikonoff")

async def cmd_stats(message: Message):
    """Показать статистику бота"""
    try:
        stats = await database.get_stats()
        user_id = message.from_user.id
        
        user_recipes = await database.get_user_recipes(user_id, limit=5)
        recipes_text = "\n".join([f"• {r['dish_name']} ({r['created_at'].strftime('%d.%m')})" 
                                  for r in user_recipes]) if user_recipes else "Пока нет сохраненных рецептов"
        
        text = (
            "📊 <b>Статистика бота:</b>\n\n"
            f"👤 Всего пользователей: {stats['users']}\n"
            f"📱 Активных сессий: {stats['active_sessions']}\n"
            f"📝 Сохранённых рецептов: {stats['saved_recipes']}\n\n"
            f"<b>Ваши последние рецепты:</b>\n{recipes_text}\n\n"
            "💾 База данных: Supabase"
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
        
        text = f"❤️ <b>Ваши избранные рецепты ({len(favorites)}):</b>\n\n"
        text += "Выберите рецепт для просмотра:"
        
        kb = get_favorites_keyboard(favorites)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Ошибка получения избранного: {e}")
        await message.answer("❌ Ошибка получения избранного")

async def cmd_admin(message: Message):
    """Команда /admin - админская панель"""
    user_id = str(message.from_user.id)
    
    if user_id not in ADMIN_IDS:
        await message.answer("🚫 У вас нет доступа к админке")
        return
    
    text = "📊 <b>Админская панель</b>\n\nВыберите действие:"
    await message.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")

# --- ФУНКЦИИ ДЛЯ ОПРЕДЕЛЕНИЯ НАМЕРЕНИЯ ---

def is_recipe_request(text: str) -> bool:
    """Определяет, является ли текст запросом на рецепт"""
    if not text:
        return False
    text_lower = text.lower().strip()
    return (text_lower.startswith("дай рецепт") or 
            text_lower.startswith("рецепт") or
            text_lower.startswith("как приготовить") or
            text_lower.startswith("how to cook") or
            text_lower.startswith("recipe for"))

def extract_dish_name_from_request(text: str) -> str:
    """Извлекает название блюда из запроса"""
    text_lower = text.lower().strip()
    
    phrases_to_remove = [
        "дай рецепт", "рецепт", "как приготовить", 
        "how to cook", "recipe for", "please", "пожалуйста"
    ]
    
    for phrase in phrases_to_remove:
        if text_lower.startswith(phrase):
            text_lower = text_lower[len(phrase):].strip()
    
    text_lower = text_lower.lstrip(":,-. ")
    return text_lower

# --- ОБРАБОТКА СООБЩЕНИЙ ---

async def handle_direct_recipe(message: Message):
    """Обработка 'Дай рецепт ...' и других запросов рецептов"""
    user_id = message.from_user.id
    dish_name = extract_dish_name_from_request(message.text)
    
    if len(dish_name) < 3:
        await message.answer("Напишите название блюда.", parse_mode="HTML")
        return

    wait = await message.answer(f"⚡️ Ищу: <b>{dish_name}</b>...", parse_mode="HTML")
    try:
        recipe = await groq_service.generate_freestyle_recipe(dish_name)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_name)
        await state_manager.set_state(user_id, "recipe_sent")
        
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
    except Exception as e:
        await wait.delete()
        logger.error(f"Ошибка генерации рецепта: {e}")
        await message.answer("❌ Ошибка генерации рецепта.")

async def handle_delete_msg(callback: CallbackQuery):
    """Удалить сообщение"""
    await callback.message.delete()
    await callback.answer()

async def handle_voice(message: Message):
    """Обработка голосового сообщения"""
    user_id = message.from_user.id
    processing_msg = await message.answer("🎧 Слушаю...")
    temp_file = f"temp/voice_{user_id}_{message.voice.file_id}.ogg"
    
    try:
        await message.bot.download(message.voice, destination=temp_file)
        text = await voice_processor.process_voice(temp_file)
        await processing_msg.delete()
        
        try: 
            await message.delete()
        except: 
            pass
        
        if is_recipe_request(text):
            await handle_direct_recipe_from_voice(message, text)
        else:
            await process_products_input(message, user_id, text)
            
    except Exception as e:
        await processing_msg.delete()
        await message.answer(f"😕 Не разобрал: {e}")
        if os.path.exists(temp_file):
            try: 
                os.remove(temp_file)
            except: 
                pass

async def handle_direct_recipe_from_voice(message: Message, recognized_text: str):
    """Обработка запроса рецепта из голосового сообщения"""
    user_id = message.from_user.id
    dish_name = extract_dish_name_from_request(recognized_text)
    
    if len(dish_name) < 3:
        await message.answer("Название блюда слишком короткое.", parse_mode="HTML")
        return

    wait = await message.answer(f"⚡️ Ищу: <b>{dish_name}</b>...", parse_mode="HTML")
    try:
        recipe = await groq_service.generate_freestyle_recipe(dish_name)
        await wait.delete()
        
        await state_manager.set_current_dish(user_id, dish_name)
        await state_manager.set_state(user_id, "recipe_sent")
        
        recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
        
        await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")
    except Exception as e:
        await wait.delete()
        logger.error(f"Ошибка генерации рецепта: {e}")
        await message.answer("❌ Ошибка генерации рецепта.")

async def handle_text(message: Message):
    """Обработка текстового сообщения"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    if text.startswith('/'):
        return
    
    if is_recipe_request(text):
        await handle_direct_recipe(message)
        return
    
    await process_products_input(message, user_id, text)

# --- ГЛАВНАЯ ЛОГИКА ОБРАБОТКИ ПРОДУКТОВ ---

async def process_products_input(message: Message, user_id: int, text: str):
    """Основная логика обработки ввода продуктов"""
    if is_recipe_request(text):
        await handle_direct_recipe(message)
        return
    
    # Пасхалка
    if text.lower().strip(" .!") in ["спасибо", "спс", "благодарю"]:
        if state_manager.get_state(user_id) == "recipe_sent":
            await message.answer("На здоровье! 👨‍🍳")
            await state_manager.clear_state(user_id)
            return

    if state_manager.get_state(user_id) == "recipe_sent":
        await state_manager.clear_session(user_id)

    current_products = state_manager.get_products(user_id)
    
    if not current_products:
        is_valid = await groq_service.validate_ingredients(text)
        if not is_valid:
            await message.answer(f"🤨 <b>\"{text}\"</b> — не похоже на продукты.", parse_mode="HTML")
            return
        
        await state_manager.set_products(user_id, text)
        msg_text = f"✅ Принято: <b>{text}</b>"
    else:
        await state_manager.append_products(user_id, text)
        all_products = state_manager.get_products(user_id)
        msg_text = f"➕ Добавлено: <b>{text}</b>\n🛒 <b>Всего:</b> {all_products}"

    await message.answer(msg_text, reply_markup=get_confirmation_keyboard(), parse_mode="HTML")

# --- ЛОГИКА КАТЕГОРИЙ И БЛЮД ---

async def start_category_flow(message: Message, user_id: int):
    """Начало выбора категории"""
    products = state_manager.get_products(user_id)
    if not products:
        await message.answer("Список продуктов пуст. Начните заново /start")
        return

    wait = await message.answer("👨‍🍳 Думаю, что приготовить...")
    
    categories = await groq_service.analyze_categories(products)
    
    await wait.delete()
    if not categories:
        await message.answer("Из этого сложно что-то приготовить.")
        return

    await state_manager.set_categories(user_id, categories)

    if len(categories) == 1:
        await show_dishes_for_category(message, user_id, products, categories[0])
    else:
        await message.answer("📂 <b>Выберите категорию:</b>", 
                           reply_markup=get_categories_keyboard(categories), 
                           parse_mode="HTML")

async def show_dishes_for_category(message: Message, user_id: int, products: str, category: str):
    """Показать блюда выбранной категории"""
    cat_name = CATEGORY_MAP.get(category, "Блюда")
    wait = await message.answer(f"🍳 Подбираю {cat_name}...")
    
    dishes_list = await groq_service.generate_dishes_list(products, category)
    
    if not dishes_list:
        await wait.delete()
        await message.answer("Не удалось придумать рецепты. Попробуйте другую категорию.")
        return

    await state_manager.set_generated_dishes(user_id, dishes_list)
    
    response_text = f"🍽 <b>Меню: {cat_name}</b>\n\n"
    for dish in dishes_list:
        response_text += f"🔸 <b>{dish['name']}</b>\n<i>{dish['desc']}</i>\n\n"
    
    await state_manager.add_message(user_id, "bot", response_text)
    
    await wait.delete()
    
    if category == "mix":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 Получить рецепты обеда", callback_data="dish_all_mix")],
            [InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data="back_to_categories")]
        ])
    else:
        kb = get_dishes_keyboard(dishes_list)
        
    await message.answer(response_text, reply_markup=kb, parse_mode="HTML")

async def generate_and_send_recipe(message: Message, user_id: int, dish_name: str):
    """Генерация и отправка рецепта"""
    wait = await message.answer(f"👨‍🍳 Пишу рецепт: <b>{dish_name}</b>...", parse_mode="HTML")
    products = state_manager.get_products(user_id)
    
    recipe = await groq_service.generate_recipe(dish_name, products)
    
    await wait.delete()
    
    await state_manager.set_current_dish(user_id, dish_name)
    await state_manager.set_state(user_id, "recipe_sent")
    
    recipe_id = await state_manager.save_recipe_to_history(user_id, dish_name, recipe)
    
    await message.answer(recipe, reply_markup=get_recipe_keyboard(recipe_id), parse_mode="HTML")

# --- ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ---

async def handle_generate_image(callback: CallbackQuery):
    """Кнопка '🎨 Сгенерировать фото' под рецептом"""
    user_id = callback.from_user.id
    
    # Проверяем лимит
    is_admin = str(user_id) in ADMIN_IDS
    can_generate, remaining = await database.check_image_limit(user_id, is_admin)
    
    if not can_generate:
        await callback.answer(
            "⚠️ Вы исчерпали дневной лимит генерации изображений (3 в день).\n"
            "Попробуйте завтра!",
            show_alert=True
        )
        return
    
    dish_name = state_manager.get_current_dish(user_id)
    recipe = state_manager.get_last_bot_message(user_id)
    
    if not dish_name or not recipe:
        await callback.answer("❌ Рецепт не найден")
        return
    
    # Проверяем кеш
    recipe_hash = hashlib.md5(recipe.encode()).hexdigest()
    
    try:
        cached = await database.get_cached_image(recipe_hash)
        
        if cached:
            logger.info(f"✅ Изображение найдено в кеше: {dish_name}")
            await callback.message.answer_photo(cached['image_url'])
            await callback.answer("✅ Из кеша")
            return
    except Exception as e:
        logger.warning(f"Ошибка проверки кеша: {e}")
    
    # Генерируем новое
    wait = await callback.message.answer(
        f"🎨 Рисую ваше блюдо...\n"
        f"{'🔓 Админ режим: без лимитов' if is_admin else f'📊 Осталось сегодня: {remaining - 1}'}"
    )
    await callback.answer()
    
    try:
        image_data = await generate_with_fallback(dish_name, recipe)
        
        if not image_data:
            await wait.edit_text(
                "❌ К сожалению, не удалось сгенерировать изображение.\n\n"
                "Возможные причины:\n"
                "• Все модели генерации временно недоступны\n"
                "• Превышен лимит запросов\n\n"
                "🔔 Об этом сообщено администратору."
            )
            
            # Уведомляем админа
            for admin_id in ADMIN_IDS:
                try:
                    await callback.bot.send_message(
                        admin_id,
                        f"⚠️ <b>Ошибка генерации изображения</b>\n\n"
                        f"Пользователь: {callback.from_user.id}\n"
                        f"Блюдо: {dish_name}\n"
                        f"Все модели Replicate недоступны",
                        parse_mode="HTML"
                    )
                except:
                    pass
            
            return
        
        # Загружаем на Supabase
        filename = f"{user_id}_{int(time.time())}_{dish_name[:20]}.jpg"
        image_url, backend = await storage_service.upload_image(image_data, filename)
        
        if not image_url:
            await wait.edit_text(
                "❌ Изображение сгенерировано, но не удалось загрузить на сервер.\n\n"
                "🔔 Об этом сообщено администратору."
            )
            
            # Уведомляем админа
            for admin_id in ADMIN_IDS:
                try:
                    await callback.bot.send_message(
                        admin_id,
                        f"⚠️ <b>Ошибка загрузки изображения</b>\n\n"
                        f"Пользователь: {callback.from_user.id}\n"
                        f"Блюдо: {dish_name}\n"
                        f"Backend: {backend}",
                        parse_mode="HTML"
                    )
                except:
                    pass
            
            return
        
        # Сохраняем в кеш
        await database.save_cached_image(
            dish_name, 
            recipe_hash, 
            image_url, 
            backend,
            len(image_data)
        )
        
        # Обновляем рецепт с URL изображения
        recipe_id = state_manager.get_last_saved_recipe_id(user_id)
        if recipe_id:
            await database.update_recipe_image(recipe_id, image_url)
        
        # Увеличиваем счётчик (только для не-админов)
        if not is_admin:
            await database.increment_image_count(user_id)
        
        # Отправляем
        await wait.delete()
        
        # Создаём BufferedInputFile для отправки
        photo = BufferedInputFile(image_data, filename=filename)
        await callback.message.answer_photo(
            photo,
            caption=f"🎨 <b>{dish_name}</b>",
            parse_mode="HTML"
        )
        
        logger.info(f"✅ Изображение отправлено: {dish_name} ({backend})")
        
    except Exception as e:
        await wait.edit_text(
            "❌ Произошла ошибка при генерации изображения.\n\n"
            "🔔 Об этом сообщено администратору."
        )
        logger.error(f"Критическая ошибка генерации изображения: {e}", exc_info=True)
        
        # Уведомляем админа
        for admin_id in ADMIN_IDS:
            try:
                await callback.bot.send_message(
                    admin_id,
                    f"⚠️ <b>Критическая ошибка генерации</b>\n\n"
                    f"Пользователь: {callback.from_user.id}\n"
                    f"Блюдо: {dish_name}\n"
                    f"Ошибка: {str(e)[:200]}",
                    parse_mode="HTML"
                )
            except:
                pass

# --- ИЗБРАННОЕ ---

async def handle_add_to_favorites(callback: CallbackQuery):
    """Кнопка '❤️ В избранное'"""
    user_id = callback.from_user.id
    
    # Извлекаем recipe_id из callback_data
    recipe_id = int(callback.data.split("_")[2])
    
    try:
        success = await database.mark_as_favorite(recipe_id)
        
        if success:
            # Убираем кнопку "В избранное" из клавиатуры
            current_keyboard = callback.message.reply_markup
            new_buttons = []
            
            if current_keyboard and current_keyboard.inline_keyboard:
                for row in current_keyboard.inline_keyboard:
                    new_row = [btn for btn in row if not btn.callback_data.startswith("fav_add_")]
                    if new_row:
                        new_buttons.append(new_row)
            
            new_kb = InlineKeyboardMarkup(inline_keyboard=new_buttons) if new_buttons else None
            
            try:
                await callback.message.edit_reply_markup(reply_markup=new_kb)
            except:
                pass
            
            await callback.answer("❤️ Добавлено в избранное!", show_alert=True)
            logger.info(f"❤️ Рецепт {recipe_id} добавлен в избранное пользователем {user_id}")
        else:
            await callback.answer("❌ Не удалось добавить в избранное")
            
    except Exception as e:
        logger.error(f"Ошибка добавления в избранное: {e}")
        await callback.answer("❌ Ошибка добавления в избранное")

async def handle_show_favorite(callback: CallbackQuery):
    """Показать рецепт из избранного"""
    recipe_id = int(callback.data.split("_")[1])
    
    try:
        recipe = await database.get_recipe_by_id(recipe_id)
        
        if not recipe:
            await callback.answer("❌ Рецепт не найден")
            return
        
        # Отправляем рецепт
        text = recipe['recipe_text']
        
        # Если есть изображение - отправляем с фото
        if recipe.get('image_url'):
            await callback.message.answer_photo(
                recipe['image_url'],
                caption=text[:1024],  # Telegram ограничение на caption
                parse_mode="HTML"
            )
            # Если текст длиннее - отправляем остаток отдельно
            if len(text) > 1024:
                await callback.message.answer(text, parse_mode="HTML")
        else:
            await callback.message.answer(text, reply_markup=get_hide_keyboard(), parse_mode="HTML")
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка показа избранного: {e}")
        await callback.answer("❌ Ошибка загрузки рецепта")

# --- АДМИНКА ---

async def handle_admin_stats(callback: CallbackQuery):
    """Админка: Статистика"""
    text = await admin_service.get_stats_message()
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    await callback.answer()

async def handle_admin_top_cooks(callback: CallbackQuery):
    """Админка: Топ-3 поваров"""
    text = await admin_service.get_top_cooks_message()
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    await callback.answer()

async def handle_admin_top_ingredients(callback: CallbackQuery):
    """Админка: Топ-10 продуктов"""
    text = await admin_service.get_top_ingredients_message(period='month')
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    await callback.answer()

async def handle_admin_top_dishes(callback: CallbackQuery):
    """Админка: Топ-5 блюд"""
    text = await admin_service.get_top_dishes_message()
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    await callback.answer()

async def handle_admin_random_fact(callback: CallbackQuery):
    """Админка: Случайный факт"""
    text = await admin_service.get_random_fact_message()
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    await callback.answer()

async def handle_admin_broadcast(callback: CallbackQuery):
    """Админка: Начало broadcast"""
    await callback.message.edit_text(
        "📢 <b>Режим Broadcast</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n\n"
        "⚠️ Для отмены отправьте /cancel",
        parse_mode="HTML"
    )
    
    # Устанавливаем состояние ожидания broadcast
    user_id = callback.from_user.id
    await state_manager.set_state(user_id, "awaiting_broadcast")
    await callback.answer()

async def handle_broadcast_message(message: Message):
    """Обработка сообщения для broadcast"""
    user_id = message.from_user.id
    
    # Проверяем права
    if str(user_id) not in ADMIN_IDS:
        return
    
    # Проверяем состояние
    if state_manager.get_state(user_id) != "awaiting_broadcast":
        return
    
    # Отменяем если /cancel
    if message.text and message.text.strip() == "/cancel":
        await state_manager.clear_state(user_id)
        await message.answer("❌ Broadcast отменён")
        return
    
    # Подтверждение
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить всем", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    await message.answer(
        "📢 <b>Подтверждение рассылки</b>\n\n"
        "Вы уверены, что хотите отправить это сообщение всем пользователям?",
        reply_markup=confirm_kb,
        parse_mode="HTML"
    )
    
    # Сохраняем текст broadcast в кеше
    state_manager._cache['broadcast_text'] = {user_id: message.text or message.caption}

async def handle_broadcast_confirm(callback: CallbackQuery):
    """Подтверждение broadcast"""
    user_id = callback.from_user.id
    
    # Получаем текст
    broadcast_text = state_manager._cache.get('broadcast_text', {}).get(user_id)
    
    if not broadcast_text:
        await callback.answer("❌ Текст не найден")
        return
    
    await callback.message.edit_text("📤 Начинаю рассылку...")
    
    try:
        # Получаем всех пользователей
        all_users = await database.get_all_user_ids()
        
        success_count = 0
        failed_count = 0
        
        for target_user_id in all_users:
            try:
                await callback.bot.send_message(
                    target_user_id,
                    f"📢 <b>Сообщение от администратора:</b>\n\n{broadcast_text}",
                    parse_mode="HTML"
                )
                success_count += 1
                await asyncio.sleep(0.05)  # Небольшая задержка между отправками
            except Exception as e:
                logger.warning(f"Не удалось отправить broadcast пользователю {target_user_id}: {e}")
                failed_count += 1
        
        # Отчёт
        await callback.message.edit_text(
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"📤 Успешно: {success_count}\n"
            f"❌ Ошибок: {failed_count}\n"
            f"👥 Всего: {len(all_users)}",
            parse_mode="HTML"
        )
        
        # Очищаем состояние
        await state_manager.clear_state(user_id)
        if user_id in state_manager._cache.get('broadcast_text', {}):
            del state_manager._cache['broadcast_text'][user_id]
        
    except Exception as e:
        logger.error(f"Ошибка broadcast: {e}")
        await callback.message.edit_text(f"❌ Ошибка рассылки: {e}")

async def handle_broadcast_cancel(callback: CallbackQuery):
    """Отмена broadcast"""
    user_id = callback.from_user.id
    await state_manager.clear_state(user_id)
    
    if user_id in state_manager._cache.get('broadcast_text', {}):
        del state_manager._cache['broadcast_text'][user_id]
    
    await callback.message.edit_text("❌ Рассылка отменена")
    await callback.answer()

# --- CALLBACK ОБРАБОТЧИКИ ---

async def handle_callback(callback: CallbackQuery):
    """Обработка всех callback-запросов"""
    user_id = callback.from_user.id
    data = callback.data
    
    # 1. Сброс
    if data == "restart":
        await state_manager.clear_session(user_id)
        await callback.message.answer("🗑 Список очищен. Жду продукты.")
        await callback.answer()
        return
    
    # 2. Очистка истории пользователя
    if data == "clear_my_history":
        try:
            async with database.pool.acquire() as conn:
                await conn.execute("DELETE FROM recipes WHERE user_id = $1", user_id)
            await callback.message.edit_text("✅ Ваша история рецептов очищена.")
        except Exception as e:
            logger.error(f"Ошибка очистки истории: {e}")
            await callback.message.edit_text("❌ Ошибка очистки истории.")
        await callback.answer()
        return

    # 3. Выбор: Добавить или Готовить
    if data == "action_add_more":
        await callback.message.answer("✏️ Напишите или продиктуйте, что добавить:")
        await callback.answer()
        return
    
    if data == "action_cook":
        await callback.message.delete()
        await start_category_flow(callback.message, user_id)
        await callback.answer()
        return

    # 4. Выбор категории
    if data.startswith("cat_"):
        category = data.split("_")[1]
        products = state_manager.get_products(user_id)
        await callback.message.delete()
        await show_dishes_for_category(callback.message, user_id, products, category)
        await callback.answer()
        return

    # 5. Назад к категориям
    if data == "back_to_categories":
        categories = state_manager.get_categories(user_id)
        if not categories:
            await callback.answer("Сессия истекла.")
            return
        
        await callback.message.delete()
        if len(categories) == 1:
            await callback.message.answer("Категория была одна.", 
                                        reply_markup=get_categories_keyboard(categories))
        else:
            await callback.message.answer("📂 <b>Выберите категорию:</b>", 
                                        reply_markup=get_categories_keyboard(categories), 
                                        parse_mode="HTML")
        await callback.answer()
        return

    # 6. Выбор блюда
    if data.startswith("dish_"):
        try:
            if data == "dish_all_mix":
                dishes = state_manager.get_generated_dishes(user_id)
                dish_name = " + ".join([d['name'] for d in dishes])
            else:
                index = int(data.split("_")[1])
                dish_name = state_manager.get_generated_dish(user_id, index)
            
            if not dish_name:
                await callback.answer("Меню устарело.")
                return
            await callback.answer("Готовлю...")
            await generate_and_send_recipe(callback.message, user_id, dish_name)
        except Exception as e:
            logger.error(f"Dish error: {e}")
        return

    # 7. Новый набор продуктов (вместо "Другой вариант")
    if data == "new_products_set":
        await state_manager.clear_session(user_id)
        await callback.message.answer(
            "🛒 <b>Новый набор продуктов</b>\n\n"
            "✏️ Напишите или продиктуйте список продуктов, с которых хотите начать.",
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # 8. Удаление сообщения
    if data == "delete_msg":
        await callback.message.delete()
        await callback.answer()
        return
    
    # 9. Генерация изображения
    if data == "gen_image":
        await handle_generate_image(callback)
        return
    
    # 10. Добавление в избранное
    if data.startswith("fav_add_"):
        await handle_add_to_favorites(callback)
        return
    
    # 11. Показ избранного
    if data.startswith("fav_") and not data.startswith("fav_add_"):
        await handle_show_favorite(callback)
        return
    
    # 12. Админка - статистика
    if data == "admin_stats":
        await handle_admin_stats(callback)
        return
    
    # 13. Админка - топ поваров
    if data == "admin_top_cooks":
        await handle_admin_top_cooks(callback)
        return
    
    # 14. Админка - топ продуктов
    if data == "admin_top_ingredients":
        await handle_admin_top_ingredients(callback)
        return
    
    # 15. Админка - топ блюд
    if data == "admin_top_dishes":
        await handle_admin_top_dishes(callback)
        return
    
    # 16. Админка - случайный факт
    if data == "admin_random_fact":
        await handle_admin_random_fact(callback)
        return
    
    # 17. Админка - broadcast
    if data == "admin_broadcast":
        await handle_admin_broadcast(callback)
        return
    
    # 18. Подтверждение broadcast
    if data == "broadcast_confirm":
        await handle_broadcast_confirm(callback)
        return
    
    # 19. Отмена broadcast
    if data == "broadcast_cancel":
        await handle_broadcast_cancel(callback)
        return

# --- РЕГИСТРАЦИЯ ХЭНДЛЕРОВ ---

def register_handlers(dp: Dispatcher):
    # Команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_author, Command("author"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_favorites, Command("favorites"))
    dp.message.register(cmd_admin, Command("admin"))
    
    # Запросы рецептов
    dp.message.register(handle_direct_recipe, F.text.lower().startswith("дай рецепт"))
    dp.message.register(handle_direct_recipe, F.text.lower().startswith("рецепт"))
    dp.message.register(handle_direct_recipe, F.text.lower().startswith("как приготовить"))
    
    # Broadcast (только для админов в состоянии awaiting_broadcast)
    dp.message.register(
        handle_broadcast_message,
        lambda msg: str(msg.from_user.id) in ADMIN_IDS and 
                    state_manager.get_state(msg.from_user.id) == "awaiting_broadcast"
    )
    
    # Контент
    dp.message.register(handle_voice, F.voice)
    dp.message.register(handle_text, F.text)
    
    # Callbacks
    dp.callback_query.register(handle_delete_msg, F.data == "delete_msg")
    dp.callback_query.register(handle_callback)
