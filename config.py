import os
from dotenv import load_dotenv

load_dotenv()

# API ключи
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Groq (поддержка нескольких ключей для fallback)
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", "")).split(",")
GROQ_API_KEYS = [key.strip() for key in GROQ_API_KEYS if key.strip()]  # Очистка
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else None  # Для совместимости
GROQ_CURRENT_KEY_INDEX = 0

# Replicate
REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY")

# Unsplash (опционально)
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

# Gemini (игнорируем пока)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# База данных Supabase (основная)
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL не найден в переменных окружения!")

# Supabase для картинок (fallback - второй аккаунт)
SUPABASE_IMAGES_URL = os.getenv("SUPABASE_IMAGES_URL")  # Опционально
SUPABASE_IMAGES_KEY = os.getenv("SUPABASE_IMAGES_KEY")  # Опционально

# Админы
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
ADMIN_IDS = [admin_id.strip() for admin_id in ADMIN_IDS if admin_id.strip()]

# Настройки
SPEECH_LANGUAGE = "ru-RU"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MAX_TOKENS = 2000

# Настройки изображений
IMAGE_QUALITY = int(os.getenv("IMAGE_QUALITY", "85"))  # Среднее качество
IMAGE_MAX_SIZE = 2048  # Максимальный размер стороны

# Папки
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

MAX_HISTORY_MESSAGES = 8

# Порт для Render
PORT = int(os.getenv("PORT", "8080"))