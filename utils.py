import os
import asyncio
import logging
from config import TEMP_DIR

logger = logging.getLogger(__name__)

class VoiceProcessor:
    """Заглушка для обратной совместимости - обработка голоса теперь в groq_service.py"""
    
    def __init__(self):
        logger.info("⚠️ VoiceProcessor не используется. Используйте groq_service.transcribe_voice()")
    
    async def process_voice(self, voice_file_path: str) -> str:
        """Заглушка для обратной совместимости"""
        logger.warning("⚠️ Используйте groq_service.transcribe_voice() вместо VoiceProcessor!")
        return "Для распознавания голоса используйте groq_service.transcribe_voice()"
