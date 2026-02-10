--- START OF FILE config.py ---

import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Groq (Считываем список ключей)
_keys_str = os.getenv("GROQ_API_KEYS", "")
GROQ_API_KEYS = [key.strip() for key in _keys_str.split(",") if key.strip()]

# Fallback: если список пуст, попробуем найти одиночный ключ
if not GROQ_API_KEYS:
    single_key = os.getenv("GROQ_API_KEY")
    if single_key:
        GROQ_API_KEYS = [single_key]

# Supabase / Postgres
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Админы
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip()]

# Настройки моделей Groq
GROQ_MODEL_TEXT = "llama-3.3-70b-versatile"
GROQ_MODEL_AUDIO = "whisper-large-v3-turbo"

# Настройки бота
MAX_HISTORY_MESSAGES = 8  # <--- Добавлено

# Папки
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

PORT = int(os.getenv("PORT", "8080"))
