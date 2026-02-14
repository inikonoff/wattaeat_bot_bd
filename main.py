import asyncio
import os
import logging
import sys
import signal
from contextlib import asynccontextmanager
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web
from config import TELEGRAM_TOKEN
from handlers import register_handlers
from state_manager import state_manager
from database import db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger(__name__)

# Глобальные переменные
bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()
shutdown_event = asyncio.Event()


# ============================================================================
# ОБРАБОТКА СИГНАЛОВ (SIGTERM) ДЛЯ RENDER
# ============================================================================

def handle_sigterm(signum, frame):
    """Обработчик сигнала SIGTERM от Render"""
    logger.info("📡 Received SIGTERM signal, initiating graceful shutdown...")
    asyncio.create_task(trigger_shutdown())


async def trigger_shutdown():
    """Триггер для graceful shutdown"""
    shutdown_event.set()


# ============================================================================
# ВЕБ-СЕРВЕР ДЛЯ UPTIMEROBOT
# ============================================================================

async def health_check(request):
    """Health check endpoint для Render/UptimeRobot"""
    return web.json_response({
        "status": "healthy",
        "service": "culinary-bot",
        "timestamp": datetime.utcnow().isoformat()
    })


async def ping(request):
    """Простой ping endpoint"""
    return web.json_response({
        "pong": True,
        "timestamp": datetime.utcnow().isoformat()
    })


