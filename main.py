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

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

async def health_check(request):
    return web.Response(text="Bot is running OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def periodic_cache_cleanup():
    """Периодическая очистка кэша каждые 30 минут"""
    while True:
        try:
            await asyncio.sleep(1800)  # 30 минут
            await state_manager.periodic_cleanup()
        except asyncio.CancelledError:
            logger.info("Периодическая очистка кэша остановлена")
            break
        except Exception as e:
            logger.error(f"Ошибка в periodic_cache_cleanup: {e}", exc_info=True)

async def main():
    logger.info("🚀 Запуск бота")
    
    # 1. БД и Хранилище
    await db.connect()
    await state_manager.initialize()
    
    # 2. Веб-сервер
    await start_web_server()
    
    # 3. Запуск периодической очистки кэша
    cleanup_task = asyncio.create_task(periodic_cache_cleanup())
    logger.info("✅ Периодическая очистка кэша запущена (каждые 30 мин)")
    
    # 4. Бот
    register_handlers(dp)
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())
