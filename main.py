import asyncio
import os
import logging
import sys
from aiogram import Bot, Dispatcher
from config import TELEGRAM_TOKEN
from handlers import register_handlers
from state_manager import state_manager
from aiohttp import web
from database import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
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

async def run_periodic_cleanup():
    """Фоновая задача для очистки старого кэша из памяти"""
    while True:
        await asyncio.sleep(3600)  # Запускаем раз в час
        await state_manager.periodic_cleanup()

async def main():
    logger.info("🚀 Запуск бота")
    
    # 1. Инициализация
    await state_manager.initialize()
    
    # 2. Запуск очистки памяти (важно без Redis!)
    asyncio.create_task(run_periodic_cleanup())
    
    # 3. Веб-сервер
    await start_web_server()
    
    # 4. Бот
    register_handlers(dp)
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    finally:
        await state_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
