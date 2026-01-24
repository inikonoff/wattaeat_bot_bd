import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY")

# Groq (несколько ключей для ротации)
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")
GROQ_API_KEYS = [key.strip() for key in GROQ_API_KEYS if key.strip()]

# Supabase (аккаунт 1 - основной)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# Supabase (аккаунт 2 - резервный, только storage)
SUPABASE_IMAGES_URL = os.getenv("SUPABASE_IMAGES_URL")
SUPABASE_IMAGES_KEY = os.getenv("SUPABASE_IMAGES_KEY")

# Админы
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in ADMIN_IDS if admin_id.strip()]

# Настройки
SPEECH_LANGUAGE = "ru-RU"
GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_HISTORY_MESSAGES = 8
IMAGE_QUALITY = 85
IMAGE_MAX_SIZE = 2048

# Лимиты
DAILY_IMAGE_LIMIT_NORMAL = 5
DAILY_IMAGE_LIMIT_ADMIN = -1  # безлимит

# Карточки рецептов
CARD_WIDTH = 1080
CARD_HEIGHT = 1920
CARD_BG_COLOR = "#FFFFFF"
CARD_ACCENT_COLOR = "#FF6B6B"
CARD_TEXT_COLOR = "#2D3436"
CARD_SECONDARY_COLOR = "#95A5A6"

# Папки
TEMP_DIR = "temp"
FONTS_DIR = "fonts"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)

# Шрифты
FONT_BOLD = os.path.join(FONTS_DIR, "Roboto-Bold.ttf")
FONT_MEDIUM = os.path.join(FONTS_DIR, "Roboto-Medium.ttf")
FONT_REGULAR = os.path.join(FONTS_DIR, "Roboto-Regular.ttf")

# Веб-сервер для Render
PORT = int(os.getenv("PORT", "8080"))
