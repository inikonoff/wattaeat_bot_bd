import asyncio
import os
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from config import TELEGRAM_TOKEN
from handlers import register_handlers
from state_manager import state_manager
from aiohttp import web
from database import db
from storage_service import storage_service

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# --- Веб-сервер для Render ---
async def health_check(request):
    return web.Response(text="Bot is running OK")

async def start_web_server():
    try:
        app = web.Application()
        app.router.add_get('/', health_check)
        app.router.add_get('/health', health_check)
        runner = web.AppRunner(app)
        await runner.setup()
        
        port = int(os.environ.get("PORT", 8080))
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info(f"✅ WEB SERVER STARTED ON PORT {port}")
    except Exception as e:
        logger.error(f"❌ Error starting web server: {e}")

# --- НАСТРОЙКА МЕНЮ БОТА ---
async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="🔄 Рестарт / новые продукты"),
        BotCommand(command="/author", description="👨‍💻 Автор бота"),
        BotCommand(command="/stats", description="📊 Статистика и история"),
        BotCommand(command="/favorites", description="❤️ Избранные рецепты"),
        BotCommand(command="/admin", description="🔧 Админка (только для админов)")
    ]
    try:
        await bot.set_my_commands(commands)
        logger.info("✅ Команды бота настроены")
    except Exception as e:
        logger.error(f"❌ Не удалось установить команды: {e}")

# --- ГЛАВНАЯ ФУНКЦИЯ ---
async def main():
    logger.info("🤖 Инициализация кулинарного бота с БД Supabase...")
    
    # 1. Инициализация базы данных
    try:
        await db.connect()
        logger.info("✅ Подключение к Supabase установлено")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка подключения к БД: {e}")
        logger.warning("⚠️  Бот запускается в режиме без БД")
    
    # 2. Инициализация StateManager
    try:
        await state_manager.initialize()
        logger.info("✅ StateManager инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации StateManager: {e}")
    
    # 3. Инициализация Storage (для изображений)
    try:
        await storage_service.initialize()
        logger.info("✅ Storage сервис инициализирован")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Storage: {e}")
        logger.warning("⚠️  Изображения не будут сохраняться")
    
    # 4. Запуск веб-сервера для Render
    await start_web_server()
    
    # 5. Регистрация обработчиков
    register_handlers(dp)
    logger.info("✅ Обработчики зарегистрированы")
    
    # 6. Настройка команд бота
    await setup_bot_commands(bot)
    
    logger.info("🚀 Запуск бота...")
    
    # 7. Удаляем вебхук и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка polling: {e}")
    finally:
        # Graceful shutdown
        logger.info("🔄 Завершение работы бота...")
        await state_manager.shutdown()
        await db.close()
        logger.info("👋 Бот завершил работу")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹ Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        sys.exit(1)