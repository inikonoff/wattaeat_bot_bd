import os
import asyncio
import logging
from pydub import AudioSegment
from config import TEMP_DIR

logger = logging.getLogger(__name__)

class VoiceProcessor:
    """Устаревший класс для обработки голоса (оставлен для совместимости)"""
    
    def __init__(self):
        logger.warning("⚠️ VoiceProcessor устарел! Используйте groq_service.transcribe_voice()")
    
    async def process_voice(self, voice_file_path: str) -> str:
        """Заглушка для обратной совместимости"""
        logger.warning("⚠️ Используйте groq_service.transcribe_voice() вместо VoiceProcessor!")
        return "Голосовая обработка перемещена в groq_service.py"
