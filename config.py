import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Groq
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")
GROQ_API_KEYS = [key.strip() for key in GROQ_API_KEYS if key.strip()]

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# Админы
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip()]

# Настройки
GROQ_MODEL = "llama-3.3-70b-versatile"  # Основная модель для текста
GROQ_MODEL_TEXT = "llama-3.3-70b-versatile"  # Явно для текстовых задач
GROQ_MODEL_AUDIO = "whisper-large-v3-turbo"  # Для транскрипции
MAX_HISTORY_MESSAGES = 8

# Лимиты
DAILY_IMAGE_LIMIT_NORMAL = 5
DAILY_IMAGE_LIMIT_ADMIN = -1

# Папки
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

PORT = int(os.getenv("PORT", "8080"))