async def status(request):
    """Детальный статус бота"""
    try:
        bot_info = await bot.get_me()
        cache_stats = await state_manager.get_stats() if hasattr(state_manager, 'get_stats') else "N/A"
        
        return web.json_response({
            "status": "running",
            "bot": {
                "username": bot_info.username,
                "id": bot_info.id,
                "name": bot_info.first_name
            },
            "cache_stats": cache_stats,
            "database": "connected" if db and hasattr(db, 'pool') and db.pool else "disconnected",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Status check error: {e}")
        return web.json_response({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }, status=500)


async def start_web_server():
    """Запуск веб-сервера с несколькими эндпоинтами"""
    app = web.Application()
    
    # Регистрируем endpoints
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    app.router.add_get('/ping', ping)
    app.router.add_get('/status', status)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render сам устанавливает PORT
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"✅ Web server started on port {port}")
    logger.info(f"📌 Health check endpoints: /health, /ping, /status")
    return runner


# ============================================================================
# ПЕРИОДИЧЕСКИЕ ЗАДАЧИ
# ============================================================================

async def periodic_cache_cleanup():
    """Периодическая очистка кэша каждые 30 минут"""
    logger.info("🔄 Periodic cache cleanup task started")
    while True:
        try:
            await asyncio.sleep(1800)  # 30 минут
            logger.info("🧹 Running periodic cache cleanup...")
            await state_manager.periodic_cleanup()
            logger.info("✅ Cache cleanup completed")
        except asyncio.CancelledError:
            logger.info("🛑 Periodic cache cleanup stopped")
            break
        except Exception as e:
            logger.error(f"❌ Error in periodic_cache_cleanup: {e}", exc_info=True)


async def keep_alive_ping():
    """Самопинг для поддержания активности (каждые 5 минут)"""
    logger.info("🔄 Keep-alive ping task started")
    url = os.environ.get("RENDER_EXTERNAL_URL")
    
    if not url:
        logger.warning("⚠️ RENDER_EXTERNAL_URL not set, keep-alive ping disabled")
        return
    
    while True:
        try:
            await asyncio.sleep(300)  # 5 минут
            
            # Пингуем себя через разные endpoints
            endpoints = [f"{url}/ping", f"{url}/health"]
            
            for endpoint in endpoints:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(endpoint, timeout=5) as response:
                            if response.status == 200:
                                logger.debug(f"✅ Self-ping successful: {endpoint}")
                            else:
                                logger.warning(f"⚠️ Self-ping returned {response.status}: {endpoint}")
                except Exception as e:
                    logger.debug(f"Self-ping failed for {endpoint}: {e}")
                    
        except asyncio.CancelledError:
            logger.info("🛑 Keep-alive ping stopped")
            break
        except Exception as e:
            logger.error(f"❌ Error in keep_alive_ping: {e}")


# ============================================================================
# ОСНОВНАЯ ЛОГИКА
# ============================================================================

async def startup():
    """Запуск всех компонентов бота"""
    logger.info("🚀 Starting Culinary Bot...")
    
    try:
        # 1. Подключаемся к БД
        logger.info("📦 Connecting to database...")
        await db.connect()
        logger.info("✅ Database connected")
        
        # 2. Инициализируем хранилище состояний
        logger.info("🗃️ Initializing state manager...")
        await state_manager.initialize()
        logger.info("✅ State manager initialized")
        
        # 3. Регистрируем обработчики команд
        logger.info("🔧 Registering handlers...")
        register_handlers(dp)
        logger.info("✅ Handlers registered")
        
        # 4. Устанавливаем команды бота
        await setup_bot_commands()
        
        # 5. Удаляем вебхук (на всякий случай)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook deleted")
        
        logger.info("🎉 Bot started successfully!")
        
    except Exception as e:
        logger.error(f"❌ Startup error: {e}", exc_info=True)
        raise


async def setup_bot_commands():
    """Установка команд бота"""
    commands = [
        BotCommand(command="start", description="🚀 Запустить бота"),
        BotCommand(command="help", description="❓ Помощь"),
        BotCommand(command="recipe", description="📖 Рецепт дня"),
        BotCommand(command="search", description="🔍 Поиск рецептов"),
        BotCommand(command="categories", description="📂 Категории"),
        BotCommand(command="favorites", description="❤️ Избранное"),
    ]
    await bot.set_my_commands(commands)
    logger.info("✅ Bot commands set")


async def run_polling():
    """Запуск polling с обработкой завершения"""
    try:
        logger.info("📡 Starting polling...")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("🛑 Polling task cancelled")
    except Exception as e:
        logger.error(f"❌ Polling error: {e}", exc_info=True)
    finally:
        logger.info("📡 Polling stopped")


async def shutdown(web_runner):
    """Graceful shutdown всех компонентов"""
    logger.info("🛑 Shutting down Culinary Bot...")
    
    # Даём время на завершение текущих задач
    logger.info("⏳ Waiting for ongoing tasks to complete (up to 10 seconds)...")
    await asyncio.sleep(10)
    
    # Останавливаем веб-сервер
    if web_runner:
        logger.info("🛑 Stopping web server...")
        await web_runner.cleanup()
        logger.info("✅ Web server stopped")
    
    # Закрываем соединения с БД
    logger.info("🛑 Closing database connections...")
    await db.close()
    logger.info("✅ Database connections closed")
    
    # Закрываем сессию бота
    logger.info("🛑 Closing bot session...")
    await bot.session.close()
    logger.info("✅ Bot session closed")
    
    logger.info("👋 Goodbye!")


async def main():
    """Главная функция"""
    logger.info("=" * 50)
    logger.info("🤖 Culinary Bot Starting")
    logger.info("=" * 50)
    
    # Регистрируем обработчик SIGTERM
    signal.signal(signal.SIGTERM, handle_sigterm)
    logger.info("✅ SIGTERM handler registered")
    
    web_runner = None
    
    try:
        # Запускаем веб-сервер для UptimeRobot
        web_runner = await start_web_server()
        
        # Запускаем бота
        await startup()
        
        # Запускаем периодические задачи в фоне
        cleanup_task = asyncio.create_task(periodic_cache_cleanup())
        ping_task = asyncio.create_task(keep_alive_ping())
        
        logger.info("=" * 50)
        logger.info("✅ Bot is fully operational!")
        logger.info("=" * 50)
        
        # Запускаем polling (блокирующая операция)
        await run_polling()
        
    except Exception as e:
        logger.error(f"❌ Fatal error in main: {e}", exc_info=True)
        
    finally:
        # Останавливаем фоновые задачи
        if 'cleanup_task' in locals():
            cleanup_task.cancel()
        if 'ping_task' in locals():
            ping_task.cancel()
            
        # Graceful shutdown
        await shutdown(web_runner)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Unhandled exception: {e}", exc_info=True)
