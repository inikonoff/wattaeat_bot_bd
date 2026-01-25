import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Hugging Face (Вместо Pollinations)
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

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
GROQ_MODEL = "llama-3.3-70b-versatile"
MAX_HISTORY_MESSAGES = 8
IMAGE_QUALITY = 85
IMAGE_MAX_SIZE = 1024  # Чуть меньше для стабильности HF

# Лимиты
DAILY_IMAGE_LIMIT_NORMAL = 5
DAILY_IMAGE_LIMIT_ADMIN = -1

# Карточки
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

# Шрифты (имена файлов)
FONT_BOLD = os.path.join(FONTS_DIR, "Roboto-Bold.ttf")
FONT_MEDIUM = os.path.join(FONTS_DIR, "Roboto-Medium.ttf")
FONT_REGULAR = os.path.join(FONTS_DIR, "Roboto-Regular.ttf")

PORT = int(os.getenv("PORT", "8080"))
