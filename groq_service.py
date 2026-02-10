# ... (импорты те же)

# --- НОВАЯ ФУНКЦИЯ ВАЛИДАЦИИ ---
def normalize_ingredients(text: str) -> str:
    """
    Превращает 'банан киви яблоко' в 'банан, киви, яблоко'.
    Не трогает, если уже есть запятые.
    """
    text = text.strip()
    # Если запятых нет, но есть пробелы и длина слов > 2
    if ',' not in text and ' ' in text:
        # Простая эвристика: заменяем пробелы на запятые
        # Можно усложнить, чтобы не бить "сметана" на "сметана, ", но для начала так
        # Лучше: заменять пробелы, если слова длинные
        words = text.split()
        if len(words) > 1:
            return ", ".join(words)
    return text

# ... (остальной код)

async def process_products_input(message: Message, user_id: int, products_text: str):
    """Обработка списка продуктов с валидацией"""
    try:
        # ВАЛИДАЦИЯ И НОРМАЛИЗАЦИЯ
        normalized_products = normalize_ingredients(products_text)
        
        await state_manager.add_products(user_id, normalized_products)
        current = await state_manager.get_products(user_id)
        
        # Если была нормализация, покажем пользователю, как мы поняли
        msg_text = f"✅ <b>Продукты сохранены:</b> {current}"
        if normalized_products != products_text:
            msg_text += f"\n<i>(Я добавил запятые для разделения)</i>"
            
        await message.answer(
            f"{msg_text}\n\nЧто делаем дальше?",
            reply_markup=get_confirmation_keyboard(), 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error processing products: {e}", exc_info=True)
        await message.answer("❌ Ошибка обработки продуктов")

# ... (остальной код handlers.py без изменений, кроме импорта normalize_ingredients если нужно)
